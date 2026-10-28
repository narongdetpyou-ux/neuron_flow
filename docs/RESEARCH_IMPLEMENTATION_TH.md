# แผนลงมือทำจากรายงานวิจัย — 28 ตุลาคม 2026

อ่าน `deep-research-report.md` ครบทั้ง 294 บรรทัดแล้ว รายงานเป็นข้อมูลประเมินและข้อเสนอ
ไม่ใช่สิทธิ์ให้เปลี่ยนการตั้งค่า เผยแพร่ release หรืออ้างผลทดลองที่ยังไม่ได้ทำ
คำสั่งของเจ้าของงานในแชตคือให้อ่าน วางแผน ลงมือจนเสร็จ และ push งานที่เสร็จขึ้น GitHub ทันที
งานนี้ใช้ branch `fix/research-hardening-20261028` และคงเวอร์ชัน candidate 0.2.1

## งานที่ลงมือและเกณฑ์เสร็จ

| ลำดับ | ผลส่งมอบ | เกณฑ์เสร็จ |
| --- | --- | --- |
| 1 | แก้ event cursor overflow ที่ CLI/API boundary | ขอบ int64, pagination, JSON exit 2; edge runner เดิมไม่มี crash; push ทันที |
| 2 | เอกสารสถานะที่แยกข้อมูลปัจจุบัน/ประวัติ/สิ่งที่ยังยืนยันไม่ได้ | ไม่มีคำกล่าว private หรือไม่เคยรัน CI ที่ล้าสมัย; มี static consistency check |
| 3 | Build backend ปลอด advisory ตามแหล่งทางการและ pin เครื่องมือ | dependency floor + reproducible build requirements; wheel และ sdist ติดตั้งใน clean venv ได้จริง |
| 4 | Coverage/lint/type gates และ CI | วัด branch พร้อม subprocess/worker; baseline จากผลจริง; correctness lint และ typecheck boundary ที่ระบุขอบเขต |
| 5 | Platform CI และ supply-chain controls ที่ทำในโค้ดได้ | เพิ่ม Windows/macOS smoke/regression; Actions pin SHA จาก upstream; metadata/SBOM และ build provenance ตรวจได้ |
| 6 | Full-runtime benchmark | วัด CLI/SQLite/IPC/delivery และ recovery จริง พร้อมตรวจยอด/receipt; บอกหน่วย percentile และข้อจำกัด |
| 7 | API/maintainer runbook และ backlog ที่ตรวจสอบได้ | ตัวอย่าง API รันได้; backup/recovery/release/access handover ชัด; งานภายนอกมีเกณฑ์และสถานะ |
| 8 | รวมผลตรวจและส่งงาน | full verifier, edge, quality, packaging, benchmark ผ่าน; บันทึกหลักฐานใหม่แยกจากของเดิม; push ทุกชุดที่เสร็จ |

ไม่ refactor สูตรเงินรวม calculator กับ verifier เพราะจะลดคุณสมบัติ independent verification
การเพิ่ม domain types เริ่มที่ boundary สำหรับ static typing โดยไม่เปลี่ยน persistence/CSV contract
parallel scheduling และ workspace relocation เป็น feature ใหม่ ต้องประเมินจาก benchmark/compatibility ก่อน

## ข้อเสนอที่ต้องมีระบบหรือหลักฐานภายนอก

ตารางนี้เป็น backlog เปิดเผย ไม่ใช่ผลเสร็จหรือเหตุผลให้ปลอม evidence:

| งานจากรายงาน | สิ่งที่ต้องมีเพื่อปิดงาน |
| --- | --- |
| main ruleset / GitHub Issues / Milestones / metadata | GitHub API และสิทธิ์ที่เหมาะสม; อ่านค่าจริงก่อนเปลี่ยนและอ่านกลับหลังเปลี่ยน |
| Colab acceptance | runtime Colab จริง, อัปโหลด/รัน/resume/ดาวน์โหลดที่ผู้ใช้ยืนยัน/restore runtime ที่สอง ตาม checklist เดิม |
| Native release asset verification | อนุมัติเผยแพร่ที่ตรงรุ่น/commit และ workflow จริง; ดาวน์โหลด assets กลับมาตรวจ SHA-256; การ push source ไม่ใช่ release approval |
| Windows/macOS support claim | ผล CI ของ runner จริง; เพิ่ม workflow อย่างเดียวไม่ถือว่ารันผ่านแล้ว |
| Signed tags / remote attestations / maintainer สำรอง | signing identity และสิทธิ์/บุคคลที่มีอยู่จริง; ไม่สร้าง key หรือแต่งข้อมูลแทนเจ้าของ |

Git read/write ใช้งานผ่าน platform HTTPS proxy ได้เมื่อรันใน execution context ที่เข้าถึง proxy
แต่ `gh api` ตอบ Forbidden; ไม่อนุมานว่า token หายและไม่ขอ token ในแชต
เพิ่ม `api.github.com` ไว้ใน draft network settings เพื่อรองรับ API โดยไม่เปลี่ยน presets เดิม
การบันทึก draft ยังไม่ใช่การ apply network policy หรือยืนยันว่า API ใช้ได้

ผลแต่ละชุดและสถานะสุดท้ายอยู่ใน `verification/research_2026_10_28/`
หลักฐานเก่า รวมทั้ง edge crash เดิมและสถานะ Colab `not_run` เก็บไว้ตามจริง

รายการข้อเสนอทั้งหมดพร้อมสถานะและเกณฑ์ปิดงานอยู่ใน [RESEARCH_BACKLOG.json](RESEARCH_BACKLOG.json)
ผลรวมที่ตรวจเสร็จจริงอ่านจาก [บันทึกผล](../verification/research_2026_10_28/README_TH.md)
