# Neuron Flow 0.3.0 — beta

รับ CSV รายการซื้อหลายเอกสาร ตรวจข้อมูลและยอดเงินแยกรายใบ พร้อมรายงานย้อนถึงแถวต้นทาง
เอกสารที่ข้อมูลผิดหรือ Agent ล้มไม่ขัดขวางเอกสารอื่น และเปิด workspace เดิมเพื่อทำต่อได้
ใช้ Python 3.10 ขึ้นไปและ standard library บนเครื่องเดียว ไม่ต้องมี API key

**รุ่น 0.3.0:** รองรับ 46 สกุลเงิน รวม USD, EUR, GBP, CNY,
JPY และ SGD โดยใช้ทศนิยม 0, 2 หรือ 3 ตำแหน่งตามสกุล และแยกยอดรวมรายสกุล
**เผยแพร่ 0.3.0 แล้ว** เมื่อ 29 ตุลาคม 2026 เวลา 16:49:18 น. ประเทศไทย
ดาวน์โหลดจาก [Release v0.3.0](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.3.0)
ตรวจครบ 6 assets และ 367 ZIP manifest entries ใน [บันทึกหลังเผยแพร่ 0.3.0](verification/publication_v0_3_0_2026_10_29/README.md)
ไฟล์ Release 0.2.1 ที่กล่าวถึงด้านล่างยังไม่มีส่วนเพิ่มนี้
ดู [รายการสกุลเงินและกติกา](docs/CURRENCIES_TH.md)

**ประวัติ:** เผยแพร่ 0.2.1 แล้วเมื่อ 28 ตุลาคม 2026 เวลา 23:17:10 น. ประเทศไทย
สำหรับ workflow CSV/CLI บนเครื่องเดียวที่ตรวจแล้ว ดูไฟล์และ checksum ที่
[Release v0.2.1](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.2.1)
ผลดาวน์โหลดครบ 6 assets และการตรวจ hash อยู่ใน [บันทึกหลังเผยแพร่](verification/publication_2026_10_29/README.md)
เพิ่ม submit-only, batch discovery, workspace 0.2.0 compatibility, structured size-limit errors,
event cursor bounds และการรักษาไบต์ fixture บน Windows
ดู [ดัชนีหลักฐาน](verification/README.md) เพื่อแยกรอบและขอบเขตการตรวจ

Colab จริงยังเป็น `not_run` การอนุมัติและผล local ไม่แทนการตรวจ Colab จริง
[การอนุมัติ 0.2.0 เดิม](verification/archive/RELEASE_APPROVAL_0_2_0.json) เก็บใน archive แล้ว
[CI ของ 0.3.0](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40852073574) ผ่านครบ 9 jobs
รวม Windows/macOS smoke บน Python 3.10/3.12
full fault-injection suite ตรวจบน Linux

## เริ่มใช้ CSV

ดาวน์โหลด `neuron_flow_v0.3.0.zip` จาก [Release v0.3.0](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.3.0)
ตรวจ checksum แล้วแตก ZIP แล้วเปิด terminal ในโฟลเดอร์ `neuron_flow`
ที่มีไฟล์นี้ ไม่ต้องติดตั้ง dependency เพิ่ม:

```bash
python -m neuron_flow csv examples/purchases.csv --batch-id demo --workspace batch_workspace
python -m neuron_flow batch-list --workspace batch_workspace
python -m neuron_flow batch-status demo --workspace batch_workspace
python -m neuron_flow batch-resume demo --workspace batch_workspace
```

ตัวอย่างปกติได้ 2 VALID ยอดที่รับรองรวม 412.70 บาท รวมตัวอย่างเดิม 310.70 บาท
คำสั่ง `csv` ประมวลผลและส่งรายงานให้แล้ว ผลจะแสดง `receipt.artifacts` พร้อม path, SHA-256 และขนาด
ไฟล์อยู่ใน `batch_workspace/batch_reports/demo/`:

