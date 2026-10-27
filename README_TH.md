# Neuron Flow 0.1.0

ต้นแบบระบบจากแนวคิด Dendrite, Soma, Axon, Axon terminal และ Synapse
รับข้อมูล → จัดงานให้ Agent → ตรวจผล → ลงมือทำ → รับผลยืนยันกลับ

ใช้ Python 3.10 ขึ้นไป และ standard library เท่านั้น ไม่ต้องติดตั้งแพ็กเกจ ไม่ต้องใช้ API key
Agent ตัวอย่างเป็นฟังก์ชันประมวลผลแบบกำหนดขั้นตอนชัดเจน สามารถเพิ่ม Agent ชนิดอื่นภายหลังได้

## เริ่มทดลอง

แตกไฟล์ ZIP แล้วเปิด terminal ในโฟลเดอร์ `neuron_flow` ที่มีไฟล์นี้ จากนั้นรัน:

```bash
python -m neuron_flow demo
```

ผลที่ถูกต้อง: `status` เป็น `SUCCEEDED` และขั้น `verify` แสดง `total` เท่ากับ `310.70`
โปรแกรมจะแสดงตำแหน่งรายงานที่บันทึกจริงใน `receipt.path` พร้อม SHA-256 ของไฟล์

ตัวอย่างนี้อ่านสมุด 2 เล่ม × 125.50 = 251.00 และปากกา 3 ด้าม × 19.90 = 59.70
รวม 310.70 บาท ใช้ Decimal ในตัวคำนวณ และใช้จำนวนสตางค์แบบ integer ตรวจซ้ำแยกอีกวิธี

สำหรับโทรศัพท์: เปิด `START_COLAB.ipynb` ใน Google Colab แล้วรันเซลล์ตามลำดับ
เซลล์แรกจะให้อัปโหลด ZIP ชุดนี้ ไม่ต้องคัดลอกโค้ดของระบบเอง
Notebook ใช้ subprocess เรียกไฟล์ Python เพื่อรองรับการสร้าง process ของ Agent อย่างถูกต้อง

## โครงห้าส่วนที่ทำงานจริง

| ส่วน | หน้าที่ในโค้ด | ตำแหน่ง |
|---|---|---|
| Dendrite | รับข้อมูล เลือก workflow ที่รองรับ ตรวจแผน และเก็บงานใหม่หรือคืนงานเดิม | `neuron_flow/engine.py`, class `Dendrite` |
| Soma | จัดคิว จำกัด process ตรวจผล จัดการ timeout/crash และกลับมาทำงานต่อ | `neuron_flow/engine.py`, class `Soma` |
| Axon | ส่งข้อมูลเข้าและผลของ dependency ให้ Agent ที่ลงทะเบียนไว้ | `neuron_flow/engine.py`, class `Axon` |
| Axon terminal | บันทึกรายงานแบบ atomic อ่านไฟล์กลับมาตรวจ และคืนใบยืนยัน | `neuron_flow/engine.py`, class `AxonTerminal` |
| Synapse | ตรวจสัญญาข้อมูล ตรวจผล และกำหนดผู้รับ event ที่เกี่ยวข้อง | `neuron_flow/engine.py`, class `Synapse` |

SQLite เก็บงาน สถานะ ผลที่ผ่านการตรวจ และประวัติ event
Agent ทำงานใน process ลูกที่ใช้ซ้ำได้ ค่าเริ่มต้นสูงสุด 3 process และแต่ละ process รับงานครั้งละหนึ่งงาน
มีตัวเฝ้าดูเพื่อหยุด process ลูกเมื่อ controller ตาย

## ส่งข้อมูลของตัวเอง

แก้รายการใน `examples/invoice.json` แล้วใช้:

```bash
python -m neuron_flow invoice examples/invoice.json --job-id my_invoice
```

หากละ `--job-id` ระบบจะสร้างรหัสจากเนื้อหาข้อมูลเพื่อจับงานเดิมซ้ำ
`unit_price` ให้ใส่เป็นข้อความ เช่น `"19.90"` เพื่อรักษาค่าทศนิยม
จำนวนต้องเป็นจำนวนเต็มบวก ราคาไม่ติดลบ และมีทศนิยมไม่เกินสองตำแหน่ง
ตัวอย่างนี้คำนวณยอดรวมของรายการ ยังไม่มีภาษี ส่วนลด OCR หรือการอ่าน PDF/ภาพ

เมื่อแก้ข้อมูลแล้วต้องใช้ job id ใหม่ ระบบปฏิเสธการใช้รหัสเดิมกับข้อมูลหรือแผนที่เปลี่ยนไป
การรันข้อมูลและรหัสเดิมอีกครั้งใช้ผลที่ตรวจผ่านแล้ว และไม่เขียนรายงานเดิมซ้ำ

## รันแผนที่กำหนดเอง

