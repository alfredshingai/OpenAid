"""Governance tests: auth/roles, submissions + reviews, audit log, rate limit."""

from __future__ import annotations

from tests.backend.conftest import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Auth & roles
# ---------------------------------------------------------------------------


def test_first_user_is_admin_later_contributors(client):
    first = register_and_login(client, "root")
    assert first["user"]["role"] == "admin"
    second = register_and_login(client, "second")
    assert second["user"]["role"] == "contributor"


def test_login_rejects_wrong_password(client):
    register_and_login(client, "alice")
    bad = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "wrong-password-1"}
    )
    assert bad.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    fake = client.get("/api/v1/auth/me", headers=auth_headers("not.a.token"))
    assert fake.status_code == 401


def test_registration_rejects_short_password(client):
    r = client.post("/api/v1/auth/register", json={"username": "shorty", "password": "short"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Protected write endpoints
# ---------------------------------------------------------------------------


def test_imports_require_reviewer_role(client):
    from tests.backend.conftest import register_and_login

    admin = register_and_login(client, "import_admin")["token"]
    contributor = register_and_login(client, "import_contrib")["token"]

    payload = {
        "country_iso3": "SWZ",
        "source_name": "role test",
        "source_is_synthetic": "true",
    }
    files = {
        "file": (
            "bad.geojson",
            "{not json",
            "application/geo+json",
        )
    }
    # country SWZ may not exist in this test DB (no seed) — expect 404 after auth passes,
    # 401/403 before it: the role gate runs before the country lookup.
    anon = client.post("/api/v1/imports/geojson", files=files, data=payload)
    assert anon.status_code == 401
    contrib = client.post(
        "/api/v1/imports/geojson",
        files=files,
        data=payload,
        headers=auth_headers(contributor),
    )
    assert contrib.status_code == 403
    admin_call = client.post(
        "/api/v1/imports/geojson", files=files, data=payload, headers=auth_headers(admin)
    )
    # role gate passed; the invalid file itself yields 404 (country missing) or 422 (bad file)
    assert admin_call.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Submissions & reviews
# ---------------------------------------------------------------------------


def test_submission_review_lifecycle(client):
    from sqlalchemy import select, func as sa_func

    from openaid_core.db import get_engine
    from openaid_core.governance.models import AuditLog

    admin_token = register_and_login(client, "reviewer_chief")["token"]
    contrib_token = register_and_login(client, "field_worker")["token"]

    created = client.post(
        "/api/v1/submissions",
        headers=auth_headers(contrib_token),
        json={
            "submission_type": "other",
            "payload": {"facility": "Mbabane Clinic", "field": "operational_status", "value": "reported_operational"},
            "country_iso3": "SWZ",
        },
    )
    # SWZ country row absent in this test DB -> 404; use no country instead
    if created.status_code == 404:
        created = client.post(
            "/api/v1/submissions",
            headers=auth_headers(contrib_token),
            json={
                "submission_type": "other",
                "payload": {"facility": "Mbabane Clinic", "field": "operational_status", "value": "reported_operational"},
            },
        )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    # contributor sees own submission
    own = client.get("/api/v1/submissions", headers=auth_headers(contrib_token))
    assert own.json()["total"] == 1

    # contributor cannot review
    forbidden = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(contrib_token),
        json={"action": "approved", "notes": "self-approval"},
    )
    assert forbidden.status_code == 403

    # reviewer approves with notes
    reviewed = client.post(
        f"/api/v1/submissions/{sid}/review",
        headers=auth_headers(admin_token),
        json={"action": "approved", "notes": "verified against source"},
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == "reviewer_chief"
    assert body["reviews"][0]["action"] == "approved"

    # audit trail recorded the lifecycle
    with get_engine().connect() as conn:
        actions = [
            row[0]
            for row in conn.execute(select(AuditLog.action).order_by(AuditLog.created_at)).all()
        ]
    assert "submission.created" in actions
    assert "submission.reviewed" in actions


def test_contributor_cannot_read_audit_log(client):
    register_and_login(client, "audit_admin")
    register_and_login(client, "audit_contrib")
    assert client.get("/api/v1/audit-log").status_code == 401
    contrib = client.get(
        "/api/v1/audit-log",
        headers=auth_headers(
            client.post(
                "/api/v1/auth/login",
                json={"username": "audit_contrib", "password": "governance-pass-1"},
            ).json()["token"]
        ),
    )
    assert contrib.status_code == 403
    admin = client.get(
        "/api/v1/audit-log",
        headers=auth_headers(
            client.post(
                "/api/v1/auth/login",
                json={"username": "audit_admin", "password": "governance-pass-1"},
            ).json()["token"]
        ),
    )
    assert admin.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting (M3)
# ---------------------------------------------------------------------------


def test_rate_limiting_returns_429(clean_db, monkeypatch):
    from openaid_core.config import get_settings
    from openaid_api.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OPENAID_RATE_LIMIT_PER_MINUTE", "5")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as c:
            codes = [c.get("/api/v1/countries").status_code for _ in range(8)]
            assert codes[:5] == [200] * 5
            assert codes[5] == 429
            assert 429 in codes[5:]
            # /health is exempt
            assert c.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()
