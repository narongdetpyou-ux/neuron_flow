"""Explicit, bounded adapters for globally used document storage services.

No connector runs on import or stores credentials. HTTP hosts are fixed, HTTPS
redirects are refused, and provider response bodies never appear in errors.
"""

import csv
import hashlib
import io
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .document_input import bounded_bytes, optional_module, table_to_csv


PROVIDERS = ("google-drive", "google-sheets", "dropbox", "s3")
HOSTS = {"www.googleapis.com", "sheets.googleapis.com", "content.dropboxapi.com"}


class ConnectorError(ValueError):
    def __init__(self, message, *, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _token(variable):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
        raise ConnectorError("CREDENTIAL_ENV: expected an environment variable name")
    value = os.environ.get(variable)
    if not value or any(character.isspace() for character in value):
        raise ConnectorError(f"CREDENTIAL_MISSING: set {variable} to an OAuth access token")
    return value


class HttpTransport:
    def request(self, method, url, *, token, body=None, headers=None):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in HOSTS:
            raise ConnectorError("ENDPOINT: HTTPS provider endpoint required")
        request = Request(url, data=body, method=method, headers={
            **(headers or {}), "Authorization": "Bearer " + token,
            "User-Agent": "NeuronFlow-document-adapter/1",
        })
        try:
            with build_opener(_NoRedirect()).open(request, timeout=30) as response:
                return bounded_bytes(response.read(16 * 1024 * 1024 + 1))
        except HTTPError as exc:
            exc.close()
            raise ConnectorError(f"PROVIDER_HTTP: status {exc.code}", status=exc.code,
                                 retryable=exc.code == 429 or 500 <= exc.code <= 599) from None
        except (URLError, TimeoutError, OSError):
            raise ConnectorError("PROVIDER_NETWORK: request failed or timed out", retryable=True) from None


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ConnectorError("RESOURCE_ID: supply a provider ID, not a share URL")
    return value


def _json_response(data):
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise ConnectorError("PROVIDER_RESPONSE: invalid JSON") from None
    if not isinstance(result, dict):
        raise ConnectorError("PROVIDER_RESPONSE: expected an object")
    return result


def fetch_source(provider, resource, *, token_env=None, cell_range=None, bucket=None,
                 version_id=None, transport=None, s3_client=None):
    """Download one explicitly selected resource; return bytes and provenance.

    Google Sheets uses FORMULA rendering so formulas can be refused, rather
    than silently trusting a stale cached or calculated financial value.
    """
    if provider not in PROVIDERS:
        raise ConnectorError("PROVIDER: choose " + ", ".join(PROVIDERS))
    transport = transport or HttpTransport()
    metadata = {"provider": provider, "resource": resource}
    if provider == "s3":
        if not bucket or not resource:
            raise ConnectorError("S3_RESOURCE: bucket and object key are required")
        arguments = {"Bucket": bucket, "Key": resource}
        if version_id:
            arguments["VersionId"] = version_id
        try:
            if s3_client is None:
                boto3 = optional_module("boto3", "s3")
                config = optional_module("botocore.config", "s3").Config
                s3_client = boto3.client("s3", config=config(connect_timeout=10, read_timeout=30,
                                                           retries={"total_max_attempts": 1}))
            response = s3_client.get_object(**arguments)
            stream = response["Body"]
            try:
                data = bounded_bytes(stream.read(16 * 1024 * 1024 + 1))
            finally:
                stream.close()
        except ValueError:
            raise
        except Exception:
            raise ConnectorError("S3_DOWNLOAD: check credentials, bucket, key and permissions") from None
        metadata.update(bucket=bucket, version_id=response.get("VersionId"), etag=response.get("ETag"))
    else:
        token = _token(token_env or ("DROPBOX_ACCESS_TOKEN" if provider == "dropbox" else "GOOGLE_ACCESS_TOKEN"))
        if provider == "google-drive":
            url = "https://www.googleapis.com/drive/v3/files/" + _identifier(resource)
            data = transport.request("GET", url + "?alt=media&supportsAllDrives=true", token=token)
        elif provider == "dropbox":
            if not resource.startswith(("/", "id:")):
                raise ConnectorError("DROPBOX_PATH: use an absolute Dropbox path or id: identifier")
            data = transport.request("POST", "https://content.dropboxapi.com/2/files/download", token=token,
                                     headers={"Dropbox-API-Arg": json.dumps({"path": resource}, ensure_ascii=True)})
        else:
            if not cell_range or len(cell_range) > 500:
                raise ConnectorError("SHEETS_RANGE: an explicit A1 range is required")
            url = ("https://sheets.googleapis.com/v4/spreadsheets/" + _identifier(resource)
                   + "/values/" + quote(cell_range, safe=""))
            response = _json_response(transport.request(
                "GET", url + "?valueRenderOption=FORMULA&majorDimension=ROWS", token=token))
            rows = response.get("values", [])
            if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
                raise ConnectorError("PROVIDER_RESPONSE: expected rows")
            if any(isinstance(cell, str) and cell.startswith("=") for row in rows for cell in row):
                raise ConnectorError("SHEETS_FORMULA: use a values-only source range")
            # Sheets omits trailing empty cells, which must remain visible to
            # the existing financial validator rather than changing row width.
            width = len(rows[0]) if rows else 0
            data = table_to_csv([row + [""] * max(0, width - len(row)) for row in rows])
            metadata.update(cell_range=cell_range, returned_range=response.get("range"),
                            representation="values-only CSV snapshot")
    bounded_bytes(data)
    metadata["sha256"] = hashlib.sha256(data).hexdigest()
    return data, metadata


def publish_sheets(source, spreadsheet_id, cell_range, *, token_env="GOOGLE_ACCESS_TOKEN", transport=None):
    """Overwrite an explicitly sized range with literal CSV strings (no append).

    A repeated request to the same range has the same effect. This is a separate
    user-invoked operation, with no implied cross-service transaction guarantee.
    """
    bounded_bytes(source)
    rows = list(csv.reader(io.StringIO(source.decode("utf-8-sig"), newline=""), strict=True))
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ConnectorError("SHEETS_TABLE: non-empty rectangular CSV required")
    # Require a finite range of exactly the data size to avoid stale trailing
    # rows or silently writing into a larger range than the caller specified.
    match = re.fullmatch(r"(?:'[^']+(?:''[^']*)*'|[A-Za-z0-9_ ]+)!([A-Z]+)([1-9][0-9]*):([A-Z]+)([1-9][0-9]*)", cell_range)
    if not match:
        raise ConnectorError("SHEETS_RANGE: use a finite sheet-qualified range, e.g. Report!A1:G3")
    def column(value):
        result = 0
        for character in value:
            result = result * 26 + ord(character) - ord("A") + 1
        return result
    start_col, start_row, end_col, end_row = match.groups()
    if (int(end_row) - int(start_row) + 1 != len(rows)
            or column(end_col) - column(start_col) + 1 != len(rows[0])):
        raise ConnectorError("SHEETS_RANGE: range dimensions must exactly match CSV rows and columns")
    token = _token(token_env)
    url = ("https://sheets.googleapis.com/v4/spreadsheets/" + _identifier(spreadsheet_id)
           + "/values/" + quote(cell_range, safe="") + "?" + urlencode({"valueInputOption": "RAW"}))
    data = json.dumps({"range": cell_range, "majorDimension": "ROWS", "values": rows},
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    bounded_bytes(data)
    response = _json_response((transport or HttpTransport()).request(
        "PUT", url, token=token, body=data, headers={"Content-Type": "application/json"}))
    if response.get("updatedCells") != len(rows) * len(rows[0]):
        raise ConnectorError("SHEETS_CONFIRMATION: unexpected updated cell count; inspect destination before retrying")
    return {"provider": "google-sheets", "spreadsheet_id": spreadsheet_id,
            "range": cell_range, "source_sha256": hashlib.sha256(source).hexdigest(),
            "updated_cells": response["updatedCells"], "status": "PUBLISHED"}
