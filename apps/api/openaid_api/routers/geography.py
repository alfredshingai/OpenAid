"""Geography & hierarchy router (promoted from the §16 PoC, unchanged contract)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from geoalchemy2.elements import WKBElement, WKTElement
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from openaid_core.config import SRID, get_settings
from openaid_core.db import get_db
from openaid_core.datasets.models import DataSource
from openaid_core.governance.models import User, UserRole
from openaid_core.governance.service import record_audit
from .auth import require_role
from openaid_core.geography.ingestion import ImportMeta, ingest_geojson_bytes, ingest_gpkg_file
from openaid_core.geography.models import (
    AdministrativeLevel,
    AdministrativeUnit,
    BoundaryVersion,
    Country,
    CountryConfiguration,
    CountryStatus,
    ImportBatch,
    ImportFormat,
    VerificationStatus,
)

router = APIRouter(prefix="/api/v1", tags=["geography"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AdministrativeLevelIn(BaseModel):
    level_number: int = Field(ge=1)
    level_name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class CountryIn(BaseModel):
    iso2: str = Field(min_length=2, max_length=2)
    iso3: str = Field(min_length=3, max_length=3)
    name: str = Field(min_length=1, max_length=200)
    official_name: str | None = None
    capital: str | None = None
    region: str | None = None
    languages: list[str] | None = None
    currency: str | None = None
    timezone: str | None = None
    levels: list[AdministrativeLevelIn] = Field(min_length=1)

    @field_validator("iso2")
    @classmethod
    def _iso2_upper(cls, v: str) -> str:
        v = v.upper()
        if not v.isalpha():
            raise ValueError("iso2 must be two letters")
        return v

    @field_validator("iso3")
    @classmethod
    def _iso3_upper(cls, v: str) -> str:
        v = v.upper()
        if not v.isalpha():
            raise ValueError("iso3 must be three letters")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _or_404(value: Any, message: str) -> Any:
    if value is None:
        raise HTTPException(status_code=404, detail=message)
    return value


def _get_country(session: Session, iso3: str) -> Country:
    return _or_404(
        session.execute(select(Country).where(Country.iso3 == iso3.upper())).scalar_one_or_none(),
        f"country {iso3.upper()} not found",
    )


def _country_out(session: Session, country: Country) -> dict[str, Any]:
    counts: dict[int, int] = {}
    for level_number, unit_count in session.execute(
        select(AdministrativeLevel.level_number, func.count(AdministrativeUnit.id))
        .join(AdministrativeUnit, AdministrativeUnit.administrative_level_id == AdministrativeLevel.id)
        .where(AdministrativeLevel.country_id == country.id)
        .group_by(AdministrativeLevel.level_number)
    ).all():
        counts[level_number] = unit_count
    levels = [
        {
            "level_number": level.level_number,
            "level_name": level.level_name,
            "description": level.description,
            "unit_count": counts.get(level.level_number, 0),
        }
        for level in country.administrative_levels
    ]
    return {
        "id": str(country.id),
        "iso2": country.iso2,
        "iso3": country.iso3,
        "name": country.name,
        "official_name": country.official_name,
        "capital": country.capital,
        "region": country.region,
        "rep_lon": float(country.rep_lon) if country.rep_lon is not None else None,
        "rep_lat": float(country.rep_lat) if country.rep_lat is not None else None,
        "status": country.status.value if hasattr(country.status, "value") else str(country.status),
        "levels": levels,
        "total_units": sum(counts.values()),
        "max_level": max((level.level_number for level in country.administrative_levels), default=0),
    }


def _unit_out(session: Session, unit: AdministrativeUnit) -> dict[str, Any]:
    parent_code = None
    if unit.parent_unit_id:
        parent_code = session.execute(
            select(AdministrativeUnit.official_code).where(AdministrativeUnit.id == unit.parent_unit_id)
        ).scalar_one_or_none()
    return {
        "id": str(unit.id),
        "name": unit.name,
        "official_code": unit.official_code,
        "country_iso3": session.execute(
            select(Country.iso3).where(Country.id == unit.country_id)
        ).scalar_one(),
        "level_number": unit.administrative_level.level_number,
        "level_name": unit.administrative_level.level_name,
        "parent_unit_id": str(unit.parent_unit_id) if unit.parent_unit_id else None,
        "parent_code": parent_code,
        "reference_date": unit.reference_date,
        "verification_status": unit.verification_status.value
        if hasattr(unit.verification_status, "value")
        else str(unit.verification_status),
        "source_unit_id": unit.source_unit_id,
    }


def _geometry_to_geojson(geometry: Any) -> dict[str, Any]:
    import shapely

    if isinstance(geometry, (WKBElement, WKTElement)):
        from geoalchemy2.shape import to_shape

        return json.loads(shapely.to_geojson(to_shape(geometry)))
    if isinstance(geometry, (bytes, memoryview, bytearray)):
        return json.loads(shapely.to_geojson(shapely.from_wkb(bytes(geometry))))
    if isinstance(geometry, str):
        t = geometry.strip()
        if t.upper().startswith("SRID="):
            t = t.split(";", 1)[1]
        if t.upper().startswith(("POLYGON", "MULTIPOLYGON")):
            return json.loads(shapely.to_geojson(shapely.from_wkt(t)))
        return json.loads(shapely.to_geojson(shapely.from_wkb(bytes.fromhex(t))))
    if hasattr(geometry, "geom_type"):
        return json.loads(shapely.to_geojson(geometry))
    raise TypeError(f"unsupported geometry type {type(geometry)!r}")


def _get_unit(session: Session, unit_id: str) -> AdministrativeUnit:
    try:
        uid = uuid.UUID(unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="unit_id must be a UUID") from None
    return _or_404(
        session.execute(select(AdministrativeUnit).where(AdministrativeUnit.id == uid)).scalar_one_or_none(),
        f"unit {unit_id} not found",
    )


def _get_or_create_source(
    session: Session, name: str | None, licence: str | None, publisher: str | None,
    url: str | None, is_synthetic: bool,
) -> DataSource | None:
    if not name:
        return None
    source = session.execute(select(DataSource).where(DataSource.name == name)).scalar_one_or_none()
    if source is None:
        source = DataSource(name=name, licence=licence, publisher=publisher, url=url,
                            is_synthetic=is_synthetic, metadata_={"created_via": "ingestion"})
        session.add(source)
        session.flush()
    return source


# ---------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------


@router.get("/countries")
def list_countries(
    status: str | None = None,
    region: str | None = None,
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """All countries with their configured hierarchy and coverage counts.

    Placeholder countries (no data onboarded yet) are included so the
    platform is Africa-wide by architecture while honest about coverage.
    """
    stmt = select(Country).order_by(Country.name)
    if status:
        stmt = stmt.where(Country.status == status)
    if region:
        stmt = stmt.where(Country.region == region)
    return [_country_out(session, c) for c in session.execute(stmt).scalars().all()]


@router.post("/countries", status_code=201)
def create_country(
    payload: CountryIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.reviewer, UserRole.admin)),
) -> dict[str, Any]:
    for existing_iso in (payload.iso2, payload.iso3):
        clash = session.execute(
            select(Country).where((Country.iso2 == existing_iso) | (Country.iso3 == existing_iso))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=409, detail=f"country code {existing_iso} already exists")
    numbers = [level.level_number for level in payload.levels]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(status_code=422, detail="level_number values must be unique")

    country = Country(
        iso2=payload.iso2, iso3=payload.iso3, name=payload.name,
        official_name=payload.official_name, capital=payload.capital, region=payload.region,
        status=CountryStatus.active,
    )
    session.add(country)
    session.flush()
    for level in payload.levels:
        session.add(AdministrativeLevel(country_id=country.id, level_number=level.level_number,
                                        level_name=level.level_name, description=level.description))
    session.add(CountryConfiguration(country_id=country.id, languages=payload.languages,
                                     currency=payload.currency, timezone=payload.timezone))
    session.flush()
    record_audit(session, "country.created", actor_id=user.id, entity_type="country",
                 entity_id=str(country.id), detail={"iso3": country.iso3, "levels": len(payload.levels)})
    return _country_out(session, country)


@router.get("/countries/{iso3}")
def get_country(iso3: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    return _country_out(session, _get_country(session, iso3))


@router.get("/countries/{iso3}/levels")
def get_country_levels(iso3: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    country = _get_country(session, iso3)
    return [
        {"level_number": l.level_number, "level_name": l.level_name, "description": l.description}
        for l in country.administrative_levels
    ]


# ---------------------------------------------------------------------------
# Hierarchy browsing
# ---------------------------------------------------------------------------


@router.get("/countries/{iso3}/units")
def browse_units(
    iso3: str,
    level_number: int | None = None,
    parent_code: str | None = None,
    limit: int = Query(default=200, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    country = _get_country(session, iso3)
    stmt = (
        select(AdministrativeUnit)
        .join(AdministrativeLevel, AdministrativeLevel.id == AdministrativeUnit.administrative_level_id)
        .where(AdministrativeUnit.country_id == country.id)
        .order_by(AdministrativeLevel.level_number, AdministrativeUnit.official_code)
        .limit(limit)
        .offset(offset)
    )
    if level_number is not None:
        stmt = stmt.where(AdministrativeLevel.level_number == level_number)
    if parent_code is not None:
        stmt = stmt.where(
            AdministrativeUnit.parent_unit_id.in_(
                select(AdministrativeUnit.id).where(
                    AdministrativeUnit.official_code == parent_code,
                    AdministrativeUnit.country_id == country.id,
                )
            )
        )
    return [_unit_out(session, u) for u in session.execute(stmt).scalars().all()]


@router.get("/countries/{iso3}/boundaries")
def get_boundaries(
    iso3: str,
    level_number: int | None = None,
    limit: int = Query(default=2000, le=10000),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    country = _get_country(session, iso3)
    params: dict[str, Any] = {"country_id": str(country.id), "limit": limit}
    level_filter = ""
    if level_number is not None:
        level_filter = "AND al.level_number = :level_number"
        params["level_number"] = level_number
    rows = session.execute(
        text(
            f"""
            SELECT u.id, u.official_code, u.name, u.parent_unit_id,
                   al.level_number, al.level_name, u.reference_date,
                   ST_AsGeoJSON(u.geometry) AS geometry
            FROM administrative_units u
            JOIN administrative_levels al ON al.id = u.administrative_level_id
            WHERE u.country_id = :country_id {level_filter}
            ORDER BY al.level_number, u.official_code
            LIMIT :limit
            """
        ),
        params,
    ).all()
    features = [
        {
            "type": "Feature",
            "id": str(r.id),
            "geometry": json.loads(r.geometry),
            "properties": {
                "official_code": r.official_code,
                "name": r.name,
                "level_number": int(r.level_number),
                "level_name": r.level_name,
                "parent_unit_id": str(r.parent_unit_id) if r.parent_unit_id else None,
                "reference_date": r.reference_date.isoformat() if r.reference_date else None,
            },
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/units/{unit_id}")
def get_unit(unit_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    unit = _get_unit(session, unit_id)
    out = _unit_out(session, unit)
    version_count = session.execute(
        select(func.count(BoundaryVersion.id)).where(BoundaryVersion.unit_id == unit.id)
    ).scalar_one()
    return {**out, "geometry_geojson": _geometry_to_geojson(unit.geometry),
            "boundary_version_count": int(version_count)}


@router.get("/units/{unit_id}/children")
def get_unit_children(unit_id: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    unit = _get_unit(session, unit_id)
    children = session.execute(
        select(AdministrativeUnit).where(AdministrativeUnit.parent_unit_id == unit.id)
        .order_by(AdministrativeUnit.official_code)
    ).scalars().all()
    return [_unit_out(session, c) for c in children]


@router.get("/units/{unit_id}/ancestors")
def get_unit_ancestors(unit_id: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Recursive walk to the root (root first) — hierarchy depth is data."""
    unit = _get_unit(session, unit_id)
    rows = session.execute(
        text(
            """
            WITH RECURSIVE chain AS (
                SELECT u.id, u.name, u.official_code, u.parent_unit_id,
                       al.level_number, al.level_name, 0 AS depth
                FROM administrative_units u
                JOIN administrative_levels al ON al.id = u.administrative_level_id
                WHERE u.id = :unit_id
                UNION ALL
                SELECT p.id, p.name, p.official_code, p.parent_unit_id,
                       al.level_number, al.level_name, chain.depth + 1
                FROM administrative_units p
                JOIN administrative_levels al ON al.id = p.administrative_level_id
                JOIN chain ON p.id = chain.parent_unit_id
            )
            SELECT id, name, official_code, level_number, level_name
            FROM chain WHERE depth > 0 ORDER BY depth DESC
            """
        ),
        {"unit_id": str(unit.id)},
    ).all()
    return [
        {"id": str(r.id), "name": r.name, "official_code": r.official_code,
         "level_number": int(r.level_number), "level_name": r.level_name}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Spatial queries
# ---------------------------------------------------------------------------


@router.get("/spatial/point")
def point_in_polygon(
    lon: float = Query(ge=-180, le=180),
    lat: float = Query(ge=-90, le=90),
    country_iso3: str | None = None,
    deepest_only: bool = False,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = (
        select(AdministrativeUnit)
        .join(AdministrativeLevel, AdministrativeLevel.id == AdministrativeUnit.administrative_level_id)
        .where(func.ST_Covers(AdministrativeUnit.geometry,
                              func.ST_SetSRID(func.ST_MakePoint(lon, lat), SRID)))
        .order_by(AdministrativeLevel.level_number)
    )
    if country_iso3:
        stmt = stmt.where(AdministrativeUnit.country_id == _get_country(session, country_iso3).id)
    matches = [_unit_out(session, u) for u in session.execute(stmt).scalars().all()]
    if deepest_only and matches:
        matches = [matches[-1]]
    return {"lon": lon, "lat": lat, "matches": matches, "match_count": len(matches)}


@router.get("/spatial/bbox")
def bbox_intersect(
    minx: float = Query(ge=-180, le=180),
    miny: float = Query(ge=-90, le=90),
    maxx: float = Query(ge=-180, le=180),
    maxy: float = Query(ge=-90, le=90),
    country_iso3: str | None = None,
    level_number: int | None = None,
    limit: int = Query(default=500, le=5000),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    if minx >= maxx or miny >= maxy:
        raise HTTPException(status_code=422, detail="require minx < maxx and miny < maxy")
    envelope = func.ST_MakeEnvelope(minx, miny, maxx, maxy, SRID)
    stmt = (
        select(AdministrativeUnit)
        .join(AdministrativeLevel, AdministrativeLevel.id == AdministrativeUnit.administrative_level_id)
        .where(func.ST_Intersects(AdministrativeUnit.geometry, envelope))
        .order_by(AdministrativeLevel.level_number, AdministrativeUnit.official_code)
        .limit(limit)
    )
    if country_iso3:
        stmt = stmt.where(AdministrativeUnit.country_id == _get_country(session, country_iso3).id)
    if level_number is not None:
        stmt = stmt.where(AdministrativeLevel.level_number == level_number)
    units = session.execute(stmt).scalars().all()
    return {"bbox": [minx, miny, maxx, maxy], "units": [_unit_out(session, u) for u in units],
            "unit_count": len(units)}


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _run_import(
    session: Session, country_iso3: str, fmt: ImportFormat, filename: str | None,
    geojson_bytes: bytes | None, gpkg_path: Path | None, source_name: str | None,
    source_licence: str | None, source_publisher: str | None, source_url: str | None,
    source_is_synthetic: bool, reference_date: date | None, upsert: bool, layer: str | None = None,
    user: User | None = None,
) -> JSONResponse:
    country = _get_country(session, country_iso3)
    source = _get_or_create_source(session, source_name, source_licence,
                                   source_publisher, source_url, source_is_synthetic)
    meta = ImportMeta(
        country_id=country.id,
        country_iso3=country.iso3,
        configured_levels={l.level_number: l.level_name for l in country.administrative_levels},
        source=source,
        reference_date=reference_date,
        upsert=upsert,
        filename=filename,
        format=fmt,
    )
    if fmt == ImportFormat.geojson:
        batch, report = ingest_geojson_bytes(session, meta, geojson_bytes or b"")
    else:
        assert gpkg_path is not None
        batch, report = ingest_gpkg_file(session, meta, gpkg_path, layer=layer)
    payload = {
        "batch_id": str(batch.id),
        "country_iso3": country.iso3,
        "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
        "format": report.format,
        "filename": report.filename,
        "report": report.to_dict(),
    }
    record_audit(session, "import.batch", actor_id=user.id if user else None,
                 entity_type="import_batch", entity_id=payload["batch_id"],
                 detail={"country": country.iso3, "status": payload["status"],
                         "imported": report.imported, "quarantined": report.quarantined})
    return JSONResponse(status_code=200 if payload["status"] != "failed" else 422, content=payload)


@router.post("/imports/geojson")
async def import_geojson(
    file: UploadFile = File(...),
    country_iso3: str = Form(...),
    user: User = Depends(require_role(UserRole.reviewer, UserRole.admin)),
    source_name: str | None = Form(default=None),
    source_licence: str | None = Form(default=None),
    source_publisher: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    source_is_synthetic: bool = Form(default=False),
    reference_date: date | None = Form(default=None),
    upsert: bool = Form(default=False),
    session: Session = Depends(get_db),
) -> JSONResponse:
    data = await file.read()
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"file exceeds the upload limit")
    return _run_import(session, country_iso3, ImportFormat.geojson, file.filename, data, None,
                       source_name, source_licence, source_publisher, source_url,
                       source_is_synthetic, reference_date, upsert)


@router.post("/imports/gpkg")
async def import_gpkg(
    file: UploadFile = File(...),
    country_iso3: str = Form(...),
    user: User = Depends(require_role(UserRole.reviewer, UserRole.admin)),
    layer: str | None = Form(default=None),
    source_name: str | None = Form(default=None),
    source_licence: str | None = Form(default=None),
    source_publisher: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    source_is_synthetic: bool = Form(default=False),
    reference_date: date | None = Form(default=None),
    upsert: bool = Form(default=False),
    session: Session = Depends(get_db),
) -> JSONResponse:
    import tempfile

    data = await file.read()
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="file exceeds the upload limit")
    with tempfile.TemporaryDirectory(prefix="openaid_import_") as tmp:
        gpkg_path = Path(tmp) / (file.filename or "upload.gpkg")
        gpkg_path.write_bytes(data)
        return _run_import(session, country_iso3, ImportFormat.gpkg, file.filename, None, gpkg_path,
                           source_name, source_licence, source_publisher, source_url,
                           source_is_synthetic, reference_date, upsert, layer=layer)


@router.get("/imports/{batch_id}")
def get_import(batch_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="batch_id must be a UUID") from None
    batch = _or_404(
        session.execute(select(ImportBatch).where(ImportBatch.id == bid)).scalar_one_or_none(),
        f"import batch {batch_id} not found",
    )
    return {
        "batch_id": str(batch.id),
        "country_iso3": session.execute(select(Country.iso3).where(Country.id == batch.country_id)).scalar_one(),
        "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
        "format": batch.format.value if hasattr(batch.format, "value") else str(batch.format),
        "filename": batch.filename,
        "report": batch.report,
    }


@router.get("/imports/{batch_id}/quarantine")
def get_import_quarantine(batch_id: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="batch_id must be a UUID") from None
    batch = _or_404(
        session.execute(select(ImportBatch).where(ImportBatch.id == bid)).scalar_one_or_none(),
        f"import batch {batch_id} not found",
    )
    return [
        {"feature_index": q.feature_index, "reason_codes": q.reason_codes, "detail": q.detail,
         "raw_properties": q.raw_properties, "raw_geometry_wkt": q.raw_geometry_wkt}
        for q in batch.quarantined
    ]
