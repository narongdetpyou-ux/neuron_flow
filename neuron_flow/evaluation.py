"""Identified paired populations, leakage/regression gates and isolated shadow runs."""

import hashlib
import importlib
import tempfile
import time
from pathlib import Path

from .report_review import _read_report, compare_reports
from .supervision import isolated, number, wire
from .telemetry import percentile


def route_variant(cluster_id, fraction=.1, salt='neuron-trial-v1'):
    number(fraction, 0, 1, 'fraction')
    if not isinstance(cluster_id, str) or not cluster_id or not isinstance(salt, str) or not salt:
        raise ValueError('Explicit stable cluster identity and salt required')
    uniform = int.from_bytes(hashlib.sha256((salt + ':' + cluster_id).encode()).digest()[:8], 'big') / 2 ** 64
    return 'candidate' if uniform < fraction else 'reference'


def candidate_gate(reference, candidate, *, training_clusters=(), max_p95_ratio=None, max_attempt_ratio=None):
    required = {'case_id', 'cluster_id', 'split', 'format', 'report_directory', 'latency_ms', 'attempts', 'first_method_success'}
    def collection(rows):
        if not isinstance(rows, list) or not rows:
            raise ValueError('A non-empty identified evaluation population is required')
        indexed = {}
        for row in rows:
            if (not isinstance(row, dict) or not required <= row.keys() or set(row) - required - {'intake_workspace', 'intake_id'}
                    or any(not isinstance(row[k], str) or not row[k] for k in ('case_id', 'cluster_id', 'format'))
                    or row['case_id'] in indexed or row['split'] not in {'validation', 'holdout'}
                    or type(row['first_method_success']) is not bool or type(row['attempts']) is not int):
                raise ValueError('Invalid or duplicate evaluation case')
            number(row['latency_ms'], 0, 1e12, 'latency_ms')
            number(row['attempts'], 1, 100, 'attempts')
            payload, _, _ = _read_report(row['report_directory'])
            indexed[row['case_id']] = (row, payload)
        return indexed
    ref, cur = collection(reference), collection(candidate)
    if ref.keys() != cur.keys():
        raise ValueError('Different evaluation case identities')
    splits = {}
    source_splits = {}
    reports, groups, group_ids = [], {}, {}
    for identifier, (before, payload) in ref.items():
        after, candidate_payload = cur[identifier]
        if any(before[k] != after[k] for k in ('cluster_id', 'split', 'format')) or payload['source_sha256'] != candidate_payload['source_sha256']:
            raise ValueError('Different dataset identity or source bytes')
        cluster = before['cluster_id']
        if cluster in training_clusters or (cluster in splits and splits[cluster] != before['split']):
            raise ValueError('Training/validation/holdout cluster leakage')
        splits[cluster] = before['split']
        source_hash = payload['source_sha256']
        if source_hash in source_splits and source_splits[source_hash] != before['split']:
            raise ValueError('Source overlaps validation and holdout splits')
        source_splits[source_hash] = before['split']
        result = compare_reports(before['report_directory'], after['report_directory'])
        reports.append({'case_id': identifier, 'agreement': result['agreement'], 'differences': result['differences']})
        key = before['format'] + '/' + str(payload['currency'])
        groups.setdefault(key, {'cases': 0, 'regressions': 0})
        group_ids.setdefault(key, []).append(identifier)
        groups[key]['cases'] += 1
        groups[key]['regressions'] += not result['agreement']
    failures = []
    if any(not r['agreement'] for r in reports):
        failures.append('SEMANTIC_REGRESSION')
    for name, limit, field, aggregate in [('LATENCY_REGRESSION', max_p95_ratio, 'latency_ms', lambda v: percentile(v, .95)),
                                           ('ATTEMPT_REGRESSION', max_attempt_ratio, 'attempts', sum)]:
        if limit is not None:
            number(limit, 1, 100, name)
            regressed_groups = []
            for group, identifiers in group_ids.items():
                if aggregate([cur[i][0][field] for i in identifiers]) > aggregate([ref[i][0][field] for i in identifiers]) * limit:
                    regressed_groups.append(group)
            for group in regressed_groups:
                groups[group].setdefault('efficiency_regressions', []).append(name)
            if regressed_groups or aggregate([r[field] for r in candidate]) > aggregate([r[field] for r in reference]) * limit:
                failures.append(name)
    if sum(r['first_method_success'] for r in candidate) < sum(r['first_method_success'] for r in reference):
        failures.append('FIRST_METHOD_REGRESSION')
    population = sorted((key, row['cluster_id'], row['split'], row['format'], payload['source_sha256'])
                        for key, (row, payload) in ref.items())
    return {'schema': 'candidate-gate-v1', 'accepted': not failures, 'failure_reasons': failures,
            'dataset_sha256': hashlib.sha256(wire(population)).hexdigest(), 'cases': len(ref),
            'independent_clusters': len(splits), 'groups': groups, 'comparisons': reports,
            'efficiency_thresholds': {'max_p95_ratio': max_p95_ratio, 'max_attempt_ratio': max_attempt_ratio},
            'scope': 'Regression against identified accepted reports; supplied timing metrics are declarations'}


