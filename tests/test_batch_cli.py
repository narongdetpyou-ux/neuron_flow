"""Real subprocess commands used by the Colab notebook."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class BatchCliTests(unittest.TestCase):
    def test_csv_resume_status_and_original_source_not_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'state'
            source = Path(temporary) / 'uploaded.csv'
            source.write_bytes((PROJECT / 'examples/purchases_invalid.csv').read_bytes())
            base = [sys.executable, '-m', 'neuron_flow']
            options = ['--workspace', str(workspace)]
            first = subprocess.run(base + ['csv', str(source), '--batch-id', 'uploaded'] + options,
                                   cwd=PROJECT, text=True, capture_output=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            delivery = json.loads(first.stdout)
            self.assertEqual(delivery['counts'], {'documents': 3, 'VALID': 1, 'INVALID': 2, 'ERROR': 0})
            self.assertEqual(delivery['ungrouped_rows'], 1)
            before = {}
            for artifact in delivery['receipt']['artifacts'].values():
                path = Path(artifact['path'])
                contents = path.read_bytes()
                self.assertEqual(hashlib.sha256(contents).hexdigest(), artifact['sha256'])
                before[path] = (contents, path.stat().st_mtime_ns)
            source.unlink()
            resumed = subprocess.run(base + ['batch-resume', 'uploaded'] + options,
                                     cwd=PROJECT, text=True, capture_output=True, timeout=30)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout), delivery)
            for path, original in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)
            status = subprocess.run(base + ['batch-status', 'uploaded'] + options,
                                    cwd=PROJECT, text=True, capture_output=True, timeout=15)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)['batch_status'], 'DELIVERED')

    def test_bad_header_and_conflict_are_machine_readable_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.csv'
            workspace = Path(temporary) / 'state'
            base = [sys.executable, '-m', 'neuron_flow', 'csv', str(source),
                    '--batch-id', 'same', '--workspace', str(workspace)]
            source.write_text('document_id,quantity\nA,1\n')
            bad = subprocess.run(base, cwd=PROJECT, text=True, capture_output=True, timeout=15)
            self.assertEqual(bad.returncode, 2)
            self.assertIn('missing=', json.loads(bad.stderr)['message'])
            source.write_bytes((PROJECT / 'examples/purchases.csv').read_bytes())
            good = subprocess.run(base, cwd=PROJECT, text=True, capture_output=True, timeout=30)
            self.assertEqual(good.returncode, 0, good.stderr)
            source.write_bytes(source.read_bytes() + b'\n')
            conflict = subprocess.run(base, cwd=PROJECT, text=True, capture_output=True, timeout=15)
            self.assertEqual(conflict.returncode, 2)
            self.assertEqual(json.loads(conflict.stderr)['error'], 'BatchConflict')
