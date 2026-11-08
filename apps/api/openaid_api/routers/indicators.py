"""Indicator intelligence router — baseline observations with provenance.

Every observation response carries source, dataset version, value type
(observed/estimated/modelled) and period, so no figure is ever shown
without its evidence trail (blueprint §6).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openaid_core.db import get_db
from openaid_core.geography.models import AdministrativeLevel, AdministrativeUnit, Country
from openaid_core.indicators.models import (
    IndicatorDefinition,
    IndicatorObservation,
    MissingType,
    ValueType,
)

router = APIRouter(prefix="/api/v1", tags=["indicators"])


def _obs_out(session: Session, o: IndicatorObservation, include_unit: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(o.id),
        "indicator": o.definition.code,
        "indicator_name": o.definition.name,
        "unit_label": o.definition.unit,
        "category": o.definition.category.value if hasattr(o.definition.category, "value") else str(o.definition.category),
        "period_start": o.period_start.isoformat(),
        "period_end": o.period_end.isoformat() if o.period_end else None,
        "value": float(o.value) if o.value is not None else None,
        "missing_type": o.missing_type.value if o.missing_type else None,
        "value_type": o.value_type.value if hasattr(o.value_type, "value") else str(o.value_type),
        "sample_size": o.sample_size,
        "source": o.source.name if o.source else None,
        "source_licence": o.source.licence if o.source else None,
        "dataset_version": o.dataset_version,
        "methodology": o.definition.methodology,
        "methodology_notes": o.methodology_notes,
    }
    if include_unit and o.unit is not None:
        out["unit"] = {
            "id": str(o.unit.id),
            "official_code": o.unit.official_code,
            "name": o.unit.name,
            "level_number": o.unit.administrative_level.level_number,
            "level_name": o.unit.administrative_level.level_name,
        }
    return out


@router.get("/indicators")
def list_indicators(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Indicator definitions with unit, methodology and comparability metadata."""
    defs = session.execute(select(IndicatorDefinition).order_by(IndicatorDefinition.code)).scalars().all()
    counts = dict(
        session.execute(
            select(IndicatorObservation.indicator_definition_id, func.count(IndicatorObservation.id))
            .group_by(IndicatorObservation.indicator_definition_id)
        ).all()
    )
    return [
        {
            "id": str(d.id),
            "code": d.code,
            "name": d.name,
            "description": d.description,
            "category": d.category.value if hasattr(d.category, "value") else str(d.category),
            "unit": d.unit,
            "measurement_type": d.measurement_type.value if hasattr(d.measurement_type, "value") else str(d.measurement_type),
            "aggregation_method": d.aggregation_method.value if hasattr(d.aggregation_method, "value") else str(d.aggregation_method),
            "methodology": d.methodology,
            "observation_count": int(counts.get(d.id, 0)),
        }
        for d in defs
    ]


