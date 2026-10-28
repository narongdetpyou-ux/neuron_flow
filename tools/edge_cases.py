"""Generate deterministic mock inputs and check CSV functions plus the real CLI.

Run with --output-dir pointing to a new directory. Exit 1 means an unexpected
exception, traceback, timeout, result mismatch or integrity failure was found.
Expected INVALID data, rejected files and declared size limits are not crashes.
No production data, credentials, network or third-party packages are needed.
"""

import argparse
from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
import traceback

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from neuron_flow.csv_agents import compute_document, validate_document, verify_document
from neuron_flow.csv_input import CsvInputError, FIELDS, MAX_SOURCE_BYTES, read_csv_bytes
from neuron_flow.model import MessageSizeError


def csv_bytes(rows, header=FIELDS):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def purchase():
    return ["A", "I1", "สินค้า", "2", "0.10", "0.20", "THB"]


def csv_cases(seed, mutations):
    def case(name, data, statuses=None, outcome="handled", ungrouped=0, cli=False):
        return {"name": name, "data": data, "expected_outcomes": [outcome],
                "expected_statuses": statuses, "expected_ungrouped": ungrouped,
                "cli": cli}

    yield case("valid", csv_bytes([purchase()]), ["VALID"], cli=True)
    yield case("bom", b"\xef\xbb\xbf" + csv_bytes([purchase()]), ["VALID"], cli=True)
    yield case("header_only", csv_bytes([]), [], cli=True)
    fields = dict(zip(FIELDS, purchase()))
    yield case("reversed_headers", csv_bytes([[fields[f] for f in reversed(FIELDS)]],
                                             tuple(reversed(FIELDS))), ["VALID"])
    for name, index, value, status in [
        ("nul_id", 0, "A\x00Z", "VALID"), ("rtl_id", 0, "A\u202eZ", "VALID"),
        ("nul_text", 2, "hello\x00world", "VALID"),
        ("multiline_quotes", 2, 'first, "quoted"\r\nsecond', "VALID"),
        ("zero_width_text", 2, "\u200b", "VALID"),
        ("text_500", 2, "😀" * 500, "VALID"),
        ("text_501", 2, "😀" * 501, "INVALID"),
        ("trimmed_id", 0, " A ", "VALID"),
    ]:
        row = purchase()
        row[index] = value
        yield case(name, csv_bytes([row]), [status], cli=True)
    for field, values in {
        3: ["0", "-1", "1.5", "NaN", "Infinity", "1e309", "๑", " 2", "2 ", "1000001", "9" * 10000],
        4: ["-0.01", "0.001", "NaN", "Infinity", "1e3", "1000000000000.01"],
        5: ["-0.01", "0.001", "NaN", "Infinity", "1e22", "10000000000000000000000.01"],
    }.items():
        for index, value in enumerate(values):
            row = purchase()
            row[field] = value
            yield case(f"numeric_{field}_{index}", csv_bytes([row]), ["INVALID"])
    zero = purchase()
    zero[4:6] = ["0.00", "0.00"]
    yield case("zero_price", csv_bytes([zero]), ["VALID"], cli=True)
    mismatch = purchase()
    mismatch[5] = "0.21"
    yield case("total_mismatch", csv_bytes([mismatch]), ["INVALID"], cli=True)
    yield case("duplicate_item", csv_bytes([purchase(), purchase()]), ["INVALID"], cli=True)
    yield case("extra_column", csv_bytes([purchase() + ["extra"]]), ["INVALID"], cli=True)
    yield case("missing_columns", csv_bytes([["A"]]), ["INVALID"])
    no_id = purchase()
    no_id[0] = " \t "
    yield case("ungrouped", csv_bytes([no_id]), [], ungrouped=1, cli=True)
    invalid = purchase()
    invalid[0], invalid[3] = "B", "0"
    yield case("mixed", csv_bytes([purchase(), invalid, no_id]), ["VALID", "INVALID"],
               ungrouped=1, cli=True)
    for name, data in [
        ("empty", b""), ("invalid_utf8", csv_bytes([purchase()]) + b"\xff"),
        ("surrogate_utf8", csv_bytes([purchase()]).replace("สินค้า".encode(), b"\xed\xa0\x80")),
        ("unterminated_quote", csv_bytes([]) + b'A,I,"unterminated'),
        ("trailing_quote", csv_bytes([]) + b'A,I,"x"garbage,2,0.10,0.20,THB\n'),
        ("duplicate_header", csv_bytes([], FIELDS + ("item_id",))),
        ("missing_header", csv_bytes([], FIELDS[:-1])),
        ("extra_header", csv_bytes([], FIELDS + ("extra",))),
        ("source_over_16mib", b"x" * (MAX_SOURCE_BYTES + 1)),
    ]:
        yield case(name, data, outcome="rejected", cli=name != "source_over_16mib")
    rows = [["MAX", f"I{i}", "x", "1000000", "1000000000000.00",
             "10000000000000000000000.00", "THB"] for i in range(10000)]
    yield case("max_arithmetic_10000", csv_bytes(rows), ["VALID"])
    yield case("items_10001", csv_bytes(rows + [rows[0]]), ["INVALID"])
    # Workflow message limits must isolate ERROR documents rather than crash.
    large = [["BIG", f"I{i}", "x" * 500, "1", "1.00", "1000.00", "THB"]
             for i in range(1000)]
    yield case("oversized_isolated", csv_bytes(large + [purchase()]), ["VALID", "VALID"], cli=True)
    rng = random.Random(seed)
    alphabet = ["", "x", "\x00", "\r", "\n", '"', ",", "\ufeff", "\u200b", "\u00a0", "😀", "ก", "9", "-", ".", "e"]
    for index in range(mutations):
        row = purchase()
        row[rng.randrange(7)] = "".join(rng.choice(alphabet) for _ in range(rng.randrange(45)))
        rows = [row]
        if index % 5 == 0:
            other = purchase()
            other[1] = "I2"
            rows.append(other)
        data = csv_bytes(rows)
        if index % 11 == 0:
            changed = bytearray(data)
            changed[rng.randrange(len(changed))] = rng.randrange(256)
            data = bytes(changed)
        yield {"name": f"mutation_{index:04d}", "data": data,
               "expected_outcomes": ["handled", "rejected"],
               "expected_statuses": None, "expected_ungrouped": None, "cli": False}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def cents(value):
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def check_csv(case):
    row = {k: v for k, v in case.items() if k not in {"data", "cli"}}
    try:
        parsed = read_csv_bytes(case["data"])
        original = deepcopy(parsed)
        require(parsed["source_sha256"] == hashlib.sha256(case["data"]).hexdigest(), "source hash changed")
        all_rows = [r["source_row"] for d in parsed["documents"] for r in d["rows"]]
        all_rows += [r["source_row"] for r in parsed["ungrouped_rows"]]
        require(len(all_rows) == parsed["input_rows"] == len(set(all_rows)), "lost or duplicate rows")
        statuses = []
        for document in parsed["documents"]:
            validated = validate_document(document)
            result = verify_document(validated, compute_document(validated))
            statuses.append(result["document_status"])
            if result["document_status"] == "VALID":
                expected = sum(item["quantity"] * cents(item["unit_price"])
                               for item in validated["invoice"]["items"])
                require(cents(result["computed_total"]) == expected == cents(result["declared_total"]),
                        "certified total differs from integer oracle")
        require(parsed == original, "pipeline mutated source data")
        row.update(outcome="handled", statuses=statuses, ungrouped=len(parsed["ungrouped_rows"]))
        if case["expected_statuses"] is not None:
            require(statuses == case["expected_statuses"], "unexpected document status")
        if case["expected_ungrouped"] is not None:
            require(row["ungrouped"] == case["expected_ungrouped"], "unexpected ungrouped row count")
    except CsvInputError as exc:
        row.update(outcome="rejected", error=type(exc).__name__, message=str(exc)[:500])
    except MessageSizeError as exc:
        row.update(outcome="size_limit", error=exc.details())
    except Exception as exc:
        row.update(outcome="unexpected", error=type(exc).__name__, traceback=traceback.format_exc())
    row["passed"] = row["outcome"] in case["expected_outcomes"]
    return row


