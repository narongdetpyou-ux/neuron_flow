# Getting support

Start with the [README](README.md) or [Thai user guide](README_TH.md) for supported
inputs, CLI commands, limits, status meanings and recovery instructions. See
[CONTRIBUTING.md](CONTRIBUTING.md) for development and test commands.

## Questions and bug reports

Use this repository's GitHub Issues for usage questions, reproducible bugs and
feature proposals. English and Thai are accepted. The repository is currently
private, so this route requires repository access. There is no separate support
email or discussion service established by this policy.

Search existing issues first. A useful report includes:

- Project version or commit, Python version and operating system.
- The command used, expected behavior and actual behavior, including exit code.
- A small synthetic CSV or JSON example that reproduces the problem.
- Relevant error messages and document and engine statuses. `INVALID` input and
  an engine `ERROR` have different meanings; a successful CLI exit alone does not
  certify every document as valid.
- For recovery problems, whether the original absolute workspace path was kept
  and which steps had already completed.

Share only the information needed to reproduce the issue. Do not upload real
purchase documents, credentials, personal information or an unreviewed workspace
database or backup. Workspaces can contain original source data, reports and
absolute paths. Review and sanitize logs before attaching them, including in this
private repository. Never paste secret values into an issue.

Suspected vulnerabilities belong in the process described by
[SECURITY.md](SECURITY.md). Conduct concerns follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Do not include sensitive disclosure
details in an ordinary support issue.

## Availability and scope

Support and maintenance are provided on a best-effort basis. There is no
guaranteed response time, resolution date, support contract or service-level
agreement. The maintainer prioritizes requests according to impact,
reproducibility, project scope and available time.

The current scope is the single-machine purchase CSV workflow described in the
README. Historical releases, external services, operating systems and hosted
notebook runtimes are not automatically covered by local test results. Include
evidence from the environment where a problem occurs.
