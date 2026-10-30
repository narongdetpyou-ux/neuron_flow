# Maintainer and handoff runbook

Read GOVERNANCE.md, SECURITY.md and CI_RELEASE.md. Check git status before changes, preserve existing work, and use Python 3.10+ with a virtual environment. Optional document tests need their extras/Tesseract; build/quality dependencies use their separate requirements.

## Verify and inspect

```bash
python3 -m venv .venv
. .venv/bin/activate
python -B -m neuron_flow --help
evidence_dir=$(mktemp -d)
python -B tools/verify_current.py --output-dir "$evidence_dir"
```

Use a fresh evidence directory. Inspect test_results.json, acceptance_matrix.json and logs with source commit, commands, platform and exit status. Failed/skipped/unrun are distinct from passed. Preserve historical evidence; local tests are not actual Colab or remote CI observations.

## Stop and recover

Only stop processes you started. Do not delete runtime.lock to take over a live workspace. Reopen with the original absolute path and compatible runtime/Agent identities:

```bash
python -B -m neuron_flow batch-list --workspace /absolute/original/workspace
python -B -m neuron_flow batch-status BATCH_ID --workspace /absolute/original/workspace
python -B -m neuron_flow batch-resume BATCH_ID --workspace /absolute/original/workspace
```

batch-list does not start workers; status/resume use the workspace lock. Inspect document ERROR counts, delivery status and receipts as well as exit codes. Preserve conflicts and back up before investigation; do not edit SQLite source or frozen receipts to force recovery.

## Consistent backup

Stop controllers/writers first and hold the workspace lock while copying reports. Use SQLite's backup API to incorporate WAL consistently. Include all intakes, originals, reviews, reports and package/absolute-path metadata. Keep matching custom Agent source/versions and the exact package manifest/commit. Hashes detect corruption but do not authenticate a backup's creator.

Save the following as backup_workspace.py outside the checkout. Arguments are the source workspace and a separate new backup directory:

```python
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from neuron_flow import __version__
from neuron_flow.storage import WorkspaceLock

source, backup = (Path(value).resolve() for value in sys.argv[1:3])
if (not (source / "state.sqlite3").is_file() or backup.exists()
        or source == backup or source in backup.parents or backup in source.parents):
    raise ValueError("Require existing workspace and a separate, new backup directory")
lock = WorkspaceLock(source / "runtime.lock")
try:
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Inspect symlinks before making a backup")
    shutil.copytree(source, backup / "workspace", ignore=shutil.ignore_patterns(
        "state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm", "runtime.lock", "*.tmp"))
    with closing(sqlite3.connect((source / "state.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        with closing(sqlite3.connect(backup / "workspace/state.sqlite3")) as destination:
            db.backup(destination)
            if destination.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise RuntimeError("Backup must be a standalone database without WAL files")
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup database integrity check failed")
    files = {path.relative_to(backup / "workspace").as_posix():
             hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted((backup / "workspace").rglob("*")) if path.is_file()}
    (backup / "manifest.json").write_text(json.dumps({
        "workspace": str(source), "project_version": __version__, "files": files},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Backup created:", backup)
finally:
    lock.close()
```

## Restore without overwriting

Restore requires the original absolute workspace path because receipts contain absolute artifact paths. Use compatible runtime/Agent versions and an absent destination. Inspect any existing workspace separately; the script does not remove or overwrite it.

```python
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys

backup, target = (Path(value).resolve() for value in sys.argv[1:3])
metadata = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
if str(target) != metadata["workspace"] or target.exists():
    raise ValueError("Restore requires the original absolute path, with no existing workspace")
root = backup / "workspace"
if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
    raise ValueError("Backup must not contain symlinks")
actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
if actual != set(metadata["files"]):
    raise ValueError("Backup file inventory differs from manifest")
for name, expected in metadata["files"].items():
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid backup member path")
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
        raise ValueError("Backup SHA-256 mismatch: " + name)
with closing(sqlite3.connect((root / "state.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Backup database integrity check failed")
shutil.copytree(root, target)
print("Restored to:", target, "using source package version:", metadata["project_version"])
```

## Release and handoff

Record version-specific user publication authorization, notes and exact source/tag identity. Run the locked fixture, full verifier, quality, distribution and offline release guards; inspect all results. CI_RELEASE.md describes build/publish controls and immutable asset checks. Confirm native release downloads and hashes after publication. Do not treat local candidate generation as publication, or publication as actual Colab acceptance.

Handoff requires repository access granted through GitHub, a tested recovery/backup procedure, pinned Agent/package identities and current operational contacts. Documentation alone does not grant access, establish a private channel or create a production SLA.
