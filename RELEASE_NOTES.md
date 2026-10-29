# Neuron Flow 0.3.0 — beta

ผู้ใช้อนุมัติให้เผยแพร่ด้วยคำสั่ง “เผยแพร่เป็น release” โดยเปิดเผยข้อจำกัดด้านล่าง
รุ่นนี้เตรียมเผยแพร่ผ่าน manual release workflow; การมีไฟล์อนุมัติหรือ build สำเร็จไม่ใช่หลักฐานว่าเผยแพร่แล้ว

## การเปลี่ยนแปลง

- รองรับ 46 สกุลเงินสำหรับ purchase CSV และ invoice JSON รวม USD, EUR, GBP, CNY, JPY และ SGD
- ใช้หน่วยย่อยทางบัญชี 0, 2 หรือ 3 ตำแหน่งตามสกุล คำนวณด้วย Decimal และตรวจซ้ำแยกด้วย integer minor units
- ปฏิเสธความละเอียดเกินกติกาโดยไม่ปัดเศษ รวมถึงทศนิยมศูนย์ที่เกินจำนวนตำแหน่ง
- รองรับเอกสารต่างสกุลใน batch เดียวกัน และรวม `certified_totals` แยกแต่ละรหัสเฉพาะเอกสาร VALID
  ผล batch หลายสกุลมี `currency` และ `certified_total` เป็น null โดยไม่รวมยอดข้ามสกุลหรือแปลงอัตราแลกเปลี่ยน
- เพิ่ม `currency` ในผลเอกสารและ summary CSV ภายใต้ `purchase-csv-multicurrency-v1`
  พร้อมตรวจสกุล ยอดจาก source และ SHA-256 ก่อนส่งมอบ
- คงสัญญาและรายงานเดิมของ THB-only intake รวมถึงผลที่บันทึกไว้ใน batch v1
  การประมวลผล source เดิมด้วยกติกาหลายสกุลใหม่ใช้ batch ID ใหม่
- เพิ่มตัวอย่าง `examples/purchases_international.csv`, คู่มือสกุลเงิน และ regression tests ของ precision,
  report tampering, CLI, recovery และ legacy currency contracts

## ความเข้ากันได้

ทุกแถวในเอกสารเดียวต้องใช้สกุลเดียวกัน รายการรหัสและกติกาอยู่ใน `docs/CURRENCIES_TH.md`
งาน CSV ที่บันทึกไว้ภายใต้ v1 ยังคงผลเดิม รวม USD ที่เดิมถูกปฏิเสธ ไม่เปลี่ยนคำตอบระหว่าง recovery
fixture 100 เอกสารใน `acceptance/` และหลักฐานเก่ายังคงเดิม โดย replay สัญญา v1 อย่างชัดเจน

invoice JSON ใช้ Agent รุ่น 2 สำหรับ extract/calculate/verify เพื่อผูกกติกาทศนิยมใหม่กับ identity
งาน invoice JSON ที่บันทึกด้วย Agent รุ่น 1 ต้องใช้ runtime เดิม หรือเริ่ม job ใหม่ใน workspace ใหม่
Python API ยังทดลอง ผู้ต่อยอดควร pin รุ่น/commit และตรวจ integration ของตนก่อนอัปเกรด

## ผลตรวจและขอบเขต

ก่อนเปลี่ยนหมายเลขรุ่น ชุด regression ของส่วนเพิ่มผ่าน 173 tests ไม่มี failure/error/skipped
รวม 15 กรณีใหม่สำหรับสกุลเงิน พร้อม lint, scoped typing, branch coverage, wheel/sdist installation
และ CLI จาก wheel ที่ติดตั้งจริง การตรวจรุ่น 0.3.0 และ package ที่แตกใหม่จะบันทึกผลอีกครั้ง
ใน manual release workflow และไฟล์ verification ของ build นั้น ให้ใช้ผลที่ตรงกับ source/tag สุดท้าย

ผล Windows/macOS ของ 0.2.1 เป็นหลักฐานประวัติ ไม่ใช้รับรองรุ่น 0.3.0
การเตรียมรุ่นนี้ยังไม่มีผล CI Windows/macOS 0.3.0 ที่ยืนยันแล้ว
Actual Google Colab upload/run/resume/download/restore acceptance ยัง `not_run`

