# Neuron Flow 0.3.0 post-publication verification

[Release v0.3.0](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.3.0)
was published on 29 October 2026 at 16:49:18 Asia/Bangkok (09:49:18 UTC).
Download/SHA-256 checks occurred at 16:49:55 Asia/Bangkok. The observed API state
was draft:false and the aggregate verification was passed:true.

## Source and workflow

- Tag/build source: a4ff09853491ba65acf60aa29daff10de01103f2.
- [Main CI](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40852073574)
  passed all nine jobs: Linux tests and distributions on Python 3.10/3.12,
  quality, and Windows/macOS smoke on Python 3.10/3.12.
- [Manual release](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40852128698)
  completed at attempt 2 using the same source/build. Attempt 1 stopped after
  creating a draft because draft lookup could not yet see it. Rerunning failed
  jobs reused the original artifact and published without replacing assets or tags.

See [workflow-summary.json](workflow-summary.json) for job status/timestamps and
[publication-verification.json](publication-verification.json) for unchanged
original download verification.

## Downloaded assets

All six asset hashes matched:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `delivery_checks.json` | 833 | `73d34a5d92a4675403e6b149b83c61db9fbb2c87ecd5a3546a5050f5d64e1ce1` |
| `neuron_flow_v0.3.0.zip` | 1,285,103 | `1c4b609e7c96ca80ba349abc9fefefe6d5df7c9f6da901e7f6558c1c51eec09f` |
| `neuron_flow_v0.3.0.zip.sha256` | 89 | `13706b7123c369e2eaa8e18289de0e72f21ed03de6f67116baccf87c6262dc39` |
| `publication_attestation.json` | 1,288 | `cf43ab981aaf5b478243a26bdc40cbddb5a3aa12b5ad9e0e4ec2de2173ff9551` |
| `SHA256SUMS.txt` | 41,541 | `b0c6f5b8641ffc28cc089c44797df8e3e479e0cf6ea11db134af6dc3a46d8fc7` |
| `START_COLAB.ipynb` | 29,276 | `f662b6061410f8194d2891c6cd90f9a52f58e8b9a252402c46ed61785542e158` |

The ZIP manifest covered all 367 entries. Its manifest/archive checksum identify
that published package, not a subsequently edited source checkout.

## CLI check from the downloaded ZIP

After extraction and manifest verification, the 0.3.0 international example gave
four VALID, zero INVALID and zero ERROR documents. Certified totals were EUR
25.50, JPY 1500, KWD 3.702 and USD 21.50. Batch currency and certified_total were
null under the multicurrency contract. This ran from the downloaded package.

## Scope

This establishes the release state and downloaded inventory/hashes at the recorded
time. Windows/macOS smoke does not replace Linux full fault-injection coverage.
Actual Colab upload/run/resume/download/restore acceptance remains not_run.
Approval, release notes, BUILD_STATUS.json and delivery_checks.json in the tag/ZIP
are pre-publication records; their preparation language and published:false values
are preserved. This dated post-publication record does not modify tags or assets.
