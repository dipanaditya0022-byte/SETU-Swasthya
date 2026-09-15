"""dashboard facility indexes + synced_at columns on patient/referral/triageencounter

Revision ID: b9e4c7a2f815
Revises: d4f1c9b7a582
Create Date: 2026-08-31 00:00:00.000000

WHY: GET /dashboard/facility/{org_unit_id} (this same step, app/api/routes/
dashboard.py) needs to scan `referral`/`triageencounter` filtered by
(org_unit_id, status)/(org_unit_id, created_at) and by an open-referral
due_at window at district scale without a sequential scan. This migration
adds exactly the four indexes the route's own queries drive, plus the
`synced_at` column the route's own `synced_today` metric reads.

TABLE NAMES: `referral`, `triageencounter`, `patient` -- singular, real,
verified directly against `\\d referral` / `\\d triageencounter` against the
live dev DB (not the `referrals`/`triage` names used loosely in prose
elsewhere), same verification precedent as every prior migration touching
these tables (9d5f6b3e0a71, d4f1c9b7a582).

HEAD: verified by tracing every migration's own `down_revision` in
alembic/versions/ -- nothing points at d4f1c9b7a582, so it is the current
chain tip. This migration chains directly off it.

============================================================================
THE SYNC/synced_at GAP -- READ BEFORE RELYING ON `synced_today` FOR
referral/triageencounter DATA
============================================================================
Checked directly against the live dev DB before writing this migration:
no `synced_at` column exists anywhere today (zero rows in
information_schema.columns for `%synced%`) and there is no dedicated
sync-log table (zero rows in `\\dt` for anything matching "sync").
app/api/routes/sync.py's `POST /sync/` is today a STATELESS validator --
it writes to no table at all.

Only `patient` has a `client_uuid` column (checked every model in
app/models/*.py -- one hit). `referral` and `triageencounter` have NO
`client_uuid` column at all, and adding one is explicitly OUT OF SCOPE for
this migration (a separate concern -- "one concern per change").

CONSEQUENCE, decided and implemented here, not left ambiguous: this
migration adds nullable `synced_at TIMESTAMPTZ` to all THREE tables (for a
consistent metric shape across the three record types the dashboard route
counts), but app/api/routes/sync.py (wired in this same step, additively)
can only ever genuinely SET it on `patient` rows, by matching an incoming
batch record's `client_uuid` against `patient.client_uuid`. For `referral`/
`triageencounter`, the new `synced_at` column will stay NULL forever until
those tables also grow a `client_uuid` column -- that is a real, structural
limitation of this schema, not a bug in this migration or in the dashboard
route, and it is documented again at the two other places a reader would
look for it: app/api/routes/sync.py's own module docstring, and
app/api/routes/dashboard.py's own `synced_today` metric docstring.

Each of the three `idx_<table>_synced` indexes is on (org_unit_id,
synced_at) -- the dashboard route's own synced_today query filters by
facility and by whether synced_at falls in a given day, so this is the
useful compound key regardless of which of the three tables ever actually
gets a non-NULL value in practice.

============================================================================
THE PARTIAL INDEX ON due_at
============================================================================
`idx_referral_due_open` mirrors d4f1c9b7a582's own `idx_referrals_breach`
partial-index style (`WHERE breached_at IS NULL`). `status NOT IN
('CLOSED', 'CANCELLED')` relies on ordinary Postgres type resolution for
unknown-type string literals: an untyped literal like `'CLOSED'` is
implicitly coerced to whatever type the surrounding operator needs --
here, `referral_status` -- exactly the same resolution Postgres already
performs for any plain `WHERE status = 'CLOSED'` comparison against an
enum column, partial-index predicate or not. (d4f1c9b7a582's own Phase 3
`CASE status WHEN 'INITIATED' THEN 'INITIATED' ...` is NOT cited as prior
proof of this here -- that UPDATE ran while `status` was still `TEXT`,
before that same migration's Phase 5 conversion to the enum type, so it
does not actually exercise this cast path. This partial index is the
first place in this schema's own migrations that compares string
literals against the already-enum `status` column.)

downgrade() reverses every step in the opposite order: drops the five new
indexes, then drops the three new `synced_at` columns. Nothing dropped here
was added by any earlier migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9e4c7a2f815'
down_revision: Union[str, Sequence[str], None] = 'd4f1c9b7a582'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- synced_at, nullable, all three tables (see module docstring's
    # "THE SYNC/synced_at GAP" -- referral/triageencounter will stay NULL
    # in practice until they grow their own client_uuid column, a
    # deliberately separate, out-of-scope concern). Nullable end-state, so
    # no three-phase nullable -> backfill -> NOT NULL dance is needed --
    # there is nothing to backfill; every existing row's synced state is
    # genuinely unknown, and NULL is the correct representation of that. --
    op.add_column("patient", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("referral", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("triageencounter", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))

    # ---- facility-scoped dashboard query indexes ----
    op.create_index("idx_referral_org_status", "referral", ["org_unit_id", "status"])
    op.create_index("idx_triageencounter_org_created", "triageencounter", ["org_unit_id", "created_at"])
    op.create_index(
        "idx_referral_due_open", "referral", ["due_at"],
        postgresql_where=sa.text("status NOT IN ('CLOSED', 'CANCELLED')"),
    )

    # ---- synced_at lookup indexes, one per table (see module docstring) ----
    op.create_index("idx_patient_synced", "patient", ["org_unit_id", "synced_at"])
    op.create_index("idx_referral_synced", "referral", ["org_unit_id", "synced_at"])
    op.create_index("idx_triageencounter_synced", "triageencounter", ["org_unit_id", "synced_at"])


def downgrade() -> None:
    op.drop_index("idx_triageencounter_synced", table_name="triageencounter")
    op.drop_index("idx_referral_synced", table_name="referral")
    op.drop_index("idx_patient_synced", table_name="patient")

    op.drop_index("idx_referral_due_open", table_name="referral")
    op.drop_index("idx_triageencounter_org_created", table_name="triageencounter")
    op.drop_index("idx_referral_org_status", table_name="referral")

    op.drop_column("triageencounter", "synced_at")
    op.drop_column("referral", "synced_at")
    op.drop_column("patient", "synced_at")
