"""Provider API contracts and network failures without touching live accounts."""

import io
import json
import os
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import Mock, patch

from neuron_flow import connectors
from neuron_flow.document_input import DocumentInputError
from tests.document_fixtures import CSV, PURCHASE


class Transport:
    def __init__(self, response=CSV):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


@patch.dict(os.environ, {"GOOGLE_ACCESS_TOKEN": "synthetic-google-token", "DROPBOX_ACCESS_TOKEN": "synthetic-dropbox-token"})
class ProviderTests(unittest.TestCase):
    def test_drive_and_dropbox_use_documented_hosts_and_header_encoding(self):
        for provider, resource in (("google-drive", "file_123"), ("dropbox", "/ใบเสร็จ.pdf"), ("dropbox", "id:abc")):
            with self.subTest(provider=provider):
                transport = Transport()
                data, provenance = connectors.fetch_source(provider, resource, transport=transport)
                self.assertEqual(data, CSV)
                self.assertEqual(provenance["provider"], provider)
                self.assertNotIn("token", json.dumps(provenance))
                method, url, options = transport.calls[0]
                if provider == "google-drive":
                    self.assertEqual(method, "GET")
                    self.assertIn("?alt=media&supportsAllDrives=true", url)
                else:
                    self.assertEqual((method, url), ("POST", "https://content.dropboxapi.com/2/files/download"))
                    header = options["headers"]["Dropbox-API-Arg"]
                    self.assertTrue(header.isascii())
                    self.assertEqual(json.loads(header)["path"], resource)

    def test_sheets_snapshot_pads_trailing_empty_cells_and_refuses_formulas(self):
        rows = [list(PURCHASE), list(PURCHASE.values()), list(PURCHASE.values())[:-1]]
        transport = Transport(json.dumps({"values": rows, "range": "Purchases!A1:G3"}).encode())
        data, metadata = connectors.fetch_source("google-sheets", "sheet_123", cell_range="Purchases!A1:G3", transport=transport)
        self.assertIn(b",25.00,\n", data)
        self.assertEqual(metadata["returned_range"], "Purchases!A1:G3")
        self.assertIn("valueRenderOption=FORMULA", transport.calls[0][1])
        self.assertIn("Purchases%21A1%3AG3", transport.calls[0][1])
        for payload, code in (({"values": "no"}, "PROVIDER_RESPONSE"),
                              ({"values": [None]}, "PROVIDER_RESPONSE"),
                              ({"values": [list(PURCHASE), ["=1+1"]]}, "SHEETS_FORMULA"),
                              ({}, "Invalid CSV header")):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, code):
                connectors.fetch_source("google-sheets", "sheet", cell_range="A1:G3", transport=Transport(json.dumps(payload).encode()))

    def test_invalid_setup_never_calls_provider_and_errors_never_reveal_tokens(self):
        for provider, resource, options, code in (
            ("unknown", "id", {}, "PROVIDER"),
            ("google-drive", "https://evil.example/file", {}, "RESOURCE_ID"),
            ("dropbox", "relative/file", {}, "DROPBOX_PATH"),
            ("google-sheets", "sheet", {}, "SHEETS_RANGE"),
            ("s3", "file", {}, "S3_RESOURCE"),
            ("google-drive", "file", {"token_env": "not a variable"}, "CREDENTIAL_ENV"),
            ("google-drive", "file", {"token_env": "NEURON_MISSING_TOKEN"}, "CREDENTIAL_MISSING"),
        ):
            transport = Transport()
            with self.subTest(provider=provider, code=code), self.assertRaisesRegex(ValueError, code) as caught:
                connectors.fetch_source(provider, resource, transport=transport, **options)
            self.assertEqual(transport.calls, [])
            self.assertNotIn("synthetic-google-token", str(caught.exception))
        with patch.dict(os.environ, {"BAD_TOKEN": "bad\ntoken"}), self.assertRaisesRegex(ValueError, "CREDENTIAL_MISSING"):
            connectors._token("BAD_TOKEN")
        for data in (b"bad", b"[]", b"\xff"):
            with self.assertRaisesRegex(ValueError, "PROVIDER_RESPONSE"):
                connectors._json_response(data)

    def test_sheets_export_is_fixed_range_raw_and_repeatable(self):
        transport = Transport(b'{"updatedCells":14}')
        first = connectors.publish_sheets(CSV, "spreadsheet", "'My Report'!A1:G2", transport=transport)
        second = connectors.publish_sheets(CSV, "spreadsheet", "'My Report'!A1:G2", transport=transport)
        self.assertEqual(first, second)
        self.assertEqual(transport.calls[0], transport.calls[1])
        method, url, kwargs = transport.calls[0]
        self.assertEqual(method, "PUT")
        self.assertIn("valueInputOption=RAW", url)
        self.assertEqual(json.loads(kwargs["body"])["values"][1][4], "12.50")
        self.assertEqual(first["updated_cells"], 14)
        # Formula-like text remains a literal string at the provider.
        connectors.publish_sheets(CSV.replace(b"Notebook", b"=SUM(A1:A2)"), "spreadsheet", "Report!A1:G2", transport=transport)
        self.assertIn(b"=SUM(A1:A2)", transport.calls[-1][2]["body"])

    def test_export_rejects_malformed_table_range_and_unconfirmed_write(self):
        for source, cell_range, code in (
            (b"", "Report!A1:G2", "SHEETS_TABLE"),
            (b"A,B\n1\n", "Report!A1:G2", "SHEETS_TABLE"),
            (CSV, "Report!A1", "SHEETS_RANGE"),
            (CSV, "Report!A1:G9", "SHEETS_RANGE"),
            (CSV, "Report!A1:F2", "SHEETS_RANGE"),
        ):
            with self.subTest(code=code, cell_range=cell_range), self.assertRaisesRegex(ValueError, code):
                connectors.publish_sheets(source, "sheet", cell_range, transport=Transport())
        with self.assertRaisesRegex(ValueError, "SHEETS_CONFIRMATION"):
            connectors.publish_sheets(CSV, "sheet", "Report!A1:G2", transport=Transport(b"{}"))


