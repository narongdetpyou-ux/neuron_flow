# ผลงานจากรายงานวิจัย — 28 ตุลาคม 2026

ลงมือและ push เป็นชุดใน branch `fix/research-hardening-20261028` จาก main `d5a72ab`
อ่าน [แผน](../../docs/RESEARCH_IMPLEMENTATION_TH.md) และ [รายการข้อเสนอ/สถานะ](../../docs/RESEARCH_BACKLOG.json)
รายงานแนบเป็นแหล่งข้อเสนอ ไม่ใช่คำสั่งให้สร้าง release หรือแก้ผลทดลอง
SHA-256 ของรายงานต้นฉบับเก็บใน `events_edge_summary.json`

## ผลตรวจ source commit 9b0ffd8 บน Linux / Python 3.12.14

- baseline 38 + current 117 กรณี ผ่านทั้งหมด; failures/errors/skipped = 0
- release guard อีก 10 กรณีผ่าน; locked 100-document fixture และ report examples ผ่าน
- edge cases เดิม 1,608/1,608 ผ่าน ไม่มี timeout รวม 3 cursor crashes ที่รายงานเดิมพบ
- quality run 155 tests ผ่าน (เป็น baseline+current ชุดเดียวกัน ไม่ใช่เพิ่มอีก 155)
- line coverage 91.86%, branch 83.73%; มี CLI และ spawn worker จริง ไม่ใช่ parent-only
- correctness lint `E9,F` ทั้ง package และ strict mypy เฉพาะ `inspection.py` ผ่าน
- wheel และ sdist ติดตั้งแยก clean venv โดยไม่ import จาก checkout; CSV 2 VALID/412.70 THB,
  ตรวจ hash/ขนาดรายงานและ resume ไม่เขียนไฟล์ใหม่
- candidate ZIP แตกใหม่ ตรวจ manifest 223 ไฟล์ และ full verifier ผ่าน
- ตัวอย่าง API, backup/restore รวมกรณี backup เสียหายและปลายทางเดิมทดสอบผ่าน

[summary.json](summary.json) ผูก source commit/fingerprint และคำสั่งของแต่ละ run
อ่าน coverage ที่ไม่ถึงเกณฑ์สมบูรณ์จาก `coverage.json`; ไม่มีการอ้างว่า coverage 100%
`quality_initial.json` และ `events_regression_results.json` เป็นผลกลางทาง แยกจากผลสุดท้าย
หลักฐานเก่าใต้ v0_2_0 และ v0_2_1 เดิมไม่ถูกเขียนทับ

## Runtime benchmark

รัน 3 samples/ขนาด เอกสารละ 5 รายการ ผ่าน CLI จริงที่รวม process startup/IPC/SQLite/fsync/delivery
1/10/100 เอกสารมี batch p50 ประมาณ 0.17/0.54/4.24 วินาที ตาม `benchmark_runtime.json`
การหยุด controller จริงแล้ว resume 100 เอกสารใช้ประมาณ 4.10 วินาที โดยงานที่เสร็จไม่ทำซ้ำ
ตัวเลขนี้เป็นผลเครื่องนี้และ whole-batch latency; 3 samples ยังไม่ใช่ tail-latency/SLA estimate ที่มั่นคง
ไม่อ้าง aggregate process-tree RAM, write amplification หรือ comprehensive worker PID visibility

## สิ่งที่อัปโหลดและสิ่งที่ยังต้องมีภายนอก

[Candidate artifacts](../../release-assets/v0.2.1-research-candidate/) มี ZIP/wheel/sdist,
SHA-256, CycloneDX SBOM และ local unsigned provenance ไม่ใช่ GitHub Release หรือ signed attestation

Git read/write ผ่าน platform proxy ได้ แต่ GitHub API ตอบ Forbidden
บันทึก `api.github.com` ใน draft ของ Environment settings แล้ว; saving ไม่ใช่การ apply/publish
จึงยังสร้าง PR/Issues/Milestones, ตรวจ Actions ของ branch นี้ หรือ apply/read-back main ruleset ไม่ได้
หากต้องการทำต่อส่วนนี้ ให้ตรวจและบันทึก network settings ที่เพิ่ม domain ดังกล่าว
การเชื่อมต่อ Git ได้ไม่ยืนยันสิทธิ์ API/admin และไม่ได้บ่งชี้ว่าต้องสร้าง token ใหม่

เพิ่ม Windows/macOS CI แล้ว แต่ยังไม่ตรวจผล runner จริง Actual Colab ยังคง `not_run`
และ 0.2.1 ยังไม่อนุมัติ/เผยแพร่ release; คำสั่งอัปโหลด source ไม่เปลี่ยนสถานะเหล่านี้
