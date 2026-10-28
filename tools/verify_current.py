"""Verify current development without changing historical release evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from neuron_flow import __version__
from tools.verify_v020 import EvidenceResult, colab_observation, release_approval


CRITERIA_FILES = {
    'A01': ['A01_golden.json'], 'A02': ['A02_header.json'], 'A03': ['A03_golden.json'],
    'A04': ['A04_golden.json', 'A04_invalid_no_retry.json'], 'A05': ['A05_golden.json'],
    'A06': ['A06_golden.json'], 'A07': ['A07_golden.json'], 'A08': ['A08_reports_traceability.json'],
    'A09': ['A09_hang.json', 'A09_crash.json', 'A09_error_report.json'],
    'A10': ['A10_controller.json', 'A10_document_receipt_window.json', 'A10_batch_receipt_window.json', 'A10_partial_delivery.json'],
    'A11': ['A11_duplicate.json', 'A11_repeat_delivery.json'], 'A12': ['A12_conflict.json'],
}


def project_fingerprint(root):
    """Bind a result to code, tests, workflow, notebook and locked inputs."""
    digest = hashlib.sha256()
    directories = {'neuron_flow', 'tools', 'tests', '.github', 'acceptance', 'docs'}
    files = {'pyproject.toml', 'requirements-build.txt', 'requirements-dev.txt', '.coveragerc', '.gitattributes',
             'START_COLAB.ipynb', 'RELEASE_APPROVAL.json',
             'RELEASE_NOTES.md', 'README.md', 'README_TH.md'}
    for path in sorted(Path(root).rglob('*')):
        relative = path.relative_to(root)
        if (not path.is_file() or path.is_symlink() or '__pycache__' in relative.parts
                or not (relative.parts[0] in directories or relative.as_posix() in files)):
            continue
        digest.update(relative.as_posix().encode('utf-8') + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()


def new_tests():
    discovered = unittest.defaultTestLoader.discover(str(PROJECT / 'tests'), top_level_dir=str(PROJECT))
    def flatten(suite):
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                yield from flatten(test)
            else:
                yield test
    return unittest.TestSuite(test for test in flatten(discovered)
                              if not test.id().startswith('tests.test_runtime.'))


def run_script(name, *arguments, timeout=180):
    return subprocess.run([sys.executable, '-B', str(PROJECT / 'tools' / name), *map(str, arguments)],
                          cwd=PROJECT, text=True, capture_output=True, timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=PROJECT / 'verification' / ('v' + __version__.replace('.', '_')))
    parser.add_argument('--colab-evidence', type=Path)
    args = parser.parse_args(argv)
    destination = args.output_dir.resolve()
    historical = PROJECT / 'verification' / 'v0_2_0'
    if destination == historical or historical in destination.parents:
        parser.error('Historical 0.2.0 evidence is immutable; choose another output directory')
    destination.mkdir(parents=True, exist_ok=True)
    evidence = destination / 'acceptance_evidence'
    evidence.mkdir(exist_ok=True)
    previous_evidence = os.environ.get('NEURON_EVIDENCE_DIR')
    os.environ['NEURON_EVIDENCE_DIR'] = str(evidence)
    started = time.monotonic()
    fixture = run_script('build_acceptance_fixture.py', '--check', timeout=30)
    baseline = run_script('verify.py', '--output-dir', destination / 'baseline')
    stream = io.StringIO()
    try:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=EvidenceResult).run(new_tests())
    finally:
        if previous_evidence is None:
            os.environ.pop('NEURON_EVIDENCE_DIR', None)
        else:
            os.environ['NEURON_EVIDENCE_DIR'] = previous_evidence
    samples = run_script('record_acceptance.py', '--output-dir', destination)
    workflow_test = PROJECT / '.github/workflows/test_release_support.py'
    workflow = (subprocess.run([sys.executable, '-B', str(workflow_test)], cwd=PROJECT,
                              capture_output=True, text=True, timeout=60)
                if workflow_test.is_file() else None)
    checks_passed = (fixture.returncode == baseline.returncode == samples.returncode == 0
                     and workflow is not None and workflow.returncode == 0
                     and result.testsRun > 0 and result.wasSuccessful() and not result.skipped)
    matrix = {criterion: {'local_status': 'passed' if checks_passed
                          and all((evidence / name).is_file() for name in names) else 'not_passed',
                          'evidence': ['acceptance_evidence/' + name for name in names]}
              for criterion, names in CRITERIA_FILES.items()}
    local_successful = checks_passed and all(item['local_status'] == 'passed' for item in matrix.values())
    colab = {'status': 'not_run', 'complete': False, 'reason': 'No actual Colab evidence supplied'}
    if args.colab_evidence:
        from tools.colab_evidence import validate_colab_evidence
        manifest_path = PROJECT / 'SHA256SUMS.txt'
        colab = validate_colab_evidence(args.colab_evidence, version=__version__,
            package_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            fixture_sha256=hashlib.sha256((PROJECT / 'acceptance/input.csv').read_bytes()).hexdigest())
    approved = release_approval(__version__)
    report = {'version': __version__, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'source_fingerprint': project_fingerprint(PROJECT),
              'python': sys.version, 'platform': platform.platform(), 'new_test_cases': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
              'baseline_38_passed': baseline.returncode == 0, 'fixture_lock_passed': fixture.returncode == 0,
              'release_workflow_guard_tests_passed': workflow is not None and workflow.returncode == 0,
              'report_examples_passed': samples.returncode == 0, 'local_successful': local_successful,
              'duration_seconds': round(time.monotonic() - started, 3), 'colab': colab_observation(),
              'colab_evidence': colab, 'colab_acceptance_complete': colab['complete'],
              'all_acceptance_complete': local_successful and colab['complete'],
              'release_approved': approved, 'release_ready': local_successful and approved,
              'remaining_acceptance': [] if colab['complete'] else ['Actual fresh Colab upload/run/resume/download/restore evidence'],
              'cases': result.cases}
    for name, contents in [('tests.log', stream.getvalue()), ('fixture_check.log', fixture.stdout + fixture.stderr),
                           ('baseline_check.log', baseline.stdout + baseline.stderr),
                           ('report_examples.log', samples.stdout + samples.stderr),
                           ('release_workflow_tests.log', '' if workflow is None else workflow.stdout + workflow.stderr)]:
        (destination / name).write_text(contents, encoding='utf-8')
    for name, value in [('test_results.json', report), ('acceptance_matrix.json', matrix)]:
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    summary = f'''# ผลตรวจ Neuron Flow {__version__}

สถานะตรวจในเครื่อง: {'ผ่าน' if local_successful else 'ไม่ผ่าน'}
ฐานเดิม 38 กรณีแยกจากชุดใหม่ {result.testsRun} กรณี; failures {len(result.failures)}, errors {len(result.errors)}, skipped {len(result.skipped)}
เทียบ 100 เอกสารกับคำตอบที่ล็อก พร้อมหลักฐาน A01–A12 ใน acceptance_evidence/

Colab จริง: {colab['status']} การตรวจในเครื่องและการอนุมัติเผยแพร่ไม่เปลี่ยนผลตรวจ Colab
การอนุมัติเผยแพร่รุ่นนี้: {'มี' if approved else 'ยังไม่มี'}
รายงานนี้ไม่แก้ไขหลักฐานของรุ่น 0.2.0 และไม่มีการเผยแพร่ภายนอก
'''
    (destination / 'VERIFICATION_TH.md').write_text(summary, encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'cases'}, ensure_ascii=False, indent=2))
    if not local_successful:
        print(stream.getvalue() + samples.stderr + baseline.stderr, file=sys.stderr)
    return 0 if local_successful and colab['status'] != 'invalid' else 1


if __name__ == '__main__':
    raise SystemExit(main())
