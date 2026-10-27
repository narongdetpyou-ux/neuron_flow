"""Importable child-process agents used only by the test suite."""

import os
import time

from neuron_flow.model import TransientAgentError, PermanentAgentError, encode


def validate_ok(message, result):
    if encode(result) != encode({"ok": True}):
        raise ValueError("Expected a typed success receipt")


def ok(message):
    return {"ok": True}


def transient_once(message):
    if message["attempt"] == 1:
        raise TransientAgentError("Temporary connection interruption")
    return ok(message)


def permanent(message):
    raise PermanentAgentError("Missing source data; retry cannot repair it")


def unexpected(message):
    raise ZeroDivisionError("Agent programming error")


def hangs_once(message):
    if message["attempt"] == 1:
        if "pid_file" in message["params"]:
            from pathlib import Path
            Path(message["params"]["pid_file"]).write_text(str(os.getpid()), encoding="utf-8")
        while True:
            time.sleep(0.05)
    return ok(message)


def hangs_always(message):
    while True:
        time.sleep(0.05)


def crashes_once(message):
    if message["attempt"] == 1:
        os._exit(23)
    return ok(message)


def wrong(message):
    return {"ok": False}


def wrong_type(message):
    return {"ok": 1}


def not_json(message):
    return {"value": {1, 2, 3}}


def nan_result(message):
    return {"value": float("nan")}


def huge_result(message):
    return {"value": "x" * 1_100_000}


def timed(message):
    started = time.monotonic()
    time.sleep(message["params"].get("duration", 0.1))
    return {"started": started, "finished": time.monotonic(), "pid": os.getpid()}


def validate_timed(message, result):
    if not (result["started"] <= result["finished"] and type(result["pid"]) is int):
        raise ValueError("Invalid timing receipt")


def wrong_total(message):
    from neuron_flow.agents import calculate_invoice
    result = calculate_invoice(message)
    result["total"] = "999.99"
    return result


def wrong_extract_type(message):
    from neuron_flow.agents import extract_invoice
    result = extract_invoice(message)
    result["items"][0]["quantity"] = True
    return result


def reject_with_false(message, result):
    return False


def modifies_output(message, result):
    result["extra"] = "changed by validator"
