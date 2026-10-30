# Historical research implementation record — 28 October 2026

The owner requested implementation of the supplied research recommendations and delivery through GitHub. The historical branch was fix/research-hardening-20261028 with version 0.2.1 candidate. A research report proposed changes; it did not itself authorize publication or establish experimental results.

Implemented work covered signed-int64 event-cursor validation, qualified status claims, pinned/hash-locked build tools, isolated wheel/sdist installation, branch coverage with real workers, scoped lint/typing, pinned Actions, platform smoke CI, local unsigned SBOM/provenance, full-runtime/recovery benchmarks, API examples, a maintainer runbook and an inspectable backlog. Independent monetary calculation and verification remained separate; scheduling parallelism and workspace relocation were not introduced as incidental refactors.

External completion criteria remain evidence-based: server settings require authorized API/UI read-back; actual Colab requires fresh upload/run/resume/download/restore; release assets require authorized exact source/tag and downloaded hash checks; platform support requires real runner results; signatures require a real signing identity. Past connectivity/API restrictions did not justify inventing credentials or evidence.

The historical record is retained under verification/ and prior release tags. Read RESEARCH_BACKLOG.json for proposal status and acceptance criteria. Current results belong to the exact dated verification run/CI commit, not this historical description.
