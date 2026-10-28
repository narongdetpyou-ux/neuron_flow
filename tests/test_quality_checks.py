"""Quality gates must reject missing workers and financial branch regressions."""

import ast
from copy import deepcopy
import unittest

from tools.check_quality import COVERAGE_FLOORS, PROJECT, coverage_gates


class QualityGateTests(unittest.TestCase):
    def evidence(self):
        summary = {'percent_statements_covered': 100, 'percent_branches_covered': 100}
        tree = ast.parse((PROJECT / 'neuron_flow/engine.py').read_text(encoding='utf-8'))
        worker = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == '_worker_main')
        return {'totals': dict(summary), 'files': {
            name: {'summary': dict(summary), 'executed_lines': [worker.body[0].lineno]}
            for name in COVERAGE_FLOORS if name != 'total'}}

    def test_financial_branch_regression_fails_despite_full_line_coverage(self):
        data = self.evidence()
        self.assertTrue(all(coverage_gates(data).values()))
        regressed = deepcopy(data)
        regressed['files']['neuron_flow/csv_agents.py']['summary']['percent_branches_covered'] = 92.99
        self.assertFalse(coverage_gates(regressed)['neuron_flow/csv_agents.py:branches'])

    def test_controller_only_or_missing_module_evidence_cannot_pass(self):
        data = self.evidence()
        data['files']['neuron_flow/engine.py']['executed_lines'] = []
        self.assertFalse(coverage_gates(data)['spawn_worker_measured'])
        del data['files']['neuron_flow/reporting.py']
        checks = coverage_gates(data)
        self.assertFalse(checks['neuron_flow/reporting.py:lines'])
        self.assertFalse(checks['neuron_flow/reporting.py:branches'])
