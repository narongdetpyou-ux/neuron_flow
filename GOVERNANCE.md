# Project governance

Neuron Flow is maintained by [@narongdetpyou-ux](https://github.com/narongdetpyou-ux),
the repository's current owner and sole administrator. The maintainer makes final
decisions about project direction, contributions, releases, moderation and
repository administration. There is no governing committee or voting process.

Issues and pull requests may be written in English or Thai. Participation follows
the [Code of Conduct](CODE_OF_CONDUCT.md), and contributions follow
[CONTRIBUTING.md](CONTRIBUTING.md). The repository is public; these
collaboration routes are public, and sensitive details require an agreed private channel.

## Proposals and decisions

Use issues to describe problems and substantial proposals. Explain the intended
behavior, alternatives and effects on compatibility, recovery, data contracts and
maintenance. Keep implementation changes in focused pull requests and record
material decisions and their reasoning in the related issue or pull request.

The maintainer may accept, request revisions, defer or decline a proposal. A
contribution or discussion does not create a commitment to implement a feature or
meet a deadline. Questions about a decision can be raised respectfully with new
evidence or a concrete alternative.

## Review and merging

Changes should normally reach the default branch, `main`, through a pull request.
Relevant validation must be recorded, with failures and unrun checks disclosed.
Seek independent review when an appropriate reviewer is available, particularly
for persistence, recovery, security, financial calculations and release changes.

The project currently has one maintainer. When independent review is unavailable,
the maintainer may merge after reviewing the complete diff and relevant evidence.
This policy does not claim that a distinct approving reviewer is required or that
GitHub enforces any particular approval count.

Documentation and repository settings have different effects. CODEOWNERS can
identify a reviewer, but does not by itself require approval or block a merge.
The current distinction between intended protections and settings actually
applied is recorded in [the repository policy notes](docs/REPOSITORY_POLICIES_TH.md).
Do not treat a policy document, template or passing local test as proof that a
server-side rule is active.

## Release authority

Only the maintainer authorizes publication. Merging code, passing CI, generating
a candidate package or creating a tag does not provide release approval.

Preserve the existing manual release workflow: publication defaults to
`publish=false`; the requested tag, exact commit and package version are checked;
and publication requires the matching committed version-specific approval. The
historical approval for 0.2.0 does not approve a later version; it is preserved in
`verification/archive/RELEASE_APPROVAL_0_2_0.json`. The root approval applies only
to its explicitly recorded version and owner instruction.
Actual Colab acceptance and other unverified environments must remain disclosed
separately from local validation and publication approval.

## Maintainer changes and policy updates

The owner may add maintainers or transfer responsibility through GitHub's access
controls. Document such changes here and update reviewer ownership and applicable
repository settings. A contribution does not automatically confer write access
or release authority.

Propose changes to governance and other repository policies through a pull
request. The maintainer approves them. These policies do not change the existing
[LICENSE](LICENSE), establish a support SLA or represent a compliance
certification. Support and security processes are described in
[SUPPORT.md](SUPPORT.md) and [SECURITY.md](SECURITY.md).
