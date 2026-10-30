"""Read-only, evidence-bound explanations and comparisons of saved batch reports.

These functions inspect completed artifacts. They never open a Runtime, execute
Agents, change a workspace or publish a candidate result.
"""

from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import re

from .csv_input import MAX_SOURCE_BYTES
from .reporting import (ReportConflict, _same, _summary_fields, _summary_rows,
                        _validate_payload)


MAX_REPORT_BYTES = 64 * 1024 * 1024
_INDEX = r"(?:0|[1-9][0-9]*)"
_CLAIM_PATH = re.compile(
    r"^/(?:counts|certified_total|certified_totals|currency|"
    r"documents/" + _INDEX + r"/(?:document_id|document_status|engine_status|currency|"
    r"source_rows|declared_total|computed_total|difference|errors/" + _INDEX
    + r"/(?:row_number|field|reason_code|expected|actual))|"
    r"ungrouped_rows/" + _INDEX + r"/(?:source_row|errors))$"
)
_DOCUMENT_FIELDS = ("document_id", "document_status", "currency", "source_rows",
                    "declared_total", "computed_total", "difference", "errors", "engine_status")


def _read(path, limit):
    if path.is_symlink():
        raise ReportConflict(f"Report artifact is a symlink: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ReportConflict(f"Report artifact exceeds {limit} bytes: {path.name}")
    return data


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReportConflict(f"Duplicate report JSON field: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ReportConflict(f"Non-finite report JSON value: {value}")


def _read_report(directory):
    root = Path(directory)
    if root.is_symlink():
        raise ReportConflict("Report directory must not be a symlink")
    artifacts = {name: _read(root / name, limit) for name, limit in (
        ("details.json", MAX_REPORT_BYTES), ("source.csv", MAX_SOURCE_BYTES),
        ("summary.csv", MAX_REPORT_BYTES))}
    try:
        payload = json.loads(artifacts["details.json"], object_pairs_hook=_unique_fields,
                             parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReportConflict("Invalid details.json") from exc
    _validate_payload(payload, artifacts["source.csv"])
    if (any(not isinstance(payload.get(key), str) or not payload[key].strip()
            for key in ("batch_id", "system_version"))
            or not isinstance(payload.get("agent_versions"), dict)):
        raise ReportConflict("Report identity requires batch_id, system_version and agent_versions")
    try:
        reader = csv.DictReader(io.StringIO(artifacts["summary.csv"].decode("utf-8"), newline=""),
                                strict=True)
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ReportConflict("Invalid summary.csv") from exc
    if reader.fieldnames != list(_summary_fields(payload)) or not _same(rows, _summary_rows(payload)):
        raise ReportConflict("Summary differs from the checked details and source")
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}
    return payload, artifacts["source.csv"], hashes


def _value(payload, path):
    if not isinstance(path, str) or not _CLAIM_PATH.fullmatch(path):
        raise KeyError("Unsupported evidence path")
    value = payload
    for key in path.split("/")[1:]:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def score_claims(payload, claims):
    """Check exact typed values at allowed report paths, not external truth.

    An empty claim list does not establish support. Money remains a string;
    booleans, integers and floats cannot masquerade as each other.
    """
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    unsupported = []
    for index, claim in enumerate(claims):
        try:
            supported = (isinstance(claim, dict) and set(claim) == {"path", "value"}
                         and _same(_value(payload, claim["path"]), claim["value"]))
        except (KeyError, IndexError, TypeError, ValueError, OverflowError, RecursionError):
            supported = False
        if not supported:
            unsupported.append(index)
    return {"claims": len(claims), "supported": len(claims) - len(unsupported),
            "unsupported_claims": unsupported, "all_supported": bool(claims) and not unsupported,
            "scope": "Exact support in the checked report; no external factual assessment"}


def _claim(payload, path):
    return {"path": path, "value": deepcopy(_value(payload, path))}


def explain_report(directory, *, document_id=None):
    """Explain checked artifacts using only their recorded results and reasons."""
    payload, _, hashes = _read_report(directory)
    documents = []
    for index, document in enumerate(payload["documents"]):
        if document_id is not None and document["document_id"] != document_id:
            continue
        base = f"/documents/{index}"
        fields = [field for field in _DOCUMENT_FIELDS if field != "errors" and field in document]
        claims = [_claim(payload, f"{base}/{field}") for field in fields]
        reasons = []
        for error_index, error in enumerate(document["errors"]):
            paths = [f"{base}/errors/{error_index}/{field}"
                     for field in ("row_number", "field", "reason_code", "expected", "actual")]
            evidence = [_claim(payload, path) for path in paths]
            claims.extend(evidence)
            reasons.append({"row_number": error["row_number"], "field": error["field"],
                            "reason_code": error["reason_code"], "claims": evidence})
        status = document["document_status"]
        summary = {"VALID": "Configured field and exact monetary checks passed.",
                   "INVALID": "Recorded document checks failed; inspect the source-row reasons.",
                   "ERROR": "Processing failed; no computed amount is certified."}[status]
        documents.append({"document_id": document["document_id"], "document_status": status,
                          "summary": summary, "reasons": reasons, "claims": claims,
                          "verification": score_claims(payload, claims)})
    if document_id is not None and not documents:
        raise ValueError(f"Unknown document_id: {document_id}")
    ungrouped = [{"source_row": row["source_row"], "claims": [
        _claim(payload, f"/ungrouped_rows/{index}/source_row"),
        _claim(payload, f"/ungrouped_rows/{index}/errors")]}
        for index, row in enumerate(payload["ungrouped_rows"])]
    batch_claims = [_claim(payload, f"/{field}")
                    for field in ("counts", "currency", "certified_total", "certified_totals")
                    if field in payload]
    return {"schema": "neuron-flow-report-explanation-v1", "batch_id": payload["batch_id"],
            "source_sha256": payload["source_sha256"], "artifact_sha256": hashes,
            "batch_claims": batch_claims,
            "documents": documents, "ungrouped_rows": ungrouped,
            "scope": "Recorded purchase checks only; no supplier, fraud or payment approval"}


def _identity(payload, hashes):
    return {"batch_id": payload["batch_id"], "system_version": payload["system_version"],
            "agent_versions": deepcopy(payload["agent_versions"]), "artifact_sha256": hashes}


def compare_reports(reference_directory, candidate_directory):
    """Compare saved semantic outcomes for identical source and contract.

    Batch/job IDs, history timestamps, attempts and version labels are not
    outcome equality tests. Version labels and artifact hashes remain visible.
    """
    reference, source, reference_hashes = _read_report(reference_directory)
    candidate, candidate_source, candidate_hashes = _read_report(candidate_directory)
    if source != candidate_source or reference["contract_version"] != candidate["contract_version"]:
        raise ReportConflict("Comparison requires identical source bytes and the same data contract")
    differences = []

    def compare(path, before, after):
        if not _same(before, after):
            differences.append({"path": path, "reference": deepcopy(before), "candidate": deepcopy(after)})

    for field in ("counts", "currency", "certified_total", "certified_totals"):
        compare(f"/{field}", reference.get(field), candidate.get(field))
    for index, (before, after) in enumerate(zip(reference["documents"], candidate["documents"])):
        for field in _DOCUMENT_FIELDS:
            default = "THB" if field == "currency" else None
            compare(f"/documents/{index}/{field}", before.get(field, default), after.get(field, default))
    return {"schema": "neuron-flow-report-comparison-v1", "comparable": True,
            "agreement": not differences, "source_sha256": reference["source_sha256"],
            "contract_version": reference["contract_version"],
            "reference": _identity(reference, reference_hashes),
            "candidate": _identity(candidate, candidate_hashes),
            "documents_compared": len(reference["documents"]),
            "difference_count": len(differences), "differences": differences,
            "scope": "Offline comparison of checked saved reports; no candidate execution or publication"}
