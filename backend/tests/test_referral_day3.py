"""Triage-to-referral linkage, synthetic breach detection, and the full
referral transition path including the recovery branch.

============================================================
PART 1 GAP, FOUND BEFORE WRITING ANY TEST -- READ THIS FIRST
============================================================
The task this file was built from assumes `referral.triage_id` exists as
a real column pointing a referral at the triage encounter that led to
it, and that `POST /referrals/` derives `referral.urgency` from that
linked triage encounter's own `decision.urgency` via a fixed mapping
(IMMEDIATE->EMERGENCY, WITHIN_2H/WITHIN_24H->URGENT, WITHIN_72H->
PRIORITY, WITHIN_7D/ROUTINE->ROUTINE). Neither exists in this codebase
today -- confirmed directly, not assumed:
  - `grep -rn "triage_id" app/ alembic/` -- zero hits, anywhere.
  - `app/models/referral.py` has no `triage_id` field at all.
  - `app/api/routes/referrals.py`'s `create_referral` takes `urgency` as
    a plain, client-supplied field on the `Referral` request body (the
    whole model IS the request body there) -- nothing derives it from
    any triage encounter, because there is no link to derive it FROM.

This is NOT fixed here. Adding a migration for a new FK column is out
of scope for a test file ("one concern per change" -- every earlier
task today's own convention), and doing it silently, without being
asked, would be worse than leaving the gap visible. Instead, this file:
  1. States the gap plainly (this docstring, and again inline below).
  2. Tests what CAN be tested today: if a caller does the urgency
     mapping THEMSELVES (the only way it happens at all right now) and
     submits the correctly-mapped value, `due_at` comes out correct --
     i.e. `compute_due_at`/`URGENCY_WINDOWS` themselves are correct and
     exercised through the real HTTP path.
  2. Also asserts the mapping table's actual values (IMMEDIATE->EMERGENCY
     etc.) as a pure, standalone table -- the ONE place in this codebase
     that mapping exists at all, until a route derives it automatically.
  3. PROVES THE GAP THAT MATTERS, not just documents it in prose: creates
     a referral whose `urgency` is INCONSISTENT with its patient's own
     just-recorded EMERGENCY/IMMEDIATE triage decision (submits ROUTINE
     instead) and shows the API accepts it with no cross-check at all
     (200, not rejected) -- this IS the "a triage that says immediate
     producing a referral due in 7 days is a silent, serious clinical
     bug and it will not announce itself" scenario the task warns about,
     demonstrated as currently, actually possible today, not
     hypothetical. See test_part1_gap_urgency_inconsistency_not_caught
     below.
============================================================

PARTS 2-5 assume nothing broken -- built directly against the real
`app/models/referral_state.py` (ALLOWED_TRANSITIONS,
TRANSITION_REQUIRED_FIELDS), `app/services/referral/breach.py`
(URGENCY_WINDOWS, compute_due_at, is_breached), and
`app/jobs/breach_detection.py` (detect_breaches, async, returns
{"newly_breached", "escalated", "checked"}).

Uses this repo's existing conventions (`raising_client`/`db`/
`org_units`/`make_actor` -- same as every other test file built today).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import text as sqltext

from app.api.routes import dashboard as dashboard_module
from app.jobs.breach_detection import detect_breaches
from app.main import app
from app.services.referral.breach import URGENCY_WINDOWS, compute_due_at
from tests._fixtures import auth_header

# The mapping this task's own spec defines. Lives ONLY here -- see the
# module docstring's Part 1 gap note: nothing in app/ derives this
# automatically today.
_TRIAGE_URGENCY_TO_REFERRAL_URGENCY: dict[str, str] = {
    "IMMEDIATE": "EMERGENCY",
    "WITHIN_2H": "URGENT",
    "WITHIN_24H": "URGENT",
    "WITHIN_72H": "PRIORITY",
    "WITHIN_7D": "ROUTINE",
    "ROUTINE": "ROUTINE",
}


@pytest.fixture
def raising_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _make_patient(client: TestClient, headers: dict, facility_id: str, name: str) -> str:
    r = client.post("/patients/", headers=headers, json={
        "name": name, "age": 29, "village": "V",
        "phone": "+919" + str(uuid.uuid4().int)[:9], "facility_id": facility_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_triage(client: TestClient, headers: dict, patient_id: str, facility_id: str, triage_input: dict) -> dict:
    r = client.post("/triage/", headers=headers, json={
        "patient_id": patient_id, "facility_id": facility_id,
        "triage_disposition": "day3 referral linkage probe",
        "protocol": triage_input["protocol"],
        "vitals": triage_input.get("vitals", {}),
        "danger_signs": triage_input.get("danger_signs", []),
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_referral(client: TestClient, headers: dict, patient_id: str, facility_id: str,
                    destination: str, urgency: str) -> dict:
    r = client.post("/referrals/", headers=headers, json={
        "patient_id": patient_id, "from_facility_id": facility_id,
        "destination_facility_id": destination,
        "reason": "day3 referral linkage probe", "urgency": urgency,
        "receiving_unit": "General OPD", "owner": "Tester",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _transition(client: TestClient, headers: dict, referral_id: str, status: str, body: dict | None = None):
    return client.patch(f"/referrals/{referral_id}/status?status={status}", headers=headers, json=body or {})


def _transitions_for(db, referral_id: str) -> list[tuple]:
    # Real column name is `occurred_at` (migration d4f1c9b7a582), not
    # `created_at` -- confirmed against the migration's own create_table
    # after this line first raised UndefinedColumn.
    return db.exec(sqltext(
        "SELECT from_status, to_status FROM referral_transitions WHERE referral_id = :r ORDER BY occurred_at"
    ), params={"r": referral_id}).all()


# ============================================================
# PART 1 -- linkage gap + the mapping table + due_at correctness.
# ============================================================

# R2 (REFER/WITHIN_24H), R3/R4/R5 (EMERGENCY/IMMEDIATE), R6 (REFER/WITHIN_24H,
# insufficient_data) -- R1 is MANAGE_HERE, excluded (task's own scope: "REFER
# and EMERGENCY cases").
_REFER_OR_EMERGENCY_CASES = [
    {"name": "R2_BORDERLINE_ANC", "protocol": "ANC", "vitals": {"bp_systolic": 142, "bp_diastolic": 92}},
    {"name": "R3_EMERGENCY_HYPERTENSIVE", "protocol": "ANC", "vitals": {"bp_systolic": 172, "bp_diastolic": 116}},
    {"name": "R4_EMERGENCY_DANGER_SIGN", "protocol": "ANC", "vitals": {"bp_systolic": 130, "bp_diastolic": 84},
     "danger_signs": ["convulsions"]},
    {"name": "R5_EMERGENCY_UNIVERSAL_VITAL", "protocol": "NCD", "vitals": {"spo2": 86, "bp_systolic": 130, "bp_diastolic": 84}},
    {"name": "R6_INSUFFICIENT_DATA", "protocol": "ANC", "vitals": {}},
]


def test_part1_no_triage_id_column_exists_on_referral(raising_client, org_units, make_actor, db):
    """Confirms the gap live, against the real running app/DB -- not just
    the static grep in this file's own docstring."""
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    patient_id = _make_patient(raising_client, headers, facility_id, "Part1 No Link Probe")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")

    assert "triage_id" not in referral, (
        "referral.triage_id does not exist in this codebase's response shape -- "
        "confirmed here live, matching the static grep in this file's own module docstring."
    )
    columns = db.exec(sqltext(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'referral'"
    )).all()
    column_names = {c[0] for c in columns}
    assert "triage_id" not in column_names, "no triage_id column exists on the real `referral` table either"


