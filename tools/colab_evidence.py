"""Validate a supplied Colab evidence assertion against package/fixture identity.

This reads local JSON only. It cannot remotely attest a Colab runtime or browser
download. A human-supplied assertion is accepted only when it is complete and
internally consistent; release approval never supplies missing acceptance facts.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import re


CHECKS = (
    "fresh_runtime", "csv_uploaded", "fixture_100_matched", "resume_no_repeated_steps",
    "artifact_hashes_match", "backup_received_confirmed", "restore_in_second_runtime",
    "resume_after_restore_no_repeated_steps",
)
ARTIFACTS = {"summary.csv", "details.json", "source.csv"}
STEPS = {"validate", "calculate", "verify"}
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_EVIDENCE_BYTES = 1024 * 1024


class _InvalidEvidence(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise _InvalidEvidence(reason)


def _object(value, keys, label):
    _require(isinstance(value, dict), f"{label} must be an object")
    missing = set(keys) - value.keys()
    extra = value.keys() - set(keys)
    _require(not missing and not extra,
             f"{label} fields mismatch: missing={sorted(missing)}, unexpected={sorted(extra)}")


def _string(value, label):
    _require(isinstance(value, str) and bool(value.strip()), f"{label} must be non-empty text")


def _hash(value, label):
    _require(isinstance(value, str) and SHA256.fullmatch(value) is not None,
             f"{label} must be a lowercase SHA-256 hex digest")


def _time(value, label):
    _string(value, label)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise _InvalidEvidence(f"{label} must be an ISO-8601 UTC timestamp") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0),
             f"{label} must include UTC timezone information")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise _InvalidEvidence(f"Non-finite JSON number: {value}")


def _snapshot(snapshot, label, fixture_sha256):
    _object(snapshot, {"artifact_hashes", "step_attempts"}, label)
    hashes = snapshot["artifact_hashes"]
    _object(hashes, ARTIFACTS, f"{label}.artifact_hashes")
    for name, digest in hashes.items():
        _hash(digest, f"{label}.artifact_hashes.{name}")
    _require(hashes["source.csv"] == fixture_sha256,
             f"{label}.artifact_hashes.source.csv differs from the fixture SHA-256")
    attempts = snapshot["step_attempts"]
    _require(isinstance(attempts, dict) and len(attempts) == 100,
             f"{label}.step_attempts must contain all 100 fixture jobs")
    for identifier, steps in attempts.items():
        _string(identifier, f"{label}.step_attempts job identifier")
        _object(steps, STEPS, f"{label}.step_attempts[{identifier}]")
        for step, count in steps.items():
            _require(type(count) is int and 1 <= count <= 2,
                     f"{label}.step_attempts[{identifier}].{step} must be an integer from 1 to 2")


def _validate(evidence, version, package_manifest_sha256, fixture_sha256):
    _object(evidence, {
        "schema_version", "status", "version", "package_manifest_sha256", "fixture_sha256",
        "source_sha256", "recorded_at_utc", "actual_runtime", "checks", "before", "after",
        "manual_download_confirmation",
    }, "evidence")
    _require(type(evidence["schema_version"]) is int and evidence["schema_version"] == 1,
             "schema_version must be integer 1")
    _require(evidence["status"] == "completed", "status must be completed; templates are not acceptance results")
    _string(version, "expected version")
    _require(isinstance(evidence["version"], str) and evidence["version"] == version,
             "Evidence version differs from the version under verification")
    _hash(package_manifest_sha256, "expected package_manifest_sha256")
    _hash(fixture_sha256, "expected fixture_sha256")
    for key in ("package_manifest_sha256", "fixture_sha256", "source_sha256"):
        _hash(evidence[key], key)
    _require(evidence["package_manifest_sha256"] == package_manifest_sha256,
             "package_manifest_sha256 differs from the known package")
    _require(evidence["fixture_sha256"] == fixture_sha256,
             "fixture_sha256 differs from the known fixture")
    _require(evidence["source_sha256"] == fixture_sha256,
             "source_sha256 differs from the known fixture")
    _time(evidence["recorded_at_utc"], "recorded_at_utc")

    runtime = evidence["actual_runtime"]
    _object(runtime, {"google_colab_importable", "runtime_marker_names", "python_version",
                      "runtime_version", "started_at_utc"}, "actual_runtime")
    _require(runtime["google_colab_importable"] is True,
             "actual_runtime.google_colab_importable must be true")
    markers = runtime["runtime_marker_names"]
    _require(isinstance(markers, list) and bool(markers),
             "actual_runtime.runtime_marker_names must be a non-empty list")
    for name in markers:
        _string(name, "actual_runtime.runtime_marker_names entry")
    _require(len(set(markers)) == len(markers), "actual_runtime.runtime_marker_names must be unique")
    _string(runtime["python_version"], "actual_runtime.python_version")
    _string(runtime["runtime_version"], "actual_runtime.runtime_version")
    _time(runtime["started_at_utc"], "actual_runtime.started_at_utc")

    _object(evidence["checks"], CHECKS, "checks")
    for check in CHECKS:
        _require(evidence["checks"][check] is True, f"checks.{check} must be boolean true")
    for label in ("before", "after"):
        _snapshot(evidence[label], label, fixture_sha256)
    _require(evidence["before"]["artifact_hashes"] == evidence["after"]["artifact_hashes"],
             "Artifact hashes changed between before and after")
    _require(evidence["before"]["step_attempts"] == evidence["after"]["step_attempts"],
             "Step attempts or job identifiers changed between before and after")

    download = evidence["manual_download_confirmation"]
    _object(download, {"actor", "confirmed_at_utc", "received"}, "manual_download_confirmation")
    _require(download["received"] is True, "manual_download_confirmation.received must be boolean true")
    _string(download["actor"], "manual_download_confirmation.actor")
    _time(download["confirmed_at_utc"], "manual_download_confirmation.confirmed_at_utc")


def validate_colab_evidence(path, *, version, package_manifest_sha256, fixture_sha256):
    """Return not_run/invalid/accepted without writing or changing any evidence.

    Supplying an incomplete template is invalid; omitting evidence is not_run.
    ``accepted`` means the supplied assertion passes these local checks. It is
    not automatic remote attestation that its claimed events actually occurred.
    """
    result = {"status": "not_run", "complete": False,
              "reason": "No actual Colab evidence was supplied", "evidence_path": None}
    if path is None:
        return result
    try:
        location = Path(path)
        result["evidence_path"] = str(location.resolve())
        with location.open("rb") as handle:
            data = handle.read(MAX_EVIDENCE_BYTES + 1)
        _require(len(data) <= MAX_EVIDENCE_BYTES, "Evidence JSON exceeds the 1 MiB bound")
        evidence = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                              parse_constant=_invalid_constant)
        _validate(evidence, version, package_manifest_sha256, fixture_sha256)
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        result.update(status="invalid", reason=f"Invalid Colab evidence: {exc}")
        return result
    result.update(status="accepted", complete=True,
                  reason="User-supplied evidence assertion matches the package/fixture and passes local consistency checks; not remote attestation")
    return result
