from copy import deepcopy
import unittest

from tools.prepare_publication import prepare, validate_request, wait_for_ci


class PublicationRequestTests(unittest.TestCase):
    def setUp(self):
        self.commit = 'a' * 40
        self.request = {'schema_version': 1, 'request_id': 'synthetic', 'version': '0.4.0', 'tag': 'v0.4.0', 'publish': True}
        self.approval = {'version': '0.4.0', 'release_approved': True, 'decision': 'release_with_disclosed_known_limitation'}
        names = ['quality', 'test (3.10)', 'test (3.12)', 'distribution (3.10)', 'distribution (3.12)',
                 'platform-smoke (windows-latest, 3.10)', 'platform-smoke (windows-latest, 3.12)',
                 'platform-smoke (macos-latest, 3.10)', 'platform-smoke (macos-latest, 3.12)']
        self.jobs = [{'name': name, 'conclusion': 'success'} for name in names]
        self.run = {'id': 1, 'head_sha': self.commit, 'path': '.github/workflows/ci.yml', 'status': 'completed', 'conclusion': 'success'}
        self.remote = None
        self.writes = []

    def api(self, method, path, body=None):
        if method == 'POST':
            self.writes.append((path, body))
            self.remote = {'object': {'sha': body['sha'], 'type': 'commit'}}
            return self.remote
        if '/jobs?' in path:
            return {'jobs': self.jobs}
        if '/actions/runs?' in path:
            return {'workflow_runs': [self.run]}
        return self.remote

    def test_exact_approved_source_waits_for_nine_jobs_and_reuses_identical_tag(self):
        result = prepare(self.api, 'owner/repo', self.commit, self.request, self.approval, '0.4.0')
        self.assertTrue(result['publish'])
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0][1], {'ref': 'refs/tags/v0.4.0', 'sha': self.commit})
        prepare(self.api, 'owner/repo', self.commit, self.request, self.approval, '0.4.0')
        self.assertEqual(len(self.writes), 1)

    def test_unapproved_version_false_publish_and_malformed_inputs_never_write(self):
        for changes in [{'publish': False}, {'publish': 1}, {'version': '0.5.0'}, {'tag': 'v0.3.0'}, {'extra': True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare(self.api, 'owner/repo', self.commit, {**self.request, **changes}, self.approval, '0.4.0')
        with self.assertRaises(ValueError):
            validate_request(self.request, {**self.approval, 'release_approved': False}, '0.4.0', self.commit)
        self.assertEqual(self.writes, [])

    def test_failed_or_partial_ci_conflicting_tag_and_wait_exhaustion_never_write(self):
        self.run['conclusion'] = 'failure'
        with self.assertRaises(ValueError):
            prepare(self.api, 'owner/repo', self.commit, self.request, self.approval, '0.4.0')
        self.run['conclusion'] = 'success'
        self.jobs.pop()
        with self.assertRaises(ValueError):
            wait_for_ci(self.api, 'owner/repo', self.commit)
        self.run['status'] = 'in_progress'
        with self.assertRaises(ValueError):
            wait_for_ci(self.api, 'owner/repo', self.commit, polls=2, sleep=lambda _: None)
        self.run['status'] = 'completed'
        self.setUp()
        self.remote = {'object': {'sha': 'b' * 40, 'type': 'commit'}}
        with self.assertRaisesRegex(ValueError, 'never overwrite'):
            prepare(self.api, 'owner/repo', self.commit, self.request, self.approval, '0.4.0')
        self.assertEqual(self.writes, [])