@pytest.mark.parametrize("case", _REFER_OR_EMERGENCY_CASES, ids=[c["name"] for c in _REFER_OR_EMERGENCY_CASES])
def test_part1_mapped_urgency_produces_correct_due_at(case, raising_client, org_units, make_actor):
    """The one thing that CAN be verified today: if the caller applies
    the mapping themselves (the only mechanism that exists) and submits
    the correctly-mapped urgency, compute_due_at/URGENCY_WINDOWS -- the
    real due_at machinery -- produce the correct due_at through the real
    HTTP path. This is NOT the same as "the system enforces the mapping"
    -- see test_part1_gap_urgency_inconsistency_not_caught below for the
    proof that it does not."""
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())

    patient_id = _make_patient(raising_client, headers, facility_id, f"Part1 {case['name']}")
    triage = _make_triage(raising_client, headers, patient_id, facility_id, case)
    triage_urgency = triage["decision"]["urgency"]
    mapped_urgency = _TRIAGE_URGENCY_TO_REFERRAL_URGENCY[triage_urgency]

    before = datetime.now(timezone.utc)
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), mapped_urgency)
    after = datetime.now(timezone.utc)

    assert referral["urgency"] == mapped_urgency
    initiated_at = datetime.fromisoformat(referral["initiated_at"])
    due_at = datetime.fromisoformat(referral["due_at"])

    expected_min = compute_due_at(before, mapped_urgency)
    expected_max = compute_due_at(after, mapped_urgency)
    assert expected_min <= due_at <= expected_max, (
        f"{case['name']}: triage_urgency={triage_urgency!r} mapped_urgency={mapped_urgency!r} "
        f"due_at={due_at!r} not within [{expected_min!r}, {expected_max!r}]"
    )
    assert due_at == initiated_at + URGENCY_WINDOWS[mapped_urgency]


