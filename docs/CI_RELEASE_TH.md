# CI และการออก Release

ชุดนี้เพิ่ม workflow สำหรับตรวจโค้ดและเตรียมเผยแพร่รุ่นถัดไป การเพิ่มไฟล์ workflow ไม่ได้เผยแพร่เวอร์ชันใดในตัวเอง
ผลตรวจในเครื่องไม่ใช่หลักฐานว่ารันบน GitHub Actions หรือ Google Colab จริงแล้ว

## ตรวจโค้ดอัตโนมัติ

`.github/workflows/ci.yml` ทำงานเมื่อ push หรือเปิด/อัปเดต pull request โดยให้สิทธิ์ `contents: read` เท่านั้น
ใช้ Linux และ Python 3.10/3.12 ตรวจชุดคำตอบอ้างอิง 100 เอกสารที่ล็อกไว้ รันทดสอบทั้งหมดใน `tests/`
ตรวจตัวป้องกันการเผยแพร่แบบ offline และ parse โค้ดกับเซลล์ Notebook
ไม่มีคำสั่ง commit, push, สร้าง tag หรือเผยแพร่ Release ใน workflow นี้

แต่ละ job ใช้ checkout ใหม่ของ runner และไฟล์หลักฐานชั่วคราวใน `runner.temp`
การทดสอบที่สร้างหรือแก้รายงานจึงไม่บันทึกผลเหล่านั้นกลับเข้า repository
การตรวจ syntax ของ Notebook ยังไม่ยืนยันการอัปโหลด รัน ดาวน์โหลด หรือคืน backup บน Colab จริง

## เตรียม candidate ด้วยการสั่งเอง

`.github/workflows/release.yml` ใช้เฉพาะ `workflow_dispatch` ไม่มี trigger จาก push, pull request หรือ tag
เริ่มในหน้า Actions → Manual release → Run workflow โดยระบุ:

1. `tag`: tag ที่มีอยู่แล้ว เช่น `v0.2.1`
2. `expected_commit`: commit SHA เต็ม 40 ตัวที่ผู้สั่งงานตรวจและอนุมัติให้ใช้ ต้องเป็น commit ที่ tag ชี้ถึงจริง
3. `publish`: ค่าเริ่มต้น **false** ให้คงค่านี้เมื่อต้องการตรวจและดาวน์โหลด candidate เท่านั้น

Workflow ตรวจ tag, commit, `neuron_flow.__version__` และเวอร์ชันใน `pyproject.toml` ให้ตรงกัน
จากนั้นตรวจ regression และสร้าง candidate ด้วย:

```bash
python tools/build_delivery.py --candidate --output-dir <โฟลเดอร์ปลายทาง>
```

ตัว builder ตรวจจากการแตก ZIP ใหม่ก่อนสำเร็จ ไฟล์จะถูกเก็บเป็น workflow artifact
ชื่อ `neuron-flow-<version>-<commit>` นาน 14 วัน ไม่มีการเรียกคำสั่งเผยแพร่เมื่อ `publish` เป็น false
การสร้าง candidate ไม่ใช้การอนุมัติของ 0.2.0 มาอนุมัติรุ่นใหม่

สำหรับงานที่ยังพัฒนาและยังไม่สร้าง tag ให้ใช้คำสั่ง candidate ในเครื่องก่อน
ควรรวม release approval และ notes ที่ต้องใช้ใน commit สุดท้ายก่อนสร้าง tag สำหรับเผยแพร่
workflow นี้ไม่ย้าย tag: หาก tag ชี้ commit ที่ไม่มีการอนุมัติ การเลือก `publish: true` จะถูกปฏิเสธ

## เผยแพร่เมื่อได้รับอนุมัติรุ่นใหม่แล้ว

ก่อนเลือก `publish: true` ต้องมี `RELEASE_APPROVAL.json` ใน commit ที่ tag ชี้ถึง โดย `version` ตรงกับรุ่นนั้น
และ `release_approved` เป็น boolean true กับ `decision: release_with_disclosed_known_limitation`
ตรงกติกาของ builder พร้อม `RELEASE_NOTES.md` ที่หัวเรื่องระบุเวอร์ชันเดียวกัน
การสั่ง workflow ต้องระบุ `expected_commit` เดิมที่ตรวจแล้วด้วย การอนุมัติในไฟล์จึงแยกจากการอนุมัติ source commit
ที่ระบุในการสั่ง workflow ไม่ใส่ SHA ของ commit ตัวเองกลับเข้าไฟล์อนุมัติจนเกิดการอ้างอิงตัวเอง

