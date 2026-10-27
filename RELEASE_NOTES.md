# Neuron Flow 0.2.0

รุ่นนี้เพิ่มการรับ CSV หลายเอกสาร ตรวจข้อมูลและยอดเงินแยกรายใบ พร้อมทำงานต่อหลังหยุดและรายงานที่ย้อนถึงต้นทางได้

- รองรับ UTF-8/UTF-8 BOM รวมรายการด้วย document_id และเก็บทุกแถว รวมแถวที่จัดกลุ่มไม่ได้
- แยก VALID, INVALID และ ERROR จาก engine_status คำนวณด้วย Decimal และตรวจซ้ำด้วย integer สตางค์
- จำกัดการลองรวม 2 ครั้ง แยกความล้มเหลวรายเอกสาร และ resume โดยไม่ทำขั้นที่สำเร็จแล้วซ้ำ
- ส่ง summary.csv, details.json และ source.csv แบบ atomic ตรวจเนื้อหาและ SHA-256 ก่อนบันทึก receipt และรักษาไฟล์เดิมเมื่อเกิด conflict
- มี Notebook สำหรับ Colab, README ภาษาไทย/อังกฤษ และชุดตรวจรับพร้อมคำตอบอ้างอิงที่ล็อกไว้

ผลตรวจ: ฐานเดิม 38 กรณีและชุดใหม่ 65 กรณีผ่าน ไม่มี failure/error/skipped; ผลครบ 100 เอกสารตรงคำตอบอ้างอิง (80 VALID / 20 INVALID)
ทดสอบ Agent ค้าง, worker ตาย และหยุด controller จริง รวมจุดหลังเขียนรายงานแต่ก่อนบันทึก receipt
ชุด ZIP ตรวจ SHA-256 และรันชุดตรวจทั้งหมดจากการแตกไฟล์ใหม่อีกครั้ง

## ข้อจำกัดที่เปิดเผยในการเผยแพร่

ผู้ใช้อนุมัติปิดรุ่นและเผยแพร่ โดยยังไม่มีผลตรวจรับบน Google Colab จริง
การตรวจ Notebook แบบ offline และผลใน Linux ไม่ใช้แทนการเริ่ม Colab runtime ใหม่ อัปโหลด ZIP/CSV รัน ทำต่อ และดาวน์โหลดผลจริง
ขั้น 6 จึงยังไม่ถือว่าตรวจครบ แม้รุ่นนี้ได้รับอนุมัติให้เผยแพร่แล้ว ดู RELEASE_APPROVAL.json และ verification/v0_2_0/stage_gates.json

ขอบเขตปัจจุบัน: เครื่องเดียว, THB, CSV ไม่เกิน 16 MiB และข้อความ engine ไม่เกิน 1 MiB; ยังไม่ได้ยืนยัน Windows/macOS
100 เอกสารเป็นขอบเขตชุดตรวจรับรอบนี้ ไม่ใช่เพดานจำนวนเอกสาร

## เริ่มใช้

แตก neuron_flow_v0.2.0.zip แล้วรันในโฟลเดอร์ neuron_flow:

```bash
python -m neuron_flow csv examples/purchases.csv --batch-id demo
python -m neuron_flow batch-resume demo
```

ตรวจ SHA-256 ของ ZIP ด้วยไฟล์ neuron_flow_v0.2.0.zip.sha256 และตรวจไฟล์ภายในด้วย SHA256SUMS.txt
ไฟล์ตรวจการส่งมอบ delivery_checks.json แนบแยกจาก ZIP เพื่อไม่ให้ hash อ้างกลับเข้าหาตัว ZIP เอง
