import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from neuron_flow.csv_input import (FIELDS, MAX_SOURCE_BYTES, CsvInputError,
                                   parse_csv, read_csv_bytes)


PROJECT = Path(__file__).resolve().parents[1]


def source(rows, header=FIELDS):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def purchase(identifier="A", description="สินค้า"):
    return [identifier, "I1", description, "2", "0.10", "0.20", "THB"]


class CsvInputTests(unittest.TestCase):
    def test_bom_unicode_and_hash(self):
        data = b"\xef\xbb\xbf" + source([purchase("ใบ-๑", "สมุด, ปากกา")])
        result = read_csv_bytes(data)
        self.assertEqual(result["source_sha256"], hashlib.sha256(data).hexdigest())
        row = result["documents"][0]["rows"][0]
        self.assertEqual(row["fields"]["description"], "สมุด, ปากกา")
        self.assertEqual(row["source_row"], 2)
        self.assertEqual(result["documents"][0]["document_id"], "ใบ-๑")

    def test_interleaved_documents_preserve_source_order_and_values(self):
        result = read_csv_bytes(source([purchase(" A "), purchase("B"), purchase("A")]))
        self.assertEqual([d["document_id"] for d in result["documents"]], ["A", "B"])
        self.assertEqual([r["source_row"] for r in result["documents"][0]["rows"]], [2, 4])
        self.assertEqual(result["documents"][0]["rows"][0]["fields"]["document_id"], " A ")
        self.assertEqual(result["input_rows"], 3)

    def test_reordered_header_maps_values_by_name(self):
        original = dict(zip(FIELDS, purchase()))
        header = tuple(reversed(FIELDS))
        result = read_csv_bytes(source([[original[f] for f in header]], header))
        self.assertEqual(result["documents"][0]["rows"][0]["fields"], original)

    def test_bad_headers_name_missing_extra_and_duplicate_columns(self):
        cases = [
            (FIELDS[:-1], "currency"),
            (FIELDS + ("unexpected",), "unexpected"),
            (FIELDS + ("item_id",), "duplicate=['item_id']"),
            (("Document_id",) + FIELDS[1:], "document_id"),
            ((), "document_id"),
        ]
        for header, message in cases:
            with self.subTest(header=header), self.assertRaises(CsvInputError) as raised:
                read_csv_bytes(source([], header))
            self.assertIn(message, str(raised.exception))

    def test_multiline_record_uses_starting_physical_line(self):
        result = read_csv_bytes(source([purchase("A", "first\r\nsecond\nthird"), purchase("B")]))
        self.assertEqual([d["rows"][0]["source_row"] for d in result["documents"]], [2, 5])
        self.assertEqual(result["documents"][0]["rows"][0]["fields"]["description"],
                         "first\r\nsecond\nthird")

    def test_blank_missing_id_short_and_extra_rows_are_not_lost(self):
        rows = [purchase(""), [], ["short"], purchase("extra") + ["kept"], purchase(" \t ")]
        result = read_csv_bytes(source(rows))
        self.assertEqual(result["input_rows"], 5)
        self.assertEqual([r["source_row"] for r in result["ungrouped_rows"]], [2, 3, 6])
        blank = result["ungrouped_rows"][1]
        self.assertEqual(blank["raw_fields"], [])
        self.assertEqual([e["reason_code"] for e in blank["errors"]], ["CSV_COLUMN_COUNT", "REQUIRED"])
        short, extra = [d["rows"][0] for d in result["documents"]]
        self.assertEqual(short["fields"]["quantity"], "")
        self.assertEqual(short["errors"][0], {"row_number": 4, "field": "*",
                         "reason_code": "CSV_COLUMN_COUNT", "expected": 7, "actual": 1})
        self.assertEqual(extra["raw_fields"][-1], "kept")
        self.assertEqual(extra["errors"][0]["actual"], 8)
        all_rows = [r["source_row"] for d in result["documents"] for r in d["rows"]]
        all_rows += [r["source_row"] for r in result["ungrouped_rows"]]
        self.assertEqual(sorted(all_rows), [2, 3, 4, 5, 6])

    def test_malformed_encoding_and_csv_reject_entire_file(self):
        header = source([])
        for data in (header + b"\xff", header + b'A,I1,"unterminated',
                     header + b'A,I1,"quoted"trailing,1,1.00,1.00,THB\n'):
            with self.subTest(data=data), self.assertRaises(CsvInputError):
                read_csv_bytes(data)

    def test_empty_source_rejected_and_header_only_has_zero_rows(self):
        with self.assertRaises(CsvInputError):
            read_csv_bytes(b"")
        result = read_csv_bytes(source([]))
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["ungrouped_rows"], [])
        self.assertEqual(result["input_rows"], 0)

    def test_source_cap_is_explicit_and_long_data_field_is_preserved(self):
        with self.assertRaisesRegex(CsvInputError, "exceeds"):
            read_csv_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
        description = "x" * 140_000
        row = read_csv_bytes(source([purchase(description=description)]))["documents"][0]["rows"][0]
        self.assertEqual(row["fields"]["description"], description)

    def test_parse_csv_wrapper(self):
        data = source([purchase()])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.csv"
            path.write_bytes(data)
            self.assertEqual(parse_csv(path), read_csv_bytes(data))

    def test_locked_acceptance_fixture_groups_all_201_rows_once(self):
        result = parse_csv(PROJECT / "acceptance" / "input.csv")
        expected = json.loads((PROJECT / "acceptance" / "expected_results.json").read_text())
        self.assertEqual(len(result["documents"]), 100)
        self.assertEqual(result["input_rows"], 201)
        self.assertEqual(result["ungrouped_rows"], [])
        self.assertEqual([d["document_id"] for d in result["documents"]],
                         [d["document_id"] for d in expected["documents"]])
        all_rows = [r["source_row"] for d in result["documents"] for r in d["rows"]]
        expected_rows = [row for d in expected["documents"] for row in d["source_rows"]]
        self.assertEqual(sorted(all_rows), sorted(expected_rows))
        self.assertEqual(len(all_rows), 201)
        self.assertEqual(len(all_rows), len(set(all_rows)))
        for actual, reference in zip(result["documents"], expected["documents"]):
            self.assertEqual([r["source_row"] for r in actual["rows"]], reference["source_rows"])


if __name__ == "__main__":
    unittest.main()
