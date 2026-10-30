# Repository policies and GitHub settings

CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, SUPPORT.md and GOVERNANCE.md define contribution, conduct, reporting, support and maintainer responsibilities. CODEOWNERS identifies the owner; issue forms, the PR template and Dependabot support the workflow. Repository documents do not establish ISO/legal certification or prove server-side enforcement.

The proposed .github/policies/main-ruleset.json requires PRs, resolved conversations and test (3.10), test (3.12), quality, distribution (3.10) and distribution (3.12). It proposes up-to-date branches and protection from force-push/deletion. Its payload is a proposal until API/UI read-back confirms active enforcement. With one maintainer it requests zero mandatory approvals; independent review should be sought when available. Additional maintainers should revisit approvals and CODEOWNERS.

Historical 28 October 2026 checks occurred while the repository was private: ruleset/protection/security endpoints returned 403 or 404, and some settings could not be changed or confirmed. A later report identified a public repository and an empty ruleset list; classic protection remained unreadable. These are dated observations, not current authorization or enforcement claims. No plan upgrade, visibility change, signing identity or access grant is implied.

Owners must inspect current Settings/API state before changing rulesets, security alerts, automatic branch deletion or token defaults. Ordinary CI uses contents:read; approved publication jobs alone obtain contents:write. Release authorization is version-specific and distinct from merging. Current release instructions are in [CI_RELEASE.md](CI_RELEASE.md).

Public contact-request issues are visible to repository readers. Request a private channel before sharing vulnerability details or personal evidence; do not invent an unconfigured address/channel. See SECURITY.md and GOVERNANCE.md.
