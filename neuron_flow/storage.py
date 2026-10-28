"""Single-controller SQLite state and append-only event records."""

import json
from pathlib import Path
import sqlite3
import time
import uuid

from .model import encode, fingerprint


def validate_event_cursor(after):
    """Reject cursors SQLite cannot bind without changing pagination semantics."""
    if type(after) is not int or not -(2 ** 63) <= after <= 2 ** 63 - 1:
        raise ValueError("Event cursor 'after' must be an integer in the signed 64-bit range "
                         "[-9223372036854775808, 9223372036854775807]")


class WorkspaceBusy(RuntimeError):
    pass


class WorkspaceLock:
    """OS lock is released automatically if the controller process dies."""

    def __init__(self, path):
        self.file = Path(path).open("a+b")
        try:
            if __import__("os").name == "nt":
                import msvcrt
                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise WorkspaceBusy("Another runtime is using this workspace") from exc

    def close(self):
        if self.file.closed:
            return
        if __import__("os").name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, spec TEXT NOT NULL,
            status TEXT NOT NULL, delivery_error TEXT, receipt TEXT
        );
        CREATE TABLE IF NOT EXISTS steps (
            job_id TEXT NOT NULL REFERENCES jobs(id), id TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            ready_at REAL NOT NULL DEFAULT 0, output TEXT, error TEXT,
            PRIMARY KEY(job_id, id)
        );
        CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
            job_id TEXT NOT NULL REFERENCES jobs(id), step_id TEXT, kind TEXT NOT NULL,
            audience TEXT NOT NULL, payload TEXT NOT NULL, timestamp REAL NOT NULL
        );
        """)

    def _event(self, event_id, job_id, step_id, kind, audience, payload):
        self.db.execute("INSERT OR IGNORE INTO events(event_id,job_id,step_id,kind,audience,payload,timestamp) VALUES(?,?,?,?,?,?,?)",
                        (event_id, job_id, step_id, kind, json.dumps(audience),
                         encode(payload).decode(), time.time()))

    def submit(self, spec):
        job_id, digest = spec["job_id"], fingerprint(spec)
        existing = self.db.execute("SELECT fingerprint FROM jobs WHERE id=?", (job_id,)).fetchone()
        if existing:
            if existing["fingerprint"] != digest:
                raise ValueError("job_id already exists with different input or steps")
            return False
        with self.db:
            self.db.execute("INSERT INTO jobs(id,fingerprint,spec,status) VALUES(?,?,?,?)",
                            (job_id, digest, encode(spec).decode(), "PENDING"))
            self.db.executemany("INSERT INTO steps(job_id,id,status) VALUES(?,?,?)",
                                [(job_id, step["id"], "PENDING") for step in spec["steps"]])
            self._event(f"{job_id}:submitted", job_id, None, "job.submitted", ["soma", "monitor"], {})
        return True

    def job(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown job: {job_id}")
        result = dict(row)
        for key in ("spec", "receipt"):
            if result[key] is not None:
                result[key] = json.loads(result[key])
        return result

    def steps(self, job_id):
        result = {}
        for row in self.db.execute("SELECT * FROM steps WHERE job_id=? ORDER BY rowid", (job_id,)):
            value = dict(row)
            for key in ("output", "error"):
                if value[key] is not None:
                    value[key] = json.loads(value[key])
            result[value["id"]] = value
        return result

    def transition(self, job_id, step_id, status, attempts, *, output=None, error=None,
                   ready_at=0, audience=()):
        with self.db:
            self.db.execute("UPDATE steps SET status=?,attempts=?,output=?,error=?,ready_at=? WHERE job_id=? AND id=?",
                            (status, attempts, None if output is None else encode(output).decode(),
                             None if error is None else encode(error).decode(), ready_at, job_id, step_id))
            self._event(f"{job_id}:{step_id}:{attempts}:{status}", job_id, step_id,
                        f"step.{status.lower()}", list(dict.fromkeys(["soma", "monitor", *audience])),
                        {"attempt": attempts, "error": error})

    def job_status(self, job_id, status, *, receipt=None, error=None):
        with self.db:
            self.db.execute("UPDATE jobs SET status=?,receipt=?,delivery_error=? WHERE id=?",
                            (status, None if receipt is None else encode(receipt).decode(), error, job_id))
            self._event(f"{job_id}:{status}:{uuid.uuid4().hex}", job_id, None, f"job.{status.lower()}",
                        ["soma", "monitor", "terminal"], {"error": error, "receipt": receipt})

    def events_for(self, recipient, job_id, after=0):
        validate_event_cursor(after)
        result = []
        for row in self.db.execute("SELECT * FROM events WHERE job_id=? AND sequence>? ORDER BY sequence", (job_id, after)):
            event = dict(row)
            event["audience"], event["payload"] = json.loads(event["audience"]), json.loads(event["payload"])
            if recipient in event["audience"]:
                result.append(event)
        return result

    def close(self):
        self.db.close()
