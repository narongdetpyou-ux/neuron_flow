# Historical 0.2.1 development scope

This record describes the earlier 0.2.1 work, not current development or publication status. The patch added submit-only CSV intake, batch discovery after an interrupted controller, supported 0.2.0 workspace reuse, structured permanent size failures, bounded event cursors and byte-stable fixture checkouts.

Operational compatibility is bound to schema, data/execution contracts, Agent identities and workflow settings. Existing source bytes, creation-version provenance, frozen payloads, successful steps and reports remain unchanged. Unknown versions or changed identities are rejected. Backup restore requires the original absolute workspace path.

Local regression/packaging evidence and actual Colab acceptance are separate. The historical release and dated evidence are available through repository history and prior release tags. Current instructions are in README.md, INTEGRATIONS.md, CI_RELEASE.md and MAINTAINER_RUNBOOK.md.
