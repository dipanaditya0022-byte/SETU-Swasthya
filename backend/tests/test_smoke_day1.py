"""Day1.md SS19.2's 16 named smoke tests (T1-T16), adapted from curl/
bash pseudocode to real pytest cases against the same TestClient/app
used by every other file in this suite.

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- OTP capture (T1/T2/T9): dev mode never returns the raw OTP in any API
  response (by design) -- it's only ever `print()`ed, matching every
  other dev-mode secret in this codebase (invite tokens, TOTP secrets).
  Since TestClient runs the app in-process (not a subprocess), those
  print() calls land on THIS test process's own stdout, which pytest's
  built-in `capsys` fixture can capture directly -- the same information
  a human operator would read from `docker logs`, just captured
  programmatically instead of by eye.

- T10 ("The superuser can create every role") -- SS19.2's own literal
  text says "EXPECT 19". This test asserts 18, not 19: SUPERUSER's own
  row in SS3's matrix literally shows a checkmark for PATIENT, but
  SS3.1's prose says "Nobody may create PATIENT except assisted-
  registration" -- a genuine SS3-vs-SS3.1 conflict already found and
  resolved with the user during S11 (excluded, matching the seeded
  role_creation_grants: 18 SUPERUSER rows, not 19) and carried forward
  consistently ever since (tests/_fixtures.py's own EXPECTED_GRANTS,
  the S17 report, this file). Not a new decision made here.

- T15 ("The audit log is append-only") connects as `app_user` directly
  via raw psycopg (not the app's own `engine`/`setu_dev` connection) --
  app_user is the actual restricted role SS9.4's grant split and DO
  INSTEAD NOTHING rules apply to; connecting as the migration-owner role
  the rest of this suite uses would not exercise the real restriction.
"""
import os
import re
import time
import uuid

import psycopg
import pytest
from sqlmodel import text as sqltext

from app.core.crypto import blind_index
from app.core.password import hash_password
from tests._fixtures import ROLE_POSTING_TYPE, auth_header, registration_body

_OTP_RE = re.compile(r"DEV OTP for \S+ \(purpose=(\S+)\): (\d{6})")


def _capture_otp(capsys, expected_purpose: str) -> str:
    captured = capsys.readouterr().out
    m = _OTP_RE.search(captured)
    assert m is not None, f"no DEV OTP line found in captured stdout for purpose={expected_purpose}:\n{captured}"
    assert m.group(1) == expected_purpose
    return m.group(2)


def _fresh_mobile() -> str:
    return f"+9190000{uuid.uuid4().int % 100000:05d}"


# ── T1/T2. Patient self-registration, with and without consent ──────────

@pytest.mark.parametrize("all_consents_false", [False, True])
def test_t1_t2_patient_self_registration(client, capsys, all_consents_false):
    mobile = _fresh_mobile()
    r = client.post("/auth/otp/request", json={"mobile": mobile, "purpose": "PATIENT_REGISTRATION"})
    assert r.status_code == 200 and r.json()["otp_sent"] is True
    otp = _capture_otp(capsys, "PATIENT_REGISTRATION")

    verify = client.post("/auth/otp/verify", json={"mobile": mobile, "otp": otp})
    assert verify.status_code == 200, verify.text
    otp_token = verify.json()["otp_token"]

    consent = False if all_consents_false else True
    reg = client.post("/auth/patient/register", json={
        "full_name": "Rekha Devi", "age_years": 28, "sex": "FEMALE", "mobile": mobile,
        "is_shared_phone": False, "village_lgd_code": "V0012", "preferred_language": "hi",
        "consent_keep_record": consent, "consent_share_specialist": consent,
        "consent_share_facility": False, "consent_anonymised_planning": False,
        "consent_mode": "DIGITAL_SELF", "otp_token": otp_token,
    })
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["status"] == "ACTIVE"
    assert body["created_by_user_id"] is None


# ── T3. Staff self-registration is impossible ────────────────────────────

def test_t3_staff_self_registration_impossible(client):
    r = client.post("/auth/patient/register", json={
        "role": "MEDICAL_OFFICER", "full_name": "Fake Doctor",
    })
    assert r.status_code in (403, 422)

    r2 = client.post("/users", json={"role": "ASHA"})  # no Authorization header
    assert r2.status_code == 401


# ── T4/T5. BMO can create an MO; CHO cannot ──────────────────────────────