class S3Tests(unittest.TestCase):
    def test_bounded_download_pins_version_and_always_closes_body(self):
        body = io.BytesIO(CSV)
        client = Mock()
        client.get_object.return_value = {"Body": body, "VersionId": "v1", "ETag": '"opaque-etag"'}
        data, metadata = connectors.fetch_source("s3", "folder/source.csv", bucket="example", version_id="v1", s3_client=client)
        self.assertEqual(data, CSV)
        client.get_object.assert_called_once_with(Bucket="example", Key="folder/source.csv", VersionId="v1")
        self.assertTrue(body.closed)
        self.assertEqual(metadata["version_id"], "v1")
        # ETag is provenance, never substituted for a content SHA-256.
        self.assertNotEqual(metadata["sha256"], metadata["etag"])

    def test_s3_sdk_initialization_and_sanitized_failures(self):
        body = io.BytesIO(CSV)
        client = Mock()
        client.get_object.return_value = {"Body": body}
        boto3 = Mock()
        boto3.client.return_value = client
        config = Mock()
        with patch.object(connectors, "optional_module", side_effect=[boto3, config]):
            data, _ = connectors.fetch_source("s3", "key", bucket="bucket")
        self.assertEqual(data, CSV)
        self.assertEqual(boto3.client.call_args.args, ("s3",))
        client.get_object.side_effect = RuntimeError("secret-provider-response")
        with self.assertRaisesRegex(ValueError, "S3_DOWNLOAD") as caught:
            connectors.fetch_source("s3", "key", bucket="bucket", s3_client=client)
        self.assertNotIn("secret", str(caught.exception))
        client.get_object.side_effect = None
        body = io.BytesIO(b"too big")
        client.get_object.return_value = {"Body": body}
        with patch.object(connectors, "bounded_bytes", side_effect=DocumentInputError("SOURCE_LIMIT")), self.assertRaisesRegex(ValueError, "SOURCE_LIMIT"):
            connectors.fetch_source("s3", "key", bucket="bucket", s3_client=client)
        self.assertTrue(body.closed)


class HttpTests(unittest.TestCase):
    def test_success_uses_tls_bearer_token_bounded_read_and_timeout(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock()
        response.read.return_value = CSV
        opener = Mock()
        opener.open.return_value = response
        with patch.object(connectors, "build_opener", return_value=opener):
            self.assertEqual(connectors.HttpTransport().request("GET", "https://www.googleapis.com/test", token="synthetic"), CSV)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)
        response.read.assert_called_once_with(16 * 1024 * 1024 + 1)
        self.assertIsNone(connectors._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example"))

    def test_redirect_status_auth_rate_limit_timeout_and_network_are_sanitized(self):
        for code in (302, 401, 403, 404, 429, 503):
            error = HTTPError("https://provider", code, "secret response", {}, io.BytesIO(b"secret"))
            with patch.object(connectors, "build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.subTest(code=code), self.assertRaises(connectors.ConnectorError) as caught:
                    connectors.HttpTransport().request("GET", "https://www.googleapis.com/test", token="secret")
            self.assertEqual(caught.exception.status, code)
            self.assertEqual(caught.exception.retryable, code in (429, 503))
            self.assertNotIn("secret", str(caught.exception))
        for error in (URLError("secret"), TimeoutError("secret"), OSError("secret")):
            with patch.object(connectors, "build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(connectors.ConnectorError) as caught:
                    connectors.HttpTransport().request("GET", "https://www.googleapis.com/test", token="secret")
            self.assertTrue(caught.exception.retryable)
        for url in ("http://www.googleapis.com/test", "https://evil.example", "https://www.googleapis.com:443/test"):
            with self.assertRaisesRegex(ValueError, "ENDPOINT"):
                connectors.HttpTransport().request("GET", url, token="secret")
