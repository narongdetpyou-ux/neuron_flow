#!/usr/bin/env python3
"""Build the versioned 100-document golden fixture without importing the runtime.

Expected errors are explicitly selected scenarios, not outputs from a validator.
Expected money uses only Python integers representing satang (no Decimal/float).
Run with --check to verify reproducibility without changing any files. Existing
locked output cannot be changed without --update-lock and an audit reason.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path


HEADER = ["document_id", "item_id", "description", "quantity", "unit_price",
          "declared_total", "currency"]
FIXTURE_ID = "neuron-flow-0.2.0-golden-v1"
SCHEMA_VERSION = "neuron-flow-acceptance-v1"
ROOT = Path(__file__).resolve().parents[1]


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute = abs(cents)
    return f"{sign}{absolute // 100}.{absolute % 100:02d}"


def cents(value: str) -> int:
    """Parse known-good fixture money with independent integer arithmetic."""
    whole, separator, fraction = value.partition(".")
    if not whole.isascii() or not whole.isdigit():
        raise ValueError(f"Not unsigned money: {value!r}")
    if separator and (not fraction.isascii() or not fraction.isdigit()
                      or len(fraction) > 2):
        raise ValueError(f"Not two-place money: {value!r}")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def total(rows: list[dict[str, str]]) -> int:
    return sum(int(row["quantity"]) * cents(row["unit_price"]) for row in rows)


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def base_rows(document_id: str) -> list[dict[str, str]]:
    return [
        dict(zip(HEADER, [document_id, "A", "สมุด", "2", "125.50", "310.70", "THB"])),
        dict(zip(HEADER, [document_id, "B", "ปากกา", "3", "19.90", "310.70", "THB"])),
    ]


def build_payloads() -> dict[str, bytes]:
    documents = []
    cases = []
    all_rows = []

    def add(rows, title, status="VALID", errors=None, mismatch=False):
        document_id = rows[0]["document_id"]
        document = {
            "document_id": document_id,
            "document_status": status,
            "source_rows": [],
            "computed_total": money(total(rows)) if status == "VALID" or mismatch else None,
            "declared_total": money(cents(rows[0]["declared_total"]))
            if rows[0]["declared_total"] else None,
            "difference": money(total(rows) - cents(rows[0]["declared_total"]))
            if status == "VALID" or mismatch else None,
            "errors": errors or [],
        }
        if any(error["reason_code"] == "DECLARED_TOTAL_CONFLICT"
               for error in document["errors"]):
            document["declared_total"] = None
        documents.append(document)
        cases.append({
            "case_id": document_id,
            "title": title,
            "expected_status": status,
            "reason_codes": sorted({error["reason_code"] for error in document["errors"]}),
            "source_rows": [],
        })
        all_rows.extend(rows)

    for index in range(1, 81):
        document_id = "INV-001" if index == 1 else f"VALID-{index:03d}"
        title = "Original invoice: 310.70 THB" if index == 1 else f"Valid deterministic invoice {index:03d}"
        if index == 1:
            rows = base_rows(document_id)
        else:
            rows = [dict(zip(HEADER, [
                document_id, f"I{line}", f"รายการ {index}/{line}",
                str((index * line) % 11 + 1),
                money((index * 7919 + line * 137) % 100000), "", "THB",
            ])) for line in range(1, (index % 3) + 2)]
        if index == 2:
            rows[0]["unit_price"] = "0.00"
            title = "Zero unit price is valid"
        elif index == 3:
            rows[0]["quantity"] = "1000000"
            title = "Quantity upper boundary: 1000000"
        elif index == 4:
            rows[0]["unit_price"] = "1000000000000.00"
            title = "Unit-price upper boundary: 1000000000000.00"
        elif index == 5:
            rows[0]["unit_price"] = "12"
            rows[1]["unit_price"] = "12.5"
            rows[0]["quantity"] = "000002"
            title = "Integer and one-place prices; leading-zero quantity"
        elif index == 6:
            rows[0]["description"] = 'สมุด, รุ่น "พิเศษ"'
            title = "UTF-8 Thai, comma and escaped CSV quotes"
        elif index == 7:
            rows[0]["description"] = "คำอธิบายบรรทัดแรก\nคำอธิบายบรรทัดที่สอง"
            title = "Quoted multiline CSV record preserves physical source line"
        declared = money(total(rows))
        for row in rows:
            row["declared_total"] = declared
        add(rows, title)

    def invalid(index, title, changes, specifications, mismatch=False):
        rows = base_rows(f"INVALID-{index:03d}")
        for row_index, field, value in changes:
            rows[row_index][field] = value
        errors = [{"row_number": row_index, "field": field,
                   "reason_code": code, "expected": expected,
                   "actual": rows[row_index][field]}
                  for row_index, field, code, expected in specifications]
        # row_number is a temporary zero-based local row index, resolved below.
        add(rows, title, "INVALID", errors, mismatch)

    missing_fields = ["description", "item_id", "quantity", "unit_price", "declared_total", "currency"]
    for index, field in enumerate(missing_fields, 1):
        invalid(index, f"Missing required {field}", [(0, field, "")],
                [(0, field, "REQUIRED", "non-empty")])

    quantities = [
        ("0", "QUANTITY_RANGE", "integer:1..1000000"),
        ("-1", "QUANTITY_FORMAT", "unsigned-integer:1..7-digits"),
        ("1.5", "QUANTITY_FORMAT", "unsigned-integer:1..7-digits"),
        ("1000001", "QUANTITY_RANGE", "integer:1..1000000"),
        ("two", "QUANTITY_FORMAT", "unsigned-integer:1..7-digits"),
    ]
    for index, (value, code, expected) in enumerate(quantities, 7):
        invalid(index, f"Quantity rejects {value}", [(0, "quantity", value)],
                [(0, "quantity", code, expected)])

    prices = [
        ("-0.01", "PRICE_FORMAT", "unsigned-decimal:1..13-digits;scale<=2"),
        ("1.001", "PRICE_FORMAT", "unsigned-decimal:1..13-digits;scale<=2"),
        ("1000000000000.01", "PRICE_RANGE", "decimal:0..1000000000000"),
        ("NaN", "PRICE_FORMAT", "unsigned-decimal:1..13-digits;scale<=2"),
    ]
    for index, (value, code, expected) in enumerate(prices, 12):
        invalid(index, f"Unit price rejects {value}", [(0, "unit_price", value)],
                [(0, "unit_price", code, expected)])

    invalid(16, "Duplicate item identifier is not counted twice", [(1, "item_id", "A")],
            [(1, "item_id", "DUPLICATE_ITEM_ID", "unique-within-document")])
    invalid(17, "Currency must be THB", [(0, "currency", "USD"), (1, "currency", "USD")],
            [(0, "currency", "CURRENCY_UNSUPPORTED", "THB"),
             (1, "currency", "CURRENCY_UNSUPPORTED", "THB")])
    invalid(18, "Currency differs between rows", [(1, "currency", "USD")],
            [(1, "currency", "CURRENCY_UNSUPPORTED", "THB"),
             (1, "currency", "CURRENCY_CONFLICT", "THB")])
    invalid(19, "Declared totals disagree between rows", [(1, "declared_total", "310.71")],
            [(1, "declared_total", "DECLARED_TOTAL_CONFLICT", "310.70")])
    invalid(20, "Declared total differs from computed total by one satang",
            [(0, "declared_total", "310.71"), (1, "declared_total", "310.71")],
            [(0, "declared_total", "TOTAL_MISMATCH", "310.70")], mismatch=True)

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=HEADER, lineterminator="\n")
    writer.writeheader()
    writer.writerows(all_rows)
    csv_text = stream.getvalue()

    # csv.reader.line_num tracks physical lines, including quoted multiline data.
    reader = csv.DictReader(io.StringIO(csv_text, newline=""))
    _ = reader.fieldnames
    previous_line = reader.line_num
    source_rows = {}
    for row in reader:
        source_rows.setdefault(row["document_id"], []).append(previous_line + 1)
        previous_line = reader.line_num
    for document, case in zip(documents, cases):
        rows = source_rows[document["document_id"]]
        document["source_rows"] = rows
        case["source_rows"] = rows
        for error in document["errors"]:
            error["row_number"] = rows[error["row_number"]]

    counts = {"documents": len(documents), "VALID": 80, "INVALID": 20,
              "ERROR": 0, "input_rows": len(all_rows), "ungrouped_rows": 0}
    assert len(documents) == 100
    assert sum(document["document_status"] == "VALID" for document in documents) == 80
    assert len({document["document_id"] for document in documents}) == 100
    expected = {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": FIXTURE_ID,
        "currency": "THB",
        "source_file": "input.csv",
        "row_number_convention": "1-based physical CSV record start; header starts at line 1",
        "difference_convention": "computed_total - declared_total",
        "invalid_total_policy": "computed_total and difference are null except TOTAL_MISMATCH; declared_total uses the first row when valid, or null when missing or conflicting",
        "counts": counts,
        "documents": documents,
    }
    coverage = {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": FIXTURE_ID,
        "oracle": "Explicit scenario errors; all reference money computed independently using integer satang; no runtime imports",
        "scope": "Golden input cases for A01, A03-A07. File rejection, ungrouped rows and process-failure acceptance require separate later scenarios.",
        "counts": counts,
        "cases": cases,
    }
    return {"input.csv": csv_text.encode("utf-8"),
            "expected_results.json": json_bytes(expected), "cases.json": json_bytes(coverage)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check all bytes and lock without writing")
    parser.add_argument("--update-lock", action="store_true", help="allow intentional replacement of locked files")
    parser.add_argument("--reason", help="required audit explanation when changing an existing lock")
    args = parser.parse_args()
    if args.check and args.update_lock:
        parser.error("--check and --update-lock are mutually exclusive")
    if args.update_lock and not args.reason:
        parser.error("--update-lock requires --reason")
    directory = ROOT / "acceptance"
    lock_path = directory / "fixture_lock.json"
    payloads = build_payloads()
    lock = {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": FIXTURE_ID,
        "algorithm": "SHA-256",
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
                  for name, data in payloads.items()},
        "change_history": [],
    }
    if lock_path.exists():
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["change_history"] = existing.get("change_history", [])
        if existing.get("files") != lock["files"]:
            if not args.update_lock:
                parser.error("generated fixture differs from lock; intentional changes require --update-lock --reason")
            lock["change_history"].append({"reason": args.reason, "previous_files": existing.get("files")})
    payloads["fixture_lock.json"] = json_bytes(lock)
    if args.check:
        changed = [name for name, data in payloads.items()
                   if not (directory / name).exists() or (directory / name).read_bytes() != data]
        if changed:
            parser.exit(1, f"Fixture check failed: {', '.join(changed)}\n")
        print("Fixture verified: 100 documents (80 VALID, 20 INVALID); all locked bytes reproduce.")
        return
    for name, data in payloads.items():
        path = directory / name
        if path.exists() and path.read_bytes() != data and not args.update_lock:
            parser.error(f"refusing to overwrite changed {name}; use --update-lock --reason")
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        path = directory / name
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    print("Fixture built: 100 documents (80 VALID, 20 INVALID); SHA-256 lock written.")


if __name__ == "__main__":
    main()