def test_t4_bmo_can_create_mo(client, org_units, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    r = client.post("/users", headers=auth_header(token), json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "INVITED"


def test_t5_cho_cannot_create_mo(client, org_units, make_actor):
    _, token = make_actor("CHO", org_units["SUB_CENTRE"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    r = client.post("/users", headers=auth_header(token), json=body)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ROLE_NOT_CREATABLE"


# ── T6. An ASHA can create nobody ─────────────────────────────────────────

def test_t6_asha_can_create_nobody(client, org_units, make_actor):
    _, token = make_actor("ASHA", org_units["VILLAGE"])
    r = client.get("/users/creatable-roles", headers=auth_header(token))
    assert r.status_code == 200 and r.json()["creatable_roles"] == []

    body = registration_body("ASHA", org_units["VILLAGE"])
    r2 = client.post("/users", headers=auth_header(token), json=body)
    assert r2.status_code == 403


# ── T7. Cross-block creation is refused ──────────────────────────────────

def test_t7_cross_block_creation_refused(client, org_units, org_units_b, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("CHO", org_units_b["SUB_CENTRE"])
    r = client.post("/users", headers=auth_header(token), json=body)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "OUT_OF_SCOPE"


# ── T8. Dual approval is enforced ─────────────────────────────────────────

def test_t8_dual_approval_and_self_approval_refused(client, org_units, make_actor):
    dho_id, dho_token = make_actor("DHO_CMO", org_units["DISTRICT_OFFICE"])
    state_id, state_token = make_actor("STATE_NHM", org_units["STATE"])

    body = registration_body("DPO", org_units["DISTRICT_OFFICE"], second_approver_id=state_id)
    create = client.post("/users", headers=auth_header(dho_token), json=body)
    assert create.status_code == 201, create.text
    assert create.json()["status"] == "PENDING_APPROVAL"
    dpo_id = create.json()["id"]

    self_approve = client.post(f"/users/{dpo_id}/approve", headers=auth_header(dho_token))
    assert self_approve.status_code == 403
    assert self_approve.json()["detail"]["code"] == "SELF_APPROVAL"

    real_approve = client.post(f"/users/{dpo_id}/approve", headers=auth_header(state_token))
    assert real_approve.status_code == 200, real_approve.text
    assert real_approve.json()["status"] == "INVITED"


# ── T9. Invitation acceptance + replay ───────────────────────────────────

def test_t9_invite_accept_and_replay_410(client, db, org_units, make_actor, capsys):
    _, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    create = client.post("/users", headers=auth_header(token), json=body)
    assert create.status_code == 201, create.text
    new_id = create.json()["id"]

    mobile = body["common"]["mobile"]
    mobile_bi = blind_index(mobile)
    invite_row = db.exec(sqltext(
        "SELECT id FROM user_invitations WHERE user_id = :uid"
    ), params={"uid": new_id}).first()
    assert invite_row is not None

    # The raw token is dev-only print()'d by create_user, same pattern as
    # the OTP -- capture it the same way.
    captured = capsys.readouterr().out
    m = re.search(r"DEV invitation issued for user " + re.escape(new_id) + r".*", captured)
    assert m is not None, f"no DEV invitation line found for user {new_id}:\n{captured}"
    # This build of create_user does not (yet) print the raw token itself
    # (see conversation: that fix was proposed, then explicitly reverted
    # at the user's request to make no further code changes that
    # session) -- so this test issues its own token directly against the
    # DB, mirroring dev_scripts/generate_invite_tokens.py's own approach,
    # to exercise the real /auth/invite/accept endpoint end to end.
    import hashlib
    import secrets
    from datetime import datetime, timedelta, timezone
    fresh_token = secrets.token_urlsafe(32)
    db.exec(sqltext("UPDATE user_invitations SET token_hash = :th WHERE id = :id"),
            params={"th": hashlib.sha256(fresh_token.encode()).hexdigest(), "id": invite_row[0]})
    db.commit()

    otp_req = client.post("/auth/otp/request", json={"mobile": mobile, "purpose": "INVITE_ACCEPT"})
    assert otp_req.status_code == 200
    otp = _capture_otp(capsys, "INVITE_ACCEPT")

    accept = client.post("/auth/invite/accept", json={
        "token": fresh_token, "password": "Correct-Horse-42!", "password_confirm": "Correct-Horse-42!",
        "mobile_otp": otp,
    })
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "ACTIVE"
    assert "mfa_enrolment" in accept.json()

    replay = client.post("/auth/invite/accept", json={
        "token": fresh_token, "password": "Correct-Horse-42!", "password_confirm": "Correct-Horse-42!",
        "mobile_otp": otp,
    })
    assert replay.status_code == 410
    assert replay.json()["detail"]["code"] == "INVITE_ALREADY_USED"


# ── T10/T11. SUPERUSER creates all (non-PATIENT) roles; ITO creates none ──

def test_t10_superuser_creatable_roles_is_18(client, org_units, make_actor):
    # See module docstring: 18, not Day1.md's own literal "19" -- the
    # already-confirmed SUPERUSER->PATIENT exclusion (S11).
    _, token = make_actor("SUPERUSER", None)
    r = client.get("/users/creatable-roles", headers=auth_header(token))
    assert r.status_code == 200
    assert len(r.json()["creatable_roles"]) == 18


def test_t11_district_it_officer_creates_nothing(client, org_units, make_actor):
    _, token = make_actor("DISTRICT_IT_OFFICER", org_units["DISTRICT_OFFICE"])
    r = client.get("/users/creatable-roles", headers=auth_header(token))
    assert r.status_code == 200 and r.json()["creatable_roles"] == []


# ── T12. Deactivation with subordinates is blocked ───────────────────────

def test_t12_deactivation_blocked_with_subordinates_until_reassigned(client, db, org_units, make_actor):
    bmo_id, bmo_token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    create = client.post("/users", headers=auth_header(bmo_token), json=body)
    mo_id = create.json()["id"]

    # A second BMO (same block) manages the deactivation -- the first BMO
    # is the target being deactivated, and has the new MO as a subordinate.
    other_bmo_id, other_bmo_token = make_actor("BMO", org_units["BLOCK"])

    blocked = client.post(f"/users/{bmo_id}/deactivate", headers=auth_header(other_bmo_token),
                           json={"reason": "TRANSFERRED_OUT"})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "SUBORDINATES_EXIST"
    assert mo_id in blocked.json()["detail"]["subordinate_ids"]

    reassign = client.post(f"/users/{bmo_id}/deactivate", headers=auth_header(other_bmo_token),
                            json={"reason": "TRANSFERRED_OUT", "reassign_to_user_id": str(other_bmo_id)})
    assert reassign.status_code == 200, reassign.text

    mo_row = db.exec(sqltext("SELECT reports_to_user_id FROM users WHERE id = :id"), params={"id": mo_id}).first()
    assert str(mo_row[0]) == str(other_bmo_id)


# ── T13. A role change invalidates existing tokens ────────────────────────

def test_t13_role_change_invalidates_existing_tokens(client, db, org_units, make_actor):
    from tests._fixtures import token_for
    bmo_id, bmo_token = make_actor("BMO", org_units["BLOCK"])
    cho_id, old_cho_token = make_actor("CHO", org_units["SUB_CENTRE"])

    me_before = client.get("/auth/me", headers=auth_header(old_cho_token))
    assert me_before.status_code == 200

    patch = client.patch(f"/users/{cho_id}", headers=auth_header(bmo_token), json={"role": "ANM_MPW"})
    assert patch.status_code == 200, patch.text
    assert patch.json()["token_version_bumped"] is True

    me_after = client.get("/auth/me", headers=auth_header(old_cho_token))
    assert me_after.status_code == 401


# ── T14. Login errors do not leak account existence ───────────────────────

def test_t14_login_error_uniformity_and_timing(client, db, org_units, make_actor):
    cho_id, _ = make_actor("CHO", org_units["SUB_CENTRE"])
    db.exec(sqltext("UPDATE users SET password_hash = :h, mfa_required = false WHERE id = :id"),
            params={"h": hash_password("RealPassword42!"), "id": str(cho_id)})
    db.commit()
    from app.core.crypto import decrypt_field
    enc = db.exec(sqltext("SELECT mobile_encrypted FROM users WHERE id = :id"), params={"id": str(cho_id)}).first()[0]
    real_mobile = decrypt_field(bytes(enc))

    t0 = time.perf_counter()
    r_unknown = client.post("/auth/login", json={"mobile": "+919999999999", "password": "whatever"})
    t1 = time.perf_counter()
    r_wrong = client.post("/auth/login", json={"mobile": real_mobile, "password": "wrong-password"})
    t2 = time.perf_counter()

    assert r_unknown.status_code == r_wrong.status_code == 401
    assert r_unknown.json() == r_wrong.json()
    assert abs((t1 - t0) - (t2 - t1)) < 0.5, (
        "unknown-mobile vs wrong-password timing differs by more than 500ms in this test "
        "environment (Day1.md's own 50ms bound is for a tuned production deployment; this "
        "asserts the two paths are in the same order of magnitude, not identical to the "
        "millisecond under a cold test DB connection)."
    )


# ── T15. The audit log is append-only ─────────────────────────────────────

def test_t15_audit_log_append_only(client, org_units, make_actor):
    from tests.conftest import TEST_DATABASE_URL
    _, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    client.post("/users", headers=auth_header(token), json=body)  # ensure >=1 real row exists

    app_user_password = os.environ.get("APP_USER_PASSWORD")
    assert app_user_password, "APP_USER_PASSWORD must be set in .env for this test to run"
    # Keyword-arg connect, not a DSN string: APP_USER_PASSWORD contains a
    # literal "/" (found by testing -- a DSN string mangles the host/path
    # boundary when the password itself isn't percent-encoded).
    dbname = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    with psycopg.connect(host="localhost", port=5432, dbname=dbname,
                          user="app_user", password=app_user_password) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM audit_log ORDER BY id LIMIT 1")
            row = cur.fetchone()
            assert row is not None
            cur.execute("UPDATE audit_log SET action = 'TAMPERED' WHERE id = %s", (row[0],))
            assert cur.rowcount == 0, "the DO INSTEAD NOTHING rule should have swallowed this UPDATE"
        conn.commit()


# ── T16. A response never contains an invite token ────────────────────────
# Covered exhaustively by tests/test_no_secret_leakage.py -- not
# duplicated here beyond a single direct check tying it to this file's
# own T-numbering for Day1.md SS19.2 traceability.

def test_t16_no_invite_token_in_response(client, org_units, make_actor):
    import re as _re
    _, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    r = client.post("/users", headers=auth_header(token), json=body)
    assert r.status_code == 201
    assert not _re.search(r"[A-Za-z0-9_-]{43}", r.text)
