"""country boundary outlines (admin-0)

Revision ID: b1000005_boundary
Revises: b1000004_formats
Create Date: 2026-11-09

Country-level outline geometry for continental map rendering. Derived from
the same COD-AB sources as admin units; display simplification happens at
query time and never alters the stored geometry.
"""
from __future__ import annotations

from alembic import op
import geoalchemy2
import sqlalchemy as sa

revision = "b1000005_boundary"
down_revision = "b1000004_formats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "countries",
        sa.Column(
            "boundary",
            geoalchemy2.Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("countries", "boundary")
