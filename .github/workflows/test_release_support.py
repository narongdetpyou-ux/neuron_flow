"""Offline publication guards; these tests never contact GitHub."""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('release_support', Path(__file__).with_name('release_support.py'))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
COMMIT = 'a' * 40


class FakeGitHub:
    def __init__(self, existing=None):
        self.release = deepcopy(existing)
        self.uploaded = []
        self.published = False
        self.created = False
        self.remote_commit = COMMIT
        self.fail_name = None

    def tag_commit(self, _tag):
        return self.remote_commit

    def find_release(self, _tag):
        return deepcopy(self.release)

    def create_draft(self, tag, version, notes):
        self.created = True
        self.release = {'id': 7, 'draft': True, 'prerelease': False, 'tag_name': tag,
                        'assets': [], 'body': notes.read_text(encoding='utf-8'),
                        'html_url': 'https://github.com/owner/project/releases/tag/' + tag}
        return deepcopy(self.release)

    def verify_asset(self, _tag, asset, expected):
        if (asset['state'] != 'uploaded' or asset['size'] != expected['bytes']
                or asset['digest'] != 'sha256:' + expected['sha256']):
            raise ValueError('Remote file differs')

    def upload(self, _tag, path):
        if path.name == self.fail_name:
            raise RuntimeError('Upload failed')
        self.uploaded.append(path.name)
        self.release['assets'].append({'name': path.name, 'size': path.stat().st_size,
                                      'state': 'uploaded', 'digest': 'sha256:' + release.digest(path)})

    def refresh(self, _release_id):
        return deepcopy(self.release)

    def publish(self, _tag):
        self.published = True
        self.release['draft'] = False
        return deepcopy(self.release)


class ReleaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        facts = {'tag': 'v0.2.1', 'version': '0.2.1', 'source_commit': COMMIT,
                 'publication_requested': True, 'release_approved': True,
                 'approval_decision': 'release_with_disclosed_known_limitation'}
        names = ['neuron_flow_v0.2.1.zip', 'neuron_flow_v0.2.1.zip.sha256',
                 'SHA256SUMS.txt', 'START_COLAB.ipynb', 'delivery_checks.json']
        files = []
        for name in names:
            path = self.directory / name
            path.write_text('verified contents: ' + name, encoding='utf-8')
            files.append({'name': name, 'bytes': path.stat().st_size, 'sha256': release.digest(path)})
        release.write_json(self.directory / 'publication_attestation.json', {**facts, 'artifacts': deepcopy(files)})
        files.append({'name': 'publication_attestation.json',
                      'bytes': (self.directory / 'publication_attestation.json').stat().st_size,
                      'sha256': release.digest(self.directory / 'publication_attestation.json')})
        (self.directory / 'release-notes.md').write_text('# Neuron Flow 0.2.1\n\nColab not yet verified.\n', encoding='utf-8')
        self.manifest = {**facts, 'files': files,
                         'notes_sha256': release.digest(self.directory / 'release-notes.md')}

    def existing(self, file_names=()):
        assets = [{'name': item['name'], 'size': item['bytes'], 'state': 'uploaded',
                   'digest': 'sha256:' + item['sha256']}
                  for item in self.manifest['files'] if item['name'] in file_names]
        return {'id': 7, 'draft': True, 'prerelease': False, 'tag_name': 'v0.2.1', 'assets': assets,
                'body': (self.directory / 'release-notes.md').read_text(encoding='utf-8')}

    def publish(self, github):
        return release.publish_bundle(self.directory, self.manifest, COMMIT, github)

    def test_manual_source_and_version_approval_must_all_match(self):
        approval = {'version': '0.2.1', 'release_approved': True,
                    'decision': 'release_with_disclosed_known_limitation'}
        release.validate_inputs('v0.2.1', COMMIT, COMMIT, '0.2.1', approval, True)
        for tag, expected, actual, version, changed in [
            ('main', COMMIT, COMMIT, '0.2.1', approval),
            ('v0.2.1', COMMIT, 'b' * 40, '0.2.1', approval),
            ('v0.2.1', COMMIT, COMMIT, '0.2.0', approval),
            ('v0.2.1', COMMIT, COMMIT, '0.2.1', {'version': '0.2.0', 'release_approved': True}),
            ('v0.2.1', COMMIT, COMMIT, '0.2.1', {'version': '0.2.1', 'release_approved': 1}),
            ('v0.2.1', COMMIT, COMMIT, '0.2.1', {**approval, 'decision': 'not approved'}),
        ]:
            with self.subTest(tag=tag, version=version, approval=changed), self.assertRaises(ValueError):
                release.validate_inputs(tag, expected, actual, version, changed, True)
        release.validate_inputs('v0.2.1', COMMIT, COMMIT, '0.2.1', {}, False)

    def test_unapproved_candidate_cannot_be_bundled_for_publication(self):
        archive = self.directory / 'neuron_flow_v0.2.1.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('neuron_flow/SHA256SUMS.txt', 'manifest')
            zipped.writestr('neuron_flow/START_COLAB.ipynb', 'notebook')
        (self.directory / 'neuron_flow_v0.2.1.zip.sha256').write_text(release.digest(archive) + '  ' + archive.name + '\n')
        release.write_json(self.directory / 'delivery_checks.json', {
            'version': '0.2.1', 'sha256': release.digest(archive),
            'fresh_local_unpack_passed': True, 'release_approved': False})
        facts = {key: value for key, value in self.manifest.items() if key not in {'files', 'notes_sha256'}}
        with self.assertRaisesRegex(ValueError, 'approved build'):
            release.bundle(self.directory, facts)

    def test_changed_downloaded_build_file_stops_before_any_github_action(self):
        github = FakeGitHub()
        (self.directory / 'START_COLAB.ipynb').write_text('changed')
        with self.assertRaises(ValueError):
            self.publish(github)
        self.assertFalse(github.created)
        self.assertEqual(github.uploaded, [])

    def test_published_release_is_immutable_to_this_workflow(self):
        existing = self.existing()
        existing['draft'] = False
        github = FakeGitHub(existing)
        with self.assertRaisesRegex(ValueError, 'already published'):
            self.publish(github)
        self.assertEqual(github.release, existing)
        self.assertEqual(github.uploaded, [])
        self.assertFalse(github.published)

    def test_conflicting_remote_file_prevents_even_missing_file_uploads(self):
        existing = self.existing(['neuron_flow_v0.2.1.zip'])
        existing['assets'][0]['digest'] = 'sha256:' + '0' * 64
        github = FakeGitHub(existing)
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.publish(github)
        self.assertEqual(github.release, existing)
        self.assertEqual(github.uploaded, [])
        self.assertFalse(github.published)

    def test_remote_tag_change_or_different_draft_notes_preserves_existing(self):
        for change in ('tag', 'notes'):
            existing = self.existing()
            github = FakeGitHub(existing)
            if change == 'tag':
                github.remote_commit = 'b' * 40
            else:
                github.release['body'] = 'different notes'
            before = deepcopy(github.release)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.publish(github)
            self.assertEqual(github.release, before)
            self.assertEqual(github.uploaded, [])

    def test_identical_draft_assets_are_reused_and_only_missing_files_uploaded(self):
        already = ['neuron_flow_v0.2.1.zip', 'SHA256SUMS.txt']
        github = FakeGitHub(self.existing(already))
        result = self.publish(github)
        self.assertFalse(result['draft'])
        self.assertTrue(github.published)
        self.assertEqual(set(github.uploaded), {item['name'] for item in self.manifest['files']} - set(already))
        self.assertEqual(len(result['assets']), 6)

    def test_failed_upload_leaves_draft_and_retry_reuses_successful_files(self):
        github = FakeGitHub()
        github.fail_name = 'START_COLAB.ipynb'
        with self.assertRaisesRegex(RuntimeError, 'Upload failed'):
            self.publish(github)
        self.assertTrue(github.created)
        self.assertTrue(github.release['draft'])
        self.assertFalse(github.published)
        before = deepcopy(github.release['assets'])
        github.fail_name = None
        github.uploaded.clear()
        result = self.publish(github)
        self.assertFalse(result['draft'])
        self.assertEqual(result['assets'][:len(before)], before)
        self.assertNotIn('neuron_flow_v0.2.1.zip', github.uploaded)

    def test_native_remote_digest_mismatch_never_uses_upload_or_publish(self):
        github = release.GitHub('owner/project')
        item = self.manifest['files'][0]
        asset = {'name': item['name'], 'state': 'uploaded', 'size': item['bytes'],
                 'digest': 'sha256:' + '0' * 64}
        with patch.object(release, 'command') as execute, self.assertRaisesRegex(ValueError, 'SHA-256'):
            github.verify_asset('v0.2.1', asset, item)
        execute.assert_not_called()

    def test_download_hash_is_checked_when_server_digest_is_absent(self):
        github = release.GitHub('owner/project')
        item = self.manifest['files'][0]
        asset = {'name': item['name'], 'state': 'uploaded', 'size': item['bytes']}
        data = (self.directory / item['name']).read_bytes()
        def download(arguments, **_kwargs):
            destination = Path(arguments[arguments.index('--dir') + 1])
            (destination / item['name']).write_bytes(data)
            return ''
        with patch.object(release, 'command', side_effect=download):
            github.verify_asset('v0.2.1', asset, item)
        item = {**item, 'sha256': hashlib.sha256(b'other contents').hexdigest()}
        with patch.object(release, 'command', side_effect=download), self.assertRaisesRegex(ValueError, 'SHA-256'):
            github.verify_asset('v0.2.1', asset, item)


if __name__ == '__main__':
    unittest.main()
