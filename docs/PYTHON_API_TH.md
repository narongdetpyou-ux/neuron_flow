# Python API สำหรับการต่อยอด

API ที่ export จาก `neuron_flow` รุ่น 0.2.1 คือ `Runtime`, `AgentDefinition`,
`SpecError`, `PermanentAgentError` และ `TransientAgentError` ยังเป็น API ของ development
candidate ไม่มีคำมั่นว่า Python signatures หรือ internal attributes จะคงเดิมข้ามรุ่น
ผู้ต่อยอดควร pin รุ่น/commit และรัน integration tests ของตนก่อนอัปเกรด
CLI/CSV contract และกติกาความเข้ากันได้ของ workspace อธิบายใน [README](../README.md)
ไม่ควรอนุมานว่า workspace ทุกเวอร์ชันใช้แทนกันได้จากเลขรุ่น patch เพียงอย่างเดียว

## Runtime และ AgentDefinition

`Runtime(workspace, *, max_workers=3, agents=None)` เป็น context manager ที่ถือ lock
ของ workspace จน `close()` หรือออกจาก `with` โดย `max_workers` อยู่ในช่วง 1–32
ถ้าไม่ส่ง `agents` จะใช้ invoice Agents ที่มากับ package
การส่งรายชื่อ Agents ของตนเป็นการแทน registry ทั้งชุด ไม่ใช่เพิ่มเข้า default registry

- `submit(spec)` ตรวจและเก็บ workflow โดยยังไม่รัน Agent คืน `job_id` และ `created`
- `run(job_id)` รันหรือกู้คืนงานที่เก็บแล้ว คืน snapshot ซึ่งต้องตรวจ `status`, `steps`
  และ `receipt` เอง การคืนค่าจากฟังก์ชันไม่แปลว่างานสำเร็จเสมอ
- `status(job_id)` อ่านสถานะผ่าน runtime ที่ถือ lock; ไม่ใช่ read-only discovery แบบ
  CLI `batch-list`
- `ingest(raw_input, job_id=None)` เลือก workflow ของ invoice contract เดิม
  ไม่ใช่ generic plugin discovery

`AgentDefinition(name, entrypoint, validator, version="1")` เป็น frozen dataclass
โดย `entrypoint` คือ `module:function` ของฟังก์ชัน import ได้ใน worker ที่ใช้ `spawn`
ส่วน `validator(message, output)` รันใน controller ต้องตรวจโดยไม่แก้ `output`
คืน `None`/`True` หรือ raise exception เมื่อผลไม่ผ่าน
เพิ่ม `version` เมื่อ behavior/contract เปลี่ยน และใช้ job ID ใหม่เมื่อ identity เปลี่ยน

Agent ได้รับ JSON message ซึ่งมี `work_id`, `job_id`, `step_id`, `attempt`, `input`,
`params` และ `dependencies` (ผลจาก dependency steps ที่ประกาศไว้)
Agent และผลลัพธ์ต้องเป็น finite JSON และอยู่ภายใต้ engine message limit 1 MiB
`TransientAgentError` ขอ retry แบบจำกัด; error อื่นเป็น failure ที่ไม่ retry ด้วย input เดิม
อย่ารวม independent monetary verifier เข้ากับ calculator เพียงเพื่อใช้ helper ร่วมกัน

## ตัวอย่าง custom Agent ที่รันได้

สร้างสองไฟล์ต่อไปนี้ใน directory เดียวกัน เช่น `/tmp/neuron-api-example`
ไฟล์ Agent ต้อง import ได้ ไม่ใช้ lambda/local function หรือใส่ Agent ไว้เฉพาะใน Notebook cell

`sample_agent.py`:

```python
from neuron_flow import PermanentAgentError


def normalize_name(message):
    value = message["input"].get("name")
    if not isinstance(value, str) or not value.strip():
        raise PermanentAgentError("name must be nonempty text")
    return {"normalized": value.strip().upper()}


def validate_name(message, output):
    value = message["input"].get("name")
    if not isinstance(value, str) or output != {"normalized": value.strip().upper()}:
        raise ValueError("Name normalization result does not match input")
```

`run_example.py`:

```python
import hashlib
from pathlib import Path
import sys

from neuron_flow import AgentDefinition, Runtime
from sample_agent import validate_name


def main():
    workspace = Path(sys.argv[1]).resolve()
    agents = [AgentDefinition("name", "sample_agent:normalize_name", validate_name, "1")]
    spec = {"job_id": "name_demo", "input": {"name": "  Ada  "},
            "steps": [{"id": "normalize", "agent": "name"}]}
    with Runtime(workspace, max_workers=1, agents=agents) as runtime:
        runtime.submit(spec)
        first = runtime.run("name_demo")
        assert first["status"] == "SUCCEEDED", first
        assert first["steps"]["normalize"]["output"] == {"normalized": "ADA"}
        artifact = Path(first["receipt"]["path"])
        original = artifact.read_bytes()
        modified = artifact.stat().st_mtime_ns
        assert hashlib.sha256(original).hexdigest() == first["receipt"]["sha256"]
    # Reopen with the same Agent identity and absolute workspace path.
    with Runtime(workspace, max_workers=1, agents=agents) as runtime:
        assert runtime.submit(spec)["created"] is False
        second = runtime.run("name_demo")
        assert second["status"] == "SUCCEEDED", second
        assert second["steps"]["normalize"]["attempts"] == 1
        assert artifact.read_bytes() == original
        assert artifact.stat().st_mtime_ns == modified
    print("custom Agent and idempotent recovery: passed")


if __name__ == "__main__":
    main()
```

จาก root ของ checkout ที่เตรียม `.venv` แล้ว รันด้วย path ของตัวอย่างที่สร้างไว้:

```bash
PYTHONPATH="$PWD:/tmp/neuron-api-example" .venv/bin/python -B \
  /tmp/neuron-api-example/run_example.py /tmp/neuron-api-example/workspace
```

`if __name__ == "__main__"` จำเป็นเพื่อไม่ให้ worker ที่ import main เริ่ม runtime ซ้ำ
ทดสอบตัวอย่างนี้บน Linux/Python 3.12.14 โดยรันงานจริง ตรวจ report SHA-256 และเปิด workspace
ใหม่เพื่อยืนยันว่าสำเร็จโดยไม่เพิ่ม attempts หรือเขียน artifact ซ้ำ
นี่ไม่ใช่หลักฐาน Windows/macOS หรือ Google Colab acceptance

## ขอบเขตความเชื่อถือ

Agents และ validators เป็น Python code ที่เชื่อถือได้ มีสิทธิ์ของ process ผู้รัน
worker timeout/process isolation ไม่ใช่ security sandbox และไม่รับประกัน exactly-once
สำหรับการเรียกบริการภายนอก หาก Agent ทำ side effect ภายนอก ต้องออกแบบ idempotency
และ reconciliation เอง อย่านำข้อมูลลับหรือไฟล์การเงินจริงใส่ตัวอย่าง/CI evidence
