"""Evidence integrity, exact comparisons and a real read-only batch handoff."""

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from neuron_flow.batch import BatchRuntime
from neuron_flow.report_review import compare_reports, explain_report, score_claims
from neuron_flow.reporting import BatchTerminal, ReportConflict
from tests.test_reporting import frozen_example


PROJECT = Path(__file__).resolve().parents[1]


class ReportReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload, self.source = frozen_example()
        self.reference = self.write("reference", self.payload, self.source)

    def write(self, name, payload, source):
        folder = self.root / name
        BatchTerminal(folder).deliver(payload, source)
        return folder

    @staticmethod
    def contents(folder):
        return {p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in folder.rglob("*") if p.is_file()}

    def corrupt_details(self, data):
        (self.reference / "details.json").write_bytes(data)

    def test_explanation_traces_valid_invalid_error_and_ungrouped_records(self):
        before = self.contents(self.reference)
        result = explain_report(self.reference)
        self.assertEqual([d["document_status"] for d in result["documents"]],
                         ["VALID", "INVALID", "ERROR"])
        for document in result["documents"]:
            self.assertTrue(document["verification"]["all_supported"])
            self.assertTrue(score_claims(self.payload, document["claims"])["all_supported"])
        invalid = result["documents"][1]
        quantity = next(reason for reason in invalid["reasons"] if reason["field"] == "quantity")
        self.assertEqual(quantity["reason_code"], "QUANTITY_RANGE")
        self.assertEqual(quantity["row_number"], 4)
        self.assertEqual(result["ungrouped_rows"][0]["source_row"], 7)
        self.assertTrue(score_claims(self.payload, result["batch_claims"])["all_supported"])
        self.assertTrue(score_claims(self.payload, result["ungrouped_rows"][0]["claims"])["all_supported"])
        self.assertEqual(result["artifact_sha256"]["source.csv"], hashlib.sha256(self.source).hexdigest())
        self.assertEqual(self.contents(self.reference), before)
        self.assertEqual(result, explain_report(self.reference))

    def test_document_filter_uses_identifier_not_pointer_syntax(self):
        payload, source = frozen_example(valid_id="invoice/a~b")
        folder = self.write("special-id", payload, source)
        result = explain_report(folder, document_id="invoice/a~b")
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(result["documents"][0]["claims"][0]["path"], "/documents/0/document_id")
        with self.assertRaisesRegex(ValueError, "Unknown document_id"):
            explain_report(folder, document_id="missing")

    def test_claims_reject_forgery_types_unknown_fields_and_unsafe_indices(self):
        claims = [
            {"path": "/documents/0/computed_total", "value": "0.50"},
            {"path": "/documents/0/computed_total", "value": .50},
            {"path": "/documents/0/errors/0/actual", "value": "invented"},
            {"path": "/documents/-1/document_status", "value": "ERROR"},
            {"path": "/documents/00/document_status", "value": "VALID"},
            {"path": "/private/token", "value": "secret"},
            {"path": "/counts", "value": self.payload["counts"], "extra": True},
            None, {"path": 1, "value": "invalid"},
        ]
        result = score_claims(self.payload, claims)
        self.assertEqual(result["supported"], 1)
        self.assertEqual(result["unsupported_claims"], list(range(1, 9)))
        self.assertFalse(result["all_supported"])
        self.assertFalse(score_claims(self.payload, [])["all_supported"])
        with self.assertRaisesRegex(ValueError, "list"):
            score_claims(self.payload, {})
        custom = {"documents": [{"errors": [{"actual": 1}]}]}
        for value in [True, 1.0, float("nan")]:
            self.assertFalse(score_claims(custom, [
                {"path": "/documents/0/errors/0/actual", "value": value}])["all_supported"])

    def test_incorrect_or_unbound_artifacts_never_produce_an_explanation(self):
        for name, changes in [
            ("wrong-money", lambda p: p["documents"][0].update(computed_total="0.51")),
            ("wrong-source", lambda p: p.update(source_sha256="0" * 64)),
            ("lost-row", lambda p: p["documents"][0].update(source_rows=[2])),
        ]:
            changed = copy.deepcopy(self.payload)
            changes(changed)
            self.corrupt_details(json.dumps(changed).encode())
            with self.subTest(name=name), self.assertRaises(ReportConflict):
                explain_report(self.reference)
        self.corrupt_details(json.dumps(self.payload).encode())
        (self.reference / "source.csv").write_bytes(self.source + b"\n")
        with self.assertRaises(ReportConflict):
            explain_report(self.reference)

    def test_malformed_nonfinite_duplicate_or_nonobject_details_are_rejected(self):
        for data in [b"{", b'"\xff"', b'{}', b'[]',
                     b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
                     b'{"x":1e999}', b'[' * 1100 + b']' * 1100]:
            self.corrupt_details(data)
            with self.subTest(data=data[:40]), self.assertRaises(ReportConflict):
                explain_report(self.reference)

    def test_required_report_identity_is_not_invented(self):
        for key, value in [("batch_id", ""), ("system_version", None), ("agent_versions", [])]:
            payload = copy.deepcopy(self.payload)
            payload[key] = value
            self.corrupt_details(json.dumps(payload).encode())
            with self.subTest(key=key), self.assertRaisesRegex(ReportConflict, "identity"):
                explain_report(self.reference)

    def test_missing_large_and_symlink_artifacts_are_rejected(self):
        with patch("neuron_flow.report_review.MAX_REPORT_BYTES", 3):
            with self.assertRaisesRegex(ReportConflict, "exceeds"):
                explain_report(self.reference)
        with patch("neuron_flow.report_review.MAX_SOURCE_BYTES", 3):
            with self.assertRaisesRegex(ReportConflict, "exceeds"):
                explain_report(self.reference)
        source = self.reference / "source.csv"
        source.unlink()
        with self.assertRaises(FileNotFoundError):
            explain_report(self.reference)
        source.symlink_to(self.write("other", self.payload, self.source) / "source.csv")
        with self.assertRaisesRegex(ReportConflict, "symlink"):
            explain_report(self.reference)
        link = self.root / "link"
        link.symlink_to(self.reference, target_is_directory=True)
        with self.assertRaisesRegex(ReportConflict, "symlink"):
            explain_report(link)

    def test_summary_must_match_checked_details(self):
        summary = self.reference / "summary.csv"
        for data in [b"bad,header\n", b"\xff", b'"unclosed']:
            summary.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ReportConflict):
                explain_report(self.reference)

    def test_comparison_ignores_execution_metadata_but_keeps_identities(self):
        candidate = copy.deepcopy(self.payload)
        candidate.update(batch_id="candidate", system_version="next-version",
                         agent_versions={"csv_verify": {"version": "candidate"}})
        for document in candidate["documents"]:
            document.update(job_id="other-job", history=[{"timestamp": 900.0}],
                            steps={"changed": {"attempts": 4}})
        directory = self.write("candidate", candidate, self.source)
        before = self.contents(self.root)
        result = compare_reports(self.reference, directory)
        self.assertTrue(result["agreement"])
        self.assertEqual(result["difference_count"], 0)
        self.assertEqual(result["documents_compared"], 3)
        self.assertEqual(result["candidate"]["system_version"], "next-version")
        self.assertNotEqual(result["reference"]["artifact_sha256"]["details.json"],
                            result["candidate"]["artifact_sha256"]["details.json"])
        self.assertEqual(before, self.contents(self.root))

    def error_candidate(self):
        candidate = copy.deepcopy(self.payload)
        document = candidate["documents"][0]
        document.update(document_status="ERROR", engine_status="FAILED", computed_total=None,
                        difference=None, errors=[{"row_number": document["source_rows"][0],
                            "field": "*", "reason_code": "ENGINE_ERROR",
                            "expected": "verified document result", "actual": {"type": "TimeoutError"}}])
        candidate["counts"].update(VALID=0, ERROR=2)
        candidate["certified_total"] = "0.00"
        return self.write("error-candidate", candidate, self.source)

    def test_comparison_reports_lost_valid_result_and_changed_certified_total(self):
        result = compare_reports(self.reference, self.error_candidate())
        self.assertFalse(result["agreement"])
        by_path = {d["path"]: d for d in result["differences"]}
        self.assertEqual(by_path["/certified_total"]["candidate"], "0.00")
        self.assertEqual(by_path["/documents/0/document_status"]["reference"], "VALID")
        self.assertEqual(by_path["/documents/0/document_status"]["candidate"], "ERROR")
        self.assertEqual(result["difference_count"], len(by_path))

    def test_comparison_rejects_different_source_or_contract(self):
        payload, source = frozen_example(bom=True)
        different = self.write("different-source", payload, source)
        with self.assertRaisesRegex(ReportConflict, "identical source"):
            compare_reports(self.reference, different)
        changed = copy.deepcopy(self.payload)
        changed.update(contract_version="purchase-csv-multicurrency-v1", certified_totals={"THB": "0.50"})
        different = self.write("different-contract", changed, self.source)
        with self.assertRaisesRegex(ReportConflict, "same data contract"):
            compare_reports(self.reference, different)

    def test_forged_candidate_money_is_invalid_instead_of_an_agreement(self):
        candidate = self.write("forged", self.payload, self.source)
        forged = copy.deepcopy(self.payload)
        forged["documents"][0]["computed_total"] = "0.51"
        (candidate / "details.json").write_text(json.dumps(forged))
        with self.assertRaises(ReportConflict):
            compare_reports(self.reference, candidate)

    def test_cli_exit_codes_and_errors_are_review_results(self):
        from neuron_flow.__main__ import main
        from contextlib import redirect_stderr, redirect_stdout
        error_candidate = self.error_candidate()
        for args, expected in [
            (["report-explain", str(self.reference), "--document-id", "INVALID"], 0),
            (["report-compare", str(self.reference), str(self.reference)], 0),
            (["report-compare", str(self.reference), str(error_candidate)], 1),
            (["report-explain", str(self.reference), "--document-id", "missing"], 2),
        ]:
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                status = main(args)
            self.assertEqual(status, expected)
            parsed = json.loads(error.getvalue() if expected == 2 else output.getvalue())
            self.assertIsInstance(parsed, dict)

    def test_archived_100_document_report_remains_readable_and_unchanged(self):
        directory = PROJECT / "verification/v0_2_1/samples/golden"
        before = self.contents(directory)
        result = explain_report(directory)
        self.assertEqual(len(result["documents"]), 100)
        self.assertTrue(all(d["verification"]["all_supported"] for d in result["documents"]))
        self.assertTrue(compare_reports(directory, directory)["agreement"])
        self.assertEqual(before, self.contents(directory))

    def test_real_multicurrency_batch_cli_inspection_and_resume_are_unchanged(self):
        source = (PROJECT / "examples/purchases_international.csv").read_bytes()
        workspace = self.root / "workspace"
        with BatchRuntime(workspace, max_workers=1) as batch:
            submitted = batch.submit(source, "international")
            delivered = batch.deliver(submitted["batch_id"])
        directory = workspace / "batch_reports/international"
        before = self.contents(workspace)
        result = explain_report(directory)
        self.assertTrue(all(d["verification"]["all_supported"] for d in result["documents"]))
        totals = next(c for c in result["batch_claims"] if c["path"] == "/certified_total")
        self.assertIsNone(totals["value"])
        currencies = next(c for c in result["batch_claims"] if c["path"] == "/certified_totals")
        self.assertEqual(currencies["value"]["JPY"], "1500")
        self.assertEqual(currencies["value"]["KWD"], "3.702")
        for command in [["report-explain", str(directory)],
                        ["report-compare", str(directory), str(directory)]]:
            completed = subprocess.run([sys.executable, "-B", "-m", "neuron_flow", *command],
                                       cwd=PROJECT, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(before, self.contents(workspace))
        with BatchRuntime(workspace, max_workers=1) as batch:
            resumed = batch.deliver("international")
        self.assertEqual(delivered["receipt"], resumed["receipt"])
        self.assertEqual(delivered["certified_totals"], {"EUR": "25.50", "JPY": "1500",
                                                        "KWD": "3.702", "USD": "21.50"})
        self.assertEqual(compare_reports(directory, directory)["difference_count"], 0)
