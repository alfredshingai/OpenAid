"""Facility & service models (blueprint §7 facility/service model).

A facility may provide several services and may have multiple managing or
supporting organisations. Operational status is never implied: unknown is a
first-class state, and validity dates are kept where evidence supports them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from ..datasets.models import DataSource
    from ..geography.models import AdministrativeUnit


class OperationalStatus(str, enum.Enum):
    unknown = "unknown"
    reported_operational = "reported_operational"
    reported_closed = "reported_closed"
    unverified = "unverified"


class FacilityOrgRole(str, enum.Enum):
    managing = "managing"
    supporting = "supporting"


class FacilityType(Base):
    __tablename__ = "facility_types"
    __table_args__ = (UniqueConstraint("code", name="uq_facility_types_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Facility(Base):
    __tablename__ = "facilities"
    __table_args__ = (
        Index("ix_facilities_geometry", "geometry", postgresql_using="gist"),
        Index("ix_facilities_country", "country_id", "facility_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    facility_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facility_types.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    operational_status: Mapped[OperationalStatus] = mapped_column(
        SAEnum(OperationalStatus, name="operational_status", native_enum=True),
        nullable=False,
        default=OperationalStatus.unknown,
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    geometry: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("administrative_units.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    source_facility_id: Mapped[str | None] = mapped_column(String(200))
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

    facility_type: Mapped[FacilityType] = relationship()
    source: Mapped["DataSource | None"] = relationship()
    unit: Mapped["AdministrativeUnit | None"] = relationship()
    services: Mapped[list["FacilityService"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan"
    )
    organisation_links: Mapped[list["FacilityOrganisation"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan"
    )


class FacilityService(Base):
    __tablename__ = "facility_services"
    __table_args__ = (
        UniqueConstraint("facility_id", "service", name="uq_facility_service"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    service: Mapped[str] = mapped_column(String(150), nullable=False)

    facility: Mapped[Facility] = relationship(back_populates="services")


class FacilityOrganisation(Base):
    __tablename__ = "facility_organisations"
    __table_args__ = (
        UniqueConstraint("facility_id", "organisation_id", "role", name="uq_facility_org_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[FacilityOrgRole] = mapped_column(
        SAEnum(FacilityOrgRole, name="facility_org_role", native_enum=True), nullable=False
    )

    facility: Mapped[Facility] = relationship(back_populates="organisation_links")
