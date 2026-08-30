"""create governance tables (approval_requests, break_glass_sessions, consents)

Revision ID: f2e7c81a5b93
Revises: d6b1a94f2c3e
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS7 / SS9 / SS12 / SS13.4 / SS17 (migration 0006 in the doc's
numbering): approval_requests, break_glass_sessions, consents.

All three tables are copied verbatim from the CREATE TABLE blocks in
Day1.md SS13.4, including their CHECK constraints and (for consents)
its one CREATE INDEX. No gap to flag or resolve for this migration --
unlike S4/S5/S7, Day1.md gives complete, unambiguous DDL for all three
tables here. SS7/SS9/SS12 were cross-checked for any additional
required fields beyond the SS13.4 DDL (dual-approval rule, break-glass
justification length and DPO notification, consent's four independent
booleans and consent_mode) -- nothing found there changes the schema;
those sections describe the *behaviour* the schema below already
supports.

Notes on two things worth being explicit about, since they're easy to
misread:

  - approval_requests.chk_different_approver enforces the two-person
    rule at the database level (SS3: "A single compromised DHO session
    cannot mint a second DHO"): a request's approver, once set, must
    differ from its requester. It does NOT force every request to have
    an approver -- approved_by is nullable (a request can sit PENDING).

  - consents' "append-only" property (SS13.4's prose: "A change writes
    a new row and stamps superseded_at on the old one") is an
    application-layer convention Day1.md documents here, NOT a
    database-enforced immutability rule for this table -- there is no
    trigger/RULE/REVOKE UPDATE in Day1.md's consents DDL, unlike the
    INSERT-only enforcement SS12/SS17 explicitly assign to audit_log's
    own migration (0007, a later step). This migration implements
    consents exactly as specified: the schema supports the append-only
    pattern (insert a new row, UPDATE only superseded_at on the old
    one), but does not itself forbid an application from updating other
    columns -- that boundary is enforced by the API layer (a later
    step), matching what Day1.md actually specifies for this table.

  - All four consent booleans (keep_record, share_specialist,
    share_facility, anonymised_planning) are NOT NULL with no default
    and no CHECK requiring TRUE -- every combination including all-
    false is valid, per SS5's "Critical rule: All four consents may be
    false... must never block account creation."
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f2e7c81a5b93'
down_revision: Union[str, Sequence[str], None] = 'd6b1a94f2c3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. approval_requests -- verbatim, Day1.md SS13.4.
    op.create_table(
        "approval_requests",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subject_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "requested_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column("required_approver_role", sa.Text(), nullable=False),
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
        sa.Column(
            "status", sa.Text(), nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # the two-person rule, enforced by the database
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by <> requested_by",
            name="chk_different_approver",
        ),
    )

    # 2. break_glass_sessions -- verbatim, Day1.md SS13.4.
    op.create_table(
        "break_glass_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dpo_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "records_accessed", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.CheckConstraint(
            "char_length(justification) >= 50",
            name="chk_justification_length",
        ),
    )

    # 3. consents -- verbatim, Day1.md SS13.4. PATIENT only (enforced at the
    #    application layer via patient_user_id -> users.role = 'PATIENT';
    #    Day1.md does not specify a database CHECK tying this table to
    #    users.role, so none is added here).
    op.create_table(
        "consents",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "patient_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("keep_record", sa.Boolean(), nullable=False),
        sa.Column("share_specialist", sa.Boolean(), nullable=False),
        sa.Column("share_facility", sa.Boolean(), nullable=False),
        sa.Column("anonymised_planning", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "recorded_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
        sa.Column("witness_name", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("audio_version", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode <> 'SPOKEN_WITNESSED' OR witness_name IS NOT NULL",
            name="chk_witness_for_spoken",
        ),
    )
    op.create_index(
        "idx_consents_patient", "consents",
        ["patient_user_id", sa.text("recorded_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_consents_patient", table_name="consents")
    op.drop_table("consents")

    op.drop_table("break_glass_sessions")

    op.drop_table("approval_requests")
