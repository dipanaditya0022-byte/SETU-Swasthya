"""GET /dashboard/facility/{org_unit_id} -- Dashboard step.

DT1-DT5 are the five cases this step's own task specified. Every
directly-inserted `Referral`/`TriageEncounter`/`Patient` row in this file
supplies `org_unit_id`/`created_by_user_id` explicitly (real, FK-constrained
NOT NULL columns, migration 9d5f6b3e0a71), same direct-insert pattern as
tests/test_breach_detection.py's own `_make_referral`.

TIMESTAMPS ARE FULLY CONTROLLED, NOT WALL-CLOCK-DEPENDENT WHERE IT MATTERS:
`open_referrals`/`breached` are evaluated against the request's own real
`now()` (they are not `date`-scoped at all -- see app/api/routes/
dashboard.py's own metric docstrings), so their fixture rows use `due_at`
offsets from `datetime.now(timezone.utc)` taken at test-body time.
`triage_today`/`synced_today` ARE `date`-scoped, so this file pins a fixed,
far-past `_TEST_DATE` (2020-01-15) and computes the exact IST-day UTC
window by hand, then sets every relevant row's `created_at`/`synced_at`
explicitly inside or outside that window -- independent of whenever this
suite actually runs, so `_TEST_DATE` never accidentally collides with any
row's real insert-time default.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import event
from sqlmodel import Session

from app.db.database import engine
from app.models.patient import Patient
from app.models.referral import Referral
from app.models.referral_state import ReferralState
from app.models.triage_encounter import TriageEncounter
from tests._fixtures import auth_header

# ============================================================
# Fixed test date + hand-computed IST day window (see module docstring).
# Must match app/api/routes/dashboard.py's own _FACILITY_TZ_OFFSET
# (IST, UTC+05:30) exactly -- if that constant ever changes, this test's
# own independently-computed window must be updated to match, which is
# the point: this is an independent re-derivation, not a shared constant
# import, so a silent drift in the route's own math would be caught here.
# ============================================================
_TEST_DATE = date(2020, 1, 15)
_IST_OFFSET = timedelta(hours=5, minutes=30)
_DAY_START_UTC = datetime(2020, 1, 14, 18, 30)  # 2020-01-15 00:00 IST
_DAY_END_UTC = datetime(2020, 1, 15, 18, 30)  # 2020-01-16 00:00 IST
_INSIDE = _DAY_START_UTC + timedelta(hours=4)  # safely inside the window
_OUTSIDE = _DAY_START_UTC - timedelta(hours=4)  # the previous IST day


def _make_referral(db: Session, *, org_unit_id, created_by_user_id, status: ReferralState,
                    due_at, created_at=None) -> Referral:
    referral = Referral(
        patient_id=uuid.uuid4(), from_facility_id=uuid.uuid4(), destination_facility_id=uuid.uuid4(),
        reason="Test referral", urgency="ROUTINE", status=status,
        initiated_at=datetime.now(timezone.utc), due_at=due_at,
        org_unit_id=org_unit_id, created_by_user_id=created_by_user_id,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


def _make_triage(db: Session, *, org_unit_id, created_by_user_id, created_at) -> TriageEncounter:
    encounter = TriageEncounter(
        patient_id=uuid.uuid4(), facility_id=uuid.uuid4(), triage_disposition="HOME_CARE",
        created_at=created_at, org_unit_id=org_unit_id, created_by_user_id=created_by_user_id,
    )
    db.add(encounter)
    db.commit()
    db.refresh(encounter)
    return encounter


def _make_patient(db: Session, *, org_unit_id, created_by_user_id, created_at, synced_at=None) -> Patient:
    patient = Patient(
        name="Test Patient", age=30, village="V", facility_id=uuid.uuid4(),
        created_at=created_at, org_unit_id=org_unit_id, created_by_user_id=created_by_user_id,
        synced_at=synced_at,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


# ============================================================
# DT1 -- seed a known dataset, assert the four metrics equal exact values.
# ============================================================

def test_dt1_known_dataset_exact_metrics(client, db, org_units, make_actor):
    phc_id = org_units["PHC"]
    actor_id, token = make_actor("MEDICAL_OFFICER", phc_id)
    now = datetime.now(timezone.utc)

    # ---- referrals: not date-scoped, evaluated against real `now`. ----
    for _ in range(4):  # open, not breached
        _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                        status=ReferralState.INITIATED, due_at=now + timedelta(hours=2))
    for _ in range(3):  # open, breached
        _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                        status=ReferralState.INITIATED, due_at=now - timedelta(hours=2))
    for _ in range(2):  # CLOSED -- excluded from open_referrals entirely
        _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                        status=ReferralState.CLOSED, due_at=now - timedelta(hours=100))
    _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,  # CANCELLED -- excluded
                    status=ReferralState.CANCELLED, due_at=now - timedelta(hours=100))
    # two more referrals, INSIDE the _TEST_DATE window, purely to prove
    # synced_today's denominator really does span `referral` (Finding B:
    # they can NEVER contribute to the numerator -- no client_uuid column).
    for _ in range(2):
        _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                        status=ReferralState.INITIATED, due_at=now + timedelta(hours=2),
                        created_at=_INSIDE)

    # ---- triage encounters: date-scoped. 5 inside the window, 2 outside. ----
    for _ in range(5):
        _make_triage(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE)
    for _ in range(2):
        _make_triage(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_OUTSIDE)

    # ---- patients: date-scoped, 3 inside the window (2 synced, 1 not),
    # 1 outside (must not appear in either numerator or denominator). ----
    _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE,
                  synced_at=_INSIDE.replace(tzinfo=timezone.utc))
    _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE,
                  synced_at=_INSIDE.replace(tzinfo=timezone.utc))
    _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE, synced_at=None)
    _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_OUTSIDE,
                  synced_at=_OUTSIDE.replace(tzinfo=timezone.utc))

    resp = client.get(
        f"/dashboard/facility/{phc_id}", params={"date": _TEST_DATE.isoformat()}, headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["facility"]["id"] == str(phc_id)
    assert body["facility"]["type"] == "PHC"
    assert body["date"] == _TEST_DATE.isoformat()

    m = body["metrics"]
    # open_referrals: 4 (not breached) + 3 (breached) + 2 (extra INITIATED for synced_today test) = 9
    assert m["open_referrals"] == {"count": 9}
    assert m["triage_today"] == {"count": 5}
    assert m["breached"]["numerator"] == 3
    assert m["breached"]["denominator"] == 9
    assert m["breached"]["rate_pct"] == round(3 / 9 * 100, 1)
    # denominator: 5 triage + 3 patients (inside) + 2 referrals (inside) = 10
    # numerator: 2 synced patients only -- referral/triage synced_at is
    # always NULL today (Finding B).
    assert m["synced_today"]["denominator"] == 10
    assert m["synced_today"]["numerator"] == 2
    assert m["synced_today"]["rate_pct"] == 20.0

    assert "generated_at" in body


# ============================================================
# DT2 -- breached and synced_today carry numerator/denominator/rate_pct.
# ============================================================

def test_dt2_breached_and_synced_today_carry_full_shape(client, db, org_units, make_actor):
    phc_id = org_units["PHC"]
    actor_id, token = make_actor("MEDICAL_OFFICER", phc_id)
    now = datetime.now(timezone.utc)

    _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                    status=ReferralState.INITIATED, due_at=now - timedelta(hours=1))
    _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                    status=ReferralState.INITIATED, due_at=now + timedelta(hours=1))
    _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE,
                  synced_at=_INSIDE.replace(tzinfo=timezone.utc))
    _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE, synced_at=None)

    resp = client.get(
        f"/dashboard/facility/{phc_id}", params={"date": _TEST_DATE.isoformat()}, headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    m = resp.json()["metrics"]

    for key in ("breached", "synced_today"):
        for field in ("numerator", "denominator", "rate_pct"):
            assert field in m[key], f"{key} missing {field}"

    assert m["breached"] == {"numerator": 1, "denominator": 2, "rate_pct": 50.0}
    assert m["synced_today"] == {"numerator": 1, "denominator": 2, "rate_pct": 50.0}


# ============================================================
# DT3 -- a facility with no activity returns all zeros with a 200.
# ============================================================

def test_dt3_no_activity_returns_zeros_not_error(client, org_units, make_actor):
    chc_id = org_units["CHC"]
    _, token = make_actor("MEDICAL_OFFICER", chc_id)

    resp = client.get(f"/dashboard/facility/{chc_id}", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    m = resp.json()["metrics"]

    assert m["open_referrals"] == {"count": 0}
    assert m["triage_today"] == {"count": 0}
    assert m["breached"] == {"numerator": 0, "denominator": 0, "rate_pct": 0.0}
    assert m["synced_today"] == {"numerator": 0, "denominator": 0, "rate_pct": 0.0}


# ============================================================
# DT4 -- an out-of-scope facility returns 404 FACILITY_NOT_IN_SCOPE, not 403.
# ============================================================

def test_dt4_out_of_scope_facility_returns_404(client, org_units, org_units_b, make_actor):
    # Actor posted in the SECOND, entirely separate org tree.
    _, token = make_actor("MEDICAL_OFFICER", org_units_b["PHC"])

    resp = client.get(f"/dashboard/facility/{org_units['PHC']}", headers=auth_header(token))
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "FACILITY_NOT_IN_SCOPE"


# ============================================================
# DT5 -- no N+1: total statement count for one request stays under 10.
# ============================================================

def test_dt5_no_n_plus_1_queries(client, db, org_units, make_actor):
    phc_id = org_units["PHC"]
    actor_id, token = make_actor("MEDICAL_OFFICER", phc_id)
    now = datetime.now(timezone.utc)

    # A handful of rows across all three tables so a naive per-row
    # implementation would show up clearly in the count.
    for _ in range(6):
        _make_referral(db, org_unit_id=phc_id, created_by_user_id=actor_id,
                        status=ReferralState.INITIATED, due_at=now + timedelta(hours=2))
    for _ in range(6):
        _make_triage(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE)
    for _ in range(6):
        _make_patient(db, org_unit_id=phc_id, created_by_user_id=actor_id, created_at=_INSIDE,
                      synced_at=_INSIDE.replace(tzinfo=timezone.utc))

    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    # `before_cursor_execute` on the real engine -- no existing precedent
    # for this in this codebase's own tests (checked: grepped for
    # `event.listen`/`before_cursor_execute` across tests/, no hits), so
    # this is this test's own minimal implementation, attached/detached
    # around exactly the one request under test.
    event.listen(engine, "before_cursor_execute", _count)
    try:
        resp = client.get(
            f"/dashboard/facility/{phc_id}", params={"date": _TEST_DATE.isoformat()}, headers=auth_header(token),
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert resp.status_code == 200, resp.text
    assert len(statements) < 10, f"expected <10 statements, got {len(statements)}:\n" + "\n---\n".join(statements)
