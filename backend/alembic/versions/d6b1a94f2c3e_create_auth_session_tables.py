"""create auth/session support tables (user_invitations, refresh_tokens, mfa_credentials, password_history, login_attempts)

Revision ID: d6b1a94f2c3e
Revises: c3a9f7d21e56
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS13.4 / SS17 (migration 0005 in the doc's numbering): the five
auth/session support tables assigned to this revision.

Four of the five -- user_invitations, refresh_tokens, password_history,
login_attempts -- are copied verbatim from the CREATE TABLE blocks in
Day1.md SS13.4, including their CHECK constraints and indexes.
(approval_requests, break_glass_sessions and consents also live in
SS13.4's same SQL block, but SS17 assigns them to migration 0006, not
this one -- they are intentionally not created here.)

mfa_credentials has NO CREATE TABLE anywhere in Day1.md -- it is named
only in the SS13.1 entity-relationship diagram (as a child of `users`)
and in SS17's migration-plan table. This was flagged to the user as a
genuine gap (not guessed) in this session. The user was asked directly,
via an explicit multiple-choice confirmation UI (not free text, and not
an agent-relayed claim), to choose between: (a) a proposed schema
covering both TOTP and WebAuthn/hardware-key credentials in one table,
(b) deferring mfa_credentials to a later migration, or (c) supplying a
better source. The user picked (a) on 2026-08-30. The resulting schema
below is that proposal, not a Day1.md quote:

  mfa_credentials
    id                      UUID PK DEFAULT gen_random_uuid()
    user_id                 UUID NOT NULL REFERENCES users(id)
    credential_type         TEXT NOT NULL  -- 'TOTP' | 'HARDWARE_KEY'
    totp_secret_encrypted   BYTEA          -- AES-256-GCM; NULL for hardware keys.
                                            -- Reversible encryption, not a hash:
                                            -- Day1.md SS10 requires the server to
                                            -- recompute TOTP codes to verify, which
                                            -- a one-way hash cannot support -- unlike
                                            -- users.password_hash, this secret must
                                            -- be decryptable by the application.
    webauthn_credential_id  TEXT           -- NULL for TOTP
    webauthn_public_key     BYTEA          -- NULL for TOTP; not secret, safe at rest
    webauthn_sign_count     INTEGER        -- replay-protection counter; NULL for TOTP
    is_verified             BOOLEAN NOT NULL DEFAULT false
    enrolled_at              TIMESTAMPTZ NOT NULL DEFAULT now()
    verified_at              TIMESTAMPTZ
    last_used_at             TIMESTAMPTZ
    revoked_at                TIMESTAMPTZ

  Two CHECK constraints enforce that each credential_type only ever
  populates the columns that make sense for it (mirroring the mutual-
  exclusivity style of users.chk_superuser_expires): a TOTP row must
  carry an encrypted secret and no WebAuthn fields; a HARDWARE_KEY row
  must carry both WebAuthn fields and no TOTP secret. A partial-unique
  index on webauthn_credential_id (where not null) prevents the same
  physical hardware key being registered to two different accounts.

Security note verified against C2/Day1.md SS10.5 ("An MFA secret after
enrolment" must never be returned by the API): this migration stores no
plaintext token/secret column anywhere -- user_invitations.token_hash
and refresh_tokens.token_hash are hashes (never the raw token), and
mfa_credentials.totp_secret_encrypted is ciphertext (application-layer
AES-256-GCM, same convention as users.mobile_encrypted), not plaintext.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd6b1a94f2c3e'
down_revision: Union[str, Sequence[str], None] = 'c3a9f7d21e56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. user_invitations -- verbatim, Day1.md SS13.4.
    op.create_table(
        "user_invitations",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "accept_mode", sa.Text(), nullable=False,
            server_default=sa.text("'PASSWORD'"),
        ),
        sa.Column(
            "issued_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count", sa.SmallInteger(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "delivery_channel", sa.Text(), nullable=False,
            server_default=sa.text("'SMS_EMAIL'"),
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR revoked_at IS NULL",
            name="chk_invite_single_use",
        ),
    )
    op.create_index("idx_invitations_user", "user_invitations", ["user_id"])

    # 2. refresh_tokens -- verbatim, Day1.md SS13.4.
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_fingerprint", sa.Text(), nullable=True),
        sa.Column("device_label", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_refresh_user", "refresh_tokens", ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("idx_refresh_family", "refresh_tokens", ["family_id"])

    # 3. mfa_credentials -- schema gap in Day1.md, proposed and confirmed
    #    by the user directly in this session (see module docstring).
    op.create_table(
        "mfa_credentials",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("credential_type", sa.Text(), nullable=False),
        sa.Column("totp_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("webauthn_credential_id", sa.Text(), nullable=True),
        sa.Column("webauthn_public_key", sa.LargeBinary(), nullable=True),
        sa.Column("webauthn_sign_count", sa.Integer(), nullable=True),
        sa.Column(
            "is_verified", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "enrolled_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "credential_type IN ('TOTP', 'HARDWARE_KEY')",
            name="chk_mfa_credential_type_valid",
        ),
        sa.CheckConstraint(
            "(credential_type = 'TOTP' AND totp_secret_encrypted IS NOT NULL "
            " AND webauthn_credential_id IS NULL AND webauthn_public_key IS NULL) "
            "OR "
            "(credential_type = 'HARDWARE_KEY' AND webauthn_credential_id IS NOT NULL "
            " AND webauthn_public_key IS NOT NULL AND totp_secret_encrypted IS NULL)",
            name="chk_mfa_credential_fields_match_type",
        ),
    )
    op.create_index("idx_mfa_credentials_user", "mfa_credentials", ["user_id"])
    op.create_index(
        "idx_mfa_webauthn_credential_id", "mfa_credentials",
        ["webauthn_credential_id"],
        unique=True, postgresql_where=sa.text("webauthn_credential_id IS NOT NULL"),
    )

    # 4. password_history -- verbatim, Day1.md SS13.4.
    op.create_table(
        "password_history",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 5. login_attempts -- verbatim, Day1.md SS13.4. BIGSERIAL PK.
    op.create_table(
        "login_attempts",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True,
        ),
        sa.Column("identifier_bi", sa.Text(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_login_attempts_ip", "login_attempts",
        ["ip", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "idx_login_attempts_id", "login_attempts",
        ["identifier_bi", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_login_attempts_id", table_name="login_attempts")
    op.drop_index("idx_login_attempts_ip", table_name="login_attempts")
    op.drop_table("login_attempts")

    op.drop_table("password_history")

    op.drop_index("idx_mfa_webauthn_credential_id", table_name="mfa_credentials")
    op.drop_index("idx_mfa_credentials_user", table_name="mfa_credentials")
    op.drop_table("mfa_credentials")

    op.drop_index("idx_refresh_family", table_name="refresh_tokens")
    op.drop_index("idx_refresh_user", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("idx_invitations_user", table_name="user_invitations")
    op.drop_table("user_invitations")
