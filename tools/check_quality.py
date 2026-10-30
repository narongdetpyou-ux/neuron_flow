"""Run correctness lint, incremental typing and branch-aware regression coverage.

Use a new output directory outside the checkout. All coverage data, including
spawned worker and CLI subprocess data, is retained there for inspection.
"""

import argparse
import ast
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
# Rounded down from the first Linux/Python 3.12 measurement. Separate line and
# branch floors prevent strong parser coverage from hiding recovery regressions.
COVERAGE_FLOORS = {
    'total': (91, 83),
    'neuron_flow/csv_agents.py': (97, 93),
    'neuron_flow/reporting.py': (89, 80),
    'neuron_flow/engine.py': (90, 78),
}


def coverage_gates(data):
    checks = {}
    files = {name.replace('\\', '/'): value for name, value in data['files'].items()}
    for name, (line_floor, branch_floor) in COVERAGE_FLOORS.items():
        details = data['totals'] if name == 'total' else files.get(name, {}).get('summary', {})
        checks[name + ':lines'] = details.get('percent_statements_covered', 0) >= line_floor
        checks[name + ':branches'] = details.get('percent_branches_covered', 0) >= branch_floor
    # A green controller-only report misses the agent code. Locate the first
    # executable worker statement by AST, rather than hard-coding a line number.
    tree = ast.parse((PROJECT / 'neuron_flow/engine.py').read_text(encoding='utf-8'))
    worker = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == '_worker_main')
    executed = files.get('neuron_flow/engine.py', {}).get('executed_lines', [])
    checks['spawn_worker_measured'] = worker.body[0].lineno in executed
    http_tree = ast.parse((PROJECT / 'neuron_flow/service.py').read_text(encoding='utf-8'))
    handler = next(node for node in ast.walk(http_tree)
                   if isinstance(node, ast.FunctionDef) and node.name == 'do_POST')
    checks['http_handler_measured'] = handler.body[0].lineno in files.get('neuron_flow/service.py', {}).get('executed_lines', [])
    return checks


def run(command, destination, name, environment, timeout=300):
    result = subprocess.run(command, cwd=PROJECT, env=environment, text=True,
                            capture_output=True, timeout=timeout)
    (destination / (name + '.log')).write_text(
        result.stdout + result.stderr, encoding='utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    destination = args.output_dir.resolve()
    if destination == PROJECT or PROJECT in destination.parents:
        parser.error('Choose a fresh output directory outside the checkout')
    if destination.exists() and any(destination.iterdir()):
        parser.error('Output directory must be empty to avoid stale coverage evidence')
    destination.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(COVERAGE_FILE=str(destination / '.coverage'),
                       COVERAGE_RCFILE=str(PROJECT / '.coveragerc'),
                       NEURON_EVIDENCE_DIR=str(destination / 'acceptance_evidence'))
    python = [sys.executable, '-B', '-m']
    lint = run(python + ['ruff', 'check', '--select', 'E9,F', 'neuron_flow'],
               destination, 'lint', environment)
    typing = run(python + ['mypy', '--strict', '--follow-imports=silent',
                          '--cache-dir', str(destination / 'mypy-cache'),
                          'neuron_flow/inspection.py'],
                 destination, 'typing', environment)
    tests = run(python + ['coverage', 'run', '-m', 'unittest', 'discover',
                         '-s', 'tests', '-t', '.', '-v'],
                destination, 'tests', environment)
    combine = run(python + ['coverage', 'combine'], destination, 'combine', environment)
    report = run(python + ['coverage', 'report'], destination, 'coverage', environment)
    json_report = run(python + ['coverage', 'json', '-o', str(destination / 'coverage.json')],
                      destination, 'coverage-json', environment)
    xml_report = run(python + ['coverage', 'xml', '-o', str(destination / 'coverage.xml')],
                     destination, 'coverage-xml', environment)
    test_counts = re.search(r'Ran (\d+) tests? in ', tests.stdout + tests.stderr)
    test_count = int(test_counts.group(1)) if test_counts else 0
    results = {
        'tool_versions': {name: version(name) for name in ('coverage', 'ruff', 'mypy')},
        'python': sys.version,
        'lint_scope': 'E9,F across neuron_flow/',
        'typing_scope': 'strict neuron_flow/inspection.py; imported modules are not gated',
        'coverage_scope': 'neuron_flow/ including CLI subprocesses, multiprocessing spawn workers and HTTP threads',
        'test_count': test_count,
        'checks': {'lint': lint.returncode == 0, 'typing': typing.returncode == 0,
                   'tests': tests.returncode == 0 and test_count > 0,
                   'combine': combine.returncode == 0, 'report': report.returncode == 0,
                   'json': json_report.returncode == 0, 'xml': xml_report.returncode == 0},
    }
    if json_report.returncode == 0:
        data = json.loads((destination / 'coverage.json').read_text(encoding='utf-8'))
        results['totals'] = data['totals']
        results['modules'] = {name: details['summary'] for name, details in data['files'].items()}
        results['coverage_floors_line_branch'] = COVERAGE_FLOORS
        results['checks'].update(coverage_gates(data))
    results['successful'] = all(results['checks'].values())
    (destination / 'quality_results.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if results['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