def run_cli(name, arguments, output, allowed_codes, timeout, expected_counts=None, expected_ungrouped=None):
    workspace = output / "workspaces" / name
    command = [sys.executable, "-B", "-m", "neuron_flow", *arguments,
               "--workspace", str(workspace), "--workers", "1"]
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=os.name == "posix")
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass  # The process may have exited between timeout and cleanup.
        stdout, stderr = process.communicate()
    row = {"name": name, "command": command, "allowed_exit_codes": allowed_codes,
           "exit_code": process.returncode, "timed_out": timed_out,
           "duration_seconds": time.perf_counter() - started, "stdout": stdout, "stderr": stderr}
    try:
        require(not timed_out, "CLI timed out")
        require("Traceback (most recent call last)" not in stdout + stderr, "unhandled CLI traceback")
        require(process.returncode in allowed_codes, "unexpected exit code")
        payload = json.loads(stderr if process.returncode == 2 else stdout)
        if process.returncode == 2:
            require(isinstance(payload, dict) and "error" in payload and "message" in payload,
                    "rejection was not machine-readable")
        if expected_counts is not None:
            require(payload["counts"] == expected_counts, "unexpected delivery counts")
            require(payload["ungrouped_rows"] == expected_ungrouped, "unexpected delivery ungrouped rows")
            for artifact in payload["receipt"]["artifacts"].values():
                data = Path(artifact["path"]).read_bytes()
                require(len(data) == artifact["bytes"] and hashlib.sha256(data).hexdigest() == artifact["sha256"],
                        "delivered artifact does not match its receipt")
            source = payload["receipt"]["artifacts"]["source.csv"]
            require(Path(source["path"]).read_bytes() == Path(arguments[1]).read_bytes(),
                    "delivered CSV differs from original mock input")
        row.update(passed=True, outcome="handled")
    except Exception as exc:
        row.update(passed=False, outcome="timeout" if timed_out else "unexpected", problem=str(exc))
    return row