def test_part1_mapping_table_actual_values():
    """The mapping table itself, as a pure fact check -- no HTTP, no DB.
    Fails loudly if anyone ever edits the dict above inconsistently with
    the spec this task was built from."""
    expected = {
        "IMMEDIATE": "EMERGENCY",
        "WITHIN_2H": "URGENT",
        "WITHIN_24H": "URGENT",
        "WITHIN_72H": "PRIORITY",
        "WITHIN_7D": "ROUTINE",
        "ROUTINE": "ROUTINE",
    }
    assert _TRIAGE_URGENCY_TO_REFERRAL_URGENCY == expected


def test_part1_gap_urgency_inconsistency_not_caught(raising_client, org_units, make_actor):
    """THE finding this whole Part exists to surface: a referral for a
    patient whose triage just said EMERGENCY/IMMEDIATE, submitted with
    urgency=ROUTINE (a 7-day SLA window), is accepted with no error and
    no warning -- because nothing links the referral back to the triage
    encounter to check consistency. This is the exact "silent, serious
    clinical bug" scenario described in this task's own text, proven
    live rather than left as a hypothetical."""
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())

    patient_id = _make_patient(raising_client, headers, facility_id, "Part1 Gap Probe")
    triage = _make_triage(raising_client, headers, patient_id, facility_id,
                           {"protocol": "ANC", "vitals": {"bp_systolic": 172, "bp_diastolic": 116}})
    assert triage["decision"]["disposition"] == "EMERGENCY"
    assert triage["decision"]["urgency"] == "IMMEDIATE"

    # Deliberately WRONG urgency -- the mapped value would be EMERGENCY
    # (1-hour window); this submits ROUTINE (7-day window) instead.
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")

    assert referral["urgency"] == "ROUTINE", (
        "the API accepted urgency=ROUTINE for a patient with an EMERGENCY/IMMEDIATE triage "
        "decision moments earlier, with no cross-check -- this IS the gap."
    )
    due_at = datetime.fromisoformat(referral["due_at"])
    initiated_at = datetime.fromisoformat(referral["initiated_at"])
    assert due_at - initiated_at >= timedelta(days=6), (
        "the referral's own due_at reflects a 7-day ROUTINE window despite the linked patient's "
        "triage having said this needs attention within the hour -- a silent, undetected mismatch."
    )


# ============================================================
# PART 2 -- controlled synthetic breach (backdate the row, never the
# system clock).
# ============================================================

