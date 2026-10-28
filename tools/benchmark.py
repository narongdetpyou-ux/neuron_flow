"""Benchmark the in-memory CSV functions with only the Python standard library.

Example (from any directory)::

    python /workspace/neuron_flow/tools/benchmark.py --output-dir /tmp/neuron-bench

Timing and tracemalloc run in separate passes. Each function/size gets a fresh
subprocess. These measurements exclude Runtime, SQLite, worker IPC and report I/O.
"""

import argparse
import csv
from datetime import datetime, timezone
import gc
import io
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from neuron_flow import __version__
from neuron_flow.csv_agents import compute_document, validate_document, verify_document
from neuron_flow.csv_input import FIELDS, read_csv_bytes


CASES = ("read_csv_bytes", "validate_document", "compute_document",
         "verify_document", "csv_pipeline")


def make_source(items):
    """Make one valid document; derive the expected total with integer satang."""
    rows, total_cents = [], 0
    for index in range(items):
        quantity = index % 5 + 1
        price_cents = 100 + index % 10000
        total_cents += quantity * price_cents
        rows.append((f"I{index}", quantity, f"{price_cents // 100}.{price_cents % 100:02d}"))
    total = f"{total_cents // 100}.{total_cents % 100:02d}"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    for item_id, quantity, price in rows:
        writer.writerow(("BENCH", item_id, "สินค้าทดสอบ", quantity, price, total, "THB"))
    return stream.getvalue().encode("utf-8"), total


def prepare_case(name, items):
    source, total = make_source(items)
    # Only construct the prerequisite objects for the selected function.
    document = validated = calculated = None
    if name in ("validate_document", "compute_document", "verify_document"):
        document = read_csv_bytes(source)["documents"][0]
    if name in ("compute_document", "verify_document"):
        validated = validate_document(document)
    if name == "verify_document":
        calculated = compute_document(validated)

    def pipeline():
        parsed = read_csv_bytes(source)
        checked = validate_document(parsed["documents"][0])
        return verify_document(checked, compute_document(checked))

    operations = {
        "read_csv_bytes": lambda: read_csv_bytes(source),
        "validate_document": lambda: validate_document(document),
        "compute_document": lambda: compute_document(validated),
        "verify_document": lambda: verify_document(validated, calculated),
        "csv_pipeline": pipeline,
    }

    def check(result):
        # Explicit checks stay active under python -O; none run inside timers.
        if name == "read_csv_bytes":
            valid = (result["input_rows"] == items and not result["ungrouped_rows"]
                     and len(result["documents"]) == 1
                     and len(result["documents"][0]["rows"]) == items)
        elif name == "validate_document":
            valid = (result["document_status"] is None and not result["errors"]
                     and len(result["invoice"]["items"]) == items
                     and result["declared_total"] == total)
        elif name == "compute_document":
            valid = (result["total"] == total and len(result["lines"]) == items)
        else:
            valid = (result["document_status"] == "VALID" and not result["errors"]
                     and result["computed_total"] == total and result["difference"] == "0.00"
                     and len(result["source_rows"]) == items)
        if not valid:
            raise RuntimeError(f"Incorrect benchmark result: {name}, {items} items")

    return operations[name], check, len(source), total


def timed_calls(operation, iterations):
    started = time.perf_counter_ns()
    for _ in range(iterations):
        result = operation()
        # Include normal output destruction, without overlapping live outputs.
        del result
    return (time.perf_counter_ns() - started) / 1_000_000


def process_peak_rss_bytes():
    """Absolute high-water RSS of this worker, before enabling tracemalloc."""
    try:
        import resource
    except ImportError:
        return None
    if sys.platform == "darwin":
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith("linux"):
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return None  # Other operating systems use different units or lack RSS.


def benchmark_case(config):
    operation, check, source_bytes, total = prepare_case(config["case"], config["items"])
    check(operation())
    for _ in range(config["warmups"]):
        operation()
    gc.collect()
    calibration_ms = timed_calls(operation, 1)
    iterations = min(config["max_iterations"],
                     max(1, math.ceil(config["target_ms"] / max(calibration_ms, 0.001))))
    samples = []
    for _ in range(config["repeats"]):
        gc.collect()
        samples.append(timed_calls(operation, iterations) / iterations)
    check(operation())
    rss = process_peak_rss_bytes()
    peaks = []
    for _ in range(config["memory_repeats"]):
        gc.collect()
        tracemalloc.start()
        try:
            baseline, _ = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            result = operation()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        check(result)
        del result
        peaks.append(max(0, peak - baseline))
    median_ms = statistics.median(samples)
    return {
        "case": config["case"], "items": config["items"], "documents": 1,
        "source_bytes": source_bytes, "expected_total_thb": total,
        "iterations_per_sample": iterations, "timing_samples_ms": samples,
        "median_ms": median_ms, "min_ms": min(samples), "max_ms": max(samples),
        "items_per_second": config["items"] * 1000 / median_ms,
        "python_peak_samples_bytes": peaks, "python_peak_bytes": max(peaks),
        "process_peak_rss_bytes": rss, "correctness_checked": True,
    }


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def item_count(value):
    number = positive_int(value)
    if number > 10000:
        raise argparse.ArgumentTypeError("must not exceed the 10,000-item document limit")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than 0")
    return number


