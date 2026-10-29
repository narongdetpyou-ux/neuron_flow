# ตรวจหลังเผยแพร่ Neuron Flow 0.3.0

[Release v0.3.0](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.3.0) เผยแพร่เมื่อ 29 ตุลาคม 2026 เวลา **16:49:18 น. ประเทศไทย**
(09:49:18 UTC) ตรวจดาวน์โหลดและ SHA-256 เมื่อ 16:49:55 น. ประเทศไทย
ผล API ที่ตรวจได้เป็น `draft: false` และผลตรวจรวม `passed: true`

## Source และ workflow

- Tag `v0.3.0` และ source ของ build: `a4ff09853491ba65acf60aa29daff10de01103f2`
- [Main CI](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40852073574) ผ่านครบ 9 jobs บน source commit นี้:
  Linux tests Python 3.10/3.12, quality, distributions Python 3.10/3.12 และ
  Windows/macOS smoke อย่างละ Python 3.10/3.12
- [Manual release](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40852128698) สำเร็จใน attempt 2 โดย build และ publish ใช้ source นี้
- Publish ครั้งแรกหยุดหลังสร้าง draft เพราะขั้นตอนค้นหา draft ยังมองไม่เห็น draft ที่เพิ่งสร้าง
  จากนั้น re-run เฉพาะ failed jobs ใช้ build artifact ชุดเดิมและเผยแพร่สำเร็จ
  ไม่แทนที่ release assets และไม่ย้าย tag

รายละเอียดสถานะและช่วงเวลาของแต่ละ job อยู่ใน [workflow-summary.json](workflow-summary.json)
ผลตรวจการดาวน์โหลดต้นฉบับเก็บโดยไม่แก้เนื้อหาที่
[publication-verification.json](publication-verification.json)

## ไฟล์ที่ดาวน์โหลดและตรวจ SHA-256

ดาวน์โหลดครบ 6 assets และตรวจ hash ตรงทุกไฟล์:

| ไฟล์ | Bytes | SHA-256 |
| --- | ---: | --- |
| `delivery_checks.json` | 833 | `73d34a5d92a4675403e6b149b83c61db9fbb2c87ecd5a3546a5050f5d64e1ce1` |
| `neuron_flow_v0.3.0.zip` | 1,285,103 | `1c4b609e7c96ca80ba349abc9fefefe6d5df7c9f6da901e7f6558c1c51eec09f` |
| `neuron_flow_v0.3.0.zip.sha256` | 89 | `13706b7123c369e2eaa8e18289de0e72f21ed03de6f67116baccf87c6262dc39` |
| `publication_attestation.json` | 1,288 | `cf43ab981aaf5b478243a26bdc40cbddb5a3aa12b5ad9e0e4ec2de2173ff9551` |
| `SHA256SUMS.txt` | 41,541 | `b0c6f5b8641ffc28cc089c44797df8e3e479e0cf6ea11db134af6dc3a46d8fc7` |
| `START_COLAB.ipynb` | 29,276 | `f662b6061410f8194d2891c6cd90f9a52f58e8b9a252402c46ed61785542e158` |

ตรวจ manifest ของไฟล์ภายใน ZIP ครบ **367 entries**
`SHA256SUMS.txt` และ checksum ของ ZIP ผูกกับชุดที่เผยแพร่นี้ ไม่ใช่ checkout ที่แก้ไขต่อภายหลัง

## ทดลอง CLI จาก ZIP ที่ดาวน์โหลด

แตก ZIP ที่ดาวน์โหลดและตรวจ manifest แล้ว รัน CLI รุ่น 0.3.0 กับ
`examples/purchases_international.csv` ได้ 4 VALID, 0 INVALID และ 0 ERROR
ยอดที่รับรองแยกเป็น EUR `25.50`, JPY `1500`, KWD `3.702` และ USD `21.50`
ส่วน `currency` และ `certified_total` เป็น null ตามกติกา batch หลายสกุล
การตรวจนี้รันจากชุดที่ดาวน์โหลด ไม่ใช่อ้างผลจาก source checkout ก่อนเผยแพร่

## ขอบเขตของข้อสรุป

ผลนี้ยืนยันสถานะ GitHub Release และความครบถ้วน/hash ของไฟล์ที่ดาวน์โหลด ณ เวลาตรวจ
CI smoke บน Windows/macOS ไม่แทน Linux full recovery/fault-injection suite
Actual Google Colab upload/run/resume/download/restore acceptance ยังคง `not_run`

ไฟล์ approval, release notes, `BUILD_STATUS.json` และ `delivery_checks.json` ใน tag/ZIP
เป็นบันทึกก่อนเผยแพร่ จึงเก็บข้อความเตรียมรุ่นและ `published:false` เดิมไว้
บันทึกหลังเผยแพร่นี้เพิ่มภายหลังโดยไม่แก้ tag หรือไฟล์ release ที่เผยแพร่แล้ว
