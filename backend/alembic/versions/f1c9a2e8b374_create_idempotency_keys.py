"""create idempotency_keys table

Revision ID: f1c9a2e8b374
Revises: b7d2e4a91c68
Create Date: 2026-08-30 00:00:00.000000

Not from Day1.md's own SS13 migration plan -- no table for this exists
anywhere in the document. SS15.3 describes the required behaviour
("The key plus a hash of the request body is stored for 24 hours with
the original response. A retry after a network timeout returns the
original 201 rather than creating a duplicate account.") for POST
/users, POST /auth/patient/register, and POST /users/{id}/approve, but
never gives a schema -- the same class of gap as mfa_credentials (S7)
and otp_codes (S16). Confirmed with the user directly in this session
(2026-08-30), not guessed.

UNIQUE (idempotency_key, endpoint): the same client-supplied key could
plausibly be reused across different endpoints without meaning "this
is the same request" -- scoping the uniqueness to (key, endpoint) pair
avoids a collision between, say, a POST /users retry and an unrelated
POST /users/{id}/approve that happened to reuse a client-generated UUID.

expires_at is a plain column, not enforced by the database (no cron/
extension assumed) -- the application is expected to treat a row past
its expires_at as if it didn't exist (SS15.3's "for 24 hours"), and a
future cleanup job (out of scope here) can periodically delete expired
rows. This mirrors how mfa_credentials/otp_codes handle TTL -- an
expires_at column checked by application code, not a database-enforced
expiry mechanism.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1c9a2e8b374'
down_revision: Union[str, Sequence[str], None] = 'b7d2e4a91c68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=False),
        sa.Column(
            "response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_key_endpoint"),
    )
    op.create_index("idx_idempotency_expires", "idempotency_keys", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_idempotency_expires", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
