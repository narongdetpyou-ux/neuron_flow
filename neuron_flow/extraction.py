"""Versioned, bounded extraction alternatives and exact-input pure-result caching."""

import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
from importlib import metadata
from pathlib import Path
import time

from .document_input import DocumentInputError, prepare_document
from .supervision import OperationFailure, isolated, number, wire

METHODS = {"native": "1", "pdf-text": "1", "pdf-ocr": "1"}
POLICY_VERSION = "extraction-policy-v1"


def identity():
    packages = {}
    for name in ("pypdf", "openpyxl", "defusedxml", "Pillow", "pypdfium2"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source.update(path.name.encode() + b"\0" + path.read_bytes())
    return {"adapter": "document-intake-v1", "source_sha256": source.hexdigest(),
            "dependencies": packages, "money_policy": "exact-minor-units-v1"}


class ExtractionCache:
    def __init__(self, max_entries=0, max_bytes=16 * 1024 * 1024, ttl_s=60):
        if type(max_entries) is not int or not 0 <= max_entries <= 10000:
            raise ValueError("max_entries must be 0-10000")
        number(max_bytes, 1, 64 * 1024 * 1024, "max_bytes")
        number(ttl_s, .01, 86400, "ttl_s")
        self.maximum, self.max_bytes, self.ttl = max_entries, max_bytes, ttl_s
        self.entries = OrderedDict()
        self.bytes = self.hits = self.misses = self.evictions = 0

    def compute(self, key, compute, *, eligible=True):
        if self.maximum and eligible and key in self.entries:
            timestamp, value, size = self.entries.pop(key)
            self.bytes -= size
            if time.monotonic() - timestamp < self.ttl:
                self.entries[key] = (timestamp, value, size)
                self.bytes += size
                self.hits += 1
                return deepcopy(value), True
        self.misses += 1
        value = compute()
        if self.maximum and eligible:
            size = len(wire(value)) + len(key)
            if size <= self.max_bytes:
                self.entries[key] = (time.monotonic(), deepcopy(value), size)
                self.bytes += size
                while len(self.entries) > self.maximum or self.bytes > self.max_bytes:
                    _, (_, _, size) = self.entries.popitem(last=False)
                    self.bytes -= size
                    self.evictions += 1
        return deepcopy(value), False

    def stats(self):
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions,
                "entries": len(self.entries), "encoded_payload_bytes": self.bytes,
                "scope": "Pure extraction only; OCR excluded; verification and receipts never cached"}


def prepare_task(payload):
    options = payload["options"]
    result = prepare_document(base64.b64decode(payload["source_base64"], validate=True), payload["filename"], **options)
    result["csv"] = base64.b64encode(result["csv"]).decode() if result["csv"] is not None else None
    return result


class ExtractionEngine:
    def __init__(self, *, strategies=("native",), timeout_s=120, cache=None, cancelled=None, deadline=None):
        if (not isinstance(strategies, (list, tuple)) or not strategies or len(strategies) > 3
                or any(not isinstance(s, str) or s not in METHODS for s in strategies) or len(set(strategies)) != len(strategies)):
            raise ValueError("Use 1-3 unique registered extraction strategies")
        number(timeout_s, .05, 3600, "timeout_s")
        self.strategies, self.timeout_s = tuple(strategies), timeout_s
        self.cache = cache if cache is not None else ExtractionCache()
        self.cancelled = cancelled
        self.deadline = deadline
        self.environment = identity()

    def binding(self):
        return {"policy_version": POLICY_VERSION, "strategies": [{"id": s, "version": METHODS[s]} for s in self.strategies],
                "environment": self.environment, "timeout_s": self.timeout_s}

    def prepare(self, data, filename, *, sheet=None, ocr=False, language="eng"):
        deadline = min(time.monotonic() + self.timeout_s, self.deadline if self.deadline is not None else float('inf'))
        attempts = []
        result = None
        for method in self.strategies:
            options = {"sheet": sheet, "ocr": ocr, "language": language}
            if method != "native":
                if Path(filename).suffix.lower() != ".pdf":
                    continue
                options["ocr"] = method == "pdf-ocr"
            remaining = deadline - time.monotonic()
            if remaining < .05:
                break
            bound = {"source_sha256": hashlib.sha256(data).hexdigest(), "format": Path(filename).suffix.lower(),
                     "method": method, "method_version": METHODS[method], "options": options,
                     "environment": self.environment, "review_revision": None, "schema": POLICY_VERSION}
            key = hashlib.sha256(wire(bound)).hexdigest()
            payload = {"source_base64": base64.b64encode(data).decode(), "filename": filename, "options": options}
            start = time.monotonic()
            try:
                result, hit = self.cache.compute(key, lambda: isolated("neuron_flow.extraction:prepare_task", payload,
                    remaining, phase="extraction", cancelled=self.cancelled), eligible=not options["ocr"])
                empty = any(not p["text"].strip() for p in result["pages"])
                reason = "EMPTY_PAGE" if empty else "EXTRACTION_COMPLETE"
                attempts.append({"method": method, "method_version": METHODS[method], "params_sha256": key,
                                 "source_sha256": bound["source_sha256"], "cache_hit": hit,
                                 "elapsed_ms": (time.monotonic() - start) * 1000, "terminal_reason": reason,
                                 "candidate_sha256": hashlib.sha256(wire(result)).hexdigest()})
                if not empty:
                    break
            except OperationFailure as exc:
                attempts.append({"method": method, "params_sha256": key, "source_sha256": bound["source_sha256"],
                                 "elapsed_ms": (time.monotonic() - start) * 1000, "terminal_reason": exc.details["reason_code"]})
                if exc.details["reason_code"] in {"CANCELLED", "TIME_BUDGET_EXHAUSTED"}:
                    result = None
                    break
        if result is None:
            error = DocumentInputError("EXTRACTION_FAILED: no method completed within the policy budget")
            error.attempts = attempts
            raise error
        result["csv"] = base64.b64decode(result["csv"], validate=True) if result["csv"] is not None else None
        result["extraction_attempts"] = attempts
        result["extraction_policy"] = self.binding()
        return result
