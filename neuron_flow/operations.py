"""Durable bounded admission and one supervised worker per local workspace."""

import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .document_input import FORMATS, bounded_bytes
from .extraction import ExtractionCache, ExtractionEngine
from .intake import stage_document
from .model import NAME
from .storage import WorkspaceLock
from .supervision import OperationFailure, isolated, load_json, number, wire
from .telemetry import Telemetry

TERMINAL = {"COMPLETED", "REVIEW_REQUIRED", "FAILED", "TIMED_OUT", "CANCELLED", "EXPIRED"}


def request_model(value):
    allowed = {"idempotency_key", "filename", "source_base64", "timeout_s", "ocr", "language", "sheet", "run", "strategies"}
    if not isinstance(value, dict) or set(value) - allowed or not {"idempotency_key", "filename", "source_base64"} <= value.keys():
        raise ValueError("Request needs idempotency_key, filename and source_base64; unknown fields forbidden")
    key, filename = value["idempotency_key"], value["filename"]
    if not isinstance(key, str) or not NAME.fullmatch(key):
        raise ValueError("Invalid idempotency_key")
    if (not isinstance(filename, str) or len(filename) > 200 or Path(filename).name != filename
            or "\\" in filename or Path(filename).suffix.lower().lstrip('.') not in FORMATS):
        raise ValueError("Use a supported basename filename")
    data = bounded_bytes(base64.b64decode(value["source_base64"], validate=True))
    timeout = number(value.get("timeout_s", 120), .05, 3600, "timeout_s")
    for key in ("ocr", "run"):
        if key in value and type(value[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    language, sheet = value.get("language", "eng"), value.get("sheet")
    if not isinstance(language, str) or not 1 <= len(language) <= 80 or (sheet is not None and (not isinstance(sheet, str) or len(sheet) > 200)):
        raise ValueError("Invalid language or sheet")
    strategies = value.get("strategies", ["native"])
    # Constructing the engine validates the fixed registry; never accept an import path over HTTP.
    engine = ExtractionEngine(strategies=strategies, timeout_s=timeout)
    request = {"idempotency_key": value["idempotency_key"], "filename": filename, "timeout_s": timeout,
               "ocr": value.get("ocr", False), "run": value.get("run", True), "language": language,
               "sheet": sheet, "strategies": list(engine.strategies), "source_sha256": hashlib.sha256(data).hexdigest(),
               "schema": "document-job-v1", "environment": engine.environment}
    return request, data


def run_task(payload):
    from .intake import run_document
    telemetry = Telemetry()
    result = run_document(payload["workspace"], payload["intake_id"], workers=1, validation_timeout_s=5, telemetry=telemetry)
    result['operation_telemetry'] = telemetry.snapshot()
    return result


class JobQueue:
    def __init__(self, workspace, *, capacity=100, max_records=10000):
        if type(capacity) is not int or type(max_records) is not int or not 1 <= capacity <= max_records <= 100000:
            raise ValueError("Require 1 <= capacity <= max_records <= 100000")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.workspace / "operations.sqlite3", timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.stop_requested = threading.Event()
        self.capacity, self.max_records = capacity, max_records
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS operation_jobs (
                id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, binding TEXT NOT NULL, source BLOB NOT NULL,
                status TEXT NOT NULL, admitted REAL NOT NULL, deadline REAL NOT NULL, owner TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, cancel INTEGER NOT NULL DEFAULT 0, result TEXT);
            CREATE TABLE IF NOT EXISTS operation_events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                kind TEXT NOT NULL, at REAL NOT NULL, payload TEXT NOT NULL);
        ''')
        self.telemetry = Telemetry()
        self.cache = ExtractionCache(max_entries=32)

    @contextmanager
    def transaction(self, *, admission=False):
        with self.lock:
            admission_lock = WorkspaceLock(self.workspace / 'operations-admission.lock') if admission else None
            try:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    yield
                    self.db.commit()
                except BaseException:
                    self.db.rollback()
                    raise
            finally:
                if admission_lock is not None:
                    admission_lock.close()

    def event(self, job_id, kind, payload):
        self.db.execute("INSERT INTO operation_events(job_id,kind,at,payload) VALUES(?,?,?,?)",
                        (job_id, kind, time.time(), wire(payload).decode()))

    def submit(self, value):
        with self.telemetry.measure("admission"):
            request, data = request_model(value)
            binding = wire(request).decode()
            with self.transaction(admission=True):
                previous = self.db.execute("SELECT * FROM operation_jobs WHERE key=?", (request['idempotency_key'],)).fetchone()
                if previous is not None:
                    if previous['binding'] != binding:
                        raise ValueError("IDEMPOTENCY_CONFLICT: key already binds different source/settings")
                    identifier = previous['id']
                else:
                    count, active = self.db.execute("SELECT count(*),sum(status IN ('QUEUED','RUNNING')) FROM operation_jobs").fetchone()
                    if count >= self.max_records or (active or 0) >= self.capacity:
                        raise ValueError("QUEUE_FULL: admission capacity or retained-record limit reached")
                    identifier, now = uuid.uuid4().hex, time.time()
                    self.db.execute("INSERT INTO operation_jobs(id,key,binding,source,status,admitted,deadline) VALUES(?,?,?,?,?,?,?)",
                                    (identifier, request['idempotency_key'], binding, data, 'QUEUED', now, now + request['timeout_s']))
                    self.event(identifier, 'ACCEPTED', {'source_sha256': request['source_sha256']})
        return self.status(identifier)

    def status(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT * FROM operation_jobs WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Unknown job")
            return {"job_id": row['id'], "status": row['status'], "attempts": row['attempts'],
                    "source_sha256": json.loads(row['binding'])['source_sha256'],
                    "deadline_at": row['deadline'], "cancel_requested": bool(row['cancel']),
                    "result": json.loads(row['result']) if row['result'] is not None else None}

    def events(self, identifier, after=0):
        from .storage import validate_event_cursor
        validate_event_cursor(after)
        self.status(identifier)
        with self.lock:
            rows = self.db.execute("SELECT * FROM operation_events WHERE job_id=? AND cursor>? ORDER BY cursor LIMIT 1000",
                                   (identifier, after)).fetchall()
        return [{"cursor": row['cursor'], "kind": row['kind'], "at": row['at'],
                 "payload": json.loads(row['payload'])} for row in rows]

    def cancel(self, identifier):
        self.status(identifier)
        with self.transaction():
            changed = self.db.execute("UPDATE operation_jobs SET cancel=1, status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE status END WHERE id=? AND cancel=0 AND status IN ('QUEUED','RUNNING')", (identifier,)).rowcount
            if changed:
                self.event(identifier, 'CANCEL_REQUESTED', {})
        return self.status(identifier)

    def _finish(self, identifier, owner, status, result):
        with self.transaction():
            changed = self.db.execute("UPDATE operation_jobs SET status=?,result=?,owner=NULL WHERE id=? AND owner=? AND status='RUNNING'",
                                      (status, wire(result).decode(), identifier, owner)).rowcount
            if changed != 1:
                raise ValueError("Worker ownership changed")
            self.event(identifier, status, result)

    def drain_one(self):
        # This OS lock outlives any SQLite transaction and is released on process death.
        owner_lock = WorkspaceLock(self.workspace / 'operations-worker.lock')
        try:
            owner = uuid.uuid4().hex
            with self.transaction():
                interrupted = self.db.execute("SELECT id,attempts,cancel FROM operation_jobs WHERE status='RUNNING'").fetchall()
                for row in interrupted:
                    state = 'CANCELLED' if row['cancel'] else 'FAILED' if row['attempts'] >= 2 else 'QUEUED'
                    details = {'reason_code': 'CANCELLED' if row['cancel'] else 'INTERRUPTED_ATTEMPTS_EXHAUSTED', 'retryable': False}
                    self.db.execute("UPDATE operation_jobs SET status=?,owner=NULL,result=? WHERE id=?",
                                    (state, wire(details).decode() if state != 'QUEUED' else None, row['id']))
                    self.event(row['id'], 'WORKER_INTERRUPTED', {'retry_limit': 2, 'next_state': state})
                expired = self.db.execute("SELECT id FROM operation_jobs WHERE status='QUEUED' AND deadline<=?", (time.time(),)).fetchall()
                for row in expired:
                    details = {'phase': 'queue', 'reason_code': 'ADMISSION_DEADLINE_EXPIRED', 'retryable': False}
                    self.db.execute("UPDATE operation_jobs SET status='EXPIRED',result=? WHERE id=?", (wire(details).decode(), row['id']))
                    self.event(row['id'], 'EXPIRED', details)
                row = self.db.execute("SELECT * FROM operation_jobs WHERE status='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
                if row is None:
                    return None
                identifier = row['id']
                self.db.execute("UPDATE operation_jobs SET status='RUNNING',owner=?,attempts=attempts+1 WHERE id=?", (owner, identifier))
                self.event(identifier, 'RUNNING', {'owner': owner})
            request = load_json(row['binding'])
            def cancelled():
                return self.stop_requested.is_set() or self.status(identifier)['cancel_requested']
            staged = None
            try:
                self.telemetry.record('queue', max(0, (time.time() - row['admitted']) * 1000))
                remaining = row['deadline'] - time.time()
                engine = ExtractionEngine(strategies=request['strategies'], timeout_s=request['timeout_s'],
                                          cache=self.cache, cancelled=cancelled,
                                          deadline=time.monotonic() + max(0, remaining))
                if engine.environment != request['environment']:
                    raise ValueError("ADAPTER_VERSION_CHANGED: resubmit with a new idempotency key")
                with self.telemetry.measure('extraction'):
                    staged = stage_document(self.workspace, row['source'], request['filename'], sheet=request['sheet'],
                                            ocr=request['ocr'], language=request['language'], extraction_engine=engine)
                manifest = load_json((Path(staged['bundle']) / 'manifest.json').read_bytes())
                with self.transaction():
                    self.event(identifier, 'EXTRACTION_ATTEMPTS', manifest.get('extraction_attempts', []))
                    self.event(identifier, 'EXTRACTION_COMPLETE', {'intake_id': staged['intake_id'], 'batch_id': staged['batch_id']})
                if cancelled():
                    raise OperationFailure({'phase': 'queue', 'reason_code': 'CANCELLED', 'message': 'Cancelled before batch'})
                if staged['status'] == 'REVIEW_REQUIRED' or not request['run']:
                    state, result = ('REVIEW_REQUIRED' if staged['status'] == 'REVIEW_REQUIRED' else 'COMPLETED'), staged
                else:
                    with self.telemetry.measure('batch'):
                        result = isolated('neuron_flow.operations:run_task',
                            {'workspace': str(self.workspace), 'intake_id': staged['intake_id']},
                            max(.05, row['deadline'] - time.time()), phase='batch', cancelled=cancelled)
                    for sample in result['operation_telemetry']['samples']:
                        self.telemetry.record(sample['phase'], sample['elapsed_ms'], sample['outcome'])
                    state = 'COMPLETED' if result['batch']['status'] == 'DELIVERED' else 'FAILED'
                if time.time() > row['deadline']:
                    raise OperationFailure({'phase': 'queue', 'reason_code': 'TIME_BUDGET_EXHAUSTED', 'message': 'Job deadline exhausted'})
                self._finish(identifier, owner, state, result)
            except Exception as exc:
                details = exc.details if isinstance(exc, OperationFailure) else {
                    'reason_code': type(exc).__name__, 'message': str(exc)[:1000], 'attempts': getattr(exc, 'attempts', [])}
                if staged is not None:
                    details['intake_id'] = staged['intake_id']
                state = ('CANCELLED' if cancelled() or details['reason_code'] == 'CANCELLED' else
                         'TIMED_OUT' if time.time() > row['deadline'] or details['reason_code'] == 'TIME_BUDGET_EXHAUSTED' else 'FAILED')
                self._finish(identifier, owner, state, details)
            return self.status(identifier)
        finally:
            owner_lock.close()

    def metrics(self):
        with self.lock:
            counts = {row[0]: row[1] for row in self.db.execute("SELECT status,count(*) FROM operation_jobs GROUP BY status")}
        return {'jobs': counts, 'telemetry': self.telemetry.snapshot(), 'cache': self.cache.stats()}

    def close(self):
        self.db.close()
