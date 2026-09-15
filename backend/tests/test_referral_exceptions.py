"""Tests for GET /referrals/exceptions (app/api/routes/referrals.py).

ET1-ET6 per this step's own task spec. Uses a local `_make_referral`
direct-insert helper, deliberately mirroring tests/test_breach_detection.py's
own helper of the same name/shape rather than importing it -- consistent
with this codebase's own established "duplicated local helper" precedent
(every route module's own `_write_audit` is duplicated the same way).

Note on `breached_at` (see app/api/routes/referrals.py's own route
docstring, point 14): this route never stamps `referral.breached_at`
itself -- only app/jobs/breach_detection.py does. A referral this route
correctly classifies as breached (via the live `is_breached()` call --
what drives `breach_only`, `summary.breached`, and sort order) can still
carry `breached_at: null` in the response if the background job hasn't
run. These tests therefore assert "is this referral breached" via
`overdue_hours > 0` / membership in a `breach_only=true` result, not via
`breached_at IS NOT NULL`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.referral import Referral
from app.models.referral_state import ReferralState
from app.services.referral.breach import compute_due_at
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
    owner_user_id=None,
) -> Referral:
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
        owner_user_id=owner_user_id,
        org_unit_id=org_unit_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


# ============================================================
# ET1 -- a deliberately breached referral appears in the list, with an
# owner and a due date.
# ============================================================

def test_et1_breached_referral_appears_with_owner_and_due_date(client, db, org_units, make_actor):
    actor_id, token = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="URGENT", initiated_at=now - timedelta(days=5), owner_user_id=actor_id,
    )

    resp = client.get("/referrals/exceptions", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    ids = [item["referral_id"] for item in body["items"]]
    assert str(referral.id) in ids
    item = next(i for i in body["items"] if i["referral_id"] == str(referral.id))

    assert item["owner"] is not None
    assert item["owner"]["user_id"] == str(actor_id)
    assert item["needs_owner"] is False
    assert item["due_at"] is not None
    assert item["overdue_hours"] > 0  # the reliable "is breached" signal -- see module docstring
    assert body["summary"]["breached"] >= 1
    assert body["summary"]["breach_rate"]["numerator"] == body["summary"]["breached"]
    assert body["summary"]["breach_rate"]["denominator"] == body["summary"]["total_open"]


# ============================================================
# ET2 -- a referral inside its window is absent when breach_only=true.
# ============================================================

def test_et2_referral_inside_window_absent_with_breach_only(client, db, org_units, make_actor):
    actor_id, token = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", initiated_at=now,  # due 7 days out -- nowhere near breached
    )

    resp = client.get("/referrals/exceptions", headers=auth_header(token), params={"breach_only": "true"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    ids = [item["referral_id"] for item in body["items"]]
    assert str(referral.id) not in ids

    # Sanity: the same referral IS visible without breach_only.
    resp2 = client.get("/referrals/exceptions", headers=auth_header(token))
    ids2 = [item["referral_id"] for item in resp2.json()["items"]]
    assert str(referral.id) in ids2


# ============================================================
# ET3 -- every item has owner (or needs_owner true), due_at and
# escalation.stage.
# ============================================================

def test_et3_every_item_has_owner_or_needs_owner_due_at_and_stage(client, db, org_units, make_actor):
    actor_id, token = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="URGENT", initiated_at=now - timedelta(days=3), owner_user_id=actor_id,
    )
    _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="EMERGENCY", initiated_at=now - timedelta(hours=5), owner_user_id=None,
    )

    resp = client.get("/referrals/exceptions", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body["items"]) >= 2
    for item in body["items"]:
        assert item["due_at"] is not None
        assert "stage" in item["escalation"]
        assert item["escalation"]["stage"] in (0, 1, 2, 3)
        if item["owner"] is None:
            assert item["needs_owner"] is True
        else:
            assert item["needs_owner"] is False
            assert item["owner"]["user_id"]


# ============================================================
# ET4 -- a request for another block's org_unit_id returns 404.
# ============================================================

def test_et4_out_of_scope_org_unit_id_returns_404(client, org_units, org_units_b, make_actor):
    _, token = make_actor("BMO", org_units["BLOCK"])

    resp = client.get(
        "/referrals/exceptions", headers=auth_header(token),
        params={"org_unit_id": str(org_units_b["BLOCK"])},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "FACILITY_NOT_IN_SCOPE"


# ============================================================
# ET5 -- sort order is EMERGENCY first then overdue_hours desc; a client
# sort param is ignored.
# ============================================================

def test_et5_sort_order_emergency_first_then_overdue_desc_client_sort_ignored(client, db, org_units, make_actor):
    actor_id, token = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)

    # A: EMERGENCY, breached lightly (overdue ~2h) -- must sort FIRST
    # regardless of its own overdue_hours, since urgency is the primary key.
    a = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="EMERGENCY", initiated_at=now - timedelta(hours=3),
        due_at=now - timedelta(hours=2),
    )
    # B: URGENT, breached heavily (overdue ~100h) -- second (breached rows
    # before not-yet-breached ones within the non-EMERGENCY tier).
    b = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="URGENT", initiated_at=now - timedelta(days=10),
        due_at=now - timedelta(hours=100),
    )
    # C: ROUTINE, not yet breached, due soon -- this route's own documented
    # tie-break for not-yet-breached rows (ascending due_at) puts it before D.
    c = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", initiated_at=now, due_at=now + timedelta(hours=1),
    )
    # D: ROUTINE, not yet breached, due much later.
    d = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="ROUTINE", initiated_at=now, due_at=now + timedelta(days=5),
    )

    expected_order = [str(a.id), str(b.id), str(c.id), str(d.id)]

    resp = client.get("/referrals/exceptions", headers=auth_header(token), params={"limit": 200})
    assert resp.status_code == 200, resp.text
    ids = [item["referral_id"] for item in resp.json()["items"]]
    assert [i for i in ids if i in expected_order] == expected_order

    # A client-supplied `sort` param (here, one that -- if honoured --
    # would reverse the meaningful ordering) must be silently ignored.
    resp2 = client.get(
        "/referrals/exceptions", headers=auth_header(token),
        params={"limit": 200, "sort": "due_at_asc"},
    )
    assert resp2.status_code == 200, resp2.text
    ids2 = [item["referral_id"] for item in resp2.json()["items"]]
    assert [i for i in ids2 if i in expected_order] == expected_order


# ============================================================
# ET6 -- with ESCALATION_ENGINE=fallback, items report engine "fallback".
# ============================================================

def test_et6_escalation_engine_fallback_reports_fallback_engine(client, db, org_units, make_actor, monkeypatch):
    monkeypatch.setenv("ESCALATION_ENGINE", "fallback")

    actor_id, token = make_actor("BMO", org_units["BLOCK"])
    now = datetime.now(timezone.utc)
    referral = _make_referral(
        db, org_unit_id=org_units["BLOCK"], created_by_user_id=actor_id,
        urgency="URGENT", initiated_at=now - timedelta(days=3), owner_user_id=actor_id,
    )

    resp = client.get("/referrals/exceptions", headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["referral_id"] == str(referral.id))

    assert item["escalation"]["engine"] == "fallback"
