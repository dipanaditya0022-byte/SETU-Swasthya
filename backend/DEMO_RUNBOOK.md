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
