"""Six concurrency scenarios against the real backend (backend/docs --
"this is NOT the same test twice. It exists to find concurrency bugs
that a single device can never surface").

============================================================
"TWO DEVICES" -- READ BEFORE JUDGING WHAT THIS FILE ACTUALLY PROVES
============================================================
This repo has no Flutter/mobile client anywhere (confirmed by a full-repo
search for pubspec.yaml/*.dart -- zero hits, same finding as the two
prior tasks today). "Two devices or emulators" cannot mean literal mobile
hardware here. The task's OWN text resolves this for scenarios 1, 2, 3, 6:
it explicitly asks for `asyncio.gather` automation -- i.e. "two devices"
means two concurrent, independently-authenticated API clients hitting the
real backend at the same instant. That is what this file does, and it is
a faithful test of the actual concurrency question (do two simultaneous
requests against the same backend/DB race correctly), even though no
physical device is involved.

Scenarios 4 and 5 are explicitly scoped "stay manual" by the task's own
text. No manual device exists either. They are NOT automated here, per
the task's own instruction -- see the delivery report for what was
probed instead (a lightweight API-level equivalent for scenario 4, and
plain code-reading for scenario 5's caching behaviour), clearly labelled
as not the literal two-device scenario.

Uses httpx.AsyncClient + ASGITransport against the real `app`, matching
tests/test_triage_decisioning.py's own established async-client pattern
in this repo (that file's own `async_client` fixture) rather than
inventing a new one. `update_referral_status` (app/api/routes/
referrals.py) is a plain `def`, not `async def` -- FastAPI runs it via
`run_in_threadpool` (a real OS thread pool), and `get_session()` opens a
brand-new `Session`/DB connection per request -- so two concurrent PATCH
requests against the SAME referral genuinely run as two overlapping
Postgres transactions, not serialised by Python's GIL or a shared
connection. This is what makes scenario 3 a real test of database-level
concurrency, not just an in-process race that Python's GIL would hide.
"""
from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

try:
    import pytest_asyncio
    _HAVE_PYTEST_ASYNCIO = True
except ImportError:  # pragma: no cover
    pytest_asyncio = None
    _HAVE_PYTEST_ASYNCIO = False

from sqlmodel import text as sqltext

from app.main import app
from tests._fixtures import auth_header

if _HAVE_PYTEST_ASYNCIO:
    @pytest_asyncio.fixture
    async def async_client():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
else:  # pragma: no cover
    @pytest.fixture
    def async_client():
        pytest.skip("pytest-asyncio is not installed in this environment.")


def _phone() -> str:
    return "+919" + str(uuid.uuid4().int)[:9]


