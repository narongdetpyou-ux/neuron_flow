"""Find durable jobs before the first result, even with a busy controller."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from neuron_flow.batch import BatchRuntime
from neuron_flow.inspection import InspectionError, list_batches

PROJECT = Path(__file__).resolve().parents[1]


def logical_state(workspace):
    with sqlite3.connect(Path(workspace) / 'state.sqlite3') as connection:
        return {name: connection.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                for name in ('jobs', 'steps', 'events', 'csv_batches', 'csv_batch_documents')}


class BatchDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='neuron-discovery-')
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / 'state with spaces'

    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-B', '-m', 'neuron_flow', *map(str, arguments),
                               '--workspace', str(self.workspace)], cwd=PROJECT,
                              capture_output=True, text=True, timeout=30)

    def test_submit_only_persists_id_without_jobs_agents_or_reports(self):
        source = Path(self.temporary.name) / 'uploaded.csv'
        source.write_bytes((PROJECT / 'examples/purchases.csv').read_bytes())
        submitted = self.cli('csv', source, '--submit-only')
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        first = json.loads(submitted.stdout)
        self.assertTrue(first['created'])
        self.assertEqual(first['status'], 'PENDING')
        source.unlink()
        before = logical_state(self.workspace)
        self.assertEqual(before['jobs'], [])
        self.assertEqual(before['events'], [])
        listed = self.cli('batch-list')
        self.assertEqual(listed.returncode, 0, listed.stderr)
        batch = json.loads(listed.stdout)['batches'][0]
        self.assertEqual(batch['batch_id'], first['batch_id'])
        self.assertEqual(batch['engine_counts'], {'PENDING': 2})
        self.assertEqual(before, logical_state(self.workspace))
        resumed = self.cli('batch-resume', batch['batch_id'])
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)['counts']['VALID'], 2)
        source.write_bytes((PROJECT / 'examples/purchases.csv').read_bytes())
        resubmitted = self.cli('csv', source, '--submit-only')
        self.assertEqual(resubmitted.returncode, 0, resubmitted.stderr)
        self.assertFalse(json.loads(resubmitted.stdout)['created'])
        self.assertEqual(json.loads(resubmitted.stdout)['status'], 'DELIVERED')

    def test_inspection_during_controller_lock_and_pending_execution_is_read_only(self):
        with BatchRuntime(self.workspace) as controller:
            controller.submit((PROJECT / 'examples/purchases.csv').read_bytes(), 'busy')
            before = logical_state(self.workspace)
            with patch('neuron_flow.engine.Worker', side_effect=AssertionError('Inspection must not start a worker')):
                result = list_batches(self.workspace)
            from_child = self.cli('batch-list')
            self.assertEqual(from_child.returncode, 0, from_child.stderr)
            self.assertEqual(result, json.loads(from_child.stdout))
            self.assertEqual(before, logical_state(self.workspace))
            self.assertEqual(result['batches'][0]['batch_id'], 'busy')
            self.assertFalse(result['batches'][0]['receipt_available'])

    def test_incompatible_batch_still_discoverable_without_touching_metadata(self):
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit((PROJECT / 'examples/purchases.csv').read_bytes(), 'future')
            manifest = json.loads(runtime.runtime.store.db.execute('SELECT manifest FROM csv_batches').fetchone()[0])
            manifest['workspace_schema_version'] = 900
            with runtime.runtime.store.db:
                runtime.runtime.store.db.execute('UPDATE csv_batches SET manifest=?', (json.dumps(manifest),))
        before = logical_state(self.workspace)
        result = list_batches(self.workspace)
        self.assertEqual(result['batches'][0]['workspace_schema_version'], 900)
        self.assertEqual(before, logical_state(self.workspace))

    def test_missing_workspace_does_not_create_files_or_directory(self):
        self.assertFalse(self.workspace.exists())
        with self.assertRaises(InspectionError):
            list_batches(self.workspace)
        result = self.cli('batch-list')
        self.assertEqual(result.returncode, 2)
        self.assertIn('does not exist', json.loads(result.stderr)['message'])
        self.assertFalse(self.workspace.exists())

    def test_existing_non_batch_runtime_has_empty_discovery(self):
        from neuron_flow import Runtime
        with Runtime(self.workspace):
            pass
        self.assertEqual(list_batches(self.workspace)['batches'], [])

    def test_malformed_metadata_is_a_structured_error_and_is_not_changed(self):
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit((PROJECT / 'examples/purchases.csv').read_bytes(), 'malformed')
        for column in ('manifest', 'payload'):
            with sqlite3.connect(self.workspace / 'state.sqlite3') as connection:
                original = connection.execute('SELECT ' + column + ' FROM csv_batches').fetchone()[0]
                connection.execute('UPDATE csv_batches SET ' + column + "='[]'")
            before = logical_state(self.workspace)
            result = self.cli('batch-list')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)['error'], 'InspectionError')
            self.assertEqual(before, logical_state(self.workspace))
            with sqlite3.connect(self.workspace / 'state.sqlite3') as connection:
                connection.execute('UPDATE csv_batches SET ' + column + '=?', (original,))
