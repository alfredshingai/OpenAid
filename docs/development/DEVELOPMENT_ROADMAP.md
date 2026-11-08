# OpenAid — Development Roadmap

> Source of truth: `OpenAid_Project_Blueprint.docx` (November 2026), §16–§17.
> Every phase ends with a report of what was implemented, tests executed and
> their results, known limitations, and the recommended next step. Features
> that exist only as placeholders are never reported as complete.

## Phase gate (binding)

**No full-application development begins until the PoC acceptance criteria
(§16) have been tested and reported, and the user has reviewed the result or
explicitly authorised the next phase.**

## Phase 0 — Architecture & validated foundation (current)

Scope: repository inspection · requirements & architecture documents ·
database design · **geography & spatial PoC** · security baseline ·
approved technical decisions.

| Deliverable | Location | Status |
| --- | --- | --- |
| Repository inspection & state report | milestone report | ✅ |
| PRODUCT_REQUIREMENTS.md | `docs/product/` | ✅ |
| SYSTEM_ARCHITECTURE.md | `docs/architecture/` | ✅ |
| DATABASE_SCHEMA.md | `docs/database/` | ✅ |
| DEVELOPMENT_ROADMAP.md | `docs/development/` | ✅ |
| Governance scaffolding (LICENCE, CONTRIBUTING, CoC, SECURITY) | repo root | ✅ |
| PoC: dynamic country hierarchies | `poc/geography-spatial/` | ✅ |
| PoC: spatial ingestion, validation, query | `poc/geography-spatial/` | ✅ |
| PoC: automated test suite + results | `poc/geography-spatial/tests/` | ✅ |
| PoC: technical report (findings/risks) | `docs/poc/poc-geography-spatial-report.md` | ✅ |
| Real-data provenance demo | `poc/geography-spatial/` scripts + report | ✅ |

**Gate: awaiting user review before Phase 1.**

## Phase 1 — Public MVP (implemented 2026-11-08)

| Deliverable | Status |
| --- | --- |
| Africa-wide map (MapLibre) with status markers + real admin boundaries, dynamic level selector | ✅ `apps/web` MapPage |
| Country pages with hierarchy navigation driven by API-configured levels | ✅ `apps/web` CountryPage |
| Baseline indicator views with provenance (source, licence, period, value type) on every figure | ✅ |
| Organisation directory (read-only, ships empty — evidence-first) | ✅ |
| Facility directory (read-only, real Eswatini data) | ✅ |
| Data catalogue foundations (licence separate from access class) | ✅ |
| CI (GitHub Actions): PostGIS backend tests incl. real-data seed + frontend | ✅ green |
| Real data onboarded | ✅ Eswatini: COD-AB boundaries (4+55), WorldPop 2020 population (285 observations), HOT OSM 758 education facilities |

Tests: backend 15/15 · PoC regression 51/51 · frontend 3/3 · CI green.

## Phase 2 — Data operations

- Ingestion pipelines beyond PoC scope (CSV/XLSX/Shapefile), schema registry.
- Dataset versions, lineage (`source_records`, `data_lineage`,
  `transformation_logs`).
- Moderation & controlled publishing (roles, submissions, reviews, audit
  logs).
- Freshness / data-readiness explorer (separate coverage dimensions).

## Phase 3 — Spatial analysis & reporting

- Population-to-facility ratios, nearest-facility, proximity bands — with
  explicit method assumptions; proximity never equated to availability or
  quality.
- Country/district profile PDFs; CSV/XLSX/GeoJSON/GeoPackage exports with
  source notes, extraction date and caveats.

## Phase 4 — AI & developer platform

- Grounded AI assistant over approved tools (see SYSTEM_ARCHITECTURE §5).
- Public versioned REST API with rate limits, docs, schemas, examples.

## Phase 5 — Continental expansion

- Progressive country onboarding workflow (the PoC's "add a country by
  data/config" property becomes an operational pipeline).
- Translations/localisation; contributor ecosystem; performance work;
  operational maturity (observability, DR drills).

## Country onboarding workflow (applies from PoC onward)

1. Create country configuration + ISO identifiers.
2. Define administrative hierarchy and local labels.
3. Acquire boundary data; record source, licence, reference date.
4. Validate codes, geometry, CRS.
5. Register approved data sources.
6. Import population/baseline datasets where available.
7. Import facility/organisation data where available.
8. Map local classifications to shared ones without losing original labels.
9. Publish coverage, limitations and freshness.
10. Test navigation, map rendering, search, spatial queries.
11. Document gaps; establish maintenance/update process.

## Milestone discipline

Each milestone must report:

1. What was implemented and why.
2. Files and migrations added/changed.
3. Commands run and actual test results (pass/fail counts).
4. Demonstration of database-backed behaviour (not mockups).
5. Known limitations, outstanding work, recommended next step.
