"""Ingestion & validation behaviour (blueprint §16 acceptance 5, 10).

Covers: successful imports, malformed files, invalid geometries, duplicate
identifiers, missing parents, CRS issues, quarantine and upsert/versioning.
"""

from __future__ import annotations

import json
from datetime import date

from tests.conftest import FIXTURES, import_fixture, seed_country_yaml, seed_three_countries

GOOD_RECT = [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]]


def _feature(**overrides):
    geometry = overrides.pop(
        "geometry", {"type": "Polygon", "coordinates": GOOD_RECT}
    )
    props = {
        "country_iso3": "XAA",
        "official_code": "XA-T1",
        "source_unit_id": "XA-T1",
        "name": "Test Region",
        "admin_level": 1,
        "parent_code": None,
    }
    props.update(overrides)
    if "source_unit_id" not in overrides:
        props["source_unit_id"] = props["official_code"]
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": props,
    }


def _collection(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def _ensure_xa(client):
    """Ensure the XAA country (2 levels) exists via the public API."""
    if client.get("/api/v1/countries/XAA").status_code == 404:
        resp = client.post(
            "/api/v1/countries",
            json={
                "iso2": "XA",
                "iso3": "XAA",
                "name": "Alandra",
                "levels": [
                    {"level_number": 1, "level_name": "Region"},
                    {"level_number": 2, "level_name": "District"},
                ],
            },
        )
        assert resp.status_code == 201, resp.text


def _import_geojson(client, payload, country="XAA", **form):
    if country == "XAA":
        _ensure_xa(client)
    data = {"country_iso3": country, "source_name": "test source", "source_is_synthetic": "true"}
    data.update(form)
    return client.post(
        "/api/v1/imports/geojson",
        files={"file": ("test.geojson", payload, "application/geo+json")},
        data=data,
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_clean_import_all_three_countries(db_session):
    countries = seed_three_countries(db_session)
    for iso3, dirname in (("XAA", "XA_alandra"), ("XBB", "XB_boroland"), ("XCC", "XC_cyria")):
        _batch, report = import_fixture(db_session, countries[iso3], dirname)
        assert report.status.value == "completed"
        assert report.quarantined == 0
        assert report.imported == {"XAA": 9, "XBB": 14, "XCC": 15}[iso3]


def test_polygon_normalised_to_multipolygon_with_warning(client):
    resp = _import_geojson(client, _collection(_feature()))
    assert resp.status_code == 200
    body = resp.json()["report"]
    assert body["imported"] == 1
    assert any("MultiPolygon" in w for w in body["warnings"])


def test_multipolygon_imports_directly(client):
    feature = _feature(
        official_code="XA-M1",
        geometry={
            "type": "MultiPolygon",
            "coordinates": [GOOD_RECT, [[[5, 0], [6, 0], [6, 1], [5, 1], [5, 0]]]],
        },
    )
    resp = _import_geojson(client, _collection(feature))
    assert resp.json()["report"]["imported"] == 1
    assert not any("MultiPolygon" in w for w in resp.json()["report"]["warnings"])


# ---------------------------------------------------------------------------
# Malformed files
# ---------------------------------------------------------------------------


def test_malformed_json_is_failed_batch(client):
    resp = _import_geojson(client, "{not json at all")
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "failed"
    assert body["report"]["issues"][0]["detail"].startswith("not valid JSON")


def test_non_featurecollection_rejected(client):
    resp = _import_geojson(client, json.dumps({"type": "Feature", "geometry": None, "properties": {}}))
    assert resp.status_code == 422
    assert "FeatureCollection" in resp.json()["report"]["issues"][0]["detail"]


# ---------------------------------------------------------------------------
# Geometry validation
# ---------------------------------------------------------------------------


def test_invalid_geometry_quarantined(client):
    """Self-intersecting (bow-tie) polygon must be quarantined, not stored."""
    bow_tie = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]],
    }
    resp = _import_geojson(client, _collection(_feature(official_code="XA-BAD1", geometry=bow_tie)))
    body = resp.json()["report"]
    assert body["imported"] == 0
    assert body["quarantined"] == 1
    assert body["issues"][0]["reason_codes"] == ["invalid_geometry"]


