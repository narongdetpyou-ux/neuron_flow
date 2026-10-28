"""Negative checks for the installed-package verification helper."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.check_distribution import receipt_snapshot


class DistributionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        artifacts = {}
        for name in ('summary.csv', 'details.json', 'source.csv'):
            data = name.encode('utf-8')
            path = self.root / name
            path.write_bytes(data)
            artifacts[name] = {'path': str(path), 'bytes': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()}
        self.result = {'status': 'DELIVERED', 'certified_total': '412.70',
                       'counts': {'documents': 2, 'VALID': 2, 'INVALID': 0, 'ERROR': 0},
                       'receipt': {'artifacts': artifacts}}

    def test_rejects_tampered_artifact_after_success(self):
        before = receipt_snapshot(self.result)
        self.assertEqual(set(before), {'summary.csv', 'details.json', 'source.csv'})
        (self.root / 'summary.csv').write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError, 'integrity failure'):
            receipt_snapshot(self.result)

    def test_rejects_missing_receipt_artifact(self):
        del self.result['receipt']['artifacts']['source.csv']
        with self.assertRaisesRegex(RuntimeError, 'incomplete artifacts'):
            receipt_snapshot(self.result)

    def test_rejects_incorrect_certified_total(self):
        self.result['certified_total'] = '412.71'
        with self.assertRaisesRegex(RuntimeError, 'expected result'):
            receipt_snapshot(self.result)


if __name__ == '__main__':
    unittest.main()
