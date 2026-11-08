"""Facilities & services directory router (read-only for Phase 1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openaid_core.config import SRID
from openaid_core.db import get_db
from openaid_core.facilities.models import Facility, FacilityType, OperationalStatus
from openaid_core.geography.models import AdministrativeUnit, Country

router = APIRouter(prefix="/api/v1", tags=["facilities"])


def _facility_out(f: Facility, include_geometry: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(f.id),
        "name": f.name,
        "facility_type": f.facility_type.code,
        "facility_type_label": f.facility_type.label,
        "operational_status": f.operational_status.value
        if hasattr(f.operational_status, "value") else str(f.operational_status),
        "reference_date": f.reference_date.isoformat() if f.reference_date else None,
        "source": f.source.name if f.source else None,
        "verification_status": f.verification_status.value
        if hasattr(f.verification_status, "value") else str(f.verification_status),
        "properties": f.properties,
    }
    if include_geometry and f.geometry is not None:
        import json

        import shapely
        from geoalchemy2.shape import to_shape

        out["lon"], out["lat"] = list(to_shape(f.geometry).coords)[0]
    if f.unit_id:
        out["unit"] = {
            "id": str(f.unit_id),
            "official_code": f.unit.official_code if f.unit else None,
            "name": f.unit.name if f.unit else None,
        }
    return out


@router.get("/facility-types")
def list_facility_types(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    types = session.execute(select(FacilityType).order_by(FacilityType.code)).scalars().all()
    counts = dict(
        session.execute(select(Facility.facility_type_id, func.count(Facility.id)).group_by(Facility.facility_type_id)).all()
    )
    return [
        {"id": str(t.id), "code": t.code, "label": t.label, "description": t.description,
         "facility_count": int(counts.get(t.id, 0))}
        for t in types
    ]


@router.get("/countries/{iso3}/facilities")
def country_facilities(
    iso3: str,
    facility_type: str | None = None,
    unit_code: str | None = None,
    operational_status: str | None = None,
    limit: int = Query(default=200, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Facility directory for a country. Operational status is reported as
    stored (often 'unknown') — presence in a dataset is not evidence of
    current operation."""
    country = session.execute(select(Country).where(Country.iso3 == iso3.upper())).scalar_one_or_none()
    if country is None:
        raise HTTPException(status_code=404, detail=f"country {iso3.upper()} not found")
    stmt = (
        select(Facility)
        .where(Facility.country_id == country.id)
        .order_by(Facility.name)
        .limit(limit)
        .offset(offset)
    )
    count_stmt = select(func.count(Facility.id)).where(Facility.country_id == country.id)
    if facility_type:
        ft = session.execute(select(FacilityType).where(FacilityType.code == facility_type)).scalar_one_or_none()
        if ft is None:
            raise HTTPException(status_code=404, detail=f"facility type {facility_type} not found")
        stmt = stmt.where(Facility.facility_type_id == ft.id)
        count_stmt = count_stmt.where(Facility.facility_type_id == ft.id)
    if operational_status:
        try:
            status = OperationalStatus(operational_status)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid operational_status") from None
        stmt = stmt.where(Facility.operational_status == status)
        count_stmt = count_stmt.where(Facility.operational_status == status)
    if unit_code:
        unit = session.execute(
            select(AdministrativeUnit).where(
                AdministrativeUnit.country_id == country.id,
                AdministrativeUnit.official_code == unit_code,
            )
        ).scalar_one_or_none()
        if unit is None:
            raise HTTPException(status_code=404, detail=f"unit {unit_code} not found")
        stmt = stmt.where(Facility.unit_id == unit.id)
        count_stmt = count_stmt.where(Facility.unit_id == unit.id)

    total = session.execute(count_stmt).scalar_one()
    return {
        "country_iso3": country.iso3,
        "total": int(total),
        "facilities": [_facility_out(f, include_geometry=True) for f in session.execute(stmt).scalars().all()],
    }


@router.get("/spatial/facilities")
def facilities_near(
    lon: float = Query(ge=-180, le=180),
    lat: float = Query(ge=-90, le=90),
    radius_km: float = Query(default=10, gt=0, le=200),
    facility_type: str | None = None,
    limit: int = Query(default=50, le=500),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Facilities within a radius of a point (spatial proximity only — this
    says nothing about service availability or quality)."""
    from geoalchemy2 import Geography
    from sqlalchemy import cast, func

    point = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), SRID), Geography)
    stmt = (
        select(Facility)
        .where(
            Facility.geometry.is_not(None),
            func.ST_DWithin(cast(Facility.geometry, Geography), point, radius_km * 1000.0),
        )
        .order_by(Facility.name)
        .limit(limit)
    )
    return {"lon": lon, "lat": lat, "radius_km": radius_km,
            "facilities": [_facility_out(f, include_geometry=True) for f in session.execute(stmt).scalars().all()]}