```bash
python -m neuron_flow run examples/workflow.json --workspace my_run --workers 3
python -m neuron_flow status invoice_from_file --workspace my_run
python -m neuron_flow events invoice_from_file --workspace my_run
```

แต่ละ step ประกอบด้วย:

| ฟิลด์ | ความหมาย | ค่าเริ่มต้น |
|---|---|---|
| `id` | หมายเลขขั้นที่ไม่ซ้ำในงานเดียวกัน | ต้องระบุ |
| `agent` | ความสามารถที่ลงทะเบียนไว้ | ต้องระบุ |
| `depends_on` | ขั้นที่ต้องสำเร็จก่อนจึงเริ่มได้ | `[]` |
| `params` | ค่าที่ส่งให้ Agent | `{}` |
| `timeout_s` | เวลาทำงานสูงสุดต่อครั้ง หลัง worker พร้อมใช้งาน | 5 วินาที |
| `max_attempts` | จำนวนครั้งทั้งหมด รวมครั้งแรก | 2 |
| `retry_delay_s` | เวลารอก่อนลองใหม่ | 0.05 วินาที |

ระบบรับได้สูงสุด 1,000 ขั้นต่อ workflow, process พร้อมกัน 1–32 ตัว,
timeout 0.05–3,600 วินาที และจำนวนครั้ง 1–5 ครั้ง
ข้อความ JSON รวม envelope และรายงานแต่ละไฟล์จำกัดประมาณ 1 MiB
หากรวมผลจนเกินขนาดรายงาน ระบบจะแจ้ง `DELIVERY_FAILED` และยังเก็บผลแต่ละขั้นใน SQLite

แผนต้องไม่มีวงจร dependency และต้องอ้างถึงขั้นที่มีอยู่จริง
Agent ที่มีให้คือ `extract_invoice`, `calculate_invoice`, `verify_invoice` และ `echo`
`extract_invoice` ปรับข้อมูลรายการให้เป็นรูปแบบกลาง ไม่ได้อนุมานข้อมูลที่ไม่มีในต้นฉบับ

## เมื่อมีความผิดพลาด

| เหตุการณ์ | พฤติกรรม |
|---|---|
| Agent ค้างเกินเวลา | หยุด process นั้น สร้างตัวแทนเมื่อจำเป็น และลองใหม่ภายในงบครั้ง |
| process ลูกตายจริง | controller เก็บสาเหตุและลองงานนั้นใหม่ |
| Agent แจ้ง `TransientAgentError` | รอแล้วลองใหม่ตามงบครั้ง |
| ข้อมูลผิด / programming error / ผลไม่ผ่านตัวตรวจ | บันทึกความผิดพลาดและไม่ลองข้อมูลเดิมซ้ำโดยอัตโนมัติ |
| ขั้นต้นทางล้มเหลว | ขั้นที่จำเป็นต้องใช้ผลนั้นเป็น `BLOCKED`; งานสาขาอื่นยังทำต่อ |
| controller หยุดกะทันหัน | เปิด workspace เดิมแล้ว resume; เก็บผลที่สำเร็จแล้วไว้และนับความพยายามที่ถูกขัดจังหวะด้วย |
| บันทึกรายงานไม่ได้ | `DELIVERY_FAILED`; resume เพื่อลองการส่งมอบอีกครั้งโดยไม่ประมวลผลขั้นที่สำเร็จแล้วใหม่ |
| มีไฟล์ชื่อเดียวกันแต่เนื้อหาต่าง | เก็บไฟล์เดิมไว้และรายงาน conflict |
| เปิด controller สองตัวใน workspace เดียว | ปฏิเสธตัวที่สองเพื่อป้องกันงานซ้ำ |

คำสั่งทำต่อ:

```bash
python -m neuron_flow resume invoice_from_file --workspace my_run
```

สถานะของขั้น: `PENDING`, `RUNNING`, `RETRY_WAIT`, `SUCCEEDED`, `FAILED`, `BLOCKED`
สถานะของงาน: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `DELIVERY_FAILED`
งานที่มีขั้นล้มเหลวจะมีรายงานระบุ `FAILED` ชัดเจน แม้สามารถบันทึกรายงานความล้มเหลวนั้นได้สำเร็จ

CLI คืน exit code 0 เมื่องานสำเร็จ/อ่านสถานะได้, 1 เมื่องานหรือการส่งมอบล้มเหลว,
และ 2 เมื่อคำสั่ง ข้อมูลตั้งต้น หรือการเปิดระบบไม่ถูกต้อง

## การส่งต่อและประวัติ

ผลของแต่ละขั้นส่งเฉพาะขั้นที่ประกาศ dependency นั้น
event มีรายชื่อผู้รับ เช่น `soma`, `monitor`, `terminal`, `step:calculate`
ผู้สังเกตอ่านเฉพาะข้อความของตัวเองได้ และใช้ `sequence` เป็นตำแหน่งอ่านครั้งถัดไป:

```bash
python -m neuron_flow events invoice_from_file --workspace my_run --recipient step:calculate --after 0
```

