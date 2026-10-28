"""Build and verify a local candidate or approved release; never publish it."""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from neuron_flow import __version__
from tools.verify_current import project_fingerprint
from tools.verify_v020 import release_approval

TOP_LEVEL = {'.gitignore', 'LICENSE', 'README.md', 'README_TH.md', 'RELEASE_APPROVAL.json',
             'RELEASE_NOTES.md', 'START_COLAB.ipynb', 'pyproject.toml'}
DIRECTORIES = {'neuron_flow', 'tools', 'tests', 'examples', 'docs', 'acceptance', '.github', 'verification'}
EXCLUDED = {'__pycache__', '_sample_workspaces', '.venv', '.git', 'dist', 'build'}


def selected_files(root):
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if (not path.is_file() or set(relative.parts) & EXCLUDED
                or not (relative.as_posix() in TOP_LEVEL or relative.parts[0] in DIRECTORIES)
                or path.suffix in {'.pyc', '.sqlite3', '.pid', '.lock', '.tmp'}
                or path.name.endswith(('.sqlite3-wal', '.sqlite3-shm'))):
            continue
        if path.is_symlink():
            raise RuntimeError(f'Cannot package a symlink: {relative}')
        yield path


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def verify_manifest(root):
    names = set()
    for line in (root / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or name in names:
            raise RuntimeError('Invalid delivery manifest path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Delivery checksum mismatch: {name}')
        names.add(name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p.relative_to(root).as_posix() != 'SHA256SUMS.txt'}
    if actual != names:
        raise RuntimeError('Manifest does not cover exactly the delivered files')
    return len(names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', action='store_true', help='Build unapproved development files locally')
    parser.add_argument('--output-dir', type=Path, default=PROJECT / 'dist')
    parser.add_argument('--verification-dir', type=Path,
                        default=PROJECT / 'verification' / ('v' + __version__.replace('.', '_')))
    args = parser.parse_args(argv)
    approved = release_approval(__version__)
    if not args.candidate and not approved:
        parser.error(f'No publication approval for {__version__}; use --candidate for local development')
    result_path = args.verification_dir.resolve() / 'test_results.json'
    if result_path.is_file():
        results = json.loads(result_path.read_text(encoding='utf-8'))
    else:
        results = {}
    if (results.get('version') != __version__ or not results.get('local_successful')
            or results.get('source_fingerprint') != project_fingerprint(PROJECT)):
        checked = subprocess.run([sys.executable, '-B', str(PROJECT / 'tools/verify_current.py'),
                                  '--output-dir', str(args.verification_dir.resolve())],
                                 cwd=PROJECT, text=True, capture_output=True, timeout=300)
        if checked.returncode:
            raise RuntimeError(checked.stdout + checked.stderr)
        results = json.loads(result_path.read_text(encoding='utf-8'))
    if not args.candidate and not results.get('release_ready'):
        raise RuntimeError('Local verification and publication approval are both required')
    notebook = json.loads((PROJECT / 'START_COLAB.ipynb').read_text(encoding='utf-8'))
    code_cells = [cell for cell in notebook['cells'] if cell['cell_type'] == 'code']
    for cell in code_cells:
        ast.parse(''.join(cell['source']))
    destination = args.output_dir.resolve()
    if destination == PROJECT:
        parser.error('Output directory must not be the project root')
    if destination.is_relative_to(PROJECT) and destination.relative_to(PROJECT).parts[0] in DIRECTORIES:
        parser.error('Output directory must be outside source/evidence folders (for example dist/)')
    destination.mkdir(parents=True, exist_ok=True)
    status = {'version': __version__, 'release_status': 'approved_unpublished' if approved else 'candidate_unpublished',
              'release_approved': approved, 'published': False, 'local_verification': 'passed',
              'colab_acceptance_complete': results['colab_acceptance_complete'],
              'all_acceptance_complete': results['all_acceptance_complete'],
              'actual_colab_acceptance': results['colab_evidence']['status'],
              'source_fingerprint': results['source_fingerprint'],
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'notebook_code_cells_compile': len(code_cells), 'remaining_acceptance': results['remaining_acceptance']}
    with tempfile.TemporaryDirectory(prefix='neuron-candidate-build-') as temporary:
        staged = Path(temporary) / 'neuron_flow'
        staged.mkdir()
        for path in selected_files(PROJECT):
            relative = path.relative_to(PROJECT)
            # Current evidence below is copied from the exact verified run.
            if relative.parts[:2] == ('verification', 'v' + __version__.replace('.', '_')):
                continue
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        verified = staged / 'verification' / ('v' + __version__.replace('.', '_'))
        for path in args.verification_dir.resolve().rglob('*'):
            relative = path.relative_to(args.verification_dir.resolve())
            if not path.is_file() or '_sample_workspaces' in relative.parts or path.name == 'delivery_checks.json':
                continue
            target = verified / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        write_json(staged / 'BUILD_STATUS.json', status)
        paths = sorted(path for path in staged.rglob('*') if path.is_file())
        manifest = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(staged).as_posix() + '\n'
                           for path in paths)
        (staged / 'SHA256SUMS.txt').write_text(manifest, encoding='utf-8')
        archive_path = destination / f'neuron_flow_v{__version__}.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staged.rglob('*')):
                if path.is_file():
                    archive.write(path, 'neuron_flow/' + path.relative_to(staged).as_posix())
        fresh_parent = Path(temporary) / 'fresh'
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(fresh_parent)
        fresh = fresh_parent / 'neuron_flow'
        files_checked = verify_manifest(fresh)
        checked = subprocess.run([sys.executable, '-B', 'tools/verify_current.py',
                                  '--output-dir', str(Path(temporary) / 'fresh-verification')],
                                 cwd=fresh, text=True, capture_output=True, timeout=300)
        if checked.returncode:
            raise RuntimeError('Fresh archive verification failed:\n' + checked.stdout + checked.stderr)
        for name in ('SHA256SUMS.txt', 'START_COLAB.ipynb', 'BUILD_STATUS.json'):
            shutil.copyfile(staged / name, destination / name)
        report = {**status, 'archive': str(archive_path), 'sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                  'bytes': archive_path.stat().st_size, 'manifest_files_verified': files_checked,
                  'fresh_local_unpack_passed': True, 'fresh_suite_passed': True}
        write_json(destination / 'delivery_checks.json', report)
        (destination / (archive_path.name + '.sha256')).write_text(
            report['sha256'] + '  ' + archive_path.name + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
