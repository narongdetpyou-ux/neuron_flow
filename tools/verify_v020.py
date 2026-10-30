"""Record new-version verification separately from the 38-case legacy suite."""

from datetime import datetime, timezone
import importlib.util
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


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)

    def _record(self, test, outcome):
        self.cases.append({'test': test.id(), 'outcome': outcome,
                           'duration_seconds': round(time.monotonic() - self.started, 4)})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, 'failed')

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, 'error')

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, 'skipped: ' + reason)


def colab_observation():
    try:
        available = importlib.util.find_spec('google.colab') is not None
    except ModuleNotFoundError:
        available = False
    markers = [name for name in ('COLAB_RELEASE_TAG', 'COLAB_BACKEND_VERSION',
                                 'COLAB_JUPYTER_TRANSPORT') if name in os.environ]
    return {'google_colab_importable': available, 'runtime_marker_names': markers,
            'observed_colab_runtime': available and bool(markers)}


def release_approval(version):
    path = PROJECT / 'RELEASE_APPROVAL.json'
    if not path.is_file():
        return False
    approval = json.loads(path.read_text(encoding='utf-8'))
    return (approval.get('release_approved') is True
            and approval.get('version') == version
            and approval.get('decision') == 'release_with_disclosed_known_limitation')


def write_report(report, destination):
    approved = report.get('release_approved', False)
    text = f"""# Neuron Flow 0.2.0 historical verifier

- Created at UTC: {report['created_at_utc']}
- Local result: {'passed' if report['local_successful'] else 'failed'}
- Release approval: {'approved with disclosed limitations' if approved else 'not approved'}
- Baseline: 38 cases; current cases: {report['new_test_cases']}
- Failures: {report['failures']}; errors: {report['errors']}; skipped: {report['skipped']}
- Python: {report['python'].split()[0]}; platform: {report['platform']}
- Locked workload: 100 documents, 80 VALID and 20 INVALID under the legacy THB contract.

See acceptance_matrix.json, acceptance_evidence/, samples/, tests.log and test_results.json.
Coverage includes real hangs/crashes and interrupted controllers and delivery recovery.
Only VALID amounts are certified. Actual Colab acceptance remains unverified.
Publication approval is separate from actual environment acceptance.

Reproduce using tools/verify.py and tools/verify_v020.py with the appropriate historical runtime.
"""
    (destination / 'VERIFICATION.md').write_text(text, encoding='utf-8')


def main():
    from neuron_flow import __version__
    destination = PROJECT / 'verification' / 'v0_2_0'
    destination.mkdir(parents=True, exist_ok=True)
    evidence = destination / 'acceptance_evidence'
    evidence.mkdir(exist_ok=True)
    os.environ['NEURON_EVIDENCE_DIR'] = str(evidence)
    fixture = subprocess.run([sys.executable, 'tools/build_acceptance_fixture.py', '--check'],
                             cwd=PROJECT, capture_output=True, text=True, timeout=30)
    baseline = subprocess.run([sys.executable, 'tools/verify.py'], cwd=PROJECT,
                              capture_output=True, text=True, timeout=180)
    suite = unittest.TestSuite()
    for pattern in ('test_csv*.py', 'test_batch*.py', 'test_reporting.py'):
        suite.addTests(unittest.defaultTestLoader.discover(
            str(PROJECT / 'tests'), pattern=pattern, top_level_dir=str(PROJECT)))
    stream = io.StringIO()
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                     resultclass=EvidenceResult).run(suite)
    samples = subprocess.run([sys.executable, 'tools/record_acceptance.py'], cwd=PROJECT,
                             capture_output=True, text=True, timeout=120)
    criteria_files = {
        'A01': ['A01_golden.json'], 'A02': ['A02_header.json'],
        'A03': ['A03_golden.json'], 'A04': ['A04_golden.json', 'A04_invalid_no_retry.json'],
        'A05': ['A05_golden.json'], 'A06': ['A06_golden.json'], 'A07': ['A07_golden.json'],
        'A08': ['A08_reports_traceability.json'], 'A09': ['A09_hang.json', 'A09_crash.json', 'A09_error_report.json'],
        'A10': ['A10_controller.json', 'A10_document_receipt_window.json', 'A10_batch_receipt_window.json', 'A10_partial_delivery.json'],
        'A11': ['A11_duplicate.json', 'A11_repeat_delivery.json'], 'A12': ['A12_conflict.json'],
    }
    matrix = {criterion: {'local_status': 'passed' if all((evidence / name).is_file() for name in names)
                          and result.wasSuccessful() and samples.returncode == 0 else 'not_passed',
                          'evidence': ['acceptance_evidence/' + name for name in names]}
              for criterion, names in criteria_files.items()}
    (destination / 'acceptance_matrix.json').write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    observation = colab_observation()
    expected_modules = ('test_csv_input', 'test_csv_agents', 'test_batch_basic', 'test_batch',
                        'test_batch_cli', 'test_batch_delivery', 'test_reporting')
    modules_present = all((PROJECT / 'tests' / (name + '.py')).is_file() for name in expected_modules)
    local_successful = (fixture.returncode == baseline.returncode == samples.returncode == 0
                        and modules_present and result.testsRun > 0 and result.wasSuccessful()
                        and not result.skipped and all(value['local_status'] == 'passed' for value in matrix.values()))
    approved = release_approval(__version__)
    report = {'version': __version__, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'platform': platform.platform(),
              'new_test_cases': result.testsRun, 'failures': len(result.failures),
              'errors': len(result.errors), 'skipped': len(result.skipped),
              'duration_seconds': round(time.monotonic() - started, 3),
              'fixture_lock_passed': fixture.returncode == 0,
              'baseline_38_passed': baseline.returncode == 0,
              'report_examples_passed': samples.returncode == 0,
              'local_successful': local_successful, 'colab': observation,
              # Publication approval is distinct from acceptance evidence.
              'release_approved': approved,
              'release_ready': local_successful and approved,
              'colab_acceptance_complete': False,
              'all_acceptance_complete': False,
              'remaining_acceptance': ['Fresh Google Colab upload/run/download acceptance with recorded evidence'],
              'cases': result.cases}
    for name, contents in [('tests.log', stream.getvalue()),
                           ('fixture_check.log', fixture.stdout + fixture.stderr),
                           ('report_examples.log', samples.stdout + samples.stderr),
                           ('baseline_check.log', baseline.stdout + baseline.stderr)]:
        (destination / name).write_text(contents, encoding='utf-8')
    (destination / 'test_results.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_report(report, destination)
    print(json.dumps({key: value for key, value in report.items() if key != 'cases'},
                     ensure_ascii=False, indent=2))
    if not local_successful:
        print(stream.getvalue(), file=sys.stderr)
    return 0 if local_successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