| ไฟล์ | เนื้อหา |
| --- | --- |
| `summary.csv` | ผลรายใบ ยอดที่ระบุ/คำนวณ ผลต่าง จำนวนข้อผิดพลาด แถวต้นทาง และ engine_status |
| `details.json` | ผลละเอียด เหตุผลรายจุด รุ่นระบบ/Agent ประวัติงาน และ source_records ต้นฉบับ |
| `source.csv` | ไฟล์เข้าเดิมทุกไบต์ รวม BOM ถ้ามี |

ตัวอย่างหลายสกุลเงิน:

```bash
python -m neuron_flow csv examples/purchases_international.csv --batch-id international --workspace batch_workspace
```

ได้ 4 VALID และ `certified_totals` แยกเป็น USD `21.50`, EUR `25.50`, JPY `1500`
และ KWD `3.702` ส่วน `currency` กับ `certified_total` เป็น `null` เมื่อมีหลายสกุล
รายงานแต่ละใบและ `summary.csv` ระบุสกุลเงิน ระบบไม่รวมเงินต่างสกุลเป็นยอดเดียว
และไม่มีการแปลงหรือดึงอัตราแลกเปลี่ยน

ลองข้อมูลผิดและแถวที่ไม่มีรหัสเอกสาร:

```bash
python -m neuron_flow csv examples/purchases_invalid.csv --batch-id mixed --workspace batch_workspace
```

ได้ 1 VALID, 2 INVALID, 0 ERROR และแถวที่จัดกลุ่มไม่ได้ 1 แถว ยอดที่รับรอง 10.00 บาท
INVALID บอก `row_number`, `field`, `reason_code`, `expected`, `actual` โดยไม่ลองข้อมูลเดิมซ้ำ
แถวว่างหรือแถวที่ไม่มี `document_id` เก็บใน `ungrouped_rows` ไม่ถูกทิ้ง
หัวตารางผิด/ซ้ำ/ขาด หรือมีชื่อช่องเกินหัวตาราง หรือ UTF-8/ไวยากรณ์ CSV ผิด จะปฏิเสธทั้งไฟล์พร้อมเหตุผล
แถวข้อมูลที่จำนวนช่องไม่ครบ/เกินยังถูกเก็บพร้อมข้อผิดพลาดรายแถว

ละ `--batch-id` เพื่อให้ระบบสร้างหรือค้นรหัสจากข้อมูลและสัญญาการทำงานที่เข้ากันได้
ถ้ามี batch ที่เข้ากันได้หลายรายการ ระบบจะให้ระบุรหัสอย่างชัดเจน ใช้ `batch-list` ค้นแล้วระบุ `--batch-id`
ถ้าแก้ข้อมูลให้ใช้รหัสใหม่ รหัสเดิมกับข้อมูล contract, Agent หรือ settings ที่ขัดกันยังเป็น conflict

## รับงานก่อน แล้วเลือกเวลาประมวลผล

```bash
python -m neuron_flow csv examples/purchases.csv --submit-only --batch-id queued --workspace batch_workspace
python -m neuron_flow batch-list --workspace batch_workspace
python -m neuron_flow batch-resume queued --workspace batch_workspace
```

`--submit-only` เก็บ source/identity และคืน batch_id พร้อมสถานะจริงก่อนเริ่ม Agent
งานใหม่ยังไม่ใช้ attempts; หากรับรหัสเดิมซ้ำ สถานะที่คืนอาจเป็นสถานะงานที่ทำเสร็จแล้ว
เมื่อ CLI ถูกหยุดก่อนคืนผลหรือไม่มี session metadata ให้ใช้ `batch-list` หา batch เดิมแล้วเปิดต่อ
คำสั่งนี้อ่านอย่างเดียว ไม่เปิด worker ไม่ยึด controller lock และใช้ได้ขณะ controller ทำงาน
ส่วน `batch-status` ยังคงเป็นคำสั่งผ่าน Runtime ที่ใช้ workspace lock

## เปิด CSV workspace 0.2.0/0.2.1 ด้วย 0.3.0

