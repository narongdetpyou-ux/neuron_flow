"""Lossless CSV record grouping for the versioned purchase input contract.

Rows retain their original field values and physical starting line number.
Data errors belong to a document (or the ungrouped-row list); malformed file
encoding, syntax and headers reject the file before any work is submitted.
"""

import csv
from collections import Counter
import hashlib
import io
from pathlib import Path


FIELDS = (
    "document_id", "item_id", "description", "quantity", "unit_price",
    "declared_total", "currency",
)
MAX_SOURCE_BYTES = 16 * 1024 * 1024


class CsvInputError(ValueError):
    """The file cannot be interpreted under the CSV input contract."""


def _read_records(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvInputError(f"CSV must be UTF-8: invalid byte at offset {exc.start}") from exc
    stream = io.StringIO(text, newline="")
    reader = csv.reader(stream, strict=True)
    try:
        header = next(reader)
    except StopIteration:
        header = []
    except csv.Error as exc:
        raise CsvInputError(f"Invalid CSV header: {exc}") from exc
    missing = [name for name in FIELDS if name not in header]
    extra = list(dict.fromkeys(name for name in header if name not in FIELDS))
    duplicates = [name for name, count in Counter(header).items() if count > 1]
    if missing or extra or duplicates:
        raise CsvInputError(
            f"Invalid CSV header: missing={missing}, extra={extra}, duplicate={duplicates}"
        )
    while True:
        source_row = reader.line_num + 1
        try:
            values = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise CsvInputError(f"Invalid CSV at record starting on row {source_row}: {exc}") from exc
        yield source_row, header, values


def read_csv_bytes(data):
    """Group every data record exactly once, including blank or malformed rows.

    Header order is flexible; its field names must match ``FIELDS`` exactly.
    ``document_id`` is trimmed only for grouping; ``fields`` and ``raw_fields``
    preserve the source values. Quoted multiline records use their first
    physical line as ``source_row``.
    """
    if not isinstance(data, bytes):
        raise CsvInputError("CSV input must be bytes")
    if len(data) > MAX_SOURCE_BYTES:
        raise CsvInputError(f"CSV source exceeds {MAX_SOURCE_BYTES} bytes")
    documents, ungrouped = {}, []
    input_rows = 0
    # The source cap is the explicit parser bound. Avoid csv's smaller implicit
    # per-field limit rejecting one long description before its data validation.
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_SOURCE_BYTES)
    try:
        for source_row, header, values in _read_records(data):
            input_rows += 1
            fields = {name: values[index] if index < len(values) else ""
                      for index, name in enumerate(header)}
            row = {"source_row": source_row, "fields": fields,
                   "raw_fields": values, "errors": []}
            if len(values) != len(FIELDS):
                row["errors"].append({
                    "row_number": source_row, "field": "*",
                    "reason_code": "CSV_COLUMN_COUNT",
                    "expected": len(FIELDS), "actual": len(values),
                })
            identifier = fields["document_id"].strip()
            if not identifier:
                row["errors"].append({
                    "row_number": source_row, "field": "document_id",
                    "reason_code": "REQUIRED", "expected": "non-empty text",
                    "actual": fields["document_id"],
                })
                ungrouped.append(row)
            else:
                document = documents.setdefault(identifier, {"document_id": identifier, "rows": []})
                document["rows"].append(row)
    finally:
        csv.field_size_limit(previous_limit)
    return {"documents": list(documents.values()), "ungrouped_rows": ungrouped,
            "input_rows": input_rows, "source_sha256": hashlib.sha256(data).hexdigest()}


def parse_csv(path):
    """Read a bounded source file and apply :func:`read_csv_bytes`."""
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    return read_csv_bytes(data)
