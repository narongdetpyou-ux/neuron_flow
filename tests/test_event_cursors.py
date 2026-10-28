"""Regression coverage for bounded SQLite event cursors and CLI rejection."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from neuron_flow.storage import Store


PROJECT = Path(__file__).resolve().parents[1]


class EventCursorTests(unittest.TestCase):
    def test_signed_int64_endpoints_and_normal_pagination(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        store.submit({"job_id": "cursor", "input": {}, "steps": []})
        store.job_status("cursor", "SUCCEEDED")
        events = store.events_for("monitor", "cursor", -(2 ** 63))
        self.assertEqual([event["kind"] for event in events],
                         ["job.submitted", "job.succeeded"])
        self.assertEqual(store.events_for("monitor", "cursor", 0), events)
        self.assertEqual(store.events_for("monitor", "cursor", events[0]["sequence"]),
                         events[1:])
        self.assertEqual(store.events_for("monitor", "cursor", 2 ** 63 - 1), [])
        self.assertEqual(store.events_for("monitor", "nonexistent", -(2 ** 63)), [])

    def test_python_api_rejects_out_of_range_and_non_integer_cursors(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        for after in (-(2 ** 63) - 1, 2 ** 63, -(10 ** 100), 10 ** 100,
                      True, False, 1.5, "1", None):
            with self.subTest(after=after):
                with self.assertRaisesRegex(ValueError, "signed 64-bit range"):
                    store.events_for("monitor", "nonexistent", after)

    def test_cli_rejects_invalid_cursors_as_json_without_creating_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "must-not-exist"
            for after in (-(2 ** 63) - 1, 2 ** 63, -(10 ** 100), 10 ** 100):
                with self.subTest(after=after):
                    result = subprocess.run(
                        [sys.executable, "-B", "-m", "neuron_flow", "events", "unknown",
                         "--after", str(after), "--workspace", str(workspace)],
                        cwd=PROJECT, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")
                    error = json.loads(result.stderr)
                    self.assertEqual(error["error"], "ValueError")
                    self.assertIn("signed 64-bit range", error["message"])
                    self.assertFalse(workspace.exists())

    def test_cli_accepts_int64_endpoints_for_unknown_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            for after in (-(2 ** 63), 0, 2 ** 63 - 1):
                with self.subTest(after=after):
                    result = subprocess.run(
                        [sys.executable, "-B", "-m", "neuron_flow", "events", "unknown",
                         "--after", str(after), "--workspace", temporary],
                        cwd=PROJECT, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), [])
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
