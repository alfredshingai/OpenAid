"""Tabular (CSV/XLSX) indicator-observation ingestion.

Contract columns (header row, case-insensitive):

    country_iso3, unit_code, indicator_code, period_start, period_end,
    value, missing_type, sample_size

* ``unit_code`` empty → country-level observation.
* Exactly one of ``value`` / ``missing_type`` (missing values are never zero).
* Unknown indicator or unit, bad periods and non-numeric values are
  quarantined with actionable detail; valid rows in the same file still
  import (same behaviour as geographic ingestion).
* Duplicates (same country + unit + indicator + period + source + dataset
  version) are skipped and counted — re-runs are idempotent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..datasets.models import DataSource
from ..geography.models import AdministrativeUnit, Country, ImportBatch, ImportFormat, ImportStatus
from .models import (
    IndicatorDefinition,
    IndicatorObservation,
    MissingType,
    ValueType,
)

REQUIRED_COLUMNS = ("indicator_code", "period_start")
CATCH_ALL = "invalid_file"


@dataclass
class TabularImportMeta:
    country_id: uuid.UUID
    country_iso3: str
    source: DataSource | None
    dataset_version: str | None
    default_value_type: ValueType = ValueType.observed
    filename: str | None = None
    format: ImportFormat = ImportFormat.csv


@dataclass
class TabularImportReport:
    received: int = 0
    imported: int = 0
    skipped_duplicates: int = 0
    quarantined: int = 0
    warnings: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "imported": self.imported,
            "skipped_duplicates": self.skipped_duplicates,
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


def parse_table(data: bytes, filename: str | None) -> list[dict[str, Any]]:
    """Parse CSV or XLSX bytes into normalised row dicts (str keys)."""
    import io

    import pandas as pd

    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        frame = pd.read_excel(io.BytesIO(data), dtype=str)
    elif name.endswith(".tsv"):
        frame = pd.read_csv(io.BytesIO(data), sep="\t", dtype=str)
    else:
        frame = pd.read_csv(io.BytesIO(data), dtype=str)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    rows: list[dict[str, Any]] = []
    for i, (_, row) in enumerate(frame.iterrows()):
        record: dict[str, Any] = {"__index": i}
        for col in frame.columns:
            value = row[col]
            record[col] = None if pd.isna(value) or str(value).strip() == "" else str(value).strip()
        rows.append(record)
    return rows


def _parse_period(value: Any, field: str, issues: list, index: int, raw: dict) -> date | None:
    if value is None:
        if field == "period_start":
            issues.append({"row": index, "reason_codes": ["missing_period"],
                           "detail": "'period_start' is required (YYYY-MM-DD)",
                           "raw": {k: raw.get(k) for k in ("indicator_code", "unit_code", "period_start")}})
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        issues.append({"row": index, "reason_codes": ["invalid_period"],
                       "detail": f"'{field}' must be an ISO date (YYYY-MM-DD), got {value!r}",
                       "raw": {k: raw.get(k) for k in ("indicator_code", "unit_code", "period_start")}})
        return None


def ingest_indicator_rows(
    session: Session,
    meta: TabularImportMeta,
    rows: list[dict[str, Any]],
) -> tuple[ImportBatch, TabularImportReport]:
    report = TabularImportReport()
    report.received = len(rows)

    defs: dict[str, uuid.UUID] = {
        d.code: d.id
        for d in session.execute(select(IndicatorDefinition)).scalars().all()
    }
    units: dict[str, uuid.UUID] = {
        u.official_code: u.id
        for u in session.execute(
            select(AdministrativeUnit).where(AdministrativeUnit.country_id == meta.country_id)
        ).scalars().all()
    }
    existing = {
        (str(u), str(d), p, str(s), str(v))
        for u, d, p, s, v in session.execute(
            select(
                IndicatorObservation.unit_id,
                IndicatorObservation.indicator_definition_id,
                IndicatorObservation.period_start,
                IndicatorObservation.source_id,
                IndicatorObservation.dataset_version,
            )
        ).all()
    }

    issues: list[dict[str, Any]] = []
    batch_rows: list[IndicatorObservation] = []

    for row in rows:
        index = row.get("__index", -1)
        raw_ctx = {k: row.get(k) for k in ("indicator_code", "unit_code", "period_start", "value", "missing_type")}

        indicator_code = (row.get("indicator_code") or "").strip()
        if not indicator_code:
            issues.append({"row": index, "reason_codes": ["missing_indicator"],
                           "detail": "'indicator_code' is required", "raw": raw_ctx})
            continue
        if indicator_code not in defs:
            issues.append({"row": index, "reason_codes": ["unknown_indicator"],
                           "detail": f"indicator '{indicator_code}' is not defined in the catalogue",
                           "raw": raw_ctx})
            continue

        unit_code = row.get("unit_code")
        unit_id = None
        if unit_code:
            unit_id = units.get(unit_code)
            if unit_id is None:
                issues.append({"row": index, "reason_codes": ["unknown_unit"],
                               "detail": f"unit '{unit_code}' does not exist for {meta.country_iso3}",
                               "raw": raw_ctx})
                continue

        period_start = _parse_period(row.get("period_start"), "period_start", issues, index, row)
        if period_start is None:
            continue
        period_end_raw = row.get("period_end")
        period_end = None
        if period_end_raw:
            period_end = _parse_period(period_end_raw, "period_end", issues, index, row)
            if period_end is None:
                continue

        value_raw = row.get("value")
        missing_raw = (row.get("missing_type") or "").strip()
        value: float | None = None
        missing_type: MissingType | None = None
        if value_raw is None and not missing_raw:
            issues.append({"row": index, "reason_codes": ["no_value"],
                           "detail": "either 'value' or 'missing_type' is required",
                           "raw": raw_ctx})
            continue
        if value_raw is not None:
            try:
                value = float(value_raw)
            except ValueError:
                issues.append({"row": index, "reason_codes": ["invalid_value"],
                               "detail": f"'value' must be numeric, got {value_raw!r}",
                               "raw": raw_ctx})
                continue
            if missing_raw:
                issues.append({"row": index, "reason_codes": ["value_and_missing"],
                               "detail": "provide 'value' OR 'missing_type', never both",
                               "raw": raw_ctx})
                continue
        else:
            try:
                missing_type = MissingType(missing_raw)
            except ValueError:
                issues.append({"row": index, "reason_codes": ["invalid_missing_type"],
                               "detail": f"missing_type must be one of {[m.value for m in MissingType]}, "
                               f"got {missing_raw!r}",
                               "raw": raw_ctx})
                continue

        sample_raw = row.get("sample_size")
        sample_size = None
        if sample_raw:
            try:
                sample_size = int(float(sample_raw))
            except ValueError:
                issues.append({"row": index, "reason_codes": ["invalid_sample_size"],
                               "detail": f"'sample_size' must be an integer, got {sample_raw!r}",
                               "raw": raw_ctx})
                continue

        source_id = meta.source.id if meta.source else None
        key = (str(unit_id), str(defs[indicator_code]), period_start, str(source_id), str(meta.dataset_version))
        if key in existing:
            report.skipped_duplicates += 1
            continue
        existing.add(key)

        batch_rows.append(
            IndicatorObservation(
                country_id=meta.country_id,
                unit_id=unit_id,
                indicator_definition_id=defs[indicator_code],
                period_start=period_start,
                period_end=period_end,
                value=value,
                value_type=meta.default_value_type,
                missing_type=missing_type,
                sample_size=sample_size,
                source_id=source_id,
                dataset_version=meta.dataset_version,
            )
        )

    report.imported = len(batch_rows)
    report.quarantined = len(issues)
    report.issues = issues

    session.add_all(batch_rows)
    batch = ImportBatch(
        country_id=meta.country_id,
        source_id=meta.source.id if meta.source else None,
        format=meta.format,
        filename=meta.filename,
        status=report.status,
        report={
            "format": meta.format.value,
            "filename": meta.filename,
            **report.to_dict(),
        },
    )
    session.add(batch)
    session.flush()
    return batch, report


def ingest_indicator_file(
    session: Session,
    meta: TabularImportMeta,
    data: bytes,
) -> tuple[ImportBatch, TabularImportReport]:
    """Parse then ingest; unparseable files become failed batches."""
    report = TabularImportReport()
    try:
        rows = parse_table(data, meta.filename)
    except Exception as exc:
        report.issues.append({"row": -1, "reason_codes": [CATCH_ALL],
                              "detail": f"could not parse tabular file: {exc}"})
        batch = ImportBatch(
            country_id=meta.country_id,
            source_id=meta.source.id if meta.source else None,
            format=meta.format,
            filename=meta.filename,
            status=ImportStatus.failed,
            report={"format": meta.format.value, "filename": meta.filename, **report.to_dict()},
        )
        session.add(batch)
        session.flush()
        return batch, report
    return ingest_indicator_rows(session, meta, rows)
