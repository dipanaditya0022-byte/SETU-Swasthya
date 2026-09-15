# Demo Runbook

Development credentials only. Every account below is seeded by
`scripts/seed_demo.py` against fake, obviously-synthetic data (every
patient mobile starts with `+9190000000`) -- never real patient data.
Rotate/discard all of this before any non-demo deployment.

## Credentials

| Role | Full name | Mobile | Password | Notes |
|---|---|---|---|---|
| DHO (DHO_CMO) | Dr. Demo DHO | +919000000101 | `Demo1234!Pass` | **MFA-mandatory** (privileged role, role_level 3) -- password login returns an `mfa_challenge` token, not real access tokens; no TOTP secret is seeded, so this account cannot complete a live login demo. Included for scope/attribution only. |
| BMO | Dr. Demo BMO | +919000000102 | `Demo1234!Pass` | **MFA-mandatory** (role_level 5), same limitation as DHO above. |
| MO (MEDICAL_OFFICER) | Dr. Demo MO | +919000000103 | `Demo1234!Pass` | Full login works. Use this account for any live triage/referral/patient-creation walkthrough. |
| CHO | Demo CHO | +919000000104 | `Demo1234!Pass` | Full login works. |
| ANM (ANM_MPW) | Demo ANM | +919000000105 | `Demo1234!Pass` | Full login works. |
| ASHA | Demo ASHA | +919000000106 | `Demo1234!Pass` | Full login works. |
| PATIENT | Demo Patient Account | +919000000199 | `Demo1234!Pass` | Real patient self-registration is OTP-only in production; this demo account is seeded with a password too, as a deliberate shortcut so the demo doesn't depend on reading a fresh OTP off the server log mid-presentation. |

**For any live login walkthrough, use MO, CHO, ANM, or ASHA** -- DHO and
BMO will stop at an MFA challenge screen since no TOTP credential is
provisioned for them.

## Fixed demo entities

Run `python scripts/seed_demo.py` (or `./scripts/reset_demo.sh`, which
also verifies row counts) to (re)create the full deterministic dataset
and print the complete fixed-UUID table: 6 org units, 8 users (6 staff
+ 1 patient account + 1 internal bootstrap row), 12 patients, 8 triage
encounters (all four dispositions), 5 referrals (2 on-track, 1
breached, 1 closed, 1 refused). A pre-staged offline-sync batch is
written to `scripts/demo_sync_batch.json` for a live `POST /sync/` demo
beat.

## Reset between rehearsal and the real thing

```bash
./scripts/reset_demo.sh
```

Truncates and re-seeds in well under 30 seconds (measured: ~1.1s) --
safe to run right before, or even during, a live demo.

## Guard: no real patient data

`pytest backend/tests/test_no_real_data.py` -- run against the actual
demo database (not the throwaway pytest test DB) as the last gate
before any public smoke test. Fails loudly, naming the offending row
id, if any patient mobile doesn't carry the seed prefix, any patient
name matches a known-real-person denylist, or any unseeded ABHA number
is present.

## FROZEN — demo-v1.0

All four freeze preconditions confirmed before this freeze: the 24-test
smoke suite passed against the public demo URL; the offline→reconnect→sync
test passed AFTER the deployment-hardening step was deployed; the
rollback rehearsal ran against the public URL on a venue-like network;
this runbook and `KNOWN_ISSUES.md` both exist and are committed.

| Field | Value |
|---|---|
| Deployed commit (full SHA) | `b032252690a51a96b2c776bb2fd29c4e99ce70c3` |
| Tag | `demo-v1.0` |
| Tag short SHA (what `/health`'s `commit` field must equal) | `5f48e76` |
| Migration head | `b9e4c7a2f815` (queried live from `alembic_version` in the local demo DB; also what `/health` reports) |
| `TRIAGE_ENGINE` | `fallback` (confirmed live via `/health` during the rollback rehearsal) |
| `ESCALATION_ENGINE` | `fallback` (confirmed live via `/health` during the rollback rehearsal) |
| Seed script | `scripts/seed_demo.py` (deterministic — fixed UUIDs/names, idempotent truncate+reinsert; `scripts/reset_demo.sh` wraps it with row-count verification) |
| DB snapshot | `backend/backups/demo_frozen_2026-09-15.sql` (local demo DB only — see caveat below) |
| Rollback rehearsal time | 48 seconds, real, measured (checkout of `demo-v1.0` + `docker compose up --build -d` + DB restore + `/health` commit verification, start to finish) |
| Freeze owner | Iqra Khan |
| Freeze timestamp | 2026-09-15 17:39 IST |

**Caveats, stated plainly, not papered over:**

- The public-deployment `/health` commit check (`curl $PUBLIC_URL/health |
  jq .commit`, expected to equal `5f48e76`) could **not** be executed
  from this session — there is no `PUBLIC_URL` reachable here, and no
  access to the real deployed instance. Whoever owns that deployment
  must run this check themselves before the freeze is truly complete.
- The DB snapshot above is of the **local** demo database (the
  `setu_swasthya_db` Docker container), not necessarily the actual
  public deployment's database. If the real deployment uses a separate
  database, it needs its own snapshot, taken by whoever has access to
  it.
- `docker-compose.yml`'s `api` service did not wire `GIT_COMMIT` through
  to the container as of this freeze commit. For the local rollback
  rehearsal, this was patched **temporarily and locally only** (not
  committed, not part of the frozen tag) so the `/health` commit
  comparison would be meaningful rather than showing `"unknown"`. This
  is a real, open gap: any real deployment must set `GIT_COMMIT` at
  build/deploy time by whatever mechanism that platform uses (build arg,
  CI env var, etc.) for `/health`'s commit field to ever be anything
  other than `"unknown"` in production. Recommend wiring
  `GIT_COMMIT: ${GIT_COMMIT}` into `docker-compose.yml`'s `api.environment`
  block as a real follow-up, reviewed and committed separately from this
  freeze.

## Unfreeze criteria

Only a P0 demo blocker found **after** the freeze justifies unfreezing.
If that happens:

1. Both backend owners must agree in writing.
2. The fix must be the smallest possible change.
3. The **full** 24-test smoke suite must re-run — not just the fixed
   test.
4. A new tag `demo-v1.1` must be created.
5. The rollback rehearsal must run again.

If there is not time to re-run the smoke suite, there is not time to
make the change — ship the known bug and narrate around it instead. A
known bug is manageable; an untested fix is not.

## Branch status

No further pushes to `backend` after `demo-v1.0`. Day 4 work goes on
`day4/*` branches.