@pytest.mark.asyncio
async def test_part2_synthetic_breach_detect_dashboard_idempotent(raising_client, db, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    org_unit_id = str(org_units["BLOCK"])

    patient_id = _make_patient(raising_client, headers, facility_id, "Part2 Breach Probe")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "URGENT")
    referral_id = referral["id"]

    # ---- baseline dashboard breached count, BEFORE backdating ----
    baseline_resp = raising_client.get(f"/dashboard/facility/{org_unit_id}", headers=headers)
    assert baseline_resp.status_code == 200, baseline_resp.text
    baseline_breached = baseline_resp.json()["metrics"]["breached"]["numerator"]

    # REAL FINDING, not a test artifact: app/api/routes/dashboard.py's own
    # _DashboardCache has a 60s TTL keyed on (org_unit_id, date). The
    # `breached`/`open_referrals` metrics it caches are POINT-IN-TIME
    # (computed from `now`, not scoped by the `date` key at all) -- so a
    # write to `referral` (e.g. this test's own backdate + detect_breaches
    # call, or a real demo running the breach job) will NOT be reflected
    # on the dashboard for up to 60 seconds after the FIRST request for
    # that facility/day, even though the underlying data changed
    # immediately. Confirmed live: the "after" assertion below failed
    # with after_breached == baseline_breached (both 0) before this
    # explicit cache-clear was added. Clearing it here isn't gaming the
    # test -- it's how a demo operator would need to work around this
    # same staleness (wait 60s, or restart the process) if they hit it
    # live. Reported plainly in this task's own delivery notes.
    dashboard_module._cache._store.clear()

    # ---- backdate the row directly via SQL -- never touch the system
    # clock (breaks JWT validation and everything else on the machine,
    # per this task's own explicit instruction). ----
    new_initiated_at = datetime.now(timezone.utc) - timedelta(hours=30)
    new_due_at = compute_due_at(new_initiated_at, "URGENT")  # ~ now - 6h
    assert new_due_at < datetime.now(timezone.utc) - timedelta(hours=5), "sanity: due_at must be well in the past"

    db.exec(sqltext(
        "UPDATE referral SET initiated_at = :initiated_at, due_at = :due_at WHERE id = :id"
    ), params={"initiated_at": new_initiated_at, "due_at": new_due_at, "id": referral_id})
    db.commit()

    # ---- run the job (async, direct call -- no HTTP endpoint for it) ----
    result_1 = await detect_breaches(db)
    assert result_1["newly_breached"] >= 1, f"expected at least our referral to be newly breached: {result_1}"

    # ---- GET /referrals/exceptions: breached_at set, escalation.stage >= 1 ----
    exceptions_resp = raising_client.get("/referrals/exceptions", headers=headers)
    assert exceptions_resp.status_code == 200, exceptions_resp.text
    items = {item["referral_id"]: item for item in exceptions_resp.json()["items"]}
    assert referral_id in items, f"referral {referral_id} not present in GET /referrals/exceptions"
    item = items[referral_id]
    assert item["breached_at"] is not None, "breached_at must be set after detect_breaches"
    assert item["escalation"]["stage"] >= 1, f"expected escalation.stage >= 1, got {item['escalation']}"

    # ---- dashboard breached count incremented by EXACTLY 1 ----
    after_resp = raising_client.get(f"/dashboard/facility/{org_unit_id}", headers=headers)
    assert after_resp.status_code == 200, after_resp.text
    after_breached = after_resp.json()["metrics"]["breached"]["numerator"]
    assert after_breached == baseline_breached + 1, (
        f"expected breached count to increase by exactly 1: baseline={baseline_breached} after={after_breached}"
    )

    # ---- escalation_stage snapshot before the second run ----
    stage_before = db.exec(sqltext(
        "SELECT escalation_stage FROM referral WHERE id = :id"
    ), params={"id": referral_id}).first()[0]

    # ---- run detect_breaches a SECOND time -- must NOT escalate again ----
    result_2 = await detect_breaches(db)
    stage_after = db.exec(sqltext(
        "SELECT escalation_stage FROM referral WHERE id = :id"
    ), params={"id": referral_id}).first()[0]

    assert stage_after == stage_before, (
        f"escalation_stage changed on a second detect_breaches call with no time passing: "
        f"before={stage_before} after={stage_after}"
    )
    # This specific referral must contribute 0 to the second run's own
    # newly_breached count -- other test data in the shared TRUNCATE-per-
    # test DB should not exist at this point, but assert our own referral's
    # state directly rather than assuming the global counter is 0 for
    # every possible referral in the table.
    referral_still_breached_once = db.exec(sqltext(
        "SELECT breached_at FROM referral WHERE id = :id"
    ), params={"id": referral_id}).first()[0]
    assert referral_still_breached_once is not None
    assert result_2["newly_breached"] == 0, f"second run must not newly-breach anything: {result_2}"


