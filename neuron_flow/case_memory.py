"""Reviewed case retrieval with fixed process profiles and immutable evidence keys.

Similarity only retrieves examples. It never certifies a document or supplies
financial amounts, and held-out labels cannot enter learning records.
"""

import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .intake import _approved, _load
from .supervision import number, wire

PROFILE_DIMENSIONS = 6


def profile_vector(value):
    if not isinstance(value, list) or len(value) != PROFILE_DIMENSIONS:
        raise ValueError("Process profile requires exactly six numeric dimensions")
    for entry in value:
        number(entry, 0, 1, "profile dimension")
    return value


class CaseMemory:
    def __init__(self, workspace, max_records=1000):
        if type(max_records) is not int or not 1 <= max_records <= 10000:
            raise ValueError("max_records must be 1-10000")
        Path(workspace).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(workspace) / 'case_memory.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS reviewed_cases (id TEXT PRIMARY KEY, evidence TEXT NOT NULL)')
        self.maximum = max_records

    def learn(self, workspace, intake_id, candidate_csv, *, profile, method, policy_version, cluster_id, split='train'):
        profile_vector(profile)
        if split != 'train':
            raise ValueError("Only training evidence can enter case memory")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in (method, policy_version, cluster_id)):
            raise ValueError("Method, policy version and independent cluster identity are required")
        folder, manifest, manifest_bytes, _ = _load(workspace, intake_id)
        approval, reviewed_csv = _approved(folder, manifest_bytes)
        from .csv_input import read_csv_bytes
        read_csv_bytes(candidate_csv)
        record = {'schema': 'reviewed-case-v1', 'split': split, 'profile': profile,
                  'method': method, 'policy_version': policy_version, 'cluster_id': cluster_id,
                  'intake_id': intake_id, 'format': manifest['format'], 'source_sha256': manifest['source_sha256'],
                  'approval_sha256': hashlib.sha256(wire(approval)).hexdigest(), 'reviewer': approval['reviewer'],
                  'candidate_sha256': hashlib.sha256(candidate_csv).hexdigest(),
                  'outcome': 'MATCH' if candidate_csv == reviewed_csv else 'MISMATCH',
                  'label_scope': 'Exact comparison to operator-reviewed CSV; reviewer identity is not authenticated'}
        content = wire(record).decode()
        identifier = hashlib.sha256(content.encode()).hexdigest()
        with self.db:
            previous = self.db.execute('SELECT evidence FROM reviewed_cases WHERE id=?', (identifier,)).fetchone()
            if previous is None:
                if self.db.execute('SELECT count(*) FROM reviewed_cases').fetchone()[0] >= self.maximum:
                    raise ValueError("MEMORY_FULL: retain or archive reviewed cases explicitly")
                self.db.execute('INSERT INTO reviewed_cases VALUES(?,?)', (identifier, content))
            elif previous[0] != content:
                raise ValueError("Contradictory evidence")
        return {'case_id': identifier, 'outcome': record['outcome'], 'created': previous is None}

    def retrieve(self, profile, policy_version, *, limit=5, excluded_clusters=()):
        profile_vector(profile)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1-100")
        results = []
        for identifier, content in self.db.execute('SELECT id,evidence FROM reviewed_cases'):
            record = json.loads(content)
            if hashlib.sha256(content.encode()).hexdigest() != identifier or record.get('schema') != 'reviewed-case-v1' or record.get('split') != 'train':
                raise ValueError("Invalid stored memory evidence")
            vector = profile_vector(record['profile'])
            if record['policy_version'] != policy_version or record['cluster_id'] in excluded_clusters:
                continue
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(vector, profile)))
            results.append({'case_id': identifier, 'distance': distance, 'method': record['method'],
                            'outcome': record['outcome'], 'source_sha256': record['source_sha256'],
                            'scope': 'Advisory reviewed case; cannot certify or automatically select a policy'})
        return sorted(results, key=lambda r: (r['distance'], r['case_id']))[:limit]

    def close(self):
        self.db.close()