รองรับรูปแบบ workspace schema 1 รวมรูปแบบ 0.2.0 ที่ยังไม่มี marker ของ schema/execution
เมื่อสัญญา CSV, Agent definitions/versions และค่าควบคุมงานตรงกับ policy ที่รองรับ
ไม่เปลี่ยน identity รุ่นต้นทาง frozen payload หรือรายงานเดิม งานที่สร้างจาก 0.2.0
ยังระบุ provenance เป็น 0.2.0; งานใหม่รุ่นนี้ระบุ 0.3.0 ตามจริง
ไม่รับรองทุกรุ่นจากหมายเลข patch อย่างเดียว และข้อมูล/สัญญาที่ขัดกันยังถูกปฏิเสธ
การคืน backup ยังต้องใช้ absolute path เดิม ไม่รองรับย้าย workspace ไป path ใหม่ในรอบนี้

## สัญญาข้อมูล CSV

CSV รองรับ UTF-8 และ UTF-8 BOM หนึ่ง record ต่อหนึ่งรายการซื้อ รวมใบด้วย `document_id`
หัวตารางต้องมีชื่อครบตามนี้ สลับลำดับคอลัมน์ได้:

```csv
document_id,item_id,description,quantity,unit_price,declared_total,currency
INV-001,A,สมุด,2,125.50,310.70,THB
INV-001,B,ปากกา,3,19.90,310.70,THB
```

| ช่อง | กติกา |
| --- | --- |
| `document_id` | มีข้อความ รวมแถวของเอกสารเดียวกันหลังตัดช่องว่างหัวท้าย |
| `item_id` | มีข้อความ ไม่ซ้ำในใบเดียวกันหลังตัดช่องว่างหัวท้าย |
| `description` | มีข้อความ รองรับไทย comma/quote และข้อความหลายบรรทัดตาม CSV |
| `quantity` | ตัวเลข ASCII จำนวนเต็ม 1–1,000,000 รูปแบบ 1–7 หลัก |
| `unit_price` | ตัวเลขไม่ติดลบ สูงสุด 10¹² หน่วยของสกุลนั้น ทศนิยมตามสกุลเงิน |
| `declared_total` | ตัวเลขไม่ติดลบ สูงสุด 10²² หน่วยของสกุลนั้น ทศนิยมตามสกุล ค่าเชิงตัวเลขต้องตรงกันทุกแถว |
| `currency` | รหัสตัวพิมพ์ใหญ่ที่รองรับ เช่น THB, USD, EUR, JPY และเหมือนกันทุกแถวในใบเดียวกัน |

JPY, KRW, VND, CLP และ ISK ใช้จำนวนเต็ม; BHD, KWD, OMR, JOD และ TND ใช้ทศนิยม
ได้ไม่เกิน 3 ตำแหน่ง; สกุลอื่นใน [รายการที่รองรับ](docs/CURRENCIES_TH.md) ใช้ได้ไม่เกิน 2 ตำแหน่ง
ค่าที่ละเอียดเกินกติกาถูกปฏิเสธโดยไม่ปัดเศษ แม้หลักที่เกินจะเป็นศูนย์

ข้อมูล THB ล้วนยังใช้ `purchase-csv-v1` และรูปแบบรายงานเดิม ส่วนข้อมูลที่มีสกุลอื่น
ใช้ `purchase-csv-multicurrency-v1` โดยอัตโนมัติ งาน v1 ที่บันทึกแล้วเปิดต่อด้วยกติกาเดิม
รวมถึงผล INVALID ของสกุลเงินที่เดิมไม่รองรับ หากต้องการประมวลผล source เดิมด้วยกติกาใหม่
ให้ใช้ batch ID ใหม่ ชุดอ้างอิง 100 เอกสารยังตรวจด้วยโหมด legacy เพื่อคงคำตอบเดิม
80 VALID / 20 INVALID; เมื่อใช้กติกาใหม่ เอกสาร USD ในชุดนั้นสามารถผ่านได้

ข้อความรหัสและคำอธิบายยาวไม่เกิน 500 ตัวอักษร หนึ่งใบมี 1–10,000 รายการตามฐานเดิม
เก็บค่าดิบไว้เสมอ `source_rows` / `row_number` นับบรรทัดจริงเริ่มต้น CSV record
โดยหัวตารางเริ่มที่ 1 ข้อความหลายบรรทัดจึงทำให้เลขแถวถัดไปขยับมากกว่าหนึ่ง
จำนวนเอกสาร = VALID + INVALID + ERROR; แถวที่จัดกลุ่มไม่ได้แสดงแยกจากจำนวนเอกสาร

