"""widen country_configurations.currency

Revision ID: 0003_widen_currency
Revises: 0002_parent_trigger
Create Date: 2026-11-08

Real-data onboarding (Eswatini demo) showed VARCHAR(20) is too tight for
currency names like "SZL (Eswatini Lilangeni)". Widen to 60.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_widen_currency"
down_revision = "0002_parent_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "country_configurations",
        "currency",
        existing_type=sa.String(20),
        type_=sa.String(60),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "country_configurations",
        "currency",
        existing_type=sa.String(60),
        type_=sa.String(20),
        existing_nullable=True,
    )
