"""JSON contracts and workflow validation. No agent executes during submission."""

import hashlib
import json
import math
import re

MAX_MESSAGE_BYTES = 1_048_576
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


class SpecError(ValueError):
    pass


class TransientAgentError(Exception):
    """The same work may succeed on a bounded retry."""


class PermanentAgentError(Exception):
    """Retrying the same input will not fix it."""


def encode(value):
    """A bounded JSON-only wire format, also used for fingerprints."""
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise SpecError("Data must be finite, JSON-serializable values") from exc
    if len(data) > MAX_MESSAGE_BYTES:
        raise SpecError(f"Message exceeds {MAX_MESSAGE_BYTES} bytes")
    return data


def fingerprint(value):
    return hashlib.sha256(encode(value)).hexdigest()


def decode(data):
    """Reject duplicate JSON fields instead of silently discarding one value."""
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SpecError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise SpecError(f"Non-finite JSON number: {value}")

    if len(data.encode("utf-8") if isinstance(data, str) else data) > MAX_MESSAGE_BYTES:
        raise SpecError("Input JSON exceeds the message limit")
    try:
        return json.loads(data, object_pairs_hook=unique_fields, parse_constant=invalid_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise SpecError("Invalid JSON input") from exc


def _number(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise SpecError(f"{label} must be a number")
    try:
        valid = math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        valid = False
    if not valid:
        raise SpecError(f"{label} must be between {minimum} and {maximum}")
    return float(value)


def normalize_spec(spec, known_agents):
    # Serialize first: reject live Python objects and detach caller-owned data.
    spec = json.loads(encode(spec))
    if not isinstance(spec, dict) or set(spec) - {"job_id", "input", "steps"}:
        raise SpecError("Workflow must contain only job_id, input and steps")
    job_id = spec.get("job_id")
    if not isinstance(job_id, str) or not NAME.fullmatch(job_id):
        raise SpecError("job_id must use 1-80 letters, digits, hyphens or underscores")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 1000:
        raise SpecError("steps must contain 1-1000 steps")
    normalized = []
    identifiers = set()
    allowed = {"id", "agent", "depends_on", "params", "timeout_s", "max_attempts", "retry_delay_s"}
    for item in steps:
        if not isinstance(item, dict) or set(item) - allowed:
            raise SpecError("Invalid step fields")
        step_id, agent = item.get("id"), item.get("agent")
        if not isinstance(step_id, str) or not NAME.fullmatch(step_id) or step_id in identifiers:
            raise SpecError("Each step needs a unique, valid id")
        identifiers.add(step_id)
        if not isinstance(agent, str) or agent not in known_agents:
            raise SpecError(f"Unknown agent: {agent!r}")
        dependencies = item.get("depends_on", [])
        if (not isinstance(dependencies, list)
                or any(not isinstance(dep, str) for dep in dependencies)
                or len(dependencies) != len(set(dependencies))):
            raise SpecError("depends_on must be a list of unique step ids")
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise SpecError("params must be an object")
        attempts = item.get("max_attempts", 2)
        if type(attempts) is not int or not 1 <= attempts <= 5:
            raise SpecError("max_attempts must be an integer between 1 and 5")
        normalized.append({
            "id": step_id, "agent": agent, "depends_on": dependencies,
            "params": params,
            "timeout_s": _number(item.get("timeout_s", 5), 0.05, 3600, "timeout_s"),
            "max_attempts": attempts,
            "retry_delay_s": _number(item.get("retry_delay_s", 0.05), 0, 60, "retry_delay_s"),
        })
    by_id = {step["id"]: step for step in normalized}
    for step in normalized:
        if any(dep not in by_id for dep in step["depends_on"]):
            raise SpecError(f"Unknown dependency in {step['id']}")
    # Kahn's algorithm avoids recursion limits even with 1000-step chains.
    ordered, pending = [], dict(by_id)
    done = set()
    while pending:
        ready = [step for step in pending.values() if set(step["depends_on"]) <= done]
        if not ready:
            raise SpecError("Dependency cycle detected")
        for step in ready:
            ordered.append(step)
            done.add(step["id"])
            del pending[step["id"]]
    return {"job_id": job_id, "input": spec.get("input", {}), "steps": ordered}
