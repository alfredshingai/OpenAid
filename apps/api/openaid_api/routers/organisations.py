"""Organisation registry router (read-only for Phase 1; no synthetic orgs shipped)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openaid_core.db import get_db
from openaid_core.geography.models import Country
from openaid_core.organisations.models import Organisation, OrganisationLocation, OrganisationSector

router = APIRouter(prefix="/api/v1", tags=["organisations"])


@router.get("/organisations")
def list_organisations(
    org_type: str | None = None,
    country_iso3: str | None = None,
    sector: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Organisation directory. The registry ships empty: organisations are
    added only with source evidence, and presence types (HQ vs office vs
    operations) are stored as separate facts."""
    stmt = select(Organisation).order_by(Organisation.name).limit(limit).offset(offset)
    count_stmt = select(func.count(func.distinct(Organisation.id))).select_from(Organisation)
    if org_type:
        stmt = stmt.where(Organisation.org_type == org_type)
        count_stmt = count_stmt.where(Organisation.org_type == org_type)
    if country_iso3:
        country = session.execute(
            select(Country).where(Country.iso3 == country_iso3.upper())
        ).scalar_one_or_none()
        if country is None:
            raise HTTPException(status_code=404, detail=f"country {country_iso3.upper()} not found")
        stmt = stmt.join(Organisation.locations).where(OrganisationLocation.country_id == country.id)
        count_stmt = count_stmt.join(Organisation.locations).where(OrganisationLocation.country_id == country.id)
    if sector:
        stmt = stmt.join(Organisation.sectors).where(OrganisationSector.sector == sector)
        count_stmt = count_stmt.join(Organisation.sectors).where(OrganisationSector.sector == sector)

    total = session.execute(count_stmt).scalar_one()
    return {
        "total": int(total),
        "organisations": [
            {
                "id": str(o.id),
                "name": o.name,
                "acronym": o.acronym,
                "org_type": o.org_type.value if hasattr(o.org_type, "value") else str(o.org_type),
                "website": o.website,
                "verification_status": o.verification_status.value
                if hasattr(o.verification_status, "value") else str(o.verification_status),
                "location_count": len(o.locations),
            }
            for o in session.execute(stmt).scalars().unique().all()
        ],
    }


@router.get("/organisations/{org_id}")
def get_organisation(org_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        oid = uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="org_id must be a UUID") from None
    o = session.execute(select(Organisation).where(Organisation.id == oid)).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail="organisation not found")
    return {
        "id": str(o.id),
        "name": o.name,
        "acronym": o.acronym,
        "org_type": o.org_type.value if hasattr(o.org_type, "value") else str(o.org_type),
        "description": o.description,
        "mandate": o.mandate,
        "website": o.website,
        "public_contact": o.public_contact,
        "verification_status": o.verification_status.value
        if hasattr(o.verification_status, "value") else str(o.verification_status),
        "sectors": [s.sector for s in o.sectors],
        "locations": [
            {
                "location_type": l.location_type.value if hasattr(l.location_type, "value") else str(l.location_type),
                "country_id": str(l.country_id) if l.country_id else None,
                "unit_id": str(l.unit_id) if l.unit_id else None,
                "valid_from": l.valid_from.isoformat() if l.valid_from else None,
                "valid_to": l.valid_to.isoformat() if l.valid_to else None,
                "verification_status": l.verification_status.value
                if hasattr(l.verification_status, "value") else str(l.verification_status),
                "source": l.source.name if l.source else None,
            }
            for l in o.locations
        ],
    }
