# คู่มือดูแลและส่งต่องาน Neuron Flow

คู่มือนี้ช่วยให้ผู้ดูแลคนถัดไปทำงานต่อได้โดยใช้ repository และผลตรวจจริง
ไม่มีการเพิ่มผู้ดูแล สิทธิ์ GitHub ช่องทางลับ หรือการรับรอง SLA จากการเพิ่มเอกสารนี้
ดู [governance](../GOVERNANCE.md), [security](../SECURITY.md) และ
[CI/release](CI_RELEASE_TH.md) ประกอบ

## เริ่มงานและตรวจความพร้อม

ใช้ checkout เดิมของ task; cloud task แยกสภาพแวดล้อมให้อยู่แล้ว
อย่าสร้าง worktree เว้นแต่ผู้ใช้สั่ง ตรวจ `git status --short` ก่อนแก้ไฟล์
ใช้ Python 3.10+ และ virtual environment ตาม [CONTRIBUTING](../CONTRIBUTING.md)
application และ regression suite ใช้ standard library ส่วนเครื่องมือ build/quality
ใช้ requirements ที่ repository ระบุ

```bash
python3 -m venv .venv
. .venv/bin/activate
python -B -m neuron_flow --help
evidence_dir=$(mktemp -d)
python -B tools/verify_current.py --output-dir "$evidence_dir"
```

อ่าน `test_results.json`, `acceptance_matrix.json` และ logs ใน directory ของ run นี้
แยก failed/skipped/unrun ออกจาก passed เก็บ source commit, Python/platform,
คำสั่งและ exit status กับหลักฐานเสมอ ไม่เขียนทับ `verification/v0_2_0/`
ผล local ไม่ยืนยันว่า GitHub Actions หรือ Colab จริงผ่าน

## หยุดและกู้คืนงาน

หนึ่ง controller ถือ lock ต่อหนึ่ง workspace หยุดเฉพาะ process ที่ตนเป็นผู้เริ่ม
อย่าลบ `runtime.lock` เพื่อพยายามแย่ง workspace ที่กำลังใช้งาน
หลัง controller หยุดหรือเครื่องเริ่มใหม่ ใช้ path เดิมและ runtime/Agent identity ที่เข้ากันได้:

```bash
python -B -m neuron_flow batch-list --workspace /absolute/original/workspace
python -B -m neuron_flow batch-status BATCH_ID --workspace /absolute/original/workspace
python -B -m neuron_flow batch-resume BATCH_ID --workspace /absolute/original/workspace
```

`batch-list` ไม่เปิด workers; `batch-status` และ `batch-resume` ใช้ runtime lock
ตรวจ document counts, `ERROR`, delivery status และ receipt ไม่ตัดสินจาก exit 0 เพียงอย่างเดียว
หาก identity/source/report conflict ให้เก็บหลักฐานและสำรองก่อนสอบสวน
อย่าเปลี่ยนข้อมูล source หรือ frozen receipt ใน SQLite เพื่อให้ resume ผ่าน

## สำรอง workspace ที่สอดคล้องกัน

หยุด controller และคำสั่งเขียนทั้งหมดก่อนสำรอง ให้ runtime lock ป้องกันการเริ่ม controller
ระหว่าง copy รายงาน และใช้ SQLite backup API เพื่อรวมข้อมูลจาก WAL อย่างสอดคล้องกัน
อย่า copy เฉพาะ `state.sqlite3` ของฐานที่ยังเปิดใช้งาน แล้วทิ้ง WAL
สำรองรายงานทั้งหมดและ metadata ของ package/absolute path ด้วย

บันทึก Python ต่อไปนี้เป็น `backup_workspace.py` นอก checkout แล้วเรียกด้วย Python ของ
project โดยตั้ง `PYTHONPATH` ให้ import checkout ได้ arguments คือ workspace และปลายทางใหม่:

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

เก็บ package ZIP/manifest หรือ exact source commit และ custom Agent code/version ที่ตรงกัน
ในที่ปลอดภัยด้วย hash ตรวจความเสียหายได้ แต่ไม่ยืนยันผู้สร้าง backup
ต้องควบคุมสิทธิ์และตรวจแหล่งที่มาของ backup แยกต่างหาก

## คืนสำรองโดยไม่เขียนทับข้อมูลเดิม

