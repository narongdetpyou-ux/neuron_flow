# ทดสอบ Edge Cases และข้อมูลจำลอง

รันจากโฟลเดอร์โปรเจกต์ด้วย Python standard library ไม่ต้องติดตั้ง dependency เพิ่ม:

```bash
.venv/bin/python -B tools/edge_cases.py --output-dir /tmp/neuron-edge-cases
```

เลือกโฟลเดอร์ใหม่ทุกครั้งเพื่อไม่เขียนทับหลักฐานเดิม สคริปต์สร้าง `mock-data/`,
`manifest.json` ที่มี SHA-256, `results.json` และ `failures.json`
CLI แต่ละกรณีใช้ workspace ของตัวเองใต้โฟลเดอร์ผลลัพธ์ ไม่แตะข้อมูลใช้งานจริง
ตั้ง seed ได้ด้วย `--seed` และจำนวน mutation ด้วย `--mutations` (ค่าเริ่มต้น 1,500)

## สิ่งที่ตรวจ

- CSV: UTF-8/BOM, NUL, RTL, emoji, quotes/newlines, header/จำนวนคอลัมน์ผิด,
  duplicate item, แถวไม่มี document ID, ข้อมูลถูก/ผิดปะปนกัน
- จำนวน/ราคา/ยอด: ศูนย์, ติดลบ, ทศนิยมผิดรูปแบบ, NaN/Infinity, เลขยาวมาก,
  ยอดไม่ตรง, ขอบเขต 10,000 และ 10,001 รายการ รวมเลขจำนวนสูงสุดตามสัญญา
- ไฟล์เกิน 16 MiB, workflow เกินขนาด message โดยให้เอกสารปกติใน batch ยังทำงานต่อ
- JSON และ CLI: null/list/scalar, JSON เสีย, duplicate fields, UTF-8 เสีย,
  nesting ลึก, ชนิดข้อมูลผิด และ `events --after` ที่ขอบ signed int64

ฟังก์ชัน CSV ตรวจ source hash, ไม่มีแถวหาย/ซ้ำ, ไม่แก้ข้อมูลต้นฉบับ และเทียบยอด VALID
กับเลขจำนวนเต็มหน่วยสตางค์ CLI ตรวจ exit code, JSON error, counts และ artifact hashes
รวมทั้ง `source.csv` ที่ส่งมอบต้องตรงกับ mock input ทุก byte
แต่ละ CLI มี timeout; หากค้างจะหยุดเฉพาะกลุ่ม process ที่สคริปต์สร้าง

การได้ INVALID, `CsvInputError` หรือ document ERROR ตามขนาดที่จำกัดไว้อยู่แล้ว
ไม่ถือว่า crash กรณีที่ไม่คาดหมาย เช่น traceback, timeout, ยอดผิด หรือไฟล์เปลี่ยน
จะถูกบันทึกใน `failures.json` และทำให้สคริปต์คืน exit code 1
Mutation tests ตรวจความทนทานและ invariants ไม่ใช่หลักฐานว่าครอบคลุม input ทุกแบบ

## จุดที่ตรวจพบในรุ่น 0.2.1 ปัจจุบัน

```bash
.venv/bin/python -B -m neuron_flow events nonexistent \
  --after 9223372036854775808 --workspace /tmp/neuron-events-overflow
```

`--after` รับ integer ที่เกินช่วง SQLite signed int64 แล้วหลุดเป็น `OverflowError`
พร้อม traceback ช่วงที่ SQL รองรับคือ −9,223,372,036,854,775,808 ถึง
9,223,372,036,854,775,807 สคริปต์ทดสอบคาดหวังการปฏิเสธด้วย JSON/exit code 2
และยังรายงานกรณีนี้เป็น **fail** จนกว่าจะมีการแก้โค้ดหลัก ไม่ได้กลบ exception
หรือปรับ expected result ให้ crash กลายเป็นผ่าน

ชุดทดสอบเดิมยังรันแยกได้ด้วย `tools/verify_current.py --output-dir <new-directory>`
เพื่อทดสอบการกู้คืนจาก worker/controller crash และกรณีค้างที่มีอยู่แล้ว
