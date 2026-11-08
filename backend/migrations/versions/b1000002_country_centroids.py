"""country map centroids

Revision ID: b1000002_centroids
Revises: 5d334cfdb109
Create Date: 2026-11-08

Approximate representative point per country, used for Africa-wide map
markers only (never for analysis). Sourced from widely published country
centroids, rounded; boundaries remain the authoritative geometry.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b1000002_centroids"
down_revision = "5d334cfdb109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("countries", sa.Column("rep_lon", sa.Numeric(8, 4), nullable=True))
    op.add_column("countries", sa.Column("rep_lat", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("countries", "rep_lat")
    op.drop_column("countries", "rep_lon")
