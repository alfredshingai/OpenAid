"""Dataset catalogue & source-registry models.

Key design rule (blueprint §10): **access classification is stored
separately from the reuse licence.** A dataset can be public to browse but
carry a licence restricting redistribution, and vice versa.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..models_base import Base, new_uuid


class AccessClass(str, enum.Enum):
    public = "public"
    restricted = "restricted"
    confidential = "confidential"
    sensitive = "sensitive"


class DataSource(Base):
    """Registry of upstream sources with licence/provenance metadata.

    Shared by geography (boundary imports), indicators (observations) and
    facilities (facility locations).
    """

    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    type: Mapped[str | None] = mapped_column(String(100))
    publisher: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    licence: Mapped[str | None] = mapped_column(String(300))
    attribution: Mapped[str | None] = mapped_column(Text)
    reference_date: Mapped[date | None] = mapped_column(Date)
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("slug", name="uq_datasets_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(150), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(300))
    licence: Mapped[str | None] = mapped_column(String(300))
    attribution: Mapped[str | None] = mapped_column(Text)
    access_class: Mapped[AccessClass] = mapped_column(
        SAEnum(AccessClass, name="access_class", native_enum=True), nullable=False, default=AccessClass.public
    )
    language: Mapped[str | None] = mapped_column(String(30))
    spatial_coverage: Mapped[dict | None] = mapped_column(JSONB)  # {"countries": [...], "level": "admin2"}
    temporal_coverage: Mapped[dict | None] = mapped_column(JSONB)  # {"start": "...", "end": "..."}
    homepage_url: Mapped[str | None] = mapped_column(String(500))
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    files: Mapped[list["DatasetFile"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetVersion.version_number"
    )


class DatasetFile(Base):
    __tablename__ = "dataset_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    format: Mapped[str] = mapped_column(String(30), nullable=False)  # gpkg, geojson, parquet, csv…
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    download_url: Mapped[str | None] = mapped_column(String(500))
    layer: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="files")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[str] = mapped_column(String(50), nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_version: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
