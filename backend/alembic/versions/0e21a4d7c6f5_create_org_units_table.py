"""create org_units table

Revision ID: 0e21a4d7c6f5
Revises: 79a9d8f8db61
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS4.2 / SS17 (migration 0002 in the doc's numbering): org_unit_type
enum, org_units table, path indexes, path-maintenance trigger.

Day1.md specifies the org_units table verbatim (SS4.2) but does not specify
the exact algorithm the "path-maintenance trigger" uses to turn a row's
`name` into a path segment (org_units has no `code`/`slug` column, and the
one illustrative path in the doc, '/UP/KANPUR/RAMPUR/PHC001/SC004/V0012',
does not match the `name` values used in the doc's own worked example,
e.g. "Rampur PHC"). This was flagged to the user as a genuine gap rather
than guessed. Resolved by the user for this migration as follows:

  - path segment = a slug of `name`: lower-cased, every run of characters
    outside [a-z0-9] collapsed to a single '-', leading/trailing '-'
    trimmed (implemented as SQL function org_unit_slugify()).
  - root row (parent_id IS NULL): path = '/' + slug(name), depth = 0.
  - child row: path = rtrim(parent.path, '/') + '/' + slug(name),
    depth = parent.depth + 1.
  - reparenting or renaming a node cascades: every existing descendant's
    `path` is rewritten with the old prefix replaced by the new one, and
    `depth` is shifted by the same delta. Implemented as two triggers:
    one BEFORE INSERT/UPDATE (recomputes the row's own path/depth from its
    current parent), one AFTER UPDATE OF path (rewrites descendants).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0e21a4d7c6f5'
down_revision: Union[str, Sequence[str], None] = '79a9d8f8db61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ORG_UNIT_TYPE_VALUES = (
    "STATE", "DISTRICT", "BLOCK", "PHC", "CHC", "SDH",
    "SUB_CENTRE", "HWC", "VILLAGE", "DISTRICT_HOSPITAL",
    "TELE_HUB", "DISTRICT_OFFICE",
)


def upgrade() -> None:
    # 1. org_unit_type enum -- 12 values, matching app/models/enums.py
    #    OrgUnitType exactly. Idempotent create (guards re-apply on a system
    #    where another migration created it first, without silently masking
    #    a real duplicate-type error from an unrelated cause).
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE org_unit_type AS ENUM (
                'STATE','DISTRICT','BLOCK','PHC','CHC','SDH',
                'SUB_CENTRE','HWC','VILLAGE','DISTRICT_HOSPITAL',
                'TELE_HUB','DISTRICT_OFFICE'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """
    )
    org_unit_type_col = postgresql.ENUM(
        *ORG_UNIT_TYPE_VALUES, name="org_unit_type", create_type=False
    )

    # 2. slugify helper used by the path-maintenance trigger (see module
    #    docstring for the exact rule, confirmed by the user for this step).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION org_unit_slugify(input TEXT)
        RETURNS TEXT AS $$
            SELECT trim(both '-' FROM regexp_replace(lower(trim(input)), '[^a-z0-9]+', '-', 'g'));
        $$ LANGUAGE sql IMMUTABLE;
        """
    )

    # 3. org_units -- exactly per Day1.md SS4.2.
    op.create_table(
        "org_units",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "parent_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_units.id", ondelete="RESTRICT"), nullable=True,
        ),
        sa.Column("unit_type", org_unit_type_col, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_local", sa.Text(), nullable=True),
        sa.Column("lgd_code", sa.Text(), nullable=True),
        sa.Column("hfr_id", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("parent_id", "name", name="uq_org_units_parent_name"),
        sa.CheckConstraint("path LIKE '/%'", name="chk_path_starts_slash"),
    )

    op.create_index(
        "idx_org_units_path", "org_units", ["path"],
        postgresql_ops={"path": "text_pattern_ops"},
    )
    op.create_index("idx_org_units_parent", "org_units", ["parent_id"])
    op.create_index(
        "idx_org_units_lgd", "org_units", ["lgd_code"],
        unique=True, postgresql_where=sa.text("lgd_code IS NOT NULL"),
    )
    op.create_index(
        "idx_org_units_hfr", "org_units", ["hfr_id"],
        unique=True, postgresql_where=sa.text("hfr_id IS NOT NULL"),
    )

    # 4a. BEFORE INSERT/UPDATE OF parent_id, name: recompute this row's own
    #     path + depth from its (possibly new) parent.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION org_units_set_own_path()
        RETURNS TRIGGER AS $$
        DECLARE
            parent_path  TEXT;
            parent_depth SMALLINT;
        BEGIN
            IF NEW.parent_id IS NULL THEN
                parent_path  := '';
                parent_depth := -1;
            ELSE
                SELECT path, depth INTO parent_path, parent_depth
                FROM org_units WHERE id = NEW.parent_id;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'org_units: parent_id % does not exist', NEW.parent_id;
                END IF;
            END IF;

            NEW.path  := rtrim(parent_path, '/') || '/' || org_unit_slugify(NEW.name);
            NEW.depth := parent_depth + 1;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_org_units_set_own_path
        BEFORE INSERT OR UPDATE OF parent_id, name ON org_units
        FOR EACH ROW
        EXECUTE FUNCTION org_units_set_own_path();
        """
    )

    # 4b. AFTER UPDATE OF parent_id, name: cascade the new prefix + depth
    #     shift onto every existing descendant in a single statement.
    #     Fires on OF parent_id, name (not OF path) deliberately: Postgres
    #     only fires an "UPDATE OF col" trigger when the triggering SQL
    #     statement's own SET list names that column. Application code
    #     renames/reparents via `UPDATE org_units SET name = ...` or
    #     `SET parent_id = ...` -- it never sets `path` directly (trigger
    #     4a's BEFORE hook recomputes NEW.path internally). An "OF path"
    #     spec would therefore never fire on a real rename/reparent, even
    #     though NEW.path did change -- verified by direct testing against
    #     a running Postgres instance.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION org_units_cascade_path()
        RETURNS TRIGGER AS $$
        DECLARE
            depth_delta SMALLINT;
        BEGIN
            IF NEW.path IS DISTINCT FROM OLD.path THEN
                depth_delta := NEW.depth - OLD.depth;

                UPDATE org_units
                SET path  = NEW.path || substring(path FROM char_length(OLD.path) + 1),
                    depth = depth + depth_delta
                WHERE path LIKE (rtrim(OLD.path, '/') || '/%');
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_org_units_cascade_path
        AFTER UPDATE OF parent_id, name ON org_units
        FOR EACH ROW
        EXECUTE FUNCTION org_units_cascade_path();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_org_units_cascade_path ON org_units;")
    op.execute("DROP FUNCTION IF EXISTS org_units_cascade_path();")
    op.execute("DROP TRIGGER IF EXISTS trg_org_units_set_own_path ON org_units;")
    op.execute("DROP FUNCTION IF EXISTS org_units_set_own_path();")

    op.drop_index("idx_org_units_hfr", table_name="org_units")
    op.drop_index("idx_org_units_lgd", table_name="org_units")
    op.drop_index("idx_org_units_parent", table_name="org_units")
    op.drop_index("idx_org_units_path", table_name="org_units")

    op.drop_table("org_units")

    op.execute("DROP FUNCTION IF EXISTS org_unit_slugify(TEXT);")
    op.execute("DROP TYPE IF EXISTS org_unit_type;")
