# PoC Technical Report — Geography & Spatial Data

**Date:** 2026-11-08 · **Scope:** OpenAid blueprint §16 proof of concept ·
**Location:** `poc/geography-spatial/` · **Status: complete — awaiting user
review before Phase 1**

---

## 1. Objective restatement

Prove that the same geography code can represent countries with different
administrative structures and can store, validate, retrieve and query their
geographic boundaries **without country-specific application logic**, before
any full-application development.

## 2. What was built

| Component | Detail |
| --- | --- |
| Schema (Alembic) | `countries`, `country_configurations`, `administrative_levels`, `administrative_units`, `boundary_versions`, `data_sources`, `import_batches`, `quarantined_features`; UUID PKs; ISO 3166-1 α2/α3; recursive parent/child |
| Integrity | DB trigger enforcing parent = same country + exactly one level above; unique official codes per country; unique (country, source, source-unit-id); typmod `geometry(MultiPolygon,4326)`; append-only boundary versions |
| Ingestion | GeoJSON (RFC 7946) **and** GeoPackage (pyogrio/GDAL); validation with 13 machine-readable reason codes; quarantine table; per-batch validation report; upsert mode → new boundary versions |
| API (FastAPI) | Countries/levels/units CRUD-lite, recursive ancestors CTE, children, boundaries FeatureCollection, point-in-polygon (ST_Covers), bbox (ST_Intersects), imports + quarantine inspection, OpenAPI docs |
| Map preview | Vendored MapLibre GL JS (no CDN), `/preview` — dynamic level dropdown derived from each country's configuration |
| Fixtures | 3 synthetic countries (ISO user-assigned codes XAA/XBB/XCC) with 2-, 3- and 4-level hierarchies; deterministic generator script; clearly labelled synthetic |
| Real-data demo | Eswatini (SWZ) from `crisis-baseline-kit` v0.5.0 (OCHA COD-AB via HDX, **CC BY-IGO**): 4 admin-1 regions via GeoJSON + 55 admin-2 tinkhundla via GeoPackage, full provenance recorded, point-in-polygon verified (Mbabane → SZ1 Hhohho → SZ112 Mbabane East) |
| Tests | **51 pytest tests** against a real PostGIS database (migrated with the same Alembic revisions) |
| Ops | Docker Compose (postgis/postgis:18-3.7 + API), native-PostgreSQL quickstart, `.env.example`, import CLI |

## 3. Acceptance criteria — evidence

| Blueprint §16 criterion | Evidence |
| --- | --- |
| Three sample countries load and browse with the same code | `test_three_countries_load_with_same_code`, `test_countries_import_and_browse_with_shared_code` |
| Different level counts and local level names | `test_different_hierarchy_shapes` (Region/District vs Province/County/Ward vs Governorate/Department/Commune/Village) |
| Fourth country = data + config only | `test_fourth_country_needs_no_code_changes` (5-level "XD" created via API + import, browsed with same endpoints) |
| Parent-child hierarchy integrity enforced and tested | Trigger `unit_parent_consistency` + `test_parent_child_consistency_enforced_by_trigger`, `test_wrong_parent_level_quarantined`, `test_missing_parent_quarantined` |
| Valid geometries with known CRS; invalid rejected with actionable errors | typmod + `test_invalid_geometry_quarantined`, `test_out_of_range_coordinates_quarantined`, `test_gpkg_wrong_crs_rejected`, quarantine detail messages |
| Point-in-polygon returns expected unit | `test_point_in_polygon_deepest_match`, `test_point_in_polygon_returns_full_chain`; real-data Mbabane check |
| API responses expose configured hierarchy dynamically | `test_country_levels_exposed_dynamically` |
| Historical boundary versions coexist without overwriting | `test_upsert_creates_new_boundary_version_and_preserves_history` |
| Tests cover imports, malformed files, invalid geometries, duplicates, missing parents, CRS issues, spatial behaviour | `tests/test_ingestion.py`, `tests/test_spatial.py` |
| README explains setup, fixtures, tests, onboarding | `poc/geography-spatial/README.md` |

**Test result: 51 passed, 0 failed, 2 warnings (deprecation notices from
upstream libraries — see limitations).**

## 4. Findings (design validation)

1. **The dynamic-hierarchy design holds.** Nothing in the API, frontend or
   ingestion knows a level name or a depth. The one point of leverage is
   `administrative_levels` per country. The 5-level "XD" country and real
   Eswatini data both flow through identical code.
2. **Database-level enforcement is worth it.** The parent-consistency trigger
   caught bugs that application-level checks would have missed (it originally
   exposed my own trigger bug during development — see §7).
