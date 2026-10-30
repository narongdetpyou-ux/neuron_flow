"""Trusted synthetic fault injection for operation supervision tests."""
import os
from pathlib import Path
import subprocess
import sys
import time


def echo(payload):
    return payload


def hang(payload):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    Path(payload['marker']).write_text(str(child.pid))
    time.sleep(60)


def crash(payload):
    os._exit(72)


def invalid(payload):
    return float('nan')


def agent(message):
    return {'checked': True}


def validator(message, output):
    if output != {'checked': True}:
        raise ValueError('Unexpected output')


def slow_validator(message, output):
    time.sleep(10)


def mutating_validator(message, output):
    output['changed'] = True


def rejecting_validator(message, output):
    return False


def candidate_agents():
    from neuron_flow.csv_agents import csv_agent_definitions
    return csv_agent_definitions()
