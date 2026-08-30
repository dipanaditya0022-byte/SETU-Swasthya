"""create users table (RBAC core identity table)

Revision ID: c3a9f7d21e56
Revises: a1f3c8e6b204
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS13.2 (migration 0004 in the doc's numbering): user_status enum,
the `users` table (identity, encrypted contact + blind indexes, credentials,
posting/hierarchy, role-specific profile JSONB, verification, lifecycle),
its 7 integrity CHECK constraints, and its 8 indexes.

Everything in this migration -- every column, type, default, CHECK
constraint and index -- is copied verbatim from the single `CREATE TABLE
users (...)` block in Day1.md SS13.2, plus the `CREATE TYPE user_status`
and the 8 `CREATE INDEX` statements immediately below it in the same
section. Nothing here was inferred or guessed: unlike org_units'
path-maintenance algorithm (0e21a4d7c6f5) or the roles/permissions schema
(a1f3c8e6b204), Day1.md gives a complete, unambiguous DDL for this table,
so there is no gap to flag or resolve for this migration.

Two things worth being explicit about because they are easy to miss on a
skim, not because either one is a gap:

  - This table is named `users` (plural). It is NOT the same table as the
    pre-existing `user` (singular) table created for the Day 1 API surface
    by app/models/user.py / migration 6cfb19a7f898 (id, name, email, phone,
    password_hash) -- that table backs the nine live, contract-frozen
    endpoints (POST /login, GET /me, etc., per C1) and this migration does
    not touch it, reference it, or rename anything. `users` (this table) is
    the new RBAC-core identity table Day 1's role/grant system is built on.
    The two tables' names do not collide in Postgres and neither FKs to the
    other. This is flagged here, not silently assumed, because the two
    names are one character apart.

  - `chk_no_self_report CHECK (reports_to_user_id <> id)` is copied
    verbatim from Day1.md. Under standard SQL NULL semantics, this
    correctly does NOT reject `reports_to_user_id IS NULL` (`NULL <> id`
    evaluates to NULL, not FALSE, and a CHECK only fails on an explicit
    FALSE) -- so a user with no manager set is unaffected, and only an
    explicit self-reference is rejected. This is standard Postgres CHECK
    behaviour, not a deviation from the doc's constraint text.

No SQLModel/ORM class is added for this table in this migration, matching
the precedent set by org_units and roles/permissions/role_creation_grants
(0e21a4d7c6f5, a1f3c8e6b204): those tables were also created as raw
Alembic DDL with no corresponding app/models/*.py class yet. Introducing
app-layer models/routes is out of scope for a single "add the table"
migration (see this task's own instruction to do one concern per change).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3a9f7d21e56'
down_revision: Union[str, Sequence[str], None] = 'a1f3c8e6b204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_STATUS_VALUES = (
    "PENDING_APPROVAL", "INVITED", "ACTIVE", "SUSPENDED",
    "TRANSFERRED", "EXPIRED", "DEACTIVATED",
)


def upgrade() -> None:
    # 1. user_status enum -- 7 values, matching app/models/enums.py
    #    UserStatus exactly. Idempotent create (guards re-apply on a system
    #    where another migration created it first, without silently masking
    #    a real duplicate-type error from an unrelated cause) -- same
    #    pattern as org_unit_type in 0e21a4d7c6f5.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE user_status AS ENUM (
                'PENDING_APPROVAL','INVITED','ACTIVE','SUSPENDED',
                'TRANSFERRED','EXPIRED','DEACTIVATED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """
    )
    user_status_col = postgresql.ENUM(
        *USER_STATUS_VALUES, name="user_status", create_type=False
    )

    # 2. users -- exactly per Day1.md SS13.2.
    op.create_table(
        "users",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),

        # -- identity --
        sa.Column("role", sa.Text(), sa.ForeignKey("roles.code"), nullable=False),
        sa.Column("role_level", sa.SmallInteger(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("full_name_local", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column(
            "preferred_language", sa.Text(), nullable=False,
            server_default=sa.text("'en'"),
        ),

        # -- contact (encrypted + blind index) --
        sa.Column("mobile_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("mobile_blind_index", sa.Text(), nullable=False),
        sa.Column("mobile_masked", sa.Text(), nullable=False),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("email_blind_index", sa.Text(), nullable=True),

        # -- credentials --
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "mfa_required", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "mfa_enrolled", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "hardware_mfa_required", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),

        # -- posting and hierarchy --
        sa.Column(
            "scope_org_unit_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_units.id"), nullable=True,
        ),
        sa.Column("scope_path", sa.Text(), nullable=True),
        sa.Column(
            "scope_extras", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "reports_to_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
        sa.Column(
            "approved_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),

        # -- role-specific profile, validated by a Pydantic discriminated union --
        sa.Column(
            "profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),

        # -- verification --
        sa.Column("hpr_id", sa.Text(), nullable=True),
        sa.Column("hpr_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abha_number_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("employee_code", sa.Text(), nullable=True),
        sa.Column("id_proof_type", sa.Text(), nullable=True),
        sa.Column("id_proof_last4", sa.Text(), nullable=True),

        # -- lifecycle --
        sa.Column(
            "status", user_status_col, nullable=False,
            server_default=sa.text("'INVITED'"),
        ),
        sa.Column(
            "token_version", sa.Integer(), nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("joining_date", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failed_login_count", sa.SmallInteger(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),

        # -- integrity constraints: the rules, enforced by the database --

        # Rule 2: only PATIENT (and the bootstrapped SUPERUSER) may exist
        # without a creator. This is the database enforcement of Rule 2 --
        # see Day1.md SS13.2's own note: "Even if every layer of
        # application logic were bypassed, PostgreSQL itself refuses to
        # store a staff account with no creator."
        sa.CheckConstraint(
            "role = 'PATIENT' OR role = 'SUPERUSER' OR created_by_user_id IS NOT NULL",
            name="chk_creator_required",
        ),
        # an active staff account must have a posting
        sa.CheckConstraint(
            "role IN ('PATIENT','SUPERUSER') OR scope_org_unit_id IS NOT NULL",
            name="chk_scope_required",
        ),
        # a suspended account must say why
        sa.CheckConstraint(
            "status <> 'SUSPENDED' OR suspension_reason IS NOT NULL",
            name="chk_suspension_reason",
        ),
        # deactivation destroys credentials
        sa.CheckConstraint(
            "status <> 'DEACTIVATED' OR password_hash IS NULL",
            name="chk_deactivated_no_creds",
        ),
        # privileged roles must carry the MFA requirement
        sa.CheckConstraint(
            "role_level > 5 OR mfa_required = TRUE",
            name="chk_privileged_mfa",
        ),
        # superusers expire
        sa.CheckConstraint(
            "role <> 'SUPERUSER' OR expires_at IS NOT NULL",
            name="chk_superuser_expires",
        ),
        # a user cannot report to themselves
        sa.CheckConstraint(
            "reports_to_user_id <> id",
            name="chk_no_self_report",
        ),
    )

    # -- indexes, exactly per Day1.md SS13.2 --
    op.create_index(
        "idx_users_mobile_bi", "users", ["mobile_blind_index"],
        unique=True, postgresql_where=sa.text("status <> 'DEACTIVATED'"),
    )
    op.create_index(
        "idx_users_email_bi", "users", ["email_blind_index"],
        unique=True,
        postgresql_where=sa.text(
            "email_blind_index IS NOT NULL AND status <> 'DEACTIVATED'"
        ),
    )
    op.create_index(
        "idx_users_hpr", "users", ["hpr_id"],
        unique=True, postgresql_where=sa.text("hpr_id IS NOT NULL"),
    )
    op.create_index(
        "idx_users_emp_code", "users", ["employee_code"],
        unique=True, postgresql_where=sa.text("employee_code IS NOT NULL"),
    )
    op.create_index("idx_users_role_status", "users", ["role", "status"])
    op.create_index(
        "idx_users_scope_path", "users", ["scope_path"],
        postgresql_ops={"scope_path": "text_pattern_ops"},
    )
    op.create_index("idx_users_reports_to", "users", ["reports_to_user_id"])
    op.create_index(
        "idx_users_profile", "users", ["profile"], postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_users_profile", table_name="users")
    op.drop_index("idx_users_reports_to", table_name="users")
    op.drop_index("idx_users_scope_path", table_name="users")
    op.drop_index("idx_users_role_status", table_name="users")
    op.drop_index("idx_users_emp_code", table_name="users")
    op.drop_index("idx_users_hpr", table_name="users")
    op.drop_index("idx_users_email_bi", table_name="users")
    op.drop_index("idx_users_mobile_bi", table_name="users")

    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS user_status;")
