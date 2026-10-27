"""Build the approved 0.2.0 release ZIP locally; external publishing is separate."""

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {'.git', '__pycache__', '.venv', 'dist', 'build', 'neuron_workspace', 'batch_workspace', '_sample_workspaces'}


def selected_files():
    files = []
    for path in sorted(PROJECT.rglob('*')):
        relative = path.relative_to(PROJECT)
        if not path.is_file() or path.is_symlink() or set(relative.parts) & EXCLUDED_PARTS:
            continue
        if (path.suffix in {'.pyc', '.sqlite3', '.lock', '.pid', '.tmp'}
                or path.name.endswith(('.sqlite3-wal', '.sqlite3-shm'))
                or path.name in {'SHA256SUMS.txt', 'delivery_checks.json'}):
            continue
        files.append(path)
    return files


def verify_manifest(root):
    files = (root / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
    for line in files:
        digest, name = line.split('  ', 1)
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Delivery checksum mismatch: {name}')
    return len(files)


def main():
    results = json.loads((PROJECT / 'verification/v0_2_0/test_results.json').read_text())
    if not results['local_successful'] or results['version'] != '0.2.0':
        raise RuntimeError('Run python tools/verify_v020.py successfully before building the release')
    approval = json.loads((PROJECT / 'RELEASE_APPROVAL.json').read_text(encoding='utf-8'))
    if (approval.get('release_approved') is not True or approval.get('version') != '0.2.0'
            or approval.get('decision') != 'release_with_disclosed_known_limitation'
            or not results.get('release_ready')):
        raise RuntimeError('A matching explicit release approval and passing local verification are required')
    notebook = json.loads((PROJECT / 'START_COLAB.ipynb').read_text(encoding='utf-8'))
    cells = [cell for cell in notebook['cells'] if cell['cell_type'] == 'code']
    for cell in cells:
        ast.parse(''.join(cell['source']))
    status = {'version': '0.2.0', 'release_status': 'release_approved_with_known_limitation',
              'release_approval': 'RELEASE_APPROVAL.json',
              'colab_acceptance_complete': False, 'all_acceptance_complete': False,
              'local_verification': 'passed', 'actual_colab_acceptance': 'not_run',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'notebook_code_cells_compile': len(cells),
              'remaining': 'Fresh Colab upload, execute, resume and download with recorded evidence'}
    (PROJECT / 'BUILD_STATUS.json').write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n')
    paths = selected_files()
    manifest = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(PROJECT).as_posix() + '\n'
                       for path in paths)
    (PROJECT / 'SHA256SUMS.txt').write_text(manifest, encoding='utf-8')
    paths.append(PROJECT / 'SHA256SUMS.txt')
    destination = PROJECT / 'dist'
    destination.mkdir(exist_ok=True)
    archive_path = destination / 'neuron_flow_v0.2.0.zip'
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, 'neuron_flow/' + path.relative_to(PROJECT).as_posix())
    # Check a genuinely fresh unpack, including the CLI, golden fixture lock and
    # normal/mixed CSV flows. These are local checks, never Colab evidence.
    with tempfile.TemporaryDirectory(prefix='neuron-release-unpack-') as temporary:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temporary)
        root = Path(temporary) / 'neuron_flow'
        files_checked = verify_manifest(root)
        commands = [
            [sys.executable, 'tools/build_acceptance_fixture.py', '--check'],
            [sys.executable, '-m', 'neuron_flow', 'csv', 'examples/purchases.csv', '--batch-id', 'fresh-normal'],
            [sys.executable, '-m', 'neuron_flow', 'csv', 'examples/purchases_invalid.csv', '--batch-id', 'fresh-mixed'],
            [sys.executable, '-m', 'neuron_flow', 'batch-resume', 'fresh-normal'],
            [sys.executable, 'tools/verify_v020.py'],
        ]
        observations = []
        for command in commands:
            run = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=300)
            observations.append({'command': command, 'exit_code': run.returncode})
            if run.returncode:
                raise RuntimeError(run.stderr or run.stdout)
        normal = json.loads(subprocess.check_output(
            [sys.executable, '-m', 'neuron_flow', 'batch-status', 'fresh-normal'], cwd=root, text=True))
        if normal['counts'] != {'documents': 2, 'VALID': 2, 'INVALID': 0, 'ERROR': 0}:
            raise RuntimeError('Fresh unpack CSV results are incorrect')
    report = {**status, 'archive': str(archive_path), 'sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
              'bytes': archive_path.stat().st_size, 'manifest_files_verified': files_checked,
              'fresh_local_unpack_passed': True, 'commands': observations}
    (PROJECT / 'verification/v0_2_0/delivery_checks.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'neuron_flow_v0.2.0.zip.sha256').write_text(
        report['sha256'] + '  ' + archive_path.name + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
