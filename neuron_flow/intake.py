"""Atomic document intake bundles, explicit receipt review and batch handoff."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .batch import BatchRuntime
from .csv_input import FIELDS, read_csv_bytes
from .document_input import DocumentInputError, bounded_bytes, prepare_document, read_source


ADAPTER_VERSION = "document-intake-v1"


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _folder(workspace, intake_id):
    if not isinstance(intake_id, str) or not re.fullmatch(r"[a-f0-9]{40}", intake_id):
        raise DocumentInputError("INTAKE_ID: expected the 40-character ID returned by intake")
    return Path(workspace).resolve() / "intakes" / intake_id


def _write(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _load(workspace, intake_id):
    folder = _folder(workspace, intake_id)
    manifest_bytes = read_source(folder / "manifest.json")
    manifest = json.loads(manifest_bytes)
    if manifest.get("adapter_version") != ADAPTER_VERSION or manifest.get("intake_id") != intake_id:
        raise DocumentInputError("INTAKE_CONFLICT: incompatible manifest")
    original = read_source(folder / "original.bin")
    if _sha(original) != manifest["source_sha256"]:
        raise DocumentInputError("INTAKE_CONFLICT: source SHA-256 does not match")
    if _sha(_json(manifest["binding"]))[:40] != intake_id:
        raise DocumentInputError("INTAKE_CONFLICT: identity does not match")
    if manifest["binding"]["source_sha256"] != manifest["source_sha256"]:
        raise DocumentInputError("INTAKE_CONFLICT: source identity does not match")
    if manifest.get('format') != manifest['binding'].get('format'):
        raise DocumentInputError('INTAKE_CONFLICT: format differs from the immutable binding')
    if 'extraction_policy' in manifest['binding'] and _json(manifest.get('extraction_policy')) != _json(manifest['binding']['extraction_policy']):
        raise DocumentInputError('INTAKE_CONFLICT: extraction policy differs from the immutable binding')
    normalized = None
    if manifest["normalized_sha256"] is not None:
        normalized = read_source(folder / "normalized.csv")
        if _sha(normalized) != manifest["normalized_sha256"]:
            raise DocumentInputError("INTAKE_CONFLICT: normalized CSV SHA-256 does not match")
    return folder, manifest, manifest_bytes, normalized


def stage_document(workspace, data, filename, *, sheet=None, ocr=False, language="eng", origin=None, extraction_engine=None):
    """Persist an immutable source/normalization bundle before any processing."""
    bounded_bytes(data)
    binding = {"adapter_version": ADAPTER_VERSION, "source_sha256": _sha(data),
               "format": Path(filename).suffix.lower().lstrip("."), "sheet": sheet,
               "ocr": ocr, "language": language, "origin": origin or {"provider": "local"}}
    if extraction_engine is not None:
        binding["extraction_policy"] = extraction_engine.binding()
    intake_id = _sha(_json(binding))[:40]
    folder = _folder(workspace, intake_id)
    if folder.exists():
        _load(workspace, intake_id)
        # Resubmission does not rerun OCR/parsers, and can reuse a complete
        # bundle even after optional dependencies have been removed.
        return intake_status(workspace, intake_id)
    prepare = prepare_document if extraction_engine is None else extraction_engine.prepare
    prepared = prepare(data, filename, sheet=sheet, ocr=ocr, language=language)
    normalized = prepared.pop("csv")
    manifest = {**prepared, "binding": binding, "adapter_version": ADAPTER_VERSION,
                "intake_id": intake_id, "filename": Path(filename).name,
                "source_sha256": _sha(data),
                "normalized_sha256": _sha(normalized) if normalized is not None else None,
                "status": "READY" if normalized is not None else "REVIEW_REQUIRED"}
    manifest_content = bounded_bytes(_json(manifest))
    _store_bundle(folder, data, manifest_content, normalized)
    return intake_status(workspace, intake_id)


def _store_bundle(folder, data, manifest_content, normalized):
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".staging-", dir=folder.parent))
    try:
        _write(temporary / "original.bin", data)
        _write(temporary / "manifest.json", manifest_content)
        if normalized is not None:
            _write(temporary / "normalized.csv", normalized)
        else:
            _write(temporary / "review_template.csv", (",".join(FIELDS) + "\n").encode("utf-8"))
        try:
            os.rename(temporary, folder)
        except OSError:
            if not folder.is_dir():
                raise
            _load(folder.parent.parent, folder.name)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _approved(folder, manifest_bytes):
    approval = json.loads(read_source(folder / "approval.json"))
    normalized = approval["csv"].encode("utf-8")
    if (approval["manifest_sha256"] != _sha(manifest_bytes)
            or approval["csv_sha256"] != _sha(normalized)
            or not isinstance(approval.get("reviewer"), str) or not approval["reviewer"].strip()):
        raise DocumentInputError("REVIEW_CONFLICT: review is not bound to this manifest and CSV")
    read_csv_bytes(normalized)
    return approval, normalized


def intake_status(workspace, intake_id):
    folder, manifest, manifest_bytes, normalized = _load(workspace, intake_id)
    status = manifest["status"]
    if normalized is None and (folder / "approval.json").exists():
        approval, normalized = _approved(folder, manifest_bytes)
        status = "REVIEWED"
        reviewer = approval["reviewer"]
    else:
        reviewer = None
    return {"intake_id": intake_id, "status": status, "format": manifest["format"],
            "batch_id": "intake_" + intake_id,
            "bundle": str(folder), "source_sha256": manifest["source_sha256"],
            "normalized_sha256": _sha(normalized) if normalized is not None else None,
            "review_reasons": manifest["review_reasons"], "reviewer": reviewer}


def review_document(workspace, intake_id, reviewed_csv, reviewer):
    folder, manifest, manifest_bytes, normalized = _load(workspace, intake_id)
    if normalized is not None:
        raise DocumentInputError("REVIEW_NOT_NEEDED: structured data already has a normalized CSV")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
        raise DocumentInputError("REVIEWER: provide a non-empty reviewer name of at most 200 characters")
    parsed = read_csv_bytes(reviewed_csv)
    if not parsed["documents"] or parsed["ungrouped_rows"]:
        raise DocumentInputError("REVIEW_ROWS: at least one identified document and no ungrouped rows required")
    approval = {"source_sha256": manifest["source_sha256"], "manifest_sha256": _sha(manifest_bytes),
                "csv_sha256": _sha(reviewed_csv), "reviewer": reviewer.strip(),
                "csv": reviewed_csv.decode("utf-8")}
    content = _json(approval)
    if len(content) > 16 * 1024 * 1024:
        raise DocumentInputError("REVIEW_LIMIT: encoded review is too large")
    if (folder / "approval.json").exists():
        if read_source(folder / "approval.json") != content:
            _approved(folder, manifest_bytes)
            # A corrected review gets a new intake/batch identity. Preserve the
            # original source and any completed financial reports unchanged.
            binding = {**manifest["binding"], "review_revision_sha256": _sha(content)}
            revision_id = _sha(_json(binding))[:40]
            revision_manifest = {**manifest, "intake_id": revision_id, "binding": binding,
                                 "supersedes_intake_id": intake_id}
            revision_folder = _folder(workspace, revision_id)
            if not revision_folder.exists():
                _store_bundle(revision_folder, read_source(folder / "original.bin"),
                              bounded_bytes(_json(revision_manifest)), None)
            return review_document(workspace, revision_id, reviewed_csv, reviewer)
    else:
        # Write a complete file, then link it exclusively. Concurrent reviewers
        # can never overwrite an approval or expose a half-written JSON file.
        descriptor, temporary_name = tempfile.mkstemp(prefix=".review-", dir=folder)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.unlink()
            _write(temporary, content)
            try:
                os.link(temporary, folder / "approval.json")
            except FileExistsError:
                if read_source(folder / "approval.json") != content:
                    raise DocumentInputError("REVIEW_CONFLICT: concurrent review differs") from None
        finally:
            temporary.unlink(missing_ok=True)
    return intake_status(workspace, intake_id)


def run_document(workspace, intake_id, *, workers=3, submit_only=False, validation_timeout_s=None, telemetry=None):
    folder, manifest, manifest_bytes, normalized = _load(workspace, intake_id)
    if normalized is None:
        if not (folder / "approval.json").exists():
            raise DocumentInputError("REVIEW_REQUIRED: review the receipt and submit reviewed CSV first")
        _, normalized = _approved(folder, manifest_bytes)
    batch_id = "intake_" + intake_id
    with BatchRuntime(workspace, max_workers=workers, validation_timeout_s=validation_timeout_s, telemetry=telemetry) as batch:
        submitted = batch.submit(normalized, batch_id)
        result = batch.status(batch_id) if submit_only else batch.deliver(batch_id)
    return {"intake": intake_status(workspace, intake_id), "batch_id": submitted["batch_id"], "batch": result}
