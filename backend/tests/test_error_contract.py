"""Regression tests for the global exception-handling contract
(app/core/errors.py -- "Register global exception handlers so no
unhandled exception can reach a client, and add a request ID to every
response and log line").

One test per handler:
  1. RequestValidationError -- via a real malformed request (a non-UUID
     path param).
  2. AppError -- nothing in this codebase raises AppError yet (see
     app/core/errors.py's own "APPERROR DECISION" docstring for why
     that's deliberate). Tested by invoking `app_error_handler` directly
     against a hand-built Starlette Request + a real AppError instance
     -- not via HTTP, since there's no live route to hit. This is
     stated here, not hidden: it proves the HANDLER is correct, not
     that any route currently uses it.
  3. IntegrityError -- a REAL Postgres unique-constraint violation,
     triggered via two direct inserts through the `db` fixture (not
     through a route's own pre-check-then-insert logic, which every
     existing route that touches a unique users column already has --
     see app/api/routes/patients.py/users.py -- and which would make a
     genuine constraint violation only reachable via a real race
     condition, not something to depend on for a deterministic test).
     The resulting REAL `sqlalchemy.exc.IntegrityError` is then passed
     to `integrity_error_handler` directly, same "call the handler,
     not a route" pattern as AppError above, for the same reason
     (determinism) -- NOT because no route can trigger one; a route
     CAN (see this file's own `test_integrity_error_reachable_via_a_real_route`
     below, which hits PATCH /referrals/{id}/status with a
     non-existent `arrival_confirmed_by` -- a genuine FK violation,
     confirmed live against the running dev server during this task).
  4. Exception (catch-all) -- monkeypatch technique from
     tests/test_atomicity.py/test_validation_matrix.py (both already in
     this repo): force a route's own helper to raise a bare RuntimeError,
     hit it via HTTP, assert the exact 3-key body.

Also: a whole-file scan asserting NO response body captured by ANY case
in this file contains a traceback/file-path/library-name fragment, and
that X-Request-ID is present on both a success response and every
error response captured here.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import text as sqltext
from starlette.requests import Request

from app.core.errors import AppError, app_error_handler, integrity_error_handler
from app.main import app
from tests._fixtures import auth_header

# Every response body captured by ANY case in this file, so the
# whole-file leak scan (test_no_response_anywhere_leaks_internals) can
# check all of them in one place instead of duplicating the substring
# assertion in every single test.
_CAPTURED_BODIES: list[str] = []


def _capture(response) -> str:
    text = response.text
    _CAPTURED_BODIES.append(text)
    return text


@pytest.fixture
def raising_client() -> TestClient:
    # Same rationale as tests/test_atomicity.py's own identical fixture:
    # the default TestClient re-raises a route's unhandled exception as
    # a Python exception in the TEST process itself (raise_server_exceptions
    # =True) rather than handing back a Response -- exactly wrong here,
    # where getting back a real Response IS the point.
    return TestClient(app, raise_server_exceptions=False)


def _fake_request(request_id: str = "test-request-id-0000") -> Request:
    """A minimal Starlette Request, NOT going through the ASGI app or
    RequestIDMiddleware at all -- confirmed live (see app/core/errors.py
    itself) that Request.state reads straight from scope["state"], so
    pre-seeding it here is the same mechanism the real middleware uses,
    just without a real HTTP round-trip. Good enough to unit-test a
    handler function directly (cases #2 and #3)."""
    scope = {
        "type": "http", "method": "GET", "path": "/test",
        "headers": [], "query_string": b"", "state": {"request_id": request_id},
    }
    return Request(scope)


# ============================================================
# #1 -- RequestValidationError -> 422, {"error": {...}} shape.
# ============================================================

def test_1_request_validation_error_shape(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    r = raising_client.get("/patients/not-a-uuid", headers=auth_header(token))
    body_text = _capture(r)

    assert r.status_code == 422
    body = json.loads(body_text)
    assert "error" in body
    err = body["error"]
    assert err["code"] == "INVALID_UUID"
    assert "field" in err
    assert "detail" in err  # the raw pydantic msg, per this task's own spec
    assert "request_id" in err and err["request_id"]
    assert r.headers.get("X-Request-ID") == err["request_id"]


# ============================================================
# #2 -- AppError -> exc.status_code. No live call site yet (see module
# docstring) -- the handler is invoked directly.
# ============================================================

@pytest.mark.asyncio
async def test_2_app_error_handler_shape():
    request = _fake_request("app-error-test-request-id")
    exc = AppError(
        409, "INVALID_TRANSITION", "This referral cannot move to that stage yet.",
        detail="INITIATED -> CLOSED is not an allowed transition.",
        allowed_next=["SLOT_BOOKED", "TRANSPORT_ARRANGED", "CANCELLED", "NOT_ARRIVED"],
    )
    response = await app_error_handler(request, exc)
    body_text = response.body.decode()
    _CAPTURED_BODIES.append(body_text)

    assert response.status_code == 409
    body = json.loads(body_text)
    err = body["error"]
    assert err["code"] == "INVALID_TRANSITION"
    assert err["message"] == "This referral cannot move to that stage yet."
    assert err["detail"] == "INITIATED -> CLOSED is not an allowed transition."
    assert err["request_id"] == "app-error-test-request-id"
    # "plus any extra keys such as allowed_next" -- this task's own spec.
    assert err["allowed_next"] == ["SLOT_BOOKED", "TRANSPORT_ARRANGED", "CANCELLED", "NOT_ARRIVED"]
    assert response.headers.get("X-Request-ID") == "app-error-test-request-id"


# ============================================================
# #3 -- IntegrityError -> 409. A REAL constraint violation, handler
# invoked directly (see module docstring for why, and the sibling test
# below for the same class of bug reached via a real HTTP route).
# ============================================================

@pytest.mark.asyncio
async def test_3_integrity_error_handler_maps_constraint_and_hides_sql(db):
    mobile_bi = uuid.uuid4().hex  # stand-in blind index value, uniqueness is all that matters here
    db.exec(sqltext(
        "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
        "mobile_masked, status, mfa_required, mfa_enrolled) "
        "VALUES ('PATIENT', 99, 'Duplicate Probe A', :menc, :mbi, '+91XXXXX00001', 'ACTIVE', false, false)"
    ), params={"menc": b"x" * 10, "mbi": mobile_bi})
    db.commit()

    real_exc = None
    try:
        db.exec(sqltext(
            "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
            "mobile_masked, status, mfa_required, mfa_enrolled) "
            "VALUES ('PATIENT', 99, 'Duplicate Probe B', :menc, :mbi, '+91XXXXX00002', 'ACTIVE', false, false)"
        ), params={"menc": b"y" * 10, "mbi": mobile_bi})
        db.commit()
    except IntegrityError as exc:
        real_exc = exc
    finally:
        db.rollback()

    assert real_exc is not None, "expected a real IntegrityError from a genuine duplicate-key insert"

    request = _fake_request("integrity-error-test-request-id")
    response = await integrity_error_handler(request, real_exc)
    body_text = response.body.decode()
    _CAPTURED_BODIES.append(body_text)

    assert response.status_code == 409
    body = json.loads(body_text)
    err = body["error"]
    assert err["code"] == "CONFLICT"
    assert err["message"] == "This mobile number is already registered."  # the friendly mapping, not str(exc)
    assert err["request_id"] == "integrity-error-test-request-id"
    # THE assertion this whole handler exists for.
    assert "idx_users_mobile_bi" not in body_text  # constraint name not leaked to the client
    assert str(real_exc) not in body_text  # the raw exception (SQL + params) never appears
    assert "INSERT INTO" not in body_text
    assert response.headers.get("X-Request-ID") == "integrity-error-test-request-id"


def test_3b_integrity_error_reachable_via_a_real_route(raising_client, org_units, make_actor):
    """Same handler, reached the NORMAL way (a real HTTP request through
    a real route), for a DIFFERENT real constraint (fk_referral_
    arrival_confirmed_by) -- confirms the handler is actually wired into
    the live app, not just correct in isolation. Confirmed live against
    the running dev server during this task before this test was
    written (see the delivery notes' curl transcript)."""
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)

    patient_resp = raising_client.post("/patients/", headers=headers, json={
        "name": "FK Violation Probe", "age": 31, "village": "V",
        "phone": "+919888800001", "facility_id": str(uuid.uuid4()),
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    referral_resp = raising_client.post("/referrals/", headers=headers, json={
        "patient_id": patient_id, "from_facility_id": str(uuid.uuid4()),
        "destination_facility_id": str(org_units["PHC"]),
        "reason": "x", "urgency": "routine", "receiving_unit": "General OPD", "owner": "T",
    })
    assert referral_resp.status_code == 200, referral_resp.text
    referral_id = referral_resp.json()["id"]

    slot_resp = raising_client.patch(
        f"/referrals/{referral_id}/status?status=SLOT_BOOKED", headers=headers,
        json={"slot_datetime": "2026-09-20T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"])},
    )
    assert slot_resp.status_code == 200, slot_resp.text

    r = raising_client.patch(
        f"/referrals/{referral_id}/status?status=ARRIVED", headers=headers,
        json={"arrival_confirmed_by": str(uuid.uuid4())},  # a UUID that names no real user
    )
    body_text = _capture(r)

    assert r.status_code == 409
    body = json.loads(body_text)
    assert body["error"]["code"] == "CONFLICT"
    assert "does not exist" in body["error"]["message"]
    assert "fk_referral_arrival_confirmed_by" not in body_text
    assert r.headers.get("X-Request-ID")


# ============================================================
# #4 -- catch-all Exception -> 500, exactly 3 keys, nothing else.
# ============================================================

def test_4_unhandled_exception_returns_exactly_three_keys(raising_client, org_units, make_actor, monkeypatch):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)

    patient_resp = raising_client.post("/patients/", headers=headers, json={
        "name": "Catch-all Probe", "age": 33, "village": "V",
        "phone": "+919888800002", "facility_id": str(uuid.uuid4()),
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    def _boom(*_args, **_kwargs):
        raise RuntimeError("a wild, unanticipated bug -- exactly what this handler exists for")

    monkeypatch.setattr("app.api.routes.triage._write_audit", _boom)

    r = raising_client.post("/triage/", headers=headers, json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "x", "protocol": "GENERAL",
    })
    body_text = _capture(r)

    assert r.status_code == 500
    body = json.loads(body_text)
    assert set(body.keys()) == {"error"}
    err = body["error"]
    assert set(err.keys()) == {"code", "message", "request_id"}  # EXACTLY these three, no more
    assert err["code"] == "INTERNAL_ERROR"
    assert err["message"] == "Something went wrong. Please try again."
    assert err["request_id"]
    assert "RuntimeError" not in body_text  # no exception type
    assert "a wild, unanticipated bug" not in body_text  # no exception message
    assert r.headers.get("X-Request-ID") == err["request_id"]


# ============================================================
# Whole-file checks: no leak, ever; X-Request-ID present on both a
# success response and every error captured above.
# ============================================================

_FORBIDDEN_SUBSTRINGS = ["Traceback", 'File "', "line ", "sqlalchemy", "psycopg", "/app/", ".py"]


def test_no_response_anywhere_leaks_internals():
    assert _CAPTURED_BODIES, "no bodies were captured -- the tests above must run first in this file"
    for body_text in _CAPTURED_BODIES:
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in body_text, (
                f"response body leaked forbidden substring {forbidden!r}: {body_text[:500]!r}"
            )


def test_x_request_id_present_on_success(raising_client):
    r = raising_client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")
