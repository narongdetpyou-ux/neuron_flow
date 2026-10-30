import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from neuron_flow.csv_agents import compute_document, validate_document, verify_document
from neuron_flow.csv_input import FIELDS, read_csv_bytes
from neuron_flow.reporting import BatchTerminal, ReportConflict, SUMMARY_FIELDS


def frozen_example(*, bom=False, valid_id="VALID"):
    rows = [
        [valid_id, "A", 'Notebook, "cafe edition"\nSecond line', "2", "0.10", "0.50", "THB"],
        ["INVALID", "A", "Invalid quantity", "0", "0.10", "0.10", "THB"],
        [valid_id, "B", "Pen", "3", "0.10", "0.50", "THB"],
        ["ERROR", "A", "Agent failure", "1", "1.00", "1.00", "THB"],
        ["", "A", "Missing document identifier", "1", "5.00", "5.00", "THB"],
    ]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    writer.writerows(rows)
    source = (b"\xef\xbb\xbf" if bom else b"") + stream.getvalue().encode("utf-8")
    parsed = read_csv_bytes(source)
    documents = []
    for original in parsed["documents"]:
        validated = validate_document(original)
        result = verify_document(validated, compute_document(validated))
        engine_status = "SUCCEEDED"
        steps = {"verify": {"status": "SUCCEEDED", "attempts": 1,
                            "output": copy.deepcopy(result), "error": None}}
        if original["document_id"] == "ERROR":
            failure = {"type": "ChildProcessError", "message": "worker exited"}
            result.update(document_status="ERROR", computed_total=None, difference=None,
                          errors=[{"row_number": result["source_rows"][0], "field": "*",
                                   "reason_code": "ENGINE_ERROR", "expected": "verified document result",
                                   "actual": failure}])
            engine_status = "FAILED"
            steps = {"calculate": {"status": "FAILED", "attempts": 2,
                                   "output": None, "error": failure}}
        documents.append({**result, "job_id": "job_" + original["document_id"],
                          "engine_status": engine_status, "steps": steps,
                          "history": [{"sequence": len(documents) + 1, "timestamp": 1.25,
                                       "kind": "job.succeeded" if engine_status == "SUCCEEDED" else "job.failed"}],
                          "source_records": original["rows"]})
    payload = {"batch_id": "sample", "status": "PROCESSED", "source_sha256": parsed["source_sha256"],
               "contract_version": "purchase-csv-v1", "system_version": "0.2.0",
               "agent_versions": {"csv_verify": {"version": "0.2.0"}},
               "input_rows": parsed["input_rows"], "ungrouped_rows": parsed["ungrouped_rows"],
               "counts": {"documents": 3, "VALID": 1, "INVALID": 1, "ERROR": 1},
               "certified_total": "0.50", "currency": "THB", "documents": documents}
    return payload, source


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="neuron-report-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "output"
        self.terminal = BatchTerminal(self.directory)

    def test_full_artifacts_preserve_normal_invalid_error_and_source_provenance(self):
        payload, source = frozen_example()
        original = copy.deepcopy(payload)
        receipt = self.terminal.deliver(payload, source)
        self.assertEqual(payload, original)
        self.assertEqual(set(receipt["artifacts"]), {"summary.csv", "details.json", "source.csv"})
        self.assertEqual((self.directory / "source.csv").read_bytes(), source)
        details = json.loads((self.directory / "details.json").read_bytes())
        self.assertEqual(details, payload)
        self.assertEqual(details["counts"], {"documents": 3, "VALID": 1, "INVALID": 1, "ERROR": 1})
        self.assertEqual(details["certified_total"], "0.50")
        reader = csv.DictReader(io.StringIO((self.directory / "summary.csv").read_text()))
        rows = list(reader)
        self.assertEqual(reader.fieldnames, list(SUMMARY_FIELDS))
        self.assertEqual([row["document_status"] for row in rows], ["VALID", "INVALID", "ERROR"])
        self.assertEqual(rows[0]["computed_total"], "0.50")
        self.assertEqual(rows[1]["computed_total"], "")
        self.assertEqual(rows[2]["engine_status"], "FAILED")
        self.assertEqual(rows[2]["error_count"], "1")
        self.assertEqual(json.loads(rows[0]["source_rows"]), [2, 5])
        for name, metadata in receipt["artifacts"].items():
            data = (self.directory / name).read_bytes()
            self.assertEqual(Path(metadata["path"]), (self.directory / name).resolve())
            self.assertEqual(metadata["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(metadata["bytes"], len(data))

    def test_repeated_delivery_preserves_receipt_bytes_and_mtime(self):
        payload, source = frozen_example()
        first = self.terminal.deliver(payload, source)
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.directory.iterdir()}
        with patch("neuron_flow.reporting.os.link", side_effect=AssertionError("must not publish twice")):
            second = self.terminal.deliver(copy.deepcopy(payload), source)
        after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.directory.iterdir()}
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_bom_source_is_kept_byte_for_byte_and_hash_is_of_original_encoding(self):
        payload, source = frozen_example(bom=True)
        receipt = self.terminal.deliver(payload, source)
        self.assertTrue((self.directory / "source.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(receipt["artifacts"]["source.csv"]["sha256"], payload["source_sha256"])
        with self.assertRaises(ReportConflict):
            BatchTerminal(self.directory / "without-bom").deliver(payload, source[3:])

    def test_intermediate_or_delivery_pending_payload_cannot_be_published(self):
        payload, source = frozen_example()
        for status in ("PENDING", "RUNNING", "DELIVERY_FAILED", "DELIVERED"):
            with self.subTest(status=status):
                payload["status"] = status
                with self.assertRaises(ReportConflict):
                    self.terminal.deliver(payload, source)
                self.assertFalse(self.directory.exists())

    def test_payload_source_and_trace_tampering_fail_before_any_artifact_is_written(self):
        payload, source = frozen_example()
        mutations = [
            lambda p: p.update(source_sha256="0" * 64),
            lambda p: p.update(input_rows=6),
            lambda p: p.update(input_rows=5.0),
            lambda p: p["ungrouped_rows"].clear(),
            lambda p: p["documents"][0].update(source_rows=[2, 4]),
            lambda p: p["documents"][0]["source_records"][0]["fields"].update(description="changed"),
            lambda p: p["documents"][0]["source_records"][0]["raw_fields"].__setitem__(2, "changed"),
            lambda p: p["documents"][0]["source_records"][0].update(source_row=2.0),
            lambda p: p["documents"][1]["errors"][0].update(row_number=99),
            lambda p: p["documents"].append(copy.deepcopy(p["documents"][0])),
            lambda p: p["documents"].reverse(),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                changed = copy.deepcopy(payload)
                mutate(changed)
                with self.assertRaises(ReportConflict):
                    self.terminal.deliver(changed, source)
                self.assertFalse(self.directory.exists())

    def test_counts_certified_totals_and_float_amounts_cannot_be_misreported(self):
        payload, source = frozen_example()
        mutations = [
            lambda p: p["counts"].update(VALID=2),
            lambda p: p["counts"].update(documents=4),
            lambda p: p["counts"].update(VALID=True),
            lambda p: p.update(certified_total="1.50"),  # ERROR amount must not be included.
            lambda p: p["documents"][0].update(computed_total="0.60"),
            lambda p: p["documents"][0].update(computed_total=0.50),
            lambda p: p["documents"][0].update(declared_total=0.50),
            lambda p: p["documents"][0].update(difference="-0.00"),
            lambda p: p["documents"][2].update(computed_total="1.00"),
            lambda p: p["documents"][1].update(computed_total="0.00", difference="-0.10"),
            lambda p: p["documents"][1].update(errors=[]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                changed = copy.deepcopy(payload)
                mutate(changed)
                with self.assertRaises(ReportConflict):
                    self.terminal.deliver(changed, source)
                self.assertFalse(self.directory.exists())

    def test_consistently_forged_report_totals_still_fail_against_source_arithmetic(self):
        payload, source = frozen_example()
        payload["documents"][0].update(computed_total="9.00", declared_total="9.00", difference="0.00")
        payload["certified_total"] = "9.00"
        with self.assertRaises(ReportConflict):
            self.terminal.deliver(payload, source)

    def test_existing_conflict_in_any_file_prevents_every_new_file_and_preserves_original(self):
        payload, source = frozen_example()
        for name in ("summary.csv", "details.json", "source.csv"):
            with self.subTest(name=name):
                directory = Path(self.temporary.name) / name
                directory.mkdir()
                conflict = directory / name
                conflict.write_bytes(b"pre-existing conflicting content")
                before = conflict.stat().st_mtime_ns
                with self.assertRaises(ReportConflict):
                    BatchTerminal(directory).deliver(payload, source)
                self.assertEqual(list(directory.iterdir()), [conflict])
                self.assertEqual(conflict.read_bytes(), b"pre-existing conflicting content")
                self.assertEqual(conflict.stat().st_mtime_ns, before)

    def test_preflight_does_not_create_missing_summary_when_later_source_conflicts(self):
        payload, source = frozen_example()
        self.terminal.deliver(payload, source)
        (self.directory / "summary.csv").unlink()
        (self.directory / "source.csv").write_bytes(b"conflict")
        details_before = (self.directory / "details.json").stat().st_mtime_ns
        with self.assertRaises(ReportConflict):
            self.terminal.deliver(payload, source)
        self.assertFalse((self.directory / "summary.csv").exists())
        self.assertEqual((self.directory / "source.csv").read_bytes(), b"conflict")
        self.assertEqual((self.directory / "details.json").stat().st_mtime_ns, details_before)

    def test_partial_publish_failure_can_resume_without_rewriting_completed_artifacts(self):
        payload, source = frozen_example()
        original_link = os.link
        calls = []

        def interrupt_after_first(temporary, target):
            calls.append(Path(target).name)
            if len(calls) == 2:
                raise OSError("controller interrupted between artifacts")
            original_link(temporary, target)

        with patch("neuron_flow.reporting.os.link", side_effect=interrupt_after_first):
            with self.assertRaises(OSError):
                self.terminal.deliver(payload, source)
        first = self.directory / "summary.csv"
        before = first.read_bytes(), first.stat().st_mtime_ns
        self.assertEqual([path.name for path in self.directory.iterdir()], ["summary.csv"])
        receipt = self.terminal.deliver(payload, source)
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), before)
        self.assertEqual(len(receipt["artifacts"]), 3)

    def test_concurrent_conflicting_file_is_never_overwritten_after_preflight(self):
        payload, source = frozen_example()
        original_link = os.link

        def competing_file(temporary, target):
            if Path(target).name == "summary.csv":
                Path(target).write_bytes(b"concurrent owner content")
            original_link(temporary, target)

        with patch("neuron_flow.reporting.os.link", side_effect=competing_file):
            with self.assertRaises(ReportConflict):
                self.terminal.deliver(payload, source)
        self.assertEqual((self.directory / "summary.csv").read_bytes(), b"concurrent owner content")
        self.assertFalse((self.directory / "details.json").exists())
        self.assertFalse(any(path.name.startswith(".batch-report-") for path in self.directory.iterdir()))

    def test_corruption_after_publish_fails_readback_and_does_not_issue_receipt(self):
        payload, source = frozen_example()
        original_link = os.link

        def corrupt_after_link(temporary, target):
            original_link(temporary, target)
            if Path(target).name == "summary.csv":
                Path(target).write_bytes(b"corrupted after publishing")

        with patch("neuron_flow.reporting.os.link", side_effect=corrupt_after_link):
            with self.assertRaises(ReportConflict):
                self.terminal.deliver(payload, source)

    def test_symlink_artifact_is_rejected_without_modifying_its_target(self):
        payload, source = frozen_example()
        self.directory.mkdir()
        outside = Path(self.temporary.name) / "keep.txt"
        outside.write_bytes(b"keep")
        (self.directory / "details.json").symlink_to(outside)
        with self.assertRaises(ReportConflict):
            self.terminal.deliver(payload, source)
        self.assertEqual(outside.read_bytes(), b"keep")
        self.assertFalse((self.directory / "summary.csv").exists())

    def test_document_identifier_is_data_and_never_becomes_an_output_path(self):
        payload, source = frozen_example(valid_id="../../outside")
        receipt = self.terminal.deliver(payload, source)
        self.assertEqual(set(path.name for path in self.directory.iterdir()),
                         {"summary.csv", "details.json", "source.csv"})
        self.assertTrue(all(Path(item["path"]).parent == self.directory.resolve()
                            for item in receipt["artifacts"].values()))
        self.assertFalse((Path(self.temporary.name) / "outside").exists())


if __name__ == "__main__":
    unittest.main()
