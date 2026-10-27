import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from neuron_flow import AgentDefinition, Runtime, SpecError
from neuron_flow.agents import (default_agents, invoice_workflow, validate_calculation,
                                validate_extract)
from neuron_flow.__main__ import DEMO_DOCUMENT
from neuron_flow.model import decode
from neuron_flow.storage import WorkspaceBusy
from tests.fault_agents import validate_ok, validate_timed, reject_with_false, modifies_output


PROJECT = Path(__file__).resolve().parents[1]


def definitions():
    names = ("ok", "transient_once", "permanent", "unexpected", "hangs_once", "hangs_always",
             "crashes_once", "wrong", "wrong_type", "not_json", "nan_result", "huge_result")
    return [AgentDefinition(name, f"tests.fault_agents:{name}", validate_ok) for name in names] + [
        AgentDefinition("timed", "tests.fault_agents:timed", validate_timed)]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def execute(self, steps, *, agents=None, data=None, workers=3, job_id="test_job"):
        with Runtime(self.workspace, max_workers=workers, agents=agents or definitions()) as runtime:
            runtime.submit({"job_id": job_id, "input": data or {}, "steps": steps})
            return runtime.run(job_id)

    def test_invoice_happy_path_exact_money_and_verified_file(self):
        with Runtime(self.workspace) as runtime:
            runtime.submit(invoice_workflow(DEMO_DOCUMENT))
            result = runtime.run("invoice_demo")
        self.assertEqual(result["status"], "SUCCEEDED")
        verified = result["steps"]["verify"]["output"]
        self.assertEqual(verified["total"], "310.70")
        self.assertIs(verified["verified"], True)
        contents = Path(result["receipt"]["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(contents).hexdigest(), result["receipt"]["sha256"])
        self.assertEqual(json.loads(contents)["status"], "SUCCEEDED")

    def test_decimal_rounding_boundary(self):
        document = {"document_id": "precision", "items": [
            {"description": "small", "quantity": 3, "unit_price": "0.10"},
            {"description": "large", "quantity": 1000000, "unit_price": "1000000000000.00"}]}
        with Runtime(self.workspace) as runtime:
            runtime.submit(invoice_workflow(document))
            result = runtime.run("invoice_demo")
        self.assertEqual(result["steps"]["verify"]["output"]["total"], "1000000000000000000.30")

    def test_bad_input_fails_without_retry_and_blocks_dependents(self):
        document = copy.deepcopy(DEMO_DOCUMENT)
        document["items"][0]["quantity"] = -1
        with Runtime(self.workspace) as runtime:
            runtime.submit(invoice_workflow(document))
            result = runtime.run("invoice_demo")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["steps"]["extract"]["attempts"], 1)
        self.assertEqual(result["steps"]["calculate"]["status"], "BLOCKED")
        self.assertEqual(result["steps"]["verify"]["attempts"], 0)

    def test_float_price_rejected_instead_of_silently_rounding(self):
        document = copy.deepcopy(DEMO_DOCUMENT)
        document["items"][0]["unit_price"] = 0.1
        with Runtime(self.workspace) as runtime:
            runtime.submit(invoice_workflow(document))
            result = runtime.run("invoice_demo")
        self.assertEqual(result["status"], "FAILED")

    def test_wrong_total_rejected_before_terminal_success(self):
        agents = default_agents() + [AgentDefinition("wrong_total", "tests.fault_agents:wrong_total", validate_calculation)]
        spec = invoice_workflow(DEMO_DOCUMENT)
        spec["steps"][1]["agent"] = "wrong_total"
        with Runtime(self.workspace, agents=agents) as runtime:
            runtime.submit(spec)
            result = runtime.run("invoice_demo")
        self.assertEqual(result["steps"]["calculate"]["error"]["type"], "OutputValidationError")
        self.assertEqual(result["steps"]["verify"]["status"], "BLOCKED")
        self.assertEqual(json.loads(Path(result["receipt"]["path"]).read_bytes())["status"], "FAILED")

    def test_output_contract_distinguishes_bool_from_integer(self):
        agents = default_agents() + [AgentDefinition("wrong_extract", "tests.fault_agents:wrong_extract_type", validate_extract)]
        document = copy.deepcopy(DEMO_DOCUMENT)
        document["items"][0]["quantity"] = 1
        spec = invoice_workflow(document)
        spec["steps"][0]["agent"] = "wrong_extract"
        with Runtime(self.workspace, agents=agents) as runtime:
            runtime.submit(spec)
            result = runtime.run("invoice_demo")
        self.assertEqual(result["steps"]["extract"]["error"]["type"], "OutputValidationError")

    def test_transient_failure_retries_then_succeeds(self):
        result = self.execute([{"id": "a", "agent": "transient_once"}])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["steps"]["a"]["attempts"], 2)

    def test_real_hung_process_terminated_and_replaced(self):
        start = time.monotonic()
        result = self.execute([{"id": "a", "agent": "hangs_once", "timeout_s": 0.15}])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["steps"]["a"]["attempts"], 2)
        self.assertLess(time.monotonic() - start, 10)

    def test_timeout_attempt_budget_is_enforced(self):
        result = self.execute([{"id": "a", "agent": "hangs_always", "timeout_s": 0.1, "max_attempts": 2}])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["steps"]["a"]["attempts"], 2)
        self.assertEqual(result["steps"]["a"]["error"]["type"], "TimeoutError")

    def test_actual_worker_crash_does_not_crash_controller(self):
        result = self.execute([{"id": "a", "agent": "crashes_once"}])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["steps"]["a"]["attempts"], 2)

    def test_permanent_error_does_not_retry(self):
        result = self.execute([{"id": "a", "agent": "permanent", "max_attempts": 5}])
        self.assertEqual(result["steps"]["a"]["attempts"], 1)
        self.assertEqual(result["status"], "FAILED")

    def test_programming_error_is_not_blindly_retried(self):
        result = self.execute([{"id": "a", "agent": "unexpected"}])
        self.assertEqual(result["steps"]["a"]["attempts"], 1)
        self.assertEqual(result["steps"]["a"]["error"]["type"], "ZeroDivisionError")

    def test_wrong_output_does_not_count_as_success(self):
        for agent in ("wrong", "wrong_type", "not_json", "nan_result", "huge_result"):
            with self.subTest(agent=agent):
                result = self.execute([{"id": "a", "agent": agent}], job_id=agent)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["steps"]["a"]["attempts"], 1)

    def test_independent_branch_survives_failed_branch(self):
        result = self.execute([
            {"id": "bad", "agent": "permanent"},
            {"id": "blocked", "agent": "ok", "depends_on": ["bad"]},
            {"id": "good", "agent": "ok"},
            {"id": "good_child", "agent": "ok", "depends_on": ["good"]},
        ])
        self.assertEqual(result["steps"]["blocked"]["status"], "BLOCKED")
        self.assertEqual(result["steps"]["good_child"]["status"], "SUCCEEDED")

    def test_parallel_load_respects_capacity_and_reuses_workers(self):
        result = self.execute([
            {"id": f"s{i}", "agent": "timed", "params": {"duration": 0.06}} for i in range(30)
        ], workers=3)
        self.assertEqual(result["status"], "SUCCEEDED")
        intervals, pids = [], set()
        for step in result["steps"].values():
            output = step["output"]
            pids.add(output["pid"])
            intervals.extend([(output["started"], 1), (output["finished"], -1)])
        active = peak = 0
        for _, change in sorted(intervals, key=lambda pair: (pair[0], pair[1])):
            active += change
            peak = max(peak, active)
        self.assertGreaterEqual(peak, 2)
        self.assertLessEqual(peak, 3)
        self.assertEqual(result["peak_workers"], 3)
        self.assertEqual(len(pids), 3)

    def test_buffered_timely_result_not_misclassified_as_timeout(self):
        result = self.execute([
            {"id": "fast", "agent": "ok", "timeout_s": 0.05},
            {"id": "other", "agent": "timed", "params": {"duration": 0.1}},
        ], workers=2)
        self.assertEqual(result["steps"]["fast"]["status"], "SUCCEEDED")
        self.assertEqual(result["steps"]["fast"]["attempts"], 1)

    def test_dependency_order_enforced_even_when_declared_in_reverse(self):
        result = self.execute([
            {"id": "child", "agent": "timed", "depends_on": ["parent"]},
            {"id": "parent", "agent": "timed"},
        ])
        parent, child = result["steps"]["parent"]["output"], result["steps"]["child"]["output"]
        self.assertGreaterEqual(child["started"], parent["finished"])

    def test_duplicate_submission_and_repeated_run_reuse_success(self):
        spec = {"job_id": "duplicate", "input": {"x": 1}, "steps": [{"id": "a", "agent": "ok"}]}
        with Runtime(self.workspace, agents=definitions()) as runtime:
            self.assertTrue(runtime.submit(spec)["created"])
            first = runtime.run("duplicate")
            path = Path(first["receipt"]["path"])
            before = path.stat().st_mtime_ns
            self.assertFalse(runtime.submit(copy.deepcopy(spec))["created"])
            second = runtime.run("duplicate")
            events = runtime.synapse.events_for("monitor", "duplicate")
        self.assertEqual(first["receipt"], second["receipt"])
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(second["steps"]["a"]["attempts"], 1)
        self.assertEqual(sum(event["kind"] == "step.running" for event in events), 1)

    def test_same_id_different_input_is_rejected(self):
        spec = {"job_id": "duplicate", "steps": [{"id": "a", "agent": "ok"}]}
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit(spec)
            spec["input"] = {"changed": True}
            with self.assertRaises(ValueError):
                runtime.submit(spec)

    def test_input_is_snapshot_not_mutable_caller_reference(self):
        spec = invoice_workflow(copy.deepcopy(DEMO_DOCUMENT))
        with Runtime(self.workspace) as runtime:
            runtime.submit(spec)
            spec["input"]["items"][0]["unit_price"] = "999.99"
            result = runtime.run("invoice_demo")
        self.assertEqual(result["steps"]["verify"]["output"]["total"], "310.70")

    def test_events_only_delivered_to_relevant_recipient(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({"job_id": "routing", "steps": [
                {"id": "a", "agent": "ok"},
                {"id": "b", "agent": "ok", "depends_on": ["a"]},
                {"id": "c", "agent": "ok"}]})
            runtime.run("routing")
            messages = runtime.synapse.events_for("step:b", "routing")
            self.assertTrue(messages)
            self.assertTrue(all(event["step_id"] == "a" for event in messages))
            self.assertEqual(runtime.synapse.events_for("step:unrelated", "routing"), [])
            last = messages[-1]["sequence"]
            self.assertEqual(runtime.synapse.events_for("step:b", "routing", last), [])

    def test_resume_preserves_completed_steps_and_attempt_budget(self):
        spec = {"job_id": "resume", "steps": [
            {"id": "a", "agent": "ok"}, {"id": "b", "agent": "ok", "depends_on": ["a"]}]}
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit(spec)
            runtime.store.transition("resume", "a", "SUCCEEDED", 1, output={"ok": True})
            runtime.store.transition("resume", "b", "RUNNING", 1)
        with Runtime(self.workspace, agents=definitions()) as runtime:
            result = runtime.run("resume")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["steps"]["a"]["attempts"], 1)
        self.assertEqual(result["steps"]["b"]["attempts"], 2)

    def test_interrupted_final_attempt_is_not_given_extra_retry(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({"job_id": "exhausted", "steps": [{"id": "a", "agent": "ok", "max_attempts": 1}]})
            runtime.store.transition("exhausted", "a", "RUNNING", 1)
        with Runtime(self.workspace, agents=definitions()) as runtime:
            result = runtime.run("exhausted")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["steps"]["a"]["attempts"], 1)

    def test_real_controller_kill_and_restart(self):
        process = subprocess.Popen([sys.executable, "-m", "tests.controller_child", str(self.workspace)],
                                   cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 12
            pid_file = self.workspace / "child.pid"
            while not pid_file.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.02)
            self.assertTrue(pid_file.exists(), "Child did not reach the intentionally hung task")
            worker_pid = int(pid_file.read_text())
            process.kill()
            process.communicate(timeout=5)
            with Runtime(self.workspace, agents=definitions()) as runtime:
                result = runtime.run("crash_recovery")
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result["steps"]["kept"]["attempts"], 1)
            self.assertEqual(result["steps"]["recover"]["attempts"], 2)
            if sys.platform.startswith("linux"):
                deadline = time.monotonic() + 3
                path = Path(f"/proc/{worker_pid}/stat")
                while path.exists() and time.monotonic() < deadline:
                    if path.read_text().split()[2] == "Z":
                        break
                    time.sleep(0.02)
                self.assertTrue(not path.exists() or path.read_text().split()[2] == "Z",
                                "Orphan worker is still running")
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def test_terminal_failure_retries_delivery_without_rerunning_agents(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({"job_id": "delivery", "steps": [{"id": "a", "agent": "ok"}]})
            deliver = runtime.terminal.deliver
            def fail(_report):
                raise OSError("Disk unavailable")
            runtime.terminal.deliver = fail
            first = runtime.run("delivery")
            self.assertEqual(first["status"], "DELIVERY_FAILED")
            self.assertIsNone(first["receipt"])
            runtime.terminal.deliver = deliver
            second = runtime.run("delivery")
        self.assertEqual(second["status"], "SUCCEEDED")
        self.assertEqual(second["steps"]["a"]["attempts"], 1)

    def test_file_written_before_receipt_failure_is_reused(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({"job_id": "window", "steps": [{"id": "a", "agent": "ok"}]})
            deliver = runtime.terminal.deliver
            def fail_after_write(report):
                deliver(report)
                raise OSError("Stopped before persisting receipt")
            runtime.terminal.deliver = fail_after_write
            self.assertEqual(runtime.run("window")["status"], "DELIVERY_FAILED")
            path = self.workspace / "reports" / "window.json"
            modified = path.stat().st_mtime_ns
            runtime.terminal.deliver = deliver
            result = runtime.run("window")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_conflicting_output_is_preserved_and_reported(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({"job_id": "conflict", "steps": [{"id": "a", "agent": "ok"}]})
            path = self.workspace / "reports" / "conflict.json"
            path.write_text("existing different report", encoding="utf-8")
            result = runtime.run("conflict")
        self.assertEqual(result["status"], "DELIVERY_FAILED")
        self.assertEqual(path.read_text(), "existing different report")

    def test_workspace_rejects_two_controllers_and_releases_lock(self):
        with Runtime(self.workspace):
            with self.assertRaises(WorkspaceBusy):
                Runtime(self.workspace)
        with Runtime(self.workspace) as runtime:
            self.assertFalse(runtime.closed)

    def test_changed_agent_version_cannot_reuse_previous_results(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({"job_id": "version", "steps": [{"id": "a", "agent": "ok"}]})
        changed = [AgentDefinition("ok", "tests.fault_agents:ok", validate_ok, version="2")]
        with Runtime(self.workspace, agents=changed) as runtime:
            with self.assertRaises(SpecError):
                runtime.run("version")

    def test_runtime_close_stops_all_worker_processes(self):
        runtime = Runtime(self.workspace, agents=definitions())
        runtime.submit({"job_id": "close", "steps": [{"id": "a", "agent": "ok"}]})
        runtime.run("close")
        processes = [worker.process for worker in runtime.soma.workers]
        runtime.close()
        self.assertTrue(all(not process.is_alive() for process in processes))
        runtime.close()
        with self.assertRaises(RuntimeError):
            runtime.status("close")

    def test_dendrite_selects_workflow_and_deduplicates_raw_input(self):
        with Runtime(self.workspace) as runtime:
            first = runtime.ingest(DEMO_DOCUMENT)
            second = runtime.ingest(DEMO_DOCUMENT)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["job_id"], second["job_id"])
            result = runtime.run(first["job_id"])
            self.assertEqual(result["steps"]["verify"]["output"]["total"], "310.70")
            with self.assertRaises(SpecError):
                runtime.ingest("unstructured text")

    def test_validator_false_is_not_ignored(self):
        result = self.execute([{"id": "a", "agent": "ok"}],
                              agents=[AgentDefinition("ok", "tests.fault_agents:ok", reject_with_false)])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["steps"]["a"]["error"]["type"], "OutputValidationError")

    def test_validator_cannot_modify_output(self):
        result = self.execute([{"id": "a", "agent": "ok"}],
                              agents=[AgentDefinition("ok", "tests.fault_agents:ok", modifies_output)])
        self.assertEqual(result["status"], "FAILED")

    def test_cli_workflow_invoice_status_and_duplicate_invocation(self):
        base = [sys.executable, "-m", "neuron_flow"]
        for command in (
            ["run", "examples/workflow.json"],
            ["run", "examples/workflow.json"],
            ["invoice", "examples/invoice.json", "--job-id", "raw_invoice"],
            ["status", "raw_invoice"],
        ):
            completed = subprocess.run(base + command + ["--workspace", str(self.workspace)],
                                       cwd=PROJECT, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertTrue(all(step["attempts"] == 1 for step in result["steps"].values()))

    def test_cli_invalid_json_is_a_clean_nonzero_failure(self):
        path = self.workspace / "invalid.json"
        path.write_text('{"job_id":"one","job_id":"two","steps":[]}', encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "neuron_flow", "run", str(path),
                                 "--workspace", str(self.workspace / "runtime")],
                                cwd=PROJECT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "SpecError")


class ContractTests(unittest.TestCase):
    def test_strict_json_rejects_duplicates_nonfinite_and_invalid_encoding(self):
        for value in ('{"a":1,"a":2}', '{"n":NaN}', '{"n":Infinity}', b"\xff", '{"x":'):
            with self.subTest(value=value), self.assertRaises(SpecError):
                decode(value)

    def test_invalid_workflows_fail_before_any_execution(self):
        base = {"job_id": "contract", "steps": [{"id": "a", "agent": "echo"}]}
        changes = [
            {"job_id": "../escape"}, {"steps": []},
            {"steps": [{"id": "a", "agent": "missing"}]},
            {"steps": [{"id": "a", "agent": "echo", "depends_on": ["a"]}]},
            {"steps": [{"id": "a", "agent": "echo", "depends_on": ["missing"]}]},
            {"steps": [{"id": "a", "agent": "echo"}, {"id": "a", "agent": "echo"}]},
            {"steps": [{"id": "a", "agent": "echo", "timeout_s": float("nan")}]},
            {"steps": [{"id": "a", "agent": "echo", "max_attempts": True}]},
            {"steps": [{"id": "a", "agent": "echo", "retry_delay_s": -1}]},
            {"steps": [{"id": "a", "agent": "echo", "unknown": "field"}]},
            {"input": {"bad": float("inf")}}, {"input": {"big": "x" * 1_100_000}},
        ]
        with tempfile.TemporaryDirectory() as workspace, Runtime(workspace) as runtime:
            for change in changes:
                with self.subTest(change=list(change)):
                    with self.assertRaises(SpecError):
                        runtime.submit({**base, **change})
            self.assertEqual(runtime.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_invalid_worker_limits(self):
        with tempfile.TemporaryDirectory() as workspace:
            for limit in (0, -1, 33, True, 1.5):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    Runtime(workspace, max_workers=limit)


if __name__ == "__main__":
    unittest.main()