เฉพาะ publish job ได้ `contents: write` และใช้ `github.token` ชั่วคราวของ GitHub Actions สำหรับ native Release Assets
ไม่ต้องใส่ PAT ลงใน repository ตัว workflow ใช้ environment ชื่อ `release`:
หาก repository ตั้ง required reviewers หรือกติกาของ environment นี้ไว้ GitHub จะใช้กติกานั้นก่อนเปิด job
การเพิ่ม workflow นี้ไม่ได้ตั้ง reviewers หรือเปลี่ยนการตั้งค่า repository ให้เอง

เมื่อขอเผยแพร่ workflow เรียก builder แบบปกติที่ต้องผ่านการอนุมัติและ `release_ready`
แทน `--candidate` และตรวจว่า `delivery_checks.json` ยืนยันการอนุมัติของ build นั้นด้วย

ก่อนเผยแพร่ ระบบจะ:

- อ่าน build artifact ที่ผ่านการตรวจแล้ว ตรวจ SHA-256 ของไฟล์และตรวจ remote tag กับ commit ที่อนุมัติอีกครั้ง
- สร้างหรือใช้ Release **draft** เดิมเฉพาะเมื่อ notes และไฟล์ที่มีอยู่ตรงกัน
- อัปโหลด ZIP, checksum ของ ZIP, `SHA256SUMS.txt`, `START_COLAB.ipynb`, `delivery_checks.json` และ `publication_attestation.json`
- ตรวจ digest จาก GitHub หรือดาวน์โหลดกลับมาตรวจ SHA-256 หาก server ไม่ส่ง digest
- เปลี่ยน draft เป็น Release ที่เผยแพร่แล้วเมื่อไฟล์ครบและผ่านการตรวจทั้งหมดเท่านั้น

`publication_attestation.json` บันทึกผู้สั่งงาน run ID, commit, เวอร์ชัน และ hash ของไฟล์จาก build นั้น
การอนุมัติเผยแพร่ไม่เปลี่ยนสถานะ Colab ให้ผ่าน ค่า Colab ในหลักฐานยังต้องตรงกับสิ่งที่ตรวจจริง
หาก Release เผยแพร่ไปแล้ว หรือ draft มี notes/ไฟล์ต่างเนื้อหา ระบบจะหยุดโดยไม่แทนที่หรือลบข้อมูลเดิม

## เมื่ออัปโหลดหยุดกลางทาง

หาก publish job ล้มเหลว ให้ใช้ **Re-run failed jobs** เพื่อใช้ build artifact ชุดเดิม
ไฟล์ที่อัปโหลดสำเร็จและ hash ตรงจะถูกใช้ต่อ ระบบเพิ่มเฉพาะไฟล์ที่ขาด ไม่มี `--clobber`
เมื่อไฟล์หรือ metadata ต่างจากชุดที่กำลังเผยแพร่ ระบบคง draft ไว้ให้ตรวจสาเหตุก่อน

ไม่ควรสั่ง build ใหม่แล้วคาดว่าจะเขียนทับไฟล์ชื่อเดิมได้ เพราะรายงานและเวลาใน ZIP ชุดใหม่อาจต่างจากชุดเดิม
workflow artifact มีอายุ 14 วัน หากหมดอายุและต้องสร้างชุดใหม่ ให้ตัดสินใจเรื่อง draft/เลขรุ่นอย่างชัดเจนก่อน

## ขอบเขตการยืนยันในรอบพัฒนานี้

ตรวจ workflow เป็น YAML, ตรวจ syntax ของ run scripts และทดสอบ logic ของ release helper แบบ offline
ครอบคลุม commit/เวอร์ชันผิด, การอนุมัติไม่ตรง, Release ที่เผยแพร่แล้ว, ไฟล์ conflict,
การใช้ draft เดิม, อัปโหลดล้มแล้วทำต่อ และการตรวจ hash จากการดาวน์โหลดสำรอง
ยังไม่มีการเรียก workflow หรือเผยแพร่รุ่นใหม่จากการตรวจเหล่านี้
การยืนยัน native uploads และสิทธิ์ environment ต้องเก็บจาก run จริงเมื่อผู้ใช้สั่งเผยแพร่ในภายหลัง
