# Document adapters — 30 October 2026

ตรวจ source ของ `0.4.0.dev0` บน Linux/Python 3.12.14 โดยไม่เปลี่ยน locked fixture
หรือหลักฐานของ release เก่า รุ่นนี้ยังไม่เผยแพร่และยังไม่มี publication approval

| การตรวจ | ผล |
| --- | --- |
| Regression ทั้ง package รวมส่วนเพิ่ม | 203 tests ผ่าน; 0 failure/error/skipped |
| Full verifier | baseline 38 + current 165 ผ่าน |
| Locked fixture | 100 documents: 80 VALID / 20 INVALID; bytes เดิม |
| Release guards | 10 tests ผ่าน; รุ่นพัฒนาไม่มีสิทธิ์อนุมัติเดิม |
| Ruff E9,F / scoped mypy strict | ผ่าน |
| Package line / branch coverage | 93.82% / 87.53%; ผ่าน floor เดิมทั้งหมด |
| Wheel / sdist | build/install ใน venv แยกจาก checkout ผ่าน |
| Installed CLI | CSV run/resume, adapters, JSON intake/run ผ่านทั้ง wheel และ sdist |
| PDF / XLSX | ทดสอบกับไฟล์ที่สร้างจริง รวมสูตร, PDF เข้ารหัส, ขอบเขตและไฟล์เสีย |
| OCR | Tesseract จริงบน PNG, JPEG, TIFF และ PDF สแกน ภาษาอังกฤษ |
| Review / recovery | ห้าม run ก่อน review, review revisions แยก ID, reuse และตรวจ SHA ผ่าน |
| Cloud adapters | API contract/failure tests ผ่านด้วย fake HTTP/S3 clients |

ดู [ผล verifier](test_results.json), [quality](quality_results.json),
[packaging](distribution_checks.json) และ [ขอบเขตคำสั่ง/สถานะ](validation_scope.json)
ผล verifier มี source fingerprint; การเติมหลักฐานใน directory นี้ไม่อยู่ใน fingerprint scope
รวม regression ของ JSON exponent ขนาดใหญ่ที่ต้องถูกปฏิเสธก่อนขยาย decimal string

ยังไม่ได้ทดสอบบัญชี cloud จริง, OCR ไทยบนเครื่องนี้ หรือ actual Colab upload/run/resume/download/restore
ไม่ตีความ local/fake API tests ว่าเปิดสิทธิ์ cloud สำเร็จหรือยืนยัน production SLA
CI สำหรับ optional adapters ติดตั้ง extras/Tesseract; ผลรันระยะไกลตรวจจาก PR แยกจากหลักฐานท้องถิ่นนี้

ไฟล์ตัวอย่างทั้งหมดเป็นข้อมูลสังเคราะห์ ไม่มีใบเสร็จจริงหรือ credentials
คู่มือการติดตั้งและคำสั่งอยู่ที่ [INTEGRATIONS_TH.md](../../docs/INTEGRATIONS_TH.md)
