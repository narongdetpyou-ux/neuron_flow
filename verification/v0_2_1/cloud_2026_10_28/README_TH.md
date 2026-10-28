# บันทึกการทดสอบบน Cloud — 28 ตุลาคม 2026

หลักฐานจากการรันจริงบน Linux/Python 3.12.14 เก็บผลเดิมและเวลาที่รันไว้ครบ
วันที่ใน JSON เป็น UTC; วันที่ในรายงานนี้อ้างอิง Asia/Bangkok

| งาน | ผล |
| --- | --- |
| Dependencies | runtime ไม่มีแพ็กเกจภายนอก; ติดตั้ง setuptools 84.2.1 สำหรับ build; pip check ผ่าน |
| Regression | 38 baseline + 102 current + 10 release guards = **150 ผ่าน**; ไม่มี failure/error/skip |
| Benchmark | **20 กรณี**: 5 ฟังก์ชัน × 10, 100, 1,000, 10,000 รายการ |
| Edge cases | **1,608 กรณี**: 1,605 จัดการได้ตามคาด, **3 crash**, ไม่มี timeout |
| Mock inputs | **1,577 ไฟล์** พร้อม manifest และ SHA-256 ใน ZIP |

## ผลที่ตรวจพบ

3 crash เป็นบั๊กเดียวกัน: `events --after` รับค่าที่เกินช่วง signed int64 ของ SQLite
แล้วเกิด `OverflowError: Python int too large to convert to SQLite INTEGER`
ค่า −9223372036854775809, 9223372036854775808 และ 10^100 ทำให้ crash
ค่าขอบเขต −2^63 และ 2^63−1 ทำงานปกติ
**PR นี้บันทึกและทำซ้ำปัญหา ยังไม่ได้แก้โค้ดแอปพลิเคชัน**
ชุด edge cases จึงคืน exit code 1 ตามผลที่พบ; ไม่ได้เปลี่ยน expected result ให้ crash ผ่าน
ไฟล์ CSV เสีย, ข้อมูล INVALID และ document ERROR ตามขนาดที่จำกัดไว้
ถูกแยกจาก unexpected crash อย่างชัดเจน

ที่ 10,000 รายการ งาน CSV pipeline ในหน่วยความจำใช้เวลา median **103.90 ms/ครั้ง**,
Python allocation peak เพิ่ม **17.38 MiB**, และ process peak RSS **35.94 MiB**
เวลาเป็น median ของ sample averages 7 samples; วัด memory แยกจากเวลา
RSS รวม interpreter และ inputs; ไม่รวม Runtime/SQLite/worker IPC/report I/O ในงานจับเวลา
ผลนี้อ้างอิงเครื่องและ settings ที่บันทึกไว้ ไม่ใช่การรับประกัน performance บนเครื่องอื่น

## หลักฐาน

- [ผล benchmark และ settings/samples](benchmark/benchmark.json), [CSV](benchmark/benchmark.csv), [ตาราง](benchmark/benchmark.txt)
- [รายงาน edge cases](edge_cases/REPORT.md), [ผลทุกกรณี](edge_cases/results.json), [3 crash พร้อม traceback](edge_cases/failures.json)
- [Mock Data ZIP](edge_cases/mock-data.zip), [manifest](edge_cases/manifest.json)
- [Regression summary](regression/test_results.json), [baseline](regression/baseline/test_results.json), [release guards](regression/release_workflow_tests.log)
- [Dependency audit](dependencies/dependency-check.json), [pip check](dependencies/pip-check.log)
- [ที่มาของหลักฐานและ source hashes](provenance.json), [SHA-256 ของไฟล์หลักฐาน](ARTIFACT_SHA256SUMS.txt)

เก็บ acceptance_evidence และ sample reports ของ regression ไว้ด้วย
ไม่รวม SQLite workspaces, process/lock files, virtualenv และ caches
paths แบบ absolute ใน raw reports เป็นตำแหน่งเดิมตอนรัน ไม่ได้ย้ายหรือแก้ receipt
mock corpus อยู่ใน ZIP เพื่อไม่เพิ่มไฟล์จำลองนับพันลงในต้นไม้ Git

## ทำซ้ำจากโฟลเดอร์โปรเจกต์

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'setuptools>=61'
.venv/bin/python -B tools/benchmark.py --output-dir /tmp/neuron-benchmark-new
.venv/bin/python -B tools/edge_cases.py --output-dir /tmp/neuron-edge-cases-new
.venv/bin/python -B tools/verify_current.py --output-dir /tmp/neuron-regression-new
```

เลือก output directory ใหม่ทุกครั้ง คำสั่ง edge cases คาดว่าจะคืน 1 จนกว่าจะแก้บั๊กที่พบ
การรันบน Google Colab จริงและการเผยแพร่ release ไม่ได้เป็นส่วนหนึ่งของหลักฐานนี้

ตรวจ checksum จากโฟลเดอร์ `verification/v0_2_1/cloud_2026_10_28`:

```bash
sha256sum -c ARTIFACT_SHA256SUMS.txt
```
