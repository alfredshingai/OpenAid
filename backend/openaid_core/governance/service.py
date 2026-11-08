"""Governance service helpers (audit trail)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .models import AuditLog


def record_audit(
    session: Session,
    action: str,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append one audit row. Call inside the caller's transaction."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )
