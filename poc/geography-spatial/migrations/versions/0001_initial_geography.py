"""initial geography schema

Revision ID: 0001_initial_geography
Revises:
Create Date: 2026-11-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_initial_geography"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostGIS extension must exist before geometry typmods are used.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "countries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("iso2", sa.String(2), nullable=False, unique=True),
        sa.Column("iso3", sa.String(3), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("official_name", sa.String(300)),
        sa.Column("capital", sa.String(200)),
        sa.Column("region", sa.String(100)),
        sa.Column(
            "status",
            sa.Enum("active", "placeholder", name="country_status", native_enum=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "country_configurations",
        sa.Column("country_id", UUID(as_uuid=True), sa.ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("languages", JSONB),
        sa.Column("currency", sa.String(20)),
        sa.Column("timezone", sa.String(100)),
        sa.Column("terminology", JSONB),
        sa.Column("configuration", JSONB),
    )

    op.create_table(
        "data_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("type", sa.String(100)),
        sa.Column("publisher", sa.String(200)),
        sa.Column("url", sa.String(500)),
        sa.Column("licence", sa.String(200)),
        sa.Column("attribution", sa.Text()),
        sa.Column("reference_date", sa.Date()),
        sa.Column("metadata", JSONB),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "administrative_levels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("country_id", UUID(as_uuid=True), sa.ForeignKey("countries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level_number", sa.Integer(), nullable=False),
        sa.Column("level_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.UniqueConstraint("country_id", "level_number", name="uq_admin_level_country_number"),
        sa.CheckConstraint("level_number >= 1", name="ck_admin_level_number_positive"),
    )

    op.create_table(
        "administrative_units",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("country_id", UUID(as_uuid=True), sa.ForeignKey("countries.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "administrative_level_id",
            UUID(as_uuid=True),
            sa.ForeignKey("administrative_levels.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("parent_unit_id", UUID(as_uuid=True), sa.ForeignKey("administrative_units.id", ondelete="RESTRICT")),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("official_code", sa.String(100), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="SET NULL")),
        sa.Column("source_unit_id", sa.String(200)),
        sa.Column("reference_date", sa.Date()),
        sa.Column(
            "verification_status",
            sa.Enum("unverified", "verified", "flagged", name="verification_status", native_enum=True),
            nullable=False,
        ),
        sa.Column("properties", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_id", "official_code", name="uq_unit_country_code"),
        sa.UniqueConstraint("country_id", "source_id", "source_unit_id", name="uq_unit_country_source_sourceid"),
    )

    op.create_table(
        "boundary_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("unit_id", UUID(as_uuid=True), sa.ForeignKey("administrative_units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("geometry", Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("unit_id", "version", name="uq_boundary_version_unit_version"),
        sa.CheckConstraint("version >= 1", name="ck_boundary_version_positive"),
    )

    op.create_table(
        "import_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("country_id", UUID(as_uuid=True), sa.ForeignKey("countries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="SET NULL")),
        sa.Column(
            "format", sa.Enum("geojson", "gpkg", name="import_format", native_enum=True), nullable=False
        ),
        sa.Column("filename", sa.String(300)),
        sa.Column(
            "status",
            sa.Enum(
                "completed", "completed_with_quarantine", "failed", name="import_status", native_enum=True
            ),
            nullable=False,
        ),
        sa.Column("report", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "quarantined_features",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_index", sa.Integer(), nullable=False),
        sa.Column("reason_codes", JSONB, nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("raw_properties", JSONB),
        sa.Column("raw_geometry_wkt", sa.Text()),
    )

    # Indexes
    op.create_index("ix_units_geometry", "administrative_units", ["geometry"], postgresql_using="gist")
    op.create_index("ix_units_country_level", "administrative_units", ["country_id", "administrative_level_id"])
    op.create_index("ix_units_parent", "administrative_units", ["parent_unit_id"])
    op.create_index("ix_boundary_versions_geometry", "boundary_versions", ["geometry"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_table("quarantined_features")
    op.drop_table("import_batches")
    op.drop_table("boundary_versions")
    op.drop_table("administrative_units")
    op.drop_table("administrative_levels")
    op.drop_table("data_sources")
    op.drop_table("country_configurations")
    op.drop_table("countries")
    op.execute("DROP TYPE IF EXISTS import_status, import_format, verification_status, country_status")