def test_out_of_range_coordinates_quarantined(client):
    far = {"type": "Polygon", "coordinates": [[[500, 0], [501, 0], [501, 1], [500, 1], [500, 0]]]}
    resp = _import_geojson(client, _collection(_feature(official_code="XA-FAR1", geometry=far)))
    body = resp.json()["report"]
    assert body["quarantined"] == 1
    assert body["issues"][0]["reason_codes"] == ["out_of_range_coordinates"]
    assert "CRS" in body["issues"][0]["detail"]


def test_missing_geometry_quarantined(client):
    feature = _feature(official_code="XA-NG1")
    feature["geometry"] = None
    resp = _import_geojson(client, _collection(feature))
    body = resp.json()["report"]
    assert body["quarantined"] == 1
    assert body["issues"][0]["reason_codes"] == ["missing_geometry"]


def test_wrong_geometry_type_quarantined(client):
    point = _feature(official_code="XA-PT1", geometry={"type": "Point", "coordinates": [1, 1]})
    resp = _import_geojson(client, _collection(point))
    body = resp.json()["report"]
    assert body["quarantined"] == 1
    assert body["issues"][0]["reason_codes"] == ["unsupported_geometry_type"]


def test_valid_and_invalid_features_in_one_batch(client):
    """Valid features import even when siblings are quarantined (§16)."""
    bad = _feature(official_code="XA-BAD2", geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 0], [0, 0]]]})  # degenerate but "valid"? make invalid bow tie instead
    bad["geometry"] = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}
    resp = _import_geojson(client, _collection(_feature(official_code="XA-OK1"), bad))
    body = resp.json()["report"]
    assert body["imported"] == 1
    assert body["quarantined"] == 1
    assert resp.json()["status"] == "completed_with_quarantine"


# ---------------------------------------------------------------------------
# Duplicates & identifiers
# ---------------------------------------------------------------------------


def test_duplicate_code_within_file_quarantined(client):
    resp = _import_geojson(client, _collection(_feature(), _feature(name="Copycat")))
    body = resp.json()["report"]
    assert body["imported"] == 1
    assert body["quarantined"] == 1
    assert body["issues"][0]["reason_codes"] == ["duplicate_code"]
    assert "twice in the file" in body["issues"][0]["detail"]


def test_duplicate_code_against_database_quarantined(client):
    assert _import_geojson(client, _collection(_feature())).status_code == 200
    resp = _import_geojson(client, _collection(_feature()))
    body = resp.json()["report"]
    assert body["imported"] == 0
    assert body["quarantined"] == 1
    assert "already exists" in body["issues"][0]["detail"]


# ---------------------------------------------------------------------------
# Country association & levels
# ---------------------------------------------------------------------------


def test_country_mismatch_quarantined(client):
    resp = _import_geojson(
        client, _collection(_feature(country_iso3="XBB")), country="XAA"
    )
    body = resp.json()["report"]
    assert body["imported"] == 0
    assert body["issues"][0]["reason_codes"] == ["country_mismatch"]


def test_unknown_level_quarantined(client):
    resp = _import_geojson(client, _collection(_feature(admin_level=7, parent_code="XA-R1")))
    body = resp.json()["report"]
    assert body["quarantined"] == 1
    assert body["issues"][0]["reason_codes"] == ["unknown_level"]
    assert "configured levels: 1, 2" in body["issues"][0]["detail"]


# ---------------------------------------------------------------------------
# Parent integrity
# ---------------------------------------------------------------------------


def test_missing_parent_quarantined(client):
    orphan = _feature(official_code="XA-ORPH", admin_level=2, parent_code="XA-NOPE")
    resp = _import_geojson(client, _collection(orphan))
    body = resp.json()["report"]
    assert body["imported"] == 0
    assert body["issues"][0]["reason_codes"] == ["missing_parent"]


