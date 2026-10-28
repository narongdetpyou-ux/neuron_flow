# Neuron Flow 0.2.1 — candidate ยังไม่เผยแพร่

รับ CSV รายการซื้อหลายเอกสาร ตรวจข้อมูลและยอดเงินแยกรายใบ พร้อมรายงานย้อนถึงแถวต้นทาง
เอกสารที่ข้อมูลผิดหรือ Agent ล้มไม่ขัดขวางเอกสารอื่น และเปิด workspace เดิมเพื่อทำต่อได้
ใช้ Python 3.10 ขึ้นไปและ standard library บนเครื่องเดียว ใช้ THB ไม่ต้องมี API key

**สถานะ:** 0.2.1 เป็น candidate สำหรับตรวจในเครื่อง ยังไม่ได้รับอนุมัติหรือเผยแพร่
เพิ่มการรับงานก่อนประมวลผล การค้นหา batch ระหว่าง controller ทำงาน ความเข้ากันได้กับ workspace
0.2.0 และรายละเอียดข้อผิดพลาดเรื่องขนาด ข้อมูลตรวจปัจจุบันอยู่ใน `verification/v0_2_1/`
ให้อ่านจำนวน tests และผลจริงจากรายงาน ไม่ใช้จำนวนชุดใหม่ของรุ่นก่อนแทนผลของ candidate

รุ่น 0.2.0 เผยแพร่แล้วโดยมีการอนุมัติพร้อมข้อจำกัดว่า **Colab จริงยังไม่ได้ตรวจ**
หลักฐานเดิมใน `verification/v0_2_0/` และ `RELEASE_APPROVAL.json` ยังคงเป็นของ 0.2.0
การอนุมัตินั้นไม่อนุมัติ 0.2.1 โดยอัตโนมัติ สถานะ Colab ของรอบนี้ยังเป็น `not_run`

## เริ่มใช้ CSV

แตก ZIP candidate `dist/neuron_flow_v0.2.1.zip` แล้วเปิด terminal ในโฟลเดอร์ `neuron_flow`
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

## เปิด workspace 0.2.0 ด้วย 0.2.1

รองรับรูปแบบ workspace schema 1 รวมรูปแบบ 0.2.0 ที่ยังไม่มี marker ของ schema/execution
เมื่อสัญญา CSV, Agent definitions/versions และค่าควบคุมงานตรงกับ policy ที่รองรับ
ไม่เปลี่ยน identity รุ่นต้นทาง frozen payload หรือรายงานเดิม งานที่สร้างจาก 0.2.0
ยังระบุ provenance เป็น 0.2.0; งานใหม่ของ candidate ระบุ 0.2.1 ตามจริง
ไม่รับรองทุกรุ่นจากหมายเลข patch อย่างเดียว และข้อมูล/สัญญาที่ขัดกันยังถูกปฏิเสธ
การคืน backup ยังต้องใช้ absolute path เดิม ไม่รองรับย้าย workspace ไป path ใหม่ในรอบนี้

## สัญญาข้อมูล purchase-csv-v1

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
| `unit_price` | ตัวเลขไม่ติดลบ สูงสุด 1,000,000,000,000 บาท ทศนิยมไม่เกิน 2 ตำแหน่ง |
| `declared_total` | ตัวเลขไม่ติดลบ สูงสุด 10²² บาท ทศนิยมไม่เกิน 2 ตำแหน่ง ค่าเชิงตัวเลขต้องตรงกันทุกแถว |
| `currency` | THB และเหมือนกันทุกแถว |

ข้อความรหัสและคำอธิบายยาวไม่เกิน 500 ตัวอักษร หนึ่งใบมี 1–10,000 รายการตามฐานเดิม
เก็บค่าดิบไว้เสมอ `source_rows` / `row_number` นับบรรทัดจริงเริ่มต้น CSV record
โดยหัวตารางเริ่มที่ 1 ข้อความหลายบรรทัดจึงทำให้เลขแถวถัดไปขยับมากกว่าหนึ่ง
จำนวนเอกสาร = VALID + INVALID + ERROR; แถวที่จัดกลุ่มไม่ได้แสดงแยกจากจำนวนเอกสาร

## สถานะและยอดเงิน

| document_status | ความหมาย |
| --- | --- |
| VALID | ข้อมูลผ่าน Decimal คำนวณผ่านการตรวจซ้ำด้วย integer สตางค์ และตรง declared_total |
| INVALID | ข้อมูลผิดกติกาหรือยอดไม่ตรง มีเหตุผลตรวจกลับได้ |
| ERROR | ระบบยังยืนยันผลไม่ได้ เช่น Agent ล้มและหมดจำนวนครั้งที่ลอง |