def shadow_task(payload):
    from .batch import BatchRuntime
    agents = None
    if payload['candidate_factory'] is not None:
        module, function = payload['candidate_factory'].split(':', 1)
        agents = getattr(importlib.import_module(module), function)()
    import base64
    source = base64.b64decode(payload['source_base64'], validate=True)
    with BatchRuntime(payload['workspace'], max_workers=1, agents=agents, legacy_thb=payload['legacy_thb'], validation_timeout_s=5) as batch:
        batch.submit(source, 'shadow')
        batch.deliver('shadow')
    return {'report_directory': str(__import__('pathlib').Path(payload['workspace']) / 'batch_reports/shadow')}


def run_shadow(reference_directory, *, candidate_factory=None, timeout_s=120):
    import base64
    payload, source, _ = _read_report(reference_directory)
    with tempfile.TemporaryDirectory(prefix='neuron-shadow-') as workspace:
        start = time.monotonic()
        result = isolated('neuron_flow.evaluation:shadow_task', {'workspace': workspace,
            'source_base64': base64.b64encode(source).decode(), 'candidate_factory': candidate_factory,
            'legacy_thb': payload['contract_version'] == 'purchase-csv-v1'}, timeout_s, phase='comparison')
        compared = compare_reports(reference_directory, result['report_directory'])
        compared.update(candidate_execution_ms=(time.monotonic() - start) * 1000,
                        candidate_factory=candidate_factory,
                        scope='Trusted candidate execution in a temporary workspace; built-in runner has no connector writes')
        return compared


def accept_policy(destination, strategies, reference, candidate, *, timeout_s=120, **gate_options):
    from .extraction import ExtractionEngine
    from .intake import _load, _approved
    policy = ExtractionEngine(strategies=strategies, timeout_s=timeout_s).binding()
    gate = candidate_gate(reference, candidate, **gate_options)
    if not gate['accepted']:
        raise ValueError('Candidate gate rejected: ' + ', '.join(gate['failure_reasons']))
    if not any(row['split'] == 'holdout' for row in reference):
        raise ValueError('A final holdout population is required for an accepted policy')
    for row in candidate:
        if not {'intake_workspace', 'intake_id'} <= row.keys():
            raise ValueError('Policy acceptance requires candidate intake evidence')
        folder, manifest, manifest_bytes, normalized = _load(row['intake_workspace'], row['intake_id'])
        if normalized is None:
            _, normalized = _approved(folder, manifest_bytes)
        payload, source, _ = _read_report(row['report_directory'])
        if (manifest.get('extraction_policy') != policy or row['format'] != manifest['format']
                or payload['batch_id'] != 'intake_' + row['intake_id'] or source != normalized):
            raise ValueError('Candidate report does not bind the proposed extraction policy')
    body = {'schema': 'accepted-extraction-policy-v1', 'policy': policy, 'gate': gate}
    body['sha256'] = hashlib.sha256(wire(body)).hexdigest()
    with Path(destination).open('xb') as stream:
        stream.write(wire(body))
    return body


def load_policy(path):
    from .extraction import ExtractionEngine
    from .supervision import load_json
    body = load_json(Path(path).read_bytes())
    sha = body.pop('sha256')
    if (hashlib.sha256(wire(body)).hexdigest() != sha or body.get('schema') != 'accepted-extraction-policy-v1'
            or body.get('gate', {}).get('accepted') is not True):
        raise ValueError('Invalid accepted policy')
    engine = ExtractionEngine(strategies=[s['id'] for s in body['policy']['strategies']], timeout_s=body['policy']['timeout_s'])
    if engine.binding() != body['policy']:
        raise ValueError('Accepted policy adapter/method environment changed')
    return engine
