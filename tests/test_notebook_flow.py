"""Execute notebook recovery cells offline; never claim actual Colab acceptance."""

import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import hashlib
import shutil
import sqlite3
import stat
import types
import unittest
import zipfile
from unittest.mock import Mock, patch

from neuron_flow import __version__


PROJECT = Path(__file__).resolve().parents[1]


def code_cell(index):
    notebook = json.loads((PROJECT / 'START_COLAB.ipynb').read_text(encoding='utf-8'))
    return ''.join(notebook['cells'][index]['source'])


class NotebookRecoveryTests(unittest.TestCase):
    def test_code_cells_compile_and_contain_no_recorded_outputs(self):
        notebook = json.loads((PROJECT / 'START_COLAB.ipynb').read_text(encoding='utf-8'))
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                ast.parse(''.join(cell['source']))
                self.assertEqual(cell.get('outputs'), [])
                self.assertIsNone(cell.get('execution_count'))

    def test_batch_id_is_saved_before_the_processing_command_can_be_interrupted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / 'session.json'
            calls = []
            def run_cli(*arguments):
                calls.append(arguments)
                if arguments[0] == 'csv':
                    self.assertIn('--submit-only', arguments)
                    return {'batch_id': 'persisted-before-run', 'created': True, 'status': 'PENDING'}
                self.assertEqual(arguments[0], 'batch-resume')
                self.assertEqual(json.loads(session.read_text())['batch_id'], 'persisted-before-run')
                raise RuntimeError('Synthetic interruption after durable submission')
            namespace = {'Path': Path, 'json': json, 'hashlib': __import__('hashlib'),
                         'files': Mock(upload=Mock(return_value={'test.csv': b'CSV test bytes'})),
                         'UPLOAD_DIRECTORY': root / 'uploads', 'WORKSPACE': root / 'workspace',
                         'SESSION_PATH': session, 'version': __version__,
                         'PACKAGE_MANIFEST_SHA': 'a' * 64, 'OBSERVATIONS': {}, 'run_cli': run_cli}
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'Synthetic interruption'):
                exec(compile(code_cell(4), '<notebook-upload>', 'exec'), namespace)
            self.assertEqual([call[0] for call in calls], ['csv', 'batch-resume'])
            self.assertTrue(namespace['OBSERVATIONS']['batch_persisted_before_execution'])
            self.assertEqual(json.loads(session.read_text())['workspace'], str(root / 'workspace'))

    def test_missing_session_is_reconstructed_from_discovery_without_source_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'state.sqlite3').touch()
            session = root / 'session.json'
            calls = []
            def run_cli(*arguments):
                calls.append(arguments)
                if arguments[0] == 'batch-list':
                    return {'batches': [{'batch_id': 'recovered', 'status': 'PENDING'}]}
                self.assertTrue(session.is_file())
                self.assertEqual(arguments[:2], ('batch-resume', 'recovered'))
                return {'status': 'DELIVERED', 'counts': {'VALID': 1}, 'receipt': {}}
            namespace = {'json': json, 'SESSION_PATH': session, 'WORKSPACE': workspace,
                         'version': __version__, 'PACKAGE_MANIFEST_SHA': 'a' * 64,
                         'OBSERVATIONS': {}, 'run_cli': run_cli}
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(code_cell(8), '<notebook-resume>', 'exec'), namespace)
            self.assertEqual([call[0] for call in calls], ['batch-list', 'batch-resume'])
            self.assertTrue(namespace['OBSERVATIONS']['batch_discovery_used'])
            self.assertTrue(namespace['OBSERVATIONS']['resume_executed'])

    def test_original_020_backup_restores_with_pinned_manifest_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root / 'backup'
            (staged / 'workspace/reports').mkdir(parents=True)
            (staged / 'verification').mkdir()
            (staged / 'verification/offline.txt').write_text('Synthetic restore fixture; not actual Colab evidence.\n')
            workspace = root / 'restored'
            with sqlite3.connect(staged / 'workspace/state.sqlite3') as connection:
                connection.execute('CREATE TABLE historical(value TEXT)')
                connection.execute("INSERT INTO historical VALUES('keep original')")
            (staged / 'workspace/reports/old.json').write_bytes(b'{"historical":true}\n')
            namespace = {'Path': Path, 'PurePosixPath': __import__('pathlib').PurePosixPath,
                         'json': json, 'hashlib': hashlib, 'zipfile': zipfile, 'io': io,
                         'stat': stat, 'shutil': shutil, 'WORKSPACE': workspace,
                         'SESSION_PATH': root / 'session.json', 'version': __version__,
                         'PACKAGE_MANIFEST_SHA': 'b' * 64, 'OBSERVATIONS': {},
                         'tempfile': types.SimpleNamespace(mkdtemp=lambda **kw: tempfile.mkdtemp(
                             prefix=kw['prefix'], dir=root))}
            setup = ast.parse(code_cell(2))
            for node in setup.body:
                if isinstance(node, ast.FunctionDef) and node.name in {'safe_unpack', 'verify_sums'}:
                    exec(compile(ast.Module(body=[node], type_ignores=[]), '<notebook-helper>', 'exec'), namespace)
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LEGACY_020_MANIFEST_SHA' for t in node.targets):
                    namespace['LEGACY_020_MANIFEST_SHA'] = ast.literal_eval(node.value)
            (staged / 'session.json').write_text(json.dumps({'batch_id': 'old',
                'workspace': str(workspace), 'project_version': '0.2.0',
                'package_manifest_sha256': namespace['LEGACY_020_MANIFEST_SHA']}))
            originals = {p.relative_to(staged).as_posix(): p.read_bytes() for p in staged.rglob('*') if p.is_file()}
            (staged / 'backup_SHA256SUMS.txt').write_text(''.join(
                hashlib.sha256(data).hexdigest() + '  ' + name + '\n' for name, data in sorted(originals.items())))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                for path in staged.rglob('*'):
                    if path.is_file():
                        archive.write(path, path.relative_to(staged).as_posix())
            namespace['files'] = Mock(upload=Mock(return_value={'backup.zip': buffer.getvalue()}))
            namespace['PROJECT'] = root / 'project'
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(code_cell(14), '<notebook-restore>', 'exec'), namespace)
            for name, data in originals.items():
                if name.startswith('workspace/'):
                    self.assertEqual((workspace / name.removeprefix('workspace/')).read_bytes(), data)
            session = json.loads(namespace['SESSION_PATH'].read_text())
            self.assertEqual(session['restored_from_version'], '0.2.0')
            self.assertEqual(session['project_version'], __version__)
            with self.assertRaisesRegex(RuntimeError, 'workspace'):
                exec(compile(code_cell(14), '<notebook-restore-again>', 'exec'), namespace)