@router.get("/indicators/{code}")
def get_indicator(code: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    d = session.execute(select(IndicatorDefinition).where(IndicatorDefinition.code == code)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail=f"indicator {code} not found")
    count = session.execute(
        select(func.count(IndicatorObservation.id)).where(
            IndicatorObservation.indicator_definition_id == d.id
        )
    ).scalar_one()
    countries = session.execute(
        select(Country.iso3, func.count(IndicatorObservation.id))
        .join(IndicatorObservation, IndicatorObservation.country_id == Country.id)
        .where(IndicatorObservation.indicator_definition_id == d.id)
        .group_by(Country.iso3)
    ).all()
    return {
        "id": str(d.id),
        "code": d.code,
        "name": d.name,
        "description": d.description,
        "category": d.category.value if hasattr(d.category, "value") else str(d.category),
        "unit": d.unit,
        "measurement_type": d.measurement_type.value if hasattr(d.measurement_type, "value") else str(d.measurement_type),
        "aggregation_method": d.aggregation_method.value if hasattr(d.aggregation_method, "value") else str(d.aggregation_method),
        "methodology": d.methodology,
        "observation_count": int(count),
        "coverage_by_country": {iso3: int(n) for iso3, n in countries},
    }


@router.get("/countries/{iso3}/indicators")
def country_indicators(
    iso3: str,
    unit_code: str | None = Query(default=None, description="restrict to one administrative unit"),
    level_number: int | None = None,
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Latest observations per indicator for a country (or one of its units)."""
    country = session.execute(select(Country).where(Country.iso3 == iso3.upper())).scalar_one_or_none()
    if country is None:
        raise HTTPException(status_code=404, detail=f"country {iso3.upper()} not found")

    stmt = (
        select(IndicatorObservation)
        .join(IndicatorDefinition, IndicatorDefinition.id == IndicatorObservation.indicator_definition_id)
        .where(IndicatorObservation.country_id == country.id)
        .order_by(IndicatorDefinition.code, IndicatorObservation.period_start.desc())
    )
    if unit_code:
        unit = session.execute(
            select(AdministrativeUnit).where(
                AdministrativeUnit.country_id == country.id,
                AdministrativeUnit.official_code == unit_code,
            )
        ).scalar_one_or_none()
        if unit is None:
            raise HTTPException(status_code=404, detail=f"unit {unit_code} not found in {iso3.upper()}")
        stmt = stmt.where(IndicatorObservation.unit_id == unit.id)
    elif level_number is not None:
        stmt = stmt.join(AdministrativeUnit, AdministrativeUnit.id == IndicatorObservation.unit_id).where(
            AdministrativeUnit.administrative_level_id.in_(
                select(AdministrativeLevel.id).where(
                    AdministrativeLevel.country_id == country.id,
                    AdministrativeLevel.level_number == level_number,
                )
            )
        )
    else:
        # country-level observations only
        stmt = stmt.where(IndicatorObservation.unit_id.is_(None))

    # latest period per indicator
    seen: set[str] = set()
    out = []
    for o in session.execute(stmt).scalars().all():
        if o.definition.code in seen:
            continue
        seen.add(o.definition.code)
        out.append(_obs_out(session, o))
    return out


@router.get("/countries/{iso3}/indicators/{code}")
def country_indicator_series(
    iso3: str,
    code: str,
    unit_code: str | None = None,
    limit: int = Query(default=500, le=5000),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Full observation series (trend) for one indicator, optionally per unit."""
    country = session.execute(select(Country).where(Country.iso3 == iso3.upper())).scalar_one_or_none()
    if country is None:
        raise HTTPException(status_code=404, detail=f"country {iso3.upper()} not found")
    definition = session.execute(
        select(IndicatorDefinition).where(IndicatorDefinition.code == code)
    ).scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=404, detail=f"indicator {code} not found")

    stmt = (
        select(IndicatorObservation)
        .where(
            IndicatorObservation.country_id == country.id,
            IndicatorObservation.indicator_definition_id == definition.id,
        )
        .order_by(IndicatorObservation.period_start.desc())
        .limit(limit)
    )
    if unit_code:
        unit = session.execute(
            select(AdministrativeUnit).where(
                AdministrativeUnit.country_id == country.id,
                AdministrativeUnit.official_code == unit_code,
            )
        ).scalar_one_or_none()
        if unit is None:
            raise HTTPException(status_code=404, detail=f"unit {unit_code} not found")
        stmt = stmt.where(IndicatorObservation.unit_id == unit.id)

    observations = session.execute(stmt).scalars().all()
    return {
        "country_iso3": country.iso3,
        "indicator": definition.code,
        "unit": definition.unit,
        "aggregation_method": definition.aggregation_method.value
        if hasattr(definition.aggregation_method, "value") else str(definition.aggregation_method),
        "observations": [
            _obs_out(session, o, include_unit=True)
            for o in observations
        ],
    }
