"""Honor one committed publication request after exact-source CI succeeds.

Runs under the repository's ephemeral Actions token. It only creates/reuses an
identical tag; the existing release workflow still validates/builds/publishes.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from neuron_flow import __version__


def validate_request(request, approval, version, commit):
    required = {'schema_version', 'request_id', 'version', 'tag', 'publish'}
    if (not isinstance(request, dict) or set(request) != required or type(request['schema_version']) is not int or request['schema_version'] != 1
            or not isinstance(request['request_id'], str) or not request['request_id']
            or not re.fullmatch(r'[0-9a-f]{40}', commit)
            or not re.fullmatch(r'\d+\.\d+\.\d+', version)
            or request['version'] != version or request['tag'] != 'v' + version or request['publish'] is not True
            or approval.get('version') != version or approval.get('release_approved') is not True
            or approval.get('decision') != 'release_with_disclosed_known_limitation'):
        raise ValueError('An explicit matching stable-version publication request and approval are required')
    return request['tag']


def wait_for_ci(api, repository, commit, *, polls=80, sleep=time.sleep):
    expected = {'quality', 'test (3.10)', 'test (3.12)', 'distribution (3.10)', 'distribution (3.12)',
                'platform-smoke (windows-latest, 3.10)', 'platform-smoke (windows-latest, 3.12)',
                'platform-smoke (macos-latest, 3.10)', 'platform-smoke (macos-latest, 3.12)'}
    for _ in range(polls):
        listing = api('GET', f'/repos/{repository}/actions/runs?head_sha={commit}&event=push&per_page=100')
        runs = [r for r in listing['workflow_runs'] if r['head_sha'] == commit and r['path'] == '.github/workflows/ci.yml']
        if runs:
            run = max(runs, key=lambda r: r['id'])
            if run['status'] == 'completed':
                if run['conclusion'] != 'success':
                    raise ValueError('Exact-source CI did not succeed; publication stopped')
                jobs = api('GET', f'/repos/{repository}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
                if {j['name'] for j in jobs} != expected or any(j['conclusion'] != 'success' for j in jobs):
                    raise ValueError('All nine exact-source CI jobs must succeed')
                return run['id']
        sleep(15)
    raise ValueError('Exact-source CI wait budget exhausted; publication stopped')


def prepare(api, repository, commit, request, approval, version, *, polls=80, sleep=time.sleep):
    tag = validate_request(request, approval, version, commit)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository name')
    ci = wait_for_ci(api, repository, commit, polls=polls, sleep=sleep)
    remote = api('GET', f'/repos/{repository}/git/ref/tags/{tag}')
    if remote is not None:
        if remote['object']['type'] != 'commit' or remote['object']['sha'] != commit:
            raise ValueError('Existing tag conflicts with the exact approved source; never overwrite it')
    else:
        api('POST', f'/repos/{repository}/git/refs', {'ref': 'refs/tags/' + tag, 'sha': commit})
        remote = api('GET', f'/repos/{repository}/git/ref/tags/{tag}')
        if remote is None or remote['object']['sha'] != commit:
            raise ValueError('Tag read-back failed')
    return {'tag': tag, 'expected_commit': commit, 'publish': True, 'ci_run_id': ci}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args(argv)
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip() != args.commit:
        raise ValueError('Checkout differs from the exact requested commit')
    package_version = re.search(r'^version = "([^"]+)"', (PROJECT / 'pyproject.toml').read_text(), re.M)
    if package_version is None or package_version.group(1) != __version__:
        raise ValueError('Package metadata version differs from the source version')
    if __version__ not in (PROJECT / 'RELEASE_NOTES.md').read_text(encoding='utf-8').splitlines()[0]:
        raise ValueError('Release notes heading must identify the exact version before tag creation')
    token = os.environ['GH_TOKEN']
    def api(method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request('https://api.github.com' + path, data=data, method=method, headers={
            'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if method == 'GET' and exc.code == 404:
                return None
            raise
    result = prepare(api, args.repository, args.commit,
        json.loads((PROJECT / 'RELEASE_REQUEST.json').read_text()),
        json.loads((PROJECT / 'RELEASE_APPROVAL.json').read_text()), __version__)
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
            for key in ('tag', 'expected_commit'):
                stream.write(f'{key}={result[key]}\n')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
