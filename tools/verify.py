"""Reproducible delivery verification using only the Python standard library."""

import compileall
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main():
    destination = PROJECT / "verification"
    destination.mkdir(exist_ok=True)
    started = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(PROJECT / "tests"), top_level_dir=str(PROJECT))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    duration = time.monotonic() - started
    (destination / "tests.log").write_text(stream.getvalue(), encoding="utf-8")
    syntax_ok = compileall.compile_dir(str(PROJECT / "neuron_flow"), quiet=1)
    syntax_ok = compileall.compile_dir(str(PROJECT / "tests"), quiet=1) and syntax_ok
    with tempfile.TemporaryDirectory(prefix="neuron-flow-verification-") as temporary:
        command = [sys.executable, "-m", "neuron_flow", "demo", "--workspace", temporary]
        first_process = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, timeout=30)
        if first_process.returncode:
            raise RuntimeError(first_process.stderr)
        first = json.loads(first_process.stdout)
        path = Path(first["receipt"]["path"])
        before_bytes, before_modified = path.read_bytes(), path.stat().st_mtime_ns
        second_process = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, timeout=30)
        if second_process.returncode:
            raise RuntimeError(second_process.stderr)
        second = json.loads(second_process.stdout)
        checks = {
            "syntax_compiles": syntax_ok,
            "fresh_cli_run_succeeds": first["status"] == "SUCCEEDED",
            "independent_check_total_310_70": first["steps"]["verify"]["output"]["total"] == "310.70",
            "report_hash_matches_receipt": hashlib.sha256(before_bytes).hexdigest() == first["receipt"]["sha256"],
            "second_run_does_not_repeat_steps": all(step["attempts"] == 1 for step in second["steps"].values()),
            "second_run_does_not_rewrite_report": path.read_bytes() == before_bytes and path.stat().st_mtime_ns == before_modified,
        }
        (destination / "demo_report.json").write_bytes(before_bytes)
    successful = result.wasSuccessful() and all(checks.values())
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "test_cases": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "test_duration_seconds": round(duration, 3),
        "checks": checks, "successful": successful,
    }
    (destination / "test_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = f"""# ผลตรวจ Neuron Flow 0.1.0

สถานะ: {'ผ่าน' if successful else 'ไม่ผ่าน'}

- เวลา UTC: {summary['created_at_utc']}
- Python: {summary['python']}
- สภาพแวดล้อม: {summary['platform']}
- ทดสอบ {result.testsRun} กรณี; failures {len(result.failures)}; errors {len(result.errors)}; skipped {len(result.skipped)}
- เวลาชุดทดสอบ: {duration:.3f} วินาที ค่านี้เป็นการตรวจการทำงาน ไม่ใช่ benchmark ประสิทธิภาพ

## สิ่งที่ทดสอบ

1. อ่านข้อมูล คำนวณด้วย Decimal ตรวจด้วย integer cents และอ่านรายงานกลับมาตรวจ SHA-256
2. ข้อมูลผิด ราคาที่เป็น float ผลรวมผิด ผลที่ชนิดข้อมูลผิด และข้อมูลที่ส่งเป็น JSON ไม่ได้
3. Agent ค้างจริง process ลูกตายจริง และการหยุด controller จริงแล้วเปิดใหม่
4. จำกัดจำนวน process และยืนยันการใช้ worker ซ้ำในงานขนาน 30 ขั้น
5. เก็บผลขั้นที่สำเร็จไว้ จำกัดจำนวนลองใหม่ และให้งานสาขาอื่นทำต่อเมื่ออีกสาขาล้มเหลว
6. ป้องกันงานซ้ำ รหัสงานชนกับข้อมูลใหม่ การเปิด controller สองตัว และ Agent เปลี่ยน version
7. ส่ง event เฉพาะผู้รับ ตรวจ failure ของการบันทึก และกรณีเขียนไฟล์แล้วแต่ยังบันทึก receipt ไม่สำเร็จ
8. ตรวจตัวตรวจที่คืน False หรือแก้ผลลัพธ์ และทดสอบ CLI จาก subprocess แยกจริง

## การตรวจซ้ำหลังชุดทดสอบ

"""
    report += "\n".join(f"- {name}: {'ผ่าน' if passed else 'ไม่ผ่าน'}" for name, passed in checks.items())
    report += """

## การแก้ไขระหว่างทบทวนโค้ด

- ใช้เวลาที่ worker ทำงานเสร็จจริงแยกจากเวลาที่ controller มาอ่านผล ป้องกันการนับผลที่รออยู่ในคิวเป็น timeout ผิด
- จับเวลาเริ่มก่อนส่งงาน และไม่รวมเวลาเปิด worker ใหม่ใน timeout งาน
- เปรียบเทียบผลแบบ JSON ที่คงชนิดข้อมูล จึงแยก true ออกจาก 1 ได้
- ปฏิเสธตัวตรวจที่คืน False และตัวตรวจที่แก้ output
- ปฏิเสธ JSON ที่มีชื่อฟิลด์ซ้ำหรือค่าตัวเลขไม่สิ้นสุด
- บันทึก event ของการลองส่งมอบแต่ละครั้งแยกกัน

## ขอบเขตหลักฐาน

ผลนี้ยืนยันพฤติกรรมในสถานการณ์ทดสอบบนเครื่องเดียว ไม่ยืนยันความสามารถเรียนรู้เอง
หรือความเหมือนสมองจริง ยังไม่ได้วัดการใช้งานหลายเครื่องหรือทดสอบ Windows/macOS
การบันทึกรายงานมีการตรวจการทำซ้ำ; การกระทำภายนอกโดย Agent ที่เพิ่มเองต้องออกแบบแยก

ทำซ้ำได้ด้วย `python tools/verify.py` จากโฟลเดอร์โปรเจกต์
ดูผลรายกรณีใน `tests.log` และผลเครื่องอ่านใน `test_results.json`
"""
    (destination / "VERIFICATION_TH.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
