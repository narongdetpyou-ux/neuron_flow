"""Hard deadlines for trusted importable operations using bounded JSON files.

POSIX cancellation terminates the process group, including OCR descendants.
This is failure isolation, not a security sandbox for hostile Python code.
"""

import importlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

MAX_OPERATION_BYTES = 64 * 1024 * 1024


def number(value, minimum, maximum, label):
    valid = False
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        try:
            valid = math.isfinite(value) and minimum <= value <= maximum
        except OverflowError:
            pass
    if not valid:
        raise ValueError(f"{label} must be finite and between {minimum} and {maximum}")
    return value


def wire(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(data) > MAX_OPERATION_BYTES:
        raise ValueError("Operation JSON exceeds the 64 MiB transport limit")
    return data


def load_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    result = json.loads(data, object_pairs_hook=unique)
    wire(result)
    return result


class OperationFailure(ValueError):
    def __init__(self, details):
        self.details = details
        super().__init__(f"{details['reason_code']}: {details.get('message', '')}")


def _group_active(group):
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rpartition(') ')[2].split()
            if int(fields[2]) == group and fields[0] not in {'Z', 'X'}:
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def terminate_tree(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    if os.name == 'posix' and Path('/proc/self/stat').is_file():
        deadline = time.monotonic() + 2
        while _group_active(process.pid):
            if time.monotonic() >= deadline:
                raise RuntimeError('Process group cleanup did not complete within its budget')
            time.sleep(.005)


def isolated(entrypoint, payload, timeout_s, *, phase="operation", cancelled=None):
    number(timeout_s, .05, 3600, "timeout_s")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="neuron-operation-") as directory:
        root = Path(directory)
        (root / "request.json").write_bytes(wire({"entrypoint": entrypoint, "payload": payload}))
        process = subprocess.Popen([sys.executable, "-B", "-m", "neuron_flow.supervision", str(root), str(os.getpid())],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=os.name == "posix")
        try:
            while process.poll() is None:
                reason = ("CANCELLED" if cancelled is not None and cancelled() else
                          "TIME_BUDGET_EXHAUSTED" if time.monotonic() - started >= timeout_s else None)
                if reason:
                    raise OperationFailure({"phase": phase, "reason_code": reason, "retryable": False,
                                            "elapsed_ms": (time.monotonic() - started) * 1000,
                                            "budget_ms": timeout_s * 1000, "message": "Operation cancelled"})
                time.sleep(.01)
            path = root / "response.json"
            if process.returncode or not path.is_file():
                raise OperationFailure({"phase": phase, "reason_code": "WORKER_EXIT", "retryable": False,
                                        "message": "Operation worker exited without a complete response"})
            with path.open("rb") as stream:
                response = load_json(stream.read(MAX_OPERATION_BYTES + 1))
            if not response["ok"]:
                raise OperationFailure({"phase": phase, "reason_code": response["type"],
                                        "retryable": False, "message": response["message"],
                                        "attempts": response.get("attempts", [])})
            if time.monotonic() - started >= timeout_s:
                raise OperationFailure({"phase": phase, "reason_code": "TIME_BUDGET_EXHAUSTED",
                                        "retryable": False, "message": "Result arrived after the deadline"})
            return response["result"]
        finally:
            terminate_tree(process)


def _watch_parent(parent):
    if os.name == "posix":
        while os.getppid() == parent:
            time.sleep(.1)
        os.killpg(os.getpgrp(), signal.SIGKILL)


def _execute(root, parent):
    threading.Thread(target=_watch_parent, args=(parent,), daemon=True).start()
    try:
        request = load_json((root / "request.json").read_bytes())
        module, name = request["entrypoint"].split(":", 1)
        function = importlib.import_module(module)
        for part in name.split("."):
            function = getattr(function, part)
        response = {"ok": True, "result": function(request["payload"])}
        data = wire(response)
    except BaseException as exc:
        data = wire({"ok": False, "type": type(exc).__name__, "message": str(exc)[:1000],
                     "attempts": getattr(exc, "attempts", [])})
    temporary = root / "response.tmp"
    temporary.write_bytes(data)
    temporary.replace(root / "response.json")


def validate_agent(payload):
    from .model import encode
    module, name = payload["validator"].split(":", 1)
    validator = importlib.import_module(module)
    for part in name.split("."):
        validator = getattr(validator, part)
    before = encode(payload["output"])
    result = validator(payload["message"], payload["output"])
    if result is not None and result is not True:
        raise ValueError("Validator rejected the result")
    if before != encode(payload["output"]):
        raise ValueError("Validator must not modify the result")
    return True


if __name__ == "__main__":
    _execute(Path(sys.argv[1]), int(sys.argv[2]))
