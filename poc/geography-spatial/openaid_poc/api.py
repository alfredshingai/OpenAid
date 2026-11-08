"""FastAPI application for the geography & spatial PoC.

Public-by-default exploration endpoints plus controlled ingestion. Hierarchy
navigation is driven entirely by each country's *configuration* — no
country-specific logic exists anywhere in this file (blueprint §5).
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from geoalchemy2 import WKTElement
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import SRID, get_settings
from .db import get_db
from .ingestion import ImportMeta, ingest_geojson_bytes, ingest_gpkg_file
from .models import (
    AdministrativeLevel,
    AdministrativeUnit,
    BoundaryVersion,
    Country,
    CountryConfiguration,
    CountryStatus,
    DataSource,
    ImportBatch,
    ImportFormat,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# Pydantic schemas
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


class LevelOut(BaseModel):
    level_number: int
    level_name: str
    description: str | None
    unit_count: int


class CountryOut(BaseModel):
    id: str
    iso2: str
    iso3: str
    name: str
    official_name: str | None
    capital: str | None
    region: str | None
    status: str
    levels: list[LevelOut]
    total_units: int
    max_level: int


class UnitOut(BaseModel):
    id: str
    name: str
    official_code: str
    country_iso3: str
    level_number: int
    level_name: str
    parent_unit_id: str | None
    parent_code: str | None
    reference_date: date | None
    verification_status: str
    source_unit_id: str | None


class UnitDetailOut(UnitOut):
    geometry_geojson: dict[str, Any]
    boundary_version_count: int


class AncestorOut(BaseModel):
    id: str
    name: str
    official_code: str
    level_number: int
    level_name: str


class ImportReportOut(BaseModel):
    batch_id: str
    country_iso3: str
    status: str
    format: str
    filename: str | None
    report: dict[str, Any]


class QuarantineOut(BaseModel):
    feature_index: int
    reason_codes: list[str]
    detail: str | None
    raw_properties: dict[str, Any] | None
    raw_geometry_wkt: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _or_404(value: Any, message: str) -> Any:
    if value is None:
        raise HTTPException(status_code=404, detail=message)
    return value


def _get_country(session: Session, iso3: str) -> Country:
    country = session.execute(
        select(Country).where(Country.iso3 == iso3.upper())
    ).scalar_one_or_none()
    return _or_404(country, f"country {iso3.upper()} not found")


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
        LevelOut(
            level_number=level.level_number,
            level_name=level.level_name,
            description=level.description,
            unit_count=counts.get(level.level_number, 0),
        ).model_dump()
        for level in country.administrative_levels
    ]
    total = sum(counts.values())
    max_level = max((level.level_number for level in country.administrative_levels), default=0)
    return {
        "id": str(country.id),
        "iso2": country.iso2,
        "iso3": country.iso3,
        "name": country.name,
        "official_name": country.official_name,
        "capital": country.capital,
        "region": country.region,
        "status": country.status.value if hasattr(country.status, "value") else str(country.status),
        "levels": levels,
        "total_units": total,
        "max_level": max_level,
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
        "country_iso3": unit.country.iso3,
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


def _get_unit(session: Session, unit_id: str) -> AdministrativeUnit:
    try:
        uid = uuid.UUID(unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="unit_id must be a UUID") from None
    unit = session.execute(select(AdministrativeUnit).where(AdministrativeUnit.id == uid)).scalar_one_or_none()
    return _or_404(unit, f"unit {unit_id} not found")


def _get_or_create_source(
    session: Session,
    name: str | None,
    licence: str | None,
    publisher: str | None,
    url: str | None,
    is_synthetic: bool,
) -> DataSource | None:
    if not name:
        return None
    source = session.execute(select(DataSource).where(DataSource.name == name)).scalar_one_or_none()
    if source is None:
        source = DataSource(
            name=name,
            licence=licence,
            publisher=publisher,
            url=url,
            is_synthetic=is_synthetic,
            metadata_={"created_via": "ingestion"},
        )
        session.add(source)
        session.flush()
    return source


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OpenAid Geography & Spatial PoC",
        description=(
            "Proof of concept for country-configurable administrative hierarchies "
            "and PostGIS spatial data handling. Synthetic fixtures only — not real data."
        ),
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- health ------------------------------------------------------------
    @app.get("/health", tags=["system"])
    def health(session: Session = Depends(get_db)) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    # -- countries ----------------------------------------------------------
    @app.get("/api/v1/countries", tags=["countries"])
    def list_countries(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
        countries = session.execute(select(Country).order_by(Country.name)).scalars().all()
        return [_country_out(session, c) for c in countries]

    @app.post("/api/v1/countries", status_code=201, tags=["countries"])
    def create_country(payload: CountryIn, session: Session = Depends(get_db)) -> dict[str, Any]:
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
            iso2=payload.iso2,
            iso3=payload.iso3,
            name=payload.name,
            official_name=payload.official_name,
            capital=payload.capital,
            region=payload.region,
            status=CountryStatus.active,
        )
        session.add(country)
        session.flush()
        for level in payload.levels:
            session.add(
                AdministrativeLevel(
                    country_id=country.id,
                    level_number=level.level_number,
                    level_name=level.level_name,
                    description=level.description,
                )
            )
        session.add(
            CountryConfiguration(
                country_id=country.id,
                languages=payload.languages,
                currency=payload.currency,
                timezone=payload.timezone,
            )
        )
        session.flush()
        return _country_out(session, country)

    @app.get("/api/v1/countries/{iso3}", tags=["countries"])
    def get_country(iso3: str, session: Session = Depends(get_db)) -> dict[str, Any]:
        return _country_out(session, _get_country(session, iso3))

    @app.get("/api/v1/countries/{iso3}/levels", tags=["countries"])
    def get_country_levels(iso3: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
        country = _get_country(session, iso3)
        return [
            {
                "level_number": level.level_number,
                "level_name": level.level_name,
                "description": level.description,
            }
            for level in country.administrative_levels
        ]

    # -- unit browsing -------------------------------------------------------
    @app.get("/api/v1/countries/{iso3}/units", tags=["hierarchy"])
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
        return [_unit_out(session, unit) for unit in session.execute(stmt).scalars().all()]

    @app.get("/api/v1/units/{unit_id}", tags=["hierarchy"])
    def get_unit(unit_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
        unit = _get_unit(session, unit_id)
        out = _unit_out(session, unit)
        geom_geojson = json.loads(_st_asgeojson(session, unit.geometry))
        version_count = session.execute(
            select(func.count(BoundaryVersion.id)).where(BoundaryVersion.unit_id == unit.id)
        ).scalar_one()
        return {**out, "geometry_geojson": geom_geojson, "boundary_version_count": int(version_count)}

    @app.get("/api/v1/units/{unit_id}/children", tags=["hierarchy"])
    def get_unit_children(unit_id: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
        unit = _get_unit(session, unit_id)
        children = session.execute(
            select(AdministrativeUnit)
            .where(AdministrativeUnit.parent_unit_id == unit.id)
            .order_by(AdministrativeUnit.official_code)
        ).scalars().all()
        return [_unit_out(session, child) for child in children]

    @app.get("/api/v1/units/{unit_id}/ancestors", tags=["hierarchy"])
    def get_unit_ancestors(unit_id: str, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
        """Recursive walk to the root; returned root-first.

        Uses a recursive CTE — the hierarchy depth is data, not code.
        """
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
                FROM chain
                WHERE depth > 0
                ORDER BY depth DESC
                """
            ),
            {"unit_id": str(unit.id)},
        ).all()
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "official_code": r.official_code,
                "level_number": int(r.level_number),
                "level_name": r.level_name,
            }
            for r in rows
        ]

    # -- boundaries (map data) ------------------------------------------------
    @app.get("/api/v1/countries/{iso3}/boundaries", tags=["hierarchy"])
    def get_boundaries(
        iso3: str,
        level_number: int | None = None,
        limit: int = Query(default=2000, le=10000),
        session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """GeoJSON FeatureCollection of a country's units at a given level."""
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
                       al.level_number, al.level_name,
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
                },
            }
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": features}

    # -- spatial queries -------------------------------------------------------
    @app.get("/api/v1/spatial/point", tags=["spatial"])
    def point_in_polygon(
        lon: float = Query(ge=-180, le=180),
        lat: float = Query(ge=-90, le=90),
        country_iso3: str | None = None,
        deepest_only: bool = False,
        session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """Administrative units containing the point (ST_Covers, EPSG:4326)."""
        stmt = (
            select(AdministrativeUnit)
            .join(AdministrativeLevel, AdministrativeLevel.id == AdministrativeUnit.administrative_level_id)
            .where(
                func.ST_Covers(
                    AdministrativeUnit.geometry,
                    func.ST_SetSRID(func.ST_MakePoint(lon, lat), SRID),
                )
            )
            .order_by(AdministrativeLevel.level_number)
        )
        if country_iso3:
            stmt = stmt.where(AdministrativeUnit.country_id == _get_country(session, country_iso3).id)
        units = session.execute(stmt).scalars().all()
        matches = [_unit_out(session, u) for u in units]
        if deepest_only and matches:
            matches = [matches[-1]]
        return {"lon": lon, "lat": lat, "matches": matches, "match_count": len(matches)}

    @app.get("/api/v1/spatial/bbox", tags=["spatial"])
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
        return {
            "bbox": [minx, miny, maxx, maxy],
            "units": [_unit_out(session, u) for u in units],
            "unit_count": len(units),
        }

    # -- ingestion ---------------------------------------------------------------
    def _run_import(
        session: Session,
        country_iso3: str,
        fmt: ImportFormat,
        filename: str | None,
        geojson_bytes: bytes | None,
        gpkg_path: Path | None,
        source_name: str | None,
        source_licence: str | None,
        source_publisher: str | None,
        source_url: str | None,
        source_is_synthetic: bool,
        reference_date: date | None,
        upsert: bool,
        layer: str | None = None,
    ) -> JSONResponse:
        country = _get_country(session, country_iso3)
        configured_levels = {
            level.level_number: level.level_name for level in country.administrative_levels
        }
        source = _get_or_create_source(
            session, source_name, source_licence, source_publisher, source_url, source_is_synthetic
        )
        meta = ImportMeta(
            country_id=country.id,
            country_iso3=country.iso3,
            configured_levels=configured_levels,
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
        payload = ImportReportOut(
            batch_id=str(batch.id),
            country_iso3=country.iso3,
            status=batch.status.value if hasattr(batch.status, "value") else str(batch.status),
            format=report.format,
            filename=report.filename,
            report=report.to_dict(),
        )
        status_code = 200 if batch.status.value != "failed" else 422
        return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))

    @app.post("/api/v1/imports/geojson", tags=["ingestion"])
    async def import_geojson(
        file: UploadFile = File(...),
        country_iso3: str = Form(...),
        source_name: str | None = Form(default=None),
        source_licence: str | None = Form(default=None),
        source_publisher: str | None = Form(default=None),
        source_url: str | None = Form(default=None),
        source_is_synthetic: bool = Form(default=False),
        reference_date: date | None = Form(default=None),
        upsert: bool = Form(default=False),
        session: Session = Depends(get_db),
    ) -> JSONResponse:
        """Ingest an RFC 7946 GeoJSON FeatureCollection (EPSG:4326 only)."""
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds the {settings.max_upload_mb} MB upload limit",
            )
        return _run_import(
            session, country_iso3, ImportFormat.geojson, file.filename, data, None,
            source_name, source_licence, source_publisher, source_url,
            source_is_synthetic, reference_date, upsert,
        )

    @app.post("/api/v1/imports/gpkg", tags=["ingestion"])
    async def import_gpkg(
        file: UploadFile = File(...),
        country_iso3: str = Form(...),
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
        """Ingest a GeoPackage layer (EPSG:4326 only)."""
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds the {settings.max_upload_mb} MB upload limit",
            )
        # Write to a temp file for GDAL/pyogrio (untrusted upload handling).
        with tempfile.TemporaryDirectory(prefix="openaid_import_") as tmp:
            gpkg_path = Path(tmp) / (file.filename or "upload.gpkg")
            gpkg_path.write_bytes(data)
            return _run_import(
                session, country_iso3, ImportFormat.gpkg, file.filename, None, gpkg_path,
                source_name, source_licence, source_publisher, source_url,
                source_is_synthetic, reference_date, upsert, layer=layer,
            )

    @app.get("/api/v1/imports/{batch_id}", tags=["ingestion"])
    def get_import(batch_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
        try:
            bid = uuid.UUID(batch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="batch_id must be a UUID") from None
        batch = session.execute(select(ImportBatch).where(ImportBatch.id == bid)).scalar_one_or_none()
        batch = _or_404(batch, f"import batch {batch_id} not found")
        return {
            "batch_id": str(batch.id),
            "country_iso3": batch.country.iso3,
            "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
            "format": batch.format.value if hasattr(batch.format, "value") else str(batch.format),
            "filename": batch.filename,
            "report": batch.report,
        }

    @app.get("/api/v1/imports/{batch_id}/quarantine", tags=["ingestion"])
    def get_import_quarantine(batch_id: str, session: Session = Depends(get_db)) -> list[QuarantineOut]:
        try:
            bid = uuid.UUID(batch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="batch_id must be a UUID") from None
        batch = session.execute(select(ImportBatch).where(ImportBatch.id == bid)).scalar_one_or_none()
        batch = _or_404(batch, f"import batch {batch_id} not found")
        return [
            QuarantineOut(
                feature_index=q.feature_index,
                reason_codes=q.reason_codes,
                detail=q.detail,
                raw_properties=q.raw_properties,
                raw_geometry_wkt=q.raw_geometry_wkt,
            )
            for q in batch.quarantined
        ]

    return app


def _st_asgeojson(session: Session, geometry: Any) -> str:
    """Serialise whatever the driver returns for a geometry column to GeoJSON.

    Depending on driver/version this can be a WKBElement, a WKT string,
    hex-encoded WKB, raw bytes, or an EWKT string with an SRID prefix.
    """
    import shapely
    from geoalchemy2.elements import WKBElement, WKTElement
    from geoalchemy2.shape import to_shape as ga_to_shape

    def _finish(shape: Any) -> str:
        return shapely.to_geojson(shape)

    if isinstance(geometry, (WKBElement, WKTElement)):
        return _finish(ga_to_shape(geometry))
    if isinstance(geometry, (bytes, memoryview, bytearray)):
        return _finish(shapely.from_wkb(bytes(geometry)))
    if isinstance(geometry, str):
        text = geometry.strip()
        if text.upper().startswith("SRID="):
            text = text.split(";", 1)[1]
        if text.upper().startswith(("POLYGON", "MULTIPOLYGON")):
            return _finish(shapely.from_wkt(text))
        return _finish(shapely.from_wkb(bytes.fromhex(text)))
    # shapely geometry objects (defensive)
    if hasattr(geometry, "geom_type"):
        return _finish(geometry)
    raise TypeError(f"unsupported geometry result type: {type(geometry)!r}")


app = create_app()