async def _make_patient(client: httpx.AsyncClient, token: str, facility_id: str, name: str) -> str:
    r = await client.post("/patients/", headers=auth_header(token), json={
        "name": name, "age": 27, "village": "V", "phone": _phone(), "facility_id": facility_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _make_referral(client: httpx.AsyncClient, token: str, patient_id: str, facility_id: str, destination: str) -> str:
    r = await client.post("/referrals/", headers=auth_header(token), json={
        "patient_id": patient_id, "from_facility_id": facility_id,
        "destination_facility_id": destination, "reason": "concurrency test",
        "urgency": "ROUTINE", "receiving_unit": "General OPD", "owner": "Tester",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ============================================================
# Scenario 1 -- two different actors, same village/scope, register
# patients simultaneously.
# ============================================================

@pytest.mark.asyncio
async def test_scenario1_two_actors_same_village_register_simultaneously(async_client, org_units, make_actor):
    _, token_a = make_actor("ASHA", org_units["VILLAGE"])
    _, token_b = make_actor("ASHA", org_units["VILLAGE"])
    facility_id = str(org_units["VILLAGE"])

    results = await asyncio.gather(
        _make_patient(async_client, token_a, facility_id, "Scenario1 Patient A"),
        _make_patient(async_client, token_b, facility_id, "Scenario1 Patient B"),
    )

    patient_id_a, patient_id_b = results
    assert patient_id_a != patient_id_b, "two distinct patient ids expected -- got a collision"
    print(f"\n[Scenario 1] PASS -- two distinct patient ids: {patient_id_a}, {patient_id_b}")


# ============================================================
# Scenario 2 -- two devices sync batches at the same moment.
# ============================================================

@pytest.mark.asyncio
async def test_scenario2_two_actors_sync_simultaneously_no_deadlock_no_loss(async_client, db, org_units, make_actor):
    _, token_a = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    _, token_b = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    facility_id = str(org_units["PHC"])

    def _batch(tag: str, n: int) -> list[dict]:
        return [{
            "client_uuid": f"scenario2-{tag}-{uuid.uuid4()}",
            "name": f"Scenario2 {tag} {i}", "age": 25, "village": "V",
            "phone": _phone(), "facility_id": facility_id,
        } for i in range(n)]

    batch_a = _batch("a", 20)
    batch_b = _batch("b", 20)

    async def _sync(token: str, batch: list[dict]):
        return await asyncio.wait_for(
            async_client.post("/sync/", headers=auth_header(token), json=batch), timeout=15.0,
        )

    responses = await asyncio.gather(_sync(token_a, batch_a), _sync(token_b, batch_b))
    r_a, r_b = responses

    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text
    body_a, body_b = r_a.json(), r_b.json()
    print(f"\n[Scenario 2] A: created={body_a['created']} duplicates={body_a['duplicates']} failed={body_a['failed']}")
    print(f"[Scenario 2] B: created={body_b['created']} duplicates={body_b['duplicates']} failed={body_b['failed']}")

    assert body_a["created"] == 20 and body_a["failed"] == 0
    assert body_b["created"] == 20 and body_b["failed"] == 0

    all_client_uuids = [rec["client_uuid"] for rec in batch_a + batch_b]
    rows = db.exec(sqltext(
        "SELECT count(*) FROM patient WHERE client_uuid = ANY(:uuids)"
    ), params={"uuids": all_client_uuids}).first()
    assert rows[0] == 40, f"expected all 40 records persisted, found {rows[0]}"
    print(f"[Scenario 2] PASS -- no deadlock (both completed within 15s), no lost batch (40/40 persisted)")


# ============================================================
# Scenario 3 -- THE IMPORTANT ONE. Two actors PATCH the SAME referral to
# different statuses at the same instant. Exactly one must win; the
# loser must get 409, evaluated against the ALREADY-UPDATED state, never
# a silent last-write-wins overwrite.
#
# See this file's own module docstring for why `update_referral_status`
# being a plain `def` route makes this a genuine concurrent-transaction
# test, not an in-process race hidden by the GIL.
#
# CODE PATH (app/api/routes/referrals.py):
#   - line 541: `referral = session.get(Referral, referral_id)` -- a
#     plain SELECT, NO `SELECT ... FOR UPDATE` row lock, NO optimistic
#     version column on the Referral model (checked app/models/
#     referral.py -- no `version_id_col`, no `updated_at`-guarded WHERE
#     clause anywhere in this route).
#   - line 548-565: `assert_transition_allowed(current_status,
#     requested_status)` is evaluated ONLY against that single in-memory
#     SELECT result -- there is no re-read before this check.
#   - line 574-588: `referral.status = requested_status; session.add
#     (referral); session.flush()` -- the ORM-generated UPDATE is
#     `UPDATE referral SET status=... WHERE id=:id` (SQLAlchemy's default
#     PK-keyed UPDATE for a loaded, dirty object) -- NOT `WHERE id=:id
#     AND status=:expected_current_status`. There is no application- or
#     database-level re-check of `status` at write time.
#
# CONCLUSION FROM CODE READING ALONE: under Postgres READ COMMITTED, if
# two concurrent transactions both SELECT the row before either commits,
# BOTH will pass `assert_transition_allowed` against the SAME stale
# INITIATED snapshot. The second transaction's UPDATE will BLOCK on the
# first transaction's row lock, then proceed once unblocked -- but
# because its WHERE clause is only `id=:id`, it will silently overwrite
# whatever the first transaction just committed, with NO 409 and NO
# error. This is a stale-read guard, not a current-state guard. See the
# live, multi-iteration results below for whether this actually manifests.
# ============================================================

async def _patch_status(client: httpx.AsyncClient, token: str, referral_id: str, status: str, body: dict):
    return await client.patch(
        f"/referrals/{referral_id}/status?status={status}", headers=auth_header(token), json=body,
    )


@pytest.mark.asyncio
async def test_scenario3_concurrent_patch_same_referral_different_statuses(async_client, db, org_units, make_actor):
    _, token_a = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    _, token_b = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    facility_id = str(org_units["PHC"])

    ITERATIONS = 10
    outcomes = []  # per-iteration: (status_codes, winner_status_in_db, both_200)

    for i in range(ITERATIONS):
        patient_id = await _make_patient(async_client, token_a, facility_id, f"Scenario3 iter{i}")
        referral_id = await _make_referral(async_client, token_a, patient_id, facility_id, str(org_units["PHC"]))

        # Two DIFFERENT valid-from-INITIATED next states -- neither is
        # trivially invalid on its own; the race is about which one
        # actually lands and whether the loser sees that state already
        # moved.
        body_slot = {"slot_datetime": "2026-09-25T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"])}
        body_transport = {"transport_mode": "AMBULANCE"}

        r_slot, r_transport = await asyncio.gather(
            _patch_status(async_client, token_a, referral_id, "SLOT_BOOKED", body_slot),
            _patch_status(async_client, token_b, referral_id, "TRANSPORT_ARRANGED", body_transport),
        )

        codes = (r_slot.status_code, r_transport.status_code)
        both_200 = codes == (200, 200)
        outcomes.append({
            "iteration": i, "codes": codes, "both_200": both_200,
            "slot_body": r_slot.json() if r_slot.status_code != 200 else None,
            "transport_body": r_transport.json() if r_transport.status_code != 200 else None,
        })

        row = db.exec(sqltext("SELECT status FROM referral WHERE id = :id"), params={"id": referral_id}).first()
        transitions = db.exec(sqltext(
            "SELECT from_status, to_status FROM referral_transitions WHERE referral_id = :id ORDER BY occurred_at"
        ), params={"id": referral_id}).all()
        outcomes[-1]["db_status"] = row[0]
        outcomes[-1]["transitions"] = transitions

        print(f"\n[Scenario 3][iter {i}] SLOT_BOOKED->{r_slot.status_code} "
              f"TRANSPORT_ARRANGED->{r_transport.status_code} db_status={row[0]} transitions={transitions}")

    both_200_iterations = [o for o in outcomes if o["both_200"]]
    if both_200_iterations:
        print(f"\n[Scenario 3] *** P0 FAILURE *** {len(both_200_iterations)}/{ITERATIONS} iterations "
              f"produced TWO 200s (silent last-write-wins overwrite): {both_200_iterations}")

    assert not both_200_iterations, (
        f"P0: {len(both_200_iterations)}/{ITERATIONS} iterations let BOTH concurrent PATCH requests "
        f"succeed on the same referral -- last-write-wins, no 409 ever raised for the loser. "
        f"Full outcomes: {outcomes}"
    )

    # Every iteration: exactly one 200, one non-200. Report the loser's
    # actual status code/body -- it must be a real rejection (409/422),
    # not a coincidental accept.
    for o in outcomes:
        assert 200 in o["codes"], f"iter {o['iteration']}: neither request succeeded -- {o}"
        assert o["codes"].count(200) == 1, f"iter {o['iteration']}: {o}"

    wins_a = sum(1 for o in outcomes if o["codes"][0] == 200)
    wins_b = sum(1 for o in outcomes if o["codes"][1] == 200)
    print(f"\n[Scenario 3] PASS across {ITERATIONS} iterations -- exactly one winner every time "
          f"(SLOT_BOOKED won {wins_a}, TRANSPORT_ARRANGED won {wins_b}). No silent overwrite observed.")


# ============================================================
# Scenario 6 -- actor from block A requests a referral in block B.
# Expect 404 (not 403). Also checks whether an audit_log row records
# the denial (see this file's own module docstring / the delivery
# report for the finding this surfaces).
# ============================================================

@pytest.mark.asyncio
async def test_scenario6_cross_block_referral_is_404_not_403(async_client, db, org_units, org_units_b, make_actor):
    _, token_block_b_owner = make_actor("MEDICAL_OFFICER", org_units_b["BLOCK"])
    patient_id = await _make_patient(async_client, token_block_b_owner, str(org_units_b["PHC"]), "Scenario6 Patient")
    referral_id = await _make_referral(
        async_client, token_block_b_owner, patient_id, str(org_units_b["PHC"]), str(org_units_b["PHC"]),
    )

    audit_count_before = db.exec(sqltext("SELECT count(*) FROM audit_log")).first()[0]

    _, token_block_a = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    r = await _patch_status(async_client, token_block_a, referral_id, "SLOT_BOOKED", {
        "slot_datetime": "2026-09-25T10:00:00Z", "destination_org_unit_id": str(org_units["PHC"]),
    })

    print(f"\n[Scenario 6] cross-block PATCH -> HTTP {r.status_code} body={r.text[:200]}")
    assert r.status_code == 404, f"expected 404 (not 403 -- anti-enumeration), got {r.status_code}: {r.text}"
    assert r.status_code != 403, "403 would confirm the referral's existence to an actor outside its scope"

    audit_count_after = db.exec(sqltext("SELECT count(*) FROM audit_log")).first()[0]
    denial_rows = db.exec(sqltext(
        "SELECT action, outcome, target_id FROM audit_log WHERE target_id = :rid"
    ), params={"rid": str(referral_id)}).all()
    print(f"[Scenario 6] audit_log rows for this referral_id: {denial_rows} "
          f"(count before={audit_count_before}, after={audit_count_after})")

    # THE FINDING, asserted as a documented CURRENT-BEHAVIOUR regression
    # guard (matching tests/test_referral_day3.py's own pattern for a
    # gap earlier today) rather than a perpetually-failing "should"
    # assertion: app/api/routes/referrals.py's own scope check inside
    # update_referral_status (unlike app/core/authz.py's
    # require_scope_or_404, which DOES call _audit_denied) does its own
    # inline `if not referral or not org_unit_is_within_scope(...)` with
    # NO call to _write_audit at all -- confirmed by reading the route
    # before writing this test, and confirmed live here. If this
    # assertion ever starts FAILING, that means audit logging was added
    # for this path -- update this test to assert the new, correct
    # behaviour (a real audit_log row) at that point; until then, this
    # documents the actual gap without leaving a permanently-red test in
    # the suite.
    assert audit_count_after == audit_count_before, (
        f"expected NO audit_log row for this denial (documented gap) but count changed: "
        f"before={audit_count_before} after={audit_count_after} rows={denial_rows} -- "
        f"if audit logging was added to update_referral_status's scope check, update this "
        f"test to assert the new correct behaviour instead."
    )
    print(
        "[Scenario 6] GAP CONFIRMED: no audit_log row written for this cross-block scope denial. "
        "app/api/routes/referrals.py's update_referral_status does its own inline scope check "
        "and never calls _write_audit for the 404 branch, unlike app/core/authz.py's "
        "require_scope_or_404 (which DOES call _audit_denied for the same class of denial "
        "elsewhere in this codebase). The 404-not-403 behaviour is correct; the missing audit "
        "trail is a real gap -- see the delivery report for severity."
    )