def report_table(results):
    lines = [f"{'Function':<20} {'Items':>7} {'Median ms':>11} {'Min ms':>10} "
             f"{'Max ms':>10} {'Python KiB':>12} {'RSS MiB':>9}"]
    for row in results:
        rss = row["process_peak_rss_bytes"]
        rss_text = f"{rss / 1024 ** 2:.2f}" if rss is not None else "n/a"
        lines.append(f"{row['case']:<20} {row['items']:>7} {row['median_ms']:>11.3f} "
                     f"{row['min_ms']:>10.3f} {row['max_ms']:>10.3f} "
                     f"{row['python_peak_bytes'] / 1024:>12.1f} {rss_text:>9}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=item_count, nargs="+", default=[10, 100, 1000, 10000])
    parser.add_argument("--cases", choices=CASES, nargs="+", default=list(CASES))
    parser.add_argument("--repeats", type=positive_int, default=7)
    parser.add_argument("--warmups", type=positive_int, default=2)
    parser.add_argument("--memory-repeats", type=positive_int, default=3)
    parser.add_argument("--target-ms", type=positive_float, default=25,
                        help="target sample duration for calibration; a slow call may exceed it")
    parser.add_argument("--max-iterations", type=positive_int, default=1000)
    parser.add_argument("--timeout", type=positive_float, default=180,
                        help="timeout in seconds for each isolated function/size worker")
    parser.add_argument("--output-dir", type=Path, help="save benchmark.json, benchmark.csv and benchmark.txt")
    parser.add_argument("--_worker-json", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker_json:
        print(json.dumps(benchmark_case(json.loads(args._worker_json))))
        return 0
    if args.output_dir:
        if args.output_dir.exists() and not args.output_dir.is_dir():
            parser.error("--output-dir must be a directory")
        if any((args.output_dir / f"benchmark.{suffix}").exists() for suffix in ("json", "csv", "txt")):
            parser.error("benchmark output already exists; choose another output directory")
    started = time.perf_counter()
    results = []
    for items in dict.fromkeys(args.sizes):
        for case in dict.fromkeys(args.cases):
            config = {"case": case, "items": items, "repeats": args.repeats,
                      "warmups": args.warmups, "memory_repeats": args.memory_repeats,
                      "target_ms": args.target_ms, "max_iterations": args.max_iterations}
            print(f"Benchmarking {case}: {items} items", file=sys.stderr, flush=True)
            command = [sys.executable, "-B", str(Path(__file__).resolve()),
                       "--_worker-json", json.dumps(config)]
            try:
                completed = subprocess.run(command, cwd=PROJECT, capture_output=True,
                                           text=True, timeout=args.timeout)
            except subprocess.TimeoutExpired:
                parser.exit(1, f"Timed out: {case}, {items} items; no complete report saved.\n")
            if completed.returncode:
                parser.exit(1, f"Benchmark failed: {case}, {items} items\n{completed.stderr}")
            results.append(json.loads(completed.stdout))
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_version": __version__, "python": sys.version,
        "platform": platform.platform(), "logical_cpu_count": os.cpu_count(),
        "elapsed_seconds": time.perf_counter() - started,
        "settings": {"sizes": list(dict.fromkeys(args.sizes)), "cases": list(dict.fromkeys(args.cases)),
                     "repeats": args.repeats, "warmups": args.warmups,
                     "memory_repeats": args.memory_repeats, "target_ms": args.target_ms,
                     "max_iterations": args.max_iterations, "worker_timeout_seconds": args.timeout},
        "methodology": {
            "workload": "One deterministic VALID UTF-8 purchase document per call, varied quantities/prices.",
            "timing": "perf_counter_ns; each sample is average time per call over its iterations; "
                      "median/min/max summarize those sample averages, not individual-call latency. "
                      "Includes output destruction. "
                      "Imports, fixture preparation, checks, GC collection, warmups and calibration excluded. "
                      "Tracing disabled; GC enabled during calls.",
            "python_peak_bytes": "Maximum extra Python-traced allocation peak for one call, "
                                 "over separate memory repeats. Prepared inputs excluded; output retained "
                                 "until reading the peak. Not total RAM or all native allocations.",
            "process_peak_rss_bytes": "Absolute peak RSS of a fresh worker before tracemalloc passes. "
                                      "Includes interpreter/imports, fixtures, warmups, calibration and timing. "
                                      "Not incremental function memory; unavailable systems return null.",
            "scope": "Direct in-memory functions; csv_pipeline is parse/validate/compute/verify. "
                     "Excludes Runtime, SQLite, worker IPC and filesystem/report I/O. "
                     "Large direct-function inputs do not establish Runtime message-limit compatibility.",
        },
        "results": results,
    }
    table = report_table(results)
    notes = ("\nPython KiB = additional peak Python-traced allocations per call.\n"
             "RSS MiB = absolute worker process peak before tracing, including interpreter and fixtures.\n"
             "Median/min/max summarize sample averages per call, not individual-call latency.\n"
             "Timing and allocation tracing use separate passes; fixtures/checks are outside timing.\n"
             "Direct functions only: Runtime, SQLite, worker IPC and report/file I/O are excluded.\n")
    print(table + notes)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "benchmark.txt").write_text(table + notes, encoding="utf-8")
        fields = ("case", "items", "documents", "source_bytes", "iterations_per_sample", "median_ms",
                  "min_ms", "max_ms", "items_per_second", "python_peak_bytes", "process_peak_rss_bytes")
        with (args.output_dir / "benchmark.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        print(f"Results saved to {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
