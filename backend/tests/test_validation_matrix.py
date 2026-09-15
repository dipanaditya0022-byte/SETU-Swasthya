"""One parametrised test covering the full failure-mode validation matrix
(backend/docs -- "Make every expected failure return a specific,
controlled HTTP response with a plain-language message" task): every row
asserts BOTH the HTTP status code AND a named, machine-readable error
code, plus whatever extra shape detail that row specifically calls for
(a field name, a range, `allowed_next`, the valid-value list, a failing
batch index, `insufficient_data`/`disposition`, or -- for the 403 row --
the ABSENCE of the permission name).

Uses this repo's existing fixtures (`org_units`, `org_units_b`,
`make_actor`, `db`) same as every other test file here. Uses a LOCAL
`raising_client` (not the shared `client` fixture) so a forced 500 (the
two negative "server still copes" checks this file does NOT need, but
some earlier-arriving fixtures in this repo use the same pattern) comes
back as a real Response instead of re-raising in the test process --
see tests/test_atomicity.py's own identical fixture/rationale.

WHY ONE TEST, NOT ONE PER ROW: the task asks for "one parametrised test
covering every row" explicitly. Each row is a `(case_id, request_fn,
expected_status, expected_code, extra_check)` tuple; `request_fn` and
`extra_check` are small closures built once per test run from a shared
`ctx` (actor token, a real patient, a real facility-type org unit, a
real non-facility org unit, an out-of-scope org unit) -- see `_build_cases`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import text as sqltext

from app.core.tokens import issue_access_token
from app.main import app
from tests._fixtures import auth_header


@pytest.fixture
def raising_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def ctx(raising_client, db, org_units, org_units_b, make_actor):
    """Shared scaffolding every case draws from -- built once per test
    run (function-scoped, like every other fixture in this repo's own
    _reset_db-per-test isolation model)."""
    # MEDICAL_OFFICER, not BMO: needs patient:create/triage:create/
    # referral:create/referral:update_status/dashboard:facility (all
    # present for this role -- checked directly against role_permissions)
    # while still lacking audit:read, needed for the PERMISSION_DENIED
    # row below.
    actor_id, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)

    def make_patient(phone_suffix: str) -> str:
        # E.164 Indian mobile: +91 + exactly 10 digits, first digit 6-9
        # (app/core/crypto.py's own _MOBILE_RE). phone_suffix is zero-
        # padded to 9 digits so "+919" + suffix is always exactly 10.
        r = raising_client.post("/patients/", headers=headers, json={
            "name": "Validation Matrix Patient", "age": 30, "village": "V",
            "phone": f"+919{phone_suffix.zfill(9)}", "facility_id": str(uuid.uuid4()),
        })
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def make_referral(patient_id: str, destination=None) -> str:
        r = raising_client.post("/referrals/", headers=headers, json={
            "patient_id": patient_id, "from_facility_id": str(uuid.uuid4()),
            "destination_facility_id": str(destination or org_units["PHC"]),
            "reason": "Validation matrix test", "urgency": "routine",
            "receiving_unit": "General OPD", "owner": "Tester",
        })
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def make_slot_booked_referral(patient_id: str) -> str:
        referral_id = make_referral(patient_id)
        r = raising_client.patch(
            f"/referrals/{referral_id}/status?status=SLOT_BOOKED", headers=headers,
            json={"slot_datetime": "2026-09-20T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"])},
        )
        assert r.status_code == 200, r.text
        return referral_id

    def make_closed_referral(patient_id: str) -> str:
        referral_id = make_slot_booked_referral(patient_id)
        r = raising_client.patch(
            f"/referrals/{referral_id}/status?status=CANCELLED", headers=headers,
            json={"cancellation_reason": "test"},
        )
        assert r.status_code == 200, r.text
        return referral_id

    def token_with(*, token_version: int = 0, expires_in_minutes: int = 15) -> str:
        return issue_access_token(
            user_id=str(actor_id), role="MEDICAL_OFFICER", level=6,
            scope_org_id=str(org_units["BLOCK"]), scope_path="/x",
            perms_hash="x", session_id="validation-matrix-test",
            token_version=token_version, amr=["pwd"],
            expires_in_minutes=expires_in_minutes,
        )

    return {
        "client": raising_client, "db": db, "headers": headers, "actor_id": actor_id,
        "org_units": org_units, "org_units_b": org_units_b, "make_actor": make_actor,
        "make_patient": make_patient, "make_referral": make_referral,
        "make_slot_booked_referral": make_slot_booked_referral,
        "make_closed_referral": make_closed_referral, "token_with": token_with,
    }


def _detail(response):
    # Error-handling task (backend/app/core/errors.py, built after this
    # file): RequestValidationError responses moved from `{"detail":
    # {...}}` to `{"error": {...}}` -- every hand-written HTTPException
    # elsewhere in this codebase (still the majority of this file's own
    # cases) is UNTOUCHED and still uses `{"detail": {...}}` (see that
    # module's own "RESPONSE-SHAPE DECISION" docstring for why). Check
    # "error" first, fall back to "detail", so this helper keeps working
    # for cases hitting either handler.
    body = response.json()
    if isinstance(body.get("error"), dict):
        return body["error"]
    d = body.get("detail", body)
    return d if isinstance(d, dict) else {}


def _build_cases(ctx):
    c = ctx["client"]
    h = ctx["headers"]
    facility = str(uuid.uuid4())

    cases = []

    def add(case_id, fn, expected_status, expected_code, extra=None):
        cases.append((case_id, fn, expected_status, expected_code, extra))

    # ============================================================
    # POST /patients/
    # ============================================================
    add("patients_missing_name",
        lambda: c.post("/patients/", headers=h, json={
            "age": 30, "village": "V", "phone": "+919000010001", "facility_id": facility}),
        422, "NAME_REQUIRED", lambda r: _detail(r).get("code", "").endswith("_REQUIRED"))

    add("patients_missing_age",
        lambda: c.post("/patients/", headers=h, json={
            "name": "X", "village": "V", "phone": "+919000010002", "facility_id": facility}),
        422, "AGE_REQUIRED")

    add("patients_age_200",
        lambda: c.post("/patients/", headers=h, json={
            "name": "X", "age": 200, "village": "V", "phone": "+919000010003", "facility_id": facility}),
        422, "INVALID_AGE")

    add("patients_malformed_mobile",
        lambda: c.post("/patients/", headers=h, json={
            "name": "X", "age": 30, "village": "V", "phone": "12345", "facility_id": facility}),
        422, "INVALID_MOBILE")

    # ============================================================
    # GET /patients/{id}
    # ============================================================
    add("get_patient_non_uuid_id",
        lambda: c.get("/patients/not-a-uuid", headers=h),
        422, "INVALID_UUID")

    add("get_patient_valid_uuid_no_such_patient",
        lambda: c.get(f"/patients/{uuid.uuid4()}", headers=h),
        404, "NOT_FOUND")

    def _oos_patient():
        row = ctx["db"].exec(sqltext(
            "INSERT INTO patient (id, name, age, village, phone, facility_id, created_at, created_by_user_id, org_unit_id) "
            "VALUES (gen_random_uuid(), 'OOS', 40, 'VB', '+919333300099', gen_random_uuid(), now(), :creator, :org) "
            "RETURNING id"
        ), params={"creator": str(ctx["actor_id"]), "org": str(ctx["org_units_b"]["BLOCK"])}).first()
        ctx["db"].commit()
        return c.get(f"/patients/{row[0]}", headers=h)

    add("get_patient_other_district_is_404_never_403", _oos_patient, 404, "NOT_FOUND",
        lambda r: r.status_code != 403)

    # ============================================================
    # POST /triage/
    # ============================================================
    patient_id = ctx["make_patient"]("020001")

    add("triage_unknown_protocol",
        lambda: c.post("/triage/", headers=h, json={
            "patient_id": patient_id, "facility_id": facility,
            "triage_disposition": "x", "protocol": "NOT_A_PROTOCOL"}),
        422, "INVALID_PROTOCOL")

    add("triage_bp_systolic_400_out_of_range",
        lambda: c.post("/triage/", headers=h, json={
            "patient_id": patient_id, "facility_id": facility, "triage_disposition": "x",
            "protocol": "ANC", "vitals": {"bp_systolic": 400}}),
        422, "VITAL_OUT_OF_RANGE",
        lambda r: _detail(r).get("field") == "bp_systolic" and "min" in _detail(r) and "max" in _detail(r))

    add("triage_bp_systolic_wrong_type",
        lambda: c.post("/triage/", headers=h, json={
            "patient_id": patient_id, "facility_id": facility, "triage_disposition": "x",
            "protocol": "ANC", "vitals": {"bp_systolic": "high"}}),
        422, None,
        lambda r: "bp_systolic" in _detail(r).get("field", _detail(r).get("message", "")))

    def _vitals_empty_anc():
        return c.post("/triage/", headers=h, json={
            "patient_id": patient_id, "facility_id": facility, "triage_disposition": "x",
            "protocol": "ANC", "vitals": {}})

    add("triage_vitals_empty_on_anc_is_200_refer_insufficient_MOST_IMPORTANT_ROW",
        _vitals_empty_anc, 200, None,
        lambda r: (r.json()["decision"]["disposition"] == "REFER"
                   and r.json()["decision"]["insufficient_data"] is True))

    add("triage_nonexistent_patient",
        lambda: c.post("/triage/", headers=h, json={
            "patient_id": str(uuid.uuid4()), "facility_id": facility,
            "triage_disposition": "x", "protocol": "GENERAL"}),
        404, "PATIENT_NOT_FOUND")

    # ============================================================
    # POST /referrals/
    # ============================================================
    referral_patient_id = ctx["make_patient"]("020002")

    add("referrals_invalid_urgency",
        lambda: c.post("/referrals/", headers=h, json={
            "patient_id": referral_patient_id, "from_facility_id": facility,
            "destination_facility_id": str(ctx["org_units"]["PHC"]),
            "reason": "x", "urgency": "whenever", "receiving_unit": "General OPD", "owner": "T"}),
        422, "INVALID_URGENCY")

    add("referrals_destination_not_a_facility_type",
        lambda: c.post("/referrals/", headers=h, json={
            "patient_id": referral_patient_id, "from_facility_id": facility,
            "destination_facility_id": str(ctx["org_units"]["STATE"]),
            "reason": "x", "urgency": "routine", "receiving_unit": "General OPD", "owner": "T"}),
        422, "INVALID_ORG_UNIT_TYPE")

    # ============================================================
    # PATCH /referrals/{id}/status
    # ============================================================
    p_initiated = ctx["make_patient"]("020003")
    ref_initiated = ctx["make_referral"](p_initiated)

    add("referral_status_initiated_to_closed_invalid_transition",
        lambda: c.patch(f"/referrals/{ref_initiated}/status?status=CLOSED", headers=h),
        409, "INVALID_TRANSITION",
        lambda r: "allowed_next" in _detail(r))

    add("referral_status_not_in_enum",
        lambda: c.patch(f"/referrals/{ref_initiated}/status?status=NOT_A_REAL_STATUS", headers=h),
        422, "INVALID_STATUS",
        lambda r: "INITIATED" in _detail(r).get("message", ""))  # lists valid values

    p_slot_booked = ctx["make_patient"]("020004")
    ref_slot_booked = ctx["make_slot_booked_referral"](p_slot_booked)

    add("referral_status_to_arrived_without_proof",
        lambda: c.patch(f"/referrals/{ref_slot_booked}/status?status=ARRIVED", headers=h),
        422, "ARRIVAL_PROOF_REQUIRED")

    p_closed = ctx["make_patient"]("020005")
    ref_closed = ctx["make_closed_referral"](p_closed)

    add("referral_status_already_closed_is_terminal",
        lambda: c.patch(f"/referrals/{ref_closed}/status?status=TRANSPORT_ARRANGED", headers=h),
        409, "TERMINAL_STATE")

    # ============================================================
    # GET /dashboard/facility/{id}
    # ============================================================
    add("dashboard_nonexistent_facility",
        lambda: c.get(f"/dashboard/facility/{uuid.uuid4()}", headers=h),
        404, "FACILITY_NOT_IN_SCOPE")

    add("dashboard_other_district",
        lambda: c.get(f"/dashboard/facility/{ctx['org_units_b']['BLOCK']}", headers=h),
        404, "FACILITY_NOT_IN_SCOPE")

    # ============================================================
    # GET /referrals/exceptions
    # ============================================================
    add("exceptions_stage_99",
        lambda: c.get("/referrals/exceptions?stage=99", headers=h),
        422, "INVALID_FILTER")

    # ============================================================
    # POST /sync/
    # ============================================================
    add("sync_structurally_malformed_batch_names_the_index",
        lambda: c.post("/sync/", headers=h, json=[
            {"client_uuid": "vm-sync-ok-1", "name": "Good"},
            "this is not a record",
            {"client_uuid": "vm-sync-ok-2", "name": "Good2"},
        ]),
        422, None,
        lambda r: _detail(r).get("index") == 1 or "1" in str(_detail(r)))

    dup_batch = [
        {"client_uuid": "vm-sync-idem-1", "name": "Idem1", "age": 20, "village": "V", "phone": "+919222200001"},
        {"client_uuid": "vm-sync-idem-2", "name": "Idem2", "age": 21, "village": "V", "phone": "+919222200002"},
    ]

    def _sync_twice():
        first = c.post("/sync/", headers=h, json=dup_batch)
        assert first.status_code == 200, first.text
        assert first.json()["created"] == 2
        second = c.post("/sync/", headers=h, json=dup_batch)
        return second

    add("sync_same_batch_twice_is_idempotent_no_duplicate",
        _sync_twice, 200, None,
        lambda r: r.json()["created"] == 0 and r.json()["duplicates"] == 2)

    # ============================================================
    # ANY endpoint
    # ============================================================
    add("any_missing_token",
        lambda: c.get("/me"), 401, "UNAUTHENTICATED")

    add("any_expired_token",
        lambda: c.get("/me", headers=auth_header(ctx["token_with"](expires_in_minutes=-1))),
        401, "TOKEN_EXPIRED")

    def _stale_token_request():
        # Deliberately does NOT touch ctx["actor_id"]'s own token_version
        # -- that account's token is reused by every later case in this
        # same run (`ctx["headers"]`), and bumping its version here would
        # silently invalidate it for every case that runs after this one.
        # A throwaway second actor keeps this row's side effect isolated.
        stale_actor_id, stale_token = ctx["make_actor"]("MEDICAL_OFFICER", ctx["org_units"]["BLOCK"])
        ctx["db"].exec(sqltext("UPDATE users SET token_version = token_version + 1 WHERE id = :id"),
                        params={"id": str(stale_actor_id)})
        ctx["db"].commit()
        return c.get("/me", headers=auth_header(stale_token))

    add("any_stale_token_version", _stale_token_request, 401, "TOKEN_STALE")

    add("any_valid_token_no_permission_does_not_name_the_permission",
        lambda: c.get("/audit", headers=h),
        403, "PERMISSION_DENIED",
        lambda r: "audit:read" not in r.text and "audit" not in _detail(r).get("detail", "").lower())

    add("any_malformed_json_body",
        lambda: c.post("/login", headers={"Content-Type": "application/json"}, data="{not valid json"),
        400, "MALFORMED_JSON")

    add("any_payload_over_1mb",
        lambda: c.post("/login", headers={"Content-Type": "application/json"},
                        data='{"mobile":"+919876500002","password":"' + ("a" * (1024 * 1024 + 10)) + '"}'),
        413, "PAYLOAD_TOO_LARGE")

    return cases


def test_validation_matrix(ctx):
    cases = _build_cases(ctx)
    failures = []
    for case_id, request_fn, expected_status, expected_code, extra_check in cases:
        response = request_fn()
        detail = _detail(response)
        actual_code = detail.get("code")
        ok = response.status_code == expected_status
        if ok and expected_code is not None:
            ok = actual_code == expected_code
        if ok and extra_check is not None:
            ok = bool(extra_check(response))
        if not ok:
            failures.append(
                f"{case_id}: expected status={expected_status} code={expected_code!r}, "
                f"got status={response.status_code} code={actual_code!r} body={response.text[:300]!r}"
            )
        else:
            print(f"PASS  {case_id} -> HTTP {response.status_code} code={actual_code!r}")

    assert not failures, "Validation matrix failures:\n" + "\n".join(failures)
