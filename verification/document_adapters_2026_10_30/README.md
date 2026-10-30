# Document adapters — 30 October 2026

This historical run tested source version 0.4.0.dev0 on Linux/Python 3.12.14,
without altering the locked fixture or prior release evidence. That source was
unreleased and had no matching publication approval. Translation of this summary
does not represent a new execution of the tests.

| Check | Recorded result |
| --- | --- |
| Full package regression including adapters | 203 tests passed; zero failures/errors/skips |
| Full verifier | 38 baseline + 165 current passed |
| Locked fixture | 100 documents, 80 VALID/20 INVALID; original bytes |
| Release guards | 10 passed; old approval did not authorize development source |
| Ruff E9,F and scoped strict mypy | Passed |
| Package line/branch coverage | 93.82% / 87.53%; all existing floors passed |
| Wheel/sdist | Built and installed in isolated environments outside the checkout |
| Installed CLI | CSV run/resume, adapters and JSON intake/run passed for both distributions |
| PDF/XLSX | Real generated files, formulas, encrypted PDFs, bounds and malformed files tested |
| OCR | Real English Tesseract on PNG, JPEG, TIFF and scanned PDF |
| Review/recovery | No run before review, revision IDs, reuse and SHA-256 checks passed |
| Cloud adapters | API contract/failure tests passed using fake HTTP/S3 clients |

See [verifier](test_results.json), [quality](quality_results.json),
[distribution](distribution_checks.json) and [command scope/status](validation_scope.json).
The verifier records its source fingerprint; adding evidence under verification/
does not change that fingerprint. Tests include oversized JSON exponents rejected
before decimal-string expansion.

Live cloud accounts, local non-English OCR and actual Colab upload/run/resume/
download/restore were not tested. Fake/local API tests do not establish cloud
authorization or a production SLA. Optional-adapter CI installs extras/Tesseract;
remote runner results must be inspected separately from this local record.
All examples are synthetic and contain no real receipts or credentials.
