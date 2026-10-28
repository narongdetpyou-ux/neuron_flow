"""The locked oracle must survive Git for Windows newline conversion settings."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class FixtureCheckoutTests(unittest.TestCase):
    def test_windows_autocrlf_checkout_preserves_locked_fixture_bytes(self):
        lock = json.loads((PROJECT / 'acceptance/fixture_lock.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / 'repository'
            repository.mkdir()
            (repository / 'acceptance').mkdir()
            shutil.copyfile(PROJECT / '.gitattributes', repository / '.gitattributes')
            for name in lock['files']:
                shutil.copyfile(PROJECT / 'acceptance' / name, repository / 'acceptance' / name)

            def git(*arguments):
                result = subprocess.run(
                    ['git', '-C', str(repository), '-c', 'core.autocrlf=true',
                     '-c', 'core.eol=crlf', *arguments],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

            git('init', '--quiet')
            git('add', '--', '.gitattributes', 'acceptance')
            checkout = root / 'checkout'
            git('checkout-index', '--all', '--prefix=' + checkout.as_posix() + '/')
            for name, expected in lock['files'].items():
                with self.subTest(name=name):
                    data = (checkout / 'acceptance' / name).read_bytes()
                    self.assertEqual(len(data), expected['size_bytes'])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256'])
