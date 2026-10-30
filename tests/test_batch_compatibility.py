"""Compatibility against workspaces produced by the published 0.2.0 code."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

from neuron_flow import __version__
from neuron_flow.batch import (BatchConflict, BatchRuntime, EXECUTION_CONTRACT_VERSION,
                               WORKSPACE_SCHEMA_VERSION)
from neuron_flow.csv_agents import csv_agent_definitions
from tests.batch_fault_agents import controller_source, fault_definitions, marker_path, purchase_source
from tests.test_batch import engine_state, wait_stopped


PROJECT = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = 'af6737e'
# Genuine published source, exported offline with git archive af6737e containing
# neuron_flow/ and the three required tests/__init__, batch_fault_agents and
# batch_controller_child modules. No current implementation generates old state.
LEGACY_ARCHIVE_SHA256 = '1cea4ff8b3f088d2d18d3ff809a749a857f7669fe72d27ebaf4aeb474660d055'


def batch_row(workspace, identifier):
    with sqlite3.connect(Path(workspace) / 'state.sqlite3') as database:
        database.row_factory = sqlite3.Row
        row = database.execute('SELECT * FROM csv_batches WHERE id=?', (identifier,)).fetchone()
        return dict(row)


def files_state(workspace):
    return {str(path.relative_to(workspace)): (path.read_bytes(), path.stat().st_mtime_ns)
            for folder in ('reports', 'batch_reports')
            for path in (Path(workspace) / folder).rglob('*') if path.is_file()}


class BatchCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy_temporary = tempfile.TemporaryDirectory(prefix='neuron-published-020-')
        cls.legacy_project = Path(cls.legacy_temporary.name)
        archived = PROJECT / 'tests/fixtures/neuron_flow_0_2_0_runtime.tar.gz'
        if hashlib.sha256(archived.read_bytes()).hexdigest() != LEGACY_ARCHIVE_SHA256:
            raise AssertionError('Published 0.2.0 fixture checksum differs from its pinned source archive')
        with tarfile.open(archived, mode='r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                relative = PurePosixPath(member.name)
                if (relative.is_absolute() or '..' in relative.parts or not relative.parts
                        or relative.parts[0] not in {'neuron_flow', 'tests'}
                        or not (member.isdir() or member.isfile() and member.name.endswith('.py'))):
                    raise AssertionError('Unexpected member in pinned legacy source fixture')
            # Keep Python 3.10 support; its tarfile may lack extraction filters.
            options = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
            archive.extractall(cls.legacy_project, members=members, **options)
        cls.legacy_environment = {**os.environ, 'PYTHONPATH': str(cls.legacy_project)}
        # A real archived driver keeps multiprocessing's spawn import separate
        # from this checkout. Its original package and agents are unmodified.
        (cls.legacy_project / '_compatibility_driver.py').write_text('''
from pathlib import Path
import json
import sys
from neuron_flow import __version__
from neuron_flow.batch import BatchRuntime

def main():
    assert __version__ == '0.2.0'
    workspace, source_file, mode, identifier = sys.argv[1:]
    identifier = None if identifier == '-' else identifier
    with BatchRuntime(workspace) as runtime:
        result = runtime.submit(Path(source_file).read_bytes(), identifier)
        if mode == 'completed':
            result = runtime.deliver(result['batch_id'])
        print(json.dumps(result))

if __name__ == '__main__':
    main()
''', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.legacy_temporary.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='neuron-compatibility-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.workspace = self.directory / 'workspace'
        self.source = purchase_source([('GOOD', 'Created by the published version')])
        self.source_path = self.directory / 'input.csv'
        self.source_path.write_bytes(self.source)

    def legacy(self, mode='completed', identifier='legacy'):
        process = subprocess.run([sys.executable, '_compatibility_driver.py', str(self.workspace),
                                  str(self.source_path), mode, identifier or '-'],
                                 cwd=self.legacy_project, env=self.legacy_environment,
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_completed_020_workspace_reuses_reports_history_and_original_identity_exactly(self):
        original = self.legacy()
        before_batch = batch_row(self.workspace, 'legacy')
        manifest = json.loads(before_batch['manifest'])
        self.assertEqual(manifest['system_version'], '0.2.0')
        self.assertNotIn('workspace_schema_version', manifest)
        self.assertNotIn('execution_contract_version', manifest)
        before_engine = engine_state(self.workspace)
        before_files = files_state(self.workspace)
        with BatchRuntime(self.workspace) as runtime:
            duplicate = runtime.submit(self.source, 'legacy')
            actual = runtime.deliver('legacy')
            payload = runtime.run('legacy')
        self.assertFalse(duplicate['created'])
        self.assertEqual(actual, original)
        self.assertEqual(payload['system_version'], '0.2.0')
        self.assertEqual(before_batch, batch_row(self.workspace, 'legacy'))
        self.assertEqual(before_engine, engine_state(self.workspace))
        self.assertEqual(before_files, files_state(self.workspace))

    def test_pending_020_workspace_finishes_with_original_provenance_and_binding(self):
        self.legacy(mode='pending')
        before = batch_row(self.workspace, 'legacy')
        with BatchRuntime(self.workspace) as runtime:
            result = runtime.deliver('legacy')
            payload = runtime.run('legacy')
        after = batch_row(self.workspace, 'legacy')
        self.assertEqual(result['counts'], {'documents': 1, 'VALID': 1, 'INVALID': 0, 'ERROR': 0})
        self.assertEqual(payload['system_version'], '0.2.0')
        self.assertEqual(before['identity'], after['identity'])
        self.assertEqual(before['manifest'], after['manifest'])
        self.assertEqual(before['source'], after['source'])
        self.assertTrue(all(step['attempts'] == 1 for step in payload['documents'][0]['steps'].values()))

    def test_auto_submission_reuses_020_generated_id_instead_of_creating_a_duplicate(self):
        original = self.legacy(identifier=None)
        before = batch_row(self.workspace, original['batch_id'])
        with BatchRuntime(self.workspace) as runtime:
            duplicate = runtime.submit(self.source)
            self.assertEqual(runtime.runtime.store.db.execute('SELECT count(*) FROM csv_batches').fetchone()[0], 1)
        self.assertEqual(duplicate, {'batch_id': original['batch_id'], 'created': False})
        self.assertEqual(before, batch_row(self.workspace, original['batch_id']))

    def test_ambiguous_legacy_matches_require_explicit_id_without_mutating_either(self):
        self.legacy(mode='pending', identifier='first')
        self.legacy(mode='pending', identifier='second')
        before = {identifier: batch_row(self.workspace, identifier) for identifier in ('first', 'second')}
        with BatchRuntime(self.workspace) as runtime:
            with self.assertRaisesRegex(BatchConflict, 'explicit batch_id'):
                runtime.submit(self.source)
            self.assertFalse(runtime.submit(self.source, 'second')['created'])
            self.assertEqual(runtime.runtime.store.db.execute('SELECT count(*) FROM csv_batches').fetchone()[0], 2)
        self.assertEqual(before, {identifier: batch_row(self.workspace, identifier)
                                  for identifier in ('first', 'second')})

    def test_new_identity_uses_contract_schema_and_agents_not_package_version(self):
        with BatchRuntime(self.workspace) as runtime:
            original = runtime.submit(self.source)
        before = batch_row(self.workspace, original['batch_id'])
        manifest = json.loads(before['manifest'])
        self.assertEqual(manifest['system_version'], __version__)
        self.assertEqual(manifest['workspace_schema_version'], WORKSPACE_SCHEMA_VERSION)
        self.assertEqual(manifest['execution_contract_version'], EXECUTION_CONTRACT_VERSION)
        # Creation provenance is supported independently of operational identity.
        # A new-format batch made by the supported 0.2.0 package has this same
        # operational fingerprint; retain it exactly when reopening on 0.2.1.
        manifest['system_version'] = '0.2.0'
        with sqlite3.connect(self.workspace / 'state.sqlite3') as database:
            database.execute('UPDATE csv_batches SET manifest=? WHERE id=?',
                             (json.dumps(manifest), original['batch_id']))
        with BatchRuntime(self.workspace) as runtime:
            duplicate = runtime.submit(self.source)
        self.assertEqual(duplicate, {'batch_id': original['batch_id'], 'created': False})
        self.assertEqual(batch_row(self.workspace, original['batch_id'])['identity'], before['identity'])

    def test_changed_source_settings_or_agents_cannot_reuse_legacy_batch(self):
        self.legacy(mode='pending')
        before = batch_row(self.workspace, 'legacy')
        with BatchRuntime(self.workspace) as runtime:
            with self.assertRaises(BatchConflict):
                runtime.submit(self.source + b'\n', 'legacy')
        with BatchRuntime(self.workspace, timeout_s=6) as runtime:
            with self.assertRaises(BatchConflict):
                runtime.submit(self.source, 'legacy')
        changed = [replace(agent, version=agent.version + '-changed')
                   if agent.name == 'csv_calculate' else agent for agent in csv_agent_definitions()]
        with BatchRuntime(self.workspace, agents=changed) as runtime:
            with self.assertRaises(BatchConflict):
                runtime.submit(self.source, 'legacy')
            with self.assertRaises(BatchConflict):
                runtime.run('legacy')
        self.assertEqual(before, batch_row(self.workspace, 'legacy'))
        self.assertEqual(engine_state(self.workspace), {})

    def test_unsupported_versions_schemas_and_contracts_reject_before_execution(self):
        self.legacy(mode='pending')
        original = batch_row(self.workspace, 'legacy')
        manifest = json.loads(original['manifest'])
        cases = [
            {'system_version': '9.0.0'},
            {'system_version': '0.2.1'},  # Markerless format is specifically 0.2.0.
            {'workspace_schema_version': 2, 'execution_contract_version': EXECUTION_CONTRACT_VERSION},
            {'workspace_schema_version': True, 'execution_contract_version': EXECUTION_CONTRACT_VERSION},
            {'workspace_schema_version': 1, 'execution_contract_version': 'purchase-batch-v2'},
            {'contract_version': 'purchase-csv-v2'},
            {'max_attempts': 3},
            {'timeout_s': 0},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                with sqlite3.connect(self.workspace / 'state.sqlite3') as database:
                    database.execute('UPDATE csv_batches SET manifest=? WHERE id=?',
                                     (json.dumps({**manifest, **changes}), 'legacy'))
                before = batch_row(self.workspace, 'legacy')
                with BatchRuntime(self.workspace) as runtime:
                    with self.assertRaises(BatchConflict):
                        runtime.run('legacy')
                self.assertEqual(before, batch_row(self.workspace, 'legacy'))
                self.assertEqual(engine_state(self.workspace), {})

    def test_manifest_identity_tampering_is_rejected_without_executing_jobs(self):
        self.legacy(mode='pending')
        original = batch_row(self.workspace, 'legacy')
        manifest = json.loads(original['manifest'])
        manifest['timeout_s'] = 6
        with sqlite3.connect(self.workspace / 'state.sqlite3') as database:
            database.execute('UPDATE csv_batches SET manifest=? WHERE id=?', (json.dumps(manifest), 'legacy'))
        with BatchRuntime(self.workspace) as runtime:
            with self.assertRaisesRegex(BatchConflict, 'identity'):
                runtime.run('legacy')
        self.assertEqual(engine_state(self.workspace), {})

    def test_actual_interrupted_020_controller_resumes_kept_steps_under_new_runtime(self):
        process = subprocess.Popen([sys.executable, '-m', 'tests.batch_controller_child', str(self.workspace)],
                                   cwd=self.legacy_project, env=self.legacy_environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = marker_path(self.workspace / 'interrupted-worker', 1)
        try:
            deadline = time.monotonic() + 12
            while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.02)
            if not marker.exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=5)
                    self.fail(f'Legacy controller failed before interrupted step: {stdout!r} {stderr!r}')
                self.fail('Legacy controller did not reach the interrupted step')
            worker_pid = int(marker.read_text())
            process.kill()
            process.communicate(timeout=5)
            before_engine = engine_state(self.workspace)
            before_batch = batch_row(self.workspace, 'controller-recovery')
            self.assertEqual(json.loads(before_batch['manifest'])['system_version'], '0.2.0')
            with BatchRuntime(self.workspace, agents=fault_definitions(), timeout_s=30) as runtime:
                result = runtime.deliver('controller-recovery')
                payload = runtime.run('controller-recovery')
            after_engine = engine_state(self.workspace)
            after_batch = batch_row(self.workspace, 'controller-recovery')
            self.assertEqual(before_engine['GOOD-FIRST'], after_engine['GOOD-FIRST'])
            self.assertEqual(after_engine['RECOVER']['steps']['validate']['attempts'], 1)
            self.assertEqual(after_engine['RECOVER']['steps']['calculate']['attempts'], 2)
            self.assertEqual(after_engine['RECOVER']['steps']['verify']['attempts'], 1)
            self.assertEqual(result['counts']['VALID'], 3)
            self.assertEqual(payload['system_version'], '0.2.0')
            self.assertEqual(before_batch['identity'], after_batch['identity'])
            self.assertEqual(before_batch['manifest'], after_batch['manifest'])
            self.assertEqual(before_batch['source'], controller_source(self.workspace))
            self.assertTrue(wait_stopped(worker_pid))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
