# OpenAid — System Architecture

> Source of truth: `OpenAid_Project_Blueprint.docx` (November 2026), sections
> 5, 9, 13, 14. This document records the implemented and planned technical
> architecture and the decisions taken so far.

## 1. Architectural principles

1. **Country-configurable, not country-dependent.** Administrative
   hierarchies are data, not code. A country with two levels and a country
   with five must work with the same application code and no
   country-specific frontend branches.
2. **Provenance by design.** Every geometry and observation carries source,
   licence, reference date and validation outcome. History is never silently
   overwritten.
3. **Modular monolith first.** No microservices, no Kubernetes until
   operational evidence demands them.
4. **Open source only.** Every dependency must be free and open source.
5. **Safe ingestion.** Uploaded files are untrusted input: size limits,
   format allow-lists, quarantine on invalid content.
6. **AI orchestrates tools; it never owns credentials.** Retrieval and
   analytics happen through approved, auditable functions — never arbitrary
   SQL execution.

## 2. Technology stack (all free & open source)

| Layer | Choice | Notes |
| --- | --- | --- |
| Frontend | React + TypeScript + Vite + Tailwind CSS | Phase 1 |
| Maps | MapLibre GL JS | used in PoC preview |
| Backend API | Python 3.12+ / FastAPI + Pydantic v2 | PoC implemented |
| ORM / migrations | SQLAlchemy 2.0 + GeoAlchemy2 + Alembic | PoC implemented |
| Database | PostgreSQL 16+ with PostGIS 3.x | PoC implemented (PostgreSQL 18.4 / PostGIS 3.7.0) |
| Geospatial processing | Shapely 2.x, pyproj | PoC implemented |
| Tabular/vector IO | GeoPandas + pyogrio (GeoPackage), stdlib JSON (GeoJSON) | PoC implemented |
| Charts | Apache ECharts | Phase 1+ |
| Background processing | Celery/Redis when justified | not yet needed |
| Object storage | S3-compatible (MinIO for local dev) | Phase 2 |
| Deployment | Docker + Docker Compose; GitHub Actions CI | PoC ships Compose |
| Testing | pytest (API/DB), Vitest (frontend, Phase 1) | PoC implemented |

## 3. Current topology (PoC)

```
 Browser (MapLibre preview)
        │  HTTP
        ▼
 FastAPI (openaid_poc.api)  ──  uvicorn
        │  SQLAlchemy 2.0 (psycopg 3)
        ▼
 PostgreSQL + PostGIS  ──  dedicated dev cluster (native) or Docker Compose
        ▲
        │ ingestion (CLI or POST /imports)
 openaid_poc.ingestion ── validation + quarantine ── GeoJSON / GeoPackage
```

## 4. Geography architecture (the core problem)

### 4.1 Model

Recursive, country-configurable administrative hierarchy:

- `countries` — ISO 3166-1 alpha-2/alpha-3 identity (alpha-3 used in URLs).
- `country_configurations` — languages, currency, timezone, terminology JSON.
- `administrative_levels` — per-country ordered level list with local names
  (e.g. Zimbabwe: Province → District → Ward; Kenya: County → Sub-county).
  No fixed depth, no fixed names.
- `administrative_units` — the actual units; recursive `parent_unit_id`;
  UUID PKs internally; original `official_code` and `source_id` preserved.
- `boundary_versions` — dated geometry versions; past versions are retained,
  never overwritten. `administrative_units.geometry` mirrors the current
  version for query speed; the version table is the historical record.
- `data_sources`, `import_batches`, `quarantined_features` — provenance and
  ingestion audit trail.

### 4.2 Integrity rules

- Parent must belong to the same country and be exactly one level above —
  enforced by a database trigger, not just application code.
- `official_code` unique per country; source unit identifier unique per
  (source, country) to catch duplicate imports.
- Geometry stored as `MultiPolygon` in EPSG:4326 (Polygon inputs are
  normalised to MultiPolygon; this is the one silent normalisation and it is
  lossless and documented).
- Non-4326 CRS inputs are rejected/quarantined with actionable errors — no
  silent reprojection in the PoC (a deliberate conservative choice; see PoC
  report).

### 4.3 Spatial delivery