## สถานะและยอดเงิน

| document_status | ความหมาย |
| --- | --- |
| VALID | ข้อมูลผ่าน Decimal คำนวณผ่านการตรวจซ้ำด้วย integer หน่วยย่อยของสกุลเงิน และตรง declared_total |
| INVALID | ข้อมูลผิดกติกาหรือยอดไม่ตรง มีเหตุผลตรวจกลับได้ |
| ERROR | ระบบยังยืนยันผลไม่ได้ เช่น Agent ล้มและหมดจำนวนครั้งที่ลอง |

`engine_status` แสดงผลประมวลผลแยกจากผลตรวจข้อมูล เช่น ใบ INVALID สามารถมี
engine_status เป็น SUCCEEDED ได้ ส่วน ERROR ยังคงแสดงในรายงานแม้เขียนรายงานสำเร็จ
ยอดรวมที่รับรองนับเฉพาะ VALID ไม่มีการใช้ float คำนวณเงิน
รายงานสัญญาหลายสกุลเงินมี `certified_totals` แยกตามรหัสสกุล หากมีสกุลเดียว
`currency` และ `certified_total` แสดงรหัสกับยอดนั้นด้วย หากมีหลายสกุลทั้งสองช่องเป็น `null`
`difference` = computed_total − declared_total; ใบข้อมูลผิดมี computed_total/difference เป็น null
ยกเว้น TOTAL_MISMATCH ซึ่งยังคำนวณยอดและผลต่างได้

CLI คืน 0 เมื่อประมวลผล/ส่งรายงานสำเร็จหรืออ่านสถานะได้ และไม่มีเอกสาร ERROR;
คืน 1 เมื่อมี ERROR หรือสถานะ DELIVERY_FAILED; คืน 2 เมื่อคำสั่ง ข้อมูลตั้งต้น หรือการส่งมอบเกิด exception
`--submit-only` คืน 0 เมื่อรับงานได้ และ `batch-list` คืน 0 เมื่ออ่านได้ ซึ่งยังไม่รับรองว่าเอกสาร VALID
ตรวจ `counts` และ `receipt` ร่วมกับ exit code ของการประมวลผลเสมอ

## หยุดและทำต่อ

SQLite เก็บ source bytes งาน ประวัติ ความพยายาม และผลรายงานที่ตรึงไว้ก่อนส่งมอบ
เรียก `batch-resume` บน workspace เดิมโดยไม่ต้องมี CSV ต้นทางอีกครั้ง
งานที่ผ่านแล้วไม่ถูกเรียกซ้ำ และรายงานเดิมไม่ถูกเขียนซ้ำ การส่งไฟล์แต่ละไฟล์เป็น atomic
พร้อม fsync ตรวจเนื้อหาและ SHA-256 หลังเขียน ความขัดแย้งของไฟล์ใดไฟล์หนึ่งจะถูกตรวจ
ก่อนสร้างไฟล์ใหม่ ถ้าหยุดระหว่างส่งสามไฟล์ การเปิดต่อเติมเฉพาะไฟล์ที่ขาด
และบันทึก receipt เมื่อครบทุกไฟล์แล้ว

ค่าเริ่มต้น timeout 5 วินาทีต่อครั้งหลัง worker พร้อมใช้งาน และ max_attempts = 2 **รวมครั้งแรก**
Agent ค้างหรือ worker ตายอาจลองใหม่ภายในงบ; ข้อมูลผิด/ผลตรวจไม่ผ่านไม่ถูกลองซ้ำอัตโนมัติ
การถูกขัดจังหวะระหว่างทำงานนับเป็นความพยายามหนึ่งครั้ง เอกสารที่หมดงบยังเป็น ERROR
ตัว controller ต้องถูกเปิดต่อโดยผู้ใช้ ไม่มี service ภายนอกคอยเริ่มให้เอง

