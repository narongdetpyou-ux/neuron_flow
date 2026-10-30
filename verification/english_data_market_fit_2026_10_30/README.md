# English documentation and data/market fit — 30 October 2026

This change translates maintained guides, notebook instructions, issue forms,
examples and generated report text to English. The README and data/market guide
explain purchase-data contracts, structured imports, receipt review, target user
groups and the distinction between arithmetic validation and business approval.

The package version remains 0.4.0.dev0. Monetary rules, saved-source preservation,
locked reference answers and prior publication approvals are unchanged. Three
checksummed historical narrative originals remain alongside English renderings;
all 60 hashes in the historical cloud manifest still match. Other archived
JSON/CSV/ZIP source evidence is unchanged.

Local validation is recorded in [validation.json](validation.json): the 38-case
baseline passed, and 165 current cases had zero failures/errors with two optional
Excel cases skipped because defusedxml is absent. The strict full verifier
correctly marks that local run incomplete; this is not a claim of 203 completed
local passes. The 10 release guards, locked fixture, report examples, English
checks, relative links and Python/notebook syntax passed. Both worked monetary
examples were checked against the implementation.

The complete optional-adapter/quality run belongs to GitHub CI for the exact PR
commit. Its results must be inspected separately. Actual Colab acceptance remains
not_run. This documentation change does not publish or replace a release.
