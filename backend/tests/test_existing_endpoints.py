"""The nine original, contract-frozen Day 1 endpoints (backend/docs/
API_CONTRACT.md) -- formalizes as pytest the same 24 manual test cases
already run live against a real server during S20's own implementation,
now with RBAC applied (Day1.md SS14.1). Payload fields and response
shapes must remain exactly as documented; only additive authorization
was layered on top (S20).
"""
import uuid

from sqlmodel import text as sqltext

from app.core.password import hash_password
from tests._fixtures import auth_header


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_post_patients_requires_auth(client):
    r = client.post("/patients/", json={
        "name": "X", "age": 30, "village": "V", "phone": "+919000000001",
        "facility_id": str(uuid.uuid4()),
    })
    assert r.status_code == 401


def test_post_patients_requires_phone(client, org_units, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    r = client.post("/patients/", headers=auth_header(token), json={
        "name": "X", "age": 30, "village": "V", "phone": None,
        "facility_id": str(uuid.uuid4()),
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PHONE_REQUIRED"


def test_post_patients_success_creates_patient_and_linked_identity(client, db, org_units, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    r = client.post("/patients/", headers=auth_header(token), json={
        "name": "Rekha Devi", "age": 28, "village": "V1", "phone": "+919222200001",
        "facility_id": str(uuid.uuid4()), "client_uuid": "cu-1",
    })
    assert r.status_code == 200, r.text  # original contract never set 201
    body = r.json()
    assert body["name"] == "Rekha Devi"
    assert body["created_by_user_id"] is not None
    assert body["org_unit_id"] is not None

    identity = db.exec(sqltext(
        "SELECT role, status FROM users WHERE mobile_blind_index = (SELECT mobile_blind_index FROM users LIMIT 0) "
        "OR full_name = 'Rekha Devi'"
    )).first()
    assert identity is not None and identity[0] == "PATIENT" and identity[1] == "ACTIVE"


def test_get_patient_out_of_scope_and_missing_both_404(client, db, org_units, org_units_b, make_actor):
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    # a patient that exists but is posted outside this BMO's scope
    row = db.exec(sqltext(
        "INSERT INTO patient (id, name, age, village, phone, facility_id, created_at, created_by_user_id, org_unit_id) "
        "VALUES (gen_random_uuid(), 'Out Of Scope', 40, 'VB', '+919333300001', gen_random_uuid(), now(), :creator, :org) "
        "RETURNING id"
    ), params={"creator": str(bmo_id), "org": str(org_units_b["BLOCK"])}).first()
    db.commit()
    oos_id = row[0]

    r1 = client.get(f"/patients/{oos_id}", headers=auth_header(token))
    r2 = client.get(f"/patients/{uuid.uuid4()}", headers=auth_header(token))
    assert r1.status_code == 404 and r1.json()["detail"] == "Patient not found"
    assert r2.status_code == 404 and r2.json()["detail"] == "Patient not found"


def test_triage_and_referral_and_status_update_flow(client, org_units, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_resp = client.post("/patients/", headers=auth_header(token), json={
        "name": "P", "age": 30, "village": "V", "phone": "+919222200002",
        "facility_id": str(uuid.uuid4()),
    })
    patient_id = patient_resp.json()["id"]

    triage_resp = client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "Manage here", "referral_urgency": "routine",
    })
    assert triage_resp.status_code == 200, triage_resp.text

    referral_resp = client.post("/referrals/", headers=auth_header(token), json={
        "patient_id": patient_id, "from_facility_id": str(uuid.uuid4()),
        "destination_facility_id": str(uuid.uuid4()), "reason": "Specialist", "urgency": "routine",
    })
    assert referral_resp.status_code == 200, referral_resp.text
    referral_id = referral_resp.json()["id"]
    assert referral_resp.json()["status"] == "INITIATED"

    status_resp = client.patch(f"/referrals/{referral_id}/status?status=ACCEPTED", headers=auth_header(token))
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "ACCEPTED"


def test_sync_requires_auth_and_validates_scope(client, org_units, org_units_b, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])

    r_noauth = client.post("/sync/", json=[])
    assert r_noauth.status_code == 401

    r = client.post("/sync/", headers=auth_header(token), json=[
        {"client_uuid": "c1", "name": "in scope, no org_unit_id claim"},
        {"client_uuid": "c2", "org_unit_id": str(org_units_b["BLOCK"])},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] == 2
    statuses = {rec["client_uuid"]: rec["status"] for rec in body["records"]}
    assert statuses["c1"] == "accepted"
    assert statuses["c2"] == "rejected"


def test_login_and_me_permanent_aliases(client, db, org_units, make_actor):
    cho_id, _ = make_actor("CHO", org_units["SUB_CENTRE"])
    password = "Correct-Horse-Battery-42!"
    db.exec(sqltext("UPDATE users SET password_hash = :h, mfa_required = false WHERE id = :id"),
            params={"h": hash_password(password), "id": str(cho_id)})
    db.commit()
    from app.core.crypto import decrypt_field
    enc = db.exec(sqltext("SELECT mobile_encrypted FROM users WHERE id = :id"),
                  params={"id": str(cho_id)}).first()[0]
    mobile = decrypt_field(bytes(enc))

    login_resp = client.post("/login", json={"mobile": mobile, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    access_token = login_resp.json()["access_token"]

    me_resp = client.get("/me", headers=auth_header(access_token))
    assert me_resp.status_code == 200
    me_body = me_resp.json()
    assert me_body["role"] == "CHO"
    assert "permissions" in me_body and "scope" in me_body
