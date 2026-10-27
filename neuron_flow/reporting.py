"""Deterministic, traceable batch artifacts with verified local delivery.

The caller freezes its payload before delivery and stores the receipt afterward.
A crash can leave a subset of identical artifacts; a repeated delivery only
creates missing files. Existing files are never overwritten, including races
between preflight and publication.
"""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile

from .csv_input import CsvInputError, read_csv_bytes


SUMMARY_FIELDS = ("document_id", "document_status", "declared_total", "computed_total",
                  "difference", "error_count", "source_rows", "engine_status")
MONEY = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
SIGNED_MONEY = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]{2}")


class ReportConflict(ValueError):
    """Artifact content or provenance conflicts with the frozen batch payload."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _same(actual, expected):
    # JSON encoding distinguishes bool/int and int/float, unlike Python equality.
    return _json(actual) == _json(expected)


def _money(cents):
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{value // 100}.{value % 100:02d}"


def _cents(value, *, signed=False):
    pattern = SIGNED_MONEY if signed else MONEY
    if (not isinstance(value, str) or not pattern.fullmatch(value)
            or value == "-0.00"):
        raise ReportConflict("Report money must be canonical decimal strings, never floats")
    negative = value.startswith("-")
    whole, fraction = value.lstrip("-").split(".")
    result = int(whole) * 100 + int(fraction)
    return -result if negative else result


def _raw_cents(value, digits):
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9]{{1,{digits}}}(\.[0-9]{{1,2}})?", value):
        raise ReportConflict("Certified money does not match valid source fields")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def _source_amounts(rows):
    total, declared = 0, None
    seen = set()
    for row in rows:
        fields = row["fields"]
        if row["errors"] or fields["currency"] != "THB":
            raise ReportConflict("Certified document contains source row errors or unsupported currency")
        item = fields["item_id"]
        description = fields["description"]
        if (not item.strip() or len(item) > 500 or item.strip() in seen
                or not description.strip() or len(description) > 500):
            raise ReportConflict("Certified document contains invalid or duplicate source text")
        seen.add(item.strip())
        quantity = fields["quantity"]
        if not re.fullmatch(r"[0-9]{1,7}", quantity) or not 1 <= int(quantity) <= 1_000_000:
            raise ReportConflict("Certified document contains invalid source quantity")
        price = _raw_cents(fields["unit_price"], 13)
        if price > 10 ** 14:
            raise ReportConflict("Certified document contains source price outside its bound")
        amount = _raw_cents(fields["declared_total"], 23)
        if amount > 10 ** 24 or declared is not None and amount != declared:
            raise ReportConflict("Certified document contains conflicting or out-of-range declared totals")
        declared = amount
        total += int(quantity) * price
    return total, declared


def _validate_payload(payload, source):
    if not isinstance(payload, dict) or not isinstance(source, bytes):
        raise ReportConflict("Delivery requires a frozen payload and original source bytes")
    try:
        _json(payload)
        if payload["status"] != "PROCESSED":
            raise ReportConflict("Only a frozen PROCESSED payload can be delivered")
        parsed = read_csv_bytes(source)
        if payload["source_sha256"] != parsed["source_sha256"]:
            raise ReportConflict("Source SHA-256 differs from the frozen payload")
        if type(payload["input_rows"]) is not int or payload["input_rows"] != parsed["input_rows"]:
            raise ReportConflict("Input row count differs from the source")
        if not _same(payload["ungrouped_rows"], parsed["ungrouped_rows"]):
            raise ReportConflict("Ungrouped rows differ from the source")
        documents = payload["documents"]
        if not isinstance(documents, list):
            raise ReportConflict("Document results must be a list")
        if [doc["document_id"] for doc in documents] != [doc["document_id"] for doc in parsed["documents"]]:
            raise ReportConflict("Document order or identifiers differ from the source")
        if payload["currency"] != "THB":
            raise ReportConflict("Batch currency must be THB")
        counts = {"documents": len(documents), "VALID": 0, "INVALID": 0, "ERROR": 0}
        certified = 0
        partition = [row["source_row"] for row in parsed["ungrouped_rows"]]
        for document, original in zip(documents, parsed["documents"]):
            rows = original["rows"]
            if not _same(document["source_records"], rows):
                raise ReportConflict("Document source records differ from original CSV values")
            source_rows = [row["source_row"] for row in rows]
            if not _same(document["source_rows"], source_rows):
                raise ReportConflict("Document source row mapping differs from original CSV records")
            partition.extend(source_rows)
            status = document["document_status"]
            if status not in {"VALID", "INVALID", "ERROR"}:
                raise ReportConflict("Unknown document status")
            counts[status] += 1
            errors = document["errors"]
            if not isinstance(errors, list) or (status != "VALID" and not errors):
                raise ReportConflict("Invalid/error documents require explicit errors")
            for error in errors:
                if (not isinstance(error, dict) or type(error["row_number"]) is not int
                        or error["row_number"] not in source_rows
                        or not isinstance(error["field"], str) or not isinstance(error["reason_code"], str)
                        or "expected" not in error or "actual" not in error):
                    raise ReportConflict("Document error cannot be traced to a source record")
            if document["declared_total"] is not None:
                _cents(document["declared_total"])
            if document["computed_total"] is not None:
                _cents(document["computed_total"])
            if document["difference"] is not None:
                _cents(document["difference"], signed=True)
            if status == "VALID":
                if errors or document["engine_status"] != "SUCCEEDED":
                    raise ReportConflict("A certified document must have succeeded with no errors")
                total, declared = _source_amounts(rows)
                if (document["computed_total"] != _money(total)
                        or document["declared_total"] != _money(declared)
                        or total != declared or document["difference"] != "0.00"):
                    raise ReportConflict("Certified document totals differ from source arithmetic")
                certified += total
            elif status == "ERROR":
                if document["computed_total"] is not None or document["difference"] is not None:
                    raise ReportConflict("An engine error cannot certify a computed amount")
            elif document["computed_total"] is not None:
                if not any(error["reason_code"] == "TOTAL_MISMATCH" for error in errors):
                    raise ReportConflict("Invalid source data cannot certify computed amounts")
                total, declared = _source_amounts(rows)
                if (total == declared or document["computed_total"] != _money(total)
                        or document["declared_total"] != _money(declared)
                        or document["difference"] != _money(total - declared)):
                    raise ReportConflict("Mismatch evidence differs from source arithmetic")
            elif document["difference"] is not None:
                raise ReportConflict("Uncomputed invalid document has a difference")
            if not isinstance(document["engine_status"], str):
                raise ReportConflict("Missing engine status")
        if (len(partition) != parsed["input_rows"] or len(partition) != len(set(partition))):
            raise ReportConflict("Input records are lost or assigned more than once")
        if not _same(payload["counts"], counts):
            raise ReportConflict("Batch document counts do not equal VALID + INVALID + ERROR")
        if payload["certified_total"] != _money(certified):
            raise ReportConflict("Certified total must count only VALID document totals")
    except ReportConflict:
        raise
    except (CsvInputError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ReportConflict(f"Invalid frozen report payload: {exc}") from exc


def _summary_rows(payload):
    return [{"document_id": document["document_id"],
             "document_status": document["document_status"],
             "declared_total": document["declared_total"] or "",
             "computed_total": document["computed_total"] or "",
             "difference": document["difference"] or "",
             "error_count": str(len(document["errors"])),
             "source_rows": json.dumps(document["source_rows"], separators=(",", ":")),
             "engine_status": document["engine_status"]}
            for document in payload["documents"]]


class BatchTerminal:
    """Deliver three artifacts in one fixed, caller-selected batch directory."""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)

    def _preflight(self, artifacts):
        for name, expected in artifacts.items():
            path = self.output_dir / name
            if path.is_symlink():
                raise ReportConflict(f"Existing artifact is a symlink: {name}")
            try:
                existing = path.read_bytes()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ReportConflict(f"Existing artifact is unreadable: {name}") from exc
            if existing != expected:
                raise ReportConflict(f"Existing artifact differs; preserving it: {name}")

    def _readback(self, artifacts, payload, summary):
        receipts = {}
        for name, expected in artifacts.items():
            path = self.output_dir / name
            if path.is_symlink():
                raise ReportConflict(f"Artifact became a symlink during delivery: {name}")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if (data != expected or len(data) != len(expected)
                    or digest != hashlib.sha256(expected).hexdigest()):
                raise ReportConflict(f"Artifact content/SHA-256 read-back failed: {name}")
            if name == "summary.csv":
                reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
                values = list(reader)
                if reader.fieldnames != list(SUMMARY_FIELDS) or not _same(values, summary):
                    raise ReportConflict("Summary CSV read-back differs from document results")
            elif name == "details.json":
                if not _same(json.loads(data), payload):
                    raise ReportConflict("Details JSON read-back differs from the frozen payload")
            else:
                if read_csv_bytes(data)["source_sha256"] != payload["source_sha256"]:
                    raise ReportConflict("Source read-back differs from original provenance")
            receipts[name] = {"path": str(path.resolve()), "sha256": digest, "bytes": len(data)}
        return {"artifacts": receipts}

    def deliver(self, payload, source):
        """Validate and preflight everything, then publish missing files only."""
        _validate_payload(payload, source)
        summary = _summary_rows(payload)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
        artifacts = {
            "summary.csv": stream.getvalue().encode("utf-8"),
            "details.json": (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                        indent=2, allow_nan=False) + "\n").encode("utf-8"),
            "source.csv": source,
        }
        # Do not write even the first new artifact when a later file conflicts.
        self._preflight(artifacts)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary = {}
        try:
            for name, data in artifacts.items():
                if (self.output_dir / name).exists():
                    continue
                descriptor, path = tempfile.mkstemp(prefix=".batch-report-", dir=self.output_dir)
                temporary[name] = Path(path)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            for name, path in temporary.items():
                target = self.output_dir / name
                try:
                    # link() publishes a complete inode atomically and never
                    # overwrites a file created after the preflight check.
                    os.link(path, target)
                except FileExistsError:
                    if target.is_symlink() or target.read_bytes() != artifacts[name]:
                        raise ReportConflict(f"Artifact appeared with conflicting content: {name}")
                path.unlink()
            if os.name != "nt":
                directory = os.open(self.output_dir, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            return self._readback(artifacts, payload, summary)
        finally:
            for path in temporary.values():
                path.unlink(missing_ok=True)
