"""link existing Day 1 tables to the identity/org model (created_by_user_id, org_unit_id)

Revision ID: 9d5f6b3e0a71
Revises: 8c4e29a7d1f0
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS17 / SS17.1 (migration 0008 in the doc's numbering, called
`0008_link_day1_tables` there): adds `created_by_user_id` and
`org_unit_id` to the existing Day 1 tables, using the three-phase
nullable -> backfill -> NOT NULL pattern SS17.1 requires so this never
fails on a non-empty table.

Three things had to be resolved beyond what Day1.md's SS17.1 example
literally shows, all confirmed with the user directly in this session
(2026-08-30) rather than guessed:

1. TABLE NAMES. Day1.md's SS17.1 example (and this task's own
   instructions) name the target tables `patients`, `triage`,
   `referrals`. The tables that actually exist in this repository --
   created by migration 79a9d8f8db61, from Aditya's original SQLModel
   classes -- are named `patient`, `referral`, `triageencounter`
   (singular; confirmed by reading that migration file and by directly
   querying the live database's pg_tables). There is no ambiguity here:
   the plural names simply don't exist as tables. This migration
   targets the real ones. `facility` also exists but is out of scope --
   neither Day1.md's SS17 migration-plan row nor this step's own
   instructions list it.

2. THE ORDERING PROBLEM WITH `roles`. SS17.1's example inserts a system
   attribution user with `role = 'SUPERUSER'`. `users.role` has `NOT
   NULL REFERENCES roles(code)` (migration c3a9f7d21e56). `roles` is
   genuinely empty at this point in the migration chain -- seeding it
   is migration 0009 (`0009_seed_reference_data`), which Day1.md's own
   SS17 table sequences AFTER this one. The example as literally
   written cannot run against a fresh database following Day1.md's own
   migration order. Confirmed by direct testing: `SELECT count(*) FROM
   roles` returned 0 before this migration.

3. THE SAME PROBLEM FOR `org_units`. SS17.1's example backfills
   `org_unit_id` from `(SELECT id FROM org_units WHERE path =
   '/UP/KANPUR' LIMIT 1)`. No migration in the whole Day 1 plan seeds
   real geographic org_units rows (0009 seeds roles/permissions/grants
   only, per SS17's own table) -- so that SELECT would always return
   NULL, which would then fail the NOT NULL constraint this same
   migration is supposed to add.

RESOLUTION (confirmed with the user): bootstrap exactly one minimal row
each into `roles` and `org_units`, just enough to satisfy the FKs,
using the same "obviously historical, never real" pattern Day1.md
SS17.1 already established for the system user (deterministic UUID,
name that says what it is, INSERT ... ON CONFLICT DO NOTHING so
migration 0009's real seed can run afterward without colliding):

  - roles: one 'SUPERUSER' row (the minimum needed for the system
    user's own role FK to resolve -- not a full role catalogue).
  - org_units: one root-level 'STATE' row named "System (pre-RBAC
    migration)", deterministic id, created via a plain INSERT (its
    path/depth are computed automatically by 0e21a4d7c6f5's
    trg_org_units_set_own_path trigger, same as any other insert).

This migration adds explicit foreign keys for BOTH created_by_user_id
AND org_unit_id on all three tables (created_by_user_id -> users.id,
org_unit_id -> org_units.id) -- SS17.1's example only shows the
create_foreign_key call for created_by_user_id, but every other
*_org_unit_id column in this schema (e.g. users.scope_org_unit_id) is
FK-constrained, so leaving org_unit_id unconstrained here would be an
inconsistency, not a deliberate spec choice.

downgrade() drops the added FKs and columns, restoring patient/
referral/triageencounter to their pre-migration shape exactly. It does
NOT delete the bootstrap SUPERUSER role row, the bootstrap org_unit
row, or the system attribution user -- these are foundational/shared
reference rows a later migration (0009) or other data may already
depend on existing continuously, the same reasoning already applied to
app_user's role in 8c4e29a7d1f0's downgrade().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9d5f6b3e0a71'
down_revision: Union[str, Sequence[str], None] = '8c4e29a7d1f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'
SYSTEM_ORG_UNIT_ID = '00000000-0000-0000-0000-000000000002'

TABLES = ("patient", "referral", "triageencounter")


def upgrade() -> None:
    # 1. add nullable columns to each existing Day 1 table.
    for table in TABLES:
        op.add_column(table, sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True,
        ))
        op.add_column(table, sa.Column(
            "org_unit_id", postgresql.UUID(as_uuid=True), nullable=True,
        ))

    # 2a. bootstrap the minimal 'SUPERUSER' roles row (see module
    #     docstring point 2) -- not the full seed, just enough for the
    #     system user's own role FK to resolve.
    op.execute("""
        INSERT INTO roles (code, display_name, level, self_register, is_clinical)
        VALUES ('SUPERUSER', 'Superuser', 0, false, false)
        ON CONFLICT (code) DO NOTHING;
    """)

    # 2b. bootstrap one root-level org_unit (see module docstring point
    #     3). path/depth are computed by trg_org_units_set_own_path
    #     (0e21a4d7c6f5) same as any other insert -- not set here.
    op.execute(f"""
        INSERT INTO org_units (id, unit_type, name)
        VALUES ('{SYSTEM_ORG_UNIT_ID}', 'STATE', 'System (pre-RBAC migration)')
        ON CONFLICT (id) DO NOTHING;
    """)

    # 2c. ensure a system attribution user exists -- Day1.md SS17.1's
    #     intent (deterministic id, DEACTIVATED, no credentials,
    #     expires_at set to satisfy chk_superuser_expires), with one
    #     necessary correction: SS17.1's own example omits
    #     mfa_required, which defaults to false (c3a9f7d21e56) and
    #     violates chk_privileged_mfa for a role_level-0 SUPERUSER
    #     (role_level > 5 OR mfa_required = TRUE) -- confirmed by
    #     testing (this exact INSERT, run as literally shown in
    #     Day1.md, fails with CheckViolation on chk_privileged_mfa).
    #     mfa_required=true is added; nothing else changed.
    op.execute(f"""
        INSERT INTO users (id, role, role_level, full_name, mobile_encrypted,
                           mobile_blind_index, mobile_masked, status, expires_at,
                           mfa_required)
        VALUES ('{SYSTEM_USER_ID}', 'SUPERUSER', 0,
                'System (pre-RBAC migration)', '\\x00', 'system-migration',
                '+91XXXXXXXXXX', 'DEACTIVATED', now(), TRUE)
        ON CONFLICT (id) DO NOTHING;
    """)

    # 3. backfill every existing row (may be zero rows today, but this
    #    must be correct for a database that already has Day 1 data).
    for table in TABLES:
        op.execute(f"""
            UPDATE {table}
            SET created_by_user_id = '{SYSTEM_USER_ID}',
                org_unit_id = '{SYSTEM_ORG_UNIT_ID}'
            WHERE created_by_user_id IS NULL;
        """)

    # 4. now enforce NOT NULL and add FKs.
    for table in TABLES:
        op.alter_column(table, "created_by_user_id", nullable=False)
        op.alter_column(table, "org_unit_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_created_by", table, "users",
            ["created_by_user_id"], ["id"],
        )
        op.create_foreign_key(
            f"fk_{table}_org_unit", table, "org_units",
            ["org_unit_id"], ["id"],
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_constraint(f"fk_{table}_org_unit", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_created_by", table, type_="foreignkey")
        op.drop_column(table, "org_unit_id")
        op.drop_column(table, "created_by_user_id")
    # Bootstrap rows (roles.SUPERUSER, the system org_unit, the system
    # user) are deliberately NOT removed -- see module docstring.
