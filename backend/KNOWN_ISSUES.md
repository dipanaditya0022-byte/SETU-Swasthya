# Known Issues — Demo Freeze

Findings from today's verification/hardening work, carried forward
deliberately rather than silently fixed or hidden before the freeze.
Per this repo's own working principle: a known bug is manageable; an
untested fix is not. None of these block the demo; all are either
narratable live or genuinely out of today's scope.

## P0 — real, unfixed

### Concurrent PATCH to the same referral can silently double-apply
Two simultaneous `PATCH /referrals/{id}/status` requests to different
target statuses on the SAME referral: in 9 of 10 live-tested iterations,
**both requests returned 200** instead of one winning and the other
getting a `409`. The loser's write silently overwrites the winner's,
with no error surfaced to either caller, and the `referral_transitions`
audit trail records an incorrect `from_status` for the overwriting
transition. Root cause: `update_referral_status`
(`app/api/routes/referrals.py`) loads the referral via a plain
`session.get()` with no row lock and no optimistic `WHERE status = ...`
re-check on the eventual `UPDATE` — the transition guard is evaluated
against a snapshot that can go stale between read and write under real
concurrency.

Reproduced and asserted in `backend/tests/test_concurrency.py::
test_scenario3_concurrent_patch_same_referral_different_statuses` (left
deliberately failing in the suite as a live alarm, not silenced).

**Demo impact:** low probability in a single-presenter demo (requires
two genuinely simultaneous requests against the same referral), but
real. Narrate around it if two devices are ever used to update the same
referral at once during the demo.

## Structural gaps — not bugs, just not built yet

### No mobile/offline client exists in this repository
Confirmed by a full-repo search (no `pubspec.yaml`, no `.dart` files
anywhere). Every "offline triage" / "airplane mode" / "automatic sync
listener" capability described in the product vision has no client-side
code to run today. `POST /sync/` (the real, working, tested endpoint)
only ever creates/updates `patient` rows — there is no `client_uuid`
column on `referral` or `triageencounter`, so an offline-created
referral or triage encounter has no reconciliation path to the server
at all, even hypothetically. The demo's "offline → reconnect → sync"
beat is necessarily API-level (`curl -d @scripts/demo_sync_batch.json`),
not a real device going through airplane mode.

### Triage decision has no automatic linkage to the referral it produces
`referral.urgency` is a plain, client-supplied field. There is no
`referral.triage_id` column and no server-side mapping from a triage
encounter's `decision.urgency` (IMMEDIATE/WITHIN_2H/etc.) to a
referral's own urgency (EMERGENCY/URGENT/etc.). Confirmed live: a
referral can be created with `urgency=ROUTINE` for a patient whose
triage moments earlier said EMERGENCY/IMMEDIATE, with no cross-check,
no warning, no rejection. The demo's own seed data and demo script
apply the correct mapping manually; a live ad-hoc referral creation
during Q&A should use the same manual mapping (IMMEDIATE→EMERGENCY,
WITHIN_2H/WITHIN_24H→URGENT, WITHIN_72H→PRIORITY, WITHIN_7D/ROUTINE→
ROUTINE) rather than guessing.

## Cosmetic / low-severity — logged only, not fixed

- **Dashboard facility metrics cache for 60 seconds.** A referral status
  change or a sync batch may not be reflected on
  `GET /dashboard/facility/{id}` for up to 60s after the underlying
  write, even though the write itself succeeded immediately. If a live
  demo does "make a change, then immediately show the dashboard," the
  count may look stale for under a minute.
- **Cross-block referral access denial writes no audit log row.**
  `PATCH /referrals/{id}/status` on a referral outside the actor's org
  scope correctly returns `404` (never `403`, per this system's own
  anti-enumeration design) but does not call the audit-log helper other
  scope-denial paths in this codebase do. The access control itself is
  correct; only the audit trail for that specific denial is missing.
- **`API_CONTRACT.md` doesn't document `GET /referrals/exceptions` or
  `GET /dashboard/facility/{id}`.** Both endpoints work correctly and
  are covered by tests; the contract doc simply predates them.
- **Missing-vitals triage cases correctly escalate to REFER, not a
  clean rejection.** This is deliberate, documented behavior (a missing
  vital is a clinical situation, not a client error), not a bug — noted
  here only so it isn't mistaken for one if seen live: an ANC triage
  submitted with no blood pressure returns `200` with
  `disposition: REFER`, `insufficient_data: true`, not an error.

## Config/ops notes carried into the freeze

- `TRIAGE_ENGINE` / `ESCALATION_ENGINE` are explicitly pinned to
  `fallback` in this environment's `.env` (no rule-engine module exists
  in this repo yet — `auto` would resolve to `fallback` anyway, but
  pinning it makes that explicit and immune to silently changing
  between rehearsal and the real thing).
- Demo dataset (`scripts/seed_demo.py`) is fully deterministic —
  re-running produces identical entity UUIDs/structure every time
  (exact timestamps on backdated/relative rows necessarily reflect each
  run's own "now", which is expected, not a determinism bug).