รุ่นนี้จัดเอกสารทีละใบและใช้ worker เดิมซ้ำ `--workers` ตั้งเพดาน worker (1–32 ค่าเริ่มต้น 3)
จึงไม่ใช่ตัวเลขรับรองว่าเอกสารหลายใบจะรันพร้อมกัน เปิด controller เดียวต่อ workspace
ผูกงานกับสัญญาข้อมูล/schema/execution, Agent และ timeout การเปิด CSV workspace 0.2.0/0.2.1 ด้วย 0.3.0 ใช้ policy
ความเข้ากันได้ข้างต้น การเปลี่ยนสัญญาหรือรุ่นนอก policy ต้องคืน runtime ที่รองรับหรือใช้รหัสใหม่

## ขอบเขตการใช้งาน

- CSV ต้นทางไม่เกิน 16 MiB; ข้อความ workflow/Agent/report เดิมจำกัด 1 MiB
  เอกสารที่ใหญ่เกินขอบเขต engine ถูกแสดงเป็น ERROR โดยเอกสารอื่นยังทำต่อ
- 100 เอกสารแบบ 80 ถูก/20 ผิดเป็นขอบเขตชุดตรวจรับรอบนี้ ไม่ใช่อัตราข้อมูลจริงหรือเพดานจำนวนเอกสาร
- ใช้เครื่องเดียว ไม่มี OCR, PDF, ภาษี ส่วนลด การเรียนรู้เอง หรือการเลือกวิธีแก้จากภาษาธรรมชาติ
- worker เป็น process สำหรับจัดการค้าง/ล้ม ไม่ใช่ sandbox ของโค้ดที่ไม่เชื่อถือ และไม่มีเพดาน RAM ราย Agent
- ทดสอบชุดเต็มบน Linux; Windows/macOS ของ 0.3.0 ผ่าน smoke subset ใน CI ของ source ที่เผยแพร่
  ยังไม่มีผลตรวจ Google Colab จริง และ smoke ไม่แทน full fault-injection suite ทุกแพลตฟอร์ม

ข้อผิดพลาด `MessageSizeError` ระบุ `phase`, `observed_bytes`, `limit_bytes` และ `retryable: false`
เพื่อบอกว่าขนาดเกินในช่วงใดและลองข้อมูลเดิมซ้ำไม่ช่วย ถ้า job report เกินขนาดแบบถาวร
batch จะแสดงเอกสารนั้นเป็น ERROR และส่งรายงานชุดได้ โดยไม่ติดลูปรอส่ง job report เดิมไม่สิ้นสุด
ERROR ยังคงอยู่ในผลสุดท้ายแม้ batch ส่งรายงานสำเร็จ

โครงห้าส่วนคงเดิม: Dendrite รับงาน, Soma จัดคิว/กู้คืน, Axon ส่ง dependency,
Synapse ตรวจสัญญา/ผล และ Axon terminal ส่งมอบพร้อม receipt
ตัวอย่าง JSON เดิมยังใช้ `python -m neuron_flow demo` และ
`python -m neuron_flow invoice examples/invoice.json --job-id my_invoice` ได้
Agent ต้องเป็นฟังก์ชันในโมดูลที่ import ได้และมี main guard เมื่อเปิด Runtime จากสคริปต์
การไม่ทำซ้ำที่ทดสอบครอบคลุมรายงานภายใน ไม่ได้รับรองผลข้างเคียงของ Agent เพิ่มเองต่อบริการภายนอก

## ตรวจซ้ำและสร้างชุดส่งมอบ

```bash
python tools/verify.py --output-dir /tmp/neuron-flow-verification-0.3.0/baseline
python tools/build_acceptance_fixture.py --check
python tools/verify_current.py --output-dir /tmp/neuron-flow-verification-0.3.0
python tools/build_delivery.py --candidate --verification-dir /tmp/neuron-flow-verification-0.3.0 --output-dir dist
```

