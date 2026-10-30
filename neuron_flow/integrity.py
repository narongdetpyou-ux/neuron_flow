"""Streaming manifest diagnostics and non-destructive, quiescent workspace backups."""

from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile

from .storage import WorkspaceLock


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def inventory(root, excluded=()):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Integrity root must be an existing regular directory")
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError("Symlink in integrity tree")
        name = path.relative_to(root).as_posix()
        if path.is_file() and name not in excluded:
            result[name] = digest(path)
        elif not path.is_file() and not path.is_dir():
            raise ValueError('Unsupported file type in integrity tree')
    return result


def write_manifest(root, name='backup_SHA256SUMS.txt'):
    if name not in {'backup_SHA256SUMS.txt', 'SHA256SUMS.txt'}:
        raise ValueError("Unsupported manifest name")
    files = inventory(root, {name})
    if not files:
        raise ValueError("Cannot manifest an empty tree")
    with (Path(root) / name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(''.join(f'{sha}  {path}\n' for path, sha in files.items()))
    return files


def verify_manifest(root, name='backup_SHA256SUMS.txt'):
    root = Path(root)
    if name not in {'backup_SHA256SUMS.txt', 'SHA256SUMS.txt'}:
        raise ValueError("Unsupported manifest name")
    manifest = root / name
    if manifest.is_symlink() or manifest.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Unsafe manifest")
    expected = {}
    for line in manifest.read_text(encoding='utf-8').splitlines():
        sha, sep, path = line.partition('  ')
        relative = PurePosixPath(path)
        if (not sep or not re.fullmatch('[a-f0-9]{64}', sha) or not relative.parts
                or relative.is_absolute() or '..' in relative.parts or '\\' in path
                or any(':' in part for part in relative.parts) or str(relative) != path
                or path in expected or path == name):
            raise ValueError("Unsafe or duplicate manifest path")
        expected[path] = sha
    if not expected:
        raise ValueError("Empty manifest")
    actual = inventory(root, {name})
    return {'ok': expected == actual, 'checked_files': len(expected),
            'missing': sorted(expected.keys() - actual.keys()), 'extra': sorted(actual.keys() - expected.keys()),
            'changed': sorted(p for p in expected.keys() & actual.keys() if expected[p] != actual[p]),
            'scope': 'Byte integrity against supplied manifest; no authorship authentication'}


def stage_backup(workspace, destination, *, session=None, verification=None):
    if Path(workspace).is_symlink():
        raise ValueError('Workspace must not be a symlink')
    source, destination = Path(workspace).resolve(), Path(destination).resolve()
    if destination.exists() or source == destination or source in destination.parents:
        raise ValueError("Choose a new backup directory outside the workspace")
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Workspace is missing or unsafe")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for name in ('runtime.lock', 'operations-worker.lock', 'operations-admission.lock'):
            lock = WorkspaceLock(source / name)
            locks.callback(lock.close)
        databases = [p for p in source.rglob('*.sqlite3')]
        excluded = {p.relative_to(source).as_posix() + suffix for p in databases for suffix in ('', '-wal', '-shm')}
        excluded |= {p.relative_to(source).as_posix() for p in source.rglob('*.lock')}
        before = inventory(source, excluded)
        temporary = Path(tempfile.mkdtemp(prefix='.backup-', dir=destination.parent))
        try:
            target = temporary / 'workspace'
            target.mkdir()
            for name in before:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, path)
            for database in databases:
                path = target / database.relative_to(source)
                path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as original:
                    with closing(sqlite3.connect(path)) as backup:
                        original.backup(backup)
            if inventory(source, excluded) != before:
                raise ValueError("Workspace files changed during backup; stop manual intake/review and retry")
            (temporary / 'backup_metadata.json').write_text(json.dumps({
                'schema': 'workspace-backup-v1', 'original_workspace': str(source),
                'database_snapshot': 'SQLite online backup under runtime/operations locks'}), encoding='utf-8')
            if session is not None:
                shutil.copy2(session, temporary / 'session.json')
            if verification is not None:
                inventory(verification)
                shutil.copytree(verification, temporary / 'verification')
            write_manifest(temporary)
            if not verify_manifest(temporary)['ok']:
                raise ValueError("Backup read-back failed")
            temporary.rename(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {'backup_directory': str(destination), **verify_manifest(destination)}


def restore_backup(backup, workspace):
    backup, workspace = Path(backup), Path(workspace)
    checked = verify_manifest(backup)
    if not checked['ok']:
        raise ValueError("Backup integrity failed: " + json.dumps(checked))
    metadata = json.loads((backup / 'backup_metadata.json').read_text())
    if metadata.get('schema') != 'workspace-backup-v1' or metadata['original_workspace'] != str(workspace.resolve()):
        raise ValueError("Restore requires the original absolute workspace path")
    if workspace.exists():
        raise ValueError("Refusing to overwrite an existing workspace")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.restore-', dir=workspace.parent))
    try:
        shutil.copytree(backup / 'workspace', temporary / 'workspace')
        (temporary / 'workspace').rename(workspace)
    finally:
        shutil.rmtree(temporary)
    return {'workspace': str(workspace.resolve()), 'restored': True, 'checked_files': checked['checked_files']}
