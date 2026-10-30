import json
from pathlib import Path
import tempfile
import unittest

from tools.probe_operations import main, population


class OperationsProbeTests(unittest.TestCase):
    def test_seeded_inputs_reproduce_and_retry_original_identity(self):
        first = population(20261030, 8)
        self.assertEqual(first, population(20261030, 8))
        self.assertNotEqual(first, population(2, 8))
        self.assertEqual(first[3], first[2])
        for count in [0, True, 101]:
            with self.assertRaises(ValueError):
                population(requests=count)

    def test_real_replay_verifies_valid_invalid_currency_totals_and_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'probe'
            self.assertEqual(main(['--requests', '4', '--output-dir', str(root)]), 0)
            result = json.loads((root / 'operations_probe.json').read_text())
            self.assertEqual(result['unique_jobs'], 3)
            self.assertEqual(result['idempotent_retries'], 1)
            self.assertTrue(all(c['passed'] for c in result['checks']))
            self.assertEqual(result['pure_extraction_cache']['hits'], 2)
            self.assertIn('calculation', result['metrics']['telemetry']['phases'])
            self.assertIn('contract_validation', result['metrics']['telemetry']['phases'])
            self.assertIn('parsing', result['metrics']['telemetry']['phases'])
