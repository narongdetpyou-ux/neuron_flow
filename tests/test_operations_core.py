import base64
from copy import deepcopy
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from neuron_flow.engine import AgentDefinition, Runtime, Synapse
from neuron_flow.extraction import ExtractionCache, ExtractionEngine
from neuron_flow.intake import stage_document
from neuron_flow.operations import JobQueue, request_model
from neuron_flow.storage import WorkspaceLock
from neuron_flow.supervision import OperationFailure, isolated, load_json, wire
from neuron_flow.telemetry import Telemetry, drift_report
from tests.operations_faults import validator, slow_validator, mutating_validator, rejecting_validator

PROJECT = Path(__file__).resolve().parents[1]


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = (PROJECT / 'examples/purchases.csv').read_bytes()

    def request(self, key='one', **options):
        return {'idempotency_key': key, 'filename': 'purchases.csv',
                'source_base64': base64.b64encode(self.source).decode(), **options}

    def queue(self, **options):
        queue = JobQueue(self.root / 'workspace', **options)
        self.addCleanup(queue.close)
        return queue

    def test_json_transport_rejects_duplicate_nonfinite_and_size(self):
        self.assertEqual(load_json(wire({'x': 1})), {'x': 1})
        for data in ['{"a":1,"a":2}', '{"x":NaN}', '{"x":1e999}', '{']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_json(data)
        with patch('neuron_flow.supervision.MAX_OPERATION_BYTES', 5), self.assertRaises(ValueError):
            wire({'x': 'large'})

    def test_isolated_result_crash_invalid_output_and_next_request(self):
        for function, reason in [('crash', 'WORKER_EXIT'), ('invalid', 'ValueError'), ('missing', 'AttributeError')]:
            with self.subTest(function=function), self.assertRaises(OperationFailure) as caught:
                isolated('tests.operations_faults:' + function, {}, 5)
            self.assertEqual(caught.exception.details['reason_code'], reason)
        self.assertEqual(isolated('tests.operations_faults:echo', {'x': '1.00'}, 5), {'x': '1.00'})
        for timeout in [True, 0, float('inf')]:
            with self.assertRaises(ValueError):
                isolated('tests.operations_faults:echo', {}, timeout)

    def test_hard_deadline_and_cancellation_kill_descendants(self):
        marker = self.root / 'pid'
        start = time.monotonic()
        with self.assertRaises(OperationFailure) as caught:
            isolated('tests.operations_faults:hang', {'marker': str(marker)}, 1, phase='extraction')
        self.assertEqual(caught.exception.details['reason_code'], 'TIME_BUDGET_EXHAUSTED')
        self.assertLess(time.monotonic() - start, 4)
        self.assertTrue(marker.is_file())
        if os.name == 'posix':
            status = Path('/proc') / marker.read_text() / 'stat'
            if status.exists():
                self.assertIn(status.read_text().split()[2], {'Z', 'X'})
        with self.assertRaises(OperationFailure) as caught:
            isolated('tests.operations_faults:hang', {'marker': str(marker)}, 5, cancelled=lambda: True)
        self.assertEqual(caught.exception.details['reason_code'], 'CANCELLED')
        self.assertEqual(isolated('tests.operations_faults:echo', 'recovered', 5), 'recovered')

    def test_isolated_validation_rejects_mutation_rejection_and_hang(self):
        output = {'checked': True}
        for function in (slow_validator, mutating_validator, rejecting_validator):
            synapse = Synapse(None, [AgentDefinition('probe', 'tests.operations_faults:agent', function)], .5)
            with self.subTest(function=function), self.assertRaises(OperationFailure):
                synapse.validate('probe', {}, output)
            self.assertEqual(output, {'checked': True})
        Synapse(None, [AgentDefinition('probe', 'tests.operations_faults:agent', validator)], 5).validate('probe', {}, output)

    def test_runtime_records_validator_timeout_and_preserves_version_binding(self):
        definitions = [AgentDefinition('slow', 'tests.operations_faults:agent', slow_validator),
                       AgentDefinition('good', 'tests.operations_faults:agent', validator)]
        workspace = self.root / 'runtime'
        with Runtime(workspace, agents=definitions, max_workers=1, validation_timeout_s=.5) as runtime:
            for name in ('slow', 'good'):
                runtime.submit({'job_id': name, 'input': {}, 'steps': [{'id': 'run', 'agent': name}]})
                result = runtime.run(name)
                self.assertEqual(result['status'], 'FAILED' if name == 'slow' else 'SUCCEEDED')
                if name == 'slow':
                    self.assertEqual(result['steps']['run']['error']['phase'], 'validation')
                    self.assertEqual(result['steps']['run']['attempts'], 1)
        with Runtime(workspace, agents=definitions, validation_timeout_s=1) as runtime:
            with self.assertRaisesRegex(ValueError, 'version changed'):
                runtime.run('good')

    def test_cache_exact_identity_expiry_eviction_copy_and_error_behavior(self):
        cache = ExtractionCache(max_entries=1, max_bytes=1024, ttl_s=.02)
        value, hit = cache.compute('a', lambda: {'money': '1.00'})
        value['money'] = 'forged'
        self.assertFalse(hit)
        self.assertEqual(cache.compute('a', lambda: None), ({'money': '1.00'}, True))
        cache.compute('b', lambda: {'b': 2})
        self.assertEqual(cache.evictions, 1)
        time.sleep(.03)
        self.assertFalse(cache.compute('b', lambda: {'b': 3})[1])
        cache.compute('large', lambda: 'x' * 2000)
        self.assertNotIn('large', cache.entries)
        with self.assertRaises(ZeroDivisionError):
            cache.compute('error', lambda: 1 / 0)
        self.assertNotIn('error', cache.entries)
        self.assertFalse(cache.compute('b', lambda: {}, eligible=False)[1])
        self.assertEqual(cache.stats()['entries'], 1)
        for options in [{'max_entries': -1}, {'ttl_s': float('nan')}, {'max_bytes': 0}]:
            with self.assertRaises(ValueError):
                ExtractionCache(**options)

    def test_extraction_uses_pure_cache_and_intake_reuses_durable_attempts(self):
        cache = ExtractionCache(max_entries=2)
        engine = ExtractionEngine(cache=cache)
        first = engine.prepare(self.source, 'purchases.csv')
        second = engine.prepare(self.source, 'other.csv')
        self.assertEqual(first['csv'], self.source)
        self.assertTrue(second['extraction_attempts'][0]['cache_hit'])
        self.assertEqual(first['extraction_attempts'][0]['candidate_sha256'], second['extraction_attempts'][0]['candidate_sha256'])
        staged = stage_document(self.root, self.source, 'purchases.csv', extraction_engine=engine)
        with patch.object(engine, 'prepare', side_effect=AssertionError('completed extraction reran')):
            self.assertEqual(staged, stage_document(self.root, self.source, 'purchases.csv', extraction_engine=engine))
        manifest = json.loads((Path(staged['bundle']) / 'manifest.json').read_text())
        self.assertEqual(len(manifest['extraction_attempts']), 1)
        changed = engine.prepare(self.source + b'\n', 'purchases.csv')
        self.assertFalse(changed['extraction_attempts'][0]['cache_hit'])
        manifest_path = Path(staged['bundle']) / 'manifest.json'
        for field, value in [('extraction_policy', {'strategies': ['invented']}), ('format', 'pdf')]:
            forged = deepcopy(manifest)
            forged[field] = value
            manifest_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, 'immutable binding'):
                stage_document(self.root, self.source, 'purchases.csv', extraction_engine=engine)
        manifest_path.write_text(json.dumps(manifest))

    def test_extraction_rejects_unsupported_methods_and_bounds_failed_attempts(self):
        for methods in [[], ['native', 'native'], ['invented']]:
            with self.assertRaises(ValueError):
                ExtractionEngine(strategies=methods)
        for methods, filename, data in [(['pdf-text'], 'x.csv', self.source),
                                        (['native'], 'x.json', b'broken'),
                                        (['native'], 'x.txt', b'ok')]:
            engine = ExtractionEngine(strategies=methods, deadline=0 if filename == 'x.txt' else None)
            with self.assertRaises(ValueError):
                engine.prepare(data, filename)

    def test_pdf_strategy_alternative_preserves_review_and_records_attempt_order(self):
        empty = {'format': 'pdf', 'csv': None, 'pages': [{'text': '', 'page': 1}], 'review_reasons': []}
        text = deepcopy(empty)
        text['pages'][0]['text'] = 'Receipt total 1.00'
        engine = ExtractionEngine(strategies=['pdf-text', 'pdf-ocr'], cache=ExtractionCache(max_entries=3))
        with patch('neuron_flow.extraction.isolated', side_effect=[empty, text]):
            result = engine.prepare(b'PDF', 'receipt.pdf')
        self.assertIsNone(result['csv'])
        self.assertEqual([a['terminal_reason'] for a in result['extraction_attempts']], ['EMPTY_PAGE', 'EXTRACTION_COMPLETE'])
        self.assertEqual(engine.cache.stats()['entries'], 1)
        failure = OperationFailure({'reason_code': 'TIME_BUDGET_EXHAUSTED', 'message': 'probe'})
        with patch('neuron_flow.extraction.isolated', side_effect=failure), self.assertRaises(ValueError):
            ExtractionEngine().prepare(b'PDF', 'receipt.pdf')

    def test_request_model_rejects_unknown_fields_invalid_types_and_identity(self):
        for changes in [{'extra': True}, {'idempotency_key': '../bad'}, {'filename': '../x.csv'},
                        {'filename': 'x.exe'}, {'source_base64': '!!'}, {'run': 1}, {'ocr': 'yes'},
                        {'sheet': []}, {'language': ''}, {'timeout_s': True}, {'timeout_s': 10 ** 1000}, {'strategies': ['other']}, {'strategies': [[]]}]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                request_model(self.request(**changes))
        with self.assertRaises(ValueError):
            request_model({})
        with self.assertRaises(ValueError):
            JobQueue(self.root / 'bad', capacity=2, max_records=1)

    def test_queue_acceptance_conflicts_capacity_cancel_cursor_and_persistence(self):
        queue = self.queue(capacity=1, max_records=2)
        accepted = queue.submit(self.request())
        identifier = accepted['job_id']
        self.assertEqual(accepted['status'], 'QUEUED')
        self.assertEqual(queue.submit(self.request())['job_id'], identifier)
        with self.assertRaisesRegex(ValueError, 'IDEMPOTENCY_CONFLICT'):
            queue.submit(self.request(ocr=True))
        with self.assertRaisesRegex(ValueError, 'QUEUE_FULL'):
            queue.submit(self.request('two'))
        self.assertEqual(queue.cancel(identifier)['status'], 'CANCELLED')
        events = queue.events(identifier)
        queue.cancel(identifier)
        self.assertEqual(queue.events(identifier), events)
        self.assertEqual(queue.events(identifier, events[-1]['cursor']), [])
        with self.assertRaises(ValueError):
            queue.events(identifier, 2 ** 63)
        with self.assertRaises(KeyError):
            queue.status('missing')
        queue.submit(self.request('two'))
        queue.cancel(queue.db.execute("SELECT id FROM operation_jobs WHERE key='two'").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'QUEUE_FULL'):
            queue.submit(self.request('three'))
        other = JobQueue(queue.workspace)
        try:
            self.assertEqual(other.status(identifier)['status'], 'CANCELLED')
        finally:
            other.close()

    def test_queue_real_batch_receipts_and_review_required(self):
        queue = self.queue()
        first = queue.submit(self.request())
        result = queue.drain_one()
        self.assertEqual(result['job_id'], first['job_id'])
        self.assertEqual(result['status'], 'COMPLETED', result)
        self.assertEqual(result['result']['batch']['certified_total'], '412.70')
        self.assertEqual(queue.submit(self.request())['result'], result['result'])
        self.assertIsNone(queue.drain_one())
        receipt = queue.submit(self.request('receipt', filename='receipt.txt', source_base64=base64.b64encode(b'total 7.00').decode()))
        self.assertEqual(queue.drain_one()['status'], 'REVIEW_REQUIRED')
        self.assertIsNone(queue.status(receipt['job_id'])['result']['normalized_sha256'])
        self.assertTrue(queue.metrics()['telemetry']['phases']['batch']['total_count'])
        with self.assertRaises(ValueError):
            queue._finish(first['job_id'], 'wrong', 'COMPLETED', {})

    def test_queue_expiry_recovery_stop_and_adapter_changes(self):
        queue = self.queue()
        first = queue.submit(self.request(timeout_s=.05))
        time.sleep(.06)
        self.assertIsNone(queue.drain_one())
        self.assertEqual(queue.status(first['job_id'])['status'], 'EXPIRED')
        queued = queue.submit(self.request('recover', run=False))
        with queue.transaction():
            queue.db.execute("UPDATE operation_jobs SET status='RUNNING',attempts=1 WHERE id=?", (queued['job_id'],))
        self.assertEqual(queue.drain_one()['status'], 'COMPLETED')
        self.assertTrue(any(e['kind'] == 'WORKER_INTERRUPTED' for e in queue.events(queued['job_id'])))
        queue.submit(self.request('changed'))
        with patch('neuron_flow.extraction.identity', return_value={'changed': True}):
            self.assertEqual(queue.drain_one()['status'], 'FAILED')
        queue.submit(self.request('stopped'))
        queue.stop_requested.set()
        self.assertEqual(queue.drain_one()['status'], 'CANCELLED')

    def test_queue_worker_lock_and_transaction_rollback(self):
        queue = self.queue()
        lock = WorkspaceLock(queue.workspace / 'operations-worker.lock')
        try:
            with self.assertRaises(RuntimeError):
                queue.drain_one()
        finally:
            lock.close()
        with self.assertRaises(ValueError), queue.transaction():
            queue.event('no-job', 'ROLLED_BACK', {})
            raise ValueError('probe')
        self.assertEqual(queue.db.execute("SELECT count(*) FROM operation_events").fetchone()[0], 0)

    @unittest.skipUnless(os.name == 'posix', 'Actual controller-kill validation is scoped to POSIX')
    def test_real_worker_death_reclaims_exact_admission_and_finishes_next_request(self):
        queue = self.queue()
        admitted = queue.submit(self.request())
        process = subprocess.Popen([sys.executable, '-B', '-m', 'neuron_flow', 'ops', 'work', '--once',
                                    '--workspace', str(queue.workspace)], cwd=PROJECT,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and queue.status(admitted['job_id'])['status'] != 'RUNNING':
                time.sleep(.005)
            self.assertEqual(queue.status(admitted['job_id'])['status'], 'RUNNING')
            process.kill()
            process.wait(5)
            recovered = queue.drain_one()
            self.assertEqual(recovered['job_id'], admitted['job_id'])
            self.assertEqual(recovered['attempts'], 2)
            self.assertEqual(recovered['status'], 'COMPLETED', recovered)
            queue.submit(self.request('next', run=False))
            self.assertEqual(queue.drain_one()['status'], 'COMPLETED')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(5)

    def test_running_cancel_is_observed_by_the_real_worker(self):
        queue = self.queue()
        admitted = queue.submit(self.request())
        thread = threading.Thread(target=queue.drain_one)
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and queue.status(admitted['job_id'])['status'] != 'RUNNING':
            time.sleep(.005)
        queue.cancel(admitted['job_id'])
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(queue.status(admitted['job_id'])['status'], 'CANCELLED')

    def test_interrupted_attempt_budget_is_explicit_and_does_not_block_next_job(self):
        queue = self.queue()
        admitted = queue.submit(self.request())
        with queue.transaction():
            queue.db.execute("UPDATE operation_jobs SET status='RUNNING',attempts=2 WHERE id=?", (admitted['job_id'],))
        self.assertIsNone(queue.drain_one())
        result = queue.status(admitted['job_id'])
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['result']['reason_code'], 'INTERRUPTED_ATTEMPTS_EXHAUSTED')
        queue.submit(self.request('next', run=False))
        self.assertEqual(queue.drain_one()['status'], 'COMPLETED')

    def test_telemetry_bounds_samples_and_describes_drift_without_deciding(self):
        telemetry = Telemetry(retention=2)
        with telemetry.measure('extraction'):
            pass
        with self.assertRaises(ValueError), telemetry.measure('validation'):
            raise ValueError('probe')
        telemetry.record('batch', 4)
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot['retained_samples'], 2)
        self.assertEqual(snapshot['phases']['extraction']['retained_count'], 0)
        self.assertEqual(snapshot['phases']['validation']['errors_retained'], 1)
        for function in [lambda: Telemetry(0), lambda: telemetry.record('unknown', 1), lambda: telemetry.record('batch', float('inf'))]:
            with self.assertRaises(ValueError):
                function()
        a = [{'format': 'csv', 'status': 'VALID', 'currency': 'THB', 'source_bytes': 10}]
        b = [{'format': 'pdf', 'status': 'REVIEW_REQUIRED', 'currency': '', 'source_bytes': 20}]
        self.assertEqual(drift_report(a, a)['categorical_total_variation'], 0)
        self.assertEqual(drift_report(a, b)['categorical_total_variation'], 1)
        for value in [[], [{'wrong': 1}]]:
            with self.assertRaises(ValueError):
                drift_report(value, b)

    @unittest.skipUnless(__import__('importlib').util.find_spec('pypdf') and __import__('importlib').util.find_spec('pypdfium2') and __import__('shutil').which('tesseract'), 'install PDF/OCR extras and Tesseract')
    def test_actual_pdf_text_then_ocr_switch_stays_in_review(self):
        from tests.document_fixtures import receipt_image
        engine = ExtractionEngine(strategies=['pdf-text', 'pdf-ocr'], timeout_s=30)
        staged = stage_document(self.root / 'scan', receipt_image('PDF'), 'scan.pdf', extraction_engine=engine)
        self.assertEqual(staged['status'], 'REVIEW_REQUIRED')
        manifest = json.loads((Path(staged['bundle']) / 'manifest.json').read_text())
        self.assertEqual([a['method'] for a in manifest['extraction_attempts']], ['pdf-text', 'pdf-ocr'])
        self.assertIn('25.00', manifest['pages'][0]['text'])
