"""Review→publish pipeline tests: approved submissions apply real changes."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from tests.backend.conftest import auth_headers, register_and_login


def _actor_tokens(client):
    admin = register_and_login(client, "publish_admin")["token"]
    contrib = register_and_login(client, "publish_contrib")["token"]
    return admin, contrib


def _submit(client, token, payload, ctype="facility_correction"):
    r = client.post(
        "/api/v1/submissions",
        headers=auth_headers(token),
        json={"submission_type": ctype, "payload": payload},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Facility correction
# ---------------------------------------------------------------------------


def test_facility_correction_applies_on_approval(client, seeded_bundle):
    from openaid_core.db import get_engine
    from openaid_core.facilities.models import Facility

    admin, contrib = _actor_tokens(client)

    with get_engine().connect() as conn:
        row = conn.execute(
            select(Facility.id, Facility.source_facility_id, Facility.name).limit(1)
        ).one()
        facility_id, source_fid, old_name = str(row[0]), row[1], row[2]

    sid = _submit(
        client,
        contrib,
        {
            "facility_id": facility_id,
            "changes": {"name": "Renamed after verification", "operational_status": "reported_operational"},
        },
    )
    resp = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin),
        json={"action": "approved", "notes": "confirmed with the facility"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"
    assert body["applied"]["applied"]["name"] == "Renamed after verification"

    with get_engine().connect() as conn:
        updated = conn.execute(
            select(Facility.name, Facility.operational_status, Facility.verification_status)
            .where(Facility.id == uuid.UUID(facility_id))
        ).one()
    assert updated[0] == "Renamed after verification"
    assert updated[1] == "reported_operational"
    assert updated[2] == "verified"


def test_facility_correction_rejects_disallowed_fields(client, seeded_bundle):
    admin, contrib = _actor_tokens(client)
    from openaid_core.db import get_engine
    from openaid_core.facilities.models import Facility

    with get_engine().connect() as conn:
        facility_id = str(conn.execute(select(Facility.id).limit(1)).scalar_one())

    sid = _submit(
        client, contrib,
        {"facility_id": facility_id, "changes": {"verification_status": "verified"}},
    )
    resp = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin),
        json={"action": "approved"},
    )
    assert resp.status_code == 422
    assert "not correctable" in resp.json()["detail"]
    # submission stays pending — nothing half-applied
    fetched = client.get(f"/api/v1/submissions/{sid}", headers=auth_headers(admin)).json()
    assert fetched["status"] == "pending"


# ---------------------------------------------------------------------------
# Boundary correction → new version, history preserved
# ---------------------------------------------------------------------------


def test_boundary_correction_creates_new_version(client, seeded_bundle):
    from openaid_core.db import get_engine
    from openaid_core.geography.models import BoundaryVersion, AdministrativeUnit

    admin, contrib = _actor_tokens(client)
    engine = get_engine()
    with engine.connect() as conn:
        unit = conn.execute(
            select(AdministrativeUnit.id, AdministrativeUnit.official_code)
            .where(AdministrativeUnit.official_code == "SZ112")
        ).one()
        before = conn.execute(
            select(BoundaryVersion.version).where(BoundaryVersion.unit_id == unit[0])
        ).scalars().all()

    new_geometry = {
        "type": "Polygon",
        "coordinates": [[[31.10, -26.35], [31.30, -26.35], [31.30, -26.20], [31.10, -26.20], [31.10, -26.35]]],
    }
    sid = _submit(
        client, contrib,
        {
            "country_iso3": "SWZ",
            "official_code": "SZ112",
            "geometry": new_geometry,
            "reference_date": "2026-11-01",
        },
        ctype="boundary_correction",
    )
    resp = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin),
        json={"action": "approved", "notes": "gazetted correction"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"]["new_version"] == max(before) + 1

    with engine.connect() as conn:
        versions = conn.execute(
            select(BoundaryVersion.version, BoundaryVersion.valid_from, BoundaryVersion.valid_to)
            .where(BoundaryVersion.unit_id == unit[0])
            .order_by(BoundaryVersion.version)
        ).all()
    assert len(versions) == len(before) + 1, "history must coexist"
    assert versions[-1].valid_to is None  # new current version open
    assert versions[-2].valid_to is not None  # previous version closed


def test_boundary_correction_rejects_invalid_geometry(client, seeded_bundle):
    admin, contrib = _actor_tokens(client)
    sid = _submit(
        client, contrib,
        {
            "country_iso3": "SWZ",
            "official_code": "SZ101",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]},  # bow tie
        },
        ctype="boundary_correction",
    )
    resp = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin),
        json={"action": "approved"},
    )
    assert resp.status_code == 422
    assert "invalid" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# New organisation / dataset records
# ---------------------------------------------------------------------------


def test_organisation_new_applies_on_approval(client):
    from openaid_core.db import get_engine
    from openaid_core.organisations.models import Organisation

    admin, contrib = _actor_tokens(client)
    sid = _submit(
        client, contrib,
        {
            "name": "Mbabane Community Kitchen",
            "org_type": "cbo",
            "description": "Community-run food relief collective (illustrative record from a reviewed submission)",
        },
        ctype="organisation_new",
    )
    resp = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin),
        json={"action": "approved", "notes": "identity and authority checked"},
    )
    assert resp.status_code == 200, resp.text
    org_id = resp.json()["applied"]["organisation_id"]

    orgs = client.get("/api/v1/organisations").json()
    assert orgs["total"] == 1
    assert orgs["organisations"][0]["name"] == "Mbabane Community Kitchen"
    assert orgs["organisations"][0]["verification_status"] == "verified"

    detail = client.get(f"/api/v1/organisations/{org_id}").json()
    assert detail["org_type"] == "cbo"


def test_dataset_new_applies_on_approval(client):
    from openaid_core.db import get_engine
    from openaid_core.datasets.models import Dataset

    admin, contrib = _actor_tokens(client)
    sid = _submit(
        client, contrib,
        {
            "slug": "example-reviewed-dataset",
            "title": "Example dataset via review",
            "description": "Created through the submission workflow (test).",
            "licence": "CC-BY 4.0",
            "access_class": "public",
        },
        ctype="dataset_new",
    )
    resp = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin),
        json={"action": "approved"},
    )
    assert resp.status_code == 200, resp.text
    fetched = client.get("/api/v1/datasets/example-reviewed-dataset").json()
    assert fetched["title"] == "Example dataset via review"
    assert fetched["access_class"] == "public"
    assert fetched["licence"] == "CC-BY 4.0"


def test_duplicate_dataset_slug_rejected_at_review(client):
    admin, contrib = _actor_tokens(client)
    payload = {
        "slug": "dup-slug-test",
        "title": "First",
        "licence": "CC0",
    }
    s1 = _submit(client, contrib, payload, ctype="dataset_new")
    client.post(f"/api/v1/submissions/{s1}/review", headers=auth_headers(admin), json={"action": "approved"})
    s2 = _submit(client, contrib, payload, ctype="dataset_new")
    resp = client.post(f"/api/v1/submissions/{s2}/review", headers=auth_headers(admin), json={"action": "approved"})
    assert resp.status_code == 422
    assert "already exists" in resp.json()["detail"]
    fetched = client.get(f"/api/v1/submissions/{s2}", headers=auth_headers(admin)).json()
    assert fetched["status"] == "pending"
