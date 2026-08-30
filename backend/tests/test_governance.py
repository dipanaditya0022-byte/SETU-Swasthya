"""GET /audit, GET/POST /consents/{patient_id}[/revoke], POST
/system/break-glass -- the four Day1.md SS14.3 endpoints found missing
and implemented in S22 (see app/api/routes/governance.py's own module
docstring for the full "found missing, confirmed with the user, then
built" account).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import text as sqltext

from tests._fixtures import auth_header, registration_body


def _make_patient(db, full_name="Test Patient") -> str:
    from app.core.crypto import blind_index, encrypt_field, mask_mobile
    mobile = f"+9190001{uuid.uuid4().int % 100000:05d}"
    row = db.exec(sqltext(
        "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
        "mobile_masked, status, mfa_required, profile) "
        "VALUES ('PATIENT', 99, :fn, :menc, :mbi, :mmask, 'ACTIVE', false, '{}'::jsonb) RETURNING id"
    ), params={"fn": full_name, "menc": encrypt_field(mobile), "mbi": blind_index(mobile), "mmask": mask_mobile(mobile)}).first()
    db.exec(sqltext(
        "INSERT INTO consents (patient_user_id, keep_record, share_specialist, share_facility, "
        "anonymised_planning, mode, language) VALUES (:pid, true, true, false, false, 'DIGITAL_SELF', 'en')"
    ), params={"pid": row[0]})
    db.commit()
    return str(row[0])


# ── GET /audit ────────────────────────────────────────────────────────────

def test_audit_read_requires_permission(client, org_units, make_actor):
    _, bmo_token = make_actor("BMO", org_units["BLOCK"])
    r = client.get("/audit", headers=auth_header(bmo_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_audit_read_allowed_for_dpo(client, db, org_units, make_actor):
    _, bmo_token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    client.post("/users", headers=auth_header(bmo_token), json=body)  # generates a real audit row

    _, dpo_token = make_actor("DPO", org_units["DISTRICT_OFFICE"])
    r = client.get("/audit", headers=auth_header(dpo_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["entries"]) >= 1
    entry = body["entries"][0]
    assert "row_hash" in entry and "action" in entry and "occurred_at" in entry


def test_audit_read_filters_by_action(client, org_units, make_actor):
    _, bmo_token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    client.post("/users", headers=auth_header(bmo_token), json=body)

    _, superuser_token = make_actor("SUPERUSER", None)
    r = client.get("/audit?action=USER_CREATED", headers=auth_header(superuser_token))
    assert r.status_code == 200
    assert all(e["action"] == "USER_CREATED" for e in r.json()["entries"])


# ── GET /consents/{patient_id} ───────────────────────────────────────────

def test_consents_dpo_can_read_any_patient(client, db, org_units, make_actor):
    patient_id = _make_patient(db)
    _, dpo_token = make_actor("DPO", org_units["DISTRICT_OFFICE"])
    r = client.get(f"/consents/{patient_id}", headers=auth_header(dpo_token))
    assert r.status_code == 200, r.text
    assert len(r.json()["consents"]) == 1
    assert r.json()["consents"][0]["active"] is True


def test_consents_patient_can_read_own(client, db):
    patient_id = _make_patient(db)
    from tests._fixtures import token_for
    token = token_for(patient_id, "PATIENT")
    r = client.get(f"/consents/{patient_id}", headers=auth_header(token))
    assert r.status_code == 200, r.text


def test_consents_patient_cannot_read_another_patients(client, db):
    patient_id = _make_patient(db, full_name="Owner")
    other_patient_id = _make_patient(db, full_name="Snooper")
    from tests._fixtures import token_for
    token = token_for(other_patient_id, "PATIENT")
    r = client.get(f"/consents/{patient_id}", headers=auth_header(token))
    assert r.status_code == 404


def test_consents_read_requires_permission(client, org_units, make_actor):
    patient_id = str(uuid.uuid4())
    _, bmo_token = make_actor("BMO", org_units["BLOCK"])
    r = client.get(f"/consents/{patient_id}", headers=auth_header(bmo_token))
    assert r.status_code == 403


def test_consents_nonexistent_patient_404(client, org_units, make_actor):
    _, dpo_token = make_actor("DPO", org_units["DISTRICT_OFFICE"])
    r = client.get(f"/consents/{uuid.uuid4()}", headers=auth_header(dpo_token))
    assert r.status_code == 404


# ── POST /consents/{patient_id}/revoke ───────────────────────────────────

def test_revoke_consent_supersedes_and_creates_all_false_row(client, db, org_units, make_actor):
    patient_id = _make_patient(db)
    _, dpo_token = make_actor("DPO", org_units["DISTRICT_OFFICE"])

    r = client.post(f"/consents/{patient_id}/revoke", headers=auth_header(dpo_token), json={"reason": "patient request"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["keep_record"] is False and body["share_specialist"] is False

    rows = db.exec(sqltext(
        "SELECT keep_record, superseded_at FROM consents WHERE patient_user_id = :pid ORDER BY recorded_at"
    ), params={"pid": patient_id}).all()
    assert len(rows) == 2
    assert rows[0][1] is not None  # original row now superseded
    assert rows[1][0] is False and rows[1][1] is None  # new row active, all false


def test_revoke_consent_patient_cannot_revoke_others(client, db):
    patient_id = _make_patient(db, full_name="Owner")
    other_patient_id = _make_patient(db, full_name="Snooper")
    from tests._fixtures import token_for
    token = token_for(other_patient_id, "PATIENT")
    r = client.post(f"/consents/{patient_id}/revoke", headers=auth_header(token), json={})
    assert r.status_code == 404


# ── POST /system/break-glass ──────────────────────────────────────────────

def test_break_glass_requires_permission(client, org_units, make_actor):
    _, dpo_token = make_actor("DPO", org_units["DISTRICT_OFFICE"])  # DPO does NOT hold system:break_glass
    r = client.post("/system/break-glass", headers=auth_header(dpo_token),
                     json={"justification": "x" * 60})
    assert r.status_code == 403


def test_break_glass_justification_too_short_422(client, org_units, make_actor):
    _, su_token = make_actor("SUPERUSER", None)
    r = client.post("/system/break-glass", headers=auth_header(su_token), json={"justification": "too short"})
    assert r.status_code == 422


def test_break_glass_activation(client, db, org_units, make_actor):
    su_id, su_token = make_actor("SUPERUSER", None)
    justification = "Emergency access needed to verify a suspected data integrity issue in district records."
    assert len(justification) >= 50
    r = client.post("/system/break-glass", headers=auth_header(su_token), json={"justification": justification})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dpo_notified"] is True

    row = db.exec(sqltext(
        "SELECT justification, dpo_notified_at, expires_at, started_at FROM break_glass_sessions WHERE id = :id"
    ), params={"id": body["id"]}).first()
    assert row is not None
    assert row[1] is not None  # dpo_notified_at set
    expires_at = row[2]
    started_at = row[3]
    delta = expires_at - started_at
    assert timedelta(minutes=59) <= delta <= timedelta(minutes=61)
