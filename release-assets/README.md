# Release assets index

Use [GitHub Releases](https://github.com/narongdetpyou-ux/neuron_flow/releases) for current published downloads.
Normal publication verifies native assets and preserves old releases without overwriting them.
Version 0.2.1 is published; see the [post-publication check](../verification/publication_2026_10_29/README.md).
Its native `delivery_checks.json` and packaged `BUILD_STATUS.json` describe the build before
upload, so their `published:false` fields are preserved. Use the dated publication record
and GitHub release metadata for remote status; actual Colab acceptance remains `not_run`.

- Files directly in this directory are the immutable **0.2.0 fallback** assets described below.
- `v0.2.1-research-candidate/` is the earlier research snapshot before the Windows fixture fix.
  It is retained for provenance, not the current 0.2.1 release. Its embedded status and checksums
  describe that original snapshot; do not replace them with later artifacts.
- Future development builds belong in ignored `dist/` or an external temporary directory.
  Generate `BUILD_STATUS.json` and `SHA256SUMS.txt` for each exact package rather than copying
  generated status/manifests into the changing source root.

## Historical 0.2.0 fallback record

# Neuron Flow 0.2.0 release files

Code tag: v0.2.0
Code commit: af6737ee9eca39ac5d5fc4d0531b605c9402cc6e

These are the verified release files. They are stored on a dedicated release-assets branch because the runtime could create Releases but GitHub uploads.github.com rejected asset uploads (HTTP 401).
The published Release links to these exact files using this branch commit, not a mutable branch URL.

Actual Google Colab acceptance has not been performed; the user approved publication with this disclosed limitation.
