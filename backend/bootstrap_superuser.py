"""
One-off script: creates a real, login-capable SUPERUSER row in the DEV
database (uses DATABASE_URL from .env, NOT the test DB).

Run from inside the backend/ directory with the venv activated:
    python bootstrap_superuser.py
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
import os

# Make sure we're using the dev DATABASE_URL from .env, not a test DB.
from dotenv import load_dotenv
load_dotenv()

import pyotp

from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.core.password import hash_password

MOBILE = "+919876500001"          # pick any unused, valid E.164 Indian mobile
PASSWORD = "Sup3rSecure!Passw0rd"  # meets the 16-char privileged password policy
# Fixed (not random) so it matches the same constant hardcoded in
# dev_scripts/create_test_staff.py's own TOTP_SECRET for this mobile --
# keep both in sync if this ever changes.
TOTP_SECRET = "QKBN7X76UI2FBS6W4P5OWC4ZJSNYOKZK"

engine = create_engine(os.environ["DATABASE_URL"])

mobile_enc = encrypt_field(MOBILE)
mobile_bi = blind_index(MOBILE)
mobile_masked = mask_mobile(MOBILE)
pw_hash = hash_password(PASSWORD)
now = datetime.now(timezone.utc)
expires_at = now + timedelta(days=90)

with engine.begin() as conn:
    existing = conn.execute(
        text("SELECT id FROM users WHERE mobile_blind_index = :bi"),
        {"bi": mobile_bi},
    ).first()
    if existing:
        user_id = existing[0]
        print(f"Already exists: {user_id}")
    else:
        row = conn.execute(
            text("""
                INSERT INTO users (
                    role, role_level, full_name, preferred_language,
                    mobile_encrypted, mobile_blind_index, mobile_masked,
                    password_hash, password_changed_at, must_change_password,
                    mfa_required, mfa_enrolled, hardware_mfa_required,
                    status, expires_at, activated_at
                ) VALUES (
                    'SUPERUSER', 0, 'Test Superuser', 'en',
                    :menc, :mbi, :mmask,
                    :pwhash, :pwchanged, false,
                    true, true, false,
                    'ACTIVE', :exp, :act
                ) RETURNING id
            """),
            {
                "menc": mobile_enc, "mbi": mobile_bi, "mmask": mobile_masked,
                "pwhash": pw_hash, "pwchanged": now,
                "exp": expires_at, "act": now,
            },
        ).first()
        user_id = row[0]
        print(f"Created SUPERUSER id={user_id}")

    # mfa_required=true above means login can never complete without a
    # matching mfa_credentials row -- without this, the account is a dead
    # end: /auth/mfa/verify always 401s MFA_NOT_ENROLLED, and the one
    # endpoint that could fix that (/auth/mfa/enrol) requires a session
    # you can never obtain (confirmed live: this exact gap blocked a real
    # login attempt). Idempotent like the user insert above -- skips if
    # an unrevoked TOTP credential already exists.
    existing_totp = conn.execute(
        text("SELECT id FROM mfa_credentials WHERE user_id = :u AND credential_type = 'TOTP' AND revoked_at IS NULL"),
        {"u": user_id},
    ).first()
    if existing_totp is None:
        conn.execute(
            text(
                "INSERT INTO mfa_credentials (user_id, credential_type, totp_secret_encrypted, is_verified) "
                "VALUES (:u, 'TOTP', :s, true)"
            ),
            {"u": user_id, "s": encrypt_field(TOTP_SECRET)},
        )
        conn.execute(text("UPDATE users SET mfa_enrolled = true WHERE id = :u"), {"u": user_id})

print(f"Mobile: {MOBILE}")
print(f"Password: {PASSWORD}")
print(f"TOTP secret (add to an authenticator app): {TOTP_SECRET}")
print(f"Current TOTP code (valid ~30s): {pyotp.TOTP(TOTP_SECRET).now()}")
