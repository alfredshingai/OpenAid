"""Ingestion orchestration: parse -> validate -> parent resolution -> persist.

Two formats are supported in the PoC (blueprint §16 requires GeoJSON plus a
second format "if feasible"): **GeoJSON** (RFC 7946, parsed with stdlib json)
and **GeoPackage** (read with pyogrio/GDAL).

Design decisions (recorded in SYSTEM_ARCHITECTURE §7):
* EPSG:4326 only. Inputs declaring any other CRS are quarantined with an
  actionable error — no silent reprojection in the PoC.
* Invalid/ambiguous features are quarantined (stored with reasons); valid
  features in the same batch are still imported. The report shows both.
* Upsert mode adds a *new boundary version* for an existing official code;
  it never overwrites history (``boundary_versions`` is append-only).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import shapely
from geoalchemy2 import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import SRID
from .models import (
    AdministrativeLevel,
    AdministrativeUnit,
    BoundaryVersion,
    DataSource,
    ImportBatch,
    ImportFormat,
    ImportStatus,
    QuarantinedFeature,
    VerificationStatus,
)
from . import validation as V

CATCH_ALL = "invalid_file"


@dataclass
class ImportMeta:
    country_id: uuid.UUID
    country_iso3: str
    configured_levels: dict[int, str]
    source: DataSource | None
    reference_date: date | None
    upsert: bool = False
    filename: str | None = None
    format: ImportFormat = ImportFormat.geojson


@dataclass
class ImportReport:
    format: str
    filename: str | None
    received: int = 0
    imported: int = 0
    upserted: int = 0
    quarantined: int = 0
    warnings: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "filename": self.filename,
            "received": self.received,
            "imported": self.imported,
            "upserted": self.upserted,
            "quarantined": self.quarantined,
            "warnings": self.warnings,
            "issues": self.issues,
        }

    @property
    def status(self) -> ImportStatus:
        if self.imported == 0 and self.quarantined == 0 and self.issues:
            return ImportStatus.failed
        if self.quarantined:
            return ImportStatus.completed_with_quarantine
        return ImportStatus.completed


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_geojson_bytes(data: bytes) -> tuple[list[tuple[int, dict[str, Any], Any]], dict[str, Any]]:
    """Parse a GeoJSON FeatureCollection into ((index, properties, geometry)..., doc)."""
    try:
        doc = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ValueError("GeoJSON root must be an object")
    if doc.get("type") != "FeatureCollection":
        raise ValueError(f"expected a FeatureCollection, got type={doc.get('type')!r}")
    features = doc.get("features")
    if not isinstance(features, list):
        raise ValueError("FeatureCollection must contain a features array")

    parsed: list[tuple[int, dict[str, Any], Any]] = []
    for i, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"feature {i} is not an object")
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if properties is None:
            properties = {}
        if not isinstance(properties, dict):
            raise ValueError(f"feature {i} properties must be an object")
        parsed.append((i, properties, geometry))
    return parsed, doc


def _parse_gpkg(path: Path, layer: str | None) -> tuple[int, list[tuple[int, dict[str, Any], Any]]]:
    """Parse a GeoPackage layer into (epsg, [(index, properties, geometry)])."""
    import numpy as np
    import pandas as pd
    import pyogrio

    gdf = pyogrio.read_dataframe(str(path), layer=layer) if layer else pyogrio.read_dataframe(str(path))
    epsg = None
    if gdf.crs is not None:
        epsg = int(gdf.crs.to_epsg() or 0)

    parsed: list[tuple[int, dict[str, Any], Any]] = []
    for i, row in enumerate(gdf.itertuples(index=False)):
        geom = getattr(row, "geometry")
        props: dict[str, Any] = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            value = getattr(row, col)
            if value is None or (isinstance(value, float) and np.isnan(value)):
                value = None
            elif isinstance(value, np.integer):
                value = int(value)
            elif isinstance(value, np.floating):
                value = float(value)
            elif isinstance(value, pd.Timestamp):
                value = value.isoformat()
            props[str(col)] = value
        parsed.append((i, props, geom))
    return (epsg if epsg else 4326), parsed


# ---------------------------------------------------------------------------
# Database lookups
# ---------------------------------------------------------------------------


def _load_configured_levels(session: Session, country_id: uuid.UUID) -> dict[int, str]:
    rows = session.execute(
        select(AdministrativeLevel.level_number, AdministrativeLevel.level_name).where(
            AdministrativeLevel.country_id == country_id
        )
    ).all()
    return {number: name for number, name in rows}


def _load_existing_codes(session: Session, country_id: uuid.UUID) -> set[str]:
    return set(
        session.execute(
            select(AdministrativeUnit.official_code).where(AdministrativeUnit.country_id == country_id)
        ).scalars()
    )


def _load_db_parents(session: Session, country_id: uuid.UUID) -> dict[str, tuple[int, Any]]:
    rows = session.execute(
        select(AdministrativeUnit.official_code, AdministrativeLevel.level_number, AdministrativeUnit.id)
        .join(AdministrativeLevel, AdministrativeLevel.id == AdministrativeUnit.administrative_level_id)
        .where(AdministrativeUnit.country_id == country_id)
    ).all()
    return {code: (level, unit_id) for code, level, unit_id in rows}


def _level_ids(session: Session, country_id: uuid.UUID) -> dict[int, uuid.UUID]:
    rows = session.execute(
        select(AdministrativeLevel.level_number, AdministrativeLevel.id).where(
            AdministrativeLevel.country_id == country_id
        )
    ).all()
    return {number: ident for number, ident in rows}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _strip_managed_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Original properties are preserved verbatim for provenance."""
    return dict(props)


