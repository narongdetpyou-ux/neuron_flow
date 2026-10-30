# รับเอกสารและเชื่อมบริการภายนอก — development หลัง 0.3.0

ส่วนเพิ่มนี้อยู่ใน source branch ที่มีไฟล์คู่มือนี้ ยังไม่มีอยู่ใน ZIP ของ Release 0.3.0
คำสั่ง CSV เดิมและสัญญาการตรวจเงิน 46 สกุลยังใช้เหมือนเดิม

## รูปแบบที่รับ

| รูปแบบ | สิ่งที่ทำได้ | เงื่อนไข |
| --- | --- | --- |
| CSV | ใช้ข้อมูลเดิมทั้งไบต์ รวม BOM | เจ็ดคอลัมน์ตามสัญญาเดิม |
| TSV | แปลงตารางคั่นด้วย tab เป็น CSV | หัวตารางเดียวกับ CSV |
| JSON | รับ array ของ row objects | แต่ละ object มีเจ็ดช่องพอดี; ปฏิเสธ duplicate keys |
| Excel `.xlsx` | อ่าน worksheet เป็น CSV และเก็บชื่อ sheet/เลขแถว | เลือก sheet เมื่อมีหลาย sheet; ไม่รับสูตร, cell error หรือ macro |
| PDF ข้อความ | ดึงข้อความแยกหน้า พร้อมบรรทัดที่อาจเป็นเลขใบ/ยอดรวม | ตรวจทานและกรอก reviewed CSV ก่อนประมวลผล |
| PDF สแกน | render หน้าที่ไม่มีข้อความแล้วใช้ Tesseract OCR | `--ocr`; ต้องติดตั้ง OCR extra และ Tesseract |
| PNG, JPG/JPEG, TIF/TIFF | OCR ใบเสร็จ รวม TIFF หลายหน้า | `--ocr`; ตรวจทาน reviewed CSV |
| TXT | รับข้อความใบเสร็จหรือข้อความที่ export มาจาก OCR อื่น | UTF-8; ตรวจทาน reviewed CSV |

PDF ที่มีทั้งภาพกับข้อความจะ OCR เฉพาะหน้าที่ดึงข้อความไม่ได้ จึงต้องตรวจภาพต้นฉบับด้วย
ระบบยังไม่แยกรายการซื้อจาก layout ใบเสร็จทุกชนิดโดยอัตโนมัติ ไม่เดาสกุลเงินจาก `$`
ไม่เลือกระหว่าง subtotal/tax/grand total ให้เอง และไม่รับรองความถูกต้องของ OCR
บรรทัดที่พบเป็นเพียง `hints` พร้อมเลขหน้า/บรรทัด เก็บข้อความทั้งหมดไว้ใน manifest
การ review คือคำยืนยันของผู้ใช้งานบนเครื่อง ไม่ใช่ electronic signature หรือระบบกำหนดสิทธิ์หลายคน

## ติดตั้งเฉพาะส่วนที่ต้องใช้

จาก checkout นี้:

```bash
python -m pip install '.[pdf]'        # PDF ข้อความ
python -m pip install '.[excel]'      # Excel + XML hardening
python -m pip install '.[ocr]'        # ภาพและ PDF สแกน
python -m pip install '.[s3]'         # Amazon S3
python -m pip install '.[documents]'  # รวมส่วนเพิ่มทั้งหมด
```

