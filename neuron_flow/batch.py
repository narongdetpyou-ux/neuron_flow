"""Durable, single-controller CSV batches built on the five-part runtime.

Each document owns an independent workflow. Workers are reused across documents;
completed workflows are never run again. SQLite owns the original source bytes,
identity binding, preparation failures and a frozen final report payload.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from . import __version__
from .csv_agents import CONTRACT_VERSION, FINAL_FIELDS, csv_agent_definitions, csv_workflow
from .csv_input import read_csv_bytes
from .engine import Runtime
from .model import NAME, SpecError, encode


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _money(cents):
    return f'{cents // 100}.{cents % 100:02d}'


class BatchConflict(ValueError):
    """An existing batch or artifact has a different immutable identity."""


class BatchRuntime:
    """Use as a context manager; the existing Runtime owns the workspace lock."""

    def __init__(self, workspace, *, max_workers=3, agents=None, timeout_s=5):
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or not 0.05 <= timeout_s <= 3600):
            raise ValueError('timeout_s must be a finite number between 0.05 and 3600')
        definitions = list(csv_agent_definitions() if agents is None else agents)
        if {agent.name for agent in definitions} != {'csv_validate', 'csv_calculate', 'csv_verify'}:
            raise ValueError('Batch agents must define csv_validate, csv_calculate and csv_verify')
        self.timeout_s = float(timeout_s)
        self.agent_versions = {agent.name: {'entrypoint': agent.entrypoint, 'version': agent.version,
                               'validator': f'{agent.validator.__module__}:{agent.validator.__qualname__}'}
                               for agent in definitions}
        self.runtime = Runtime(workspace, max_workers=max_workers, agents=definitions)
        self.workspace = self.runtime.workspace
        try:
            self.runtime.store.db.executescript('''
            CREATE TABLE IF NOT EXISTS csv_batches (
                id TEXT PRIMARY KEY, identity TEXT NOT NULL, source BLOB NOT NULL,
                manifest TEXT NOT NULL, status TEXT NOT NULL, payload TEXT,
                receipt TEXT, delivery_error TEXT
            );
            CREATE TABLE IF NOT EXISTS csv_batch_documents (
                batch_id TEXT NOT NULL REFERENCES csv_batches(id), ordinal INTEGER NOT NULL,
                job_id TEXT NOT NULL UNIQUE, document TEXT NOT NULL, preparation_error TEXT,
                PRIMARY KEY(batch_id, ordinal)
            );
            ''')
        except BaseException:
            self.runtime.close()
            raise

    def __enter__(self):
        self.runtime.__enter__()
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.runtime.close()

    def _batch(self, batch_id):
        self.__enter__()
        row = self.runtime.store.db.execute('SELECT * FROM csv_batches WHERE id=?', (batch_id,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown batch: {batch_id}')
        row = dict(row)
        for name in ('manifest', 'payload', 'receipt'):
            if row[name] is not None:
                row[name] = json.loads(row[name])
        manifest = row['manifest']
        if (manifest['contract_version'] != CONTRACT_VERSION
                or manifest['system_version'] != __version__
                or manifest['agent_versions'] != self.agent_versions):
            raise BatchConflict('Batch contract, system or Agent version changed; restore it or use a new batch_id')
        if hashlib.sha256(row['source']).hexdigest() != manifest['source_sha256']:
            raise BatchConflict('Stored source bytes no longer match their SHA-256')
        return row

    def _documents(self, batch_id):
        return [dict(row) for row in self.runtime.store.db.execute(
            'SELECT * FROM csv_batch_documents WHERE batch_id=? ORDER BY ordinal', (batch_id,))]

    def submit(self, source, batch_id=None):
        """Reject malformed files before submission; bind IDs to exact source bytes."""
        self.__enter__()
        parsed = read_csv_bytes(source)
        binding = {'source_sha256': parsed['source_sha256'], 'contract_version': CONTRACT_VERSION,
                   'system_version': __version__, 'agent_versions': self.agent_versions,
                   'timeout_s': self.timeout_s, 'max_attempts': 2}
        identity = _digest(binding)
        batch_id = f'batch_{identity[:32]}' if batch_id is None else batch_id
        if not isinstance(batch_id, str) or not NAME.fullmatch(batch_id):
            raise ValueError('batch_id must use 1-80 letters, digits, hyphens or underscores')
        existing = self.runtime.store.db.execute('SELECT identity FROM csv_batches WHERE id=?', (batch_id,)).fetchone()
        if existing:
            if existing['identity'] != identity:
                raise BatchConflict('batch_id conflicts with different source bytes, contract, Agent versions or workflow settings')
            self._batch(batch_id)
            return {'batch_id': batch_id, 'created': False}
        manifest = {**binding, 'input_rows': parsed['input_rows'],
                    'ungrouped_rows': parsed['ungrouped_rows']}
        records = []
        for ordinal, document in enumerate(parsed['documents']):
            job_id = 'doc_' + _digest([batch_id, document['document_id']])
            records.append((batch_id, ordinal, job_id, _json(document)))
        db = self.runtime.store.db
        with db:
            db.execute('INSERT INTO csv_batches(id,identity,source,manifest,status) VALUES(?,?,?,?,?)',
                       (batch_id, identity, source, _json(manifest), 'PENDING'))
            db.executemany('INSERT INTO csv_batch_documents(batch_id,ordinal,job_id,document) VALUES(?,?,?,?)', records)
        return {'batch_id': batch_id, 'created': True}

    def _verify_job_receipt(self, snapshot):
        receipt = snapshot['receipt']
        if receipt is None:
            raise BatchConflict('Completed workflow has no delivery receipt')
        path = Path(receipt['path'])
        expected = self.workspace / 'reports' / f"{snapshot['job_id']}.json"
        if path.resolve() != expected.resolve():
            raise BatchConflict('Workflow receipt points outside its expected report')
        report = {'job_id': snapshot['job_id'], 'status': snapshot['status'], 'steps': {
            key: {field: value[field] for field in ('status', 'attempts', 'output', 'error')}
            for key, value in snapshot['steps'].items()}}
        expected_bytes = encode(report) + b'\n'
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise BatchConflict('Completed workflow report is missing or unreadable') from exc
        if (actual != expected_bytes or len(actual) != receipt['bytes']
                or hashlib.sha256(actual).hexdigest() != receipt['sha256']):
            raise BatchConflict('Completed workflow report differs from its verified receipt')

    def _verify_completed_jobs(self, batch_id):
        for record in self._documents(batch_id):
            if record['preparation_error'] is not None:
                continue
            snapshot = self.runtime.status(record['job_id'])
            if snapshot['receipt'] is not None:
                self._verify_job_receipt(snapshot)

    def _error_document(self, document, error):
        return {'document_id': document['document_id'], 'document_status': 'ERROR',
                'source_rows': [row['source_row'] for row in document['rows']],
                'computed_total': None, 'declared_total': None, 'difference': None,
                'errors': [{'row_number': document['rows'][0]['source_row'], 'field': '*',
                            'reason_code': 'ENGINE_ERROR', 'expected': 'verified document result', 'actual': error}]}

    def _document_result(self, record):
        document = json.loads(record['document'])
        if record['preparation_error'] is not None:
            result = self._error_document(document, json.loads(record['preparation_error']))
            snapshot = {'status': 'REJECTED', 'steps': {}}
            history = []
        else:
            snapshot = self.runtime.status(record['job_id'])
            if snapshot['status'] in {'SUCCEEDED', 'FAILED'} and snapshot['receipt'] is not None:
                self._verify_job_receipt(snapshot)
            else:
                snapshot = self.runtime.run(record['job_id'])
                if snapshot['receipt'] is not None:
                    self._verify_job_receipt(snapshot)
            if snapshot['status'] == 'SUCCEEDED':
                output = snapshot['steps']['verify']['output']
                result = {field: deepcopy(output[field]) for field in FINAL_FIELDS}
            else:
                error = {'engine_status': snapshot['status'], 'delivery_error': snapshot['delivery_error'],
                         'failed_steps': {key: value['error'] for key, value in snapshot['steps'].items()
                                          if value['status'] == 'FAILED'}}
                result = self._error_document(document, error)
                validated = snapshot['steps']['validate']['output']
                if validated is not None:
                    result['declared_total'] = validated['declared_total']
            history = self.runtime.synapse.events_for('monitor', record['job_id'])
        return {**result, 'job_id': record['job_id'], 'engine_status': snapshot['status'],
                'steps': {key: {field: value[field] for field in ('status', 'attempts', 'output', 'error')}
                          for key, value in snapshot['steps'].items()},
                'history': history, 'source_records': document['rows']}

    def run(self, batch_id):
        """Resume only pending/retryable work and freeze its final report payload."""
        batch = self._batch(batch_id)
        if batch['payload'] is not None:
            self._verify_completed_jobs(batch_id)
            return batch['payload']
        db = self.runtime.store.db
        with db:
            db.execute("UPDATE csv_batches SET status='RUNNING' WHERE id=?", (batch_id,))
        # Submit every independent document first. A controller killed anywhere
        # in this loop can resubmit safely using the same job fingerprints.
        for record in self._documents(batch_id):
            if record['preparation_error'] is not None:
                continue
            try:
                self.runtime.submit(csv_workflow(json.loads(record['document']), record['job_id'],
                                                  batch['manifest']['timeout_s']))
            except SpecError as exc:
                error = {'type': type(exc).__name__, 'message': str(exc)}
                with db:
                    db.execute('UPDATE csv_batch_documents SET preparation_error=? WHERE batch_id=? AND ordinal=?',
                               (_json(error), batch_id, record['ordinal']))
        documents = [self._document_result(record) for record in self._documents(batch_id)]
        counts = {'documents': len(documents), 'VALID': 0, 'INVALID': 0, 'ERROR': 0}
        certified_cents = 0
        for document in documents:
            counts[document['document_status']] += 1
            if document['document_status'] == 'VALID':
                whole, fraction = document['computed_total'].split('.')
                certified_cents += int(whole) * 100 + int(fraction)
        assert counts['documents'] == counts['VALID'] + counts['INVALID'] + counts['ERROR']
        manifest = batch['manifest']
        delivery_pending = any(document['engine_status'] == 'DELIVERY_FAILED' for document in documents)
        status = 'DELIVERY_FAILED' if delivery_pending else 'PROCESSED'
        payload = {'batch_id': batch_id, 'status': status, 'source_sha256': manifest['source_sha256'],
                   'contract_version': manifest['contract_version'], 'system_version': manifest['system_version'],
                   'agent_versions': manifest['agent_versions'], 'input_rows': manifest['input_rows'],
                   'counts': counts, 'certified_total': _money(certified_cents), 'currency': 'THB',
                   'ungrouped_rows': manifest['ungrouped_rows'], 'documents': documents}
        with db:
            # A failed document terminal is still pending delivery. Preserve its
            # successful steps, but do not freeze an ERROR payload that would
            # prevent retrying its receipt on the next resume.
            db.execute('UPDATE csv_batches SET status=?,payload=?,delivery_error=? WHERE id=?',
                       (status, None if delivery_pending else _json(payload),
                        'Document report delivery remains pending' if delivery_pending else None, batch_id))
        return payload

    def status(self, batch_id):
        """Inspect progress without executing work or changing its history."""
        batch = self._batch(batch_id)
        if batch['payload'] is not None:
            return {**batch['payload'], 'batch_status': batch['status'],
                    'receipt': batch['receipt'], 'delivery_error': batch['delivery_error']}
        documents = []
        for record in self._documents(batch_id):
            document = json.loads(record['document'])
            try:
                snapshot = self.runtime.status(record['job_id'])
            except KeyError:
                snapshot = {'status': 'PENDING', 'steps': {}}
            documents.append({'document_id': document['document_id'], 'job_id': record['job_id'],
                              'engine_status': 'REJECTED' if record['preparation_error'] else snapshot['status'],
                              'steps': snapshot['steps']})
        return {'batch_id': batch_id, 'status': batch['status'], 'documents': documents,
                'source_sha256': batch['manifest']['source_sha256'], 'receipt': batch['receipt'],
                'delivery_error': batch['delivery_error']}

    def _save_receipt(self, batch_id, receipt):
        # This transaction is deliberately last: a controller killed just before
        # it can reuse all verified files from the already-frozen payload.
        db = self.runtime.store.db
        with db:
            db.execute("UPDATE csv_batches SET status='DELIVERED',receipt=?,delivery_error=NULL WHERE id=?",
                       (_json(receipt), batch_id))

    def _verify_batch_receipt(self, batch_id, receipt):
        directory = self.workspace / 'batch_reports' / batch_id
        artifacts = receipt.get('artifacts', {})
        if set(artifacts) != {'summary.csv', 'details.json', 'source.csv'}:
            raise BatchConflict('Batch receipt has an invalid artifact list')
        for name, artifact in artifacts.items():
            path = Path(artifact['path'])
            if path.resolve() != (directory / name).resolve():
                raise BatchConflict('Batch receipt points outside its expected report directory')
            try:
                actual = path.read_bytes()
            except OSError as exc:
                raise BatchConflict(f'Previously delivered artifact is missing: {name}') from exc
            if len(actual) != artifact['bytes'] or hashlib.sha256(actual).hexdigest() != artifact['sha256']:
                raise BatchConflict(f'Previously delivered artifact changed: {name}')

    def deliver(self, batch_id):
        """Write verified batch artifacts, then persist their final receipt."""
        from .reporting import BatchTerminal
        payload = self.run(batch_id)
        if payload['status'] != 'PROCESSED':
            raise RuntimeError('Document delivery is still pending; resume this batch')
        batch = self._batch(batch_id)
        terminal = BatchTerminal(self.workspace / 'batch_reports' / batch_id)
        try:
            if batch['receipt'] is not None:
                self._verify_batch_receipt(batch_id, batch['receipt'])
            receipt = terminal.deliver(payload, batch['source'])
            if batch['receipt'] is not None and receipt != batch['receipt']:
                raise BatchConflict('Batch artifacts differ from their original receipt')
            if batch['receipt'] is None or batch['status'] != 'DELIVERED':
                self._save_receipt(batch_id, receipt)
        except Exception as exc:
            db = self.runtime.store.db
            with db:
                db.execute("UPDATE csv_batches SET status='DELIVERY_FAILED',delivery_error=? WHERE id=?",
                           (str(exc)[:1000], batch_id))
            raise
        return {'batch_id': batch_id, 'status': 'DELIVERED', 'counts': payload['counts'],
                'certified_total': payload['certified_total'], 'currency': 'THB',
                'ungrouped_rows': len(payload['ungrouped_rows']), 'receipt': receipt}
