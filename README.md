# OpenAid

**Open data. Stronger communities. Better decisions.**

OpenAid is a public, open-source, Africa-wide platform combining humanitarian
intelligence, geospatial information, open data infrastructure and
community-development insights. It is intended to help people explore
communities, understand local needs, discover organisations and services,
analyse baseline indicators, identify possible geographic service gaps and
make evidence-informed decisions.

OpenAid is **not** a dashboard or a directory. Its long-term ambition is to
become dependable public-interest information infrastructure: transparent
about where information comes from, when it was collected, how it was
transformed, what it can and cannot support, and where information is missing.

## Status

**Phase 0 — Architecture & validated foundation (in progress).**

Per the project blueprint, the first engineering deliverable is an isolated
**geography & spatial-data proof of concept** (dynamic multi-country
administrative hierarchies + PostGIS spatial ingestion/query), which must pass
its acceptance criteria before any full-application development begins.

| Artefact | Location | Status |
| --- | --- | --- |
| Product & architecture documents | [`docs/`](docs/) | ✅ |
| Geography & spatial PoC | [`poc/geography-spatial/`](poc/geography-spatial/) | ✅ |
| Full application (`apps/`, `backend/`) | — | ⛔ gated on PoC review |

## Principles (non-negotiable)

1. **Accuracy before appearance** — never invent statistics, organisations, facilities, sources or coverage.
2. **Africa-wide by architecture, evidence-led by coverage** — support every African country structurally; onboard validated data progressively.
3. **Country-configurable, not country-dependent** — no hardcoded administrative hierarchy or terminology.
4. **Provenance by design** — source, licence, dates, versions, transformations and verification status are retained.
5. **Comparable only when justified** — indicator comparability is explicit, never assumed.
6. **Privacy and safety** — no beneficiary personal data, medical records, sensitive protection data or protected locations.
7. **Open standards and interoperability** — documented APIs and portable geospatial formats.
8. **Public value over feature count** — usefulness, transparency, accessibility, reproducibility.
9. **Incremental engineering** — working functionality, migrations and tests at every milestone.

## Licence

Code is licensed under the [GNU AGPL-3.0](LICENSE). Data licences are recorded
per source and per dataset and may differ from the code licence.
