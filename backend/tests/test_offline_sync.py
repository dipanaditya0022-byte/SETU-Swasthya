"""Offline-to-sync path, steps 7-9 automated at the API level (backend/docs
-- "Run and verify the full offline-to-sync path end to end").

============================================================
STEPS 1-6 AND THE RULE-PARITY QUESTION -- READ BEFORE TRUSTING ANY "PASS"
BELOW AS "THE OFFLINE PATH WORKS"
============================================================
This repo has NO Flutter/mobile client at all -- confirmed by searching the
entire repository root (`find . -iname "pubspec.yaml" -o -iname "*.dart"`,
zero hits anywhere outside this backend/ directory). Steps 1 (airplane
mode), 2 (local-first patient registration), 3 (offline triage disposition),
4 (offline referral creation with a client UUID), 5 (reconnect), and 6
(automatic sync listener) all describe MOBILE CLIENT behaviour. There is no
code anywhere in this repository to run, observe, or test for any of them.
This file does not simulate, mock, or otherwise pretend to exercise them --
doing so would misrepresent what was actually verified. See
backend/docs/DAY3_OFFLINE_SYNC.md (or this task's own delivery report) for
the step-by-step table stating this plainly for each of the 9 steps.

RULE PARITY (step 3's own explicit question -- "if the client cannot run
rules at all, say so plainly"): it cannot, because no client exists. But
that is not the only gap. Confirmed directly against this file's own code
under test: `POST /sync/` (app/api/routes/sync.py) NEVER calls the triage
engine, ever -- it only creates/updates `patient` rows. There is no
`client_uuid` column on `TriageEncounter` (checked app/models/
triage_encounter.py) or on `Referral` (checked app/models/referral.py) --
only `Patient` has one. So even setting aside "no client exists to run
rules offline," there is NO SYNC PATH for a triage encounter or a referral
to ever reach this server via POST /sync/ at all -- offline-created
triage/referral data has no reconciliation mechanism in this backend today,
regardless of what a future client could compute locally. The entire
clinical value proposition of offline triage (a red-flag warning at the
point of care, before any connectivity exists) is unimplemented on both
sides: no client to compute it, and no server-side path to receive it even
if a client did.
============================================================

STEPS 7-9, what this file DOES verify, live and for real:
  7. POST /sync/ receives a batch, rows persisted, server ids reconciled
     with client_uuids (patient records only -- see gap above).
  8. Idempotency: THE key check is that the dedup key is the record's own
     client_uuid (confirmed directly against sync.py's `_sync_one`: `WHERE
     client_uuid = :cu` against the `patient` table), not a hash of the
     whole batch. Three live cases: 50 fresh -> created=50; the identical
     50 replayed -> created=0/duplicates=50; the same 50 plus 1 new ->
     created=1/duplicates=50. A batch-hash-keyed implementation would fail
     the third case (a single-byte-different batch would look like an
     entirely new, unmatched batch) -- this is exactly the scenario a real
     field worker produces (yesterday's queue plus one new registration).
  9. GET /dashboard/facility/{org_unit_id}'s synced_today metric reflects
     the newly-synced patient rows.

ALSO: no "deployment hardening step" (security headers, CORS, rate
limiting) exists anywhere in this session's history as of when this file
was written -- confirmed by reviewing every earlier task done today. The
task that produced this file asked to "run it twice: once now, and once
again after the deployment hardening step" -- only the first run is
possible today; there is no hardened build yet to run a second time
against. State this plainly rather than fabricating a before/after
comparison.

Uses this repo's existing conventions (`raising_client`/`db`/`org_units`/
`make_actor`/`auth_header` -- same as every other test file built today).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests._fixtures import auth_header


@pytest.fixture
def raising_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _record(facility_id: str, tag: str) -> dict:
    return {
        "client_uuid": f"offline-sync-{tag}-{uuid.uuid4()}",
        "name": f"Offline Patient {tag}",
        "age": 25,
        "village": "V",
        "phone": "+919" + str(uuid.uuid4().int)[:9],
        "facility_id": facility_id,
    }


# ============================================================
# Step 7 -- backend receipt: batch persisted, server ids reconciled with
# client_uuids.
# ============================================================

def test_step7_backend_receipt_persists_batch_and_reconciles_ids(raising_client, db, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(org_units["PHC"])

    batch = [_record(facility_id, "step7") for _ in range(5)]
    r = raising_client.post("/sync/", headers=headers, json=batch)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["synced"] == 5
    assert body["created"] == 5
    assert body["duplicates"] == 0
    assert body["failed"] == 0
    assert all(rec["status"] == "accepted" for rec in body["records"])

    # Server ids reconciled with client_uuids: every submitted client_uuid
    # now resolves to a real `patient` row with a real server-generated id.
    from sqlmodel import text as sqltext
    for record in batch:
        row = db.exec(sqltext(
            "SELECT id, name FROM patient WHERE client_uuid = :cu"
        ), params={"cu": record["client_uuid"]}).first()
        assert row is not None, f"no patient row found for client_uuid={record['client_uuid']}"
        server_id, name = row
        assert server_id is not None
        assert name == record["name"]


# ============================================================
# Step 8 -- idempotency, keyed on the record's own client_uuid, NOT a
# batch hash. The three cases from the task's own spec, run live.
# ============================================================

def test_step8_idempotency_first_send_replay_and_replay_plus_one(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(org_units["PHC"])

    batch_50 = [_record(facility_id, "idem50") for _ in range(50)]

    # ---- Case 1: first send, 50 fresh records ----
    r1 = raising_client.post("/sync/", headers=headers, json=batch_50)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    print(f"\n[Case 1: first send, 50 records] -> {{'created': {body1['created']}, 'duplicates': {body1['duplicates']}}}")
    assert body1["created"] == 50, body1
    assert body1["duplicates"] == 0, body1
    assert body1["failed"] == 0, body1

    # ---- Case 2: replay, the EXACT SAME 50 records ----
    r2 = raising_client.post("/sync/", headers=headers, json=batch_50)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    print(f"[Case 2: replay same 50] -> {{'created': {body2['created']}, 'duplicates': {body2['duplicates']}}}")
    assert body2["created"] == 0, body2
    assert body2["duplicates"] == 50, body2
    assert body2["failed"] == 0, body2

    # ---- Case 3: replay + 1 new record ----
    batch_51 = batch_50 + [_record(facility_id, "idem51-new")]
    r3 = raising_client.post("/sync/", headers=headers, json=batch_51)
    assert r3.status_code == 200, r3.text
    body3 = r3.json()
    print(f"[Case 3: replay + 1, 51 records] -> {{'created': {body3['created']}, 'duplicates': {body3['duplicates']}}}")
    assert body3["created"] == 1, (
        f"THE case a batch-hash-keyed idempotency implementation would fail: "
        f"expected created=1 (the one genuinely new record), got {body3}"
    )
    assert body3["duplicates"] == 50, body3
    assert body3["failed"] == 0, body3

    # (A duplicate-row-count-in-the-DB check, on top of these response
    # counts, is already covered by test_step7's own `db`-fixture
    # assertion for the create path; this test intentionally stays
    # response-shape-focused, matching the task's own three assertions.)


def test_step8_dedup_key_is_the_records_own_client_uuid_not_a_batch_hash(raising_client, org_units, make_actor):
    """Direct proof of the mechanism, not just its externally-observable
    effect: two DIFFERENT batches that happen to share ONE client_uuid in
    common must treat only that one record as a duplicate -- a batch-hash
    scheme would treat the two batches as entirely unrelated (both fully
    "new") since their overall contents differ."""
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(org_units["PHC"])

    shared_record = _record(facility_id, "shared")
    batch_a = [shared_record, _record(facility_id, "a1"), _record(facility_id, "a2")]
    batch_b = [shared_record, _record(facility_id, "b1"), _record(facility_id, "b2"), _record(facility_id, "b3")]

    r_a = raising_client.post("/sync/", headers=headers, json=batch_a)
    assert r_a.status_code == 200, r_a.text
    assert r_a.json()["created"] == 3 and r_a.json()["duplicates"] == 0

    r_b = raising_client.post("/sync/", headers=headers, json=batch_b)
    assert r_b.status_code == 200, r_b.text
    body_b = r_b.json()
    # A batch-hash scheme would see batch_b (different overall contents)
    # as fully new -> created=4. Per-record client_uuid dedup correctly
    # recognises only the one shared record.
    assert body_b["created"] == 3, (
        f"expected only the 3 genuinely-new records in batch_b to be created "
        f"(the shared record must be caught as a duplicate individually); got {body_b}"
    )
    assert body_b["duplicates"] == 1, body_b


# ============================================================
# Step 9 -- dashboard reflects synced records.
# ============================================================

def test_step9_dashboard_synced_today_reflects_synced_records(raising_client, org_units, make_actor):
    _, token = make_actor("MEDICAL_OFFICER", org_units["BLOCK"])
    headers = auth_header(token)
    facility_id = str(org_units["PHC"])
    org_unit_id = str(org_units["PHC"])

    # Sync-created patient rows are stamped org_unit_id = the actor's own
    # scope (org_units["BLOCK"], since sync.py falls back to
    # current_user.scope_org_unit_id when no org_unit_id is supplied per
    # record) -- use org_units["BLOCK"] as the dashboard facility being
    # queried, not PHC, so the newly-synced rows actually land inside it.
    org_unit_id = str(org_units["BLOCK"])
    baseline_resp = raising_client.get(f"/dashboard/facility/{org_unit_id}", headers=headers)
    assert baseline_resp.status_code == 200, baseline_resp.text
    baseline = baseline_resp.json()["metrics"]["synced_today"]

    # Bypass the dashboard's own 60s TTL cache -- see
    # tests/test_referral_day3.py's identical, already-documented finding
    # for why this is necessary and not a test artifact.
    from app.api.routes import dashboard as dashboard_module
    dashboard_module._cache._store.clear()

    batch = [_record(facility_id, "step9") for _ in range(3)]
    r = raising_client.post("/sync/", headers=headers, json=batch)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3

    dashboard_module._cache._store.clear()
    after_resp = raising_client.get(f"/dashboard/facility/{org_unit_id}", headers=headers)
    assert after_resp.status_code == 200, after_resp.text
    after = after_resp.json()["metrics"]["synced_today"]

    print(f"\n[Step 9] synced_today baseline={baseline} after={after}")
    assert after["numerator"] == baseline["numerator"] + 3, (
        f"expected synced_today numerator to increase by exactly 3: baseline={baseline} after={after}"
    )
    assert after["denominator"] == baseline["denominator"] + 3, (
        f"expected synced_today denominator to increase by exactly 3 too "
        f"(these 3 patient rows were both created AND synced today): baseline={baseline} after={after}"
    )
