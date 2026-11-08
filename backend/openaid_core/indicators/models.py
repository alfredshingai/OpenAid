"""Indicator domain models (blueprint §6).

Core rules encoded here:
* Observations are tied to geography + period + source + dataset version +
  methodology + value type + quality status.
* **Missing values are never zero** — ``value`` is NULL and ``missing_type``
  distinguishes unknown / not_collected / not_applicable / suppressed /
  unavailable (CHECK: exactly one of value / missing_type).
* Comparability is an explicit, recorded assessment — never assumed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
    from ..geography.models import AdministrativeUnit


class IndicatorCategory(str, enum.Enum):
    demographic = "demographic"
    health = "health"
    education = "education"
    wash = "wash"
    agriculture = "agriculture"
    economy = "economy"
    climate = "climate"
    infrastructure = "infrastructure"
    humanitarian = "humanitarian"


class MeasurementType(str, enum.Enum):
    count = "count"
    rate = "rate"
    average = "average"
    index = "index"
    monetary = "monetary"


class AggregationMethod(str, enum.Enum):
    sum = "sum"
    weighted_average = "weighted_average"
    simple_average = "simple_average"
    not_aggregatable = "not_aggregatable"


class ValueType(str, enum.Enum):
    observed = "observed"
    estimated = "estimated"
    modelled = "modelled"


class MissingType(str, enum.Enum):
    unknown = "unknown"
    not_collected = "not_collected"
    not_applicable = "not_applicable"
    suppressed = "suppressed"
    unavailable = "unavailable"


class ComparabilityAssessment(str, enum.Enum):
    directly_comparable = "directly_comparable"
    comparable_with_adjustments = "comparable_with_adjustments"
    contextually_comparable = "contextually_comparable"
    not_comparable = "not_comparable"
    not_assessed = "not_assessed"


class IndicatorDefinition(Base):
    __tablename__ = "indicator_definitions"
    __table_args__ = (UniqueConstraint("code", name="uq_indicator_definitions_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[IndicatorCategory] = mapped_column(
        SAEnum(IndicatorCategory, name="indicator_category", native_enum=True), nullable=False
    )
    unit: Mapped[str | None] = mapped_column(String(60))  # persons, %, count, km…
    measurement_type: Mapped[MeasurementType] = mapped_column(
        SAEnum(MeasurementType, name="measurement_type", native_enum=True), nullable=False
    )
    aggregation_method: Mapped[AggregationMethod] = mapped_column(
        SAEnum(AggregationMethod, name="aggregation_method", native_enum=True), nullable=False
    )
    methodology: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndicatorObservation(Base):
    __tablename__ = "indicator_observations"
    __table_args__ = (
        # exactly one of value / missing_type
        CheckConstraint(
            "(value IS NULL) <> (missing_type IS NULL)", name="ck_observation_value_xor_missing"
        ),
        Index("ix_obs_country", "country_id", "indicator_definition_id", "period_start"),
        Index("ix_obs_unit", "unit_id", "indicator_definition_id", "period_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    # NULL unit_id + country_id = country-level observation
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("administrative_units.id", ondelete="CASCADE")
    )
    indicator_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indicator_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date | None] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Numeric(20, 6))
    value_type: Mapped[ValueType] = mapped_column(
        SAEnum(ValueType, name="observation_value_type", native_enum=True), nullable=False
    )
    missing_type: Mapped[MissingType | None] = mapped_column(
        SAEnum(MissingType, name="observation_missing_type", native_enum=True)
    )
    sample_size: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    dataset_version: Mapped[str | None] = mapped_column(String(100))
    methodology_notes: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    definition: Mapped[IndicatorDefinition] = relationship()
    source: Mapped["DataSource | None"] = relationship()
    unit: Mapped["AdministrativeUnit | None"] = relationship()


class ComparabilityAssessmentRecord(Base):
    """An explicit judgement about comparing two indicators (blueprint §6)."""

    __tablename__ = "comparability_assessments"
    __table_args__ = (
        UniqueConstraint(
            "indicator_a_id", "indicator_b_id", name="uq_comparability_pair"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    indicator_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indicator_definitions.id", ondelete="CASCADE"), nullable=False
    )
    indicator_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("indicator_definitions.id", ondelete="CASCADE"), nullable=False
    )
    assessment: Mapped[ComparabilityAssessment] = mapped_column(
        SAEnum(ComparabilityAssessment, name="comparability_assessment", native_enum=True), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    assessed_by: Mapped[str | None] = mapped_column(String(200))
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
