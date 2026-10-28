"""Inspect persisted batches without a Runtime, workers, or database mutations."""

import json
from pathlib import Path
import sqlite3


class InspectionError(ValueError):
    pass


def list_batches(workspace):
    """Read a consistent metadata snapshot, including while a controller runs.

    Inspection deliberately does not apply the current runtime compatibility
    policy: older/incompatible jobs still need to be discoverable for recovery.
    No source CSV is read and no Agent function is imported or executed.
    """
    directory = Path(workspace).resolve()
    path = directory / 'state.sqlite3'
    if not path.is_file():
        raise InspectionError(f'Workspace database does not exist: {path}')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'csv_batches' not in tables:
            return {'workspace': str(directory), 'batches': []}
        batches = []
        for record in connection.execute('SELECT id,manifest,status,payload,receipt,delivery_error FROM csv_batches ORDER BY id'):
            manifest = json.loads(record['manifest'])
            payload = json.loads(record['payload']) if record['payload'] else None
            if not isinstance(manifest, dict) or (payload is not None and not isinstance(payload, dict)):
                raise InspectionError('Batch manifest and result must be JSON objects')
            states = {}
            documents = 0
            if 'csv_batch_documents' in tables:
                for row in connection.execute('''
                    SELECT d.preparation_error,j.status FROM csv_batch_documents d
                    LEFT JOIN jobs j ON j.id=d.job_id WHERE d.batch_id=? ORDER BY d.ordinal
                ''', (record['id'],)):
                    documents += 1
                    status = 'REJECTED' if row['preparation_error'] else (row['status'] or 'PENDING')
                    states[status] = states.get(status, 0) + 1
            batches.append({'batch_id': record['id'], 'status': record['status'],
                            'source_sha256': manifest.get('source_sha256'),
                            'created_with_version': manifest.get('system_version'),
                            'contract_version': manifest.get('contract_version'),
                            'workspace_schema_version': manifest.get('workspace_schema_version', 1),
                            'documents': documents, 'engine_counts': states,
                            'counts': payload.get('counts') if payload else None,
                            'receipt_available': record['receipt'] is not None,
                            'delivery_error': record['delivery_error']})
        return {'workspace': str(directory), 'batches': batches}
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise InspectionError(f'Cannot inspect workspace: {exc}') from exc
    finally:
        connection.close()
