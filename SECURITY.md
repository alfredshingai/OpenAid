# Security Policy

## Supported versions

OpenAid is in early development. Security fixes apply to the latest `main`
branch and the most recent tagged release.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Report suspected vulnerabilities privately to the maintainers via GitHub's
"Report a vulnerability" feature on this repository (Security tab → Advisories)
or by contacting the repository owner directly.

Please include:

- A description of the issue and its impact
- Steps to reproduce or a proof of concept
- Affected versions/commits
- Any suggested mitigation

You can expect an initial acknowledgement within 7 days. We ask for a
reasonable disclosure window while a fix is prepared.

## Scope notes

- The platform is designed so that no beneficiary personal data, medical
  records, sensitive protection data or protected locations are ever stored.
  Reports involving such data appearing anywhere in the project are treated as
  critical.
- Uploaded files are processed as untrusted input: size limits, format
  allow-lists and safe parsing are in scope for every ingestion path.
- Secrets must never be committed. `.env` files are gitignored; use
  `.env.example` as the documented template.