## ข้อจำกัดที่เปิดเผย

- ไม่มีการแปลงอัตราแลกเปลี่ยนหรือปัดเศษสำหรับเงินสด และไม่รับสกุลนอกตารางที่ระบุ
- แต่ละเอกสารใช้สกุลเดียว การใส่สกุลผสมในใบเดียวเป็น INVALID
- ตรวจ full recovery/fault-injection บน Linux; smoke subset บนแพลตฟอร์มอื่นไม่แทนชุดเต็ม
- เอกสารทำทีละใบ ใช้ worker ซ้ำ และ backup/restore ต้องใช้ absolute workspace path เดิม
- CSV สูงสุด 16 MiB; engine message/job report สูงสุด 1 MiB; retry รวมสูงสุด 2 attempts
- ไม่มี OCR/PDF, tax/discount engine หรือ SLA production

ตรวจ SHA-256 ของ ZIP และไฟล์ภายในก่อนใช้ เก็บ backup ของ workspace
การอนุมัติเผยแพร่ไม่เปลี่ยนผล Colab หรือทำให้ `not_run` กลายเป็น passed

## ประวัติรุ่น 0.2.1

### Neuron Flow 0.2.1 — beta

อนุมัติให้เผยแพร่ตามคำสั่งเจ้าของงาน โดยเปิดเผยข้อจำกัดด้านล่าง
เป็นรุ่นสำหรับ purchase CSV/CLI บนเครื่องเดียว ไม่ใช่การรับรอง production หรือ SLA

## การเปลี่ยนแปลง

- รับงานด้วย `csv --submit-only`, ค้น batch ที่คงอยู่ด้วย `batch-list` และ resume โดยไม่ต้องมี source upload เดิม
- รองรับ workspace 0.2.0 ตาม schema/contract/Agent compatibility ที่กำหนดไว้
- แสดง structured size-limit errors โดยไม่ขัดขวางเอกสารอื่นใน batch
- ปฏิเสธ `events --after` เกิน signed-int64 ด้วย JSON error แทน traceback และไม่สร้าง workspace
- รักษาไบต์ golden fixture บน Windows โดยไม่เปลี่ยนคำตอบอ้างอิงหรือ checksum
- เพิ่ม hash-locked patched build tools, clean wheel/sdist installation checks, branch coverage,
  correctness lint และ incremental strict typing ของ discovery boundary
- เพิ่ม full-runtime benchmark พร้อม real controller kill/recovery, API examples และ backup/restore runbook
- จัดดัชนีหลักฐาน เก็บสถานะ/approval เก่าใน archive ลบ cache ที่สร้างใหม่ได้ และนำ manifest เก่าที่ซ้ำออกจาก source root
  package ZIP ยังคงมี manifest ที่สร้างจากไฟล์จริงของ package นั้น

## ผลตรวจและขอบเขต

Windows/macOS smoke ผ่าน Python 3.10/3.12 และ Linux regression/quality/distribution ผ่านจริง
[CI ของ Windows fix](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40717586187)
ผลที่ตรงกับ source/tag สุดท้ายจะอยู่ใน manual release workflow และใน package verification
แต่ละรอบบันทึกจำนวน tests, failures, errors และ skipped จริง ไม่ใช้จำนวนเก่าแทนรุ่นปัจจุบัน
SHA-256, frozen expected answers และ independent Decimal/integer-satang checks ยังคงเดิม

## ข้อจำกัดที่เปิดเผย

- Actual Google Colab upload/run/resume/download/restore acceptance ยัง `not_run`
- Windows/macOS ตรวจ smoke subset; full recovery/fault-injection suite ตรวจบน Linux
- Python API ใน 0.2.x ยังทดลอง; เอกสารทำทีละใบ ใช้ workers ซ้ำ ไม่ใช่ batch parallel scheduling
- backup/restore ใช้ absolute workspace path เดิม ไม่มี workspace relocation
- THB, CSV สูงสุด 16 MiB, engine message/job report สูงสุด 1 MiB และ retry รวมสูงสุด 2 attempts
- ไม่มี OCR/PDF, tax/discount engine หรือ SLA production

