"""Source checkout must not accidentally validate Colab against an old manifest."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_current


class VerificationManifestTests(unittest.TestCase):
    def test_missing_package_manifest_fails_before_tests_or_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'evidence'
            stderr = io.StringIO()
            with patch.object(verify_current, 'PROJECT', root), \
                    patch.object(verify_current, 'run_script') as run_script, \
                    contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                verify_current.main(['--colab-evidence', str(root / 'colab.json'),
                                     '--output-dir', str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertIn('verified extracted package', stderr.getvalue())
            self.assertFalse(output.exists())
            run_script.assert_not_called()
