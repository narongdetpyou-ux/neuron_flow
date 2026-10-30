"""Bounded phase samples and document-oriented descriptive drift, no policy writes."""

from collections import Counter, deque
from contextlib import contextmanager
import math
import os
from pathlib import Path
import time

from .supervision import number


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


class Telemetry:
    def __init__(self, retention=2000):
        if type(retention) is not int or not 1 <= retention <= 100000:
            raise ValueError("retention must be 1-100000")
        self.samples = deque(maxlen=retention)
        self.counts = Counter()

    def record(self, phase, elapsed_ms, outcome="OK"):
        number(elapsed_ms, 0, 1e12, "elapsed_ms")
        if phase not in {"admission", "queue", "extraction", "parsing", "agent", "validation", "calculation", "verification", "contract_validation", "batch", "delivery", "comparison"}:
            raise ValueError("Unknown telemetry phase")
        self.samples.append({"phase": phase, "elapsed_ms": elapsed_ms, "outcome": outcome})
        self.counts[phase] += 1

    @contextmanager
    def measure(self, phase):
        start = time.monotonic()
        outcome = "ERROR"
        try:
            yield
            outcome = "OK"
        finally:
            self.record(phase, (time.monotonic() - start) * 1000, outcome)

    def snapshot(self):
        phases = {}
        for phase, total in sorted(self.counts.items()):
            values = [s["elapsed_ms"] for s in self.samples if s["phase"] == phase]
            phases[phase] = {"total_count": total, "retained_count": len(values),
                             "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
                             "errors_retained": sum(s["outcome"] != "OK" for s in self.samples if s["phase"] == phase)}
        rss = None
        if os.name == "posix":
            try:
                rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            except (OSError, ValueError, IndexError):
                pass
        return {"phases": phases, "retained_samples": len(self.samples), "samples": list(self.samples), "controller_rss_bytes": rss,
                "memory_scope": "Controller only; child memory is not aggregated or estimated"}


def drift_report(reference, current):
    def profile(rows):
        if not isinstance(rows, list) or not rows:
            raise ValueError("Drift requires non-empty explicit reference/current profiles")
        categories = Counter()
        sizes = []
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"format", "status", "currency", "source_bytes"}
                    or any(not isinstance(row[k], str) for k in ("format", "status", "currency"))):
                raise ValueError("Invalid document profile")
            number(row["source_bytes"], 0, 16 * 1024 * 1024, "source_bytes")
            categories[(row["format"], row["status"], row["currency"])] += 1
            sizes.append(row["source_bytes"])
        return categories, sizes
    ref, rs = profile(reference)
    cur, cs = profile(current)
    distance = sum(abs(ref[k] / len(rs) - cur[k] / len(cs)) for k in ref.keys() | cur.keys()) / 2
    return {"reference_rows": len(rs), "current_rows": len(cs), "categorical_total_variation": distance,
            "reference_p95_source_bytes": percentile(rs, .95), "current_p95_source_bytes": percentile(cs, .95),
            "scope": "Descriptive document mix change; no significance, accuracy or automatic policy claim"}
