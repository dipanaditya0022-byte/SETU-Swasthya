"""Deterministic demo dataset (Day-3 demo-prep task).

FIXED UUIDs, FIXED names, FIXED values throughout -- re-running this
script produces an IDENTICAL database every time. IDEMPOTENT: truncates
the demo-owned tables first, then re-inserts everything fresh -- not an
upsert. Chosen because "identical database" is the literal requirement
and a clean truncate+reinsert is the only way to *guarantee* that (an
upsert can't undo a manual row someone deleted between runs); this is
also exactly what backend/scripts/reset_demo.sh needs anyway, so the
seed script doing its own truncation makes that a one-line "run this
script again" rather than a second, separately-maintained truncate list.

Does NOT touch reference/seed data (roles, permissions, role_permissions,
role_creation_grants) or anything outside the demo tables -- same
distinction tests/conftest.py's own `_MUTABLE_TABLES` truncate list
already draws for the pytest DB, reused here (this file keeps its own
copy scoped to just what THIS seed writes, not that file's full list,
since this is the real dev/demo DB, not a per-test throwaway).

EVERY demo patient's mobile number starts with the literal prefix
+9190000000 -- this is the exact detection mechanism
backend/tests/test_no_real_data.py's guard checks against. Get this
prefix exactly right if you ever touch this file.

UUID NAMESPACE (hand-picked constants, never uuid4()) -- the 4th
hyphen-group of every UUID below names its CATEGORY, so any UUID printed
anywhere in a demo (a curl response, a screen) is instantly recognisable:
  ...-0001-...   org units
  ...-0002-...   users (staff + the one patient-role login account)
  ...-0003-...   patient (clinical) records
  ...-0004-...   triage encounters
  ...-0005-...   referrals
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.core.password import hash_password
from app.jobs.breach_detection import detect_breaches
from app.services.referral.breach import compute_due_at
from app.services.triage.fallback import FallbackTriageEngine
from app.services.triage.port import TriageInput

engine = create_engine(os.environ["DATABASE_URL"])

# ============================================================
# Fixed UUIDs
# ============================================================
ORG = {
    "DISTRICT": "00000000-0000-0000-0001-000000000001",
    "BLOCK": "00000000-0000-0000-0001-000000000002",
    "PHC": "00000000-0000-0000-0001-000000000003",
    "HWC": "00000000-0000-0000-0001-000000000004",
    "VILLAGE_NORTH": "00000000-0000-0000-0001-000000000005",
    "VILLAGE_SOUTH": "00000000-0000-0000-0001-000000000006",
}

# role -> (uuid, full_name, mobile suffix, role_level, scope org unit key)
# DHO -> DHO_CMO (closest real RoleCode; no bare "DHO" exists in
# app/models/enums.py -- confirmed before writing this). MO -> MEDICAL_OFFICER.
# ANM -> ANM_MPW. Every other name matches a real RoleCode directly.
#
# STAFF mobiles use a DIFFERENT, still-obviously-fake +9190000001XX
# range, not the exact +9190000000 prefix -- deliberate, not an
# oversight: Part 3's own guard is specifically scoped to "every PATIENT
# mobile" (the `patient` table, clinical records -- the actual DPDP risk
# this whole guard exists for), not staff accounts. Keeping staff on a
# visibly distinct numbering (xxx101-106 vs patients' xxx01-12) also
# makes the two categories easier to tell apart at a glance during a
# live demo. See backend/tests/test_no_real_data.py's own docstring for
# the same scoping, stated again there.
USERS = {
    "DHO":   ("00000000-0000-0000-0002-000000000001", "Dr. Demo DHO",   "+919000000101", "DHO_CMO", 3, "DISTRICT"),
    "BMO":   ("00000000-0000-0000-0002-000000000002", "Dr. Demo BMO",   "+919000000102", "BMO", 5, "BLOCK"),
    "MO":    ("00000000-0000-0000-0002-000000000003", "Dr. Demo MO",    "+919000000103", "MEDICAL_OFFICER", 6, "PHC"),
    "CHO":   ("00000000-0000-0000-0002-000000000004", "Demo CHO",       "+919000000104", "CHO", 7, "HWC"),
    "ANM":   ("00000000-0000-0000-0002-000000000005", "Demo ANM",       "+919000000105", "ANM_MPW", 8, "HWC"),
    "ASHA":  ("00000000-0000-0000-0002-000000000006", "Demo ASHA",      "+919000000106", "ASHA", 9, "VILLAGE_NORTH"),
}
# The one PATIENT-role login account (separate from the 12 clinical
# `patient` table rows below) -- for a "log in as the patient" demo beat.
PATIENT_USER_ID = "00000000-0000-0000-0002-000000000099"
PATIENT_USER_MOBILE = "+919000000199"

# 12 patients, fake Indian-context names -- deliberately generic,
# common-but-fake given+family name pairs, not any real/specific person.
# Every mobile starts with the seed prefix +9190000000 (task's own exact
# requirement) followed by a 2-digit index 01-12.
PATIENTS = [
    ("00000000-0000-0000-0003-000000000001", "Anjali Sharma", 28, "VILLAGE_NORTH"),
    ("00000000-0000-0000-0003-000000000002", "Ravi Kumar", 45, "VILLAGE_NORTH"),
    ("00000000-0000-0000-0003-000000000003", "Sunita Devi", 32, "VILLAGE_NORTH"),
    ("00000000-0000-0000-0003-000000000004", "Manoj Yadav", 51, "VILLAGE_NORTH"),
    ("00000000-0000-0000-0003-000000000005", "Pooja Singh", 24, "VILLAGE_NORTH"),
    ("00000000-0000-0000-0003-000000000006", "Rakesh Prasad", 60, "VILLAGE_NORTH"),
    ("00000000-0000-0000-0003-000000000007", "Meena Kumari", 29, "VILLAGE_SOUTH"),
    ("00000000-0000-0000-0003-000000000008", "Suresh Verma", 38, "VILLAGE_SOUTH"),
    ("00000000-0000-0000-0003-000000000009", "Kavita Devi", 33, "VILLAGE_SOUTH"),
    ("00000000-0000-0000-0003-000000000010", "Deepak Mishra", 41, "VILLAGE_SOUTH"),
    ("00000000-0000-0000-0003-000000000011", "Geeta Rani", 27, "VILLAGE_SOUTH"),
    ("00000000-0000-0000-0003-000000000012", "Ashok Pandey", 55, "VILLAGE_SOUTH"),
]

# 8 triage encounters covering all four real dispositions (MANAGE_HERE,
# TELECONSULT, REFER, EMERGENCY -- app/services/triage/port.py's own
# Disposition Literal, confirmed no fifth value exists). Vitals are the
# SAME reference values proven live in an earlier task's
# tests/fixtures/triage/ fixtures -- not guessed thresholds -- run
# through the real FallbackTriageEngine below, not hardcoded.
# patient index (0-based into PATIENTS) -> (protocol, vitals, danger_signs)
TRIAGE_CASES = [
    (0, "ANC", {"bp_systolic": 118, "bp_diastolic": 76, "haemoglobin": 11.4}, []),   # MANAGE_HERE
    (1, "ANC", {"bp_systolic": 118, "bp_diastolic": 76, "temperature_c": 38.5}, []),  # TELECONSULT (fever)
    (2, "ANC", {"bp_systolic": 142, "bp_diastolic": 92}, []),                         # REFER
    (3, "ANC", {"bp_systolic": 172, "bp_diastolic": 116}, []),                        # EMERGENCY
    (4, "NCD", {"bp_systolic": 118, "bp_diastolic": 76}, []),                         # MANAGE_HERE
    (5, "NCD", {"bp_systolic": 145, "bp_diastolic": 92}, []),                         # TELECONSULT (NCD 140-160/90-100)
    (6, "ANC", {"bp_systolic": 145, "bp_diastolic": 95}, []),                         # REFER
    (7, "ANC", {"bp_systolic": 130, "bp_diastolic": 84}, ["convulsions"]),            # EMERGENCY (danger sign)
]
TRIAGE_IDS = [f"00000000-0000-0000-0004-{i+1:012d}" for i in range(len(TRIAGE_CASES))]

# 5 referrals -- (patient index, urgency, kind)
#   kind in {"on_track", "breached", "closed", "refused"}
REFERRAL_IDS = [f"00000000-0000-0000-0005-{i+1:012d}" for i in range(5)]

DEMO_SYNC_BATCH_PATH = Path(__file__).parent / "demo_sync_batch.json"

# Tables this script owns -- truncated (FK-safe order: children before
# parents) before every seed run. Deliberately NOT the reference/seed
# tables (roles, permissions, role_permissions, role_creation_grants,
# facility) -- those are shared platform seed data, not demo content.
_DEMO_TABLES_FK_ORDER = [
    "referral_transitions", "audit_log", "consents", "triageencounter",
    "referral", "patient", "users", "org_units",
]


def _reset(conn) -> None:
    conn.execute(text("TRUNCATE " + ", ".join(_DEMO_TABLES_FK_ORDER) + " CASCADE"))


def _insert_org_unit(conn, org_id: str, unit_type: str, name: str, parent_id: str | None) -> None:
    conn.execute(text(
        "INSERT INTO org_units (id, unit_type, name, parent_id) VALUES (:id, :t, :n, :p)"
    ), {"id": org_id, "t": unit_type, "n": name, "p": parent_id})


def _seed_org_units(conn) -> None:
    _insert_org_unit(conn, ORG["DISTRICT"], "DISTRICT", "Demo District", None)
    _insert_org_unit(conn, ORG["BLOCK"], "BLOCK", "Demo Block", ORG["DISTRICT"])
    _insert_org_unit(conn, ORG["PHC"], "PHC", "Demo PHC", ORG["BLOCK"])
    _insert_org_unit(conn, ORG["HWC"], "HWC", "Demo HWC", ORG["BLOCK"])
    _insert_org_unit(conn, ORG["VILLAGE_NORTH"], "VILLAGE", "Demo Village North", ORG["PHC"])
    _insert_org_unit(conn, ORG["VILLAGE_SOUTH"], "VILLAGE", "Demo Village South", ORG["PHC"])


def _seed_users(conn) -> str:
    """Returns the DHO's own id, used as `created_by_user_id` for
    everyone else (a real, in-tree creator -- chk_creator_required
    requires one for every non-PATIENT/non-SUPERUSER row). The DHO
    itself is attributed to a throwaway SUPERUSER row created here only
    to satisfy that same constraint, then never referenced again (no
    SUPERUSER login is part of this demo dataset)."""
    # SUPERUSER's own required fields (chk_privileged_mfa: mfa_required=
    # true; chk_superuser_expires: expires_at NOT NULL) -- matches
    # bootstrap_superuser.py's own already-working INSERT, not guessed.
    bootstrap_superuser_id = "00000000-0000-0000-0002-000000000000"
    now = datetime.now(timezone.utc)
    conn.execute(text(
        "INSERT INTO users (id, role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
        "mobile_masked, status, mfa_required, mfa_enrolled, expires_at, activated_at) "
        "VALUES (:id, 'SUPERUSER', 0, 'Demo Seed Bootstrap', :menc, :mbi, :mmask, 'ACTIVE', true, true, :exp, :act)"
    ), {
        "id": bootstrap_superuser_id, "menc": encrypt_field("+919000000001"),
        "mbi": blind_index("+919000000001"), "mmask": mask_mobile("+919000000001"),
        "exp": now + timedelta(days=90), "act": now,
    })

    for key, (user_id, full_name, mobile, role, role_level, org_key) in USERS.items():
        pw_hash = hash_password("Demo1234!Pass")
        # chk_privileged_mfa: role_level > 5 OR mfa_required = TRUE --
        # DHO (level 3) and BMO (level 5) are privileged and MUST carry
        # mfa_required=true to satisfy the constraint. mfa_enrolled stays
        # false for every demo account (no real TOTP secret is
        # provisioned by this script) -- meaning a live password login
        # for DHO/BMO specifically will return an mfa_challenge token,
        # not real access tokens, matching this system's own real
        # security design (a district health officer login going
        # through MFA is correct behaviour, not a demo bug). Documented
        # plainly in DEMO_RUNBOOK.md: use MO/CHO/ANM/ASHA for any live
        # login walkthrough; DHO/BMO exist in the dataset for their
        # staff/scope/attribution role, not as a live-login demo path.
        mfa_required = role_level <= 5
        conn.execute(text(
            "INSERT INTO users (id, role, role_level, full_name, preferred_language, "
            "mobile_encrypted, mobile_blind_index, mobile_masked, password_hash, "
            "password_changed_at, must_change_password, mfa_required, mfa_enrolled, "
            "hardware_mfa_required, scope_org_unit_id, scope_path, created_by_user_id, "
            "status, activated_at) "
            "VALUES (:id, :role, :lvl, :fn, 'en', :menc, :mbi, :mmask, :pwhash, :pwchanged, "
            "false, :mfareq, false, false, :org, (SELECT path FROM org_units WHERE id = :org), "
            ":creator, 'ACTIVE', :act)"
        ), {
            "id": user_id, "role": role, "lvl": role_level, "fn": full_name,
            "menc": encrypt_field(mobile), "mbi": blind_index(mobile), "mmask": mask_mobile(mobile),
            "pwhash": pw_hash, "pwchanged": datetime.now(timezone.utc), "mfareq": mfa_required,
            "org": ORG[org_key], "creator": bootstrap_superuser_id, "act": datetime.now(timezone.utc),
        })

    # The one PATIENT-role login account (task's own "plus 1 patient
    # account"). PATIENT rows are exempt from chk_creator_required/
    # chk_scope_required (no org posting, no creator needed) -- given a
    # demo password too (real self-registration is OTP-only, but this is
    # seed data for a live demo, not a production account -- a fixed
    # password here is a deliberate shortcut so the demo doesn't depend
    # on reading a fresh OTP off the server log mid-presentation; noted
    # plainly in DEMO_RUNBOOK.md, not hidden).
    pw_hash = hash_password("Demo1234!Pass")
    conn.execute(text(
        "INSERT INTO users (id, role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
        "mobile_masked, password_hash, password_changed_at, must_change_password, mfa_required, "
        "mfa_enrolled, status, activated_at) "
        "VALUES (:id, 'PATIENT', 99, 'Demo Patient Account', :menc, :mbi, :mmask, :pwhash, :pwchanged, "
        "false, false, false, 'ACTIVE', :act)"
    ), {
        "id": PATIENT_USER_ID, "menc": encrypt_field(PATIENT_USER_MOBILE), "mbi": blind_index(PATIENT_USER_MOBILE),
        "mmask": mask_mobile(PATIENT_USER_MOBILE), "pwhash": pw_hash, "pwchanged": datetime.now(timezone.utc),
        "act": datetime.now(timezone.utc),
    })

    return USERS["MO"][0]  # MO is the creator/actor for patient/triage/referral rows below


def _seed_patients(conn, actor_id: str) -> None:
    for i, (patient_id, name, age, village_key) in enumerate(PATIENTS):
        mobile = f"+9190000000{i + 1:02d}"
        conn.execute(text(
            "INSERT INTO patient (id, name, age, village, phone, facility_id, created_by_user_id, "
            "org_unit_id, created_at) "
            "VALUES (:id, :name, :age, :village, :phone, :facility_id, :creator, :org, :created_at)"
        ), {
            "id": patient_id, "name": name, "age": age,
            "village": "North Village" if village_key == "VILLAGE_NORTH" else "South Village",
            "phone": mobile, "facility_id": ORG[village_key], "creator": actor_id, "org": ORG[village_key],
            "created_at": datetime.now(timezone.utc),
        })


def _seed_triage(conn, actor_id: str) -> None:
    engine_obj = FallbackTriageEngine()
    for (patient_idx, protocol, vitals, danger_signs), triage_id in zip(TRIAGE_CASES, TRIAGE_IDS):
        patient_id = PATIENTS[patient_idx][0]
        decision = engine_obj.evaluate(TriageInput(
            protocol=protocol, vitals=vitals, danger_signs=danger_signs,
        ))
        conn.execute(text(
            "INSERT INTO triageencounter (id, patient_id, facility_id, triage_disposition, "
            "referral_urgency, created_by_user_id, org_unit_id, disposition, urgency, reason, "
            "red_flags, protocol_version, insufficient_data, missing_fields, engine, evaluated_at, "
            "created_at) "
            "VALUES (:id, :pid, :fid, :td, :ru, :creator, :org, :disp, :urg, :reason, "
            ":flags, :pv, :insuff, :missing, :engine, :evalat, :createdat)"
        ), {
            "id": triage_id, "pid": patient_id, "fid": ORG["PHC"], "td": decision.disposition,
            "ru": decision.urgency, "creator": actor_id, "org": ORG["PHC"],
            "disp": decision.disposition, "urg": decision.urgency, "reason": decision.reason,
            "flags": json.dumps(decision.red_flags), "pv": decision.protocol_version,
            "insuff": decision.insufficient_data, "missing": json.dumps(decision.missing_fields),
            "createdat": datetime.now(timezone.utc),
            "engine": engine_obj.name, "evalat": datetime.now(timezone.utc),
        })


def _write_transition(conn, referral_id: str, from_status: str | None, to_status: str, actor_id: str) -> None:
    conn.execute(text(
        "INSERT INTO referral_transitions (referral_id, from_status, to_status, actor_user_id, "
        "actor_role, metadata) VALUES (:rid, :fs, :ts, :actor, 'MEDICAL_OFFICER', '{}'::jsonb)"
    ), {"rid": referral_id, "fs": from_status, "ts": to_status, "actor": actor_id})


def _seed_referrals(conn, actor_id: str) -> None:
    now = datetime.now(timezone.utc)

    def _create(idx: int, patient_idx: int, urgency: str, initiated_at: datetime, status: str,
                extra: dict | None = None) -> None:
        referral_id = REFERRAL_IDS[idx]
        due_at = compute_due_at(initiated_at, urgency)
        row = {
            "id": referral_id, "pid": PATIENTS[patient_idx][0], "from_fid": ORG["PHC"],
            "dest_fid": ORG["HWC"], "reason": "Demo referral -- follow-up required",
            "urgency": urgency, "status": status, "owner": "Demo BMO",
            "creator": actor_id, "org": ORG["PHC"], "initiated_at": initiated_at, "due_at": due_at,
            "created_at": initiated_at, "escalation_stage": 0,
        }
        row.update(extra or {})
        columns = ["id", "patient_id", "from_facility_id", "destination_facility_id", "reason",
                   "urgency", "status", "owner", "created_by_user_id", "org_unit_id",
                   "initiated_at", "due_at", "created_at", "escalation_stage"]
        extra_cols = [c for c in (extra or {}) if c not in columns]
        columns += extra_cols
        placeholders = ", ".join(f":{c}" for c in columns)
        col_map = {"patient_id": "pid", "from_facility_id": "from_fid", "destination_facility_id": "dest_fid",
                   "created_by_user_id": "creator", "org_unit_id": "org"}
        insert_cols = ", ".join(columns)
        bind_names = ", ".join(f":{col_map.get(c, c)}" for c in columns)
        conn.execute(text(f"INSERT INTO referral ({insert_cols}) VALUES ({bind_names})"), row)
        _write_transition(conn, referral_id, None, "INITIATED", actor_id)

    # 1. On-track #1 -- INITIATED, URGENT, initiated now (due_at ~24h out).
    _create(0, 0, "URGENT", now, "INITIATED")

    # 2. On-track #2 -- SLOT_BOOKED, ROUTINE, due_at days out.
    _create(1, 1, "ROUTINE", now, "SLOT_BOOKED",
            extra={"slot_datetime": now + timedelta(days=2)})
    _write_transition(conn, REFERRAL_IDS[1], "INITIATED", "SLOT_BOOKED", actor_id)

    # 3. BREACHED -- backdated initiated_at (now-30h), URGENT (24h window)
    # -> due_at ~6h in the past, so this shows in GET /referrals/exceptions
    # both via the route's own LIVE is_breached() check (no job needed)
    # AND (after detect_breaches() runs, below) with a real breached_at/
    # escalation_stage set, matching what a genuinely-aged referral would
    # look like.
    backdated = now - timedelta(hours=30)
    _create(2, 2, "URGENT", backdated, "INITIATED")

    # 4. CLOSED -- set directly, not walked through every intermediate
    # state via HTTP (script determinism/speed over full-path realism;
    # PATCH .../status's own real transition path is already covered by
    # backend/tests/test_referral_day3.py). One transition row recorded
    # (INITIATED -> CLOSED) for basic consistency with what the real
    # route would have written, not the full intermediate chain.
    _create(3, 3, "ROUTINE", now - timedelta(days=3), "CLOSED",
            extra={"closed_at": now - timedelta(days=1)})
    _write_transition(conn, REFERRAL_IDS[3], "INITIATED", "CLOSED", actor_id)

    # 5. REFUSED -- with a real RefusalReason value (app/models/
    # referral_state.py's own enum).
    _create(4, 4, "ROUTINE", now - timedelta(days=1), "REFUSED",
            extra={"refusal_reason": "DISTANCE"})
    _write_transition(conn, REFERRAL_IDS[4], "INITIATED", "REFUSED", actor_id)


def _write_demo_sync_batch() -> None:
    """A realistic offline-queue payload, pre-staged as a JSON file, for
    someone to `curl -X POST http://localhost:8002/sync/ -H "Authorization:
    Bearer $TOKEN" -d @demo_sync_batch.json` live during the demo -- the
    exact real POST /sync/ request shape (a bare list of dicts, matched
    by client_uuid -- app/api/routes/sync.py's own module docstring),
    fixed client_uuids so this file itself is deterministic/re-runnable."""
    # Phones continue the same +9190000000XX seed-prefix scheme as the 12
    # PATIENTS above (index 13-15) -- these become REAL `patient` rows
    # once POST /sync/ is actually called with this file, so they must
    # pass the same test_no_real_data.py prefix guard as everything else.
    # (Caught live: an earlier version of this file used a DIFFERENT,
    # non-matching prefix by a one-digit slip -- +919000000901 instead of
    # +9190000000XX -- fixed here after the guard test's own dry run
    # would have failed on it.)
    batch = [
        {"client_uuid": "demo-sync-0001", "name": "Vikram Chauhan", "age": 34,
         "village": "North Village", "phone": "+9190000000" + "13", "facility_id": ORG["VILLAGE_NORTH"]},
        {"client_uuid": "demo-sync-0002", "name": "Lakshmi Naidu", "age": 29,
         "village": "South Village", "phone": "+9190000000" + "14", "facility_id": ORG["VILLAGE_SOUTH"]},
        {"client_uuid": "demo-sync-0003", "name": "Om Prakash", "age": 47,
         "village": "North Village", "phone": "+9190000000" + "15", "facility_id": ORG["VILLAGE_NORTH"]},
    ]
    DEMO_SYNC_BATCH_PATH.write_text(json.dumps(batch, indent=2) + "\n")


def _print_uuid_table() -> None:
    print()
    print("=" * 78)
    print("DEMO DATASET -- FIXED UUIDs")
    print("=" * 78)
    print("\n-- Org Units --")
    for key, org_id in ORG.items():
        print(f"  {key:<16} {org_id}")
    print("\n-- Users --")
    for key, (user_id, full_name, mobile, role, *_rest) in USERS.items():
        print(f"  {key:<16} {user_id}  {full_name} ({role}, {mobile})")
    print(f"  {'PATIENT_LOGIN':<16} {PATIENT_USER_ID}  Demo Patient Account (PATIENT, {PATIENT_USER_MOBILE})")
    print("\n-- Patients --")
    for i, (patient_id, name, age, village_key) in enumerate(PATIENTS):
        mobile = f"+9190000000{i + 1:02d}"
        print(f"  patient {i + 1:02d}       {patient_id}  {name} ({mobile})")
    print("\n-- Triage Encounters --")
    for i, ((patient_idx, protocol, _v, _d), triage_id) in enumerate(zip(TRIAGE_CASES, TRIAGE_IDS)):
        print(f"  triage {i + 1}         {triage_id}  patient {patient_idx + 1:02d}, {protocol}")
    print("\n-- Referrals --")
    kinds = ["on_track (INITIATED)", "on_track (SLOT_BOOKED)", "BREACHED", "CLOSED", "REFUSED"]
    for i, (referral_id, kind) in enumerate(zip(REFERRAL_IDS, kinds)):
        print(f"  referral {i + 1}       {referral_id}  {kind}")
    print("\n" + "=" * 78)
    print(f"Demo sync batch staged at: {DEMO_SYNC_BATCH_PATH}")
    print("=" * 78)


def main() -> None:
    with engine.begin() as conn:
        _reset(conn)
        _seed_org_units(conn)
        actor_id = _seed_users(conn)
        _seed_patients(conn, actor_id)
        _seed_triage(conn, actor_id)
        _seed_referrals(conn, actor_id)

    # detect_breaches is async; run it in its own connection/session
    # after the main seed transaction commits, matching how the real
    # background job runs (its own session, not nested in another
    # transaction) -- sets a real breached_at + escalation_stage on
    # referral #3 rather than leaving it looking un-scanned.
    import asyncio
    from sqlmodel import Session
    with Session(engine) as session:
        asyncio.run(detect_breaches(session))

    _write_demo_sync_batch()
    _print_uuid_table()


if __name__ == "__main__":
    main()
