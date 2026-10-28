"""Measure real CLI batches, repeat delivery and interrupted-controller recovery.

Run from any directory. Results are whole-batch wall time, not per-document
latency. Each sample uses new source/workspaces and invokes the normal CLI.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import sqlite3
import statistics
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from neuron_flow import __version__
from neuron_flow.csv_input import FIELDS
from neuron_flow.storage import WorkspaceBusy, WorkspaceLock


def make_source(documents, items):
    """Produce deterministic valid data and an independent integer-satang total."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    total = sum((index % 3 + 1) * (100 + index) for index in range(items))
    for document in range(documents):
        for item in range(items):
            cents = 100 + item
            writer.writerow((f"D{document:06}", f"I{item:05}", "synthetic benchmark",
                             item % 3 + 1, money(cents), money(total), "THB"))
    return stream.getvalue().encode("utf-8"), money(total * documents)


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def source_fingerprint():
    digest = hashlib.sha256()
    paths = list((PROJECT / "neuron_flow").glob("*.py"))
    paths.extend([Path(__file__).resolve(), PROJECT / "pyproject.toml"])
    for path in sorted(paths):
        digest.update(path.relative_to(PROJECT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def percentile(samples, fraction):
    """Nearest-rank quantile; small-sample p95 is usually the observed maximum."""
    if not samples or not 0 < fraction <= 1:
        raise ValueError("a nonempty sample and a fraction in (0, 1] are required")
    return sorted(samples)[math.ceil(len(samples) * fraction) - 1]


def cli(arguments, timeout):
    started = time.perf_counter()
    completed = subprocess.run([sys.executable, "-B", "-m", "neuron_flow", *arguments],
                               cwd=PROJECT, capture_output=True, text=True, timeout=timeout, check=False)
    elapsed = time.perf_counter() - started
    if completed.returncode:
        raise RuntimeError(f"CLI failed ({completed.returncode}): {completed.stderr}")
    return json.loads(completed.stdout), elapsed


def database_state(workspace):
    """Consistent read-only observation, including successful outputs and history."""
    path = workspace / "state.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as database:
        database.row_factory = sqlite3.Row
        database.execute("BEGIN")
        jobs = {row["id"]: dict(row) for row in database.execute("SELECT * FROM jobs")}
        steps = {(row["job_id"], row["id"]): dict(row)
                 for row in database.execute("SELECT * FROM steps")}
        events = [dict(row) for row in database.execute("SELECT * FROM events ORDER BY sequence")]
    return jobs, steps, events


def controller_children(pid):
    """Linux-only bounded observation; never signal an independently found PID."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        return [int(value) for value in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
    except FileNotFoundError:
        return []


def wait_cleanup(workspace, child_pids, timeout=5):
    """Confirm kernel lock release and observed children exiting on parent death."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = []
        for pid in child_pids or []:
            try:
                # Zombies retain /proc entries but execute no further work.
                state = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0]
            except FileNotFoundError:
                continue
            if state != "Z":
                active.append(pid)
        lock_released = not (workspace / "runtime.lock").exists()
        if not lock_released:
            try:
                lock = WorkspaceLock(workspace / "runtime.lock")
            except WorkspaceBusy:
                pass
            else:
                lock.close()
                lock_released = True
        if lock_released and not active:
            return
        time.sleep(0.01)
    raise RuntimeError("Interrupted controller cleanup did not release its lock/observed children")


def artifacts(receipt):
    result = {}
    for name, record in receipt["artifacts"].items():
        path = Path(record["path"])
        data = path.read_bytes()
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise RuntimeError(f"Artifact integrity failure: {name}")
        result[name] = {"bytes": len(data), "sha256": record["sha256"],
                        "mtime_ns": path.stat().st_mtime_ns}
    if set(result) != {"source.csv", "summary.csv", "details.json"}:
        raise RuntimeError("Missing expected batch artifacts")
    return result


def check_result(result, documents, total):
    if (result.get("status") != "DELIVERED"
            or result.get("counts") != {"documents": documents, "VALID": documents,
                                        "INVALID": 0, "ERROR": 0}
            or result.get("certified_total") != total or result.get("ungrouped_rows") != 0):
        raise RuntimeError("Incorrect runtime benchmark result")
    return artifacts(result["receipt"])


def storage_bytes(workspace):
    # Final on-disk bytes, after the CLI closes. These are not bytes written:
    # temporary WAL, journal and fsync/write amplification require OS tracing.
    files = [path for path in workspace.rglob("*") if path.is_file()]
    return {"sqlite_bytes": sum(path.stat().st_size for path in files
                                if path.name.startswith("state.sqlite3")),
            "workspace_bytes": sum(path.stat().st_size for path in files)}


def normal_sample(directory, documents, items, timeout):
    directory.mkdir()
    source, total = make_source(documents, items)
    source_path = directory / "source.csv"
    source_path.write_bytes(source)
    workspace = directory / "workspace"
    result, fresh_s = cli(["csv", str(source_path), "--batch-id", "benchmark",
                          "--workspace", str(workspace)], timeout)
    original_artifacts = check_result(result, documents, total)
    before = database_state(workspace)
    source_path.unlink()  # Recovery/repeated delivery must not need the upload.
    resumed, resume_s = cli(["batch-resume", "benchmark", "--workspace", str(workspace)], timeout)
    if (resumed != result or check_result(resumed, documents, total) != original_artifacts
            or database_state(workspace) != before):
        raise RuntimeError("Completed-batch resume repeated work or changed artifacts/history")
    return {"fresh_seconds": fresh_s, "completed_resume_seconds": resume_s,
            "source_bytes": len(source), "artifact_bytes": sum(a["bytes"] for a in original_artifacts.values()),
            **storage_bytes(workspace), "artifact_hashes": original_artifacts,
            "completed_resume_unchanged": True, "correctness_checked": True}


def interrupted_sample(directory, documents, items, timeout):
    """Kill the normal controller after durable progress, then resume via CLI."""
    directory.mkdir()
    source, total = make_source(documents, items)
    source_path = directory / "source.csv"
    source_path.write_bytes(source)
    workspace = directory / "workspace"
    command = [sys.executable, "-B", "-m", "neuron_flow", "csv", str(source_path),
               "--batch-id", "interrupted", "--workspace", str(workspace)]
    # Log files avoid filling pipes while polling a potentially large batch.
    with (directory / "controller.stdout").open("wb") as stdout, (directory / "controller.stderr").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=PROJECT, stdout=stdout, stderr=stderr)
        started = time.perf_counter()
        deadline = started + timeout
        try:
            while time.perf_counter() < deadline and process.poll() is None:
                try:
                    jobs, _, _ = database_state(workspace)
                except sqlite3.OperationalError:
                    # Startup creates the file before the schema is committed.
                    time.sleep(0.002)
                    continue
                completed = sum(row["receipt"] is not None for row in jobs.values())
                if 0 < completed < documents:
                    break
                time.sleep(0.002)
            else:
                raise RuntimeError("Could not interrupt after durable partial progress; recovery was not measured")
        finally:
            child_pids = controller_children(process.pid)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            # Also check cleanup on startup/polling failure, before propagating
            # that failure. Workers have their own parent-death watcher.
            wait_cleanup(workspace, child_pids)
    interrupted_s = time.perf_counter() - started
    before_jobs, before_steps, before_events = database_state(workspace)
    finished = {key: value for key, value in before_jobs.items() if value["receipt"] is not None}
    succeeded = {key: value for key, value in before_steps.items() if value["status"] == "SUCCEEDED"}
    if not finished or len(finished) >= documents or not succeeded:
        raise RuntimeError("Controller did not stop with completed and outstanding work")
    source_path.unlink()
    result, resume_s = cli(["batch-resume", "interrupted", "--workspace", str(workspace)], timeout)
    delivered = check_result(result, documents, total)
    after_jobs, after_steps, after_events = database_state(workspace)
    if (any(after_jobs.get(key) != value for key, value in finished.items())
            or any(after_steps.get(key) != value for key, value in succeeded.items())
            or after_events[:len(before_events)] != before_events):
        raise RuntimeError("Interrupted recovery rewrote completed work or existing events")
    if any(row["attempts"] > 2 for row in after_steps.values()):
        raise RuntimeError("Interrupted recovery exceeded the attempt limit")
    return {"documents": documents, "controller_exit_code": process.returncode,
            "seconds_before_kill": interrupted_s, "recovery_seconds": resume_s,
            "completed_jobs_at_stop": len(finished), "successful_steps_preserved": len(succeeded),
            "completed_work_unchanged": True, "source_removed_before_resume": True,
            "workspace_lock_released_before_resume": True,
            "observed_child_pids": child_pids,
            "observed_children_stopped": True if child_pids is not None else None,
            "artifact_hashes": delivered, **storage_bytes(workspace), "correctness_checked": True}


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=positive_int, nargs="+", default=[1, 10, 100], help="documents per batch")
    parser.add_argument("--items", type=positive_int, default=5, help="items per document (max 100)")
    parser.add_argument("--repeats", type=positive_int, default=5)
    parser.add_argument("--timeout", type=positive_float, default=180, help="seconds per CLI operation")
    parser.add_argument("--recovery-documents", type=positive_int, default=100,
                        help="separate interrupted batch, at least 10 documents")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.items > 100 or max(args.sizes) > 1000 or not 10 <= args.recovery_documents <= 1000:
        parser.error("bounded workload: items<=100, documents<=1000, recovery documents in [10,1000]")
    destination = args.output_dir.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        parser.error("choose a new or empty output directory; existing evidence is preserved")
    destination.mkdir(parents=True, exist_ok=True)
    report = {"version": __version__, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_fingerprint": source_fingerprint(),
              "python": sys.version, "platform": platform.platform(),
              "method": "wall time of complete CLI subprocess including startup/shutdown; nearest-rank p95; independent new workspace per sample",
              "items_per_document": args.items, "repeats": args.repeats,
              "cli_timeout_seconds": args.timeout, "results": [], "successful": False}
    try:
        for documents in dict.fromkeys(args.sizes):
            samples = [normal_sample(destination / f"batch-{documents}-sample-{index}", documents,
                                     args.items, args.timeout) for index in range(args.repeats)]
            times = [row["fresh_seconds"] for row in samples]
            resumes = [row["completed_resume_seconds"] for row in samples]
            median_s = statistics.median(times)
            report["results"].append({"documents": documents, "samples": samples,
                                      "batch_p50_seconds": median_s, "batch_p95_seconds": percentile(times, .95),
                                      "documents_per_second_at_p50": documents / median_s,
                                      "completed_resume_p50_seconds": statistics.median(resumes),
                                      "completed_resume_p95_seconds": percentile(resumes, .95)})
            print(f"{documents} documents: batch p50={median_s:.4f}s p95={percentile(times, .95):.4f}s", flush=True)
        report["recovery"] = interrupted_sample(destination / "interrupted", args.recovery_documents,
                                                  args.items, args.timeout)
        report["successful"] = True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print(f"Benchmark failed: {exc}", file=sys.stderr)
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        report["maximum_child_high_water_rss_bytes"] = int(rss if sys.platform == "darwin" else rss * 1024) if sys.platform == "darwin" or sys.platform.startswith("linux") else None
    except ImportError:
        report["maximum_child_high_water_rss_bytes"] = None
    report["memory_scope"] = "maximum waited-for child process high-water RSS across the whole benchmark, not simultaneous process-tree RSS or incremental allocation; unavailable on unsupported platforms"
    report["io_scope"] = "final SQLite/workspace bytes only, not cumulative writes or write amplification"
    (destination / "benchmark_runtime.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (destination / "benchmark_runtime.csv").open("w", newline="", encoding="utf-8") as output:
        fields = ["documents", "batch_p50_seconds", "batch_p95_seconds", "documents_per_second_at_p50",
                  "completed_resume_p50_seconds", "completed_resume_p95_seconds"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["results"])
    return 0 if report["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
