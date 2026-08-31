"""Tests for the triage decisioning wired into POST /triage/
(app/api/routes/triage.py, this step). Uses the same client/org_units/
make_actor fixtures as tests/test_existing_endpoints.py.

NOTE (why this file exists rather than a live curl session): this task
was executed in an environment with no Bash tool and no .venv present in
this worktree, so the engine wiring below could not be exercised live
against a running uvicorn server. This file is a real, runnable pytest
integration test exercising the same two scenarios the task asked for
via curl, following this repo's own established TestClient pattern
(tests/test_existing_endpoints.py) -- written so that whoever runs
`pytest -q` (or `pytest tests/test_triage_decisioning.py -v`) with the
dev/test Postgres container up gets a real pass/fail, not a fabricated
one.
"""
import logging
import uuid

from tests._fixtures import auth_header


def _make_patient(client, token, age=28):
    r = client.post("/patients/", headers=auth_header(token), json={
        "name": "Test Patient", "age": age, "village": "V", "phone": f"+9192220{uuid.uuid4().int % 100000:05d}",
        "facility_id": str(uuid.uuid4()),
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_backward_compatible_old_shaped_request_still_succeeds(client, org_units, make_actor):
    """The exact request shape test_existing_endpoints.py's own
    test_triage_and_referral_and_status_update_flow sends (no protocol/
    vitals at all) must still return 200 and now also carry a computed
    `decision` object -- additive only, nothing removed."""
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = _make_patient(client, token)

    r = client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "Manage here", "referral_urgency": "routine",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Existing fields, unchanged.
    assert body["patient_id"] == patient_id
    assert body["triage_disposition"] == "Manage here"
    assert body["referral_urgency"] == "routine"
    assert body["created_by_user_id"] is not None
    assert body["org_unit_id"] is not None
    # New, additive field.
    assert "decision" in body
    decision = body["decision"]
    for key in ("disposition", "urgency", "reason", "red_flags", "protocol_version",
                "insufficient_data", "missing_fields", "engine", "evaluated_at"):
        assert key in decision
    assert decision["engine"] in ("rule", "fallback")


def test_high_bp_anc_severe_headache_computes_refer_within_24h(client, org_units, make_actor):
    """SCENARIO 2: BP 156/98, protocol ANC, symptom severe_headache ->
    server-computed decision.disposition == REFER,
    decision.urgency == WITHIN_24H (the ANC handler's own
    hypertension-refer branch -- app/services/triage/fallback.py's
    _anc(), 140<=bp_sys<160)."""
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = _make_patient(client, token)

    r = client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "caller's own note", "referral_urgency": "routine",
        "protocol": "ANC",
        "vitals": {"bp_systolic": 156, "bp_diastolic": 98},
        "symptoms": ["severe_headache"],
    })
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert decision["disposition"] == "REFER"
    assert decision["urgency"] == "WITHIN_24H"
    assert decision["insufficient_data"] is False


def test_caller_supplied_disposition_is_ignored_and_logged(client, org_units, make_actor, caplog):
    """SCENARIO 3: client sends "disposition": "MANAGE_HERE" (and
    "urgency": "ROUTINE") alongside the same dangerous ANC vitals ->
    response must still show the engine's real computed REFER/
    WITHIN_24H, NOT the caller's MANAGE_HERE, and an INFO log line
    recording the client's attempt must actually appear."""
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = _make_patient(client, token)

    with caplog.at_level(logging.INFO, logger="app.api.routes.triage"):
        r = client.post("/triage/", headers=auth_header(token), json={
            "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
            "triage_disposition": "caller's own note", "referral_urgency": "routine",
            "protocol": "ANC",
            "vitals": {"bp_systolic": 156, "bp_diastolic": 98},
            "symptoms": ["severe_headache"],
            "disposition": "MANAGE_HERE",
            "urgency": "ROUTINE",
        })
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert decision["disposition"] == "REFER", "caller-supplied MANAGE_HERE must never win"
    assert decision["disposition"] != "MANAGE_HERE"
    assert decision["urgency"] == "WITHIN_24H"

    info_records = [rec for rec in caplog.records if rec.levelno == logging.INFO]
    assert any("disposition" in rec.getMessage() and patient_id in rec.getMessage() for rec in info_records), (
        f"expected an INFO log line naming the ignored field(s) and patient_id; got: "
        f"{[rec.getMessage() for rec in info_records]}"
    )


def test_unknown_protocol_is_422_invalid_protocol(client, org_units, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = _make_patient(client, token)

    r = client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note", "protocol": "NOT_A_REAL_PROTOCOL",
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_PROTOCOL"


def test_out_of_scope_patient_still_403(client, org_units, org_units_b, make_actor):
    """Existing scope-check behaviour (S20) must be untouched by this step."""
    _, token_a = make_actor("BMO", org_units["BLOCK"])
    _, token_b = make_actor("BMO", org_units_b["BLOCK"])
    patient_id = _make_patient(client, token_a)

    r = client.post("/triage/", headers=auth_header(token_b), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note",
    })
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "OUT_OF_SCOPE"
