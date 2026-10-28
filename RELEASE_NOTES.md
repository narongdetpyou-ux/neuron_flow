# Neuron Flow 0.2.1 — candidate ยังไม่เผยแพร่

รุ่นนี้เป็น candidate สำหรับตรวจและทบทวน ยังไม่ได้รับอนุมัติหรือเผยแพร่ 0.2.1
การอนุมัติ 0.2.0 ที่เก็บใน RELEASE_APPROVAL.json ไม่อนุมัติ candidate นี้โดยอัตโนมัติ
Colab จริงยังเป็น not_run และยังไม่มีผล GitHub Actions จริงในรอบนี้

## สิ่งที่เพิ่มและแก้ใน candidate

- `csv --submit-only` เก็บ source/identity และคืน batch_id กับสถานะจริงก่อนเริ่ม Agent
  การเรียก `csv` ตามปกติยังประมวลผลและส่งรายงาน
- `batch-list --workspace ...` ค้น batch โดยอ่านอย่างเดียว ใช้ได้แม้ controller กำลังถือ lock
  ช่วยเปิดงานต่อเมื่อไม่ได้รับผล CLI สุดท้ายหรือไม่มี Notebook session metadata
- เปิด workspace 0.2.0 ด้วย 0.2.1 ภายใต้ schema 1 และ policy ของ contract/Agents/settings ที่รองรับ
  ไม่เขียน identity, provenance, frozen payload หรือรายงานเก่าใหม่ หาก auto-ID พบหลาย batch ที่เข้ากันได้
  ต้องระบุรหัสชัดเจน ข้อมูลหรือสัญญาที่ขัดกันยังเกิด conflict
- `MessageSizeError` มี phase, observed_bytes, limit_bytes และ retryable=false
  job report ที่เกินขนาดแบบถาวรถูกแสดงเป็น ERROR ในรายงานชุด ไม่ติดลูปรอส่งข้อมูลเดิม
- `verify_current.py --output-dir ...` ตรวจรุ่นปัจจุบันและเก็บผลแยกจากหลักฐาน 0.2.0
  `verify.py --output-dir ...` แยก baseline ได้; จำนวน tests ให้อ่านจากรายงานจริงของ candidate
- เพิ่ม checklist/template และ API ตรวจ assertion หลักฐาน Colab ที่ผู้ใช้ส่ง
  ตรวจ package/fixture hashes, 100 jobs, attempts/hashes ก่อนหลัง และคำยืนยันรับดาวน์โหลดจริง
  tests ใช้ข้อมูลจำลอง ไม่ใช่หลักฐานว่า Colab ผ่าน; ไม่ส่งไฟล์หลักฐานยังเป็น not_run
- เตรียม CI Python 3.10/3.12 และ manual release workflow ที่ตั้ง publish=false โดยปริยาย
  การมี workflow ยังไม่ได้ยืนยันว่าแก้ปัญหาสิทธิ์ native assets HTTP 401 แล้ว

## ตรวจและสร้าง candidate

```bash
python tools/verify_current.py --output-dir verification/v0_2_1
python tools/build_delivery.py --candidate --output-dir dist
```

ผลตรวจจำนวน baseline/new tests, failures/errors/skipped, ชุดอ้างอิง 100 ใบ และ environment
อยู่ในรายงานจริงใต้ verification/v0_2_1/ ไม่ใช้จำนวนชุดใหม่ของ 0.2.0 แทนค่าปัจจุบัน
คำตอบอ้างอิงเดิม 80 VALID / 20 INVALID ยังคงล็อกไว้

ชุด candidate ประกอบด้วย neuron_flow_v0.2.1.zip, .sha256, Notebook, manifest,
BUILD_STATUS.json และ delivery_checks.json ใน output directory ตรวจจาก ZIP ที่แตกใหม่
การสร้างไฟล์เป็นงานในเครื่อง ไม่มีการเผยแพร่ภายนอก
หากไม่ระบุ --candidate ต้องมี approval ตรงรุ่นปัจจุบันและผลตรวจที่ผ่าน

## ขอบเขตที่ยังคงเดิม

เครื่องเดียว THB สัญญา purchase-csv-v1, CSV 16 MiB, engine message/job report 1 MiB,
Decimal ตรวจซ้ำด้วย integer สตางค์, สูงสุด 2 attempts รวมครั้งแรก และเอกสารยังทำทีละใบโดยใช้ worker ซ้ำ
100 เอกสารเป็นขอบเขตชุดตรวจรับ ไม่ใช่เพดานจำนวนเอกสาร ไม่มีการเพิ่ม OCR/PDF ภาษี หรือส่วนลด
backup ยังคืนที่ absolute path เดิม ไม่ได้เพิ่มการย้าย workspace ต่าง path
ผลอนุมัติเผยแพร่แยกจาก colab_acceptance_complete และการทดสอบในเครื่องไม่แทนการตรวจ Colab จริง

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
ขั้น 6 จึงยังไม่ถือว่าตรวจครบ แม้รุ่นนี้ได้รับอนุมัติให้เผยแพร่แล้ว ดู RELEASE_APPROVAL.json และ verification/v0_2_0/stage_gates.json

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
