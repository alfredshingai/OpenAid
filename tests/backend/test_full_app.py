"""Full-application backend tests (Phase 1).

Real-data tests use the extracted crisis-baseline-kit SWZ bundle when
``OPENAID_TEST_BUNDLE_DIR`` points at it; otherwise they skip and the
synthetic coverage below still runs.
"""

from __future__ import annotations

import json

from tests.backend.conftest import BUNDLE_DIR


# ---------------------------------------------------------------------------
# Country registry: Africa-wide by architecture, evidence-led by coverage
# ---------------------------------------------------------------------------


def test_african_countries_seeded_as_placeholders(client):
    from openaid_core.db import session_scope
    from openaid_core.seed.phase1 import seed_countries

    with session_scope() as session:
        by_iso3 = seed_countries(session)

    assert len(by_iso3) >= 54
    body = client.get("/api/v1/countries").json()
    assert len(body) == len(by_iso3)
    assert all(c["status"] == "placeholder" for c in body), "no data yet -> all placeholders"
    iso3s = {c["iso3"] for c in body}
    for expected in ("ZWE", "KEN", "NGA", "EGY", "ZAF", "COD", "MDG"):
        assert expected in iso3s


def test_placeholder_country_has_zero_units(client):
    from openaid_core.db import session_scope
    from openaid_core.seed.phase1 import seed_countries

    with session_scope() as session:
        seed_countries(session)
    zwe = client.get("/api/v1/countries/ZWE").json()
    assert zwe["status"] == "placeholder"
    assert zwe["total_units"] == 0
    assert zwe["max_level"] == 0


# ---------------------------------------------------------------------------
# Real Eswatini data (full pipeline)
# ---------------------------------------------------------------------------


def test_swz_full_load_boundaries(client, seeded_bundle):
    swz = client.get("/api/v1/countries/SWZ").json()
    assert swz["status"] == "active"
    levels = {l["level_number"]: (l["level_name"], l["unit_count"]) for l in swz["levels"]}
    assert levels[1] == ("Region (admin-1)", 4)
    assert levels[2] == ("Tinkhundla (admin-2)", 55)


def test_swz_indicators_carry_provenance(client, seeded_bundle):
    body = client.get("/api/v1/countries/SWZ/indicators").json()
    by_code = {o["indicator"]: o for o in body}
    pop = by_code["total_population"]
    assert pop["value"] and pop["value"] > 900_000, "Eswatini ~1.1M (WorldPop 2020)"
    assert pop["value_type"] == "modelled", "WorldPop is modelled, never presented as observed"
    assert pop["source"] and "WorldPop" in pop["source"]
    assert pop["source_licence"] and "CC-BY" in pop["source_licence"]
    assert pop["period_start"] == "2020-12-31"
    assert pop["methodology"]  # definition methodology present

    schools = by_code["education_facilities_count"]
    assert schools["value_type"] == "observed"
    assert "mapping coverage" in schools["methodology"]


def test_swz_unit_level_observations(client, seeded_bundle):
    units = client.get("/api/v1/countries/SWZ/units?level_number=2&limit=200").json()
    assert len(units) == 55
    unit = units[0]
    obs = client.get(f"/api/v1/countries/SWZ/indicators?unit_code={unit['official_code']}").json()
    codes = {o["indicator"] for o in obs}
    assert {"total_population", "population_density", "education_facilities_count",
            "road_density", "schools_per_10k_population"} <= codes


def test_indicator_series_endpoint(client, seeded_bundle):
    series = client.get("/api/v1/countries/SWZ/indicators/total_population").json()
    assert series["indicator"] == "total_population"
    assert len(series["observations"]) >= 56  # 55 units + 1 country-level


def test_swz_point_in_polygon_real(client, seeded_bundle):
    body = client.get(
        "/api/v1/spatial/point?lon=31.136&lat=-26.318&country_iso3=SWZ&deepest_only=true"
    ).json()
    assert body["match_count"] == 1
    assert body["matches"][0]["official_code"] == "SZ112"
    assert body["matches"][0]["name"] == "Mbabane East"


def test_swz_facilities_with_honest_status(client, seeded_bundle):
    body = client.get("/api/v1/countries/SWZ/facilities?limit=500").json()
    assert body["total"] == 758
    first = body["facilities"][0]
    assert first["operational_status"] in ("unknown", "unverified"), \
        "OSM presence must never be presented as verified operation"
    assert first["source"] and "HOT OSM" in first["source"]
    assert any("not evidence of current operation" in (f["properties"] or {}).get("note", "")
               for f in body["facilities"])


