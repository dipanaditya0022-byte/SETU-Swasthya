"""Regression tests for the atomicity fixes in this step (backend/docs/
DAY3_BUGS.md follow-up task -- "Confirm that failed requests are not
partially writing incorrect records, and make every write path a single
transaction").

Each of the four "single transaction" write paths (POST /patients/,
POST /triage/, POST /referrals/, PATCH /referrals/{id}/status) gets one
test: force a failure AFTER the first write inside the route (by
monkeypatching that route module's own `_write_audit` helper to raise --
the same technique used for this step's own live, pre-fix proof against
a real server, documented in the PR/commit this test file ships with),
then assert ZERO rows persisted for that request -- not just the row
that would have been written first, every row the request would have
written.

POST /sync/ gets a different test, matching its own deliberately
different design (per-item SAVEPOINTs, not one transaction for the whole
batch): a 50-item batch with one deliberately malformed item asserts
49 succeed, 1 fails, and the failing item's index is named in the
response -- proving one bad item cannot sink 49 good ones.

Uses this repo's own existing fixtures (`client`, `db`, `org_units`,
`make_actor`, `auth_header`) -- see tests/conftest.py / tests/_fixtures.py
-- not a new test-setup pattern.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import text as sqltext

from app.main import app
from tests._fixtures import auth_header

# The shared `client` fixture (tests/conftest.py) uses TestClient's
# default raise_server_exceptions=True, which re-raises an unhandled
# route exception as a Python exception in the TEST itself rather than
# handing back a Response -- useful for most tests (a route should never
# raise), but exactly wrong here, where causing a 500 IS the point. This
# file's own client turns that off so a forced failure comes back as a
# normal `Response(status_code=500)`, like a real caller would see.
@pytest.fixture
def raising_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _boom(*_args, **_kwargs):
    raise RuntimeError("FORCED_FAILURE_TEST_ATOMICITY")


# ============================================================
# POST /patients/ -- user row + patient row + consent row, ONE transaction.
# ============================================================

def test_patients_atomic_on_failure(raising_client, db, org_units, make_actor, monkeypatch):
    monkeypatch.setattr("app.api.routes.patients._write_audit", _boom)
    _, token = make_actor("BMO", org_units["BLOCK"])
    phone = "+919" + str(uuid.uuid4().int)[:9]

    r = raising_client.post("/patients/", headers=auth_header(token), json={
        "name": "Atomicity Test", "age": 30, "village": "V",
        "phone": phone, "facility_id": str(uuid.uuid4()), "client_uuid": None,
    })
    assert r.status_code == 500

    patient_count = db.exec(
        sqltext("SELECT count(*) FROM patient WHERE phone = :p"), params={"p": phone}
    ).first()[0]
    assert patient_count == 0, "a failed POST /patients/ must leave NO patient row"

    from app.core.crypto import blind_index
    user_count = db.exec(
        sqltext("SELECT count(*) FROM users WHERE mobile_blind_index = :m"),
        params={"m": blind_index(phone)},
    ).first()[0]
    assert user_count == 0, "a failed POST /patients/ must leave NO linked users row either"


# ============================================================
# POST /triage/ -- triage row + audit row, ONE transaction.
# ============================================================

def test_triage_atomic_on_failure(raising_client, db, org_units, make_actor, monkeypatch):
    _, token = make_actor("BMO", org_units["BLOCK"])

    patient_resp = raising_client.post("/patients/", headers=auth_header(token), json={
        "name": "Triage Atomicity Patient", "age": 32, "village": "V",
        "phone": "+919" + str(uuid.uuid4().int)[:9], "facility_id": str(uuid.uuid4()), "client_uuid": None,
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    monkeypatch.setattr("app.api.routes.triage._write_audit", _boom)

    r = raising_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "Manage here", "referral_urgency": "routine",
        "protocol": "ANC", "vitals": {"bp_systolic": 156, "bp_diastolic": 98},
        "symptoms": ["severe_headache"], "danger_signs": [], "sex": "FEMALE",
        "is_pregnant": True, "gestational_weeks": 32, "history": {},
    })
    assert r.status_code == 500

    triage_count = db.exec(
        sqltext("SELECT count(*) FROM triageencounter WHERE patient_id = :p"),
        params={"p": patient_id},
    ).first()[0]
    assert triage_count == 0, "a failed POST /triage/ must leave NO row (not even one with disposition set)"


# ============================================================
# POST /referrals/ -- referral row + initial transition + audit row, ONE
# transaction.
# ============================================================

def test_referral_create_atomic_on_failure(raising_client, db, org_units, make_actor, monkeypatch):
    _, token = make_actor("BMO", org_units["BLOCK"])

    patient_resp = raising_client.post("/patients/", headers=auth_header(token), json={
        "name": "Referral Atomicity Patient", "age": 40, "village": "V",
        "phone": "+919" + str(uuid.uuid4().int)[:9], "facility_id": str(uuid.uuid4()), "client_uuid": None,
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    monkeypatch.setattr("app.api.routes.referrals._write_audit", _boom)

    r = raising_client.post("/referrals/", headers=auth_header(token), json={
        "patient_id": patient_id, "from_facility_id": str(uuid.uuid4()),
        "destination_facility_id": str(uuid.uuid4()), "reason": "Atomicity test",
        "urgency": "routine", "receiving_unit": "General OPD", "owner": "Tester",
    })
    assert r.status_code == 500

    referral_row = db.exec(
        sqltext("SELECT id FROM referral WHERE patient_id = :p"), params={"p": patient_id}
    ).first()
    assert referral_row is None, "a failed POST /referrals/ must leave NO referral row"

    # Even if a referral row somehow existed, its transitions must be 0 --
    # asserted independently in case patient_id filtering above ever
    # changes; this is the exact "status changed with no transition row"
    # signature this whole task is about.
    transitions_count = db.exec(
        sqltext(
            "SELECT count(*) FROM referral_transitions t "
            "JOIN referral r ON r.id = t.referral_id WHERE r.patient_id = :p"
        ),
        params={"p": patient_id},
    ).first()[0]
    assert transitions_count == 0


# ============================================================
# PATCH /referrals/{id}/status -- referral update + transition row +
# audit row, ONE transaction.
# ============================================================

def test_referral_status_patch_atomic_on_failure(raising_client, db, org_units, make_actor, monkeypatch):
    _, token = make_actor("BMO", org_units["BLOCK"])

    patient_resp = raising_client.post("/patients/", headers=auth_header(token), json={
        "name": "Referral Status Atomicity Patient", "age": 45, "village": "V",
        "phone": "+919" + str(uuid.uuid4().int)[:9], "facility_id": str(uuid.uuid4()), "client_uuid": None,
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    referral_resp = raising_client.post("/referrals/", headers=auth_header(token), json={
        "patient_id": patient_id, "from_facility_id": str(uuid.uuid4()),
        "destination_facility_id": str(uuid.uuid4()), "reason": "Atomicity test",
        "urgency": "routine", "receiving_unit": "General OPD", "owner": "Tester",
    })
    assert referral_resp.status_code == 200, referral_resp.text
    referral_id = referral_resp.json()["id"]

    transitions_before = db.exec(
        sqltext("SELECT count(*) FROM referral_transitions WHERE referral_id = :r"),
        params={"r": referral_id},
    ).first()[0]
    assert transitions_before == 1, "creation itself should have written the initial NULL->INITIATED transition"

    monkeypatch.setattr("app.api.routes.referrals._write_audit", _boom)

    r = raising_client.patch(
        f"/referrals/{referral_id}/status?status=SLOT_BOOKED",
        headers=auth_header(token),
        json={"slot_datetime": "2026-09-20T10:00:00Z", "destination_org_unit_id": str(uuid.uuid4())},
    )
    assert r.status_code == 500

    status_after, transitions_after = db.exec(
        sqltext(
            "SELECT r.status, (SELECT count(*) FROM referral_transitions t WHERE t.referral_id = r.id) "
            "FROM referral r WHERE r.id = :r"
        ),
        params={"r": referral_id},
    ).first()
    assert status_after == "INITIATED", "a failed PATCH .../status must leave the referral's status UNCHANGED"
    assert transitions_after == 1, "and must not add a transition row for the change that didn't really happen"


# ============================================================
# POST /sync/ -- deliberately different: per-item SAVEPOINTs, partial
# success reported, one bad item must not sink the batch.
# ============================================================

def test_sync_one_malformed_item_does_not_sink_the_batch(raising_client, org_units, make_actor, db):
    _, token = make_actor("BMO", org_units["BLOCK"])
    batch_tag = uuid.uuid4().hex[:8]

    records = []
    for i in range(50):
        if i == 23:
            # Malformed: org_unit_id that fails UUID casting when the
            # route's own scope check runs it through Postgres -- the
            # exact class of failure that, before this step's fix, raised
            # UNCAUGHT inside the batch for-loop and 500'd the whole
            # request (proven live against a real server; see this test
            # file's own module docstring and backend/docs/DAY3_BUGS.md).
            records.append({"client_uuid": f"sync-atom-{batch_tag}-{i}", "name": f"Bad {i}",
                             "org_unit_id": "not-a-valid-uuid"})
        else:
            records.append({"client_uuid": f"sync-atom-{batch_tag}-{i}", "name": f"Good {i}",
                             "age": 20 + i, "village": "V", "phone": f"+9191234{i:05d}"})

    r = raising_client.post("/sync/", headers=auth_header(token), json=records)
    assert r.status_code == 200, r.text  # partial failure is NOT a request failure
    body = r.json()

    assert body["synced"] == 50  # unchanged, contract-frozen meaning: count submitted
    assert body["created"] == 49
    assert body["duplicates"] == 0
    assert body["failed"] == 1

    failed_results = [x for x in body["results"] if x["status"] == "failed"]
    assert len(failed_results) == 1
    assert failed_results[0]["index"] == 23, "the failing item's index must be named in the response"

    persisted = db.exec(
        sqltext("SELECT count(*) FROM patient WHERE client_uuid LIKE :pat"),
        params={"pat": f"sync-atom-{batch_tag}-%"},
    ).first()[0]
    assert persisted == 49, "49 of 50 records must actually be in the database, not just reported as created"
