"""Durable source evidence, human review gate and real batch/CLI handoff."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from neuron_flow import intake
from neuron_flow import intake_cli
from tests.document_fixtures import CSV, RECEIPT


PROJECT = Path(__file__).resolve().parents[1]


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def stage(self, receipt=False):
        return intake.stage_document(self.workspace, RECEIPT.encode() if receipt else CSV,
                                     "receipt.txt" if receipt else "data.csv")

    def test_structured_bundle_reuses_exact_source_and_recovers_without_upload(self):
        result = self.stage()
        self.assertEqual(result["status"], "READY")
        folder = Path(result["bundle"])
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()}
        self.assertEqual(self.stage(), result)
        with patch.object(intake, "prepare_document", side_effect=AssertionError("must not rerun parser")):
            self.assertEqual(self.stage(), result)
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()})
        run = intake.run_document(self.workspace, result["intake_id"])
        self.assertEqual(run["batch"]["counts"]["VALID"], 1)
        self.assertEqual(run["batch"]["certified_totals"], {"USD": "25.00"})
        self.assertEqual(intake.run_document(self.workspace, result["intake_id"]), run)
        queued = intake.stage_document(self.workspace, CSV.replace(b"R-001", b"R-002"), "data.csv")
        submitted = intake.run_document(self.workspace, queued["intake_id"], submit_only=True)
        self.assertEqual(submitted["batch"]["status"], "PENDING")

    def test_receipt_cannot_run_before_review_and_review_is_bound_to_original(self):
        result = self.stage(receipt=True)
        identifier = result["intake_id"]
        folder = Path(result["bundle"])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertTrue((folder / "review_template.csv").exists())
        with self.assertRaisesRegex(ValueError, "REVIEW_REQUIRED"):
            intake.run_document(self.workspace, identifier)
        reviewed = intake.review_document(self.workspace, identifier, CSV, "test reviewer")
        self.assertEqual(reviewed["status"], "REVIEWED")
        self.assertEqual(intake.review_document(self.workspace, identifier, CSV, "test reviewer"), reviewed)
        approval = json.loads((folder / "approval.json").read_bytes())
        self.assertEqual(approval["source_sha256"], hashlib.sha256(RECEIPT.encode()).hexdigest())
        self.assertEqual(intake.run_document(self.workspace, identifier)["batch"]["counts"]["VALID"], 1)
        revision = intake.review_document(self.workspace, identifier, CSV.replace(b"25.00", b"99.00"), "test reviewer")
        self.assertNotEqual(revision["intake_id"], identifier)
        self.assertEqual(revision["source_sha256"], result["source_sha256"])
        self.assertEqual(intake.run_document(self.workspace, revision["intake_id"])["batch"]["counts"]["INVALID"], 1)
        self.assertEqual(intake.run_document(self.workspace, identifier)["batch"]["counts"]["VALID"], 1)
        self.assertEqual(intake.review_document(self.workspace, identifier, CSV.replace(b"25.00", b"99.00"), "test reviewer"), revision)
        approval["csv"] += "\n"
        (folder / "approval.json").write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "REVIEW_CONFLICT"):
            intake.intake_status(self.workspace, identifier)

    def test_review_does_not_certify_an_incorrect_total(self):
        result = self.stage(receipt=True)
        reviewed_csv = CSV.replace(b"25.00", b"999.00")
        intake.review_document(self.workspace, result["intake_id"], reviewed_csv, "reviewer")
        batch = intake.run_document(self.workspace, result["intake_id"])["batch"]
        self.assertEqual(batch["counts"]["INVALID"], 1)
        self.assertEqual(batch["counts"]["VALID"], 0)

    def test_bad_review_rows_reviewer_and_unneeded_review(self):
        structured = self.stage()
        with self.assertRaisesRegex(ValueError, "REVIEW_NOT_NEEDED"):
            intake.review_document(self.workspace, structured["intake_id"], CSV, "reviewer")
        receipt = self.stage(receipt=True)
        for reviewer in ("", " " * 2, "x" * 201, None):
            with self.subTest(reviewer=reviewer), self.assertRaisesRegex(ValueError, "REVIEWER"):
                intake.review_document(self.workspace, receipt["intake_id"], CSV, reviewer)
        for data in (CSV.split(b"\n")[0] + b"\n", CSV.replace(b"R-001", b"")):
            with self.assertRaisesRegex(ValueError, "REVIEW_ROWS"):
                intake.review_document(self.workspace, receipt["intake_id"], data, "reviewer")
        real_json = intake._json
        with patch.object(intake, "_json", side_effect=lambda value: b"x" * (16 * 1024 * 1024 + 1) if "csv" in value else real_json(value)), self.assertRaisesRegex(ValueError, "REVIEW_LIMIT"):
            intake.review_document(self.workspace, receipt["intake_id"], CSV, "reviewer")

    def test_source_normalized_identity_and_manifest_tampering_detected(self):
        for name, change, code in (
            ("original.bin", lambda data: data + b"\n", "source SHA"),
            ("normalized.csv", lambda data: data + b"\n", "normalized CSV SHA"),
            ("manifest.json", lambda data: data.replace(b"document-intake-v1", b"document-intake-v9"), "incompatible manifest"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                result = intake.stage_document(temporary, CSV, "data.csv")
                path = Path(result["bundle"]) / name
                path.write_bytes(change(path.read_bytes()))
                with self.assertRaisesRegex(ValueError, code):
                    intake.intake_status(temporary, result["intake_id"])
        result = self.stage()
        path = Path(result["bundle"]) / "manifest.json"
        original = json.loads(path.read_bytes())
        changed = json.loads(path.read_bytes())
        changed["binding"]["language"] = "other"
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "identity does not match"):
            intake.intake_status(self.workspace, result["intake_id"])
        original["source_sha256"] = "wrong"
        path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "source SHA"):
            intake.intake_status(self.workspace, result["intake_id"])
        with self.assertRaisesRegex(ValueError, "INTAKE_ID"):
            intake.intake_status(self.workspace, "../../file")


class IntakeCliTests(unittest.TestCase):
    def test_actual_receipt_review_run_status_and_structured_import_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            source = Path(temporary) / "receipt.txt"
            source.write_text(RECEIPT)
            reviewed = Path(temporary) / "reviewed.csv"
            reviewed.write_bytes(CSV)
            def command(*arguments):
                return subprocess.run([sys.executable, "-m", "neuron_flow", *arguments], cwd=PROJECT,
                                      text=True, capture_output=True, timeout=30)
            options = ("--workspace", str(workspace))
            staged = command("intake", str(source), *options)
            self.assertEqual(staged.returncode, 0, staged.stderr)
            identifier = json.loads(staged.stdout)["intake_id"]
            source.unlink()
            blocked = command("intake-run", identifier, *options)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("REVIEW_REQUIRED", blocked.stderr)
            approved = command("intake-review", identifier, str(reviewed), "--reviewer", "synthetic tester", *options)
            self.assertEqual(approved.returncode, 0, approved.stderr)
            self.assertEqual(json.loads(approved.stdout)["status"], "REVIEWED")
            status = command("intake-status", identifier, *options)
            self.assertEqual(json.loads(status.stdout)["status"], "REVIEWED")
            run = command("intake-run", identifier, *options)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["batch"]["counts"]["VALID"], 1)
            staged = command("intake", str(reviewed), *options)
            identifier = json.loads(staged.stdout)["intake_id"]
            queued = command("intake-run", identifier, "--submit-only", *options)
            self.assertEqual(queued.returncode, 0, queued.stderr)
            self.assertEqual(json.loads(queued.stdout)["batch"]["status"], "PENDING")
            listed = command("adapters")
            self.assertIn("s3", json.loads(listed.stdout)["sources"])

    def test_connector_cli_redacts_missing_credentials(self):
        result = subprocess.run([sys.executable, "-m", "neuron_flow", "connector-fetch", "google-drive", "file123",
                                 "--filename", "receipt.pdf", "--token-env", "NEURON_MISSING_TOKEN"],
                                cwd=PROJECT, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        error = json.loads(result.stderr)
        self.assertEqual(error["error"], "ConnectorError")
        self.assertFalse(error["retryable"])

    def test_cli_service_dispatch_with_fake_transport_and_explicit_destinations(self):
        import argparse
        parser = argparse.ArgumentParser()
        intake_cli.add_commands(parser.add_subparsers(dest="command"))
        with tempfile.TemporaryDirectory() as temporary:
            args = parser.parse_args(["connector-fetch", "dropbox", "/source.csv", "--filename", "source.csv", "--workspace", temporary])
            with patch.object(intake_cli, "fetch_source", return_value=(CSV, {"provider": "dropbox"})):
                self.assertEqual(intake_cli.execute(args)["status"], "READY")
            args.provider = "google-sheets"
            args.filename = "bad.pdf"
            with self.assertRaisesRegex(ValueError, "SHEETS_FORMAT"):
                intake_cli.execute(args)
            source = Path(temporary) / "report.csv"
            source.write_bytes(CSV)
            args = parser.parse_args(["sheets-publish", str(source), "sheet", "--range", "Report!A1:G2"])
            with patch.object(intake_cli, "publish_sheets", return_value={"status": "PUBLISHED"}) as publish:
                self.assertEqual(intake_cli.execute(args)["status"], "PUBLISHED")
                publish.assert_called_once_with(CSV, "sheet", "Report!A1:G2", token_env="GOOGLE_ACCESS_TOKEN")