`verify.py` ตรวจ baseline เดิมแยกจาก `verify_current.py` ที่ค้น tests ของรุ่นปัจจุบัน
พร้อมเทียบ 100 เอกสารกับคำตอบที่ล็อกและเก็บหลักฐาน A01–A12 จำนวน baseline/new tests,
failures/errors/skipped และข้อมูล Python อ่านจาก output directory ของรอบนั้น
ตัวอย่าง POSIX ด้านบนใช้โฟลเดอร์ชั่วคราวใหม่ เลือก path อื่นที่ยังไม่ใช้ได้ และไม่เขียนทับหลักฐานเก่า
[บันทึกหลังเผยแพร่ 0.3.0](verification/publication_v0_3_0_2026_10_29/README.md) ระบุ source, CI/release runs และ hash ของไฟล์ที่ดาวน์โหลด
ส่วน[รายงานจาก ZIP ของ 0.2.1](verification/publication_2026_10_29/README.md) บันทึก
38 baseline + 120 current + 10 release guards ผ่าน ส่วนรายงานเดิมข้างเคียงใน `verification/v0_2_1/`
เป็นรอบก่อนหน้า [stage gates](verification/v0_2_1/stage_gates.json) สรุปรุ่นเผยแพร่พร้อมลิงก์รายงานที่ตรงกันแล้ว
`verify_v020.py` เก็บไว้เป็นเครื่องมือประวัติของ 0.2.0 ไม่ใช้ตรวจรุ่นปัจจุบัน
คำตอบอ้างอิงและ SHA-256 ที่ล็อกอยู่ใน `acceptance/` ห้ามสร้างคำตอบจากผลของ validator รุ่นใหม่
การเปลี่ยนเกณฑ์ต้องบันทึกเหตุผลและตรวจกรณีที่ได้รับผลกระทบใหม่

`build_delivery.py --candidate` ตรวจแล้วสร้าง `dist/neuron_flow_v0.3.0.zip` พร้อมไฟล์ `.sha256`,
Notebook, `SHA256SUMS.txt`, `BUILD_STATUS.json` และ `delivery_checks.json` ใน output directory
มีการตรวจจากการแตก ZIP ใหม่ ไฟล์สถานะของ candidate ให้ดูใน output directory;
ไฟล์สถานะ/ผลตรวจ 0.2.0 ที่เก็บไว้ไม่ใช่ผลปัจจุบัน การสร้าง ZIP ไม่เผยแพร่ภายนอก
`BUILD_STATUS.json` และ `delivery_checks.json` บันทึกก่อนเผยแพร่ จึงคง `published:false`
ใน release assets ที่ล็อกไว้ ใช้[บันทึกหลังเผยแพร่ 0.3.0](verification/publication_v0_3_0_2026_10_29/README.md) เพื่อตรวจสถานะ remote ที่สังเกตได้
หากไม่ระบุ `--candidate` ต้องมีการอนุมัติที่ตรงรุ่น 0.3.0; approval ของรุ่นก่อนใช้แทนไม่ได้

