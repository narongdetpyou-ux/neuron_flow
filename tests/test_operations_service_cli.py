import base64
from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from neuron_flow.__main__ import main
from neuron_flow.intake import review_document, stage_document
from neuron_flow.operations import JobQueue
from neuron_flow.reporting import BatchTerminal
from neuron_flow.service import create_server, serve
from tests.test_reporting import frozen_example

PROJECT = Path(__file__).resolve().parents[1]


class ServiceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'workspace'
        self.source = self.root / 'purchases.csv'
        self.source.write_bytes((PROJECT / 'examples/purchases.csv').read_bytes())

    def server(self, capacity=100):
        queue = JobQueue(self.workspace, capacity=capacity)
        server = create_server(queue, 'r' * 32, 'w' * 32, 0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            thread.join(2)
            server.server_close()
            queue.close()
        self.addCleanup(cleanup)
        return queue, server.server_port

    def http(self, port, method, path, body=None, token='w' * 32, headers=None, raw=None):
        connection = HTTPConnection('127.0.0.1', port, timeout=5)
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        request_headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', **(headers or {})}
        connection.request(method, path, body=data, headers=request_headers)
        result = connection.getresponse()
        value = json.loads(result.read())
        status = result.status
        connection.close()
        return status, value

    def request(self, key='one'):
        return {'idempotency_key': key, 'filename': 'purchases.csv', 'source_base64': base64.b64encode(self.source.read_bytes()).decode()}

    def cli(self, *args, expected=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = main(list(map(str, args)))
        self.assertEqual(status, expected, error.getvalue() + output.getvalue())
        return json.loads(error.getvalue() if status == 2 else output.getvalue())

    def test_http_roles_admission_completion_events_and_cancel(self):
        queue, port = self.server()
        self.assertEqual(self.http(port, 'GET', '/health', token='wrong')[0], 403)
        self.assertEqual(self.http(port, 'GET', '/health', token='r' * 32)[0], 200)
        self.assertEqual(self.http(port, 'POST', '/jobs', self.request(), token='r' * 32)[0], 403)
        status, first = self.http(port, 'POST', '/jobs', self.request())
        self.assertEqual(status, 202)
        self.assertEqual(first['status'], 'QUEUED')
        self.assertEqual(self.http(port, 'POST', '/jobs', self.request())[1]['job_id'], first['job_id'])
        changed = self.request()
        changed['ocr'] = True
        self.assertEqual(self.http(port, 'POST', '/jobs', changed)[0], 409)
        self.assertEqual(queue.drain_one()['status'], 'COMPLETED')
        path = '/jobs/' + first['job_id']
        self.assertEqual(self.http(port, 'GET', path, token='r' * 32)[1]['status'], 'COMPLETED')
        self.assertTrue(self.http(port, 'GET', path + '/events?after=0')[1]['events'])
        self.assertEqual(self.http(port, 'GET', '/metrics')[1]['jobs']['COMPLETED'], 1)
        second = self.http(port, 'POST', '/jobs', self.request('second'))[1]
        self.assertEqual(self.http(port, 'POST', '/jobs/' + second['job_id'] + '/cancel', {})[1]['status'], 'CANCELLED')

    def test_http_rejects_capacity_malformed_unknown_and_unbounded_requests(self):
        queue, port = self.server(capacity=1)
        self.assertEqual(self.http(port, 'POST', '/jobs', self.request())[0], 202)
        self.assertEqual(self.http(port, 'POST', '/jobs', self.request('second'))[0], 429)
        self.assertEqual(self.http(port, 'POST', '/jobs', {**self.request(), 'extra': 1})[0], 400)
        for path in ['/unknown', '/jobs/' + '0' * 32]:
            self.assertEqual(self.http(port, 'GET', path)[0], 404)
        self.assertEqual(self.http(port, 'POST', '/unknown', {})[0], 404)
        identifier = queue.db.execute('SELECT id FROM operation_jobs').fetchone()[0]
        self.assertEqual(self.http(port, 'POST', '/jobs/' + identifier + '/cancel', {'extra': 1})[0], 400)
        self.assertEqual(self.http(port, 'GET', '/jobs/' + identifier + '/events?after=bad')[0], 400)
        self.assertEqual(self.http(port, 'POST', '/jobs', raw=b'{')[0], 400)
        self.assertEqual(self.http(port, 'POST', '/jobs', raw=b'{"x":1,"x":2}')[0], 400)
        self.assertEqual(self.http(port, 'POST', '/jobs', {}, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.http(port, 'POST', '/jobs', {}, headers={'Transfer-Encoding': 'chunked'})[0], 411)
        self.assertEqual(self.http(port, 'POST', '/jobs', {}, headers={'Content-Length': str(25 * 1024 * 1024)})[0], 413)

    def test_server_token_and_port_contract_and_orderly_worker_shutdown(self):
        queue = JobQueue(self.workspace)
        try:
            for read, write, port in [('', 'w' * 32, 0), ('s' * 32, 's' * 32, 0), ('r' * 32, 'w' * 32, -1)]:
                with self.assertRaises(ValueError):
                    create_server(queue, read, write, port)
        finally:
            queue.close()
        fake = Mock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with patch('neuron_flow.service.create_server', return_value=fake):
            self.assertEqual(serve(self.workspace, 'r' * 32, 'w' * 32, 0), {'status': 'STOPPED'})
        self.assertTrue(fake.server_close.called)

    def test_cli_queue_stage_discovery_events_and_failure_codes(self):
        queued = self.cli('ops', 'submit', self.source, '--key', 'cli', '--workspace', self.workspace, '--stage-only')
        identifier = queued['job_id']
        self.assertEqual(self.cli('ops', 'status', identifier, '--workspace', self.workspace)['status'], 'QUEUED')
        self.assertTrue(self.cli('ops', 'events', identifier, '--workspace', self.workspace)['events'])
        self.assertEqual(self.cli('ops', 'work', '--once', '--workspace', self.workspace)['status'], 'COMPLETED')
        self.assertEqual(self.cli('ops', 'work', '--once', '--workspace', self.workspace)['status'], 'IDLE')
        self.assertEqual(self.cli('ops', 'cancel', identifier, '--workspace', self.workspace)['status'], 'COMPLETED')
        self.assertEqual(self.cli('ops', 'metrics', '--workspace', self.workspace)['jobs']['COMPLETED'], 1)
        self.assertIn('error', self.cli('ops', 'status', 'missing', '--workspace', self.workspace, expected=2))
        staged = self.cli('ops', 'stage', self.source, '--workspace', self.workspace)
        self.assertEqual(staged['status'], 'READY')
        with patch('neuron_flow.operations_cli.time.sleep', side_effect=KeyboardInterrupt):
            self.assertEqual(self.cli('ops', 'work', '--workspace', self.workspace)['status'], 'STOPPED')
        with patch.dict('os.environ', {'TEST_READ': 'r' * 32, 'TEST_WRITE': 'w' * 32}), patch('neuron_flow.service.serve', return_value={'status': 'STOPPED'}) as run:
            self.cli('ops', 'serve', '--workspace', self.workspace, '--read-token-env', 'TEST_READ', '--write-token-env', 'TEST_WRITE')
            self.assertEqual(run.call_args.args[1:3], ('r' * 32, 'w' * 32))

    def test_cli_gate_policy_shadow_and_drift(self):
        from neuron_flow.extraction import ExtractionEngine
        from neuron_flow.intake import run_document
        staged = stage_document(self.workspace, self.source.read_bytes(), 'purchases.csv', extraction_engine=ExtractionEngine())
        run_document(self.workspace, staged['intake_id'], workers=1)
        report = self.workspace / ('batch_reports/intake_' + staged['intake_id'])
        case = {'case_id': 'a', 'cluster_id': 'layout-a', 'split': 'holdout', 'format': 'csv',
                'report_directory': str(report), 'latency_ms': 2, 'attempts': 1, 'first_method_success': True,
                'intake_workspace': str(self.workspace), 'intake_id': staged['intake_id']}
        path = self.root / 'gate.json'
        path.write_text(json.dumps({'reference': [case], 'candidate': [case]}))
        self.assertTrue(self.cli('ops', 'gate', path)['accepted'])
        policy = self.root / 'policy.json'
        self.assertTrue(self.cli('ops', 'policy-accept', path, policy, '--strategy', 'native')['gate']['accepted'])
        self.assertEqual(self.cli('ops', 'stage', self.source, '--policy', policy, '--workspace', self.workspace)['status'], 'READY')
        with patch('neuron_flow.evaluation.run_shadow', return_value={'agreement': True}) as shadow:
            self.cli('ops', 'shadow', report)
            shadow.assert_called_once()
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps([{'format': 'csv', 'status': 'VALID', 'currency': 'THB', 'source_bytes': 12}]))
        self.assertEqual(self.cli('ops', 'drift', profile, profile)['categorical_total_variation'], 0)
        changed = {**case, 'first_method_success': False}
        path.write_text(json.dumps({'reference': [case], 'candidate': [changed]}))
        self.assertFalse(self.cli('ops', 'gate', path, expected=1)['accepted'])

    def test_cli_reviewed_memory_and_integrity_round_trip(self):
        receipt = stage_document(self.workspace, b'Receipt total 412.70', 'receipt.txt')
        review_document(self.workspace, receipt['intake_id'], self.source.read_bytes(), 'synthetic-reviewer')
        profile = '[1,0,0,0,0,0]'
        self.cli('ops', 'memory-learn', receipt['intake_id'], self.source, '--workspace', self.workspace,
                 '--profile', profile, '--policy-version', 'v1', '--method', 'native', '--cluster-id', 'layout-a')
        self.assertEqual(len(self.cli('ops', 'memory-retrieve', '--workspace', self.workspace,
                                      '--profile', profile, '--policy-version', 'v1')['cases']), 1)
        backup = self.root / 'backup'
        self.assertTrue(self.cli('ops', 'backup', self.workspace, backup)['ok'])
        self.assertTrue(self.cli('ops', 'integrity', backup)['ok'])
        shutil.rmtree(self.workspace)
        self.assertTrue(self.cli('ops', 'restore', backup, self.workspace)['restored'])
        (backup / 'extra').write_text('extra')
        self.assertFalse(self.cli('ops', 'integrity', backup, expected=1)['ok'])
