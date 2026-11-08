# OpenAid PoC — Geography & Spatial Data

> Blueprint §16 proof of concept: **country-configurable administrative
> hierarchies** and **spatial data ingestion, storage, validation and
> querying** — the two highest-risk foundations of OpenAid.
>
> ⚠️ **All bundled fixtures are SYNTHETIC.** The countries (Alandra, Boroland,
> Cyria) do not exist. See [`fixtures/README.md`](fixtures/README.md).

## What it proves

1. **Same code, any hierarchy.** A 2-level, a 3-level and a 4-level country
   load, import, browse and query through identical code paths. Level names
   (Region/District, Province/County/Ward, Governorate/Department/Commune/Village)
   are data, returned by the API — the map preview renders whatever depth it
   receives, with no country-specific branches.
2. **Adding a country needs no code changes.** `POST /api/v1/countries` with a
   level list, then import boundary data. (Tested: a 5-level country "XD".)
3. **Safe ingestion.** GeoJSON *and* GeoPackage, with validation of schema,
   country association, duplicate codes, parent integrity, coordinate ranges,
   geometry validity and CRS. Invalid features are **quarantined** with
   actionable errors; valid features in the same batch still import.
4. **History is never overwritten.** Upserting a boundary creates a new
   `boundary_versions` row and closes the old one — both coexist.
5. **PostGIS answers spatial questions.** Point-in-polygon, bbox intersection,
   recursive ancestor walks — all GiST-indexed, all behind a documented API.

## Quickstart (Docker Compose)

```bash
docker compose up --build -d
# the api container initialises the schema and seeds the three synthetic
# countries automatically
open http://localhost:8000/preview     # MapLibre map preview
open http://localhost:8000/docs        # OpenAPI docs / interactive API
```

Import a fixture manually and run the tests:

```bash
docker compose exec api python -m openaid_poc.cli import \
    fixtures/XA_alandra/boundary.geojson --country XAA \
    --source-name "Synthetic fixture" --synthetic --reference-date 2026-01-01
docker compose exec api python -m pytest tests/ -v
```

## Quickstart (native PostgreSQL — no Docker)

Requires PostgreSQL 12+ with the PostGIS extension (developed against
PostgreSQL 18.4 + PostGIS 3.7.0 on Windows).

```bash
# 1. Create a database and role
psql -h 127.0.0.1 -U postgres -c "CREATE ROLE openaid LOGIN CREATEROLE PASSWORD 'openaid_dev_poc'"
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE openaid_poc OWNER openaid"

# 2. Configure and install
export DATABASE_URL=postgresql+psycopg://openaid:openaid_dev_poc@127.0.0.1:5432/openaid_poc
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r poc/geography-spatial/requirements.txt
pip install -e poc/geography-spatial

# 3. Migrate, seed, import, serve (from poc/geography-spatial/)
python -m openaid_poc.cli init-db
python -m openaid_poc.cli seed-countries fixtures
python -m openaid_poc.cli import fixtures/XBB_boroland/boundary.geojson \
    --country XBB --source-name "Synthetic fixture" --synthetic --reference-date 2026-01-01
python -m openaid_poc.cli serve            # http://localhost:8000/preview
```

## The property contract

Boundary features (GeoJSON properties or GeoPackage columns) must carry:

| Property | Meaning |
| --- | --- |
| `country_iso3` | Target country — mismatched features are quarantined |
| `official_code` | Unique code per country (e.g. `XA-D11`) |
| `name` | Display name |
| `admin_level` | 1-based level number, must exist in the country's configuration |
| `parent_code` | Parent's `official_code`; required for `admin_level > 1` |
| `source_unit_id` | Optional original identifier from the source dataset |

Everything else on a feature is preserved verbatim in `properties` (JSONB).

Validation rejections carry machine-readable `reason_codes`:
`missing_property`, `invalid_property`, `country_mismatch`, `unknown_level`,
`duplicate_code`, `missing_parent`, `invalid_parent_level`,
`unsupported_crs`, `unsupported_geometry_type`, `invalid_geometry`,
`empty_geometry`, `out_of_range_coordinates`, `missing_geometry`.