มี CI สำหรับ Python 3.10/3.12 และ workflow เผยแพร่แบบ manual ซึ่งตั้ง `publish=false` เป็นค่าเริ่มต้น
รายงานวิจัยวันที่ 28 ตุลาคม 2026 บันทึกว่า main CI ของ commit
`d5a72ab64a7439c999faf7ba47f77239d1238a11` ผ่านแล้ว
ผลดังกล่าวเป็น snapshot ไม่ใช่ผล CI ของ commit ที่แก้ภายหลัง
ดู [บันทึกการลงมือทำ](docs/RESEARCH_IMPLEMENTATION_TH.md) สำหรับประวัติช่วงนั้น
ภายหลัง [Manual release run #3](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40723991028)
ผ่านทั้ง build และ publish และบันทึกหลังเผยแพร่ยืนยันดาวน์โหลด native assets พร้อม hash ตรงแล้ว
HTTP 401 เป็นผลของการอัปโหลดในอดีต ไม่ใช่ผลของ release 0.2.1 ส่วน Colab จริงยังเป็น `not_run`

## ใช้ Notebook บน Google Colab

เปิด `START_COLAB.ipynb` ใน Colab runtime ใหม่ แล้วรันเซลล์ตามคำอธิบาย:
อัปโหลด ZIP รุ่น 0.3.0 → ตรวจ SHA-256 ทุกไฟล์ → อัปโหลด CSV หนึ่งไฟล์ → รับงาน/รัน CLI
→ ดูรายงาน → เปิดต่อโดยไม่อัปโหลด CSV ซ้ำ → ตรวจทั้งชุด → ดาวน์โหลด backup
ไม่มี Agent อยู่ในเซลล์ Notebook; เซลล์เรียก Python ผ่าน subprocess

Colab เก็บไฟล์ในพื้นที่ชั่วคราว ต้องดาวน์โหลด ZIP สำรองก่อนจบ session
backup รวม workspace SQLite ที่สำรองอย่างสอดคล้อง รายงาน verification และ session metadata
การคืน backup รุ่นเดียวกันใช้ ZIP โปรเจกต์เดิมและ workspace path เดิม
(`/content/neuron_flow_workspace`) เพราะ receipt เก็บ absolute path
Notebook มีเซลล์คืน backup สำหรับ runtime ใหม่ โดยไม่เขียนทับ workspace ที่มีข้อมูลอยู่

การตรวจ syntax ของเซลล์และการทดสอบในเครื่องยังไม่ใช่การตรวจบน Colab จริง
ทำตาม [รายการตรวจ Colab](docs/COLAB_ACCEPTANCE_TH.md) และใช้
[template หลักฐาน](docs/colab_acceptance_TEMPLATE.json) เริ่มที่ `not_run`/checks=false
เมื่อมีหลักฐานจริงครบแล้วจึงส่งไฟล์ให้ verifier ด้วย `--colab-evidence path/to/evidence.json`
ตัวตรวจตรวจ assertion ที่ผู้ใช้ส่งกับรุ่น package/fixture hashes และความสอดคล้องของข้อมูล
ไม่ใช่การรับรอง runtime ระยะไกลอัตโนมัติ tests ของตัวตรวจใช้ข้อมูลจำลอง ไม่ใช่หลักฐาน Colab
ไฟล์ที่ส่งไม่ครบ/ขัดกันเป็น `invalid` และคำสั่งตรวจคืนผลไม่สำเร็จ; ไม่ส่งไฟล์เป็น `not_run`

ต้องมีหลักฐานอัปโหลด รัน เปิดต่อ ดาวน์โหลดที่ผู้ใช้ยืนยันว่าได้รับจริง และคืนใน runtime ใหม่
ก่อนถือว่า Colab acceptance ครบ การอนุมัติ release ไม่เปลี่ยนข้อเท็จจริงนี้
ดูขอบเขต patch และเกณฑ์เพิ่มเติมใน [แผน 0.2.1](docs/DEVELOPMENT_0_2_1_TH.md)

## นโยบายโครงการ

อ่าน[วิธีมีส่วนร่วม](CONTRIBUTING.md), [จรรยาบรรณ](CODE_OF_CONDUCT.md),
[การรายงานด้านความปลอดภัย](SECURITY.md), [การขอความช่วยเหลือ](SUPPORT.md)
และ[การกำกับดูแลโครงการ](GOVERNANCE.md)
ส่ง Issue และ PR เป็นภาษาไทยหรืออังกฤษได้
[สถานะการตั้งค่านโยบาย GitHub](docs/REPOSITORY_POLICIES_TH.md)
แยกกติกาที่เตรียมไว้จากการตั้งค่าที่เปิดใช้งานจริง

## ขอบเขตผู้ใช้และการพัฒนาจากรายงานวิจัย

เหมาะสำหรับผู้พัฒนาและผู้ตรวจเอกสารซื้อ CSV บนเครื่องเดียวที่ควบคุมได้
fixture ที่ล็อกตรวจ 100 เอกสาร; เพดาน parser ไม่ใช่ throughput หรือ SLA production
Agent code ต้องเชื่อถือได้ งานหลายเอกสารยังเรียงลำดับ ผู้ใช้ควบคุมสิทธิ์ backup และอายุเก็บข้อมูลเอง
Python API ใน 0.x ยังทดลอง ดู [ตัวอย่าง API](docs/PYTHON_API_TH.md),
[คู่มือผู้ดูแล](docs/MAINTAINER_RUNBOOK_TH.md), [quality gates](docs/QUALITY_TH.md),
[packaging](docs/PACKAGING_TH.md) และ [runtime benchmark](docs/BENCHMARK_RUNTIME_TH.md)
CI smoke ของ 0.3.0 บน Windows/macOS ผ่าน Python 3.10/3.12 แล้ว
และ smoke ไม่แทน full fault-injection suite ของทุกแพลตฟอร์ม
