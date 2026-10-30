"""Reproducible delivery verification using only the Python standard library."""

import compileall
import argparse
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


def main(argv=None):
    from neuron_flow import __version__
    parser = argparse.ArgumentParser(description="Run the original 38-case baseline")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "verification")
    args = parser.parse_args(argv)
    destination = args.output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # Keep the original 38-case baseline separate from 0.2.0 acceptance.
    # New CSV/batch checks are recorded by tools/verify_v020.py.
    suite = unittest.defaultTestLoader.discover(
        str(PROJECT / "tests"), pattern="test_runtime.py", top_level_dir=str(PROJECT))
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
        "tested_implementation_version": __version__, "suite_origin_version": "0.1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "test_cases": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "test_duration_seconds": round(duration, 3),
        "checks": checks, "successful": successful,
    }
    (destination / "test_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = f"""# Neuron Flow original 0.1.0 baseline verification

Result: {'passed' if successful else 'failed'}
The original 38-case baseline ran against implementation {__version__}.
Current acceptance results are recorded separately.

- UTC: {summary['created_at_utc']}
- Python: {summary['python']}
- Platform: {summary['platform']}
- Cases: {result.testsRun}; failures: {len(result.failures)}; errors: {len(result.errors)}; skipped: {len(result.skipped)}
- Test duration: {duration:.3f} seconds. This is correctness verification, not a performance benchmark.

The baseline covers Decimal calculation, independent integer verification, report hashes,
invalid data and outputs, worker hangs/crashes, controller interruption, bounded retries,
worker reuse, identity conflicts, workspace locking, event routing and interrupted delivery.
Additional CLI checks verify report integrity and idempotent recovery:

"""
    report += "\n".join(f"- {name}: {'passed' if passed else 'failed'}" for name, passed in checks.items())
    report += "\n\nReproduce with `python tools/verify.py`. See `tests.log` and `test_results.json`.\n"
    (destination / "VERIFICATION.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
