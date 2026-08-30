"""Shared, non-pytest fixture helpers for the Day 1 test suite (S21):
the org-unit hierarchy design, actor creation, and per-role valid
POST /users payload builders. Kept separate from conftest.py so the
data/logic is easy to audit independently of pytest wiring.

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- EXPECTED_GRANTS (the 65-pair allowed set) is transcribed directly
  from Day1.md SS3's own literal 19x19 matrix table, cell by cell --
  not from the seeded role_creation_grants table (that would make the
  test validate the seed against itself, proving nothing). SUPERUSER
  -> PATIENT is the one cell EXCLUDED here despite the literal table
  showing a checkmark: SS3's own table and SS3.1's prose ("Nobody may
  create PATIENT except assisted-registration") conflict on this exact
  cell, already found and resolved with the user during S11 (excluded,
  matching the already-seeded 65-row grant table) -- this file carries
  that same, already-confirmed resolution forward rather than
  re-litigating it. test_creation_matrix.py's own first assertion
  checks EXPECTED_GRANTS against the live role_creation_grants table,
  so a drift between the transcription here and the seed would be
  caught immediately, not silently passed.

- THE ORG-UNIT HIERARCHY. Confirmed with the user directly in this
  session (2026-08-30): DISTRICT_OFFICE is nested ABOVE BLOCK/PHC/
  SDH/DISTRICT_HOSPITAL/TELE_HUB/etc, not as their geographic sibling
  under DISTRICT (Day1.md SS4.1's own diagram draws it as a sibling --
  a real, previously-flagged gap that left DHO_CMO unable to reach 9 of
  its own 14 creation grants under literal scope containment). This
  fixture hierarchy resolves that for real, not just for tests -- it
  is the shape org_units should actually have, giving DHO_CMO the
  "District subtree" reach SS1's own role table already promises:

    STATE
     `-- DISTRICT
          `-- DISTRICT_OFFICE
               |-- BLOCK
               |    |-- PHC
               |    |    `-- SUB_CENTRE
               |    |         `-- VILLAGE
               |    |-- CHC
               |    `-- HWC
               |-- SDH
               |-- DISTRICT_HOSPITAL
               `-- TELE_HUB

  Verified by hand against all 65 grant rows' own allowed_org_unit_types
  (queried live from role_creation_grants) before writing this: every
  creator role's own posting type sits at a point in this tree from
  which every one of its own targets' allowed types is reachable
  (either the creator's own unit, when its type is itself in the
  target's allowed set, or a genuine descendant of it).

- Actors are created by direct INSERT (status=ACTIVE, mfa_enrolled=true
  when mfa_required=true), and tokens are minted directly via
  app.core.tokens.issue_access_token rather than a real password+MFA
  login -- a deliberate performance/determinism choice for the 361-case
  matrix specifically (confirmed as reasonable in this session's own
  established testing pattern). This is safe because
  get_current_active_user (app/core/authz.py) only ever trusts the
  token's `sub` and `ver` claims -- every other field (status, role,
  scope, mfa flags) is re-read fresh from the database on every
  request, never taken from the token. Full end-to-end password+MFA
  login IS separately exercised by test_smoke_day1.py and
  test_auth_security.py -- this shortcut is not a substitute for that
  coverage, only for the matrix's own sheer volume.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, text

from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.core.tokens import issue_access_token
from app.models.enums import ROLE_LEVEL, RoleCode

# ============================================================
# The 65-pair grant matrix -- Day1.md SS3's own table, transcribed
# verbatim, cell by cell. See module docstring for the SUPERUSER ->
# PATIENT exclusion.
# ============================================================

ALL_ROLES: list[str] = [r.value for r in RoleCode]  # all 19, PATIENT included

EXPECTED_GRANTS: set[tuple[str, str]] = {
    # SUPERUSER -- every role except PATIENT (SS3 vs SS3.1 conflict,
    # resolved in S11, carried forward here -- see module docstring).
    *((("SUPERUSER", t) for t in ALL_ROLES if t != "PATIENT")),
    # STATE_NHM -- 11
    ("STATE_NHM", "STATE_NHM"), ("STATE_NHM", "COLLECTOR"), ("STATE_NHM", "DHO_CMO"),
    ("STATE_NHM", "DISTRICT_EPIDEMIOLOGIST"), ("STATE_NHM", "HEALTH_ADMIN_DPM"),
    ("STATE_NHM", "PROGRAMME_OFFICER"), ("STATE_NHM", "DISTRICT_IT_OFFICER"),
    ("STATE_NHM", "DPO"), ("STATE_NHM", "SPECIALIST"), ("STATE_NHM", "BMO"),
    ("STATE_NHM", "MEDICAL_OFFICER"),
    # COLLECTOR -- 5
    ("COLLECTOR", "DHO_CMO"), ("COLLECTOR", "HEALTH_ADMIN_DPM"),
    ("COLLECTOR", "DISTRICT_IT_OFFICER"), ("COLLECTOR", "BMO"), ("COLLECTOR", "VHSNC_MEMBER"),
    # DHO_CMO -- 14
    ("DHO_CMO", "DISTRICT_EPIDEMIOLOGIST"), ("DHO_CMO", "HEALTH_ADMIN_DPM"),
    ("DHO_CMO", "PROGRAMME_OFFICER"), ("DHO_CMO", "DISTRICT_IT_OFFICER"),
    ("DHO_CMO", "DPO"), ("DHO_CMO", "SPECIALIST"), ("DHO_CMO", "BMO"),
    ("DHO_CMO", "MEDICAL_OFFICER"), ("DHO_CMO", "CHO"), ("DHO_CMO", "ANM_MPW"),
    ("DHO_CMO", "LAB_TECHNICIAN"), ("DHO_CMO", "PHARMACIST"), ("DHO_CMO", "ASHA"),
    ("DHO_CMO", "VHSNC_MEMBER"),
    # HEALTH_ADMIN_DPM -- 2
    ("HEALTH_ADMIN_DPM", "LAB_TECHNICIAN"), ("HEALTH_ADMIN_DPM", "PHARMACIST"),
    # BMO -- 7
    ("BMO", "MEDICAL_OFFICER"), ("BMO", "CHO"), ("BMO", "ANM_MPW"),
    ("BMO", "LAB_TECHNICIAN"), ("BMO", "PHARMACIST"), ("BMO", "ASHA"), ("BMO", "VHSNC_MEMBER"),
    # MEDICAL_OFFICER -- 5
    ("MEDICAL_OFFICER", "CHO"), ("MEDICAL_OFFICER", "ANM_MPW"),
    ("MEDICAL_OFFICER", "LAB_TECHNICIAN"), ("MEDICAL_OFFICER", "PHARMACIST"),
    ("MEDICAL_OFFICER", "ASHA"),
    # CHO -- 2
    ("CHO", "ANM_MPW"), ("CHO", "ASHA"),
    # ANM_MPW -- 1
    ("ANM_MPW", "ASHA"),
}
assert len(EXPECTED_GRANTS) == 65, f"expected 65 grant pairs, got {len(EXPECTED_GRANTS)}"

# ============================================================
# Org-unit hierarchy -- see module docstring for the shape and the
# DHO_CMO nesting fix.
# ============================================================

# (unit_type, name, parent_key) -- parent_key indexes into the dict as
# it's built, None for the root.
_HIERARCHY_SPEC: list[tuple[str, str, str | None]] = [
    ("STATE", "Test State", None),
    ("DISTRICT", "Test District", "STATE"),
    ("DISTRICT_OFFICE", "Test District Office", "DISTRICT"),
    ("BLOCK", "Test Block", "DISTRICT_OFFICE"),
    ("PHC", "Test PHC", "BLOCK"),
    ("SUB_CENTRE", "Test Sub-Centre", "PHC"),
    ("VILLAGE", "Test Village", "SUB_CENTRE"),
    ("CHC", "Test CHC", "BLOCK"),
    ("HWC", "Test HWC", "BLOCK"),
    ("SDH", "Test SDH", "DISTRICT_OFFICE"),
    ("DISTRICT_HOSPITAL", "Test District Hospital", "DISTRICT_OFFICE"),
    ("TELE_HUB", "Test Tele Hub", "DISTRICT_OFFICE"),
]


def build_org_hierarchy(session: Session) -> dict[str, uuid.UUID]:
    """Creates one org_unit of each of the 12 OrgUnitType values, nested
    per module docstring. Returns {unit_type: id}. Each type is unique
    in this tree, so callers can look up "the PHC" etc. unambiguously."""
    ids: dict[str, uuid.UUID] = {}
    for unit_type, name, parent_key in _HIERARCHY_SPEC:
        parent_id = ids[parent_key] if parent_key else None
        row = session.exec(text(
            "INSERT INTO org_units (unit_type, name, parent_id) VALUES (:t, :n, :p) RETURNING id"
        ), params={"t": unit_type, "n": name, "p": str(parent_id) if parent_id else None}).first()
        ids[unit_type] = row[0]
    return ids


def build_second_org_tree(session: Session) -> dict[str, uuid.UUID]:
    """A second, entirely separate DISTRICT subtree (own DISTRICT_OFFICE/
    BLOCK/PHC/SUB_CENTRE/VILLAGE), for cross-scope negative tests (T7:
    a Block-A BMO must not be able to create staff in Block B)."""
    spec: list[tuple[str, str, str | None]] = [
        ("DISTRICT", "Test District B", None),
        ("DISTRICT_OFFICE", "Test District Office B", "DISTRICT"),
        ("BLOCK", "Test Block B", "DISTRICT_OFFICE"),
        ("PHC", "Test PHC B", "BLOCK"),
        ("SUB_CENTRE", "Test Sub-Centre B", "PHC"),
        ("VILLAGE", "Test Village B", "SUB_CENTRE"),
    ]
    ids: dict[str, uuid.UUID] = {}
    for unit_type, name, parent_key in spec:
        parent_id = ids[parent_key] if parent_key else None
        row = session.exec(text(
            "INSERT INTO org_units (unit_type, name, parent_id) VALUES (:t, :n, :p) RETURNING id"
        ), params={"t": unit_type, "n": name, "p": str(parent_id) if parent_id else None}).first()
        ids[unit_type] = row[0]
    return ids


def _get_path(session: Session, org_unit_id: uuid.UUID) -> str:
    row = session.exec(text("SELECT path FROM org_units WHERE id = :id"), params={"id": str(org_unit_id)}).first()
    return row[0]


def _within(target_path: str, actor_path: str) -> bool:
    """Same logic as app.core.authz.org_unit_is_within_scope, used here
    only to pick a reachable target unit for fixture construction -- not
    a re-implementation the app itself relies on."""
    return target_path == actor_path or target_path.startswith(actor_path.rstrip("/") + "/")


def pick_target_org_unit(
    session: Session, units: dict[str, uuid.UUID], actor_org_unit_id: uuid.UUID,
    allowed_types: list[str],
) -> uuid.UUID:
    """Given the actor's own org unit and a grant's allowed_org_unit_types,
    return a real org_unit_id of an allowed type that sits within the
    actor's own scope (preferring the actor's own unit when its type is
    itself allowed). `allowed_types == ["*"]` (SUPERUSER's self-grant)
    returns the actor's own unit unconditionally."""
    if allowed_types == ["*"]:
        return actor_org_unit_id
    actor_path = _get_path(session, actor_org_unit_id)
    actor_type_row = session.exec(text("SELECT unit_type FROM org_units WHERE id = :id"),
                                   params={"id": str(actor_org_unit_id)}).first()
    actor_type = actor_type_row[0] if actor_type_row else None
    if actor_type in allowed_types:
        return actor_org_unit_id
    for t in allowed_types:
        candidate = units.get(t)
        if candidate is None:
            continue
        if _within(_get_path(session, candidate), actor_path):
            return candidate
    raise AssertionError(
        f"No reachable org unit of types {allowed_types} within actor's own unit "
        f"(type={actor_type}, path={actor_path}) -- hierarchy fixture is incomplete."
    )


# ============================================================
# Actor creation.
# ============================================================

def make_active_actor(
    session: Session, *, role: str, org_unit_id: uuid.UUID | None, mobile: str,
    full_name: str = "Test Actor", created_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Creates an ACTIVE, real users row for `role`, posted at
    `org_unit_id` (None only valid for SUPERUSER, per chk_scope_required).
    MFA is force-enrolled whenever the role requires it (role_level<=5,
    chk_privileged_mfa), so the actor can itself pass Gate 1 when
    creating others.

    `created_by_user_id` must be a real users.id (chk_creator_required
    is a genuine FK, not just a NOT NULL check) for every role except
    SUPERUSER/PATIENT -- see conftest.py's `root_superuser` fixture,
    which every other test actor is created under."""
    level = ROLE_LEVEL[RoleCode(role)]
    mfa_required = level <= 5 or role == "SUPERUSER"
    if role not in ("SUPERUSER", "PATIENT") and created_by_user_id is None:
        raise AssertionError(f"created_by_user_id is required for role={role} (chk_creator_required)")
    mobile_bi = blind_index(mobile)
    row = session.exec(text(
        "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
        "mobile_masked, status, scope_org_unit_id, scope_path, created_by_user_id, "
        "mfa_required, mfa_enrolled, expires_at) "
        "VALUES (:role, :lvl, :fn, :menc, :mbi, :mmask, 'ACTIVE', :org, "
        "(SELECT path FROM org_units WHERE id = :org), :creator, :mfareq, :mfaenr, :exp) "
        "RETURNING id"
    ), params={
        "role": role, "lvl": level, "fn": full_name, "menc": encrypt_field(mobile),
        "mbi": mobile_bi, "mmask": mask_mobile(mobile),
        "org": str(org_unit_id) if org_unit_id else None,
        "creator": str(created_by_user_id) if created_by_user_id else None,
        "mfareq": mfa_required, "mfaenr": mfa_required,
        "exp": (datetime.now(timezone.utc) + timedelta(days=90)) if role == "SUPERUSER" else None,
    }).first()
    return row[0]


def token_for(user_id: uuid.UUID, role: str) -> str:
    """Mints an access token directly (see module docstring for why this
    is safe for matrix-scale testing)."""
    return issue_access_token(
        user_id=str(user_id), role=role, level=ROLE_LEVEL[RoleCode(role)],
        scope_org_id=None, scope_path=None, perms_hash="test",
        session_id=str(uuid.uuid4()), token_version=1, amr=["pwd", "totp"],
    )


# ============================================================
# Per-role posting-type preference -- which allowed_org_unit_types entry
# to use when CREATING an actor of this role (i.e. what type of unit
# this role itself gets posted at). Matches the allowed_org_unit_types
# already queried from role_creation_grants for whoever creates this
# role (all consistent across creators for a given target role).
# ============================================================

ROLE_POSTING_TYPE: dict[str, str | None] = {
    "SUPERUSER": None,
    "STATE_NHM": "STATE",
    "COLLECTOR": "DISTRICT",
    "DHO_CMO": "DISTRICT_OFFICE",
    "DISTRICT_EPIDEMIOLOGIST": "DISTRICT_OFFICE",
    "HEALTH_ADMIN_DPM": "DISTRICT_OFFICE",
    "PROGRAMME_OFFICER": "DISTRICT_OFFICE",
    "DISTRICT_IT_OFFICER": "DISTRICT_OFFICE",
    "DPO": "DISTRICT_OFFICE",
    "SPECIALIST": "TELE_HUB",
    "BMO": "BLOCK",
    "MEDICAL_OFFICER": "PHC",
    "CHO": "SUB_CENTRE",
    "ANM_MPW": "SUB_CENTRE",
    "LAB_TECHNICIAN": "PHC",
    "PHARMACIST": "PHC",
    "ASHA": "VILLAGE",
    "VHSNC_MEMBER": "VILLAGE",
    "PATIENT": None,
}


# ============================================================
# Common/posting/profile payload builders -- one per staff role,
# mirroring app/schemas/profiles.py's own field requirements exactly
# (S14). PATIENT is excluded (self-registration only, separate endpoint).
# ============================================================

_MOBILE_COUNTER = [7000000000]


def _next_mobile() -> str:
    _MOBILE_COUNTER[0] += 1
    return f"+91{_MOBILE_COUNTER[0]}"


def _future_date(days: int = 365 * 3) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _past_date(days: int = 30) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def common_block(role: str, mobile: str | None = None) -> dict[str, Any]:
    level = ROLE_LEVEL[RoleCode(role)]
    c: dict[str, Any] = {
        "full_name": "Test Person", "mobile": mobile or _next_mobile(),
        "date_of_birth": "1990-01-01", "sex": "FEMALE", "preferred_language": "en",
        "designation": "Test posting", "joining_date": _past_date(),
        "id_proof_type": "PAN", "id_proof_last4": "1234",
    }
    if level <= 5:
        c["email"] = f"test.{uuid.uuid4().hex[:8]}@example.com"
    if level <= 6:
        c["employee_code"] = f"EMP-{uuid.uuid4().hex[:8].upper()}"
    return c


def posting_block(role: str, org_unit_id: uuid.UUID) -> dict[str, Any]:
    level = ROLE_LEVEL[RoleCode(role)]
    p: dict[str, Any] = {"org_unit_id": str(org_unit_id)}
    if level <= 5:
        p["posting_order_ref"] = f"ORD/2026/{uuid.uuid4().hex[:6]}"
        p["posting_order_date"] = _past_date()
    return p


def profile_block(role: str, org_unit_id: uuid.UUID, second_approver_id: uuid.UUID | None = None) -> dict[str, Any]:
    org = str(org_unit_id)
    unique = uuid.uuid4().hex[:8].upper()
    if role == "ASHA":
        return {
            "asha_state_code": f"UP-ASHA-{unique}", "village_lgd_codes": ["V0001"],
            "sub_centre_org_unit_id": org, "population_covered": 1000,
            "education_level": "CLASS_10", "induction_training_completed": True,
            "works_offline_primarily": True,
        }
    if role == "ANM_MPW":
        return {
            "council_registration_number": f"CRN-ANM-{unique}", "council_name": "UP Nurses and Midwives Council",
            "council_registration_expiry": _future_date(), "qualification": "ANM",
            "sub_centre_org_unit_id": org, "village_lgd_codes": ["V0001"],
            "is_immunisation_certified": True,
        }
    if role == "CHO":
        return {
            "hpr_id": f"HPR-CHO-{unique}", "cch_certificate_number": f"CCH-{unique}",
            "council_registration_number": f"CRN-CHO-{unique}", "council_registration_expiry": _future_date(),
            "base_qualification": "BSC_NURSING", "hwc_org_unit_id": org,
            "teleconsult_enabled": True, "dispensing_scope": ["BASIC"],
        }
    if role == "MEDICAL_OFFICER":
        return {
            "hpr_id": f"HPR-MO-{unique}", "medical_council_registration_number": f"MCR-MO-{unique}",
            "medical_council_name": "UP Medical Council", "registration_expiry": _future_date(),
            "qualification": "MBBS", "qualification_year": 2015, "facility_org_unit_id": org,
            "is_moic": False, "prescribing_scope": ["OPD"], "telemedicine_certified": False,
        }
    if role == "SPECIALIST":
        return {
            "hpr_id": f"HPR-SPEC-{unique}", "medical_council_registration_number": f"MCR-SPEC-{unique}",
            "registration_expiry": _future_date(), "specialty": "MEDICINE", "pg_qualification": "MD",
            "tele_hub_org_unit_id": org, "telemedicine_certified": True,
            "languages_spoken": ["en"], "roster_days": ["MON", "TUE"],
            "roster_start_time": "09:00:00", "roster_end_time": "17:00:00",
            "max_queue_length": 10, "accepts_store_and_forward": True,
        }
    if role == "LAB_TECHNICIAN":
        return {
            "qualification": "DMLT", "facility_org_unit_id": org, "lab_code": f"LAB-{unique}",
            "authorised_test_categories": ["HAEMATOLOGY"], "can_release_results": True,
        }
    if role == "PHARMACIST":
        return {
            "pharmacy_council_registration_number": f"PCR-{unique}", "council_registration_expiry": _future_date(),
            "qualification": "D_PHARM", "facility_org_unit_id": org,
            "can_dispense_schedule_h": True, "can_manage_stock": True,
            "can_raise_indent": True, "cold_chain_trained": True,
        }
    if role == "BMO":
        return {
            "hpr_id": f"HPR-BMO-{unique}", "medical_council_registration_number": f"MCR-BMO-{unique}",
            "registration_expiry": _future_date(), "block_org_unit_id": org,
            "facilities_supervised": [org], "escalation_contact_priority": 1,
        }
    if role == "DHO_CMO":
        return {
            "hpr_id": f"HPR-DHO-{unique}", "medical_council_registration_number": f"MCR-DHO-{unique}",
            "registration_expiry": _future_date(), "qualification": "MBBS",
            "district_org_unit_id": org, "appointment_order_ref": f"ORD/DHO/{unique}",
            "is_clinical_governance_chair": True, "can_approve_l3_accounts": True,
        }
    if role == "DISTRICT_EPIDEMIOLOGIST":
        return {
            "qualification": "MPH", "district_org_unit_id": org,
            "analytics_scope": ["SURVEILLANCE"], "deidentified_access_only": True,
        }
    if role == "HEALTH_ADMIN_DPM":
        return {
            "qualification": "MHA", "district_org_unit_id": org,
            "functional_areas": ["LOGISTICS"], "can_approve_indent": True,
        }
    if role == "PROGRAMME_OFFICER":
        return {
            "programme": "RCH", "district_org_unit_id": org,
            "can_approve_protocol_changes": False,
        }
    if role == "DISTRICT_IT_OFFICER":
        return {
            "district_org_unit_id": org, "technical_scope": ["DEVICES"],
            "can_manage_devices": True, "can_view_sync_health": True,
        }
    if role == "DPO":
        return {
            "scope_level": "DISTRICT", "scope_org_unit_id": org,
            "appointment_order_ref": f"ORD/DPO/{unique}",
            "published_contact_email": f"dpo.{unique}@example.com",
            "published_contact_phone": _next_mobile(),
            "second_approver_user_id": str(second_approver_id) if second_approver_id else str(uuid.uuid4()),
        }
    if role == "COLLECTOR":
        return {
            "service_type": "IAS", "district_org_unit_id": org, "tenure_start": _past_date(),
        }
    if role == "STATE_NHM":
        return {
            "state_code": "UP", "directorate_designation": "Test Directorate",
            "can_approve_l2_l3_accounts": True,
        }
    if role == "VHSNC_MEMBER":
        return {
            "village_lgd_code": "V0001", "panchayat_name": "Test Panchayat", "position": "MEMBER",
            "term_start": _past_date(), "term_end": _future_date(days=365),
        }
    if role == "SUPERUSER":
        return {
            "full_name": "Test Superuser Peer", "email": f"su.{unique}@example.com",
            "mobile": _next_mobile(), "justification": "Test-only dual-approved peer superuser creation " * 2,
            "second_approver_user_id": str(second_approver_id) if second_approver_id else str(uuid.uuid4()),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
        }
    raise AssertionError(f"no profile builder for role {role!r}")


def registration_body(role: str, org_unit_id: uuid.UUID, mobile: str | None = None,
                       second_approver_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "role": role,
        "common": common_block(role, mobile=mobile),
        "posting": posting_block(role, org_unit_id),
        "profile": profile_block(role, org_unit_id, second_approver_id=second_approver_id),
    }


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