def _insert_unit(
    session: Session,
    meta: ImportMeta,
    level_ids: dict[int, uuid.UUID],
    feature: V.ParsedFeature,
    parent_db_id: uuid.UUID | None,
) -> AdministrativeUnit:
    unit = AdministrativeUnit(
        country_id=meta.country_id,
        administrative_level_id=level_ids[feature.admin_level],
        parent_unit_id=parent_db_id,
        name=feature.name,
        official_code=feature.official_code,
        geometry=WKTElement(feature.geometry.wkt, srid=SRID),
        source_id=meta.source.id if meta.source else None,
        source_unit_id=feature.source_unit_id or feature.official_code,
        reference_date=meta.reference_date,
        verification_status=VerificationStatus.unverified,
        properties=_strip_managed_properties(feature.properties),
    )
    session.add(unit)
    session.flush()  # assign unit.id before creating the boundary version

    session.add(
        BoundaryVersion(
            unit_id=unit.id,
            version=1,
            geometry=WKTElement(feature.geometry.wkt, srid=SRID),
            valid_from=meta.reference_date,
            valid_to=None,
            source_id=meta.source.id if meta.source else None,
        )
    )
    return unit


def _upsert_unit(
    session: Session,
    meta: ImportMeta,
    feature: V.ParsedFeature,
    existing: AdministrativeUnit,
) -> None:
    """Add a new boundary version for an existing unit; never lose history."""
    current_version = session.execute(
        select(func.max(BoundaryVersion.version)).where(BoundaryVersion.unit_id == existing.id)
    ).scalar_one()
    next_version = int(current_version or 0) + 1

    # Close out the currently-open version row (valid_to null => current).
    session.execute(
        update(BoundaryVersion)
        .where(BoundaryVersion.unit_id == existing.id, BoundaryVersion.valid_to.is_(None))
        .values(valid_to=meta.reference_date)
    )
    session.add(
        BoundaryVersion(
            unit_id=existing.id,
            version=next_version,
            geometry=WKTElement(feature.geometry.wkt, srid=SRID),
            valid_from=meta.reference_date,
            valid_to=None,
            source_id=meta.source.id if meta.source else None,
        )
    )
    existing.geometry = WKTElement(feature.geometry.wkt, srid=SRID)
    existing.properties = _strip_managed_properties(feature.properties)
    existing.reference_date = meta.reference_date
    existing.source_id = meta.source.id if meta.source else existing.source_id


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def _fail_batch(session: Session, meta: ImportMeta, report: ImportReport) -> ImportBatch:
    batch = ImportBatch(
        country_id=meta.country_id,
        source_id=meta.source.id if meta.source else None,
        format=meta.format,
        filename=meta.filename,
        status=ImportStatus.failed,
        report=report.to_dict(),
    )
    session.add(batch)
    session.flush()
    return batch