## Onboarding another country (no code changes)

```bash
# 1. Create the country + its hierarchy via the API
curl -X POST http://localhost:8000/api/v1/countries -H "Content-Type: application/json" -d '{
  "iso2": "KE", "iso3": "KEN", "name": "Kenya",
  "levels": [
    {"level_number": 1, "level_name": "County"},
    {"level_number": 2, "level_name": "Sub-County"}
  ]
}'

# 2. Register the source and import boundaries (EPSG:4326)
python -m openaid_poc.cli import kenya_admin.geojson --country KEN \
    --source-name "OCHA COD-AB (HDX)" --source-licence "CC BY IGO" \
    --reference-date 2026-08-01
```

For a worked **real-data** example (one country from the open-source
`crisis-baseline-kit` project, boundaries from OCHA COD-AB via HDX, CC BY IGO),
see `scripts/ingest_real_demo.py`.

## API surface

| Method & path | Purpose |
| --- | --- |
| `GET /health` | Liveness + database check |
| `GET /api/v1/countries` | List countries with level definitions and unit counts |
| `POST /api/v1/countries` | Create a country + hierarchy configuration |
| `GET /api/v1/countries/{iso3}` | Country detail |
| `GET /api/v1/countries/{iso3}/levels` | Configured administrative levels |
| `GET /api/v1/countries/{iso3}/units` | Browse units (`?level_number=&parent_code=&limit=&offset=`) |
| `GET /api/v1/countries/{iso3}/boundaries` | GeoJSON FeatureCollection (`?level_number=`) |
| `GET /api/v1/units/{id}` | Unit detail incl. geometry and version count |
| `GET /api/v1/units/{id}/children` | Direct children |
| `GET /api/v1/units/{id}/ancestors` | Recursive walk to the root (root first) |
| `GET /api/v1/spatial/point` | Point-in-polygon (`?lon=&lat=&country_iso3=&deepest_only=`) |
| `GET /api/v1/spatial/bbox` | Bbox intersection (`?minx=&miny=&maxx=&maxy=&level_number=`) |
| `POST /api/v1/imports/geojson` | Ingest GeoJSON (multipart) + validation report |
| `POST /api/v1/imports/gpkg` | Ingest GeoPackage (multipart) + validation report |
| `GET /api/v1/imports/{batch_id}` | Batch status/report |
| `GET /api/v1/imports/{batch_id}/quarantine` | Quarantined features with reasons |

Example request/response:

```
GET /api/v1/spatial/point?lon=1.0&lat=0.5&country_iso3=XAA&deepest_only=true

{
  "lon": 1.0, "lat": 0.5,
  "matches": [
    {
      "id": "…", "name": "District 11", "official_code": "XA-D11",
      "country_iso3": "XAA", "level_number": 2, "level_name": "District",
      "parent_unit_id": "…", "parent_code": "XA-R1",
      "reference_date": "2026-01-01", "verification_status": "unverified",
      "source_unit_id": "XA-D11"
    }
  ],
  "match_count": 1
}
```

## Tests

51 automated tests run against a real PostGIS database (a separate
`openaid_poc_test` database created by the suite, migrated with the same
Alembic migrations):

- `tests/test_hierarchy_config.py` — dynamic hierarchies, 4th-country onboarding
- `tests/test_ingestion.py` — validation, quarantine, duplicates, CRS, upserts
- `tests/test_spatial.py` — point-in-polygon, bbox, ancestors, trigger integrity
- `tests/test_api.py` — API contract, OpenAPI documentation completeness

```bash
pytest tests/ -v          # DATABASE_URL must point at a PostGIS cluster
```

## Known limitations

See `docs/poc/poc-geography-spatial-report.md` for the full report —
notably: EPSG:4326-only ingestion (no reprojection), no authentication on
write endpoints, no rate limiting, no vector tiles yet, and single-threaded
synchronous ingestion.
