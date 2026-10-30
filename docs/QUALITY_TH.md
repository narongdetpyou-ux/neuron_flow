# ตรวจคุณภาพโค้ดและวัด coverage

ติดตั้งเครื่องมือสำหรับพัฒนาแยกจาก runtime ซึ่งยังใช้ standard library เท่านั้น:

```bash
python -m pip install -r requirements-dev.txt '.[documents]'
python -B tools/check_quality.py --output-dir /tmp/neuron-quality-new
```

เลือก directory ใหม่ที่อยู่นอก checkout เพื่อแยกผลรอบนี้ออกจากหลักฐานเก่า
helper คืน exit code 1 หาก lint, typing, tests, การรวม coverage หรือเกณฑ์ coverage ไม่ผ่าน
ส่วนรับเอกสารใหม่ต้องติดตั้ง Tesseract และ language data เพื่อทดสอบ OCR จริง
ดู [คู่มือ adapters](INTEGRATIONS_TH.md); core-only tests จะ skip optional formats อย่างชัดเจน
เก็บ logs, `quality_results.json`, `coverage.json` และ `coverage.xml` ใน directory ที่ระบุ
ไม่มีการลด assertions หรือข้าม tests เพื่อให้เกณฑ์ผ่าน

## ขอบเขตของ gate

- Ruff `E9,F` ตรวจ syntax/undefined names/unused imports และข้อผิดพลาดพื้นฐานทั้ง `neuron_flow/`
  ยังไม่บังคับรูปแบบการเขียนทั้งหมด
- mypy `--strict` เริ่มที่ `neuron_flow/inspection.py`: ระบุชนิด path, shape ของผล discovery
  และตัวนับสถานะ เอกสารจาก workspace รุ่นก่อนยังมี metadata ที่อ่านเป็น `object`
  เพราะ discovery ตั้งใจเปิดให้อ่าน workspace ที่ runtime ปัจจุบันยังไม่รับประมวลผล
  imported modules ยังไม่อยู่ใน type gate และไม่ถือว่า package ทั้งหมด strict-typed
- coverage รัน `unittest discover -s tests -t . -v` จริงทั้งชุด พร้อมวัด branch
  ของทุกโมดูลใน `neuron_flow/` ไม่มี module exclusion เพิ่มเพื่อดันตัวเลข

## วัด process ลูกอย่างไร

`.coveragerc` เปิด `concurrency=multiprocessing`, `patch=subprocess,_exit` และ `sigterm=True`
เพื่อเก็บทั้ง CLI subprocess, worker แบบ spawn และ worker ที่ runtime หยุดด้วย SIGTERM
จากนั้นรวม data files ก่อนออก JSON/XML การเปิดเพียง subprocess tracing จะไม่พอ
เพราะ runtime ตั้งใจ terminate worker แทนรอ graceful stop เมื่อ task อาจค้าง
helper จึงตรวจว่าคำสั่งแรกใน `_worker_main` ถูก execute จริง โดยหาเลขบรรทัดผ่าน AST
หาก instrument เฉพาะ controller จะไม่ผ่าน gate แม้เปอร์เซ็นต์รวมสูง

การวัดนี้เพิ่ม overhead และไม่ใช่ benchmark SIGKILL และการล้มแบบไม่อาจ flush ข้อมูล
ยังทำให้ข้อมูลบางเส้นทางหายได้ และ Windows ไม่สามารถเก็บข้อมูลจาก TerminateProcess
แบบเดียวกับ POSIX SIGTERM ได้ จึงใช้ Linux สำหรับ coverage gate และตรวจการทำงาน
ข้ามแพลตฟอร์มด้วย regression suite แยกต่างหาก

## Baseline และเกณฑ์เริ่มต้น

วัดบน Linux/Python 3.12.14 เมื่อ 28 ตุลาคม 2026 ด้วย coverage 7.16.2
ได้ 1,389/1,511 statements (**91.93%**) และ 494/590 branches (**83.73%**)
ค่า combined line+branch ที่ `coverage report` แสดงคือ **89.62%**
รอบตั้ง baseline นี้รัน 150 tests ผ่าน ไม่มี failure/error/skipped
จำนวน tests อาจเพิ่มหลังรวมงานอื่น ให้ใช้ `quality_results.json` ของรอบปัจจุบัน
แทนการถือจำนวนในเอกสารนี้เป็นเงื่อนไขความครบถ้วน

| Scope | Line baseline | Branch baseline | Line floor | Branch floor |
| --- | ---: | ---: | ---: | ---: |
| รวม package | 91.93% | 83.73% | 91% | 83% |
| `csv_agents.py` | 97.30% | 93.02% | 97% | 93% |
| `reporting.py` | 89.20% | 80.91% | 89% | 80% |
| `engine.py` | 91.15% | 79.25% | 90% | 78% |

ตั้ง floor จากผลที่วัดจริงโดยปัดลงเล็กน้อย แยก financial validation, artifact delivery
และ orchestration เพื่อไม่ให้ module ที่ coverage สูงบดบัง regression อีกส่วน
`.coveragerc` ยังตั้ง combined floor 89% ส่วน helper บังคับ line/branch แยกตามตาราง
ห้ามลด floor เพียงเพื่อให้ code change ผ่าน ให้เพิ่ม tests ที่พิสูจน์พฤติกรรมก่อน
แล้วทบทวน baseline เมื่อ contract หรือขอบเขตการวัดเปลี่ยนอย่างมีเหตุผล

โมดูลเก่า `agents.py` ยังมี branch coverage เพียง 62.50% ใน baseline นี้
coverage ไม่ได้พิสูจน์ความถูกต้องของทุก state combination หรือยืนยัน production readiness
ใช้รายชื่อ missing lines/branches ใน `coverage.json`/`coverage.log` เพื่อเลือก failure path
ที่ยังต้องทดสอบ โดยรักษา independent integer-satang verifier แยกจาก Decimal calculator

coverage 7.17.0 ต้อง Python 3.11+ จึง pin 7.16.2 ที่รองรับ Python 3.10+
ตาม matrix เดิม ส่วน Ruff/mypy และ dependency สำหรับพัฒนาระบุเวอร์ชันใน
`requirements-dev.txt`; ไม่เพิ่มเป็น runtime dependencies