- PostGIS holds authoritative geometries and answers containment/intersection
  queries with spatial indexes (GiST).
- GeoJSON endpoints serve interoperable exchange and the map preview.
- Vector tiles (pg_tileserv / Martin or PostGIS ST_AsMVT) are planned for the
  full application when the Africa-wide map arrives; the PoC does not need
  them.

## 5. AI architecture (planned, Phase 4)

- The assistant orchestrates **approved tools only**
  (`search_datasets`, `get_geography_profile`, `search_organisations`,
  `search_facilities`, `get_indicator_observations`,
  `compare_geographies`, `calculate_service_coverage`, `generate_report`).
- No unrestricted SQL, no direct DB credentials in the AI runtime.
- Outputs must cite datasets, source dates, definitions and limitations, and
  must separate source facts from calculated results and interpretation.
- The assistant never makes autonomous beneficiary-selection or funding
  decisions.

## 6. Deployment & operations (target)

Public users → CDN/WAF → frontend → API → PostgreSQL/PostGIS; Redis queue +
workers for heavy geospatial jobs; S3-compatible object storage; managed
backups with tested restores; encryption in transit and at rest; rate limits
and upload controls; migrations via Alembic with rollback plan; monitoring
via OpenTelemetry-compatible tooling.

## 7. Decision log

| # | Decision | Rationale | Date |
| --- | --- | --- | --- |
| D1 | AGPL-3.0 for code | Blueprint proposal, strongest copyleft for public infrastructure | 2026-11-08 |
| D2 | Monorepo with `poc/` isolation | Blueprint §18 structure | 2026-11-08 |
| D3 | PoC uses synthetic fixtures (ISO 3166 user-assigned codes XA/XB/XC) | No licence risk; deterministic tests; real-data demo provided separately with provenance | 2026-11-08 |
| D4 | UUID PKs, ISO alpha-3 external identifiers | Blueprint §5 | 2026-11-08 |
| D5 | MultiPolygon normalisation at ingest | Query/typmod simplicity; lossless | 2026-11-08 |
| D6 | Reject non-EPSG:4326 inputs (no silent reprojection) in PoC | Provenance safety; revisit in Phase 2 with explicit documented transforms | 2026-11-08 |
| D7 | Boundary version history mandatory from day one | Blueprint §5; silent overwrites destroy provenance | 2026-11-08 |
| D8 | Local dev supports native PostgreSQL (no Docker required) and Docker Compose | Contributor machines without virtualisation; Compose remains canonical for CI | 2026-11-08 |

## 8. Assumptions & open questions

**Assumptions**

- HDX COD-AB boundaries (CC BY IGO) are redistributable with attribution —
  to be re-verified before any release ships real boundaries.
- PostgreSQL 16+ / PostGIS 3.x will be the managed-cloud database target.
- Initial deployment targets a single cloud region; Africa-wide latency is
  acceptable for Phase 1.

**Open questions**

1. Managed PostGIS hosting choice (cost, region, backup guarantees) — deferred.
2. Vector tile strategy (ST_AsMVT in-app vs. Martin/pg_tileserv sidecar) — deferred to Phase 1.
3. Country-level data-protection law review workflow (per-country nuance) — Phase 2 governance design.
4. Organisation identity verification process for "organisation representative" role — Phase 2.
5. Which second ingestion format becomes mandatory first: GeoPackage or Shapefile — leaning GeoPackage (single file, CRS metadata), decided by Phase 2.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Licence misinterpretation on real data | Verify per source before publication; provenance registry stores licence per source |
| Uneven country data | Coverage gaps surfaced explicitly; data-readiness explorer (separate dimensions, no single score) |
| Boundary changes over time | `boundary_versions` with validity windows from day one |
| Indicator comparability misuse | `comparability_assessments` designed before indicator UI ships |
| Sensitive data leakage | Access classes separate from licences; privacy review in ingestion workflow |
| Scope expansion | Phase gates with explicit acceptance criteria |
| AI fabrication | Tool-grounded retrieval, citations, uncertainty disclosure; no autonomous decisions |
| Python 3.14 wheel availability for geospatial stack | Verified working (shapely 2.2, pyproj 3.8, geopandas 1.2, pyogrio 0.13); CI pins versions |
