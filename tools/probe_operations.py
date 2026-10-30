"""Replay a seeded synthetic purchase workload through the actual durable queue."""

import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from neuron_flow.extraction import ExtractionCache, ExtractionEngine
from neuron_flow.operations import JobQueue
from neuron_flow.report_review import _read_report


def amount(minor, digits):
    if digits == 0:
        return str(minor)
    factor = 10 ** digits
    return f'{minor // factor}.{minor % factor:0{digits}d}'


def population(seed=20261030, requests=8):
    if type(requests) is not int or not 1 <= requests <= 100:
        raise ValueError('requests must be 1-100')
    rng = random.Random(seed)
    rows = []
    for index in range(requests):
        if index % 4 == 3:
            rows.append(dict(rows[-1]))
            continue
        currency, digits = rng.choice([('JPY', 0), ('THB', 2), ('KWD', 3)])
        price = rng.randint(1, 9999)
        quantity = rng.randint(1, 9)
        correct = price * quantity
        invalid = index % 3 == 2
        output = io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\n')
        writer.writerow(['document_id', 'item_id', 'description', 'quantity', 'unit_price', 'declared_total', 'currency'])
        writer.writerow([f'SYN-{index}', 'A', 'Synthetic purchase', str(quantity), amount(price, digits),
                         amount(correct + int(invalid), digits), currency])
        source = output.getvalue().encode()
        rows.append({'key': f'probe-{index}', 'source_base64': base64.b64encode(source).decode(),
                     'source_sha256': hashlib.sha256(source).hexdigest(), 'expected_status': 'INVALID' if invalid else 'VALID',
                     'expected_computed': amount(correct, digits), 'expected_certified': amount(0 if invalid else correct, digits)})
    return rows


def replay(requests=8, seed=20261030):
    cases = population(seed, requests)
    with tempfile.TemporaryDirectory(prefix='neuron-probe-') as workspace:
        queue = JobQueue(workspace)
        try:
            unique = {}
            admission_ms, completed = [], []
            started = time.monotonic()
            for row in cases:
                before = time.monotonic()
                result = queue.submit({'idempotency_key': row['key'], 'filename': 'purchase.csv',
                                       'source_base64': row['source_base64'], 'timeout_s': 120})
                admission_ms.append((time.monotonic() - before) * 1000)
                if row['key'] in unique and unique[row['key']][0] != result['job_id']:
                    raise ValueError('Duplicate admission did not preserve identity')
                unique[row['key']] = (result['job_id'], row)
            while True:
                result = queue.drain_one()
                if result is None:
                    break
                completed.append(result)
            checks = []
            for identifier, expected in unique.values():
                result = queue.status(identifier)
                batch = result.get('result', {}).get('batch', {})
                saved = {}
                if result['status'] == 'COMPLETED':
                    directory = Path(batch['receipt']['artifacts']['details.json']['path']).parent
                    saved, _, _ = _read_report(directory)
                documents = saved.get('documents', [])
                checks.append({'job_id': identifier, 'source_sha256': expected['source_sha256'],
                               'expected_status': expected['expected_status'], 'observed_job_status': result['status'],
                               'observed_document_status': documents[0]['document_status'] if documents else None,
                               'passed': result['status'] == 'COMPLETED' and len(documents) == 1
                               and documents[0]['document_status'] == expected['expected_status']
                               and documents[0]['computed_total'] == expected['expected_computed']
                               and batch['certified_total'] == expected['expected_certified']})
            elapsed = (time.monotonic() - started) * 1000
            cache = ExtractionCache(max_entries=2)
            engine = ExtractionEngine(cache=cache)
            sample = base64.b64decode(cases[0]['source_base64'])
            cache_latencies = []
            for _ in range(3):
                before = time.monotonic()
                extracted = engine.prepare(sample, 'purchase.csv')
                if extracted['csv'] != sample:
                    raise ValueError('Cache changed normalized CSV')
                cache_latencies.append((time.monotonic() - before) * 1000)
            return {'schema': 'operations-probe-v1', 'seed': seed, 'requests': requests,
                    'unique_jobs': len(unique), 'idempotent_retries': requests - len(unique),
                    'completed_jobs': len(completed), 'checks': checks,
                    'passed': bool(checks) and all(c['passed'] for c in checks), 'elapsed_ms': elapsed,
                    'admission_ms': admission_ms, 'metrics': queue.metrics(),
                    'pure_extraction_cache': {'actual_latencies_ms': cache_latencies, **cache.stats()},
                    'scope': 'Synthetic labeled CSV replay against real local runtime; timings are measured, no production SLA or cross-workload speed claim'}
        finally:
            queue.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=int, default=8)
    parser.add_argument('--seed', type=int, default=20261030)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output_dir.exists() or args.output_dir.resolve().is_relative_to(PROJECT):
        parser.error('Choose a new directory outside the checkout')
    args.output_dir.mkdir(parents=True)
    result = replay(args.requests, args.seed)
    (args.output_dir / 'operations_probe.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('passed', 'requests', 'unique_jobs', 'idempotent_retries', 'elapsed_ms')}, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
