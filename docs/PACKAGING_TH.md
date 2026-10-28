# สร้างและทดสอบ Python distributions

ชื่อ distribution คงเป็น `neuron-flow-prototype` เพื่อรักษาวิธีติดตั้งเดิม
ชื่อ import คือ `neuron_flow` และคำสั่งที่ติดตั้งคือ `neuron-flow`
รุ่น 0.2.1 ยังคงเป็น candidate; การ build หรือ push โค้ดไม่ใช่การอนุมัติ release
และไม่เผยแพร่ไป PyPI

## Build tools และความปลอดภัย

`pyproject.toml` กำหนด `setuptools>=84.1.0` ส่วน
[`requirements-build.txt`](../requirements-build.txt) pin เวอร์ชันและ SHA-256 ของ build tools
แยกจาก runtime ซึ่งไม่มี third-party dependencies

ตรวจ [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w)
โดยตรงเมื่อ 28 ตุลาคม 2026: affected `>=38.2.2,<84.1.0`, patched `84.1.0`
advisory นี้เกี่ยวกับ legacy wheel installation บน Windows;
ไม่ได้หมายความว่าทุกการรันโปรเจกต์บน Linux ถูก exploit
ล็อกปัจจุบันใช้ setuptools 84.2.1 และตรวจ Python requirement จาก PyPI แล้ว (`>=3.10`)
ให้ทบทวน advisory และเปลี่ยน lock พร้อม hashes เมื่ออัปเดต tooling
ไม่แก้ hash หรือปิด TLS เพื่อข้าม verification failure

## ตรวจใน clean environments

จาก repository root ใช้ Python 3.10+:

```bash
python -m venv .venv-build
. .venv-build/bin/activate
python -m pip install --require-hashes -r requirements-build.txt
python -B tools/check_distribution.py --output-dir /tmp/neuron-distribution-check
```

บน Windows ใช้ `.venv-build\Scripts\Activate.ps1` และเลือก output directory
ใหม่ใน temp directory ของเครื่องนั้น คำสั่งต้องใช้ directory ใหม่ทุกครั้งเพื่อแยกผลแต่ละ run

ตัวตรวจ copy เฉพาะ package/metadata ไป temp directory ก่อน build จึงไม่สร้าง
egg-info หรือ build outputs ทับ source checkout; สร้าง sdist แล้วสร้าง wheel จาก sdist
ด้วย `build --no-isolation` โดยตรวจว่าตรงกับ build-tool lock ก่อนเริ่ม
จากนั้นแยก clean venv สำหรับแต่ละ artifact:

- ติดตั้ง wheel โดยไม่ใช้ network หรือ runtime dependencies
- ติดตั้ง sdist โดยโหลด build backend ที่ล็อกจาก wheelhouse และใช้ `--no-build-isolation`
- ตรวจ import path ว่าอยู่ภายใน venv พร้อม `pip check`
- เรียก console script จาก directory นอก checkout เพื่อประมวลผล CSV จริง:
  2 VALID documents, 412.70 THB และตรวจ bytes/size/SHA-256 ของ artifacts ทั้งสาม
- resume batch แล้วตรวจว่า receipt และไฟล์เดิมรวมถึงเวลาแก้ไขไม่เปลี่ยน

ผลและเวอร์ชัน build tools อยู่ใน `distribution_checks.json`; คำสั่งและ exit status จริง
อยู่ใน `commands.json` และ artifacts มี SHA-256 ในรายงาน
`sbom.cdx.json` เป็น CycloneDX 1.5 inventory ระบุ Python standard library และ build tools
ส่วน `provenance.json` ผูก digest ของ source package/metadata ที่ copy ก่อน build,
build lock, tool versions และ artifact hashes เป็น **local unsigned record**
ไม่ใช่ signed provenance, GitHub attestation หรือหลักฐานว่าเผยแพร่ release แล้ว
นี่เป็น functional packaging check ไม่แทน regression suite หรือ actual Colab acceptance

## ใช้งานแบบ offline หลังเตรียม wheelhouse

```bash
python -m pip download --require-hashes --only-binary=:all: -r requirements-build.txt --dest /tmp/neuron-build-wheels
python -B tools/check_distribution.py --wheelhouse /tmp/neuron-build-wheels --output-dir /tmp/neuron-offline-check
```

การระบุ `--wheelhouse` ทำให้ helper ไม่ดาวน์โหลด package เพิ่ม
wheelhouse ต้องเตรียมด้วย Python/OS ที่จะตรวจเพื่อให้ conditional dependencies ตรงกัน
การติดตั้ง build tools เข้าสภาพแวดล้อมที่เรียก helper ต้องเสร็จก่อน
ทั้งแบบ online และ offline รักษา package hash และ TLS verification
