"""API contract tests: navigation derived from configuration (blueprint §16
acceptance 8) plus error behaviour.
"""

from __future__ import annotations

import pytest

from tests.conftest import import_fixture, seed_three_countries


@pytest.fixture
def loaded(db_session):
    countries = seed_three_countries(db_session)
    for iso3, dirname in (("XAA", "XA_alandra"), ("XBB", "XB_boroland"), ("XCC", "XC_cyria")):
        batch, report = import_fixture(db_session, countries[iso3], dirname)
        assert report.quarantined == 0
    return countries


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_country_levels_exposed_dynamically(client, loaded):
    """Each country's hierarchy comes back exactly as configured — the
    frontend can render any depth without country-specific branches."""
    for iso3, expected in (
        ("XAA", [("Region", 1), ("District", 2)]),
        ("XBB", [("Province", 1), ("County", 2), ("Ward", 3)]),
        ("XCC", [("Governorate", 1), ("Department", 2), ("Commune", 3), ("Village", 4)]),
    ):
        levels = client.get(f"/api/v1/countries/{iso3}/levels").json()
        assert [(l["level_name"], l["level_number"]) for l in levels] == expected


def test_country_detail_unit_counts(client, loaded):
    body = client.get("/api/v1/countries/XBB").json()
    counts = {l["level_number"]: l["unit_count"] for l in body["levels"]}
    assert counts == {1: 2, 2: 4, 3: 8}
    assert body["total_units"] == 14
    assert body["max_level"] == 3


def test_countries_listing(client, loaded):
    countries = client.get("/api/v1/countries").json()
    iso3s = {c["iso3"] for c in countries}
    assert {"XAA", "XBB", "XCC"} <= iso3s


def test_duplicate_country_code_conflict(client):
    payload = {
        "iso2": "XA",
        "iso3": "XAA",
        "name": "Duplicate",
        "levels": [{"level_number": 1, "level_name": "Region"}],
    }
    assert client.post("/api/v1/countries", json=payload).status_code == 201
    # both iso2 and iso3 clashes are caught
    assert client.post("/api/v1/countries", json=payload).status_code == 409
    assert (
        client.post(
            "/api/v1/countries",
            json={"iso2": "XB", "iso3": "XAA", "name": "Clash3", "levels": [{"level_number": 1, "level_name": "R"}]},
        ).status_code
        == 409
    )


def test_create_country_validation_errors(client):
    resp = client.post(
        "/api/v1/countries",
        json={"iso2": "XY", "iso3": "XYZ", "name": "Bad", "levels": [{"level_number": 1, "level_name": "R"}]},
    )
    assert resp.status_code == 201  # iso2/iso3 mismatch across countries is allowed (XY/XYZ unused)

    # duplicate codes are handled in test_duplicate_country_code_conflict;
    # here: alpha-3 must be at least 3 letters
    resp = client.post(
        "/api/v1/countries",
        json={"iso2": "ZQ", "iso3": "ZQ", "name": "Short", "levels": [{"level_number": 1, "level_name": "R"}]},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/v1/countries",
        json={"iso2": "ZZ", "iso3": "ZZZ", "name": "NoLevels", "levels": []},
    )
    assert resp.status_code == 422


def test_unit_browse_filters(client, loaded):
    level2 = client.get("/api/v1/countries/XAA/units?level_number=2").json()
    assert len(level2) == 6
    by_parent = client.get("/api/v1/countries/XAA/units?parent_code=XA-R2").json()
    assert [u["official_code"] for u in by_parent] == ["XA-D21", "XA-D22"]
    assert all(u["level_name"] == "District" for u in by_parent)


def test_unit_detail_includes_geometry_and_version_count(client, loaded):
    units = client.get("/api/v1/countries/XAA/units?level_number=2").json()
    detail = client.get(f"/api/v1/units/{units[0]['id']}").json()
    assert detail["geometry_geojson"]["type"] == "MultiPolygon"
    assert detail["boundary_version_count"] == 1
    assert detail["parent_code"] == "XA-R1"


def test_boundaries_featurecollection(client, loaded):
    fc = client.get("/api/v1/countries/XCC/boundaries?level_number=4").json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 8
    geom = fc["features"][0]["geometry"]
    assert geom["type"] == "MultiPolygon"
    assert fc["features"][0]["properties"]["level_name"] == "Village"


def test_404s(client):
    assert client.get("/api/v1/countries/ZZZ").status_code == 404
    assert client.get("/api/v1/units/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/api/v1/units/not-a-uuid").status_code == 400
    assert client.get("/api/v1/imports/00000000-0000-0000-0000-000000000000").status_code == 404


def test_openapi_documents_all_v1_paths(client):
    """The public API contract is documented (blueprint §4.12 foundation)."""
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    for path in (
        "/api/v1/countries",
        "/api/v1/countries/{iso3}",
        "/api/v1/countries/{iso3}/levels",
        "/api/v1/countries/{iso3}/units",
        "/api/v1/countries/{iso3}/boundaries",
        "/api/v1/units/{unit_id}",
        "/api/v1/units/{unit_id}/children",
        "/api/v1/units/{unit_id}/ancestors",
        "/api/v1/spatial/point",
        "/api/v1/spatial/bbox",
        "/api/v1/imports/geojson",
        "/api/v1/imports/gpkg",
        "/api/v1/imports/{batch_id}",
        "/api/v1/imports/{batch_id}/quarantine",
    ):
        assert path in paths, path