OCR ต้องติดตั้ง Tesseract executable แยกจาก Python packages และติดตั้ง language data ที่ใช้
เช่น Linux/Colab ที่ติดตั้งแพ็กเกจระบบได้:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-tha
tesseract --list-langs
```

ใช้ `--language tha+eng` สำหรับไทยและอังกฤษเมื่อมีทั้งสอง language packs
การรัน CSV/TSV/JSON/TXT, Drive, Dropbox และ Sheets ไม่ต้องติดตั้ง Python dependency เพิ่ม
เครื่องที่ไม่ติดตั้ง extra จะได้รับ `DEPENDENCY_MISSING` เมื่อเรียก format นั้น

## รับไฟล์ ตรวจทาน และรัน

```bash
python -m neuron_flow adapters
python -m neuron_flow intake examples/intake/purchases.json --workspace batch_workspace
python -m neuron_flow intake purchases.xlsx --sheet Purchases --workspace batch_workspace
python -m neuron_flow intake receipt.pdf --ocr --language tha+eng --workspace batch_workspace
```

คำสั่งคืน `intake_id`, `bundle`, `status`, source SHA-256 และ normalized SHA-256
ข้อมูลตารางมีสถานะ `READY`; PDF/TXT/ภาพเป็น `REVIEW_REQUIRED`
รับไฟล์แล้วจะยังไม่เริ่ม batch หรือเรียกบริการภายนอกเพิ่ม

ตัวอย่างหลังรับใบเสร็จ โดยแทน `INTAKE_ID` ด้วยค่าที่คำสั่งส่งกลับ:

```bash
python -m neuron_flow intake-status INTAKE_ID --workspace batch_workspace
python -m neuron_flow intake-review INTAKE_ID examples/intake/receipt_reviewed.csv --reviewer operator --workspace batch_workspace
python -m neuron_flow intake-run INTAKE_ID --workspace batch_workspace
```

เปิด `original.bin` ด้วยนามสกุลเดิมที่ระบุใน `manifest.json` เพื่อตรวจภาพ/เอกสาร
อ่านข้อความแต่ละหน้าและ hints ใน manifest แล้วกรอก `review_template.csv` หรือสร้าง CSV ตามตัวอย่าง
ค่าที่กรอกต้องเป็นข้อมูลที่ตรวจจากใบเสร็จนั้นจริง ตัวอย่างทั้งหมดใน repository เป็นข้อมูลสังเคราะห์
การ review อาจผ่านขั้นรับข้อมูลแต่ตรวจยอดได้ INVALID ในขั้น batch ซึ่งต้องแยกกัน
หากแก้ reviewed CSV หลัง review แล้ว ระบบคืน `intake_id` ใหม่สำหรับ revision นั้น
ให้ใช้ ID ใหม่กับ `intake-run`; ต้นฉบับและรายงานของ ID ก่อนหน้ายังคงอยู่

`intake-run --submit-only` รับเข้าคิวก่อน และใช้ `batch-resume` กับ `batch_id` ที่คืนกลับมาทำต่อได้
`intake-run` ซ้ำใช้ batch เดิมและรายงานเดิม ไม่ต้องอัปโหลดต้นฉบับใหม่

## บริการที่เชื่อมต่อ

เลือกบริการจัดเก็บและตารางที่มีการใช้ข้ามประเทศและมี API ทางการ โดยจำกัดชุดเริ่มต้นให้ดูแลต่อได้
ไม่ได้ติดตั้ง connector ทุกบริการที่มี API และไม่ได้เชื่อมบัญชีของผู้ใช้โดยอัตโนมัติ

| บริการ | รับเข้า | ส่งออก | Credentials |
| --- | --- | --- | --- |
| Google Drive | ดาวน์โหลดไฟล์ด้วย file ID | — | OAuth access token |
| Google Sheets | snapshot range เป็น CSV; ปฏิเสธสูตร | เขียนทับ finite range แบบ RAW | OAuth access token |
| Dropbox | ดาวน์โหลด path หรือ `id:` | — | OAuth access token |
| Amazon S3 | ดาวน์โหลด object; เลือก VersionId ได้ | — | AWS SDK credential chain |

ตั้ง `GOOGLE_ACCESS_TOKEN` / `DROPBOX_ACCESS_TOKEN` ใน environment หรือ secret manager ของเครื่อง
ไม่วาง token ในไฟล์ config, command arguments, repository หรือ public evidence
ใช้ `--token-env CUSTOM_VARIABLE` เพื่อเปลี่ยนชื่อตัวแปรได้
OAuth login/refresh และการจัดการอายุ token เป็นหน้าที่ของผู้ให้ credentials ในรุ่นนี้
Drive ใช้ scope ที่ดาวน์โหลดไฟล์นั้นได้ เช่น `drive.readonly`; Sheets อ่านใช้ `spreadsheets.readonly`
และเขียนใช้ `spreadsheets`; Dropbox ใช้ `files.content.read`; S3 ใช้ `s3:GetObject`
หรือ `s3:GetObjectVersion` เมื่อระบุ version

```bash
python -m neuron_flow connector-fetch google-drive FILE_ID --filename receipt.pdf --workspace batch_workspace
python -m neuron_flow connector-fetch dropbox /receipts/receipt.pdf --filename receipt.pdf --workspace batch_workspace
python -m neuron_flow connector-fetch s3 receipts/receipt.pdf --bucket EXAMPLE_BUCKET --version-id VERSION_ID --filename receipt.pdf --workspace batch_workspace
python -m neuron_flow connector-fetch google-sheets SPREADSHEET_ID --range 'Purchases!A1:G100' --filename purchases.csv --workspace batch_workspace
```

Drive connector นี้รับไฟล์จริงใน Drive; Google Docs/Slides แบบ native ต้อง export ก่อน
Sheets connector อ่านด้วย `FORMULA` เพื่อไม่ยอมรับยอดเงินที่คำนวณหรือ cache ไว้อย่างเงียบ ๆ
range ต้องมีหัวตารางเจ็ดช่อง โดยใช้ values-only source
Cloud snapshot ที่รับสำเร็จเก็บ provenance/provider/locator และ SHA-256 ของไบต์ที่ใช้จริง
การดาวน์โหลดใหม่หลัง cloud source เปลี่ยนจะได้ identity ใหม่

ส่งรายงานไป Google Sheets เป็นคำสั่งแยกที่เขียนจริงเมื่อผู้ใช้งานเรียก:

```bash
python -m neuron_flow sheets-publish report.csv SPREADSHEET_ID --range 'Report!A1:G2'
```

range ต้องระบุ sheet, ต้นแถว/คอลัมน์ และปลายแถว/คอลัมน์ให้มีขนาดเท่าตารางพอดี
ตัวอย่าง `A1:G2` ใช้กับตาราง 7 คอลัมน์ 2 แถวรวม header เท่านั้น ให้ปรับตามรายงานจริง
ใช้ `RAW` ส่งค่าทั้งหมดเป็นข้อความ จึงไม่ทำให้ description ที่ขึ้นต้น `=` กลายเป็นสูตร
เขียนทับ range เดิมได้ผลเดิม ไม่มี append อัตโนมัติ และไม่ล้างข้อมูลนอก range
หากเปลี่ยนขนาดรายงาน ต้องจัดการช่วงเก่าที่เหลือเอง
ไม่ส่งรายงานออกหลัง batch โดยอัตโนมัติ และไม่อ้างธุรกรรมร่วมระหว่าง SQLite กับ cloud

## หลักฐาน การกู้คืน และขอบเขต

`workspace/intakes/<intake_id>/` เก็บ `original.bin`, `manifest.json`, `normalized.csv`
หรือ `review_template.csv` และ `approval.json` หลัง review
บันทึก bundle ด้วย temporary directory แล้ว rename และบันทึก review แบบ exclusive atomic link
ตรวจ SHA-256 ต้นฉบับและ normalized CSV ทุกครั้งก่อนใช้
review ผูก hash กับ manifest และ reviewed CSV; batch ID เป็น `intake_<intake_id>`
ข้อมูลเดิมที่ขัดกับ SHA จะถูกปฏิเสธ ไม่เขียนทับเพื่อทำให้ผ่าน

รายงาน batch ยังคง `summary.csv`, `details.json`, `source.csv` ตามสัญญาเดิม
`source.csv` ของ non-CSV intake เป็น normalized/reviewed CSV ไม่ใช่ต้นฉบับ PDF/Excel
ใช้ `source_record_mapping` ใน intake manifest เชื่อม normalized row กับ JSON index,
worksheet row หรือ ordinal ของ CSV/TSV data record และสำรองทั้ง workspace รวม `intakes/`
การสำรองเฉพาะ SQLite จะไม่รวมต้นฉบับ PDF/ภาพและหลักฐาน review

ขีดจำกัด: source/normalized CSV 16 MiB, ตาราง 100,000 data rows,
PDF/ภาพไม่เกิน 50 หน้า/frames, ภาพ/render ไม่เกิน 25 ล้าน pixels,
ข้อความรวม 2 ล้านตัวอักษร, workbook ที่ขยายแล้วไม่เกิน 64 MiB/2,000 ZIP members,
OCR timeout 30 วินาทีต่อหน้า, HTTP timeout 30 วินาที
ตัวเลข JSON ที่ exponent ทำให้ decimal string ขยายเกิน source limit ถูกปฏิเสธก่อนสร้าง string
HTTP redirect ถูกปฏิเสธและไม่ส่ง token ข้าม host; error แสดง status/retryable โดยไม่แสดง provider body
ไม่ retry network อัตโนมัติ ให้ตรวจผลปลายทางก่อนเรียกส่งออกซ้ำหลัง timeout
SDK S3 ตั้ง timeout และปิด retries ที่ซ่อนอยู่ใน client ที่ระบบสร้างเอง

parsers/OCR ทำงานบนเครื่องเดียวและยังไม่มี security sandbox หรือ memory/process isolation
ขีดจำกัดเหล่านี้ไม่ใช่ production SLA หรือหลักประกันต่อ PDF/ZIP ที่มุ่งโจมตี parser
ยังไม่มี tax/discount/FX engine, `.xls`/`.xlsm`, HEIC หรือ e-invoice XML
ชุดทดสอบ API ใช้ fake HTTP และ S3 clients; ไม่ถือเป็นหลักฐานว่าบัญชี cloud จริงเปิดสิทธิ์ครบแล้ว
สถานะ Actual Colab acceptance ของส่วนเพิ่มนี้ยัง `not_run`

## API สำหรับต่อยอด

```python
from neuron_flow.connectors import fetch_source
from neuron_flow.intake import stage_document, review_document, run_document

data, origin = fetch_source("dropbox", "/receipts/receipt.pdf")
staged = stage_document("batch_workspace", data, "receipt.pdf", origin=origin)
# ตรวจ original.bin/manifest.json และเตรียม reviewed CSV ก่อนเรียก review_document
```

`prepare_document()` เป็น adapter boundary ที่ไม่มี network calls
`fetch_source()` คืน `(bytes, provenance)` และรับ transport/client สำหรับทดสอบ
`stage_document()` เป็นจุดบันทึกหลักฐานก่อนส่งเข้า batch
ยังเป็น Python API แบบทดลอง ควร pin source commit ที่ใช้

## เอกสารทางการที่ใช้ตรวจ API

- [Google Drive files.get](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get)
- [Google Sheets values.get](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get)
- [Google Sheets values.update](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update)
- [Dropbox API v2](https://docs.dropboxapi.com/)
- [Dropbox official Python SDK: download headers and protocol](https://github.com/dropbox/dropbox-sdk-python/blob/main/dropbox/dropbox_client.py)
- [Amazon S3 get_object](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html)
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html)
- [pypdfium2 API](https://pypdfium2.readthedocs.io/en/stable/python_api.html)
- [Tesseract command line](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
