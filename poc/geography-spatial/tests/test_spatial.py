"""Spatial query behaviour (blueprint §16 acceptance 6).

Point-in-polygon, bbox intersection and hierarchy walking against the
synthetic rectangular fixtures, where the expected answer is known exactly.
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


def test_point_in_polygon_deepest_match(client, loaded):
    resp = client.get("/api/v1/spatial/point?lon=1.0&lat=0.5&country_iso3=XAA&deepest_only=true")
    body = resp.json()
    assert body["match_count"] == 1
    match = body["matches"][0]
    assert match["official_code"] == "XA-D11"
    assert match["level_name"] == "District"


def test_point_in_polygon_returns_full_chain(client, loaded):
    """A point inside Cyria matches all four levels, ordered shallow→deep."""
    resp = client.get("/api/v1/spatial/point?lon=0.5&lat=0.5&country_iso3=XCC")
    codes = [m["official_code"] for m in resp.json()["matches"]]
    assert codes == ["XC-G1", "XC-D1", "XC-M11", "XC-V111"]


def test_point_in_polygon_without_country_filter(client, loaded):
    """Same point queried continent-wide returns matches per country."""
    resp = client.get("/api/v1/spatial/point?lon=1.0&lat=0.5")
    by_country = {m["country_iso3"] for m in resp.json()["matches"]}
    assert {"XAA", "XBB", "XCC"} <= by_country


def test_point_outside_all_returns_empty(client, loaded):
    resp = client.get("/api/v1/spatial/point?lon=20.0&lat=20.0")
    assert resp.json()["match_count"] == 0


def test_bbox_intersection(client, loaded):
    """BBox over part of XB province 2 (x 2..4, y 1..2 band + wards)."""
    resp = client.get("/api/v1/spatial/bbox?minx=2.2&miny=1.1&maxx=2.8&maxy=1.9&country_iso3=XBB")
    codes = [u["official_code"] for u in resp.json()["units"]]
    assert codes == ["XB-P2", "XB-C22", "XB-W221"]


def test_bbox_level_filter(client, loaded):
    resp = client.get(
        "/api/v1/spatial/bbox?minx=0.1&miny=0.1&maxx=3.9&maxy=1.9&country_iso3=XAA&level_number=2"
    )
    codes = {u["official_code"] for u in resp.json()["units"]}
    assert codes == {"XA-D11", "XA-D12", "XA-D21", "XA-D22"}


def test_bbox_invalid_order_rejected(client, loaded):
    resp = client.get("/api/v1/spatial/bbox?minx=3&miny=1&maxx=1&maxy=0")
    assert resp.status_code == 422


def test_ancestors_recursive_walk_root_first(client, loaded):
    units = client.get("/api/v1/countries/XCC/units?level_number=4").json()
    unit_id = next(u["id"] for u in units if u["official_code"] == "XC-V111")
    ancestors = client.get(f"/api/v1/units/{unit_id}/ancestors").json()
    assert [(a["level_number"], a["official_code"]) for a in ancestors] == [
        (1, "XC-G1"),
        (2, "XC-D1"),
        (3, "XC-M11"),
    ]


def test_children_walk(client, loaded):
    units = client.get("/api/v1/countries/XAA/units?level_number=1").json()
    r1 = next(u for u in units if u["official_code"] == "XA-R1")
    children = client.get(f"/api/v1/units/{r1['id']}/children").json()
    assert [c["official_code"] for c in children] == ["XA-D11", "XA-D12"]


def test_parent_child_consistency_enforced_by_trigger(db_session, loaded):
    """The database trigger rejects a parent from another country (defense in depth)."""
    from sqlalchemy import text

    from openaid_poc.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        child = conn.execute(
            text("SELECT id, administrative_level_id, country_id FROM administrative_units WHERE official_code = 'XA-D11'")
        ).one()
        foreign_parent = conn.execute(
            text("SELECT id FROM administrative_units WHERE official_code = 'XB-P1'")
        ).scalar_one()
        try:
            conn.execute(
                text("UPDATE administrative_units SET parent_unit_id = :p WHERE id = :c"),
                {"p": str(foreign_parent), "c": str(child.id)},
            )
        except Exception as exc:
            assert "different country" in str(exc)
        else:
            raise AssertionError("trigger must reject cross-country parenting")
