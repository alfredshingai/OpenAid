"""Governance router: submissions, reviews, audit log (blueprint §4.11)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from openaid_core.config import get_settings
from openaid_core.db import get_db
from openaid_core.geography.models import Country
from openaid_core.governance.models import (
    AuditLog,
    Review,
    Submission,
    SubmissionStatus,
    SubmissionType,
    User,
    UserRole,
)
from openaid_core.governance.publish import ApplicationError, apply_submission
from openaid_core.governance.service import record_audit
from openaid_core.indicators.ingestion import TabularImportMeta, ingest_indicator_file
from openaid_core.indicators.models import ValueType
from openaid_core.datasets.models import DataSource
from openaid_core.geography.models import ImportFormat
from .auth import _user_from_token, require_role

router = APIRouter(prefix="/api/v1", tags=["governance"])

REVIEWER_ROLES = (UserRole.reviewer, UserRole.admin)


class SubmissionIn(BaseModel):
    submission_type: SubmissionType
    payload: dict = Field(min_length=1)
    country_iso3: str | None = None


class ReviewIn(BaseModel):
    action: SubmissionStatus
    notes: str | None = Field(default=None, max_length=4000)


def _submission_out(s: Submission, include_reviews: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(s.id),
        "submission_type": s.submission_type.value if hasattr(s.submission_type, "value") else str(s.submission_type),
        "status": s.status.value if hasattr(s.status, "value") else str(s.status),
        "payload": s.payload,
        "country_iso3": s.country.iso3 if s.country else None,
        "submitted_by": s.submitted_by.username,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
        "review_notes": s.review_notes,
        "reviewed_by": s.reviewed_by.username if s.reviewed_by else None,
    }
    if include_reviews:
        out["reviews"] = [
            {
                "action": r.action.value if hasattr(r.action, "value") else str(r.action),
                "notes": r.notes,
                "reviewer": r.reviewer.username,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in s.reviews
        ]
    return out


@router.post("/submissions", status_code=201)
def create_submission(
    payload: SubmissionIn,
    user: User = Depends(require_role(UserRole.contributor, UserRole.reviewer, UserRole.admin)),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    country_id = None
    if payload.country_iso3:
        country = session.execute(
            select(Country).where(Country.iso3 == payload.country_iso3.upper())
        ).scalar_one_or_none()
        if country is None:
            raise HTTPException(status_code=404, detail=f"country {payload.country_iso3.upper()} not found")
        country_id = country.id
    submission = Submission(
        submitted_by_id=user.id,
        submission_type=payload.submission_type,
        country_id=country_id,
        payload=payload.payload,
    )
    session.add(submission)
    session.flush()
    record_audit(
        session, "submission.created", actor_id=user.id, entity_type="submission",
        entity_id=str(submission.id), detail={"type": payload.submission_type.value},
    )
    return _submission_out(submission)


@router.get("/submissions")
def list_submissions(
    status: SubmissionStatus | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Contributors see their own submissions; reviewers/admins see all."""
    actor = _user_from_token(session, authorization)
    if actor is None:
        raise HTTPException(status_code=401, detail="authentication required")
    role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    stmt = select(Submission).order_by(Submission.created_at.desc()).limit(limit).offset(offset)
    if role not in ("reviewer", "admin"):
        stmt = stmt.where(Submission.submitted_by_id == actor.id)
    if status is not None:
        stmt = stmt.where(Submission.status == status)
    submissions = session.execute(stmt).scalars().unique().all()
    return {
        "total": len(submissions),
        "submissions": [_submission_out(s) for s in submissions],
    }


@router.get("/submissions/{submission_id}")
def get_submission(
    submission_id: str,
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    actor = _user_from_token(session, authorization)
    if actor is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        sid = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="submission_id must be a UUID") from None
    s = session.execute(select(Submission).where(Submission.id == sid)).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="submission not found")
    role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    if role not in ("reviewer", "admin") and s.submitted_by_id != actor.id:
        raise HTTPException(status_code=403, detail="not your submission")
    return _submission_out(s)


