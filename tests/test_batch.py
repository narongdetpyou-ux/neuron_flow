"""Batch-level isolation, persistence, conflict and real-process fault checks."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from neuron_flow.batch import BatchRuntime
from neuron_flow.csv_agents import csv_agent_definitions
from neuron_flow.csv_input import CsvInputError
from tests.batch_fault_agents import (controller_source, fault_definitions,
                                       marker_path, purchase_source)


PROJECT = Path(__file__).resolve().parents[1]


def evidence(name, source, expected, actual, **extra):
    destination = os.environ.get("NEURON_EVIDENCE_DIR")
    if not destination:
        return
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    report = {"scenario": name, "source_csv": source.decode("utf-8-sig"),
              "source_sha256": hashlib.sha256(source).hexdigest(),
              "expected": expected, "actual": actual, **extra}
    (directory / f"{name}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def engine_state(workspace):
    """Read persisted state without starting recovery or creating any events."""
    with sqlite3.connect(Path(workspace) / "state.sqlite3") as database:
        database.row_factory = sqlite3.Row
        result = {}
        for row in database.execute("SELECT * FROM jobs ORDER BY rowid"):
            job = dict(row)
            spec = json.loads(job["spec"])
            identifier = spec["input"]["document_id"]
            job["spec"] = spec
            job["receipt"] = json.loads(job["receipt"]) if job["receipt"] else None
            job["steps"] = {}
            for step_row in database.execute("SELECT * FROM steps WHERE job_id=? ORDER BY rowid", (job["id"],)):
                step = dict(step_row)
                for key in ("output", "error"):
                    step[key] = json.loads(step[key]) if step[key] else None
                job["steps"][step["id"]] = step
            job["events"] = [dict(event) for event in database.execute(
                "SELECT * FROM events WHERE job_id=? ORDER BY sequence", (job["id"],))]
            result[identifier] = job
        return result


def stopped(pid):
    if sys.platform.startswith("linux"):
        path = Path(f"/proc/{pid}/stat")
        try:
            # Linux retains a zombie's PID until its parent reaps it; it no
            # longer executes and must count as stopped in this assertion.
            return path.read_text().split(")", 1)[1].strip().split()[0] == "Z"
        except FileNotFoundError:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def wait_stopped(pid, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stopped(pid):
            return True
        time.sleep(0.02)
    return stopped(pid)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="neuron-batch-test-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def test_invalid_data_does_not_retry_or_prevent_next_document(self):
        source = purchase_source([("INVALID", "จำนวนผิด"), ("GOOD", "ทำต่อ")])
        source = source.replace(
            ",2,0.10,0.20,THB".encode(), ",-1,0.10,0.20,THB".encode(), 1)
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "invalid-isolation")
            result = runtime.run("invalid-isolation")
        first, second = result["documents"]
        self.assertEqual(first["document_status"], "INVALID")
        self.assertEqual(first["engine_status"], "SUCCEEDED")
        self.assertEqual(second["document_status"], "VALID")
        self.assertTrue(all(step["attempts"] == 1 for step in first["steps"].values()))
        evidence("A04_invalid_no_retry", source,
                 {"INVALID": "INVALID", "GOOD": "VALID", "attempts": 1}, result)

    def fault_case(self, identifier, expected_types, evidence_name):
        base = self.workspace / f"{identifier.lower()}-worker"
        source = purchase_source([(identifier, str(base)), ("GOOD-AFTER", "ใบอื่นต้องทำต่อ")])
        with BatchRuntime(self.workspace, agents=fault_definitions(), timeout_s=0.15) as runtime:
            runtime.submit(source, identifier.lower())
            result = runtime.run(identifier.lower())
            workers = [worker.process for worker in runtime.runtime.soma.workers]
            self.assertLessEqual(len(workers), 3)
        first, second = result["documents"]
        self.assertEqual(result["counts"], {"documents": 2, "VALID": 1, "INVALID": 0, "ERROR": 1})
        self.assertEqual(first["document_status"], "ERROR")
        self.assertEqual(first["engine_status"], "FAILED")
        self.assertEqual(first["steps"]["calculate"]["attempts"], 2)
        self.assertIn(first["steps"]["calculate"]["error"]["type"], expected_types)
        self.assertEqual(second["document_status"], "VALID")
        self.assertTrue(all(step["attempts"] <= 2 for d in result["documents"] for step in d["steps"].values()))
        process_observations = []
        for attempt in (1, 2):
            marker = marker_path(base, attempt)
            self.assertTrue(marker.is_file(), f"Fault agent attempt {attempt} was not reached")
            pid = int(marker.read_text())
            ended = wait_stopped(pid)
            self.assertTrue(ended, f"Fault worker {pid} remains alive")
            process_observations.append({"attempt": attempt, "worker_pid": pid, "stopped": ended})
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        evidence(evidence_name, source,
                 {identifier: "ERROR", "GOOD-AFTER": "VALID", "max_attempts": 2},
                 result, processes=process_observations)

    def test_real_hung_worker_exhausts_two_attempts_then_next_document_finishes(self):
        self.fault_case("HANG", {"TimeoutError"}, "A09_hang")

    def test_real_worker_death_exhausts_two_attempts_then_next_document_finishes(self):
        self.fault_case("CRASH", {"ChildProcessError", "EOFError", "ConnectionResetError",
                                  "BrokenPipeError", "OSError"}, "A09_crash")

    def test_real_controller_kill_resumes_without_repeating_completed_work(self):
        source = controller_source(self.workspace)
        process = subprocess.Popen([sys.executable, "-m", "tests.batch_controller_child", str(self.workspace)],
                                   cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = marker_path(self.workspace / "interrupted-worker", 1)
        try:
            deadline = time.monotonic() + 12
            while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.02)
            if not marker.exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=5)
                    self.fail(f"Controller did not reach hung calculation: {stdout!r} {stderr!r}")
                self.fail("Controller did not reach hung calculation within deadline")
            worker_pid = int(marker.read_text())
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            before = engine_state(self.workspace)
            self.assertEqual(before["GOOD-FIRST"]["status"], "SUCCEEDED")
            self.assertEqual(before["RECOVER"]["steps"]["validate"]["status"], "SUCCEEDED")
            self.assertEqual(before["RECOVER"]["steps"]["calculate"]["status"], "RUNNING")
            with BatchRuntime(self.workspace, agents=fault_definitions(), timeout_s=30) as runtime:
                result = runtime.run("controller-recovery")
            after = engine_state(self.workspace)
            self.assertEqual(result["counts"], {"documents": 3, "VALID": 3, "INVALID": 0, "ERROR": 0})
            self.assertEqual(before["GOOD-FIRST"], after["GOOD-FIRST"])
            self.assertEqual(after["RECOVER"]["steps"]["validate"]["attempts"], 1)
            self.assertEqual(after["RECOVER"]["steps"]["calculate"]["attempts"], 2)
            self.assertEqual(after["RECOVER"]["steps"]["verify"]["attempts"], 1)
            self.assertTrue(wait_stopped(worker_pid), "Interrupted controller left an executing orphan worker")
            evidence("A10_controller", source,
                     {"counts": {"documents": 3, "VALID": 3, "INVALID": 0, "ERROR": 0},
                      "completed_work_unchanged": True, "recovered_calculate_attempts": 2},
                     result, before=before, after=after,
                     process_returncode=process.returncode, worker_pid=worker_pid,
                     worker_stopped=stopped(worker_pid), stdout=stdout.decode(), stderr=stderr.decode())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def test_identical_resubmission_preserves_snapshot_history_attempts_and_receipts(self):
        source = purchase_source([("A", "เดิม"), ("B", "รายการที่สอง")])
        with BatchRuntime(self.workspace) as runtime:
            first_submission = runtime.submit(source, "same")
            first = runtime.run("same")
        before = engine_state(self.workspace)
        paths = {job["receipt"]["path"]: Path(job["receipt"]["path"]).stat().st_mtime_ns
                 for job in before.values()}
        with BatchRuntime(self.workspace) as runtime:
            duplicate = runtime.submit(source, "same")
            second = runtime.run("same")
            status = runtime.status("same")
        after = engine_state(self.workspace)
        self.assertTrue(first_submission["created"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(first, second)
        self.assertEqual(second, {key: status[key] for key in second})
        self.assertEqual(before, after)
        self.assertTrue(all(Path(path).stat().st_mtime_ns == modified for path, modified in paths.items()))
        evidence("A11_duplicate", source,
                 {"created_again": False, "snapshot_unchanged": True, "history_unchanged": True},
                 second, before=before, after=after)

    def test_changed_source_under_same_batch_id_conflicts_and_preserves_existing_state(self):
        source = purchase_source([("A", "ต้นฉบับ")])
        changed = purchase_source([("A", "ข้อมูลเปลี่ยน")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "conflict")
            first = runtime.run("conflict")
            before = engine_state(self.workspace)
            with self.assertRaises(ValueError) as raised:
                runtime.submit(changed, "conflict")
            second = runtime.status("conflict")
        self.assertEqual(before, engine_state(self.workspace))
        self.assertEqual(first, {key: second[key] for key in first})
        evidence("A12_conflict", source, {"conflict": True, "preserves_existing": True}, second,
                 changed_source_csv=changed.decode(), error=str(raised.exception))

    def test_changed_agent_version_cannot_reuse_batch(self):
        source = purchase_source([("A", "รุ่นเดิม")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "version")
            runtime.run("version")
        before = engine_state(self.workspace)
        definitions = [replace(d, version=d.version + "-changed") if d.name == "csv_calculate" else d
                       for d in csv_agent_definitions()]
        with BatchRuntime(self.workspace, agents=definitions) as runtime:
            with self.assertRaises(ValueError):
                runtime.submit(source, "version")
            with self.assertRaises(ValueError):
                runtime.run("version")
        self.assertEqual(before, engine_state(self.workspace))

    def test_document_report_written_before_receipt_can_resume_without_rerunning_steps(self):
        source = purchase_source([("A", "บันทึกรายงานแล้วแต่ยังไม่ได้ receipt")])
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, "receipt-window")
            deliver = runtime.runtime.terminal.deliver

            def fail_after_write(report):
                deliver(report)
                raise OSError("Interrupted after document report, before receipt")

            runtime.runtime.terminal.deliver = fail_after_write
            first = runtime.run("receipt-window")
            self.assertEqual(first["status"], "DELIVERY_FAILED")
            document = first["documents"][0]
            self.assertEqual(document["engine_status"], "DELIVERY_FAILED")
            path = self.workspace / "reports" / f"{document['job_id']}.json"
            before_bytes, before_mtime = path.read_bytes(), path.stat().st_mtime_ns
            before = engine_state(self.workspace)
            runtime.runtime.terminal.deliver = deliver
            second = runtime.run("receipt-window")
        after = engine_state(self.workspace)
        self.assertEqual(second["status"], "PROCESSED")
        self.assertEqual(second["documents"][0]["document_status"], "VALID")
        self.assertEqual(before["A"]["steps"], after["A"]["steps"])
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)
        self.assertTrue(all(step["attempts"] == 1 for step in second["documents"][0]["steps"].values()))
        evidence("A10_document_receipt_window", source,
                 {"resume_status": "PROCESSED", "document_status": "VALID", "step_attempts": 1,
                  "report_not_rewritten": True}, second,
                 before=before, after=after, interrupted_snapshot=first)

    def test_invalid_header_rejected_before_creating_document_jobs(self):
        with BatchRuntime(self.workspace) as runtime:
            with self.assertRaises(CsvInputError):
                runtime.submit(b"document_id,wrong\nA,x\n", "header")
        self.assertEqual(engine_state(self.workspace), {})

    def test_generated_batch_id_is_stable_for_identical_bytes(self):
        source = purchase_source([("A", "รหัสจากเนื้อหา")])
        with BatchRuntime(self.workspace) as runtime:
            first = runtime.submit(source)
            second = runtime.submit(source)
        self.assertEqual(first["batch_id"], second["batch_id"])
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])


if __name__ == "__main__":
    unittest.main()
