"""Keep immutable automation and build-lock verification tied to source identity."""

import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.verify_current import project_fingerprint

PROJECT = Path(__file__).resolve().parents[1]


class WorkflowPolicyTests(unittest.TestCase):
    def test_actions_are_pinned_to_full_commits(self):
        references = []
        for path in (PROJECT / '.github/workflows').glob('*.yml'):
            references.extend(re.findall(r'^\s*- uses:\s*(\S+)', path.read_text(), re.M))
        self.assertTrue(references)
        for reference in references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r'^[^@]+@[0-9a-f]{40}$')

    def test_proposed_ruleset_preserves_baseline_checks_and_quality_gates(self):
        policy = json.loads((PROJECT / '.github/policies/main-ruleset.json').read_text())
        rule = next(r for r in policy['rules'] if r['type'] == 'required_status_checks')
        contexts = {c['context'] for c in rule['parameters']['required_status_checks']}
        self.assertEqual(contexts, {'test (3.10)', 'test (3.12)', 'quality',
                                    'distribution (3.10)', 'distribution (3.12)'})

    def test_build_and_quality_configuration_changes_invalidate_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = project_fingerprint(root)
            for name in ('requirements-build.txt', 'requirements-dev.txt', '.coveragerc'):
                with self.subTest(name=name):
                    (root / name).write_text('changed build or quality contract\n')
                    after = project_fingerprint(root)
                    self.assertNotEqual(after, before)
                    before = after