def test_wrong_parent_level_quarantined(client):
    """A level-2 unit whose parent is another level-2 unit is rejected."""
    assert _import_geojson(client, _collection(_feature())).status_code == 200
    # A valid level-2 child of the level-1 root first.
    resp = _import_geojson(
        client, _collection(_feature(official_code="XA-L2A", admin_level=2, parent_code="XA-T1"))
    )
    assert resp.json()["report"]["imported"] == 1, resp.json()
    # Now a second level-2 unit parented on that level-2 unit -> invalid.
    resp = _import_geojson(
        client, _collection(_feature(official_code="XA-KID", admin_level=2, parent_code="XA-L2A"))
    )
    body = resp.json()["report"]
    assert body["quarantined"] == 1, body
    assert body["issues"][0]["reason_codes"] == ["invalid_parent_level"]


def test_parent_from_database_resolves(client):
    """A child whose parent exists in the DB (not the file) imports fine."""
    assert _import_geojson(client, _collection(_feature())).status_code == 200
    child = _feature(official_code="XA-D11", admin_level=2, parent_code="XA-T1")
    resp = _import_geojson(client, _collection(child))
    assert resp.json()["report"]["imported"] == 1


def test_parent_in_same_file_resolves_and_orders(db_session, client):
    """Level-2 children whose parents are later in the same file still import."""
    child_first = _feature(official_code="XA-K1", admin_level=2, parent_code="XA-ROOT")
    root = _feature(official_code="XA-ROOT", admin_level=1)
    resp = _import_geojson(client, _collection(child_first, root))
    body = resp.json()["report"]
    assert body["imported"] == 2, body
    assert body["quarantined"] == 0


def test_missing_parent_cascades_to_children(client):
    """A quarantined parent blocks its children with an actionable error."""
    bad_parent = _feature(official_code="XA-BADP", admin_level=1, geometry={
        "type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]
    })
    child = _feature(official_code="XA-CHILD", admin_level=2, parent_code="XA-BADP")
    resp = _import_geojson(client, _collection(bad_parent, child))
    body = resp.json()["report"]
    assert body["imported"] == 0
    reasons = {i["feature_index"]: i["reason_codes"] for i in body["issues"]}
    assert reasons[0] == ["invalid_geometry"]
    assert reasons[1] == ["missing_parent"]


# ---------------------------------------------------------------------------
# CRS handling
# ---------------------------------------------------------------------------


