# Security policy

## Scope and supported versions

Security reports are welcome for the current default branch and the latest
published release. At the time this policy was added, these are the 0.2.1
development candidate and release 0.2.0. Fixes are developed on the default
branch; a backport or maintenance release is a maintainer decision. Older
releases do not receive routine backports. Support is best effort, with no
guaranteed response or remediation deadline.

## Reporting a vulnerability

Please do not put exploit details, credentials, personal information or real
purchase documents in an issue, pull request or CI log.

1. Check the repository's **Security** tab. If **Report a vulnerability** is
   available, use that private reporting flow.
2. If that flow is unavailable, submit a [private-contact request][contact]
   containing only a request to arrange a confidential channel. Do not include
   vulnerability details. The request is publicly visible and is not itself a confidential
   reporting channel.
3. Wait for maintainer `@narongdetpyou-ux` to agree a suitable private channel
   before sending sensitive information. No separate security email address or
   private reporting endpoint is currently promised by this policy.

Once a private channel is agreed, include the affected version/commit, impact,
reproduction steps using synthetic data, and any suggested mitigation. Test
only systems and data you are authorized to use. Coordinate disclosure with
the maintainer so affected users can receive a fix or mitigation first; there
is no fixed embargo period or bounty program.

GitHub private vulnerability reporting has not been verified available for
this public repository. Adding this document does not enable that feature.

## Threat model and handling data

- Agents execute trusted Python code. Worker processes provide failure
  isolation and bounded retries; they are not a security sandbox for untrusted
  plugins or hostile Python code.
- CSV values are untrusted data. Preserve input limits, strict validation,
  independent money checks, report integrity and workspace locking.
- Workspaces can retain original CSV bytes and reports. Restrict access, keep
  backups in a controlled location and use synthetic data in public evidence.
- There are no runtime API-key requirements. Never commit credentials, live
  workspace databases, or real financial records to the repository.

Ordinary invalid input or an availability bug is not automatically a security
vulnerability. If a flaw can expose data or cross an access boundary, use the
reporting process above rather than publishing a detailed reproduction.

[contact]: https://github.com/narongdetpyou-ux/neuron_flow/issues/new?template=contact_request.yml&title=Private%20contact%20request
