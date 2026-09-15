"""referral state machine (status enum, workflow columns, referral_transitions)

Revision ID: d4f1c9b7a582
Revises: a4d72f9e1c83
Create Date: 2026-08-31 00:00:00.000000

WHY: the referral workflow (SLA due dates, breach detection/escalation,
slot/transport/arrival capture, terminal-state reasons, and an auditable
transition log) cannot be represented by the bare `status TEXT` column
Aditya's Day 1 schema shipped with. This migration turns `referral.status`
into a real 13-state Postgres enum and adds the columns the state machine
(app/models/referral_state.py, already merged in this worktree) needs to
persist against, plus a `referral_transitions` history table. No route is
touched by this migration -- app/api/routes/referrals.py is wired to the
new columns in a later step, per this task's "one concern per change" rule.

TABLE NAME: verified, not assumed. app/models/referral.py's `Referral`
class has no explicit `__tablename__`, and migration 79a9d8f8db61's own
`op.create_table('referral', ...)` (the migration that actually created
it) confirms the live table is named `referral`, singular -- matching the
precedent already established for this exact question by migration
9d5f6b3e0a71's `TABLES = ("patient", "referral", "triageencounter")` and
a4d72f9e1c83's docstring for the sibling `triageencounter` table. The
plural `referrals` used casually in some prose does not exist as a table
in this database.

HEAD: verified by tracing every migration's `down_revision` in
alembic/versions/ -- no file points at a4d72f9e1c83, so it is the current
chain tip. This migration chains directly off it.

FK TARGET: `owner_user_id` and `arrival_confirmed_by` reference `users`
(plural) -- the RBAC-core identity table from c3a9f7d21e56 -- using the
exact same `op.add_column` (nullable) + separate `op.create_foreign_key`
pattern 9d5f6b3e0a71 already established for adding FK columns to this
same `referral` table. This is deliberately NOT the legacy singular
`user` table that backs the frozen Day 1 auth endpoints (C1) -- the two
do not collide in Postgres and neither is touched by the other.

*** A GENUINE CONFLICT FOUND AND RESOLVED, NOT SILENTLY WORKED AROUND ***
The task instruction that produced this migration listed `urgency TEXT`
as one of the "new, all nullable" Phase 2 columns to add. That is wrong
for THIS repository: `referral.urgency` already exists, as `TEXT NOT
NULL`, created by the very first migration for this table
(79a9d8f8db61's `sa.Column('urgency', ..., nullable=False)`) and it is
already populated on every row today -- `POST /referrals/` takes the
whole `Referral` SQLModel as its request body (app/api/routes/
referrals.py), so `urgency` is already a required, client-supplied,
NOT-NULL field on every existing and future row, not a new one this
migration needs to introduce.
  - Running `op.add_column("referral", sa.Column("urgency", ...))` here
    would fail immediately with `DuplicateColumn` on any database that
    has ever run 79a9d8f8db61 -- i.e. every database in this project.
  - Resolution: this migration does NOT re-add `urgency`, does NOT
    backfill it, and does NOT re-assert NOT NULL on it (Postgres allows
    `ALTER COLUMN ... SET NOT NULL` as a harmless no-op on an
    already-NOT-NULL column, but there is nothing to assert here -- the
    constraint already exists from Day 1, doing it again would just be
    noise). Every OTHER column in the Phase 2 list below was checked
    against 79a9d8f8db61's and 9d5f6b3e0a71's `CREATE TABLE`/`ADD
    COLUMN` statements and does not already exist on `referral`.
  - Flagging this here rather than silently dropping `urgency` from the
    list without comment, per this project's "if the repo and the spec
    disagree, stop and report the difference" rule.

DATA STATE (verified live, not assumed): the coordinator ran, against
the real dev DB in this worktree:
    SELECT status, count(*) FROM referral GROUP BY 1 ORDER BY 2 DESC;   -- 0 rows
    SELECT count(*) FROM referral;                                      -- count = 0
The table is empty. Phase 3's status-value mapping below is therefore
written to be correct for a *populated* table in general (this same
migration file may run against a different environment that has data),
not special-cased to skip because today's dev DB happens to have none.

PHASE 3 STATUS MAPPING MECHANISM: an explicit `CASE status WHEN <known
value> THEN <same known value> ... ELSE status END` UPDATE. Every one of
the 13 canonical ReferralState values (app/models/referral_state.py) maps
to itself (identity -- Aditya's route already wrote these exact
upper-case strings; there is no observed or assumed alternate spelling to
remap). Anything NOT in that list falls through the `ELSE status` branch
completely unchanged -- it is deliberately NOT coerced, defaulted, or
dropped. That means an unrecognized value survives Phase 3 as free text,
and then Phase 5's `ALTER COLUMN status TYPE referral_status USING
status::referral_status` will fail loudly with Postgres's own
`invalid input value for enum referral_status: "<value>"` error and abort
the whole migration transaction -- which is the correct, honest behavior
per this task's own instruction ("that's correct behavior, don't work
around it silently"). No status value has been invented or guessed here;
none existed to map.

PHASE 2 TIMESTAMPTZ BACKFILL NOTE: `referral.created_at` is
`DateTime()` (timezone-naive) per 79a9d8f8db61, and the model
(`default_factory=datetime.utcnow`) always writes naive UTC. The new
`initiated_at` column is `TIMESTAMPTZ`. Backfilling naive-UTC into
timestamptz uses an explicit `AT TIME ZONE 'UTC'` cast (not a bare
`::timestamptz` cast, which would instead assume the DB session's
`TimeZone` setting) so the backfilled instant is correct regardless of
what timezone the migration happens to run under.

Downgrade reverses every step: drops the two new indexes, drops
`referral_transitions`, converts `status` back to `TEXT`, drops the two
FKs and every column this migration added (never touching `urgency`,
which this migration never added), then drops the `referral_status`
enum type.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4f1c9b7a582'
down_revision: Union[str, Sequence[str], None] = 'a4d72f9e1c83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REFERRAL_STATUS_VALUES = (
    "INITIATED", "SLOT_BOOKED", "TRANSPORT_ARRANGED", "ARRIVED",
    "CONSULTED", "BACK_REFERRED", "CLOSED", "CANCELLED", "NOT_ARRIVED",
    "TRACED", "RESCHEDULED", "REFUSED", "LOST",
)


def upgrade() -> None:
    # ---- PHASE 1: the enum type -------------------------------------
    # Idempotent create, same guarded pattern as user_status (c3a9f7d21e56)
    # and org_unit_type (0e21a4d7c6f5) -- so a re-run after a partial
    # failure on another branch doesn't mask a real duplicate-type error
    # from an unrelated cause.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE referral_status AS ENUM (
                'INITIATED','SLOT_BOOKED','TRANSPORT_ARRANGED','ARRIVED',
                'CONSULTED','BACK_REFERRED','CLOSED','CANCELLED',
                'NOT_ARRIVED','TRACED','RESCHEDULED','REFUSED','LOST'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """
    )

    # ---- PHASE 2: new columns, all nullable --------------------------
    # `urgency` is deliberately NOT in this list -- see module docstring
    # "A GENUINE CONFLICT FOUND AND RESOLVED": it already exists as
    # TEXT NOT NULL from 79a9d8f8db61 and is populated on every row.
    op.add_column("referral", sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("breached_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("breach_detected_by", sa.Text(), nullable=True))
    op.add_column("referral", sa.Column("escalation_stage", sa.SmallInteger(), nullable=True))
    op.add_column("referral", sa.Column("escalation_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("referral", sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("back_referred_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("slot_datetime", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("transport_mode", sa.Text(), nullable=True))
    op.add_column("referral", sa.Column("arrival_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("referral", sa.Column("arrival_scan_ref", sa.Text(), nullable=True))
    op.add_column("referral", sa.Column("refusal_reason", sa.Text(), nullable=True))
    op.add_column("referral", sa.Column("loss_reason", sa.Text(), nullable=True))
    op.add_column("referral", sa.Column("cancellation_reason", sa.Text(), nullable=True))
    op.add_column("referral", sa.Column("back_referral_note", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_referral_owner_user_id", "referral", "users",
        ["owner_user_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_referral_arrival_confirmed_by", "referral", "users",
        ["arrival_confirmed_by"], ["id"],
    )

    # ---- PHASE 3: backfill existing rows -----------------------------
    # `urgency` is untouched -- already NOT NULL, already populated,
    # not added by this migration (see docstring).
    op.execute(
        """
        UPDATE referral
        SET initiated_at = (created_at AT TIME ZONE 'UTC')
        WHERE initiated_at IS NULL;
        """
    )
    op.execute(
        """
        UPDATE referral
        SET due_at = initiated_at + interval '7 days'
        WHERE due_at IS NULL AND initiated_at IS NOT NULL;
        """
    )
    op.execute(
        """
        UPDATE referral
        SET escalation_stage = 0
        WHERE escalation_stage IS NULL;
        """
    )
    # Explicit status mapping. Every known value maps to itself; anything
    # unrecognized is left untouched on purpose so Phase 5's enum CAST
    # fails loudly on it instead of this UPDATE silently swallowing or
    # inventing a mapping for it. See module docstring "PHASE 3 STATUS
    # MAPPING MECHANISM".
    op.execute(
        """
        UPDATE referral
        SET status = CASE status
            WHEN 'INITIATED' THEN 'INITIATED'
            WHEN 'SLOT_BOOKED' THEN 'SLOT_BOOKED'
            WHEN 'TRANSPORT_ARRANGED' THEN 'TRANSPORT_ARRANGED'
            WHEN 'ARRIVED' THEN 'ARRIVED'
            WHEN 'CONSULTED' THEN 'CONSULTED'
            WHEN 'BACK_REFERRED' THEN 'BACK_REFERRED'
            WHEN 'CLOSED' THEN 'CLOSED'
            WHEN 'CANCELLED' THEN 'CANCELLED'
            WHEN 'NOT_ARRIVED' THEN 'NOT_ARRIVED'
            WHEN 'TRACED' THEN 'TRACED'
            WHEN 'RESCHEDULED' THEN 'RESCHEDULED'
            WHEN 'REFUSED' THEN 'REFUSED'
            WHEN 'LOST' THEN 'LOST'
            ELSE status
        END;
        """
    )

    # ---- PHASE 4: enforce NOT NULL on the backfilled columns ---------
    # `urgency` intentionally excluded -- see docstring.
    op.alter_column("referral", "initiated_at", nullable=False)
    op.alter_column("referral", "escalation_stage", nullable=False)

    # ---- PHASE 5: convert status to the enum, LAST -------------------
    # If any row's status value wasn't one of the 13 canonical strings
    # (and therefore wasn't touched by the CASE above), this cast fails
    # loudly here and aborts the migration -- by design, not a bug.
    op.execute(
        "ALTER TABLE referral ALTER COLUMN status TYPE referral_status "
        "USING status::referral_status;"
    )

    # ---- referral_transitions: append-only transition history -------
    op.create_table(
        "referral_transitions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "referral_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("referral.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "idx_referral_transitions_ref", "referral_transitions",
        ["referral_id", "occurred_at"],
    )
    op.create_index(
        "idx_referrals_breach", "referral", ["status", "due_at"],
        postgresql_where=sa.text("breached_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_referrals_breach", table_name="referral")
    op.drop_index("idx_referral_transitions_ref", table_name="referral_transitions")
    op.drop_table("referral_transitions")

    op.execute("ALTER TABLE referral ALTER COLUMN status TYPE TEXT USING status::text;")

    op.drop_constraint("fk_referral_arrival_confirmed_by", "referral", type_="foreignkey")
    op.drop_constraint("fk_referral_owner_user_id", "referral", type_="foreignkey")

    op.drop_column("referral", "back_referral_note")
    op.drop_column("referral", "cancellation_reason")
    op.drop_column("referral", "loss_reason")
    op.drop_column("referral", "refusal_reason")
    op.drop_column("referral", "arrival_scan_ref")
    op.drop_column("referral", "arrival_confirmed_by")
    op.drop_column("referral", "transport_mode")
    op.drop_column("referral", "slot_datetime")
    op.drop_column("referral", "closed_at")
    op.drop_column("referral", "back_referred_at")
    op.drop_column("referral", "arrived_at")
    op.drop_column("referral", "owner_user_id")
    op.drop_column("referral", "escalation_notified_at")
    op.drop_column("referral", "escalation_stage")
    op.drop_column("referral", "breach_detected_by")
    op.drop_column("referral", "breached_at")
    op.drop_column("referral", "due_at")
    op.drop_column("referral", "initiated_at")

    op.execute("DROP TYPE IF EXISTS referral_status;")
