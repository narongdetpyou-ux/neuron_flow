# Continuous integration and release publication

## CI

ci.yml runs on pushes and pull requests with contents:read. Linux/Python 3.10 and 3.12 check the locked reference, full regression suite, offline release guards and source/notebook syntax. Quality installs pinned development tools, optional document dependencies and Tesseract, then checks English documentation and branch/scoped typing floors. Distribution builds/installs wheel and sdist in isolated venvs. Windows/macOS run their documented smoke subset. Workspaces/evidence use runner.temp; tests do not commit generated results.

## Manual candidate or publication

release.yml accepts workflow_dispatch with an existing vX.Y.Z tag, exact expected_commit and publish (default false). Source package version, pyproject version, tag and exact commit must agree. Current source version 0.4.0 has matching explicit owner publication approval. A committed `RELEASE_REQUEST.json` with `publish=true` is handled by `approved-publication.yml` after merge to main. That workflow requires all nine push-CI jobs for the exact commit, creates or reuses an identical tag, then calls the same guarded `release.yml` as a reusable workflow with the exact tag/commit and `publish=true`. Conflicting tags or failed/missing CI stop publication. Manual dispatch still defaults to `publish=false`; historical approvals do not authorize a different version.

The release build installs the document extras and Tesseract, then checks the locked reference, the regression suite without skips, offline release guards and isolated distributions; it builds a ZIP and verifies a fresh extraction. Optional adapter coverage and quality gates are separate CI jobs: inspect their results for the exact source. publish=false saves candidate artifacts without publishing. publish=true additionally requires committed RELEASE_APPROVAL.json matching version, release_approved=true and decision=release_with_disclosed_known_limitation, plus matching release notes. Approval from another version never suffices.

Only publication obtains contents:write and uses the ephemeral Actions token. The release environment's actual repository-side protection rules apply. The workflow preserves its read-back checks and never overwrites mismatched tags/assets. Approved publication verifies the exact artifact inventory, sizes/hashes, notes and remote tag; creates/reuses a matching draft; uploads the six native assets; verifies each; then makes the draft public. Existing published releases are not overwritten. Failed publication retains a draft for inspection.

## Published assets and verification

The native assets are neuron_flow_v<version>.zip, its .sha256, SHA256SUMS.txt, START_COLAB.ipynb, delivery_checks.json and publication_attestation.json. BUILD_STATUS.json/delivery_checks.json record build-time state and remain immutable after publication; a post-publication check records observed remote state separately. Obtain and hash every asset, check the ZIP inventory/manifest and verify its tag/source/workflow identities. Publication attestation is a workflow observation, not proof of actual Colab acceptance or an independent security audit.

Historical 0.2.1/0.3.0 release records remain in repository history and dated verification directories. The current package builder includes archived verification snapshots as well as fresh current-run evidence. Historical published assets retain their original language and bytes. Actual Colab and live cloud-account tests remain disclosed separately from local tests and publication approval.