# ============================================================
# PART 3 -- full forward transition path over HTTP.
# ============================================================

def test_part3_full_transition_path_all_seven_200_and_write_transitions(raising_client, db, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())

    patient_id = _make_patient(raising_client, headers, facility_id, "Part3 Full Path")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")
    referral_id = referral["id"]

    steps = [
        ("SLOT_BOOKED", {"slot_datetime": "2026-09-25T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"])}),
        ("TRANSPORT_ARRANGED", {"transport_mode": "AMBULANCE"}),
        ("ARRIVED", {"arrival_scan_ref": "ABHA-SCAN-001"}),
        ("CONSULTED", {"consulted_by_user_id": str(uuid.uuid4())}),
        ("BACK_REFERRED", {"back_referral_note": "Follow-up at sub-centre"}),
        ("CLOSED", {}),
    ]

    responses = []
    prior_status = "INITIATED"
    for status, body in steps:
        r = _transition(raising_client, headers, referral_id, status, body)
        responses.append((status, r.status_code, r.text[:200]))
        assert r.status_code == 200, f"{prior_status} -> {status} failed: {r.text}"

        transitions = _transitions_for(db, referral_id)
        matching = [t for t in transitions if t[0] == prior_status and t[1] == status]
        assert matching, (
            f"no referral_transitions row found for {prior_status} -> {status}; "
            f"rows so far: {transitions}"
        )
        prior_status = status

    # All 7 (the creation-time INITIATED transition + the 6 walked here)
    # rows present, in order.
    all_transitions = _transitions_for(db, referral_id)
    assert len(all_transitions) == 7, f"expected 7 transition rows (1 creation + 6 walked), got {all_transitions}"

    # Printed, not returned -- pytest 8+ warns (and a future version will
    # error) on a test function returning non-None. -v -s shows this.
    print(f"\nPart 3 transition walk responses: {responses}")


# ============================================================
# PART 4 -- rejections, exact status + code.
# ============================================================

