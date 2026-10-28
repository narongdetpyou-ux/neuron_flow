"""Run platform regressions and expose failures through GitHub check annotations."""

import sys
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

MODULES = ('tests.test_csv_input', 'tests.test_csv_agents', 'tests.test_event_cursors',
           'tests.test_batch_cli', 'tests.test_fixture_checkout')


def annotation(test, traceback):
    # Escaping keeps multiline traces in one annotation instead of interpreting
    # arbitrary test output as additional workflow commands.
    def escaped(value):
        return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    title = escaped(test.id()).replace(':', '%3A').replace(',', '%2C')
    return f'::error title={title}::{escaped(traceback)}'


def main():
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for test, traceback in result.failures + result.errors:
        print(annotation(test, traceback), flush=True)
    return 0 if result.testsRun > 0 and result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
