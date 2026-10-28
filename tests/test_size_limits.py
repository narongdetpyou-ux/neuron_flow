"""Real wire, output and report boundaries without changing the declared caps."""

import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from neuron_flow import AgentDefinition, Runtime, SpecError
from neuron_flow.batch import BatchRuntime
from neuron_flow.csv_input import FIELDS, MAX_SOURCE_BYTES, CsvInputError, read_csv_bytes
from neuron_flow.csv_agents import (calculate_csv, calculate_csv_output, validate_csv,
                                    validate_csv_output, verify_csv, verify_csv_output)
from neuron_flow.engine import AxonTerminal
from neuron_flow.model import MAX_MESSAGE_BYTES, MessageSizeError, decode, encode


def _mark(message):
    marker = message['params'].get('marker')
    if marker:
        with Path(marker).open('a', encoding='utf-8') as stream:
            stream.write(str(message['attempt']) + '\n')


def blob(message):
    _mark(message)
    return {'blob': 'x' * message['params'].get('size', 0)}


def validate_blob(message, output):
    if (set(output) != {'blob'} or not isinstance(output['blob'], str)
            or len(output['blob']) != message['params'].get('size', 0)):
        raise ValueError('Incorrect blob result')


def sink(message):
    _mark(message)
    return {'ok': True}


def validate_sink(message, output):
    if type(output) is not dict or output != {'ok': True}:
        raise ValueError('Incorrect success result')


def inflate_validator(message, output):
    output['blob'] = 'x' * MAX_MESSAGE_BYTES


def definitions():
    return [AgentDefinition('blob', 'tests.test_size_limits:blob', validate_blob),
            AgentDefinition('sink', 'tests.test_size_limits:sink', validate_sink),
            AgentDefinition('inflate', 'tests.test_size_limits:blob', inflate_validator)]


def _padded(message, result):
    if message['input']['document_id'] == 'PADDED':
        result['diagnostic_padding'] = 'x' * 400_000
    return result


def _without_padding(message, result):
    result = dict(result)
    padding = result.pop('diagnostic_padding', None)
    expected = 'x' * 400_000 if message['input']['document_id'] == 'PADDED' else None
    if padding != expected:
        raise ValueError('Diagnostic output padding differs')
    return result


def padded_validate(message):
    return _padded(message, validate_csv(message))


def validate_padded_validation(message, result):
    validate_csv_output(message, _without_padding(message, result))


def padded_calculate(message):
    return _padded(message, calculate_csv(message))


def validate_padded_calculation(message, result):
    calculate_csv_output(message, _without_padding(message, result))


def _verification_message(message):
    result = {**message, 'dependencies': dict(message['dependencies'])}
    calculation = message['params']['calculation']
    result['dependencies'][calculation] = _without_padding(message, result['dependencies'][calculation])
    return result


def padded_verify(message):
    return _padded(message, verify_csv(_verification_message(message)))


def validate_padded_verification(message, result):
    verify_csv_output(_verification_message(message), _without_padding(message, result))


def padded_definitions():
    return [
        AgentDefinition('csv_validate', 'tests.test_size_limits:padded_validate', validate_padded_validation, 'size-test1'),
        AgentDefinition('csv_calculate', 'tests.test_size_limits:padded_calculate', validate_padded_calculation, 'size-test1'),
        AgentDefinition('csv_verify', 'tests.test_size_limits:padded_verify', validate_padded_verification, 'size-test1'),
    ]


def _csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(FIELDS)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


class SizeLimitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='neuron-size-limits-')
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def assert_size_error(self, error, phase):
        self.assertEqual(error['phase'], phase)
        self.assertEqual(error['limit_bytes'], MAX_MESSAGE_BYTES)
        self.assertGreater(error['observed_bytes'], error['limit_bytes'])
        self.assertIs(error['retryable'], False)

    def test_exact_json_limit_and_utf8_byte_measurement(self):
        overhead = len(encode({'body': ''}))
        exact = {'body': 'a' * (MAX_MESSAGE_BYTES - overhead)}
        data = encode(exact)
        self.assertEqual(len(data), MAX_MESSAGE_BYTES)
        self.assertEqual(decode(data), exact)
        with self.assertRaises(MessageSizeError) as raised:
            encode({'body': exact['body'] + 'x'}, phase='test_boundary')
        self.assertIsInstance(raised.exception, SpecError)
        self.assertEqual(raised.exception.observed_bytes, MAX_MESSAGE_BYTES + 1)
        with self.assertRaises(MessageSizeError) as raised:
            decode(b' ' + data)
        self.assert_size_error(raised.exception.details(), 'json_input')
        unicode_value = {'body': 'ก' * (MAX_MESSAGE_BYTES // 3 + 1)}
        observed = len(json.dumps(unicode_value, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':')).encode('utf-8'))
        with self.assertRaises(MessageSizeError) as raised:
            encode(unicode_value, phase='utf8_boundary')
        self.assertEqual(raised.exception.observed_bytes, observed)
        self.assert_size_error(raised.exception.details(), 'utf8_boundary')

    def test_csv_exact_source_cap_and_one_byte_over(self):
        prefix = ','.join(FIELDS).encode() + b'\nBIG,A,'
        suffix = b',1,1.00,1.00,THB\n'
        data = prefix + b'x' * (MAX_SOURCE_BYTES - len(prefix) - len(suffix)) + suffix
        self.assertEqual(len(data), MAX_SOURCE_BYTES)
        parsed = read_csv_bytes(data)
        self.assertEqual(parsed['input_rows'], 1)
        self.assertEqual(parsed['documents'][0]['document_id'], 'BIG')
        self.assertEqual(parsed['source_sha256'], hashlib.sha256(data).hexdigest())
        with self.assertRaisesRegex(CsvInputError, 'exceeds'):
            read_csv_bytes(data + b'\n')

    def test_oversized_workflow_rejects_only_its_document_with_details(self):
        rows = [['BIG', f'I{index}', 'x' * 500, 1, '1.00', '1000.00', 'THB']
                for index in range(1000)]
        rows.append(['GOOD', 'A', 'other document survives', 1, '1.00', '1.00', 'THB'])
        source = _csv(rows)
        self.assertLess(len(source), MAX_SOURCE_BYTES)
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, 'size-isolation')
            delivery = runtime.deliver('size-isolation')
            result = runtime.run('size-isolation')
            self.assertEqual(delivery['counts'], {'documents': 2, 'VALID': 1, 'INVALID': 0, 'ERROR': 1})
            oversized, healthy = result['documents']
            self.assertEqual(oversized['engine_status'], 'REJECTED')
            error = oversized['errors'][0]['actual']
            self.assertEqual(error['type'], 'MessageSizeError')
            self.assert_size_error(error, 'workflow_submission')
            self.assertEqual(healthy['computed_total'], '1.00')
            self.assertEqual(result['certified_total'], '1.00')
            before = runtime.runtime.store.events_for('monitor', healthy['job_id'])
            self.assertEqual(runtime.run('size-isolation'), result)
            self.assertEqual(runtime.runtime.store.events_for('monitor', healthy['job_id']), before)

    def test_combined_dependencies_overflow_before_agent_executes_without_retry(self):
        marker = self.workspace / 'must-not-execute'
        spec = {'job_id': 'request_limit', 'input': {'padding': 'p' * 600_000}, 'steps': [
            {'id': 'source', 'agent': 'blob', 'params': {'size': 600_000}},
            {'id': 'oversized_request', 'agent': 'sink', 'depends_on': ['source'],
             'params': {'marker': str(marker)}, 'max_attempts': 2},
            {'id': 'independent', 'agent': 'sink'},
        ]}
        self.assertLess(len(encode(spec)), MAX_MESSAGE_BYTES)
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit(spec)
            result = runtime.run('request_limit')
        failed = result['steps']['oversized_request']
        self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual(failed['attempts'], 1)
        self.assertEqual(failed['error']['type'], 'InputContractError')
        self.assertEqual(failed['error']['cause'], 'MessageSizeError')
        self.assert_size_error(failed['error'], 'agent_request')
        self.assertFalse(marker.exists())
        self.assertEqual(result['steps']['independent']['status'], 'SUCCEEDED')
        self.assertEqual(result['status'], 'FAILED')
        self.assertIsNotNone(result['receipt'])

    def test_oversized_agent_response_is_permanent_and_other_work_finishes(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({'job_id': 'response_limit', 'steps': [
                {'id': 'oversized', 'agent': 'blob', 'params': {'size': MAX_MESSAGE_BYTES}, 'max_attempts': 2},
                {'id': 'independent', 'agent': 'sink'},
            ]})
            result = runtime.run('response_limit')
        failed = result['steps']['oversized']
        self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual(failed['attempts'], 1)
        self.assertIsNone(failed['output'])
        self.assertEqual(failed['error']['type'], 'MessageSizeError')
        self.assert_size_error(failed['error'], 'agent_response')
        self.assertEqual(result['steps']['independent']['status'], 'SUCCEEDED')
        self.assertEqual(result['status'], 'FAILED')

    def test_validator_cannot_persist_an_oversized_output(self):
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit({'job_id': 'validator_limit', 'steps': [
                {'id': 'mutated', 'agent': 'inflate', 'max_attempts': 2},
            ]})
            result = runtime.run('validator_limit')
        failed = result['steps']['mutated']
        self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual(failed['attempts'], 1)
        self.assertIsNone(failed['output'])
        self.assertEqual(failed['error']['type'], 'OutputValidationError')
        self.assertEqual(failed['error']['cause'], 'MessageSizeError')
        self.assert_size_error(failed['error'], 'agent_output_validation')

    def test_oversized_terminal_report_preserves_steps_and_structured_error_on_resume(self):
        first_marker, second_marker = self.workspace / 'first.calls', self.workspace / 'second.calls'
        spec = {'job_id': 'terminal_limit', 'steps': [
            {'id': 'first', 'agent': 'blob', 'params': {'size': 600_000, 'marker': str(first_marker)}},
            {'id': 'second', 'agent': 'blob', 'params': {'size': 600_000, 'marker': str(second_marker)}},
        ]}
        with Runtime(self.workspace, agents=definitions()) as runtime:
            runtime.submit(spec)
            first = runtime.run('terminal_limit')
        self.assertEqual(first['status'], 'DELIVERY_FAILED')
        self.assertIsNone(first['receipt'])
        self.assertFalse((self.workspace / 'reports/terminal_limit.json').exists())
        self.assertIsInstance(first['delivery_error'], str)
        self.assert_size_error(first['delivery_error_details'], 'terminal_report')
        self.assertEqual(first['delivery_error_details']['type'], 'MessageSizeError')
        with Runtime(self.workspace, agents=definitions()) as runtime:
            persisted = runtime.status('terminal_limit')
            self.assertEqual(persisted['delivery_error_details'], first['delivery_error_details'])
            resumed = runtime.run('terminal_limit')
        self.assertEqual(resumed['status'], 'DELIVERY_FAILED')
        self.assertIsNone(resumed['receipt'])
        self.assertEqual(resumed['peak_workers'], 0)
        self.assertEqual(resumed['steps'], first['steps'])
        self.assertEqual(first_marker.read_text(), '1\n')
        self.assertEqual(second_marker.read_text(), '1\n')

    def test_terminal_newline_counts_toward_the_report_byte_limit(self):
        report = {'job_id': 'exact_report', 'status': 'SUCCEEDED', 'steps': {
            'a': {'status': 'SUCCEEDED', 'attempts': 1, 'output': {'blob': ''}, 'error': None}}}
        size = MAX_MESSAGE_BYTES - len(encode(report)) - 1
        report['steps']['a']['output']['blob'] = 'x' * size
        terminal = AxonTerminal(self.workspace / 'reports')
        receipt = terminal.deliver(report)
        path = Path(receipt['path'])
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(receipt['bytes'], MAX_MESSAGE_BYTES)
        report['steps']['a']['output']['blob'] += 'x'
        with self.assertRaises(MessageSizeError) as raised:
            terminal.deliver(report)
        self.assertEqual(raised.exception.phase, 'terminal_report')
        self.assertEqual(raised.exception.observed_bytes, MAX_MESSAGE_BYTES + 1)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_permanent_document_report_size_error_does_not_block_batch_delivery(self):
        # Each valid Agent response and dependency command fits individually;
        # retaining all three checked results makes only the final report exceed
        # its limit. This is different from worker/request/output rejection.
        source = _csv([['PADDED', 'A', 'large diagnostics', 1, '1.00', '1.00', 'THB'],
                       ['GOOD', 'A', 'independent document', 1, '1.00', '1.00', 'THB']])
        with BatchRuntime(self.workspace, agents=padded_definitions()) as runtime:
            runtime.submit(source, 'terminal-size-isolation')
            delivery = runtime.deliver('terminal-size-isolation')
            result = runtime.run('terminal-size-isolation')
            self.assertEqual(delivery['status'], 'DELIVERED')
            self.assertEqual(delivery['counts'], {'documents': 2, 'VALID': 1, 'INVALID': 0, 'ERROR': 1})
            oversized, healthy = result['documents']
            self.assertEqual(oversized['document_status'], 'ERROR')
            self.assertEqual(oversized['engine_status'], 'DELIVERY_FAILED')
            self.assertIsNone(oversized['computed_total'])
            error = oversized['errors'][0]['actual']['delivery_error_details']
            self.assert_size_error(error, 'terminal_report')
            self.assertEqual(error['type'], 'MessageSizeError')
            self.assertTrue(all(step['status'] == 'SUCCEEDED' and step['attempts'] == 1
                                for step in oversized['steps'].values()))
            self.assertEqual(healthy['document_status'], 'VALID')
            self.assertEqual(result['certified_total'], '1.00')
            history = {doc['job_id']: runtime.runtime.store.events_for('monitor', doc['job_id'])
                       for doc in result['documents']}
            files = {name: (Path(artifact['path']).read_bytes(), Path(artifact['path']).stat().st_mtime_ns)
                     for name, artifact in delivery['receipt']['artifacts'].items()}
            self.assertEqual(runtime.deliver('terminal-size-isolation'), delivery)
            for doc in result['documents']:
                self.assertEqual(runtime.runtime.store.events_for('monitor', doc['job_id']), history[doc['job_id']])
            for name, artifact in delivery['receipt']['artifacts'].items():
                path = Path(artifact['path'])
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), files[name])


if __name__ == '__main__':
    unittest.main()
