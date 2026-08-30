"""create otp_codes table

Revision ID: b7d2e4a91c68
Revises: e5a83c1f9d6b
Create Date: 2026-08-30 00:00:00.000000

Not from Day1.md's own SS13 migration plan -- no migration for this
table exists anywhere in the document. Day1.md SS10.5 describes OTP
*properties* (6 digits, 5-min TTL, 3 verify attempts, single use,
hashed at rest) and app/api/routes/auth.py (S16) needs somewhere to
persist them for POST /auth/otp/request and POST /auth/otp/verify --
but no CREATE TABLE for this exists in the document, the same class of
gap as mfa_credentials (S7). Confirmed with the user directly in this
session (2026-08-30), not guessed.

Design notes:
  - mobile_blind_index (not the encrypted mobile itself): lookup-only,
    same pattern as users.mobile_blind_index -- this table never needs
    to display the mobile back, only match against what the caller
    already supplied.
  - otp_hash: plain SHA-256, not Argon2id. SS10.5's "hashed at rest"
    doesn't specify which algorithm; Argon2id (used for passwords,
    S13) is deliberately slow/memory-hard to resist offline brute-force
    on a *reused* secret over a long lifetime -- overkill and the
    wrong tool for a 6-digit code with a 5-minute TTL and 3-attempt
    cap, where the real defence is short expiry + attempt limiting,
    not KDF cost. This matches the fast-hash pattern Day1.md itself
    already uses for refresh tokens and invitation tokens
    (SS10.4/SS7.2's own sha256(presented_token)).
  - otp_token_hash / otp_token_expires_at: after a successful verify,
    SS5.4's PATIENT block and SS14.2's smoke test both show a separate
    short-lived `otp_token` returned to the caller and later presented
    again (to /auth/patient/register, /auth/invite/accept) as proof of
    phone possession, distinct from the original 6-digit code. Both
    are hashed the same way, on the same row, rather than a second
    table, since they represent the same OTP challenge's lifecycle.

Idempotent in the normal Alembic sense (single straightforward
CREATE TABLE); clean downgrade.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7d2e4a91c68'
down_revision: Union[str, Sequence[str], None] = 'e5a83c1f9d6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "otp_codes",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mobile_blind_index", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("otp_hash", sa.Text(), nullable=False),
        sa.Column(
            "attempt_count", sa.SmallInteger(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_token_hash", sa.Text(), nullable=True),
        sa.Column("otp_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_otp_codes_mobile", "otp_codes", ["mobile_blind_index"])
    op.create_index(
        "idx_otp_codes_token", "otp_codes", ["otp_token_hash"],
        postgresql_where=sa.text("otp_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_otp_codes_token", table_name="otp_codes")
    op.drop_index("idx_otp_codes_mobile", table_name="otp_codes")
    op.drop_table("otp_codes")
