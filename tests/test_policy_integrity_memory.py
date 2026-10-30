from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from neuron_flow.case_memory import CaseMemory
from neuron_flow.evaluation import accept_policy, candidate_gate, load_policy, route_variant, run_shadow
from neuron_flow.integrity import inventory, restore_backup, stage_backup, verify_manifest, write_manifest
from neuron_flow.intake import review_document, stage_document
from neuron_flow.reporting import BatchTerminal
from neuron_flow.storage import WorkspaceLock
from tests.test_reporting import frozen_example

PROJECT = Path(__file__).resolve().parents[1]


class PolicyIntegrityMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload, self.source = frozen_example()
        self.report = self.root / 'reference'
        BatchTerminal(self.report).deliver(self.payload, self.source)
        self.rows = [{'case_id': 'a', 'cluster_id': 'supplier-a', 'format': 'csv', 'split': 'validation',
                      'report_directory': str(self.report), 'latency_ms': 10, 'attempts': 1, 'first_method_success': True},
                     {'case_id': 'b', 'cluster_id': 'supplier-b', 'format': 'csv', 'split': 'holdout',
                      'report_directory': str(self.report), 'latency_ms': 12, 'attempts': 1, 'first_method_success': True}]
        payload, source = frozen_example(valid_id='SECOND')
        second = self.root / 'second-reference'
        BatchTerminal(second).deliver(payload, source)
        self.rows[1]['report_directory'] = str(second)

    def test_deterministic_cluster_assignment_requires_explicit_identity(self):
        self.assertEqual(route_variant('supplier-a', 0), 'reference')
        self.assertEqual(route_variant('supplier-a', 1), 'candidate')
        self.assertEqual(route_variant('supplier-a'), route_variant('supplier-a'))
        for identity, fraction in [('', .1), ('a', float('nan')), ('a', -1)]:
            with self.assertRaises(ValueError):
                route_variant(identity, fraction)

    def test_candidate_gate_identifies_population_and_exact_outcomes(self):
        accepted = candidate_gate(self.rows, deepcopy(self.rows), max_p95_ratio=1, max_attempt_ratio=1)
        self.assertTrue(accepted['accepted'])
        self.assertEqual(accepted['independent_clusters'], 2)
        self.assertEqual(accepted['groups']['csv/THB']['cases'], 2)
        self.assertEqual(accepted['dataset_sha256'], candidate_gate(list(reversed(self.rows)), self.rows)['dataset_sha256'])
        for change in ['id', 'source', 'split', 'cluster']:
            candidate = deepcopy(self.rows)
            if change == 'id':
                candidate[0]['case_id'] = 'different'
            elif change == 'source':
                payload, source = frozen_example(bom=True)
                folder = self.root / 'other'
                BatchTerminal(folder).deliver(payload, source)
                candidate[0]['report_directory'] = str(folder)
            else:
                candidate[0]['split' if change == 'split' else 'cluster_id'] = 'holdout' if change == 'split' else 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidate_gate(self.rows, candidate)

    def test_candidate_gate_rejects_leakage_and_malformed_cases(self):
        with self.assertRaisesRegex(ValueError, 'leakage'):
            candidate_gate(self.rows, self.rows, training_clusters=['supplier-a'])
        leaked = deepcopy(self.rows)
        leaked[1]['cluster_id'] = 'supplier-a'
        with self.assertRaisesRegex(ValueError, 'leakage'):
            candidate_gate(leaked, leaked)
        duplicated = deepcopy(self.rows)
        duplicated[1]['report_directory'] = duplicated[0]['report_directory']
        with self.assertRaisesRegex(ValueError, 'Source overlaps'):
            candidate_gate(duplicated, duplicated)
        for rows in [[], [self.rows[0], self.rows[0]], [{**self.rows[0], 'split': 'train'}],
                     [{**self.rows[0], 'attempts': True}], [{**self.rows[0], 'extra': True}],
                     [{**self.rows[0], 'latency_ms': float('nan')}]]:
            with self.assertRaises(ValueError):
                candidate_gate(rows, self.rows)

    def test_candidate_gate_rejects_efficiency_and_first_method_regressions(self):
        candidate = deepcopy(self.rows)
        candidate[0].update(latency_ms=100, attempts=3, first_method_success=False)
        result = candidate_gate(self.rows, candidate, max_p95_ratio=1, max_attempt_ratio=1)
        self.assertEqual(set(result['failure_reasons']), {'LATENCY_REGRESSION', 'ATTEMPT_REGRESSION', 'FIRST_METHOD_REGRESSION'})
        with self.assertRaises(ValueError):
            candidate_gate(self.rows, self.rows, max_p95_ratio=.5)
        reference = deepcopy(self.rows)
        reference[0]['format'] = 'pdf'
        reference[1]['latency_ms'] = 1000
        hidden = deepcopy(reference)
        hidden[0]['latency_ms'] = 40
        result = candidate_gate(reference, hidden, max_p95_ratio=1.1)
        self.assertIn('LATENCY_REGRESSION', result['failure_reasons'])
        self.assertEqual(result['groups']['pdf/THB']['efficiency_regressions'], ['LATENCY_REGRESSION'])

    def test_candidate_gate_rejects_changed_status_even_with_valid_report(self):
        candidate_payload = deepcopy(self.payload)
        document = candidate_payload['documents'][0]
        document.update(document_status='ERROR', engine_status='FAILED', computed_total=None, difference=None,
                        errors=[{'row_number': document['source_rows'][0], 'field': '*', 'reason_code': 'ENGINE_ERROR',
                                 'expected': 'verified', 'actual': 'synthetic timeout'}])
        candidate_payload['counts'].update(VALID=0, ERROR=2)
        candidate_payload['certified_total'] = '0.00'
        folder = self.root / 'candidate'
        BatchTerminal(folder).deliver(candidate_payload, self.source)
        candidate = deepcopy(self.rows)
        candidate[0]['report_directory'] = str(folder)
        result = candidate_gate(self.rows, candidate)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['groups']['csv/THB']['regressions'], 1)

    def test_accepted_policy_is_immutable_hash_bound_and_environment_bound(self):
        from neuron_flow.extraction import ExtractionEngine
        from neuron_flow.intake import run_document
        workspace = self.root / 'policy-workspace'
        staged = stage_document(workspace, (PROJECT / 'examples/purchases.csv').read_bytes(), 'purchases.csv', extraction_engine=ExtractionEngine())
        run_document(workspace, staged['intake_id'], workers=1)
        row = {**self.rows[1], 'report_directory': str(workspace / ('batch_reports/intake_' + staged['intake_id'])),
               'intake_workspace': str(workspace), 'intake_id': staged['intake_id']}
        rows = [row]
        path = self.root / 'accepted.json'
        with self.assertRaisesRegex(ValueError, 'intake evidence'):
            accept_policy(path, ['native'], self.rows, self.rows)
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            accept_policy(path, ['pdf-text'], rows, rows)
        result = accept_policy(path, ['native'], rows, rows)
        self.assertTrue(result['gate']['accepted'])
        self.assertEqual(load_policy(path).strategies, ('native',))
        alternate_workspace = self.root / 'alternate-budget'
        alternate = stage_document(alternate_workspace, (PROJECT / 'examples/purchases.csv').read_bytes(), 'purchases.csv', extraction_engine=ExtractionEngine(timeout_s=30))
        run_document(alternate_workspace, alternate['intake_id'], workers=1)
        alternate_row = {**row, 'report_directory': str(alternate_workspace / ('batch_reports/intake_' + alternate['intake_id'])),
                         'intake_workspace': str(alternate_workspace), 'intake_id': alternate['intake_id']}
        alternate_path = self.root / 'alternate-policy.json'
        accept_policy(alternate_path, ['native'], [alternate_row], [alternate_row], timeout_s=30)
        self.assertEqual(load_policy(alternate_path).timeout_s, 30)
        with self.assertRaises(FileExistsError):
            accept_policy(path, ['native'], rows, rows)
        with self.assertRaisesRegex(ValueError, 'holdout'):
            accept_policy(self.root / 'no-holdout', ['native'], [self.rows[0]], [self.rows[0]])
        slow = deepcopy(self.rows)
        slow[0]['attempts'] = 2
        with self.assertRaisesRegex(ValueError, 'gate rejected'):
            accept_policy(self.root / 'rejected', ['native'], self.rows, slow, max_attempt_ratio=1)
        with patch('neuron_flow.extraction.identity', return_value={'different': True}), self.assertRaisesRegex(ValueError, 'environment changed'):
            load_policy(path)
        value = json.loads(path.read_bytes())
        value['policy']['timeout_s'] = 5
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Invalid accepted'):
            load_policy(path)

    def test_actual_shadow_executes_trusted_factory_on_separate_workspace(self):
        # Use a real accepted current report instead of the frozen synthetic ERROR case.
        from neuron_flow.batch import BatchRuntime
        workspace = self.root / 'runtime'
        source = (PROJECT / 'examples/purchases_international.csv').read_bytes()
        with BatchRuntime(workspace, max_workers=1) as batch:
            batch.submit(source, 'real')
            batch.deliver('real')
        report = workspace / 'batch_reports/real'
        before = inventory(workspace)
        result = run_shadow(report, candidate_factory='tests.operations_faults:candidate_agents', timeout_s=60)
        self.assertTrue(result['agreement'], result['differences'])
        self.assertGreater(result['candidate_execution_ms'], 0)
        self.assertEqual(inventory(workspace), before)
        with self.assertRaises(ValueError):
            run_shadow(report, candidate_factory='tests.operations_faults:missing', timeout_s=5)

    def test_integrity_diagnoses_missing_changed_extra_and_unsafe_paths(self):
        tree = self.root / 'tree'
        tree.mkdir()
        (tree / 'a').write_text('keep')
        (tree / 'b').write_text('original')
        write_manifest(tree)
        self.assertTrue(verify_manifest(tree)['ok'])
        (tree / 'a').unlink()
        (tree / 'b').write_text('changed')
        (tree / 'extra').write_text('extra')
        result = verify_manifest(tree)
        self.assertEqual(result['missing'], ['a'])
        self.assertEqual(result['changed'], ['b'])
        self.assertEqual(result['extra'], ['extra'])
        manifest = tree / 'backup_SHA256SUMS.txt'
        for name in ['../escape', '/absolute', 'x\\y', 'x:stream', './alias', 'backup_SHA256SUMS.txt']:
            manifest.write_text('a' * 64 + '  ' + name + '\n')
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_manifest(tree)
        manifest.write_text('a' * 64 + '  b\n' + 'a' * 64 + '  b\n')
        with self.assertRaises(ValueError):
            verify_manifest(tree)
        manifest.write_text('')
        with self.assertRaises(ValueError):
            verify_manifest(tree)
        for function in [lambda: verify_manifest(tree, 'other'), lambda: write_manifest(tree, 'other'), lambda: inventory(self.root / 'missing')]:
            with self.assertRaises(ValueError):
                function()

    def test_integrity_rejects_symlinks_empty_tree_and_manifest_overwrite(self):
        tree = self.root / 'empty'
        tree.mkdir()
        with self.assertRaises(ValueError):
            write_manifest(tree)
        (tree / 'link').symlink_to(self.report / 'source.csv')
        with self.assertRaises(ValueError):
            inventory(tree)
        (tree / 'link').unlink()
        (tree / 'real').write_text('data')
        write_manifest(tree)
        with self.assertRaises(FileExistsError):
            write_manifest(tree)
        (tree / 'backup_SHA256SUMS.txt').unlink()
        (tree / 'backup_SHA256SUMS.txt').symlink_to(tree / 'real')
        with self.assertRaises(ValueError):
            verify_manifest(tree)

    def test_workspace_backup_is_consistent_and_restore_never_overwrites(self):
        workspace = self.root / 'workspace'
        workspace.mkdir()
        (workspace / 'artifact').write_text('immutable')
        with sqlite3.connect(workspace / 'state.sqlite3') as db:
            db.execute('CREATE TABLE evidence(value TEXT)')
            db.execute("INSERT INTO evidence VALUES('preserved')")
        session = self.root / 'session.json'
        session.write_text('{}')
        backup = self.root / 'backup'
        self.assertTrue(stage_backup(workspace, backup, session=session)['ok'])
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            restore_backup(backup, workspace)
        with self.assertRaisesRegex(ValueError, 'original absolute'):
            restore_backup(backup, self.root / 'different')
        shutil.rmtree(workspace)
        self.assertTrue(restore_backup(backup, workspace)['restored'])
        self.assertEqual((workspace / 'artifact').read_text(), 'immutable')
        with sqlite3.connect(workspace / 'state.sqlite3') as db:
            self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0], 'preserved')
        (backup / 'workspace/artifact').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            restore_backup(backup, workspace)

    def test_backup_rejects_active_runtime_and_changed_tree(self):
        workspace = self.root / 'workspace'
        workspace.mkdir()
        lock = WorkspaceLock(workspace / 'runtime.lock')
        try:
            with self.assertRaises(RuntimeError):
                stage_backup(workspace, self.root / 'busy')
        finally:
            lock.close()
        for source, target in [(workspace, workspace / 'nested'), (self.root / 'missing', self.root / 'new')]:
            with self.assertRaises(ValueError):
                stage_backup(source, target)
        (workspace / 'data').write_text('before')
        actual_inventory = inventory
        count = 0
        def changing(root, excluded=()):
            nonlocal count
            count += 1
            if count == 2:
                (workspace / 'data').write_text('after')
            return actual_inventory(root, excluded)
        with patch('neuron_flow.integrity.inventory', side_effect=changing), self.assertRaisesRegex(ValueError, 'changed during backup'):
            stage_backup(workspace, self.root / 'racing')
        self.assertFalse((self.root / 'racing').exists())

    def reviewed_case(self):
        staged = stage_document(self.root / 'intakes', b'Receipt total 412.70', 'receipt.txt')
        source = (PROJECT / 'examples/purchases.csv').read_bytes()
        review_document(self.root / 'intakes', staged['intake_id'], source, 'synthetic-reviewer')
        return staged, source

    def test_memory_learns_only_review_bound_outcomes_and_retrieves_structure(self):
        staged, source = self.reviewed_case()
        memory = CaseMemory(self.root / 'memory', max_records=2)
        self.addCleanup(memory.close)
        arguments = {'profile': [1, 0, .5, 0, 1, 0], 'method': 'native', 'policy_version': 'v1', 'cluster_id': 'layout-a'}
        first = memory.learn(self.root / 'intakes', staged['intake_id'], source, **arguments)
        self.assertEqual(first['outcome'], 'MATCH')
        self.assertFalse(memory.learn(self.root / 'intakes', staged['intake_id'], source, **arguments)['created'])
        different = source.replace(b'412.70', b'412.71') + b'\n'
        self.assertEqual(memory.learn(self.root / 'intakes', staged['intake_id'], different, **arguments)['outcome'], 'MISMATCH')
        cases = memory.retrieve(arguments['profile'], 'v1')
        self.assertEqual(len(cases), 2)
        self.assertTrue(all(c['distance'] == 0 for c in cases))
        self.assertEqual(memory.retrieve(arguments['profile'], 'v2'), [])
        self.assertEqual(memory.retrieve(arguments['profile'], 'v1', excluded_clusters=['layout-a']), [])
        with self.assertRaisesRegex(ValueError, 'MEMORY_FULL'):
            memory.learn(self.root / 'intakes', staged['intake_id'], source + b'\n\n', **arguments)

    def test_memory_rejects_self_labels_holdout_bad_dimensions_and_corrupt_load(self):
        staged, source = self.reviewed_case()
        memory = CaseMemory(self.root / 'memory')
        self.addCleanup(memory.close)
        arguments = {'profile': [0] * 6, 'method': 'native', 'policy_version': 'v1', 'cluster_id': 'layout-a'}
        for changes in [{'split': 'holdout'}, {'profile': [0, 1]}, {'profile': [float('nan')] * 6}, {'method': ''}]:
            with self.assertRaises(ValueError):
                memory.learn(self.root / 'intakes', staged['intake_id'], source, **{**arguments, **changes})
        structured = stage_document(self.root / 'intakes', source, 'x.csv')
        with self.assertRaises(FileNotFoundError):
            memory.learn(self.root / 'intakes', structured['intake_id'], source, **arguments)
        case = memory.learn(self.root / 'intakes', staged['intake_id'], source, **arguments)
        with self.assertRaises(ValueError):
            memory.retrieve([0] * 6, 'v1', limit=0)
        with memory.db:
            memory.db.execute('UPDATE reviewed_cases SET evidence=? WHERE id=?', ('{}', case['case_id']))
        with self.assertRaisesRegex(ValueError, 'Invalid stored'):
            memory.retrieve([0] * 6, 'v1')
        with self.assertRaises(ValueError):
            CaseMemory(self.root / 'invalid', max_records=0)
