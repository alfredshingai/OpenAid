"""Dynamic country hierarchy configuration (blueprint §16 acceptance 1–3).

The same application code must represent countries with 2, 3 and 4
administrative levels and different local level names, and adding a new
country must require data/configuration only.
"""

from __future__ import annotations

import yaml

from tests.conftest import FIXTURES, import_fixture, seed_country_yaml, seed_three_countries


def test_three_countries_load_with_same_code(db_session):
    countries = seed_three_countries(db_session)
    assert set(countries) == {"XAA", "XBB", "XCC"}


def test_different_hierarchy_shapes(db_session):
    """2-, 3- and 4-level countries all work; level names are per-country."""
    countries = seed_three_countries(db_session)
    assert [l.level_name for l in countries["XAA"].administrative_levels] == ["Region", "District"]
    assert [l.level_name for l in countries["XBB"].administrative_levels] == ["Province", "County", "Ward"]
    assert [l.level_name for l in countries["XCC"].administrative_levels] == [
        "Governorate",
        "Department",
        "Commune",
        "Village",
    ]


def test_countries_import_and_browse_with_shared_code(db_session):
    """All three fixtures import and browse through identical code paths."""
    countries = seed_three_countries(db_session)
    counts = {}
    for iso3, dirname in (("XAA", "XA_alandra"), ("XBB", "XB_boroland"), ("XCC", "XC_cyria")):
        _batch, report = import_fixture(db_session, countries[iso3], dirname)
        assert report.quarantined == 0, report.issues
        counts[iso3] = report.imported
    assert counts == {"XAA": 9, "XBB": 14, "XCC": 15}


def test_fourth_country_needs_no_code_changes(db_session, client):
    """Adding a country = data + configuration + validation (blueprint §16).

    XD (5 levels) is created purely via the public API and data files —
    no application code is touched. This is the core 'country-configurable,
    not country-dependent' proof.
    """
    import json

    from openaid_poc.models import AdministrativeUnit

    # 1. Create a 5-level country via the API (no code changes).
    resp = client.post(
        "/api/v1/countries",
        json={
            "iso2": "XD",
            "iso3": "XDD",
            "name": "Dystopia",
            "levels": [
                {"level_number": i, "level_name": name}
                for i, name in enumerate(["Division", "Region", "District", "Sector", "Cell"], start=1)
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["max_level"] == 5

    # 2. Build a boundary file for XD programmatically (data only).
    features = []
    for i in (1, 2):
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[i - 1, 0], [i, 0], [i, 2], [i - 1, 2], [i - 1, 0]]],
                },
                "properties": {
                    "country_iso3": "XDD",
                    "official_code": f"XD-1-{i}",
                    "name": f"Region {i}",
                    "admin_level": 2,
                    "parent_code": "XD-1-0",
                    "source_unit_id": f"XD-1-{i}",
                },
            }
        )
    features.insert(
        0,
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
            "properties": {
                "country_iso3": "XDD",
                "official_code": "XD-1-0",
                "name": "Division 1",
                "admin_level": 1,
                "source_unit_id": "XD-1-0",
            },
        },
    )
    doc = {"type": "FeatureCollection", "features": features}

    # 3. Import through the standard ingestion endpoint.
    resp = client.post(
        "/api/v1/imports/geojson",
        files={"file": ("xd.geojson", json.dumps(doc), "application/geo+json")},
        data={"country_iso3": "XDD", "source_name": "XD synthetic", "source_is_synthetic": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["report"]["imported"] == 3

    # 4. Browse it with the same hierarchy endpoints used for XA–XC.
    units = client.get("/api/v1/countries/XDD/units?level_number=2").json()
    assert [u["official_code"] for u in units] == ["XD-1-1", "XD-1-2"]
    deepest = client.get("/api/v1/spatial/point?lon=1.5&lat=0.5&country_iso3=XDD&deepest_only=true").json()
    assert deepest["matches"][0]["official_code"] == "XD-1-2"
    assert deepest["matches"][0]["level_name"] == "Region"

    unit_id = units[0]["id"]
    ancestors = client.get(f"/api/v1/units/{unit_id}/ancestors").json()
    assert [a["official_code"] for a in ancestors] == ["XD-1-0"]

    # And the data really is there.
    assert client.get("/api/v1/countries/XDD/units?level_number=2").json()[0] is not None
    from openaid_poc.db import get_engine
    from sqlalchemy import select, func as sa_func

    with get_engine().connect() as conn:
        n = conn.execute(sa_func.count(AdministrativeUnit.id)).scalar_one()
    assert n == 3


def test_level_configuration_from_yaml_is_dynamic(db_session):
    """Level labels come from configuration, not a hardcoded enum."""
    country = seed_country_yaml(db_session, FIXTURES / "XB_boroland" / "country.yaml")
    doc = yaml.safe_load((FIXTURES / "XB_boroland" / "country.yaml").read_text(encoding="utf-8"))
    names_from_config = [l["level_name"] for l in doc["levels"]]
    assert [l.level_name for l in country.administrative_levels] == names_from_config