def test_part4_initiated_to_closed_is_409_invalid_transition_with_allowed_next(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    patient_id = _make_patient(raising_client, headers, facility_id, "Part4 Invalid Transition")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")

    r = _transition(raising_client, headers, referral["id"], "CLOSED")
    assert r.status_code == 409, r.text
    body = r.json()["detail"]
    assert body["code"] == "INVALID_TRANSITION"
    assert "allowed_next" in body and body["allowed_next"], "allowed_next must be listed, non-empty"


def test_part4_closed_to_arrived_is_409_terminal_state(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    patient_id = _make_patient(raising_client, headers, facility_id, "Part4 Terminal State")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")
    referral_id = referral["id"]

    # Walk to CLOSED via the shortest legal path: INITIATED -> NOT_ARRIVED -> LOST -> CLOSED.
    assert _transition(raising_client, headers, referral_id, "NOT_ARRIVED").status_code == 200
    r = _transition(raising_client, headers, referral_id, "LOST", {"loss_reason": "unreachable"})
    assert r.status_code == 200, r.text
    r = _transition(raising_client, headers, referral_id, "CLOSED")
    assert r.status_code == 200, r.text

    r = _transition(raising_client, headers, referral_id, "ARRIVED", {"arrival_scan_ref": "X"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "TERMINAL_STATE"


def test_part4_arrived_without_proof_is_422_arrival_proof_required(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    patient_id = _make_patient(raising_client, headers, facility_id, "Part4 Arrival Proof")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")
    referral_id = referral["id"]

    assert _transition(raising_client, headers, referral_id, "SLOT_BOOKED", {
        "slot_datetime": "2026-09-25T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"]),
    }).status_code == 200

    r = _transition(raising_client, headers, referral_id, "ARRIVED")  # no proof
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "ARRIVAL_PROOF_REQUIRED"


def test_part4_refused_without_reason_is_422_transition_field_required(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    patient_id = _make_patient(raising_client, headers, facility_id, "Part4 Refused Reason")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "ROUTINE")
    referral_id = referral["id"]

    assert _transition(raising_client, headers, referral_id, "NOT_ARRIVED").status_code == 200
    assert _transition(raising_client, headers, referral_id, "TRACED", {
        "traced_by_user_id": str(uuid.uuid4()),
    }).status_code == 200

    r = _transition(raising_client, headers, referral_id, "REFUSED")  # no refusal_reason
    assert r.status_code == 422, r.text
    body = r.json()["detail"]
    assert body["code"] == "TRANSITION_FIELD_REQUIRED"
    assert body["field"] == "refusal_reason"


# ============================================================
# PART 5 -- the recovery branch.
# ============================================================

def test_part5_recovery_branch_reschedule_resets_breach_and_recomputes_due_at(raising_client, db, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())
    patient_id = _make_patient(raising_client, headers, facility_id, "Part5 Recovery Branch")
    referral = _make_referral(raising_client, headers, patient_id, facility_id, str(org_units["PHC"]), "URGENT")
    referral_id = referral["id"]

    # INITIATED -> NOT_ARRIVED
    r = _transition(raising_client, headers, referral_id, "NOT_ARRIVED")
    assert r.status_code == 200, r.text

    # -> TRACED
    r = _transition(raising_client, headers, referral_id, "TRACED", {"traced_by_user_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text

    # -> RESCHEDULED -- the key assertion.
    before_reschedule = datetime.now(timezone.utc)
    r = _transition(raising_client, headers, referral_id, "RESCHEDULED")
    after_reschedule = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    rescheduled_body = r.json()

    assert rescheduled_body["breached_at"] is None, "breached_at must be reset to NULL on RESCHEDULED"

    original_initiated_at = datetime.fromisoformat(referral["initiated_at"])
    due_at = datetime.fromisoformat(rescheduled_body["due_at"])
    expected_min = compute_due_at(before_reschedule, "URGENT")
    expected_max = compute_due_at(after_reschedule, "URGENT")
    assert expected_min <= due_at <= expected_max, (
        f"due_at={due_at!r} not recomputed from the reschedule instant "
        f"(expected within [{expected_min!r}, {expected_max!r}])"
    )
    # And explicitly NOT computed from the original initiated_at.
    due_at_if_from_original = compute_due_at(original_initiated_at, "URGENT")
    assert due_at != due_at_if_from_original, (
        "due_at matches what it would be if (incorrectly) computed from the ORIGINAL "
        "initiated_at rather than the reschedule instant"
    )

    # -> SLOT_BOOKED -> ARRIVED -> CONSULTED -> CLOSED, completing the walk.
    r = _transition(raising_client, headers, referral_id, "SLOT_BOOKED", {
        "slot_datetime": "2026-09-25T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"]),
    })
    assert r.status_code == 200, r.text

    r = _transition(raising_client, headers, referral_id, "ARRIVED", {"arrival_scan_ref": "ABHA-SCAN-RECOVERY"})
    assert r.status_code == 200, r.text

    r = _transition(raising_client, headers, referral_id, "CONSULTED", {"consulted_by_user_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text

    r = _transition(raising_client, headers, referral_id, "CLOSED")
    assert r.status_code == 200, r.text

    transitions = _transitions_for(db, referral_id)
    expected_path = [
        (None, "INITIATED"), ("INITIATED", "NOT_ARRIVED"), ("NOT_ARRIVED", "TRACED"),
        ("TRACED", "RESCHEDULED"), ("RESCHEDULED", "SLOT_BOOKED"), ("SLOT_BOOKED", "ARRIVED"),
        ("ARRIVED", "CONSULTED"), ("CONSULTED", "CLOSED"),
    ]
    actual_path = [(t[0], t[1]) for t in transitions]
    assert actual_path == expected_path, f"recovery branch path mismatch: {actual_path}"
