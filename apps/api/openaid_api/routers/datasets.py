"""Open data catalogue router — metadata, licences, access classes, downloads."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from openaid_core.db import get_db
from openaid_core.datasets.models import AccessClass, Dataset

router = APIRouter(prefix="/api/v1", tags=["datasets"])


@router.get("/datasets")
def list_datasets(
    access_class: str | None = None,
    is_synthetic: bool | None = None,
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Catalogue entries. Access classification (who may access) is reported
    separately from the reuse licence."""
    stmt = select(Dataset).order_by(Dataset.title)
    if access_class:
        try:
            ac = AccessClass(access_class)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid access_class") from None
        stmt = stmt.where(Dataset.access_class == ac)
    if is_synthetic is not None:
        stmt = stmt.where(Dataset.is_synthetic == is_synthetic)
    return [_dataset_out(d) for d in session.execute(stmt).scalars().all()]


def _dataset_out(d: Dataset) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "slug": d.slug,
        "title": d.title,
        "description": d.description,
        "publisher": d.publisher,
        "licence": d.licence,
        "attribution": d.attribution,
        "access_class": d.access_class.value if hasattr(d.access_class, "value") else str(d.access_class),
        "language": d.language,
        "spatial_coverage": d.spatial_coverage,
        "temporal_coverage": d.temporal_coverage,
        "homepage_url": d.homepage_url,
        "is_synthetic": d.is_synthetic,
        "files": [
            {"filename": f.filename, "format": f.format, "layer": f.layer,
             "size_bytes": f.size_bytes, "sha256": f.sha256, "download_url": f.download_url}
            for f in d.files
        ],
        "versions": [
            {"version_number": v.version_number, "changelog": v.changelog,
             "published_at": v.published_at.isoformat() if v.published_at else None,
             "source_version": v.source_version}
            for v in d.versions
        ],
    }


@router.get("/datasets/{slug}")
def get_dataset(slug: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    d = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail=f"dataset {slug} not found")
    return _dataset_out(d)
