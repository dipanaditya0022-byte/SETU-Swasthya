"""create append-only audit_log with hash chain and app_user grant split

Revision ID: 8c4e29a7d1f0
Revises: f2e7c81a5b93
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS9.4 / SS12 / SS17 (migration 0007 in the doc's numbering):
the audit_log table, its 5 indexes, the app_user role/grant split, and
the two DO INSTEAD NOTHING rules that make UPDATE/DELETE on audit_log
a no-op. Table schema, indexes, and the four-line privilege split are
all copied verbatim from Day1.md SS12.2 and SS9.4.

Three things worth being explicit about, since none of them are things
Day1.md spells out mechanically and each was a real implementation
decision made here, not a spec quote:

1. WHO app_user ACTUALLY IS RIGHT NOW. This repo's docker-compose.yml
   and .env.example provision exactly one Postgres role (whatever
   POSTGRES_USER resolves to -- e.g. changeme_user / setu_dev), and
   DATABASE_URL connects the whole application through it. There is no
   existing two-tier admin-vs-runtime role split anywhere in this repo
   before this migration. Creating the `app_user` role here establishes
   the DB-level object and its restricted grants (so the security
   control described in Day1.md SS9.3 "Audit immunity: None" and threat
   T8 exists at the database level), but it does NOT switch the running
   application to connect as app_user -- DATABASE_URL is untouched by
   this migration. That cutover (pointing the app's own connection at
   app_user instead of the migration-owner role) is a separate,
   later deployment/config change, out of scope here.

2. PASSWORD SOURCE. Day1.md's own SQL uses a psql client-side variable,
   `CREATE ROLE app_user LOGIN PASSWORD :'app_password'` -- that syntax
   only exists in the psql client, not in SQL itself, and can't be sent
   as-is through a DBAPI connection. Per C2 (never commit secrets), this
   migration never hardcodes a password: it reads APP_USER_PASSWORD from
   the environment at migration-run time. `CREATE ROLE ... PASSWORD`
   does not accept a standard bind-parameter placeholder there (Postgres's
   grammar wants a literal token, not `$1` -- confirmed by testing: a
   plain bound-parameter attempt fails with a syntax error). Instead the
   password is escaped server-side via Postgres's own `quote_literal()`
   (itself called through a normal parameterised SELECT, so the raw value
   still never touches string formatting on the Python side), and only
   the resulting pre-quoted literal is spliced into the CREATE ROLE
   statement -- the standard safe pattern for this exact class of DDL
   problem. The migration raises a clear RuntimeError and refuses to
   proceed if the role doesn't already exist and APP_USER_PASSWORD isn't
   set -- it does not silently skip role creation or fall back to a
   default password. APP_USER_PASSWORD is added to backend/.env.example
   as a placeholder, matching S2's convention for secret-shaped env vars.

3. DOWNGRADE SCOPE. downgrade() drops the two rules, re-grants
   UPDATE/DELETE on audit_log to app_user (undoing the REVOKE), and
   drops audit_log's indexes and the table itself -- but it does NOT
   DROP ROLE app_user or revoke its blanket ALL-TABLES grant. A
   Postgres role is a cluster-level object Day1.md gives no teardown
   procedure for, and other objects/migrations could plausibly already
   depend on it existing by the time anyone runs this downgrade;
   automatically stripping a live role's privileges as a side effect of
   reverting one table's migration is exactly the kind of surprising,
   hard-to-reverse action this project's own constraints (fail closed,
   don't destroy work silently) argue against. If app_user itself ever
   needs to be torn down, that should be its own explicit, reviewed
   step.

Not enforced here, by design: Day1.md SS12.4 ("Never in the audit
log": passwords, hashes, MFA secrets, full mobile numbers, clinical
values/notes) is an application-layer discipline, not a column-level
CHECK constraint -- there is no generic way for a database CHECK to
detect "this JSONB blob contains a clinical note", and Day1.md doesn't
specify one. Whoever writes audit_log rows (a later step) is
responsible for that boundary.

The Python-side hash chain function (Day1.md SS12.3's compute_row_hash,
verbatim) lives in backend/app/core/audit.py, not in this migration --
it's application code that runs at INSERT time in whatever later step
actually writes audit rows, not schema DDL.
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8c4e29a7d1f0'
down_revision: Union[str, Sequence[str], None] = 'f2e7c81a5b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. audit_log -- verbatim, Day1.md SS12.2. No FK on actor_user_id
    #    (or any other column) deliberately -- SS13.1: "no FK to allow
    #    retention" (a referenced user/target row can be deleted or
    #    anonymised later without cascading into, or being blocked by,
    #    the audit trail).
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("actor_ip", postgresql.INET(), nullable=True),
        sa.Column("actor_user_agent", sa.Text(), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_org_unit", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("row_hash", sa.Text(), nullable=False),
    )
    op.create_index("idx_audit_actor", "audit_log", ["actor_user_id", sa.text("occurred_at DESC")])
    op.create_index("idx_audit_target", "audit_log", ["target_type", "target_id", sa.text("occurred_at DESC")])
    op.create_index("idx_audit_action", "audit_log", ["action", sa.text("occurred_at DESC")])
    op.create_index("idx_audit_time", "audit_log", [sa.text("occurred_at DESC")])
    op.create_index("idx_audit_meta", "audit_log", ["metadata"], postgresql_using="gin")

    # 2. app_user role -- verbatim grants from Day1.md SS9.4, created
    #    idempotently. Password never hardcoded (see module docstring
    #    point 2): read from APP_USER_PASSWORD at migration-run time and
    #    passed as a bound parameter, never string-formatted into SQL.
    role_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")
    ).scalar()
    if not role_exists:
        password = os.environ.get("APP_USER_PASSWORD")
        if not password:
            raise RuntimeError(
                "APP_USER_PASSWORD environment variable must be set to run "
                "this migration (it creates the app_user role -- see "
                "backend/.env.example). Refusing to create app_user with no "
                "password or a hardcoded default."
            )
        # CREATE ROLE ... PASSWORD does not accept a bind-parameter
        # placeholder (Postgres's grammar wants a literal there). Ask
        # Postgres to safely escape the value server-side via
        # quote_literal() -- itself invoked through a normal
        # parameterised query, so the raw password never passes through
        # Python-side string formatting -- then splice only the
        # resulting pre-quoted literal into the DDL.
        quoted_password = conn.execute(
            sa.text("SELECT quote_literal(:pwd)"),
            {"pwd": password},
        ).scalar()
        conn.execute(sa.text(f"CREATE ROLE app_user LOGIN PASSWORD {quoted_password}"))

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;")

    # 3. audit_log-specific restriction -- verbatim, Day1.md SS9.4.
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM app_user;")
    op.execute("GRANT INSERT, SELECT ON audit_log TO app_user;")

    # 4. DO INSTEAD NOTHING rules -- verbatim, Day1.md SS9.4. These apply
    #    to ANY role writing to audit_log (rules rewrite the query at the
    #    table level, not per-role) -- the REVOKE above is defence in
    #    depth specifically for app_user, the rules are the universal
    #    backstop referenced by SS12.3's "Combined with the INSERT-only
    #    grant... an attacker cannot quietly rewrite the record."
    #    DROP RULE IF EXISTS first for idempotent re-apply.
    op.execute("DROP RULE IF EXISTS audit_log_no_update ON audit_log;")
    op.execute("CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;")
    op.execute("DROP RULE IF EXISTS audit_log_no_delete ON audit_log;")
    op.execute("CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;")


def downgrade() -> None:
    op.execute("DROP RULE IF EXISTS audit_log_no_delete ON audit_log;")
    op.execute("DROP RULE IF EXISTS audit_log_no_update ON audit_log;")

    # Undo the audit_log-specific REVOKE, but leave the app_user role and
    # its blanket ALL-TABLES grant in place (see module docstring point 3).
    op.execute("GRANT UPDATE, DELETE ON audit_log TO app_user;")

    op.drop_index("idx_audit_meta", table_name="audit_log")
    op.drop_index("idx_audit_time", table_name="audit_log")
    op.drop_index("idx_audit_action", table_name="audit_log")
    op.drop_index("idx_audit_target", table_name="audit_log")
    op.drop_index("idx_audit_actor", table_name="audit_log")

    op.drop_table("audit_log")