def ingest_parsed_features(
    session: Session,
    meta: ImportMeta,
    parsed: list[tuple[int, dict[str, Any], Any]],
) -> tuple[ImportBatch, ImportReport]:
    """Validate and persist a batch of parsed features for one country."""
    report = ImportReport(format=meta.format.value, filename=meta.filename)
    report.received = len(parsed)

    existing_codes = _load_existing_codes(session, meta.country_id)
    db_parents = _load_db_parents(session, meta.country_id)

    result = V.validate_features(
        parsed,
        meta.configured_levels,
        meta.country_iso3,
        existing_codes,
        allow_existing=meta.upsert,
    )
    report.warnings.extend(result.warnings)

    parent_issues = V.resolve_parents(result.features, db_parents)
    blocked_codes: set[str] = set()
    for issue in parent_issues:
        report.issues.append(issue.to_dict())
        blocked = next(f for f in result.features if f.feature_index == issue.feature_index)
        blocked_codes.add(blocked.official_code)

    for issue in result.issues:
        report.issues.append(issue.to_dict())
    report.quarantined = len({i["feature_index"] for i in report.issues})

    # Import in level order so parents exist before children reference them.
    level_ids = _level_ids(session, meta.country_id)
    code_to_unit_id: dict[str, uuid.UUID] = {code: ident for code, (_lvl, ident) in db_parents.items()}

    for feature in sorted(result.features, key=lambda f: (f.admin_level, f.feature_index)):
        if feature.official_code in blocked_codes:
            continue

        parent_db_id: uuid.UUID | None = None
        if feature.parent_code is not None:
            if feature.parent_code in code_to_unit_id:
                parent_db_id = code_to_unit_id[feature.parent_code]
            else:
                report.issues.append(
                    {
                        "feature_index": feature.feature_index,
                        "reason_codes": [V.R_MISSING_PARENT],
                        "detail": f"parent {feature.parent_code!r} was quarantined in this batch, "
                        f"so {feature.official_code!r} cannot be imported",
                    }
                )
                continue

        if feature.official_code in db_parents and meta.upsert:
            existing = session.execute(
                select(AdministrativeUnit).where(
                    AdministrativeUnit.country_id == meta.country_id,
                    AdministrativeUnit.official_code == feature.official_code,
                )
            ).scalar_one()
            _upsert_unit(session, meta, feature, existing)
            report.upserted += 1
            report.imported += 1
        else:
            unit = _insert_unit(session, meta, level_ids, feature, parent_db_id)
            code_to_unit_id[feature.official_code] = unit.id
            report.imported += 1

    report.quarantined = len({i["feature_index"] for i in report.issues})

    batch = ImportBatch(
        country_id=meta.country_id,
        source_id=meta.source.id if meta.source else None,
        format=meta.format,
        filename=meta.filename,
        status=report.status,
        report=report.to_dict(),
    )
    session.add(batch)
    session.flush()

    # Persist quarantine rows for every rejected feature index.
    index_to_issue = {issue.feature_index: issue for issue in result.issues}
    for index in {i["feature_index"] for i in report.issues}:
        issue = index_to_issue.get(index)
        session.add(
            QuarantinedFeature(
                batch_id=batch.id,
                feature_index=index,
                reason_codes=issue.reason_codes if issue else [V.R_MISSING_PARENT],
                detail=issue.detail if issue else "parent was quarantined in this batch",
                raw_properties=issue.raw_properties if issue else None,
                raw_geometry_wkt=issue.raw_geometry_wkt if issue else None,
            )
        )
    return batch, report


def ingest_geojson_bytes(
    session: Session,
    meta: ImportMeta,
    data: bytes,
) -> tuple[ImportBatch, ImportReport]:
    report = ImportReport(format="geojson", filename=meta.filename)

    # File-level checks that abort the whole batch -------------------------
    try:
        parsed, doc = _parse_geojson_bytes(data)
    except ValueError as exc:
        report.issues.append({"feature_index": -1, "reason_codes": [CATCH_ALL], "detail": str(exc)})
        return _fail_batch(session, meta, report), report

    crs_member = doc.get("crs")
    if crs_member:
        text_repr = json.dumps(crs_member)
        if "4326" not in text_repr and "CRS84" not in text_repr and "OGC:1.3" not in text_repr:
            report.received = len(parsed)
            report.issues.append(
                {
                    "feature_index": -1,
                    "reason_codes": [V.R_UNSUPPORTED_CRS],
                    "detail": "GeoJSON declares a non-WGS84 CRS; reproject to EPSG:4326 "
                    "(RFC 7946 GeoJSON is always WGS84). Nothing was imported.",
                }
            )
            return _fail_batch(session, meta, report), report

    return ingest_parsed_features(session, meta, parsed)


def ingest_gpkg_file(
    session: Session,
    meta: ImportMeta,
    path: Path,
    layer: str | None = None,
) -> tuple[ImportBatch, ImportReport]:
    try:
        epsg, parsed = _parse_gpkg(path, layer)
    except Exception as exc:
        report = ImportReport(format="gpkg", filename=meta.filename)
        report.issues.append(
            {
                "feature_index": -1,
                "reason_codes": [CATCH_ALL],
                "detail": f"could not read GeoPackage: {exc}",
            }
        )
        return _fail_batch(session, meta, report), report

    report = ImportReport(format="gpkg", filename=meta.filename)
    report.received = len(parsed)

    if epsg != SRID:
        report.issues.append(
            {
                "feature_index": -1,
                "reason_codes": [V.R_UNSUPPORTED_CRS],
                "detail": f"GeoPackage layer declares EPSG:{epsg}; the PoC ingests EPSG:4326 only. "
                "Reproject the layer and retry. Nothing was imported.",
            }
        )
        return _fail_batch(session, meta, report), report

    return ingest_parsed_features(session, meta, parsed)
