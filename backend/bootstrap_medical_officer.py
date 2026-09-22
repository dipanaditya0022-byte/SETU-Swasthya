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
        # Was previously a hardcoded UUID that only matched one laptop's local
        # DB -- gen_random_uuid() makes bootstrap_superuser.py's id different
        # on every fresh DB, so a literal here breaks on any other checkout.
        # Look up whichever SUPERUSER already exists instead. Run
        # bootstrap_superuser.py first if this comes back empty.
        creator = conn.execute(
            text("SELECT id FROM users WHERE role = 'SUPERUSER' ORDER BY activated_at ASC LIMIT 1")
        ).scalar()
        if not creator:
            raise SystemExit(
                "No SUPERUSER found in the database -- run bootstrap_superuser.py "
                "(or apply migrations, which seed a default SUPERUSER) before this script."
            )

        # Same "works on my laptop" bug class as `creator` above, just
        # never fixed here: ORG_UNIT_ID used to be a hardcoded literal
        # that only matched whichever laptop's local DB happened to seed
        # that exact UUID (confirmed live: this exact FK violation --
        # scope_org_unit_id not present in org_units -- on a genuinely
        # fresh/differently-seeded database). Prefer a PHC (where
        # create_test_staff.py's own MEDICAL_OFFICER profile posts one),
        # fall back to any org unit if no PHC exists.
        org_unit_id = conn.execute(
            text("SELECT id FROM org_units WHERE unit_type = 'PHC' ORDER BY name ASC LIMIT 1")
        ).scalar()
        if not org_unit_id:
            org_unit_id = conn.execute(text("SELECT id FROM org_units LIMIT 1")).scalar()
        if not org_unit_id:
            raise SystemExit(
                "No org_units found in the database -- run backend/scripts/seed_demo.py "
                "(or otherwise create at least one org unit) before this script."
            )

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
            "org": org_unit_id, "creator": creator, "act": now,
        }).first()
        print(f"Created MEDICAL_OFFICER id={row[0]}")

print(f"Mobile: {MOBILE}")
print(f"Password: {PASSWORD}")
