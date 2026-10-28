# Benchmark เวลาและหน่วยความจำ

ใช้ Python 3.10 ขึ้นไปและ standard library เท่านั้น ไม่ต้องติดตั้งแพ็กเกจเพิ่ม
รันจากโฟลเดอร์โปรเจกต์:

```bash
.venv/bin/python -B tools/benchmark.py --output-dir /tmp/neuron-benchmark
```

ค่าเริ่มต้นวัด 5 งานกับเอกสารที่มี 10, 100, 1,000 และ 10,000 รายการ:

- `read_csv_bytes`: อ่าน UTF-8 CSV และจัดกลุ่มเอกสาร
- `validate_document`: ตรวจข้อมูลและเตรียม invoice
- `compute_document`: คำนวณยอดด้วย Decimal
- `verify_document`: ตรวจยอดซ้ำด้วยจำนวนเต็มหน่วยสตางค์
- `csv_pipeline`: รวมทั้งสี่ขั้นตอนในหน่วยความจำ

ข้อมูลสังเคราะห์แต่ละขนาดเป็นเอกสาร VALID หนึ่งใบ มีจำนวนและราคาสินค้าหลากหลาย
สคริปต์ตรวจผลกับยอดอ้างอิงที่สร้างด้วยเลขจำนวนเต็มก่อนวัดและหลังวัด
ไม่ได้ใช้เวลาเริ่ม process หรือสร้างข้อมูลมารวมในเวลาของฟังก์ชัน

## วิธีวัด

แต่ละคู่ฟังก์ชัน/ขนาดรันใน subprocess ใหม่ มี warmup 2 ครั้ง แล้วปรับจำนวนครั้งต่อ sample
ให้ใกล้ 25 ms โดยไม่เกิน 1,000 ครั้ง หากฟังก์ชันหนึ่งครั้งใช้เวลานานกว่าเป้าหมายจะวัดครั้งเดียว
เก็บ 7 samples ด้วย `perf_counter_ns` โดยไม่ได้เปิด `tracemalloc`
คอลัมน์เวลาเป็น median/min/max ของ **เวลาเฉลี่ยต่อครั้งในแต่ละ sample**
ไม่ใช่ percentile ของ latency รายครั้ง เวลารวมการคืนหน่วยความจำของผลลัพธ์ตามปกติ
ยังเปิด cyclic GC ระหว่างเรียก แต่การสั่งเก็บขยะก่อนแต่ละ sample อยู่นอกช่วงจับเวลา

หน่วยความจำวัดแยกจากเวลา:

- **Python KiB**: ค่า peak สูงสุดจากการวัด 3 ครั้งด้วย `tracemalloc`
  เป็นหน่วยความจำ Python ที่จัดสรรเพิ่มระหว่างเรียกหนึ่งครั้ง โดยยังถือผลลัพธ์ไว้ขณะอ่าน peak
  ไม่รวมข้อมูลที่เตรียมไว้ก่อนวัด และไม่ใช่ RAM ทั้งหมดของ process
- **RSS MiB**: peak RAM ของ worker process ทั้งตัวจาก `resource.getrusage`
  อ่านก่อนเปิด `tracemalloc` รวม interpreter, imports, ข้อมูลเตรียมไว้ และรอบจับเวลา
  ไม่ใช่หน่วยความจำเพิ่มเฉพาะฟังก์ชัน บนระบบที่ไม่รองรับจะแสดง `n/a`

1 KiB = 1,024 bytes; 1 MiB = 1,048,576 bytes
การวัดตรงนี้ไม่รวม Runtime workers, IPC, SQLite และการอ่าน/เขียนไฟล์รายงาน
ขนาดข้อมูลที่ฟังก์ชันรับได้โดยตรงไม่ได้ยืนยันว่าจะผ่านขนาด message ของ Runtime
ผลขึ้นกับ CPU, Python, GC และภาระเครื่อง ควรเปรียบเทียบบนเครื่องและ settings เดียวกัน

## เลือกงานและบันทึกผล

```bash
.venv/bin/python -B tools/benchmark.py \
  --sizes 100 1000 --cases compute_document csv_pipeline \
  --repeats 9 --memory-repeats 3 \
  --output-dir /tmp/neuron-benchmark-selected
```

ผลบันทึกเป็น `benchmark.txt`, `benchmark.csv` และ `benchmark.json`
JSON เก็บ samples, settings, เวอร์ชัน Python/โปรเจกต์ และคำอธิบายวิธีวัด
เลือกโฟลเดอร์ผลลัพธ์ใหม่ในการรันครั้งถัดไป เพราะสคริปต์ไม่เขียนทับไฟล์ผลเดิม
ดูตัวเลือกทั้งหมดด้วย `python tools/benchmark.py --help`
