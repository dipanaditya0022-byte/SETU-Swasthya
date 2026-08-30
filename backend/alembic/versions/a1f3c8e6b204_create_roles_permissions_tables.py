"""create roles, permissions, role_permissions, role_creation_grants tables

Revision ID: a1f3c8e6b204
Revises: 0e21a4d7c6f5
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS3 / SS8 / SS13.3 / SS17 (migration 0003 in the doc's numbering):
roles, permissions, role_permissions, role_creation_grants.

Day1.md gives a full CREATE TABLE for role_creation_grants (SS13.3) but,
despite naming `roles`, `permissions` and `role_permissions` as part of
this same migration in SS17's migration-plan table and in the SS13.1 ERD
(`roles ──< role_permissions >── permissions`), it never states a CREATE
TABLE, column list or type for any of those three tables anywhere in the
document (verified by grepping every `CREATE TABLE` in Day1.md -- the
only ones present are org_units, audit_log, users, role_creation_grants,
user_invitations, refresh_tokens, approval_requests,
break_glass_sessions, password_history, login_attempts, consents).

This was flagged to the user as a genuine gap rather than guessed. The
orchestrating session proposed a schema and the user picked it via an
explicit multiple-choice confirmation ("Yes, use this design
(recommended)": minimal permissions, no group/description columns) in
the implementation session, 2026-08-30. Resulting schema:

  roles:
    code TEXT PRIMARY KEY, display_name, level SMALLINT, self_register
    BOOLEAN, is_clinical BOOLEAN, created_at. TEXT and TIMESTAMPTZ NOT
    NULL DEFAULT now() are used for display_name/created_at because
    every other table in Day1.md (org_units, role_creation_grants,
    users, ...) uses exactly those types for the equivalent columns.

  permissions:
    kept minimal, per the confirmed choice: code TEXT PRIMARY KEY (the
    "resource:action" string itself, e.g. "user:create"), created_at
    TIMESTAMPTZ NOT NULL DEFAULT now(). SS8.2's descriptive "Group" /
    "Meaning" columns are deliberately NOT included, by the user's
    choice. Adding them later is an additive migration that touches
    nothing depending on permissions.code.

  role_permissions:
    role_code TEXT REFERENCES roles(code), permission_code TEXT
    REFERENCES permissions(code), created_at, PRIMARY KEY (role_code,
    permission_code) -- confirmed, mirroring role_creation_grants's
    (creator_role, target_role) composite-PK pattern.

  role_creation_grants: verbatim from Day1.md SS13.3.

Two indexes (idx_role_permissions_permission, idx_role_creation_grants_
target) are added on the second half of each composite PK. Day1.md does
not mandate them; they follow the same FK-reverse-lookup-index
convention used elsewhere in the schema (e.g. idx_org_units_parent,
idx_users_reports_to) so a permission-code or target-role lookup is not
a sequential scan.

No rows are seeded here -- Day1.md SS17 assigns the full ~19/~60/~450/
~55-row seed to migration 0009 as a separate data migration, per SS17.2's
rule that a failed seed must not roll back a schema change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1f3c8e6b204'
down_revision: Union[str, Sequence[str], None] = '0e21a4d7c6f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. roles -- Day1.md SS1 role taxonomy as data. Confirmed schema.
    op.create_table(
        "roles",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column(
            "self_register", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_clinical", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 2. permissions -- SS8.2 catalogue as data. Minimal confirmed schema
    #    (see module docstring).
    op.create_table(
        "permissions",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 3. role_permissions -- join table, confirmed schema.
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_code", sa.Text(),
            sa.ForeignKey("roles.code"), nullable=False,
        ),
        sa.Column(
            "permission_code", sa.Text(),
            sa.ForeignKey("permissions.code"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "role_code", "permission_code", name="pk_role_permissions"
        ),
    )
    op.create_index(
        "idx_role_permissions_permission", "role_permissions", ["permission_code"],
    )

    # 4. role_creation_grants -- verbatim from Day1.md SS13.3.
    op.create_table(
        "role_creation_grants",
        sa.Column(
            "creator_role", sa.Text(),
            sa.ForeignKey("roles.code"), nullable=False,
        ),
        sa.Column(
            "target_role", sa.Text(),
            sa.ForeignKey("roles.code"), nullable=False,
        ),
        sa.Column(
            "requires_second_approver", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "allowed_org_unit_types", postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "creator_role", "target_role", name="pk_role_creation_grants"
        ),
    )
    op.create_index(
        "idx_role_creation_grants_target", "role_creation_grants", ["target_role"],
    )


def downgrade() -> None:
    op.drop_index("idx_role_creation_grants_target", table_name="role_creation_grants")
    op.drop_table("role_creation_grants")

    op.drop_index("idx_role_permissions_permission", table_name="role_permissions")
    op.drop_table("role_permissions")

    op.drop_table("permissions")
    op.drop_table("roles")
