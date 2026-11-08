"""CSV/XLSX indicator ingestion tests."""

from __future__ import annotations

from sqlalchemy import select

from tests.backend.conftest import auth_headers, register_and_login

CSV_VALID = """country_iso3,unit_code,indicator_code,period_start,period_end,value,missing_type,sample_size
SWZ,,total_population,2020-12-31,,1109299,
SWZ,SZ101,total_population,2020-12-31,,9113,
SWZ,SZ102,education_facilities_count,2020-12-31,,41,
SWZ,SZ103,education_facilities_count,2020-12-31,,,not_collected
"""

CSV_MIXED = """country_iso3,unit_code,indicator_code,period_start,value,missing_type
SWZ,SZ999,total_population,2020-12-31,123,
SWZ,SZ101,unknown_indicator,2020-12-31,5,
SWZ,SZ101,total_population,not-a-date,5,
SWZ,SZ101,total_population,2020-12-31,abc,
SWZ,SZ101,total_population,2020-12-31,5,suppressed
SWZ,SZ101,total_population,2020-12-31,,
"""


def _admin(client):
    return register_and_login(client, "ingest_admin")["token"]


def _import(client, token, content: bytes, filename="indicators.csv", **form):
    data = {"country_iso3": "SWZ", "source_name": "CSV test source",
            "source_licence": "CC0", "dataset_version": "test-v1", **form}
    return client.post(
        "/api/v1/imports/indicators",
        files={"file": (filename, content, "text/csv")},
        data=data,
        headers=auth_headers(token),
    )


def test_csv_import_valid_rows(client, seeded_bundle):
    token = _admin(client)
    resp = _import(client, token, CSV_VALID.encode())
    assert resp.status_code == 200, resp.text
    body = resp.json()["report"]
    assert body["imported"] == 4
    assert body["quarantined"] == 0

    # verify values landed with provenance
    series = client.get("/api/v1/countries/SWZ/indicators/total_population").json()
    row = next(o for o in series["observations"] if o.get("unit") is None and o["dataset_version"] == "test-v1")
    assert abs(row["value"] - 1109299) < 1
    assert row["source"] == "CSV test source"
    assert row["source_licence"] == "CC0"


def test_csv_import_quarantines_bad_rows(client, seeded_bundle):
    token = _admin(client)
    resp = _import(client, token, CSV_MIXED.encode())
    assert resp.status_code == 200
    body = resp.json()["report"]
    assert body["imported"] == 0
    assert body["quarantined"] == 6
    reasons = {tuple(i["reason_codes"]) for i in body["issues"]}
    assert ("unknown_unit",) in reasons
    assert ("unknown_indicator",) in reasons
    assert ("invalid_period",) in reasons
    assert ("invalid_value",) in reasons
    assert ("value_and_missing",) in reasons
    # batch report retrievable with the quarantine
    batch_id = resp.json()["batch_id"]
    q = client.get(f"/api/v1/imports/{batch_id}").json()
    assert q["status"] == "completed_with_quarantine"


def test_csv_duplicates_skipped(client, seeded_bundle):
    token = _admin(client)
    first = _import(client, token, CSV_VALID.encode())
    assert first.json()["report"]["imported"] == 4
    second = _import(client, token, CSV_VALID.encode())
    assert second.json()["report"]["imported"] == 0
    assert second.json()["report"]["skipped_duplicates"] == 4


def test_xlsx_import_roundtrip(client, seeded_bundle):
    import io

    import pandas as pd

    token = _admin(client)
    frame = pd.DataFrame(
        [
            {"country_iso3": "SWZ", "unit_code": "", "indicator_code": "total_population",
             "period_start": "2020-12-31", "value": 1109299, "missing_type": None},
            {"country_iso3": "SWZ", "unit_code": "SZ101", "indicator_code": "road_density",
             "period_start": "2020-12-31", "value": 44.7, "missing_type": None},
        ]
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="observations")
    xlsx = buf.getvalue()

    resp = _import(client, token, xlsx, filename="indicators.xlsx")
    assert resp.status_code == 200, resp.text
    body = resp.json()["report"]
    assert body["imported"] == 2
    assert body["quarantined"] == 0
    series = client.get("/api/v1/countries/SWZ/indicators/total_population").json()
    assert any(
        o.get("unit") is None and o["dataset_version"] == "test-v1" and abs(o["value"] - 1109299) < 1
        for o in series["observations"]
    )


def test_indicator_import_requires_reviewer(client, seeded_bundle):
    register_and_login(client, "ingest_admin")  # admin
    contrib = register_and_login(client, "ingest_contrib")["token"]
    resp = _import(client, contrib, CSV_VALID.encode())
    assert resp.status_code == 403
    anon = client.post(
        "/api/v1/imports/indicators",
        files={"file": ("indicators.csv", CSV_VALID.encode(), "text/csv")},
        data={"country_iso3": "SWZ"},
    )
    assert anon.status_code == 401


def test_malformed_csv_failed_batch(client, seeded_bundle):
    token = _admin(client)
    # Binary garbage cannot decode as UTF-8 -> pandas raises -> failed batch.
    resp = _import(client, token, b"\x00\x01\x02\xff" * 256)
    assert resp.status_code == 422, resp.text
    assert resp.json()["status"] == "failed"
    assert resp.json()["report"]["issues"][0]["reason_codes"] == ["invalid_file"]
