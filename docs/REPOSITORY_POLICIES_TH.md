# นโยบายและการตั้งค่า GitHub

ชุดนี้ใช้แนวปฏิบัติทั่วไปของโครงการซอฟต์แวร์และ GitHub Community Standards
ไม่ได้อ้างการรับรอง ISO หรือมาตรฐานด้านกฎหมายใด ๆ
คง LICENSE เดิมและกระบวนการอนุมัติเผยแพร่รุ่นเดิม

## เอกสารและแบบฟอร์ม

| ไฟล์ | หน้าที่ |
| --- | --- |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | วิธีมีส่วนร่วม เตรียมเครื่อง ทดสอบ และส่ง PR |
| [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Contributor Covenant 2.1 พร้อมขั้นตอนกำกับดูแล |
| [SECURITY.md](../SECURITY.md) | ขอบเขตความปลอดภัยและวิธีขอช่องทางรายงานที่เหมาะสม |
| [SUPPORT.md](../SUPPORT.md) | การขอความช่วยเหลือโดยใช้ข้อมูลจำลอง |
| [GOVERNANCE.md](../GOVERNANCE.md) | ผู้ดูแล การตัดสินใจ review และการอนุมัติ release |
| [CODEOWNERS](../.github/CODEOWNERS) | ระบุเจ้าของโค้ดเป็น @narongdetpyou-ux |
| [Issue forms](../.github/ISSUE_TEMPLATE/) | Bug, feature, usage question และคำขอช่องทางติดต่อ |
| [PR template](../.github/PULL_REQUEST_TEMPLATE.md) | ปัญหา ผลที่เปลี่ยน การตรวจ และข้อจำกัด |
| [Dependabot](../.github/dependabot.yml) | ตรวจ GitHub Actions และ build dependency ฝั่ง pip ทุกวันจันทร์ 09:00 น. ตาม Asia/Bangkok |

เอกสารเหล่านี้อยู่ใน branch/PR จนกว่าจะ merge และฟีเจอร์ที่ GitHub อ่านจาก default branch
จะใช้ไฟล์หลัง merge แล้ว การเพิ่ม CODEOWNERS หรือกล่าวถึง CI ในเอกสารไม่เท่ากับเปิด enforcement
Dependabot config เป็นการตรวจเวอร์ชัน dependency ไม่ได้ยืนยันว่า security alerts เปิดอยู่
ไม่มีการเปิด auto-merge ของ dependency PR

## กติกา main ที่เตรียมไว้

[main-ruleset.json](../.github/policies/main-ruleset.json) เป็น payload สำหรับ GitHub REST API
`POST /repos/narongdetpyou-ux/neuron_flow/rulesets` เมื่อบัญชีและสิทธิ์รองรับ
**เป็นค่าที่เสนอไว้ ยังไม่ได้บังคับใช้** แม้ใน payload ระบุ `enforcement: active`

- เข้า `main` ผ่าน PR และแก้ review conversations ให้ครบ
- ต้องผ่าน `test (3.10)` และ `test (3.12)` จาก GitHub Actions app ID 15368
  ยืนยันชื่อและ app จาก check runs จริงแล้ว
- branch ต้องอัปเดตกับฐานก่อน merge; ไม่อนุญาต force-push หรือลบ `main`
- ไม่ตั้ง bypass actor; ไม่บังคับ signed commits, deployments หรือ manual release jobs
- required approval เท่ากับ 0 ในขณะมีผู้ดูแลคนเดียว ไม่บังคับ code-owner/last-push approval
  เพราะผู้เขียน PR ไม่สามารถ approve PR ตัวเองได้ ให้ขอ independent review เมื่อมีผู้เหมาะสม

หากเพิ่มผู้ดูแล ควรพิจารณา approval อย่างน้อย 1 คนและปรับ CODEOWNERS พร้อมกัน
กติกานี้ไม่เปลี่ยน merge methods เดิม และไม่อนุมัติการเผยแพร่ release

## สถานะที่ตรวจจริง — 28 ตุลาคม 2026

repository เป็น **private**, default branch คือ `main` และมี owner/admin หนึ่งราย
ผล API ในช่วงจัดทำครั้งนี้:

| การตั้งค่า | ผลตรวจ/การดำเนินการ |
| --- | --- |
| Rulesets | GitHub ตอบ 403: ต้องใช้แผนที่รองรับ private-repository rulesets |
| Classic branch protection | อ่านไม่ได้: 403 Resource not accessible by integration |
| ลบ branch หลัง merge | ขอเปิดแล้วแต่ถูกปฏิเสธ 403; ไม่ยืนยันว่าเปลี่ยนสำเร็จ |
| Dependabot alerts | ขอเปิดแล้วแต่ถูกปฏิเสธ 403; สถานะปัจจุบันยังยืนยันไม่ได้ |
| Dependabot security updates | อ่านไม่ได้: 403; ยังไม่ได้เปลี่ยน |
| Default Actions token permissions | อ่านไม่ได้: 403; ยังไม่ได้เปลี่ยน |
| Private vulnerability reporting | API ตอบ 404; ไม่ยืนยันว่ามีช่องทางนี้ |

GitHub ตอบข้อความสำหรับ rulesets ว่า “Upgrade to GitHub Pro or make this repository public to enable this feature.”
คงความเป็น private ไว้ ผู้ดูแลสามารถเลือกแผนที่รองรับ private repository ได้
ไม่มีการอัปเกรดแผน เปลี่ยน visibility หรือเพิ่มสิทธิ์ integration โดยอัตโนมัติ

Owner ต้องใช้ Settings ที่มีสิทธิ์เพียงพอหากจะเปิดการตั้งค่าที่ถูกบล็อก:

1. ตรวจแผนบริการและตั้ง ruleset จาก payload ข้างต้น แล้วตรวจ API/หน้า Rules ให้เห็นว่า active จริง
2. ตรวจ Settings → Security สำหรับ dependency graph, Dependabot alerts และ security updates
   ฟีเจอร์ที่มีให้เลือกขึ้นกับประเภท repository/แผนบริการ
3. เปิด Automatically delete head branches ใน Settings → General หากต้องการใช้นโยบายนี้
4. ตั้ง Actions default token เป็น read-only และไม่ให้ workflow อนุมัติ PR เอง
   โดยคงสิทธิ์ `contents: write` เฉพาะ publish job ที่ได้รับอนุมัติแล้ว

CI เดิมระบุ `contents: read` และ release publish job ระบุ `contents: write` อยู่แล้ว
ไม่เปลี่ยน workflow หรือ trigger การเผยแพร่ในงานนี้

## การติดต่อเรื่องอ่อนไหว

ไม่สร้างอีเมลหรือกล่าวอ้างว่ามี private channel ที่ยังไม่ได้ตั้งค่า
กรณีไม่มีปุ่ม Report a vulnerability ให้ส่งเพียงคำขอจัดช่องทางติดต่อผ่านแบบฟอร์ม
คำขอนี้มองเห็นได้โดยผู้มีสิทธิ์อ่าน repository และไม่ใช่ข้อความส่วนตัวถึง maintainer
รอช่องทางที่ตกลงกันก่อนส่งรายละเอียดช่องโหว่หรือหลักฐานเกี่ยวกับบุคคล
ดู [SECURITY.md](../SECURITY.md) และ [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)
