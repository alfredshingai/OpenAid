"""import formats csv/xlsx

Revision ID: b1000004_formats
Revises: 39a3bb46bebe
Create Date: 2026-11-08
"""
from __future__ import annotations

from alembic import op

revision = "b1000004_formats"
down_revision = "39a3bb46bebe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction.
    op.execute("ALTER TYPE import_format ADD VALUE IF NOT EXISTS 'csv'")
    op.execute("ALTER TYPE import_format ADD VALUE IF NOT EXISTS 'xlsx'")


def downgrade() -> None:
    # Enum value removal is not supported; leave them in place.
    pass