รองรับ absolute workspace path เดิมเท่านั้น เพราะ receipts เก็บ absolute artifact paths
ใช้ runtime/Agent versions เดิมหรือความเข้ากันได้ที่ project ระบุไว้
สคริปต์ต่อไปนี้รับ backup directory และ original workspace path โดยปลายทางต้องยังไม่มีอยู่
หากมี workspace อยู่แล้ว ให้หยุดและเก็บรักษา/ย้ายไปที่ปลอดภัยด้วยการตัดสินใจของผู้ดูแลก่อน
สคริปต์ไม่ลบหรือเขียนทับ directory เดิม

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

หลังคืน backup รัน batch discovery, status และ resume ด้วย runtime เดิม
ตรวจ SHA-256 ของ artifact จาก receipt, counts, certified total และ attempts ของงานที่สำเร็จแล้ว
ทดสอบ restore ด้วยข้อมูลจำลองเป็นระยะ แทนการสมมติว่า backup ที่สร้างได้จะกู้คืนได้เสมอ
Notebook มีขั้นตอน backup/restore ของ Colab แยกใน [Colab acceptance](COLAB_ACCEPTANCE_TH.md)
ผลทดสอบ scripts นี้บน Linux ไม่ใช่หลักฐานว่าได้รับไฟล์ดาวน์โหลดหรือคืน runtime บน Colab จริง

## แก้ CI ที่ล้มเหลวและออก release

อ่าน failure แรกและ logs ของ job/commit ที่ตรงกัน ตรวจว่าเป็น regression, setup/network
หรือ platform limitation ทำซ้ำคำสั่งเดียวกันก่อนแก้ ห้ามลด assertion/แก้ golden answers
หรือทำ skipped ให้กลายเป็น passed เพื่อทำให้ CI เขียว
สำหรับ Windows/macOS ต้องเก็บผล runner จริงก่อนอ้างการรองรับ

source commit, branch push, PR merge และ candidate build ไม่อนุมัติ release
ใช้ [release workflow](CI_RELEASE_TH.md) ซึ่งตรวจ exact commit/tag/version และ approval ของรุ่นนั้น
คง `publish=false` จนมีคำสั่งอนุมัติของ maintainer ที่ตรงกับรุ่น/commit
กรณี upload ล้มให้ใช้ artifact เดิมและ re-run failed jobs ตามคู่มือ
อย่าใช้ `--clobber`, เลื่อน tag หรือสร้าง approval แทนผู้ดูแล
ตรวจ native release asset ด้วย download/SHA-256 จริง แล้วเก็บ URL/run/commit/digest เป็นหลักฐาน
Colab `not_run` ต้องคงสถานะเดิมจนผ่าน upload/run/resume/download/restore จริง

## สิทธิ์ การส่งต่อ และการเก็บข้อมูล

มีผู้ดูแลหนึ่งคนตาม governance การส่งต่อควรใช้ GitHub Settings และสิทธิ์ขั้นต่ำที่จำเป็น
เพิ่มผู้ดูแลสำรองเมื่อเจ้าของเห็นสมควร ให้ผู้รับยืนยันการเข้าถึง repository, CI และช่องทางกู้บัญชีจริง
อัปเดต CODEOWNERS/governance และทดสอบขั้นตอน release แบบไม่ publish
ไม่ส่งรหัสผ่าน PAT recovery codes หรือ secret ผ่าน issue/chat/ไฟล์ repository
เมื่อเจ้าของเข้าบัญชีไม่ได้ ให้ใช้กระบวนการกู้บัญชี GitHub ที่เป็นทางการ
ผู้มีสิทธิ์อ่านโค้ดไม่ได้รับสิทธิ์ผู้ดูแลโดยอัตโนมัติ ไม่มีช่องทางลับหรือผู้รับสำรองที่เอกสารนี้แต่งตั้งเอง

SQLite/source.csv/reports/backups อาจมีข้อมูลการเงินจริง จำกัด filesystem/cloud-storage access
กำหนดอายุเก็บข้อมูลและผู้มีสิทธิ์อนุมัติลบตามงานจริง เพราะ project ยังไม่มี automatic retention policy
ตรวจว่างานปิดแล้วและ backup/restore ผ่านก่อนลบด้วยการตัดสินใจของผู้รับผิดชอบ
ใช้เฉพาะ synthetic data ใน CI, benchmark และ public evidence
Agents เป็น trusted Python code; process isolation ไม่ใช่ sandbox และไม่รับรองธุรกรรมบริการภายนอก
