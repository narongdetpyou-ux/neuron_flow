"""Failure annotations must retain traces without creating workflow commands."""

import unittest

from tools.platform_smoke import annotation


class PlatformAnnotationTests(unittest.TestCase):
    def test_multiline_failure_trace_is_one_escaped_annotation(self):
        text = annotation(self, 'AssertionError: 100%\r\n::notice::test output\n')
        self.assertTrue(text.startswith('::error title='))
        self.assertIn('AssertionError: 100%25%0D%0A::notice::test output%0A', text)
        self.assertNotIn('\n', text)
        self.assertNotIn('\r', text)