นี่เป็น event log แบบเก็บถาวรและอ่านตามผู้รับ ไม่มีระบบ subscriber บนเครือข่ายในรุ่นนี้
ไม่มีการส่ง event ทุกข้อความให้ Agent ทุกตัว

## เพิ่ม Agent

สร้างโมดูล Python ที่ import ได้ เช่น `my_agents.py` ในโฟลเดอร์โปรเจกต์:

```python
def uppercase(message):
    return {"text": message["input"]["text"].upper()}

def validate_uppercase(message, result):
    expected = {"text": message["input"]["text"].upper()}
    if result != expected:
        raise ValueError("Incorrect uppercase result")
```

แล้วสร้างไฟล์ `run_custom.py`:

```python
from neuron_flow import Runtime, AgentDefinition
from my_agents import validate_uppercase

def main():
    agent = AgentDefinition("uppercase", "my_agents:uppercase", validate_uppercase, version="1")
    with Runtime("custom_run", agents=[agent]) as runtime:
        runtime.submit({
            "job_id": "uppercase_example",
            "input": {"text": "hello"},
            "steps": [{"id": "convert", "agent": "uppercase"}],
        })
        print(runtime.run("uppercase_example"))

if __name__ == "__main__":
    main()
```

รัน `python run_custom.py` จะได้ผล `HELLO`
ฟังก์ชัน Agent รับ dict ที่มี `input`, `params`, `dependencies`, `attempt`, `job_id`, `step_id`, `work_id`
และต้องคืนข้อมูลที่แปลงเป็น JSON ได้
ตัวตรวจต้องทำงานสั้นและตรวจอย่างเดียว: คืน `None`/`True` เมื่อผ่าน หรือ raise เมื่อไม่ผ่าน
การคืน `False` หรือแก้ผลลัพธ์ระหว่างตรวจจะถูกปฏิเสธ
เพิ่ม `version` เมื่อเปลี่ยนความหมายของ Agent หรือตัวตรวจ เพื่อไม่ให้ผลเก่าถูกนำกลับมาใช้อย่างเงียบ ๆ
ต้องใช้ main guard ดังตัวอย่าง และวางฟังก์ชัน Agent ในโมดูลที่ import ได้ ไม่ประกาศเป็น lambda หรือฟังก์ชันในเซลล์ notebook

## ตรวจสอบซ้ำ

```bash
python -m unittest discover -s tests -v
python tools/verify.py
```

คำสั่งที่สองรันทดสอบทั้งหมด ตรวจ syntax และเรียก CLI สองครั้งบน workspace ใหม่
ตรวจผลรวม ตรวจ hash ของไฟล์ และตรวจว่าครั้งที่สองไม่ทำงานหรือเขียนรายงานเดิมซ้ำ
ผลตรวจที่ส่งมาพร้อมชุดนี้อยู่ใน `verification/VERIFICATION_TH.md`,
`verification/test_results.json` และ `verification/tests.log`

## ขอบเขตของรุ่นนี้

เป็นต้นแบบ workflow ที่ทำงานบนเครื่องเดียว ใช้โครงห้าส่วนเป็นการออกแบบซอฟต์แวร์
การเลือกแผนอัตโนมัติรองรับข้อมูล invoice แบบมีโครงสร้าง ส่วนงานชนิดอื่นใช้ workflow และ Agent ที่ลงทะเบียนเพิ่ม
ระบบยังไม่มีการเรียนรู้เองหรือสร้างวิธีแก้ปัญหาใหม่จากภาษาธรรมชาติ

การแยก process ช่วยจัดการงานค้าง แต่ไม่ใช่ sandbox สำหรับโค้ดที่ไม่เชื่อถือ และยังไม่ได้จำกัด RAM ต่อ Agent
ตัวตรวจรันใน controller จึงต้องเป็นฟังก์ชันที่เชื่อถือได้และไม่ค้าง
timeout เป็นขอบเขตเวลางานที่ตรวจด้วยรอบ scheduler ไม่ใช่ hard real-time guarantee
การเริ่ม worker อาจใช้เวลาเพิ่มเติม และไม่รวมอยู่ใน timeout ของงาน

การไม่ทำการกระทำซ้ำรับรองเฉพาะการบันทึกรายงานภายในที่ให้มา
Agent แบบเพิ่มเองควรประมวลผลข้อมูลและคืนผล; หากเรียกบริการภายนอกหรือสร้างผลข้างเคียง
ต้องออกแบบการใช้ `work_id`/รหัสธุรกรรมและการยืนยันผลของบริการนั้นเพิ่มเติม
การ resume เป็นคำสั่งที่ผู้ใช้เรียก ยังไม่มี service ภายนอกคอยเปิด controller ใหม่อัตโนมัติ
ทดสอบจริงบน Linux กับ Python ตามที่ระบุในรายงานตรวจ ส่วน Windows/macOS ยังไม่ได้ทดสอบในรอบนี้