def test_facilities_near_mbabane(client, seeded_bundle):
    body = client.get("/api/v1/spatial/facilities?lon=31.136&lat=-26.318&radius_km=5").json()
    assert len(body["facilities"]) > 0
    for f in body["facilities"]:
        assert "lon" in f and "lat" in f


def test_dataset_catalogue_licences_and_access(client, seeded_bundle):
    datasets = client.get("/api/v1/datasets").json()
    by_slug = {d["slug"]: d for d in datasets}
    assert "ocha-codab-ewswatini-admin-boundaries" in by_slug
    codab = by_slug["ocha-codab-ewswatini-admin-boundaries"]
    assert "CC BY-IGO" in codab["licence"]
    assert codab["access_class"] == "public"
    assert codab["attribution"]  # attribution recorded
    assert any(f["format"] == "gpkg" for f in codab["files"])
    wp = by_slug["worldpop-2020-swz-population"]
    assert "CC-BY 4.0" in wp["licence"]
    assert all(d["is_synthetic"] is False for d in datasets)


def test_hierarchy_navigation_swz(client, seeded_bundle):
    units = client.get("/api/v1/countries/SWZ/units?level_number=2&limit=200").json()
    target = next(u for u in units if u["official_code"] == "SZ112")
    ancestors = client.get(f"/api/v1/units/{target['id']}/ancestors").json()
    assert [(a["level_number"], a["official_code"]) for a in ancestors] == [(1, "SZ1")]
    children = client.get(f"/api/v1/units/{ancestors[0]['id']}/children").json()
    assert len(children) > 10  # Hhohho has many tinkhundla


def test_boundaries_geojson_swz(client, seeded_bundle):
    fc = client.get("/api/v1/countries/SWZ/boundaries?level_number=2").json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 55
    geom = fc["features"][0]["geometry"]
    assert geom["type"] == "MultiPolygon"
    assert fc["features"][0]["properties"]["reference_date"] == "2026-01-26"


def test_organisations_registry_ships_empty(client, seeded_bundle):
    body = client.get("/api/v1/organisations").json()
    assert body == {"total": 0, "organisations": []}, \
        "no organisation rows without source evidence — never synthetic-by-default"


def test_openapi_documents_all_routers(client):
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    for path in (
        "/api/v1/countries",
        "/api/v1/countries/{iso3}/indicators",
        "/api/v1/countries/{iso3}/facilities",
        "/api/v1/indicators",
        "/api/v1/datasets",
        "/api/v1/organisations",
        "/api/v1/spatial/point",
        "/api/v1/spatial/bbox",
        "/api/v1/spatial/facilities",
        "/api/v1/imports/geojson",
        "/api/v1/imports/gpkg",
    ):
        assert path in paths, path


# ---------------------------------------------------------------------------
# Country-configurable property still holds in the full app
# ---------------------------------------------------------------------------


def test_new_country_via_api_needs_no_code(client):
    from tests.backend.conftest import auth_headers, register_and_login

    # write endpoints are protected: anonymous -> 401, contributor -> 403
    anon = client.post(
        "/api/v1/countries",
        json={"iso2": "KE", "iso3": "KEN", "name": "Kenya",
              "levels": [{"level_number": 1, "level_name": "County"}]},
    )
    assert anon.status_code == 401

    admin = register_and_login(client, "root_admin")  # first user -> admin
    headers = {"Authorization": "Bearer " + admin["token"]}
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"

    bob = register_and_login(client, "contributor_bob")  # later user -> contributor
    bob_headers = {"Authorization": "Bearer " + bob["token"]}
    forbidden = client.post(
        "/api/v1/countries",
        headers=bob_headers,
        json={"iso2": "KE", "iso3": "KEN", "name": "Kenya",
              "levels": [{"level_number": 1, "level_name": "County"}]},
    )
    assert forbidden.status_code == 403

    resp = client.post(
        "/api/v1/countries",
        headers=headers,
        json={
            "iso2": "KE",
            "iso3": "KEN",
            "name": "Kenya",
            "levels": [
                {"level_number": 1, "level_name": "County"},
                {"level_number": 2, "level_name": "Sub-County"},
                {"level_number": 3, "level_name": "Ward"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    levels = client.get("/api/v1/countries/KEN/levels").json()
    assert [l["level_name"] for l in levels] == ["County", "Sub-County", "Ward"]