def json_cases():
    for index, value in enumerate([None, [], True, 1, "text", {}, {"items": None}]):
        yield f"invoice_shape_{index}", "invoice", json.dumps(value).encode(), [1, 2]
    for index, data in enumerate([b'{', b'{"job_id":"a","job_id":"b"}', b'NaN',
                                  b'Infinity', b'"\xff"', b'[' * 1100 + b'0' + b']' * 1100,
                                  b'9' * 4500]):
        yield f"json_malformed_{index}", "run", data, [2]
    for index, steps in enumerate([None, [], [None], [{"id": "s", "agent": "echo", "params": None}],
                                   [{"id": "s", "agent": "echo", "depends_on": ["s"]}],
                                   [{"id": "s", "agent": "echo", "depends_on": [None]}]]):
        yield f"workflow_shape_{index}", "run", json.dumps({"job_id": "edge", "steps": steps}).encode(), [2]
    value = {"document_id": "A", "items": [{"item_id": "1", "description": "x", "quantity": True,
                                           "unit_price": "1.00"}]}
    yield "invoice_bool_quantity", "invoice", json.dumps(value).encode(), [1]
    value["items"][0].update(quantity=1, unit_price=0.1)
    yield "invoice_float_price", "invoice", json.dumps(value).encode(), [1]
    value["items"][0].update(unit_price="1.00", description="\ud800")
    yield "invoice_surrogate", "invoice", json.dumps(value).encode(), [2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--mutations", type=int, default=1500)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    if args.mutations < 0 or not 0 < args.timeout < 3600:
        parser.error("mutations must be nonnegative and timeout must be between 0 and 3600")
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("choose a new output directory to preserve existing evidence")
    mock = output / "mock-data"
    mock.mkdir(parents=True)
    direct, cli, manifest = [], [], []
    started = time.perf_counter()
    for case in csv_cases(args.seed, args.mutations):
        path = mock / (case["name"] + ".csv")
        path.write_bytes(case["data"])
        entry = {k: v for k, v in case.items() if k != "data"}
        entry.update(file=str(path.relative_to(output)), bytes=len(case["data"]),
                     sha256=hashlib.sha256(case["data"]).hexdigest())
        manifest.append(entry)
        result = check_csv(case)
        result["file"] = entry["file"]
        direct.append(result)
        if case["cli"]:
            print("CLI CSV:", case["name"], flush=True)
            counts = None
            if case["expected_outcomes"] == ["rejected"]:
                allowed = [2]
            elif case["name"] == "oversized_isolated":
                allowed, counts = [1], {"documents": 2, "VALID": 1, "INVALID": 0, "ERROR": 1}
            else:
                allowed = [0]
                states = case["expected_statuses"]
                counts = {"documents": len(states), "VALID": states.count("VALID"),
                          "INVALID": states.count("INVALID"), "ERROR": 0}
            cli.append(run_cli(case["name"], ["csv", str(path), "--batch-id", "edge"], output,
                               allowed, args.timeout, counts, case["expected_ungrouped"]))
    for name, command, data, allowed in json_cases():
        path = mock / (name + ".json")
        path.write_bytes(data)
        manifest.append({"name": name, "file": str(path.relative_to(output)), "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest(), "cli": command,
                         "allowed_exit_codes": allowed})
        cli.append(run_cli(name, [command, str(path)], output, allowed, args.timeout))
    for name, after, allowed in [
        ("events_min_int64", -(2 ** 63), [0]), ("events_max_int64", 2 ** 63 - 1, [0]),
        ("events_underflow", -(2 ** 63) - 1, [2]), ("events_overflow", 2 ** 63, [2]),
        ("events_huge_integer", 10 ** 100, [2]),
    ]:
        cli.append(run_cli(name, ["events", "nonexistent", "--after", str(after)], output, allowed, args.timeout))
    failures = [{"suite": suite, **row} for suite, rows in (("csv", direct), ("cli", cli))
                for row in rows if not row["passed"]]
    summary = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
               "seed": args.seed, "mutations": args.mutations,
               "elapsed_seconds": time.perf_counter() - started,
               "csv_cases": len(direct), "csv_outcomes": dict(Counter(row["outcome"] for row in direct)),
               "cli_cases": len(cli), "passed": len(direct) + len(cli) - len(failures),
               "unexpected_cases": len(failures), "timeouts": sum(row["timed_out"] for row in cli),
               "failed_case_names": [row["name"] for row in failures]}
    for name, data in [("manifest.json", manifest), ("results.json", {"summary": summary, "csv": direct, "cli": cli}),
                       ("failures.json", failures)]:
        (output / name).write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("Evidence:", output)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
