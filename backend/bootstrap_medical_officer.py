from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
load_dotenv()

from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.core.password import hash_password

MOBILE = "+919876500002"
PASSWORD = "Med1calOfficer!Pass"
SUPERUSER_ID = "f2014011-998c-48f1-8231-673c4be286bf"
ORG_UNIT_ID = "00000000-0000-0000-0000-000000000002"

engine = create_engine(os.environ["DATABASE_URL"])

mobile_enc = encrypt_field(MOBILE)
mobile_bi = blind_index(MOBILE)
mobile_masked = mask_mobile(MOBILE)
pw_hash = hash_password(PASSWORD)
now = datetime.now(timezone.utc)

with engine.begin() as conn:
    existing = conn.execute(text("SELECT id FROM users WHERE mobile_blind_index = :bi"), {"bi": mobile_bi}).first()
    if existing:
        print(f"Already exists: {existing[0]}")
    else:
        row = conn.execute(text("""
            INSERT INTO users (
                role, role_level, full_name, preferred_language,
                mobile_encrypted, mobile_blind_index, mobile_masked,
                password_hash, password_changed_at, must_change_password,
                mfa_required, mfa_enrolled, hardware_mfa_required,
                scope_org_unit_id, scope_path, created_by_user_id,
                status, activated_at
            ) VALUES (
                'MEDICAL_OFFICER', 6, 'Test Medical Officer', 'en',
                :menc, :mbi, :mmask,
                :pwhash, :pwchanged, false,
                false, false, false,
                :org, (SELECT path FROM org_units WHERE id = :org), :creator,
                'ACTIVE', :act
            ) RETURNING id
        """), {
            "menc": mobile_enc, "mbi": mobile_bi, "mmask": mobile_masked,
            "pwhash": pw_hash, "pwchanged": now,
            "org": ORG_UNIT_ID, "creator": SUPERUSER_ID, "act": now,
        }).first()
        print(f"Created MEDICAL_OFFICER id={row[0]}")

print(f"Mobile: {MOBILE}")
print(f"Password: {PASSWORD}")
