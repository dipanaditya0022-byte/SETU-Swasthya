"""Six locked triage reference cases (backend/tests/fixtures/triage/R1-R6)
-- "these six are the demo's clinical credibility. They must return
identical output every single run."

============================================================
NOT VALIDATED CLINICAL PROTOCOL -- READ BEFORE TRUSTING THESE NUMBERS
============================================================
The thresholds encoded in these six fixtures (and in
app/services/triage/fallback.py, which they lock down) are
ILLUSTRATIVE. They have NOT been reviewed or signed off by a Clinical
Governance Committee and must not be presented, demoed, or deployed as
validated clinical protocol. This file's job is to prove the ENGINE is
deterministic and wired correctly end-to-end -- it is not, and cannot
be, a clinical safety review.
============================================================

TWO LEVELS, per case, both asserted against the SAME fixture's `expect`:
  Level 1 (unit)  -- FallbackTriageEngine().evaluate(TriageInput(...))
                     called directly. Fast, isolates a rule bug from a
                     wiring bug.
  Level 2 (API)   -- a real HTTP POST /triage/ against this app, same
                     input, through auth/scope/persistence/serialization.
                     "A rule that works in Python and fails through the
                     endpoint is still a broken demo" -- this is the
                     level that actually matters for the demo.
Every case asserts Level 1 == Level 2 on disposition/urgency -- not just
each against `expect` independently.

PLUS, per case, after the Level 2 call:
  - PERSISTENCE: what's actually in `triageencounter` for the returned
    id must equal what the API response said, field for field. (Real
    table name -- confirmed directly against app/models/triage_encounter.py;
    the task's own text says `triage`, which is not a table in this
    schema.)
  - DETERMINISM: the API call repeated three times must produce
    byte-identical `decision` objects apart from `evaluated_at`.
  - ENGINE: whichever engine actually answered (`decision.engine`) is
    asserted AND printed -- if it's "fallback" (it is, in this repo's
    default `.env`: no TRIAGE_ENGINE override, TRIAGE_ENGINE=auto probes
    SD's rule engine via app/services/triage/factory.py, which isn't
    importable in this repo -- confirmed by the factory's own probe log
    line), the test output says so plainly rather than treating "an
    engine ran" as good enough.

Fixtures use this repo's existing conventions (`raising_client`/`db`/
`org_units`/`make_actor` -- same as tests/test_atomicity.py,
tests/test_validation_matrix.py, tests/test_error_contract.py, all
already in this repo).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import text as sqltext

from app.main import app
from app.services.triage.fallback import FallbackTriageEngine
from app.services.triage.port import TriageInput
from tests._fixtures import auth_header

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "triage"
_FIXTURE_FILES = [
    "R1_normal_anc.json",
    "R2_borderline_anc.json",
    "R3_emergency_hypertensive.json",
    "R4_emergency_danger_sign.json",
    "R5_emergency_universal_vital.json",
    "R6_insufficient_data.json",
]


def _load_fixtures() -> list[dict]:
    fixtures = []
    for filename in _FIXTURE_FILES:
        with open(_FIXTURES_DIR / filename) as f:
            fixtures.append(json.load(f))
    return fixtures


_FIXTURES = _load_fixtures()


@pytest.fixture
def raising_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _triage_input(fixture_input: dict) -> TriageInput:
    return TriageInput(
        protocol=fixture_input["protocol"],
        is_pregnant=fixture_input.get("is_pregnant", False),
        gestational_weeks=fixture_input.get("gestational_weeks"),
        vitals=fixture_input.get("vitals", {}),
        symptoms=fixture_input.get("symptoms", []),
        danger_signs=fixture_input.get("danger_signs", []),
    )


def _assert_matches_expect(disposition: str, urgency: str, expect: dict, case_name: str) -> None:
    assert disposition == expect["disposition"], (
        f"{case_name}: expected disposition {expect['disposition']!r}, got {disposition!r}"
    )
    assert urgency == expect["urgency"], (
        f"{case_name}: expected urgency {expect['urgency']!r}, got {urgency!r}"
    )


# ============================================================
# Level 1 -- unit, direct engine call.
# ============================================================

@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["name"] for f in _FIXTURES])
def test_level1_unit_engine_matches_expect(fixture):
    engine = FallbackTriageEngine()
    result = engine.evaluate(_triage_input(fixture["input"]))

    _assert_matches_expect(result.disposition, result.urgency, fixture["expect"], fixture["name"])

    if "insufficient_data" in fixture["expect"]:
        assert result.insufficient_data == fixture["expect"]["insufficient_data"], (
            f"{fixture['name']}: insufficient_data mismatch"
        )
    if "missing_fields_contains" in fixture["expect"]:
        assert fixture["expect"]["missing_fields_contains"] in result.missing_fields, (
            f"{fixture['name']}: expected {fixture['expect']['missing_fields_contains']!r} in missing_fields"
        )

    # R6's OWN point, asserted explicitly and separately from the
    # disposition-equality check above, per this task's own instruction
    # ("ASSERT disposition != MANAGE_HERE explicitly. That assertion is
    # the point."):
    if fixture["name"] == "R6_INSUFFICIENT_DATA":
        assert result.disposition != "MANAGE_HERE", (
            "R6: insufficient data must NEVER silently read as MANAGE_HERE -- "
            "a missing vital is a clinical situation, not something to wave through."
        )


# ============================================================
# Level 2 -- API, real HTTP POST /triage/. Also does the persistence
# check (same request already made) and reports the engine.
# ============================================================

def _post_triage(client: TestClient, headers: dict, patient_id: str, facility_id: str, fixture_input: dict):
    return client.post("/triage/", headers=headers, json={
        "patient_id": patient_id,
        "facility_id": facility_id,
        "triage_disposition": "reference case probe",
        "protocol": fixture_input["protocol"],
        "is_pregnant": fixture_input.get("is_pregnant", False),
        "gestational_weeks": fixture_input.get("gestational_weeks"),
        "vitals": fixture_input.get("vitals", {}),
        "symptoms": fixture_input.get("symptoms", []),
        "danger_signs": fixture_input.get("danger_signs", []),
    })


@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["name"] for f in _FIXTURES])
def test_level2_api_matches_expect_and_unit_and_persistence(fixture, raising_client, db, org_units, make_actor, capsys):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(uuid.uuid4())

    patient_resp = raising_client.post("/patients/", headers=headers, json={
        "name": f"Reference Case {fixture['name']}", "age": 28, "village": "V",
        "phone": "+919" + str(uuid.uuid4().int)[:9], "facility_id": facility_id,
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    api_resp = _post_triage(raising_client, headers, patient_id, facility_id, fixture["input"])
    assert api_resp.status_code == 200, api_resp.text
    api_body = api_resp.json()
    api_decision = api_body["decision"]

    # ---- API vs expect ----
    _assert_matches_expect(api_decision["disposition"], api_decision["urgency"], fixture["expect"], fixture["name"])
    if "insufficient_data" in fixture["expect"]:
        assert api_decision["insufficient_data"] == fixture["expect"]["insufficient_data"]
    if "missing_fields_contains" in fixture["expect"]:
        assert fixture["expect"]["missing_fields_contains"] in api_decision["missing_fields"]
    if fixture["name"] == "R6_INSUFFICIENT_DATA":
        assert api_decision["disposition"] != "MANAGE_HERE"

    # ---- Unit vs API: identical disposition/urgency, not just both
    # separately matching `expect`. ----
    unit_result = FallbackTriageEngine().evaluate(_triage_input(fixture["input"]))
    assert unit_result.disposition == api_decision["disposition"], (
        f"{fixture['name']}: UNIT/API DISPOSITION MISMATCH -- "
        f"unit={unit_result.disposition!r} api={api_decision['disposition']!r}"
    )
    assert unit_result.urgency == api_decision["urgency"], (
        f"{fixture['name']}: UNIT/API URGENCY MISMATCH -- "
        f"unit={unit_result.urgency!r} api={api_decision['urgency']!r}"
    )

    # ---- Persistence check: DB row must equal the API response,
    # field for field. Real table/column names, confirmed against
    # app/models/triage_encounter.py before writing this. ----
    row = db.exec(sqltext(
        "SELECT disposition, urgency, insufficient_data, engine, protocol_version "
        "FROM triageencounter WHERE id = :id"
    ), params={"id": api_body["id"]}).first()
    assert row is not None, f"{fixture['name']}: no triageencounter row found for id={api_body['id']}"
    db_disposition, db_urgency, db_insufficient_data, db_engine, db_protocol_version = row

    assert db_disposition == api_decision["disposition"], f"{fixture['name']}: stored disposition != API disposition"
    assert db_urgency == api_decision["urgency"], f"{fixture['name']}: stored urgency != API urgency"
    assert db_insufficient_data == api_decision["insufficient_data"], f"{fixture['name']}: stored insufficient_data != API"
    assert db_engine == api_decision["engine"], f"{fixture['name']}: stored engine != API engine"
    assert db_protocol_version == api_decision["protocol_version"], f"{fixture['name']}: stored protocol_version != API"

    # ---- Engine check: report plainly, don't swallow it. ----
    with capsys.disabled():
        print(f"\n[{fixture['name']}] engine={api_decision['engine']!r}")
    if api_decision["engine"] == "fallback":
        with capsys.disabled():
            print(f"[{fixture['name']}] NOTE: this case was answered by the FALLBACK engine, "
                  f"not SD's rule engine. The demo must know which logic it is showing.")


# ============================================================
# Determinism check -- all six, three times each through the API,
# byte-identical decision objects apart from evaluated_at.
# ============================================================

def test_determinism_three_runs_identical_except_evaluated_at(raising_client, org_units, make_actor, capsys):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)

    mismatches = []
    for fixture in _FIXTURES:
        facility_id = str(uuid.uuid4())
        decisions = []
        for run in range(3):
            patient_resp = raising_client.post("/patients/", headers=headers, json={
                "name": f"Determinism {fixture['name']} run{run}", "age": 28, "village": "V",
                "phone": "+919" + str(uuid.uuid4().int)[:9], "facility_id": facility_id,
            })
            assert patient_resp.status_code == 200, patient_resp.text
            patient_id = patient_resp.json()["id"]

            api_resp = _post_triage(raising_client, headers, patient_id, facility_id, fixture["input"])
            assert api_resp.status_code == 200, api_resp.text
            decisions.append(api_resp.json()["decision"])

        # Compare all three with evaluated_at stripped.
        stripped = [{k: v for k, v in d.items() if k != "evaluated_at"} for d in decisions]
        if not (stripped[0] == stripped[1] == stripped[2]):
            mismatches.append((fixture["name"], stripped))

        with capsys.disabled():
            print(f"[{fixture['name']}] 3 runs identical (excl. evaluated_at): {stripped[0] == stripped[1] == stripped[2]}")

    assert not mismatches, f"Non-deterministic case(s): {mismatches}"
