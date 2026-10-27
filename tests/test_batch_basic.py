"""Batch source ownership, independent results, and frozen reuse invariants."""

import json
from pathlib import Path
import tempfile
import unittest

from neuron_flow.batch import BatchRuntime, BatchConflict
from neuron_flow.csv_agents import FINAL_FIELDS

PROJECT = Path(__file__).resolve().parents[1]


class BatchBasicTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def test_locked_100_documents_and_duplicate_reuse_are_exact(self):
        source = (PROJECT / 'acceptance/input.csv').read_bytes()
        expected = json.loads((PROJECT / 'acceptance/expected_results.json').read_text())
        with BatchRuntime(self.workspace) as runtime:
            submitted = runtime.submit(source, 'golden')
            self.assertTrue(submitted['created'])
            first = runtime.run('golden')
            self.assertEqual(first['counts'], {'documents': 100, 'VALID': 80, 'INVALID': 20, 'ERROR': 0})
            actual = [{key: document[key] for key in FINAL_FIELDS} for document in first['documents']]
            self.assertEqual(actual, expected['documents'])
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in (self.workspace / 'reports').glob('*.json')}
            self.assertFalse(runtime.submit(source, 'golden')['created'])
            self.assertEqual(runtime.run('golden'), first)
            for path, (contents, modified) in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (contents, modified))
            self.assertLessEqual(runtime.runtime.soma.peak_workers, 3)
        with BatchRuntime(self.workspace) as resumed:
            self.assertEqual(resumed.run('golden'), first)
            self.assertEqual(resumed.runtime.soma.peak_workers, 0)

    def test_source_bytes_survive_file_removal_and_ungrouped_stay_separate(self):
        source = PROJECT / 'examples/purchases_invalid.csv'
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source.read_bytes(), 'mixed')
        with BatchRuntime(self.workspace) as runtime:
            result = runtime.run('mixed')
        self.assertEqual(result['counts'], {'documents': 3, 'VALID': 1, 'INVALID': 2, 'ERROR': 0})
        self.assertEqual(result['certified_total'], '10.00')
        self.assertEqual(result['input_rows'], 4)
        self.assertEqual([row['source_row'] for row in result['ungrouped_rows']], [5])
        self.assertEqual(sum(len(doc['source_rows']) for doc in result['documents'])
                         + len(result['ungrouped_rows']), result['input_rows'])

    def test_conflicting_bytes_do_not_change_original_binding(self):
        source = (PROJECT / 'examples/purchases.csv').read_bytes()
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(source, 'same')
            with self.assertRaises(BatchConflict):
                runtime.submit(source + b'\n', 'same')
            result = runtime.run('same')
            self.assertEqual(result['counts']['VALID'], 2)

    def test_corrupted_workflow_report_is_detected_on_reuse(self):
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit((PROJECT / 'examples/purchases.csv').read_bytes(), 'corrupt')
            result = runtime.run('corrupt')
            path = self.workspace / 'reports' / (result['documents'][0]['job_id'] + '.json')
            path.write_bytes(b'conflicting report')
            with self.assertRaises(BatchConflict):
                runtime.run('corrupt')
            self.assertEqual(path.read_bytes(), b'conflicting report')

    def test_bad_header_submits_no_batch(self):
        with BatchRuntime(self.workspace) as runtime:
            with self.assertRaises(ValueError):
                runtime.submit(b'document_id,quantity\nA,1\n', 'bad')
            self.assertEqual(runtime.runtime.store.db.execute('SELECT count(*) FROM csv_batches').fetchone()[0], 0)

    def test_header_only_and_unicode_document_id(self):
        header = b'document_id,item_id,description,quantity,unit_price,declared_total,currency\n'
        with BatchRuntime(self.workspace) as runtime:
            runtime.submit(header, 'empty')
            empty = runtime.run('empty')
            self.assertEqual(empty['counts']['documents'], 0)
            self.assertEqual(empty['certified_total'], '0.00')
            source = header + 'ใบ/../ไทย,A,ทดสอบ,1,0.01,0.01,THB\n'.encode()
            runtime.submit(source, 'thai')
            result = runtime.run('thai')
            self.assertEqual(result['documents'][0]['document_id'], 'ใบ/../ไทย')
            self.assertEqual(result['documents'][0]['document_status'], 'VALID')
            self.assertNotIn('/', result['documents'][0]['job_id'])
