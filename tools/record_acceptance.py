"""Create durable normal/invalid/system-failure reports and A01-A08 evidence."""

import hashlib
import argparse
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from neuron_flow.batch import BatchRuntime
from neuron_flow import __version__
from neuron_flow.csv_agents import FINAL_FIELDS
from neuron_flow.csv_input import CsvInputError, read_csv_bytes
from tests.batch_fault_agents import fault_definitions, purchase_source


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Record acceptance evidence for the current implementation')
    parser.add_argument('--output-dir', type=Path,
                        default=PROJECT / 'verification' / ('v' + __version__.replace('.', '_')))
    args = parser.parse_args(argv)
    destination = args.output_dir.resolve()
    evidence = destination / 'acceptance_evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    samples = destination / 'samples'
    samples.mkdir(exist_ok=True)
    # Runtime state contains absolute receipts and frozen event histories. Keep
    # it out of portable delivery archives; export plain artifact examples.
    workspaces = destination / '_sample_workspaces'
    workspaces.mkdir(exist_ok=True)

    def export_sample(name, delivered):
        target = samples / name
        target.mkdir(exist_ok=True)
        copied = {}
        for filename, artifact in delivered['receipt']['artifacts'].items():
            path = target / filename
            shutil.copyfile(artifact['path'], path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
                raise AssertionError('Copied example artifact hash differs')
            copied[filename] = {'path': str(path), 'sha256': artifact['sha256'], 'bytes': path.stat().st_size}
        save(samples / (name + '_receipt.json'), {**delivered, 'example_artifact_copies': copied})

    source = (PROJECT / 'acceptance/input.csv').read_bytes()
    expected = json.loads((PROJECT / 'acceptance/expected_results.json').read_text(encoding='utf-8'))
    # Replay the immutable v1 reference under its original currency contract.
    # New international-currency intake has separate regression coverage.
    with BatchRuntime(workspaces / 'golden', legacy_thb=True) as runtime:
        runtime.submit(source, 'golden-100')
        receipt = runtime.deliver('golden-100')
        result = runtime.run('golden-100')
    actual = [{key: document[key] for key in FINAL_FIELDS} for document in result['documents']]
    if actual != expected['documents']:
        raise AssertionError('Full batch reports differ from locked reference answers')
    export_sample('golden', receipt)
    mapping = {
        'A01': lambda doc: doc['document_status'] == 'VALID',
        'A03': lambda doc: any(error['reason_code'] == 'REQUIRED' for error in doc['errors']),
        'A04': lambda doc: any(error['field'] in {'quantity', 'unit_price'} for error in doc['errors']),
        'A05': lambda doc: any(error['reason_code'] == 'DUPLICATE_ITEM_ID' for error in doc['errors']),
        'A06': lambda doc: any(error['reason_code'] in {'CURRENCY_UNSUPPORTED', 'CURRENCY_CONFLICT', 'DECLARED_TOTAL_CONFLICT'} for error in doc['errors']),
        'A07': lambda doc: any(error['reason_code'] == 'TOTAL_MISMATCH' for error in doc['errors']),
    }
    for criterion, selected in mapping.items():
        pairs = [{'expected': reference, 'actual': observed} for reference, observed
                 in zip(expected['documents'], actual, strict=True) if selected(reference)]
        if not pairs:
            raise AssertionError(f'No acceptance examples for {criterion}')
        save(evidence / (criterion + '_golden.json'), {
            'criterion': criterion, 'source_file': 'acceptance/input.csv',
            'source_sha256': hashlib.sha256(source).hexdigest(), 'expected_file': 'acceptance/expected_results.json',
            'passed': True, 'comparisons': pairs, 'receipt': receipt})
    invalid_headers = [b'document_id,quantity\nA,1\n',
                       b'document_id,item_id,description,quantity,unit_price,declared_total,currency,currency\n',
                       b'document_id,item_id,description,quantity,unit_price,declared_total,currency,unknown\n']
    header_results = []
    for invalid in invalid_headers:
        try:
            read_csv_bytes(invalid)
        except CsvInputError as exc:
            header_results.append({'source_csv': invalid.decode(), 'expected': 'file rejected with named columns',
                                   'actual': str(exc)})
        else:
            raise AssertionError('Invalid header was accepted')
    save(evidence / 'A02_header.json', {'criterion': 'A02', 'passed': True, 'cases': header_results})
    for name, input_path in [('normal', 'examples/purchases.csv'), ('invalid', 'examples/purchases_invalid.csv')]:
        sample_source = (PROJECT / input_path).read_bytes()
        with BatchRuntime(workspaces / name) as runtime:
            runtime.submit(sample_source, name)
            delivery = runtime.deliver(name)
        export_sample(name, delivery)
    fault_workspace = workspaces / 'system_failure'
    fault_source = purchase_source([('HANG', str(fault_workspace / 'hang-worker')), ('GOOD-AFTER', 'Other documents can finish')])
    with BatchRuntime(fault_workspace, agents=fault_definitions(), timeout_s=0.15) as runtime:
        runtime.submit(fault_source, 'system-failure')
        failure_delivery = runtime.deliver('system-failure')
    if failure_delivery['counts'] != {'documents': 2, 'VALID': 1, 'INVALID': 0, 'ERROR': 1}:
        raise AssertionError('System-failure example must retain ERROR after successful report delivery')
    export_sample('system_failure', failure_delivery)
    save(destination / 'golden_batch_result.json', {'source': 'acceptance/input.csv',
        'expected': 'acceptance/expected_results.json', 'documents_compared': len(actual),
        'all_fields_match': True, 'counts': result['counts'], 'receipt': receipt})
    print('Recorded full-batch 100-document comparison and three verified report examples.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
