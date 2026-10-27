"""Real recovery and immutable report integration checks for CSV batches."""

import base64
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from neuron_flow.batch import BatchRuntime
from tests.batch_delivery_child import delivery_source
from tests.batch_fault_agents import fault_definitions, purchase_source
from tests.test_batch import engine_state, evidence


PROJECT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"source.csv", "summary.csv", "details.json"}


def artifact_state(workspace, batch_id):
    directory = Path(workspace) / "batch_reports" / batch_id
    return {name: {"bytes": (directory / name).read_bytes(),
                   "mtime_ns": (directory / name).stat().st_mtime_ns}
            for name in sorted(ARTIFACTS)}


def durable_artifact_evidence(state):
    return {name: {"sha256": hashlib.sha256(value["bytes"]).hexdigest(),
                   "size_bytes": len(value["bytes"]), "mtime_ns": value["mtime_ns"]}
            for name, value in state.items()}


def read_details(workspace, batch_id):
    return json.loads((Path(workspace) / "batch_reports" / batch_id / "details.json").read_text(encoding="utf-8"))


def read_summary(workspace, batch_id):
    with (Path(workspace) / "batch_reports" / batch_id / "summary.csv").open(
            encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class BatchDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="neuron-delivery-test-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def check_receipt(self, result, source):
        self.assertEqual(result["status"], "DELIVERED")
        artifacts = result["receipt"]["artifacts"]
        self.assertEqual(set(artifacts), ARTIFACTS)
        for name, receipt in artifacts.items():
            path = Path(receipt["path"])
            self.assertTrue(path.is_absolute())
            self.assertEqual(path, self.workspace / "batch_reports" / result["batch_id"] / name)
            data = path.read_bytes()
            self.assertEqual(receipt["bytes"], len(data))
            self.assertEqual(receipt["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(Path(artifacts["source.csv"]["path"]).read_bytes(), source)

    def test_reports_have_verified_receipts_and_trace_every_grouped_or_ungrouped_row(self):
        source = b"\xef\xbb\xbf" + purchase_source([("GOOD", "หลายบรรทัด\nมี comma, อยู่ด้วย"),
                                                    ("", "รหัสเอกสารหาย")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "traceability")
            result = runtime.deliver("traceability")
        self.check_receipt(result, source)
        details = read_details(self.workspace, "traceability")
        summary = read_summary(self.workspace, "traceability")
        self.assertEqual(details["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(details["input_rows"], 2)
        self.assertEqual(details["counts"], {"documents": 1, "VALID": 1, "INVALID": 0, "ERROR": 0})
        self.assertEqual(details["documents"][0]["source_rows"], [2])
        self.assertEqual(details["documents"][0]["source_records"][0]["fields"]["description"],
                         "หลายบรรทัด\nมี comma, อยู่ด้วย")
        self.assertEqual(details["ungrouped_rows"][0]["source_row"], 4)
        self.assertEqual(result["ungrouped_rows"], 1)
        self.assertEqual(summary[0]["document_id"], "GOOD")
        self.assertEqual(summary[0]["document_status"], "VALID")
        for field in ("declared_total", "computed_total", "difference", "error_count", "source_rows"):
            self.assertIn(field, summary[0])
        evidence("A08_reports_traceability", source,
                 {"documents": 1, "ungrouped_row": 4, "grouped_row": 2, "hashes_match": True},
                 details, receipt=result["receipt"], summary=summary,
                 source_bytes_base64=base64.b64encode(source).decode("ascii"))

    def test_repeated_delivery_preserves_files_steps_events_and_receipt(self):
        source = purchase_source([("GOOD", "ส่งซ้ำได้")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "repeat-delivery")
            first = runtime.deliver("repeat-delivery")
        before_files = artifact_state(self.workspace, "repeat-delivery")
        before_engine = engine_state(self.workspace)
        with BatchRuntime(self.workspace) as runtime:
            second = runtime.deliver("repeat-delivery")
        self.assertEqual(first, second)
        self.assertEqual(before_files, artifact_state(self.workspace, "repeat-delivery"))
        self.assertEqual(before_engine, engine_state(self.workspace))
        evidence("A11_repeat_delivery", source,
                 {"receipt_unchanged": True, "files_unchanged": True, "engine_unchanged": True},
                 second, artifacts=durable_artifact_evidence(before_files))

    def test_preexisting_identical_source_artifact_is_reused_after_partial_delivery(self):
        source = purchase_source([("GOOD", "ไฟล์เดียวถูกบันทึกก่อนหยุด")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "partial")
            runtime.run("partial")
        directory = self.workspace / "batch_reports" / "partial"
        directory.mkdir(parents=True)
        path = directory / "source.csv"
        path.write_bytes(source)
        modified = path.stat().st_mtime_ns
        before_engine = engine_state(self.workspace)
        with BatchRuntime(self.workspace) as runtime:
            result = runtime.deliver("partial")
        self.check_receipt(result, source)
        self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertEqual(before_engine, engine_state(self.workspace))
        evidence("A10_partial_delivery", source,
                 {"source_not_rewritten": True, "engine_unchanged": True, "status": "DELIVERED"},
                 result)

    def test_conflicting_existing_report_is_preserved_and_delivery_is_rejected(self):
        source = purchase_source([("GOOD", "รักษาไฟล์ขัดแย้ง")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "preexisting-conflict")
            runtime.run("preexisting-conflict")
            directory = self.workspace / "batch_reports" / "preexisting-conflict"
            directory.mkdir(parents=True)
            path = directory / "summary.csv"
            path.write_bytes(b"conflicting existing report\n")
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaises(ValueError):
                runtime.deliver("preexisting-conflict")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_corrupt_cached_report_is_detected_and_preserved(self):
        source = purchase_source([("GOOD", "ตรวจไฟล์เมื่อใช้ receipt ซ้ำ")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "corrupt-cached")
            runtime.deliver("corrupt-cached")
        path = self.workspace / "batch_reports" / "corrupt-cached" / "summary.csv"
        path.write_bytes(b"tampered after receipt\n")
        before = path.read_bytes(), path.stat().st_mtime_ns
        before_engine = engine_state(self.workspace)
        with BatchRuntime(self.workspace) as runtime:
            with self.assertRaises(ValueError):
                runtime.deliver("corrupt-cached")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(before_engine, engine_state(self.workspace))

    def test_error_document_remains_visible_when_batch_report_delivery_succeeds(self):
        source = purchase_source([("CRASH", str(self.workspace / "crash-report")),
                                  ("GOOD", "ยอดที่รับรองได้")])
        with BatchRuntime(self.workspace, agents=fault_definitions(), timeout_s=0.15) as runtime:
            runtime.submit(source, "error-visible")
            result = runtime.deliver("error-visible")
        self.check_receipt(result, source)
        self.assertEqual(result["counts"], {"documents": 2, "VALID": 1, "INVALID": 0, "ERROR": 1})
        self.assertEqual(result["certified_total"], "0.20")
        details = read_details(self.workspace, "error-visible")
        summary = read_summary(self.workspace, "error-visible")
        self.assertEqual([d["document_status"] for d in details["documents"]], ["ERROR", "VALID"])
        self.assertEqual([d["document_status"] for d in summary], ["ERROR", "VALID"])
        self.assertEqual(details["documents"][0]["engine_status"], "FAILED")
        self.assertEqual(details["counts"]["documents"], sum(details["counts"][key] for key in ("VALID", "INVALID", "ERROR")))
        evidence("A09_error_report", source,
                 {"delivery_status": "DELIVERED", "ERROR": 1, "VALID": 1, "certified_total": "0.20"},
                 details, receipt=result["receipt"], summary=summary)

    def test_pending_document_delivery_cannot_be_frozen_into_final_batch_reports(self):
        source = purchase_source([("GOOD", "พื้นที่เขียนรายงานรายใบไม่พร้อม")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "pending-document")
            deliver = runtime.runtime.terminal.deliver

            def fail(_report):
                raise OSError("Document report unavailable")

            runtime.runtime.terminal.deliver = fail
            with self.assertRaises(RuntimeError):
                runtime.deliver("pending-document")
            self.assertFalse((self.workspace / "batch_reports" / "pending-document" / "details.json").exists())
            runtime.runtime.terminal.deliver = deliver
            result = runtime.deliver("pending-document")
        self.check_receipt(result, source)
        self.assertEqual(result["counts"]["VALID"], 1)
        self.assertTrue(all(step["attempts"] == 1 for step in read_details(
            self.workspace, "pending-document")["documents"][0]["steps"].values()))

    def test_real_controller_kill_after_all_reports_before_receipt_reuses_files_and_work(self):
        source = delivery_source()
        process = subprocess.Popen([sys.executable, "-m", "tests.batch_delivery_child", str(self.workspace)],
                                   cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = self.workspace / "delivery.ready"
        try:
            deadline = time.monotonic() + 12
            while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.02)
            if not marker.exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=5)
                    self.fail(f"Delivery controller exited before receipt boundary: {stdout!r} {stderr!r}")
                self.fail("Delivery controller did not reach the receipt boundary")
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            with sqlite3.connect(self.workspace / "state.sqlite3") as database:
                payload, receipt = database.execute(
                    "SELECT payload,receipt FROM csv_batches WHERE id='delivery-window'").fetchone()
            self.assertIsNotNone(payload)
            self.assertIsNone(receipt)
            before_files = artifact_state(self.workspace, "delivery-window")
            before_engine = engine_state(self.workspace)
            with BatchRuntime(self.workspace) as runtime:
                result = runtime.deliver("delivery-window")
            self.check_receipt(result, source)
            after_files = artifact_state(self.workspace, "delivery-window")
            after_engine = engine_state(self.workspace)
            self.assertEqual(before_files, after_files)
            self.assertEqual(before_engine, after_engine)
            evidence("A10_batch_receipt_window", source,
                     {"status": "DELIVERED", "receipt_before": None, "files_unchanged": True,
                      "steps_and_events_unchanged": True}, result,
                     before=before_engine, after=after_engine,
                     artifacts_before=durable_artifact_evidence(before_files),
                     artifacts_after=durable_artifact_evidence(after_files),
                     process_returncode=process.returncode, stdout=stdout.decode(), stderr=stderr.decode())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
