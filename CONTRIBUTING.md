# Contributing to OpenAid

Thank you for considering contributing to OpenAid. This project aims to be
dependable public-interest information infrastructure, so contributions are
held to a high evidentiary standard.

## Ground rules

- **Accuracy before appearance.** Never submit invented statistics,
  organisations, facilities, sources or coverage claims. Cite the origin of
  every factual claim in code, docs and data.
- **Synthetic data must be labelled synthetic.** Test fixtures and sample data
  must never be presented as real-world evidence.
- **Respect licences.** Only ingest or redistribute data whose licence you
  have verified. Record the source, licence and reference date.
- **Country-configurable, not country-dependent.** Never hardcode one
  country's administrative hierarchy, labels or terminology.
- **Tests accompany changes.** New behaviour needs tests; bug fixes need a
  regression test.

## Development setup

See [`poc/geography-spatial/README.md`](poc/geography-spatial/README.md) for
the current proof-of-concept setup (Docker Compose or native PostgreSQL).

## Workflow

1. Open or comment on an issue describing the problem or proposal.
2. Fork / branch from `main`.
3. Make small, reviewable changes with clear commit messages.
4. Run the test suite locally; include the results in your PR.
5. Submit a pull request describing what changed and why.

## Data contributions

Corrections and dataset submissions go through the contribution workflow
(issue templates where applicable). Submissions are reviewed before
publication; reviewer decisions and sources are recorded.

## Code of conduct

By participating you agree to abide by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Please report security issues per [SECURITY.md](SECURITY.md) — do not open
public issues for them.
