"""add users.designation and users.photo_object_key

Revision ID: c5e8f3a061db
Revises: f1c9a2e8b374
Create Date: 2026-08-30 00:00:00.000000

Found by direct testing (POST /users against a real Postgres instance
failed with `psycopg.errors.UndefinedColumn: column "designation" of
relation "users" does not exist`), not from a code review -- a genuine
gap between two sections of Day1.md, not something invented here.

SS5.2 (the common-core registration field spec) requires `designation`
(str, required, 2-80 chars, "free text as printed on the posting
order") and `photo_object_key` (str, optional, "object-store key ...
never a base64 blob in the request body") for every staff role. But
SS13.2's own `CREATE TABLE users (...)` DDL -- which migration
c3a9f7d21e56 (S6) reproduced verbatim from that section -- never
included either column. Both sections are Day1.md's own text; this
migration doesn't choose between them, it completes the schema so the
field spec SS5.2 already commits to has somewhere to be stored.

Both columns are added nullable at the database level, even though
`designation` is a *required* field in CommonCore (app/schemas/
profiles.py, S14) -- consistent with how this schema already treats
several API-required fields (e.g. email, conditionally required by
role level) as DB-nullable and enforces requiredness at the
Pydantic/route layer instead. Adding designation as DB NOT NULL would
need the three-phase nullable -> backfill -> NOT NULL pattern (S10)
for the existing bootstrap system user row, which has no designation
value and no natural one to backfill (it's not a real posting).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e8f3a061db'
down_revision: Union[str, Sequence[str], None] = 'f1c9a2e8b374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("designation", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("photo_object_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "photo_object_key")
    op.drop_column("users", "designation")
