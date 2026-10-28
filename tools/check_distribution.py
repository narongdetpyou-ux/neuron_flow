"""Build wheel/sdist, then verify each in a clean environment outside the checkout."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import venv


PROJECT = Path(__file__).resolve().parents[1]


def source_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
            digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()


def write_supply_chain_records(output, report):
    """Local unsigned inventory/provenance: these are not remote attestations."""
    version = report['installs'][0]['import_probe']['version']
    sbom = {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
            'serialNumber': f'urn:uuid:{uuid.uuid4()}',
            'metadata': {'timestamp': report['created_at_utc'],
                         'component': {'type': 'application', 'name': 'neuron-flow-prototype',
                                       'version': version,
                                       'purl': f'pkg:pypi/neuron-flow-prototype@{version}',
                                       'licenses': [{'license': {'id': 'GPL-3.0-only'}}]},
                         'properties': [{'name': 'neuron-flow:runtime-dependencies', 'value': 'Python standard library only'},
                                        {'name': 'neuron-flow:python', 'value': report['python']}]},
            'components': [{'type': 'library', 'name': name, 'version': tool_version,
                            'purl': f'pkg:pypi/{name}@{tool_version}',
                            'properties': [{'name': 'neuron-flow:usage', 'value': 'build tooling, not runtime'}]}
                           for name, tool_version in report['build_tools'].items()]}
    provenance = {'record_type': 'local_unsigned_build_record', 'signed': False,
                  'remote_attestation': False, 'created_at_utc': report['created_at_utc'],
                  'source_tree_sha256': report['source_tree_sha256'],
                  'source_digest_scope': 'Sorted relative filenames, NUL, contents, NUL of copied package/metadata before build',
                  'build_lock_sha256': hashlib.sha256((PROJECT / 'requirements-build.txt').read_bytes()).hexdigest(),
                  'build_tools': report['build_tools'], 'python': report['python'],
                  'artifacts': report['artifacts'], 'installed_smoke_checks_passed': True}
    for filename, value in [('sbom.cdx.json', sbom), ('provenance.json', provenance)]:
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(command, *, cwd, env, log):
    result = subprocess.run(list(map(str, command)), cwd=cwd, env=env, text=True,
                            capture_output=True, timeout=180)
    log.append({'command': list(map(str, command)), 'cwd': str(cwd),
                'returncode': result.returncode, 'stdout': result.stdout,
                'stderr': result.stderr})
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command}\n'
                           f'{result.stdout}\n{result.stderr}')
    return result.stdout


def receipt_snapshot(result):
    """Verify actual bytes against every receipt before recording recovery state."""
    if (result.get('status') != 'DELIVERED' or result.get('certified_total') != '412.70'
            or result.get('counts') != {'documents': 2, 'VALID': 2, 'INVALID': 0, 'ERROR': 0}):
        raise RuntimeError('Installed CSV workflow did not produce the expected result')
    artifacts = result['receipt']['artifacts']
    if set(artifacts) != {'summary.csv', 'details.json', 'source.csv'}:
        raise RuntimeError('Installed CSV workflow returned incomplete artifacts')
    snapshot = {}
    for name, artifact in artifacts.items():
        path = Path(artifact['path'])
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != artifact['sha256'] or len(data) != artifact['bytes']:
            raise RuntimeError(f'Installed artifact integrity failure: {name}')
        snapshot[name] = {'sha256': digest, 'bytes': len(data), 'mtime_ns': path.stat().st_mtime_ns}
    return snapshot


def check_install(artifact, *, wheelhouse, temporary, env, log):
    label = 'wheel' if artifact.suffix == '.whl' else 'sdist'
    root = temporary / label
    root.mkdir()
    venv.EnvBuilder(with_pip=True).create(root / 'venv')
    scripts = root / 'venv' / ('Scripts' if os.name == 'nt' else 'bin')
    python = scripts / ('python.exe' if os.name == 'nt' else 'python')
    cli = scripts / ('neuron-flow.exe' if os.name == 'nt' else 'neuron-flow')
    pip = [python, '-m', 'pip', '--disable-pip-version-check']
    if label == 'sdist':
        run([*pip, 'install', '--no-index', '--find-links', wheelhouse,
             '--require-hashes', '-r', PROJECT / 'requirements-build.txt'], cwd=root, env=env, log=log)
    run([*pip, 'install', '--no-index', '--no-deps', '--no-build-isolation', artifact],
        cwd=root, env=env, log=log)
    run([*pip, 'check'], cwd=root, env=env, log=log)
    probe = json.loads(run([python, '-I', '-c',
        'import json,sys,neuron_flow; print(json.dumps({"path":neuron_flow.__file__, '
        '"prefix":sys.prefix,"version":neuron_flow.__version__}))'], cwd=root, env=env, log=log))
    if not Path(probe['path']).resolve().is_relative_to((root / 'venv').resolve()):
        raise RuntimeError('Distribution test imported the checkout instead of installed package')
    source = root / 'purchases.csv'
    shutil.copy2(PROJECT / 'examples' / 'purchases.csv', source)
    workspace = root / 'workspace'
    first = json.loads(run([cli, 'csv', source, '--batch-id', 'package-smoke',
                           '--workspace', workspace], cwd=root, env=env, log=log))
    before = receipt_snapshot(first)
    second = json.loads(run([cli, 'batch-resume', 'package-smoke', '--workspace', workspace],
                            cwd=root, env=env, log=log))
    if first != second or receipt_snapshot(second) != before:
        raise RuntimeError('Recovery changed delivered reports or their receipts')
    return {'kind': label, 'import_probe': probe, 'counts': first['counts'],
            'certified_total': first['certified_total'], 'artifact_checks': before,
            'recovery_preserved_receipts_and_files': True, 'passed': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='A new output directory outside the checkout')
    parser.add_argument('--wheelhouse', type=Path,
                        help='Pre-downloaded hashed build wheels; avoids all network access')
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.is_relative_to(PROJECT) or output.exists():
        parser.error('Choose a new output directory outside the checkout')
    output.mkdir(parents=True)
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    log = []
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'passed': False,
              'build_tools': {name: importlib.metadata.version(name)
                              for name in ('setuptools', 'build', 'wheel', 'packaging', 'pyproject-hooks')}}
    try:
        for name, version in report['build_tools'].items():
            if f'{name}=={version} ' not in (PROJECT / 'requirements-build.txt').read_text(encoding='utf-8'):
                raise RuntimeError(f'Install the pinned build tools first: unexpected {name}=={version}')
        wheelhouse = args.wheelhouse.resolve() if args.wheelhouse else output / 'wheelhouse'
        if not args.wheelhouse:
            wheelhouse.mkdir()
            run([sys.executable, '-m', 'pip', '--disable-pip-version-check', 'download',
                 '--require-hashes', '--only-binary=:all:', '-r', PROJECT / 'requirements-build.txt',
                 '--dest', wheelhouse], cwd=output, env=env, log=log)
        with tempfile.TemporaryDirectory(prefix='neuron-distribution-') as name:
            temporary = Path(name)
            source = temporary / 'source'
            source.mkdir()
            for filename in ('pyproject.toml', 'README.md', 'LICENSE'):
                shutil.copy2(PROJECT / filename, source / filename)
            shutil.copytree(PROJECT / 'neuron_flow', source / 'neuron_flow',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            report['source_tree_sha256'] = source_digest(source)
            run([sys.executable, '-m', 'build', '--no-isolation', '--outdir', output, source],
                cwd=temporary, env=env, log=log)
            artifacts = sorted([*output.glob('*.whl'), *output.glob('*.tar.gz')])
            if len(artifacts) != 2 or len(list(output.glob('*.whl'))) != 1:
                raise RuntimeError('Build must produce exactly one wheel and one sdist')
            report['artifacts'] = {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                          'bytes': p.stat().st_size} for p in artifacts}
            report['installs'] = [check_install(p, wheelhouse=wheelhouse, temporary=temporary,
                                               env=env, log=log) for p in artifacts]
            write_supply_chain_records(output, report)
            report['passed'] = True
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        (output / 'distribution_checks.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (output / 'commands.json').write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