`engine_status` แสดงผลประมวลผลแยกจากผลตรวจข้อมูล เช่น ใบ INVALID สามารถมี
engine_status เป็น SUCCEEDED ได้ ส่วน ERROR ยังคงแสดงในรายงานแม้เขียนรายงานสำเร็จ
ยอดรวมที่รับรอง (`certified_total`) นับเฉพาะ VALID ไม่มีการใช้ float คำนวณเงิน
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
ผูกงานกับสัญญาข้อมูล/schema/execution, Agent และ timeout รุ่น 0.2.0 → 0.2.1 ใช้ policy
ความเข้ากันได้ข้างต้น การเปลี่ยนสัญญาหรือรุ่นนอก policy ต้องคืน runtime ที่รองรับหรือใช้รหัสใหม่

## ขอบเขตการใช้งาน

- CSV ต้นทางไม่เกิน 16 MiB; ข้อความ workflow/Agent/report เดิมจำกัด 1 MiB
  เอกสารที่ใหญ่เกินขอบเขต engine ถูกแสดงเป็น ERROR โดยเอกสารอื่นยังทำต่อ
- 100 เอกสารแบบ 80 ถูก/20 ผิดเป็นขอบเขตชุดตรวจรับรอบนี้ ไม่ใช่อัตราข้อมูลจริงหรือเพดานจำนวนเอกสาร
- ใช้เครื่องเดียว ไม่มี OCR, PDF, ภาษี ส่วนลด การเรียนรู้เอง หรือการเลือกวิธีแก้จากภาษาธรรมชาติ
- worker เป็น process สำหรับจัดการค้าง/ล้ม ไม่ใช่ sandbox ของโค้ดที่ไม่เชื่อถือ และไม่มีเพดาน RAM ราย Agent
- ทดสอบใน Linux ตามรุ่น Python ที่บันทึกในรายงาน ยังไม่ได้ยืนยัน Windows/macOS หรือ Google Colab จริง

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
python tools/verify.py --output-dir verification/v0_2_1/baseline
python tools/build_acceptance_fixture.py --check
python tools/verify_current.py --output-dir verification/v0_2_1
python tools/build_delivery.py --candidate --output-dir dist
```

`verify.py` ตรวจ baseline เดิมแยกจาก `verify_current.py` ที่ค้น tests ของรุ่นปัจจุบัน
พร้อมเทียบ 100 เอกสารกับคำตอบที่ล็อกและเก็บหลักฐาน A01–A12 จำนวน baseline/new tests,
failures/errors/skipped และข้อมูล Python อ่านจาก `verification/v0_2_1/test_results.json`
กับรายงานย่อยจริง `--output-dir` แยกผลปัจจุบันจากหลักฐาน 0.2.0 ที่ไม่ควรเขียนทับ
`verify_v020.py` เก็บไว้เป็นเครื่องมือประวัติของ 0.2.0 ไม่ใช้ตรวจ candidate
คำตอบอ้างอิงและ SHA-256 ที่ล็อกอยู่ใน `acceptance/` ห้ามสร้างคำตอบจากผลของ validator รุ่นใหม่
การเปลี่ยนเกณฑ์ต้องบันทึกเหตุผลและตรวจกรณีที่ได้รับผลกระทบใหม่

`build_delivery.py --candidate` ตรวจแล้วสร้าง `dist/neuron_flow_v0.2.1.zip` พร้อมไฟล์ `.sha256`,
Notebook, `SHA256SUMS.txt`, `BUILD_STATUS.json` และ `delivery_checks.json` ใน output directory
มีการตรวจจากการแตก ZIP ใหม่ ไฟล์สถานะของ candidate ให้ดูใน output directory;
ไฟล์สถานะ/ผลตรวจ 0.2.0 ที่เก็บไว้ไม่ใช่ผลปัจจุบัน การสร้าง ZIP ไม่เผยแพร่ภายนอก
หากไม่ระบุ `--candidate` ต้องมีการอนุมัติที่ตรงรุ่น 0.2.1; approval ของ 0.2.0 ใช้แทนไม่ได้

มี CI สำหรับ Python 3.10/3.12 และ workflow เผยแพร่แบบ manual ซึ่งตั้ง `publish=false` เป็นค่าเริ่มต้น
ยังไม่มีผลรัน GitHub Actions จริงในรอบนี้ ช่องทาง native release assets ที่เคยพบ HTTP 401
ต้องตรวจสิทธิ์และการอัปโหลด/ดาวน์โหลดจริงภายหลัง การเพิ่ม workflow ไม่ได้ยืนยันว่าแก้สิทธิ์สำเร็จแล้ว

## ใช้ Notebook บน Google Colab

เปิด `START_COLAB.ipynb` ใน Colab runtime ใหม่ แล้วรันเซลล์ตามคำอธิบาย:
อัปโหลด ZIP candidate รุ่น 0.2.1 → ตรวจ SHA-256 ทุกไฟล์ → อัปโหลด CSV หนึ่งไฟล์ → รับงาน/รัน CLI
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
