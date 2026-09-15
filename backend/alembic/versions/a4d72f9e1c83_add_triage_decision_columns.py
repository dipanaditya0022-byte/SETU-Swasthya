"""add triage decision columns (triageencounter)

Revision ID: a4d72f9e1c83
Revises: c5e8f3a061db
Create Date: 2026-08-31 00:00:00.000000

WHY: the computed triage disposition must persist with the encounter,
not be recomputed on read. A recomputed disposition would change when
the protocol version changes, which would silently rewrite clinical
history for encounters that were already evaluated under an earlier
protocol.

TABLE: the model is app/models/triage_encounter.py's TriageEncounter,
but SQLModel's default naming (no explicit __tablename__) means the
actual table -- as created by migration 79a9d8f8db61 -- is
`triageencounter` (one word), NOT `triage`. Its primary key is `id`
(UUID). Confirmed by reading both the model and the CREATE TABLE in
79a9d8f8db61 before writing this migration.

Note this table already has a NOT NULL `triage_disposition` column
(the Day 1 free-text field the route sets today) and a nullable
`referral_urgency` column. The new `disposition` / `urgency` columns
added here are deliberately separate, engine-computed fields -- this
migration does not touch, rename, or backfill `triage_disposition` or
`referral_urgency`, and no route is modified by this migration.

All nine new columns are added nullable-safe for existing rows:
  - disposition, urgency, reason, protocol_version, engine,
    evaluated_at: NULLABLE, no default, no backfill. Pre-Day-2 rows
    were never evaluated by any decision engine; a NULL disposition on
    those rows is the honest state. Stamping them with a fabricated
    disposition would put a clinical decision into the record that
    nothing ever made, so this migration contains no UPDATE statement
    for `disposition` (or any of these five columns).
  - red_flags, missing_fields: NOT NULL DEFAULT '[]'::jsonb. These are
    structural containers, not opinions -- "no red flags recorded" and
    "no missing fields recorded" are true, non-fabricated statements
    about a row nothing ever evaluated, so a NOT NULL default here
    does not carry the same risk as defaulting `disposition`.
  - insufficient_data: NOT NULL DEFAULT FALSE, same reasoning -- a
    pre-Day-2 row was never flagged insufficient by anything, so
    FALSE is the honest default, not a fabrication.

A partial index on (disposition) WHERE disposition IS NOT NULL lets
operational queries ("show me all triaged-and-decided encounters")
skip the historical NULL rows entirely, without an index entry that
would be meaningless for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a4d72f9e1c83'
down_revision: Union[str, Sequence[str], None] = 'c5e8f3a061db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("triageencounter", sa.Column("disposition", sa.Text(), nullable=True))
    op.add_column("triageencounter", sa.Column("urgency", sa.Text(), nullable=True))
    op.add_column("triageencounter", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(
        "triageencounter",
        sa.Column(
            "red_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("triageencounter", sa.Column("protocol_version", sa.Text(), nullable=True))
    op.add_column(
        "triageencounter",
        sa.Column(
            "insufficient_data", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "triageencounter",
        sa.Column(
            "missing_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("triageencounter", sa.Column("engine", sa.Text(), nullable=True))
    op.add_column(
        "triageencounter",
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "idx_triageencounter_disposition",
        "triageencounter",
        ["disposition"],
        postgresql_where=sa.text("disposition IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_triageencounter_disposition", table_name="triageencounter")
    op.drop_column("triageencounter", "evaluated_at")
    op.drop_column("triageencounter", "engine")
    op.drop_column("triageencounter", "missing_fields")
    op.drop_column("triageencounter", "insufficient_data")
    op.drop_column("triageencounter", "protocol_version")
    op.drop_column("triageencounter", "red_flags")
    op.drop_column("triageencounter", "reason")
    op.drop_column("triageencounter", "urgency")
    op.drop_column("triageencounter", "disposition")
