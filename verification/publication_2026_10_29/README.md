# Neuron Flow v0.2.1 publication check

The release was published on **28 October 2026 at 16:17:10 UTC** (23:17:10 in
Asia/Bangkok). The read-only check recorded here confirms all six native assets
download with HTTP 200 and match GitHub's byte sizes and SHA-256 digests.
This records publication and file integrity; actual Google Colab acceptance remains `not_run`.

## Identity and source records

| Item | Observed value |
| --- | --- |
| Release | [v0.2.1](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.2.1), ID 426897457 |
| Release flags | `draft:false`, `prerelease:false`, `immutable:true` |
| Annotated tag object | `8d6519b5f8024dae5cc1012661cc7d36732a5545` |
| Tag target and built source | `bb9b9b4374e3b25ee0c1a429bd6bc881b638c478` |
| Workflow commit | `3e39933f4b1a2030d1a8a500a1ba8349e0096332` |
| Workflow run | [Manual release #3](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40723991028), attempt 1, completed/success |

The workflow checks out the requested tag, not its own workflow commit. Both jobs'
logs identify `bb9b9b4...` as `EXPECTED_COMMIT`; the two later workflow commits
only expose build/publication failure diagnostics. The distinct commits are intentional.
The [release check JSON](release_check.json) records the API URLs, asset URLs,
digests, sizes, original workflow/tag identifiers and the recording time.

## Download and integrity results

| Asset | Bytes | Download and digest |
| --- | ---: | --- |
| `neuron_flow_v0.2.1.zip` | 1118742 | HTTP 200; SHA-256 matches |
| `neuron_flow_v0.2.1.zip.sha256` | 89 | HTTP 200; SHA-256 matches |
| `SHA256SUMS.txt` | 34412 | HTTP 200; SHA-256 matches |
| `START_COLAB.ipynb` | 27689 | HTTP 200; SHA-256 matches |
| `delivery_checks.json` | 833 | HTTP 200; SHA-256 matches |
| `publication_attestation.json` | 1288 | HTTP 200; SHA-256 matches |

The ZIP's SHA-256 is:

```text
25ae7877f77582e2ea92120d2fbab6c4750a2ed9ba8f7c71060401153ddde34c
```

Its sidecar matches. The separately published `SHA256SUMS.txt` is byte-identical
to the manifest inside the ZIP; all 306 listed files match, with no missing files
or digest mismatches. The only archive file not listed is the manifest itself.
The standalone Notebook is byte-identical to its packaged copy, and ZIP CRC checks pass.
The outer ZIP checksum and the manifest's internal-file checks have different scopes.

## Original evidence and current summary

These files were copied byte-for-byte, without regenerating results:

- [test_results.json](test_results.json): 120 current cases, zero failures/errors/skips.
- [baseline_test_results.json](baseline_test_results.json): 38 baseline cases, zero failures/errors/skips.
- [release_workflow_tests.log](release_workflow_tests.log): 10 release guards, OK.
- [delivery_checks.json](delivery_checks.json): the native build/delivery asset.
- [publication_attestation.json](publication_attestation.json): the native workflow-produced bundle record.

The JSON check records ZIP member paths and hashes for the extracted reports.
Their Linux/Python 3.12.15 results describe the released source, not later changes to `main`.
No new application test run or Colab execution is claimed by copying these records.
The [updated stage gates](../v0_2_1/stage_gates.json) point to these reports.
The [previous summary](../archive/stage_gates_0_2_1_pre_publication.json) is preserved
byte-for-byte. Other historical reports, including the earlier 102-current-case
run in `v0_2_1/`, retain their original observations.

`published:false` / `approved_unpublished` in the immutable delivery asset and
packaged `BUILD_STATUS.json` describe the build before publication. They are not
live API queries and must not be rewritten to change the locked ZIP or its hashes.
The actual post-publication state is established by the release API and downloads above.

The publication attestation identifies the source, tag, workflow run and the
sizes/hashes of the five other assets, all of which match. Its own hash matches
GitHub's digest. It was created before publication and contains no digital
signature, so it does not independently prove final publication or remote execution.

## Remaining Colab acceptance

Both native JSON assets and the copied test report retain
`colab_acceptance_complete:false`; the report states no actual Colab evidence was supplied.
The distributed Notebook has seven code cells with no recorded execution outputs.
Follow the [Colab checklist](../../docs/COLAB_ACCEPTANCE_TH.md) for fresh-runtime
upload/execution, exact 100-document matching, interrupted-controller recovery,
resume without repeated completed work, confirmed receipt of the backup and
restore/resume in a second runtime at the original workspace path. Publication,
workflow success and local tests do not supply those observations.
