"""Geography domain models (promoted unchanged in schema from the §16 PoC).

Recursive, country-configurable administrative hierarchy with append-only
boundary versioning. See docs/database/DATABASE_SCHEMA.md §2.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Numeric,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..models_base import Base, new_uuid

if TYPE_CHECKING:
    from ..datasets.models import DataSource


class CountryStatus(str, enum.Enum):
    active = "active"
    placeholder = "placeholder"


class VerificationStatus(str, enum.Enum):
    unverified = "unverified"
    verified = "verified"
    flagged = "flagged"


class ImportFormat(str, enum.Enum):
    geojson = "geojson"
    gpkg = "gpkg"
    csv = "csv"
    xlsx = "xlsx"


class ImportStatus(str, enum.Enum):
    completed = "completed"
    completed_with_quarantine = "completed_with_quarantine"
    failed = "failed"


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(300))
    capital: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(100))
    # Approximate representative point for Africa-wide map markers only
    # (never for analysis — boundaries are the authoritative geometry).
    rep_lon: Mapped[float | None] = mapped_column(Numeric(8, 4))
    rep_lat: Mapped[float | None] = mapped_column(Numeric(8, 4))
    status: Mapped[CountryStatus] = mapped_column(
        SAEnum(CountryStatus, name="country_status", native_enum=True),
        nullable=False,
        default=CountryStatus.placeholder,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    configuration: Mapped["CountryConfiguration | None"] = relationship(
        back_populates="country", uselist=False, cascade="all, delete-orphan"
    )
    administrative_levels: Mapped[list["AdministrativeLevel"]] = relationship(
        back_populates="country",
        cascade="all, delete-orphan",
        order_by="AdministrativeLevel.level_number",
    )


class CountryConfiguration(Base):
    __tablename__ = "country_configurations"

    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True
    )
    languages: Mapped[list | None] = mapped_column(JSONB)
    currency: Mapped[str | None] = mapped_column(String(60))
    timezone: Mapped[str | None] = mapped_column(String(100))
    terminology: Mapped[dict | None] = mapped_column(JSONB)
    configuration: Mapped[dict | None] = mapped_column(JSONB)

    country: Mapped[Country] = relationship(back_populates="configuration")


class AdministrativeLevel(Base):
    __tablename__ = "administrative_levels"
    __table_args__ = (
        UniqueConstraint("country_id", "level_number", name="uq_admin_level_country_number"),
        CheckConstraint("level_number >= 1", name="ck_admin_level_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    level_number: Mapped[int] = mapped_column(Integer, nullable=False)
    level_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    country: Mapped[Country] = relationship(back_populates="administrative_levels")
    units: Mapped[list["AdministrativeUnit"]] = relationship(back_populates="administrative_level")


class AdministrativeUnit(Base):
    __tablename__ = "administrative_units"
    __table_args__ = (
        UniqueConstraint("country_id", "official_code", name="uq_unit_country_code"),
        UniqueConstraint("country_id", "source_id", "source_unit_id", name="uq_unit_country_source_sourceid"),
        Index("ix_units_geometry", "geometry", postgresql_using="gist"),
        Index("ix_units_country_level", "country_id", "administrative_level_id"),
        Index("ix_units_parent", "parent_unit_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    administrative_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("administrative_levels.id", ondelete="RESTRICT"), nullable=False
    )
    parent_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("administrative_units.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    official_code: Mapped[str] = mapped_column(String(100), nullable=False)
    geometry: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    source_unit_id: Mapped[str | None] = mapped_column(String(200))
    reference_date: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status", native_enum=True),
        nullable=False,
        default=VerificationStatus.unverified,
    )
    properties: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    administrative_level: Mapped[AdministrativeLevel] = relationship(back_populates="units")
    boundary_versions: Mapped[list["BoundaryVersion"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan", order_by="BoundaryVersion.version"
    )


class BoundaryVersion(Base):
    """Append-only history of a unit's geometry; never updated or deleted."""

    __tablename__ = "boundary_versions"
    __table_args__ = (
        UniqueConstraint("unit_id", "version", name="uq_boundary_version_unit_version"),
        CheckConstraint("version >= 1", name="ck_boundary_version_positive"),
        Index("ix_boundary_versions_geometry", "geometry", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("administrative_units.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    unit: Mapped["AdministrativeUnit"] = relationship(back_populates="boundary_versions")


class ImportBatch(Base):
    """One ingestion run, with its validation report."""

    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    format: Mapped[ImportFormat] = mapped_column(
        SAEnum(ImportFormat, name="import_format", native_enum=True), nullable=False
    )
    filename: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[ImportStatus] = mapped_column(
        SAEnum(ImportStatus, name="import_status", native_enum=True), nullable=False
    )
    report: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped["DataSource | None"] = relationship()
    quarantined: Mapped[list["QuarantinedFeature"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class QuarantinedFeature(Base):
    """A feature rejected during ingestion, with actionable error detail."""

    __tablename__ = "quarantined_features"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    raw_properties: Mapped[dict | None] = mapped_column(JSONB)
    raw_geometry_wkt: Mapped[str | None] = mapped_column(Text)

    batch: Mapped[ImportBatch] = relationship(back_populates="quarantined")
