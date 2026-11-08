"""Organisation domain models (blueprint §7 organisation presence model).

Headquarters, registration, country office, operational location and project
implementation site are **separate facts**, each with source evidence, dates
and verification status. Presence is never inferred from registration alone.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..geography.models import VerificationStatus
from ..models_base import Base, new_uuid


class OrganisationType(str, enum.Enum):
    ngo = "ngo"
    ingo = "ingo"
    un_agency = "un_agency"
    government = "government"
    cbo = "cbo"
    private_sector = "private_sector"
    research = "research"
    other = "other"


class OfficeType(str, enum.Enum):
    headquarters = "headquarters"
    registration = "registration"
    country_office = "country_office"
    operational_location = "operational_location"
    project_site = "project_site"


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    acronym: Mapped[str | None] = mapped_column(String(50))
    org_type: Mapped[OrganisationType] = mapped_column(
        SAEnum(OrganisationType, name="organisation_type", native_enum=True), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    mandate: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(500))
    # public contact points only — never personal data
    public_contact: Mapped[dict | None] = mapped_column(JSONB)
    hq_country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="SET NULL")
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status", native_enum=True),
        nullable=False,
        default=VerificationStatus.unverified,
    )
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    locations: Mapped[list["OrganisationLocation"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    sectors: Mapped[list["OrganisationSector"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )


class OrganisationLocation(Base):
    __tablename__ = "organisation_locations"
    __table_args__ = (
        Index("ix_org_locations_geometry", "geometry", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    location_type: Mapped[OfficeType] = mapped_column(
        SAEnum(OfficeType, name="office_type", native_enum=True), nullable=False
    )
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="SET NULL")
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("administrative_units.id", ondelete="SET NULL")
    )
    geometry: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status", native_enum=True),
        nullable=False,
        default=VerificationStatus.unverified,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    organisation: Mapped[Organisation] = relationship(back_populates="locations")


class OrganisationSector(Base):
    __tablename__ = "organisation_sectors"
    __table_args__ = (
        UniqueConstraint("organisation_id", "sector", name="uq_org_sector"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    sector: Mapped[str] = mapped_column(String(100), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(100))  # e.g. humanitarian clusters

    organisation: Mapped[Organisation] = relationship(back_populates="sectors")
