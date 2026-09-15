"""Referral breach detection -- the shared rule (app/services/referral/breach.py)
and the background job (app/jobs/breach_detection.py) that uses it.

BT1-BT6 are the six cases this step's own task specified. BT7/BT8 are
additional coverage added here for the two interaction/ambiguity findings
flagged in the accompanying report (NOT_ARRIVED double-bump guard, urgency
casing/vocabulary normalisation) -- not strictly required by the task's own
list, but directly exercise the decisions documented in
app/jobs/breach_detection.py's and app/services/referral/breach.py's own
docstrings, so a regression in either is caught by a real test rather than
only by a comment.

Uses the injected `now` parameter both `is_breached` and `detect_breaches`
already expose, per this repo's own existing pattern (no freezegun --
checked backend/requirements.txt, not present, and this repo's own
established style already threads `now` through explicitly wherever a test
needs control over "the current time" -- see app/api/routes/referrals.py's
own `now = datetime.now(timezone.utc)` STEP 4/5 comment). No `time.sleep`
anywhere in this file.

`referral.org_unit_id`/`created_by_user_id` are real, FK-constrained NOT
NULL columns (migration 9d5f6b3e0a71) -- every directly-inserted Referral
row in this file supplies both from the `org_units`/`make_actor` fixtures,
same as tests/test_existing_endpoints.py's own direct-insert pattern for
`patient`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import text as sqltext

from app.jobs.breach_detection import detect_breaches
from app.models.referral import Referral
from app.models.referral_state import ReferralState
from app.services.referral.breach import compute_due_at, is_breached
from tests._fixtures import auth_header


def _make_referral(
    db,
    *,
    org_unit_id,
    created_by_user_id,
    urgency: str = "ROUTINE",
    status: ReferralState = ReferralState.INITIATED,
    initiated_at: datetime | None = None,
    due_at: datetime | None = None,
    breached_at: datetime | None = None,
    breach_detected_by: str | None = None,
    escalation_stage: int = 0,
    escalation_notified_at: datetime | None = None,
    owner_user_id=None,
) -> Referral:
    """Direct-insert helper (bypasses POST /referrals/ -- no HTTP/auth
    plumbing needed for the unit-level BT1/2/3/5/6/7/8 cases). BT4 goes
    through the real route on purpose, since that's specifically what's
    being proven there."""
    initiated_at = initiated_at or datetime.now(timezone.utc)
    if due_at is None:
        due_at = compute_due_at(initiated_at, urgency)
    referral = Referral(
        patient_id=uuid.uuid4(),
        from_facility_id=uuid.uuid4(),
        destination_facility_id=uuid.uuid4(),
        reason="Test referral",
        urgency=urgency,
        status=status,
        initiated_at=initiated_at,
        due_at=due_at,
        breached_at=breached_at,
        breach_detected_by=breach_detected_by,
        escalation_stage=escalation_stage,
        escalation_notified_at=escalation_notified_at,
        owner_user_id=owner_user_id,
        org_unit_id=org_unit_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


# ============================================================
# BT1 -- past window, not arrived -> breached.
# ============================================================

@pytest.mark.asyncio
async def test_bt1_past_window_not_arrived_is_breached(db, org_units, make_actor):
    actor_id, _ = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    initiated = now - timedelta(days=10)  # ROUTINE window (7d) long expired
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", status=ReferralState.INITIATED, initiated_at=initiated,
    )

    assert is_breached(referral, now) is True

    result = await detect_breaches(db, now=now)
    assert result["newly_breached"] == 1
    assert result["checked"] >= 1

    db.refresh(referral)
    assert referral.breached_at is not None
    assert referral.breach_detected_by == "JOB"
    assert referral.escalation_stage == 1


# ============================================================
# BT2 -- arrived inside window -> NEVER breached, even long after.
# ============================================================

@pytest.mark.asyncio
async def test_bt2_arrived_inside_window_never_breached_even_long_after(db, org_units, make_actor):
    actor_id, _ = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    initiated = now - timedelta(days=365)  # due_at is a year in the past
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", status=ReferralState.ARRIVED, initiated_at=initiated,
    )

    assert is_breached(referral, now) is False

    result = await detect_breaches(db, now=now)
    assert result["newly_breached"] == 0

    db.refresh(referral)
    assert referral.breached_at is None


# ============================================================
# BT3 -- CANCELLED -> never breached.
# ============================================================

@pytest.mark.asyncio
async def test_bt3_cancelled_never_breached(db, org_units, make_actor):
    actor_id, _ = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    initiated = now - timedelta(days=365)
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="EMERGENCY", status=ReferralState.CANCELLED, initiated_at=initiated,
    )

    assert is_breached(referral, now) is False

    result = await detect_breaches(db, now=now)
    assert result["newly_breached"] == 0

    db.refresh(referral)
    assert referral.breached_at is None


# ============================================================
# BT4 -- RESCHEDULED -> breached_at cleared, due_at recomputed.
# Real HTTP round trip through the route, per the task's own instruction
# that this is what's being wired -- not a direct-DB shortcut.
# ============================================================

def test_bt4_rescheduled_clears_breached_at_and_recomputes_due_at(client, db, org_units, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_resp = client.post("/patients/", headers=auth_header(token), json={
        "name": "P", "age": 30, "village": "V", "phone": "+919222200099",
        "facility_id": str(uuid.uuid4()),
    })
    assert patient_resp.status_code == 200, patient_resp.text
    patient_id = patient_resp.json()["id"]

    referral_resp = client.post("/referrals/", headers=auth_header(token), json={
        "patient_id": patient_id, "from_facility_id": str(uuid.uuid4()),
        "destination_facility_id": str(uuid.uuid4()), "reason": "Specialist", "urgency": "urgent",
    })
    assert referral_resp.status_code == 200, referral_resp.text
    referral_id = referral_resp.json()["id"]
    # D2-S8: due_at is now set server-side at creation (was NULL before
    # this step for every row created after migration d4f1c9b7a582).
    assert referral_resp.json()["due_at"] is not None

    r1 = client.patch(f"/referrals/{referral_id}/status?status=NOT_ARRIVED", headers=auth_header(token))
    assert r1.status_code == 200, r1.text
    r2 = client.patch(
        f"/referrals/{referral_id}/status?status=TRACED", headers=auth_header(token),
        json={"traced_by_user_id": str(uuid.uuid4())},
    )
    assert r2.status_code == 200, r2.text

    # Simulate this referral having already been detected as breached by
    # the job (breached_at set), so RESCHEDULED clearing it is actually
    # proven, not vacuously true because it was already NULL.
    db.exec(sqltext(
        "UPDATE referral SET breached_at = now(), breach_detected_by = 'JOB' WHERE id = :id"
    ), params={"id": referral_id})
    db.commit()

    before = datetime.now(timezone.utc)
    r3 = client.patch(f"/referrals/{referral_id}/status?status=RESCHEDULED", headers=auth_header(token))
    assert r3.status_code == 200, r3.text
    body = r3.json()

    assert body["breached_at"] is None

    new_due_at = datetime.fromisoformat(body["due_at"])
    # URGENT's window is 24h, computed from the RESCHEDULE instant (via
    # the shared compute_due_at), not from the original initiated_at
    # (which was several seconds/minutes before `before`).
    assert before + timedelta(hours=23) < new_due_at < before + timedelta(hours=25)


# ============================================================
# BT5 -- detect_breaches() called twice: newly_breached is 0 the second
# time, escalation_stage unchanged.
# ============================================================

@pytest.mark.asyncio
async def test_bt5_detect_breaches_twice_is_idempotent(db, org_units, make_actor):
    actor_id, _ = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    initiated = now - timedelta(days=10)
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", status=ReferralState.INITIATED, initiated_at=initiated,
    )

    result1 = await detect_breaches(db, now=now)
    assert result1["newly_breached"] == 1
    db.refresh(referral)
    stage_after_first = referral.escalation_stage
    notified_after_first = referral.escalation_notified_at
    assert stage_after_first == 1

    result2 = await detect_breaches(db, now=now)
    assert result2["newly_breached"] == 0

    db.refresh(referral)
    assert referral.escalation_stage == stage_after_first
    assert referral.escalation_notified_at == notified_after_first


# ============================================================
# BT6 -- escalation caps at stage 3 -> never 4.
# ============================================================

@pytest.mark.asyncio
async def test_bt6_escalation_caps_at_stage_3(db, org_units, make_actor):
    actor_id, _ = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    initiated = now - timedelta(days=10)
    breached_at = now - timedelta(days=5)  # far past every URGENT threshold
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="URGENT", status=ReferralState.INITIATED, initiated_at=initiated,
        breached_at=breached_at, breach_detected_by="JOB", escalation_stage=1,
    )

    result = await detect_breaches(db, now=now)
    assert result["escalated"] == 1
    db.refresh(referral)
    assert referral.escalation_stage == 3

    result2 = await detect_breaches(db, now=now)
    assert result2["escalated"] == 0
    db.refresh(referral)
    assert referral.escalation_stage == 3  # never 4


# ============================================================
# BT7 (additional) -- NOT_ARRIVED already at stage 1 (route side effect)
# is not double-bumped by the job's own "newly breached -> 0 -> 1" rule.
# See app/jobs/breach_detection.py's own docstring for the full reasoning.
# ============================================================

@pytest.mark.asyncio
async def test_bt7_not_arrived_already_stage1_is_not_double_bumped(db, org_units, make_actor):
    actor_id, _ = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    initiated = now - timedelta(days=10)
    # Simulates PATCH .../status -> NOT_ARRIVED already having set
    # escalation_stage = 1 as a side effect, before this job ever runs.
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", status=ReferralState.NOT_ARRIVED, initiated_at=initiated,
        escalation_stage=1,
    )

    result = await detect_breaches(db, now=now)
    assert result["newly_breached"] == 1  # the breach itself is still recorded

    db.refresh(referral)
    assert referral.breached_at is not None
    assert referral.escalation_stage == 1  # not bumped to 2, not regressed to 0


# ============================================================
# BT8 (additional) -- urgency casing/vocabulary normalisation.
# ============================================================

def test_bt8_urgency_casing_and_unknown_vocabulary_normalized():
    initiated = datetime.now(timezone.utc)
    assert compute_due_at(initiated, "routine") == compute_due_at(initiated, "ROUTINE")
    assert compute_due_at(initiated, " Routine ") == compute_due_at(initiated, "ROUTINE")
    # Unknown free text (no CHECK constraint exists on referral.urgency --
    # see breach.py's own docstring) falls back to the ROUTINE window.
    assert compute_due_at(initiated, "asap") == compute_due_at(initiated, "ROUTINE")
    assert compute_due_at(initiated, "") == compute_due_at(initiated, "ROUTINE")
    assert compute_due_at(initiated, None) == compute_due_at(initiated, "ROUTINE")