รับ ZIP/checksum/Notebook จาก release นี้ ตรวจ SHA-256 ก่อนใช้และเก็บ backup ของ workspace
การอนุมัติเผยแพร่ไม่เปลี่ยน `colab_acceptance_complete` และไม่ทำให้หลักฐาน `not_run` กลายเป็น passed

## ประวัติรุ่น 0.2.0 — เผยแพร่แล้ว

รุ่นนี้เพิ่มการรับ CSV หลายเอกสาร ตรวจข้อมูลและยอดเงินแยกรายใบ พร้อมทำงานต่อหลังหยุดและรายงานที่ย้อนถึงต้นทางได้

- รองรับ UTF-8/UTF-8 BOM รวมรายการด้วย document_id และเก็บทุกแถว รวมแถวที่จัดกลุ่มไม่ได้
- แยก VALID, INVALID และ ERROR จาก engine_status คำนวณด้วย Decimal และตรวจซ้ำด้วย integer สตางค์
- จำกัดการลองรวม 2 ครั้ง แยกความล้มเหลวรายเอกสาร และ resume โดยไม่ทำขั้นที่สำเร็จแล้วซ้ำ
- ส่ง summary.csv, details.json และ source.csv แบบ atomic ตรวจเนื้อหาและ SHA-256 ก่อนบันทึก receipt และรักษาไฟล์เดิมเมื่อเกิด conflict
- มี Notebook สำหรับ Colab, README ภาษาไทย/อังกฤษ และชุดตรวจรับพร้อมคำตอบอ้างอิงที่ล็อกไว้

ผลตรวจ: ฐานเดิม 38 กรณีและชุดใหม่ 65 กรณีผ่าน ไม่มี failure/error/skipped; ผลครบ 100 เอกสารตรงคำตอบอ้างอิง (80 VALID / 20 INVALID)
ทดสอบ Agent ค้าง, worker ตาย และหยุด controller จริง รวมจุดหลังเขียนรายงานแต่ก่อนบันทึก receipt
ชุด ZIP ตรวจ SHA-256 และรันชุดตรวจทั้งหมดจากการแตกไฟล์ใหม่อีกครั้ง

### ข้อจำกัดที่เปิดเผยในการเผยแพร่

ผู้ใช้อนุมัติปิดรุ่นและเผยแพร่ โดยยังไม่มีผลตรวจรับบน Google Colab จริง
การตรวจ Notebook แบบ offline และผลใน Linux ไม่ใช้แทนการเริ่ม Colab runtime ใหม่ อัปโหลด ZIP/CSV รัน ทำต่อ และดาวน์โหลดผลจริง
ขั้น 6 จึงยังไม่ถือว่าตรวจครบ แม้รุ่นนี้ได้รับอนุมัติให้เผยแพร่แล้ว ดู verification/archive/RELEASE_APPROVAL_0_2_0.json และ verification/v0_2_0/stage_gates.json

ขอบเขตปัจจุบัน: เครื่องเดียว, THB, CSV ไม่เกิน 16 MiB และข้อความ engine ไม่เกิน 1 MiB; ยังไม่ได้ยืนยัน Windows/macOS
100 เอกสารเป็นขอบเขตชุดตรวจรับรอบนี้ ไม่ใช่เพดานจำนวนเอกสาร

### เริ่มใช้

แตก neuron_flow_v0.2.0.zip แล้วรันในโฟลเดอร์ neuron_flow:

```bash
python -m neuron_flow csv examples/purchases.csv --batch-id demo
python -m neuron_flow batch-resume demo
```

ตรวจ SHA-256 ของ ZIP ด้วยไฟล์ neuron_flow_v0.2.0.zip.sha256 และตรวจไฟล์ภายในด้วย SHA256SUMS.txt
ไฟล์ตรวจการส่งมอบ delivery_checks.json แนบแยกจาก ZIP เพื่อไม่ให้ hash อ้างกลับเข้าหาตัว ZIP เอง
