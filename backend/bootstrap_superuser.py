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

from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.core.password import hash_password

MOBILE = "+919876500001"          # pick any unused, valid E.164 Indian mobile
PASSWORD = "Sup3rSecure!Passw0rd"  # meets the 16-char privileged password policy

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
        print(f"Already exists: {existing[0]}")
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
        print(f"Created SUPERUSER id={row[0]}")

print(f"Mobile: {MOBILE}")
print(f"Password: {PASSWORD}")
