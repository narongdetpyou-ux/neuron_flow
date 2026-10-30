# Actual Google Colab acceptance

Local notebook syntax/recovery tests are not actual Colab acceptance. Start a fresh real runtime and record environment, timestamps, package/fixture identity, commands/results and downloaded-file receipt. Use colab_acceptance_TEMPLATE.json; its initial checks are false and status is not_run.

1. Upload the exact current release ZIP and verify SHA256SUMS.txt for every packaged file.
2. Upload one CSV and persist its batch ID before starting workers. Record versions, Python/runtime markers and source hashes.
3. Execute the normal and invalid scenarios, inspect document statuses/currency totals/receipts and report hashes.
4. Resume the same batch without uploading the CSV again; confirm unchanged successful steps, attempts, source and report bytes/mtime.
5. Run the complete verifier and retain machine-readable evidence. Install selected optional extras/Tesseract to test those adapters; the notebook's main demonstration is the core CSV workflow.
6. Create and download the workspace backup. Manually confirm the download was received; a download call alone is insufficient.
7. In a second fresh runtime, install the same project ZIP and restore the backup at its original absolute path without overwriting an existing workspace. Resume and inspect identical completed results.

Supply completed evidence when verifying an extracted package:

```bash
python -B tools/verify_current.py --output-dir /tmp/neuron-colab-evidence --colab-evidence completed_colab_evidence.json
```

The validator requires the extracted package manifest and verifies submitted assertions against package/fixture identity and consistency. A source checkout without SHA256SUMS.txt cannot establish package identity. It is not automatic remote attestation. Inconsistent/incomplete supplied evidence is invalid and fails verification; omitted evidence remains not_run. Synthetic unit tests do not supply actual Colab observations. Release approval is recorded separately and does not turn unrun checks into passed checks. Live cloud-account authorization also requires its own actual test.
