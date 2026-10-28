"""Benchmark reporting must reject incorrect results and exercise real CLI recovery."""

import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.benchmark_runtime import (
    check_result,
    database_state,
    interrupted_sample,
    make_source,
    normal_sample,
    percentile,
)


class RuntimeBenchmarkTests(unittest.TestCase):
    def test_source_total_is_independent_integer_satang(self):
        source, total = make_source(3, 4)
        rows = list(csv.DictReader(io.StringIO(source.decode())))
        self.assertEqual(len(rows), 12)
        # 1*100 + 2*101 + 3*102 + 1*103 = 711 satang per document.
        self.assertEqual(total, "21.33")
        self.assertEqual({row["declared_total"] for row in rows}, {"7.11"})

    def test_nearest_rank_quantile_and_bad_result(self):
        self.assertEqual(percentile([4, 1, 2, 3], .95), 4)
        self.assertEqual(percentile([4, 1, 2, 3], .5), 2)
        with self.assertRaises(ValueError):
            percentile([], .95)
        with self.assertRaises(RuntimeError):
            check_result({"status": "DELIVERED", "counts": {}}, 1, "1.00")

    def test_real_cli_fresh_repeat_and_interrupted_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fresh = normal_sample(base / "normal", 2, 2, 30)
            self.assertTrue(fresh["completed_resume_unchanged"])
            self.assertGreater(fresh["sqlite_bytes"], 0)
            connect = sqlite3.connect
            connections = []

            def record_connection(*args, **kwargs):
                database = connect(*args, **kwargs)
                connections.append(database)
                return database

            with patch("tools.benchmark_runtime.sqlite3.connect", side_effect=record_connection):
                database_state(base / "normal" / "workspace")
            with self.assertRaises(sqlite3.ProgrammingError):
                connections[0].execute("SELECT 1")
            recovery = interrupted_sample(base / "interrupted", 20, 2, 30)
            self.assertTrue(recovery["completed_work_unchanged"])
            self.assertTrue(recovery["workspace_lock_released_before_resume"])
            self.assertNotEqual(recovery["controller_exit_code"], 0)
            self.assertGreater(recovery["successful_steps_preserved"], 0)


if __name__ == "__main__":
    unittest.main()
