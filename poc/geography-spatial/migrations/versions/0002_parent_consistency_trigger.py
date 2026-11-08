"""parent consistency trigger

Revision ID: 0002_parent_trigger
Revises: 0001_initial_geography
Create Date: 2026-11-08

Enforces, at the database level, that an administrative unit's parent:
  * exists,
  * belongs to the same country, and
  * sits exactly one administrative level above it,
and that root units (no parent) are level 1.
"""
from __future__ import annotations

from alembic import op

revision = "0002_parent_trigger"
down_revision = "0001_initial_geography"
branch_labels = None
depends_on = None

TRIGGER_FN = """
CREATE OR REPLACE FUNCTION trg_enforce_unit_parent_consistency() RETURNS trigger AS $$
DECLARE
    parent_level INT;
    parent_country UUID;
    child_level INT;
BEGIN
    -- The child row does not exist yet on INSERT, so read its level from the
    -- new row itself and the level table, not from administrative_units.
    SELECT al.level_number
      INTO child_level
      FROM administrative_levels al
     WHERE al.id = NEW.administrative_level_id;

    IF child_level IS NULL THEN
        RAISE EXCEPTION 'administrative_level % does not exist', NEW.administrative_level_id;
    END IF;

    IF NEW.parent_unit_id IS NULL THEN
        IF child_level <> 1 THEN
            RAISE EXCEPTION 'unit % (level %) must have a parent', NEW.id, child_level;
        END IF;
        RETURN NEW;
    END IF;

    SELECT al.level_number, au.country_id
      INTO parent_level, parent_country
      FROM administrative_units au
      JOIN administrative_levels al ON al.id = au.administrative_level_id
     WHERE au.id = NEW.parent_unit_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'parent unit % does not exist', NEW.parent_unit_id;
    END IF;

    IF parent_country IS DISTINCT FROM NEW.country_id THEN
        RAISE EXCEPTION 'parent unit % belongs to a different country', NEW.parent_unit_id;
    END IF;

    IF parent_level IS DISTINCT FROM child_level - 1 THEN
        RAISE EXCEPTION 'parent of unit % must be level %, found level %',
                        NEW.id, child_level - 1, parent_level;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
DROP TRIGGER IF EXISTS unit_parent_consistency ON administrative_units;
CREATE TRIGGER unit_parent_consistency
BEFORE INSERT OR UPDATE OF parent_unit_id, administrative_level_id ON administrative_units
FOR EACH ROW EXECUTE FUNCTION trg_enforce_unit_parent_consistency();
"""


def upgrade() -> None:
    op.execute(TRIGGER_FN)
    op.execute(TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS unit_parent_consistency ON administrative_units")
    op.execute("DROP FUNCTION IF EXISTS trg_enforce_unit_parent_consistency()")