def test_geojson_non_wgs84_crs_rejected(client):
    doc = json.loads(_collection(_feature()))
    doc["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}}
    resp = _import_geojson(client, json.dumps(doc))
    assert resp.status_code == 422
    body = resp.json()["report"]
    assert body["issues"][0]["reason_codes"] == ["unsupported_crs"]
    assert "Nothing was imported" in body["issues"][0]["detail"]


def _seed_xa_via_api(client):
    resp = client.post(
        "/api/v1/countries",
        json={
            "iso2": "XA",
            "iso3": "XAA",
            "name": "Alandra",
            "levels": [
                {"level_number": 1, "level_name": "Region"},
                {"level_number": 2, "level_name": "District"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text


def test_gpkg_correct_crs_imports(client, tmp_path):
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Polygon

    _seed_xa_via_api(client)
    gdf = gpd.GeoDataFrame(
        pd.DataFrame(
            [
                {
                    "country_iso3": "XAA",
                    "official_code": "XA-G1",
                    "source_unit_id": "XA-G1",
                    "name": "Region One",
                    "admin_level": 1,
                    "parent_code": None,
                }
            ]
        ),
        geometry=[Polygon(GOOD_RECT[0])],
        crs="EPSG:4326",
    )
    gpkg = tmp_path / "xa.gpkg"
    gdf.to_file(gpkg, layer="admin1", driver="GPKG")
    with gpkg.open("rb") as fh:
        resp = client.post(
            "/api/v1/imports/gpkg",
            files={"file": ("xa.gpkg", fh.read(), "application/geopackage+sqlite3")},
            data={"country_iso3": "XAA", "source_name": "gpkg test", "source_is_synthetic": "true"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["report"]["imported"] == 1


def test_gpkg_wrong_crs_rejected(client, tmp_path):
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Polygon

    _seed_xa_via_api(client)
    gdf = gpd.GeoDataFrame(
        pd.DataFrame(
            [
                {
                    "country_iso3": "XAA",
                    "official_code": "XA-G3857",
                    "source_unit_id": "XA-G3857",
                    "name": "Projected Region",
                    "admin_level": 1,
                    "parent_code": None,
                }
            ]
        ),
        geometry=[Polygon(GOOD_RECT[0])],
        crs="EPSG:3857",
    )
    gpkg = tmp_path / "xa3857.gpkg"
    gdf.to_file(gpkg, layer="admin1", driver="GPKG")
    with gpkg.open("rb") as fh:
        resp = client.post(
            "/api/v1/imports/gpkg",
            files={"file": ("xa3857.gpkg", fh.read(), "application/geopackage+sqlite3")},
            data={"country_iso3": "XAA", "source_name": "gpkg test", "source_is_synthetic": "true"},
        )
    assert resp.status_code == 422
    body = resp.json()["report"]
    assert body["issues"][0]["reason_codes"] == ["unsupported_crs"]
    assert "EPSG:3857" in body["issues"][0]["detail"]


# ---------------------------------------------------------------------------
# Upsert & boundary versioning
# ---------------------------------------------------------------------------


def test_upsert_creates_new_boundary_version_and_preserves_history(client):
    from sqlalchemy import select

    from openaid_poc.db import get_engine
    from openaid_poc.models import AdministrativeUnit, BoundaryVersion

    assert _import_geojson(client, _collection(_feature()), ).status_code == 200

    moved = _feature(geometry={"type": "Polygon", "coordinates": [[[1, 0], [3, 0], [3, 1], [1, 1], [1, 0]]]})
    resp = _import_geojson(client, _collection(moved), upsert="true", reference_date="2026-06-01")
    assert resp.status_code == 200, resp.text
    body = resp.json()["report"]
    assert body["upserted"] == 1

    engine = get_engine()
    with engine.connect() as conn:
        versions = conn.execute(
            select(BoundaryVersion.version, BoundaryVersion.valid_from, BoundaryVersion.valid_to)
            .join(AdministrativeUnit, AdministrativeUnit.id == BoundaryVersion.unit_id)
            .where(AdministrativeUnit.official_code == "XA-T1")
            .order_by(BoundaryVersion.version)
        ).all()
    assert len(versions) == 2, "history must coexist, not be overwritten"
    v1, v2 = versions
    assert v1.version == 1 and v1.valid_to == date(2026, 6, 1), "v1 closed out"
    assert v2.version == 2 and v2.valid_to is None, "v2 current"

    # Non-upsert re-import of the same code stays quarantined.
    resp = _import_geojson(client, _collection(_feature()))
    assert resp.json()["report"]["quarantined"] == 1


def test_quarantine_endpoint_returns_actionable_detail(client):
    resp = _import_geojson(client, _collection(_feature(official_code="XA-Q1", admin_level=9, parent_code="XA-R1")))
    batch_id = resp.json()["batch_id"]
    rows = client.get(f"/api/v1/imports/{batch_id}/quarantine").json()
    assert len(rows) == 1
    assert rows[0]["reason_codes"] == ["unknown_level"]
    assert rows[0]["feature_index"] == 0


def test_import_batch_report_retrievable(client):
    resp = _import_geojson(client, _collection(_feature()))
    batch_id = resp.json()["batch_id"]
    fetched = client.get(f"/api/v1/imports/{batch_id}").json()
    assert fetched["status"] == "completed"
    assert fetched["report"]["imported"] == 1
