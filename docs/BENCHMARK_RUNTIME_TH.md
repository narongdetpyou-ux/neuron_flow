# Benchmark เส้นทาง CLI/Runtime จริง

ใช้คู่กับ [microbenchmark](BENCHMARK_TH.md) ซึ่งวัดเฉพาะฟังก์ชันในหน่วยความจำ:

```bash
python -B tools/benchmark_runtime.py --output-dir /tmp/neuron-runtime-benchmark
# เพิ่มขนาดเมื่อมีเวลา/พื้นที่เพียงพอ
python -B tools/benchmark_runtime.py --sizes 1 10 100 1000 --repeats 5 --output-dir /tmp/neuron-runtime-large
```

ค่าปริยายคือ 1/10/100 เอกสาร เอกสารละ 5 รายการ 5 samples ต่อขนาด
แต่ละ sample สร้าง workspace ใหม่ เรียก CLI จริง จึงรวม interpreter startup,
worker spawn/IPC, SQLite transactions, report verification, fsync และ shutdown
จับเวลาด้วย monotonic `perf_counter` รอบ subprocess ทั้งคำสั่ง ไม่รวมการสร้าง CSV
ไม่มี warm-up ที่หักออกจากผล: ตัวเลขสะท้อนการเรียก CLI ใหม่ทุกครั้ง

ผล JSON เก็บทุก sample, environment, source fingerprint (core Python, benchmark และ pyproject),
เวลา p50/p95 ของ **ทั้ง batch**, throughput
documents/second ที่เวลา median และขนาด source/artifact/SQLite/workspace
p50 ใช้ median ส่วน p95 ใช้ nearest-rank (`ceil(0.95*n)`); 5 samples ทำให้ p95
เป็นค่าสูงสุดที่เห็น จึงไม่ใช่การประมาณ tail latency ที่แม่นยำสำหรับ production
CSV สรุปอ่านต่อใน spreadsheet ได้ ค่าเหล่านี้ไม่ใช่ latency ของแต่ละเอกสาร
และไม่ใช่ SLA หรือผลเปรียบเทียบฮาร์ดแวร์แบบควบคุม

ทุกผลต้องผ่านการตรวจจำนวน VALID, ยอดรวมที่สร้างจาก integer satang แยกจาก runtime,
artifact size/SHA-256 และครบ `source.csv`, `summary.csv`, `details.json`
จากนั้นลบ CSV upload และเรียก `batch-resume` อีกครั้ง จับเวลาแยกและตรวจว่า
ผล, successful steps, attempts, event history และ bytes/mtime ของ artifact ไม่เปลี่ยน

มี batch แยกสำหรับ recovery (ปริยาย 100 เอกสาร ปรับด้วย `--recovery-documents`)
poll SQLite แบบ read-only จนเห็นอย่างน้อยหนึ่งเอกสารมี receipt และยังมีงานไม่ครบ
จึง kill controller จริง แล้วเรียก CLI `batch-resume` หลังลบ CSV upload
ผลต้อง VALID ครบ ยอด/hash ถูกต้อง และ successful steps, completed jobs และ event prefix
ก่อนหยุดต้องเหมือนเดิม ไม่มี step เกิน 2 attempts
ทุกครั้งที่ poll จะปิด SQLite connection ทันที รวมเส้นทาง exception
หลังหยุด controller ต้องตรวจว่า workspace lock ปลดแล้วก่อน resume
บน Linux ตรวจว่า child PID ที่เห็นจาก `/proc` ก่อน kill หยุดทำงานแล้วด้วย
(รวม zombie เป็น stopped); ระบบอื่นแสดงการตรวจ child นี้เป็น null ไม่อ้างว่าตรวจแล้ว
ใช้ parent-death watcher ของ runtime ในการหยุด worker ไม่ส่ง signal ไปยัง PID ที่ค้นพบแยกเอง
ถ้า controller เสร็จเร็วเกินกว่าจะหยุดในช่วงนี้ จะรายงาน failure; ไม่อ้างว่าทดสอบ recovery แล้ว
เวลา recovery ไม่รวมเวลาก่อน kill และรวมเฉพาะ CLI ที่ resume จนจบ
การหยุดนี้ไม่ได้บังคับว่า worker ต้องกำลังคำนวณ; อาจหยุดระหว่างเอกสาร/ขั้นตอน
ชุด regression ของโครงการมีกรณี hung-worker และ controller kill ที่กำหนดจุดได้แยกต่างหาก

บน Linux/macOS รายงาน maximum child high-water RSS ด้วย `resource.RUSAGE_CHILDREN`
ครอบคลุม subprocess ที่ระบบรอเก็บสถานะตลอด benchmark ไม่ใช่ผลรวม RAM ของ process tree
ที่ทำงานพร้อมกัน ไม่ใช่ incremental Python allocation และไม่แยกแต่ละ sample
แพลตฟอร์มที่ไม่มีหน่วย/กลไกรองรับแสดง null
ขนาดไฟล์เป็นค่าหลัง CLI ปิดแล้ว **ไม่ใช่ write amplification/cumulative bytes written**;
WAL ชั่วคราวอาจถูก checkpoint/ลบไป ต้องใช้ OS tracing แยกต่างหากหากต้องการตัวเลข I/O จริง

`--timeout` จำกัดเวลาแต่ละ CLI และเวลารอ checkpoint ของ recovery (ปริยาย 180 วินาที)
ข้อผิดพลาด/timeout/ผลผิดคืน exit 1 และบันทึก `successful: false` พร้อมสาเหตุ
เลือก output directory ว่างเพื่อไม่ทับหลักฐานเดิม workspace และ log ยังคงอยู่เพื่อตรวจสอบ
ข้อมูลเป็น synthetic ไม่มีเอกสารการเงินจริง ไม่มีการเผยแพร่หรือเชื่อมบริการภายนอก