@router.post("/submissions/{submission_id}/review")
def review_submission(
    submission_id: str,
    payload: ReviewIn,
    user: User = Depends(require_role(*REVIEWER_ROLES)),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="submission_id must be a UUID") from None
    s = session.execute(select(Submission).where(Submission.id == sid)).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if payload.action == SubmissionStatus.pending:
        raise HTTPException(status_code=422, detail="action must be a review decision")
    applied: dict[str, Any] | None = None
    if payload.action == SubmissionStatus.approved:
        # Approval applies the change inside this transaction; a validation
        # failure rolls everything back and the submission stays pending.
        try:
            applied = apply_submission(session, s)
        except ApplicationError as exc:
            raise HTTPException(status_code=422, detail=f"cannot apply: {exc}") from None
    s.status = payload.action
    s.review_notes = payload.notes
    s.reviewed_by_id = user.id
    s.reviewed_at = datetime.now(timezone.utc)
    s.reviews.append(Review(reviewer_id=user.id, action=payload.action, notes=payload.notes))
    record_audit(
        session, "submission.reviewed", actor_id=user.id, entity_type="submission",
        entity_id=str(s.id),
        detail={"action": payload.action.value, "type": s.submission_type.value, "applied": applied},
    )
    if applied is not None:
        record_audit(
            session, "submission.applied", actor_id=user.id, entity_type="submission",
            entity_id=str(s.id), detail=applied,
        )
    out = _submission_out(s)
    out["applied"] = applied
    return out


@app if False else router.post("/imports/indicators", tags=["ingestion"])
async def import_indicators(
    file: UploadFile = File(...),
    country_iso3: str = Form(...),
    source_name: str | None = Form(default=None),
    source_licence: str | None = Form(default=None),
    source_publisher: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    dataset_version: str | None = Form(default=None),
    value_type: ValueType = Form(default=ValueType.observed),
    user: User = Depends(require_role(UserRole.reviewer, UserRole.admin)),
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Ingest indicator observations from CSV / TSV / XLSX.

    Contract columns: indicator_code, unit_code (empty = country-level),
    period_start, period_end, value, missing_type, sample_size. Rows failing
    validation are quarantined with reasons; valid rows still import.
    """
    from fastapi.responses import JSONResponse as _JSONResponse
    import tempfile
    from pathlib import Path as _Path

    country = session.execute(
        select(Country).where(Country.iso3 == country_iso3.upper())
    ).scalar_one_or_none()
    if country is None:
        raise HTTPException(status_code=404, detail=f"country {country_iso3.upper()} not found")

    data = await file.read()
    settings = get_settings()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file exceeds the upload limit")

    fmt = ImportFormat.xlsx if (file.filename or "").lower().endswith((".xlsx", ".xls")) else ImportFormat.csv

    source = None
    if source_name:
        source = session.execute(
            select(DataSource).where(DataSource.name == source_name)
        ).scalar_one_or_none()
        if source is None:
            source = DataSource(
                name=source_name, licence=source_licence, publisher=source_publisher,
                url=source_url, is_synthetic=False,
                metadata_={"created_via": "indicator_ingestion"},
            )
            session.add(source)
            session.flush()

    meta = TabularImportMeta(
        country_id=country.id,
        country_iso3=country.iso3,
        source=source,
        dataset_version=dataset_version,
        default_value_type=value_type,
        filename=file.filename,
        format=fmt,
    )
    batch, report = ingest_indicator_file(session, meta, data)
    record_audit(
        session, "import.indicators", actor_id=user.id, entity_type="import_batch",
        entity_id=str(batch.id),
        detail={"country": country.iso3, "status": batch.status.value,
                "imported": report.imported, "quarantined": report.quarantined,
                "skipped_duplicates": report.skipped_duplicates},
    )
    status_code = 200 if batch.status.value != "failed" else 422
    return _JSONResponse(status_code=status_code, content={
        "batch_id": str(batch.id),
        "country_iso3": country.iso3,
        "status": batch.status.value,
        "report": report.to_dict(),
    })


@router.get("/audit-log")
def audit_log(
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_role(UserRole.admin)),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Append-only governance trail (admin only)."""
    rows = session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "actor": r.actor.username if r.actor else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