3. **GeoPackage as second format is cheap.** pyogrio made GPKG ingestion a
   few dozen lines; CRS metadata comes for free (unlike GeoJSON, where CRS is
   a convention).
4. **Quarantine-with-reasons beats all-or-nothing.** Mixed batches
   (valid + invalid features) are the normal case for humanitarian data;
   the batch report + quarantine table give reviewers something actionable.
5. **Real data immediately stressed the schema** (currency `VARCHAR(20)` was
   too short for a real currency label) — fixed via migration 0003. This
   validates running the PoC against real data early.

## 5. Limitations (explicit)

- **EPSG:4326 only.** Non-4326 inputs are rejected with guidance. No
  reprojection, no on-the-fly CRS transformation. Deliberate (provenance
  safety); revisit in Phase 2 with explicit, logged transforms.
- **No authentication/authorization.** All endpoints are open, matching
  "public exploration" but *not* the contribution workflow (Phase 2 adds
  roles/reviews; write endpoints must then be protected).
- **No rate limiting or per-client quotas** yet.
- **No vector tiles.** GeoJSON endpoints are fine for PoC-scale data; the
  Africa-wide map (Phase 1) needs ST_AsMVT/Martin or similar.
- **Synchronous, single-transaction ingestion.** Large country files
  (100k+ features) will need the async worker pipeline planned for Phase 2.
- **Point-in-polygon returns all nested matches ordered by level**, deepest
  via flag — no spatial precedence/tie-breaking rules yet (real nested
  boundaries make "deepest" heuristic; needs a documented rule in Phase 1).
- **No topology validation beyond OGC validity** (no overlap/gap checks
  between sibling units; recommended for Phase 2 with `ST_Union` checks).
- **Python 3.14 / SQLAlchemy 2.1 upstream deprecation warnings** in the test
  run (Starlette TestClient/httpx, Alembic path_separator). Cosmetic.
- **Windows-native dev path**: PostGIS was installed by extracting the OSGeo
  bundle into `C:\Program Files\PostgreSQL\18` (official MD5-verified zip).
  A harmless, unreachable `trust` line was appended to the *system*
  `pg_hba.conf` during setup and can be removed manually; the PoC itself runs
  on a dedicated user-space cluster (`C:\Users\Administrator\openaid_poc_pgdata`,
  port 5433) so the system service is untouched.

## 6. Risks & recommended changes to the full architecture

| Risk / change | Recommendation |
| --- | --- |
| Country onboarding needs a repeatable pipeline | Keep `ingest_real_demo.py`'s transform-then-ingest pattern; formalise as per-source adapters in Phase 2 (the blueprint's ingestion module) |
| `official_code` uniqueness is country-scoped only | Real datasets reuse codes across versions/sources; boundary_versions should later carry (unit, source, reference-date) uniqueness — revisit when historical loads land |
| Geometry normalisation (Polygon→MultiPolygon) is silent-by-design | Kept lossless and reported as a warning; document in API docs; consider a strict mode flag |
| Duplicate source identifiers constraint ties units to first import | Upsert mode covers updates; consider a `superseded_by` model for re-keying units if sources change identifiers (Phase 2) |
| Comparability/provenance tables not exercised | PoC covers geography provenance only; indicator provenance design (§12 blueprint) must be validated in its own mini-PoC before Phase 1 indicator UI |
| Vector tile delivery untested | Add a tiles PoC (ST_AsMVT endpoint or Martin) as an early Phase 1 spike |

## 7. Known issues found & fixed during the PoC

1. `shapely.shape` used as module-level function — fixed to
   `shapely.geometry.shape` (shapely 2.2).
2. Parent-consistency trigger originally read the child row from the table
   during BEFORE INSERT (row not visible) — rewritten to read from `NEW`.
3. pg_hba first-match-wins: a `trust` line appended after `scram` lines is
   dead — replaced by the dedicated dev cluster approach.
4. ISO 3166 user-assigned alpha-3 codes must be 3 letters (XAA–XZZ), not
   "XA"/"XB" — fixtures renamed early before any real coupling.
5. `country_configurations.currency` widened 20→60 after real data tripped it.

## 8. Verdict

The two highest-risk foundations behave as designed. **Recommendation: the
architecture (recursive country-configurable hierarchy + PostGIS +
quarantining ingestion + append-only versions) is validated and ready to
carry the Phase 1 public MVP.**

*Per the blueprint §16 gate: full-application development does not start
until the user reviews this report and explicitly authorises Phase 1.*
