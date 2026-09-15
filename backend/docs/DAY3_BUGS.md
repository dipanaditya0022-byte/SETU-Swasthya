# Day 3 readiness verification — status: PASS (with fixes applied)

Verified against a genuinely clean checkout, not the existing working
directory. Method: `cd /tmp && rm -rf setu-verify && git clone ... setu-verify`,
then the setup was followed as documented — nothing copied in from any
existing `.venv`, Docker volume, or `.env`.

- Clean clone: `/tmp/setu-verify`, branch `backend`
- HEAD verified: `5ffb7e2 Iqra Khan merge: bring in Day 2 T1-T5
  triage/referral/dashboard implementation from worktree-lazy-wishing-key`
  — matches the real working repo, so this run is current.
- Setup path used: `README.md` → "⚡ Getting started" → "Backend setup" →
  **Option A (Docker, `docker compose up --build`)** — the task's named
  `backend/docs/DockerPrompt.md` does not exist (see bug #1).

---

## 1. Setup timing

| Step | Time | Notes |
|---|---|---|
| `git clone` | ~4.4s | negligible |
| `git checkout` + `git pull --rebase` | ~3.1s | required a workaround — see bug #2 |
| `.env` population (copy template + generate JWT keypair + `FIELD_ENCRYPTION_KEY` + `BLIND_INDEX_KEY` + `APP_USER_PASSWORD`) | ~10s hands-on | see bug #3 — commands exist but aren't consolidated into one runbook step |
| `docker compose up --build -d` (image build + Postgres healthy + API container start) | **42.8s** | includes full `pip install` of all deps inside the image, migrations run automatically via the container's startup command |
| `alembic upgrade head` | included above, 0 extra | runs automatically on API container start (Dockerfile `CMD`); confirmed clean in container logs, no errors |
| `/health` responding 200 | immediate (1st poll) | after container start |
| Seed a working demo login (`bootstrap_medical_officer.py`) | failed, then fixed, then instant | **P0 — see bug #4**, this is the real finding |

**Total elapsed, clone start → confirmed-working seeded demo account:**
`11:02:45 IST → 11:12:19 IST` = **9 minutes 34 seconds.**

**Verdict: PASS.** Well under the 20-minute threshold — but only because this
run stopped to fix bug #4 along the way. Anyone following the docs without
debugging access would have been stuck at "the documented test account
doesn't exist and the seed script crashes," not merely "slow."

---

## 2. Replay script

Written to `backend/scripts/day2_replay.sh` (also mirrored into the verified
clean checkout at `/tmp/setu-verify/backend/scripts/day2_replay.sh`), executed
for real with `curl`/`jq` against the container booted above. Full content:

```bash
#!/usr/bin/env bash
#
# day2_replay.sh -- Day 2 end-to-end replay against a running backend.
# Verified working end-to-end against a genuinely clean checkout,
# 2026-09-15. See backend/docs/DAY3_BUGS.md for the run this came from.
#
# Prereqs: curl, jq. Server must already be up (README.md "Backend setup")
# and a MEDICAL_OFFICER test account must already exist -- run
# backend/bootstrap_medical_officer.py first (requires a SUPERUSER to
# already exist -- run bootstrap_superuser.py, or apply migrations, which
# seed one -- before that).
#
# Usage: BASE_URL=http://localhost:8002 ./day2_replay.sh   (Docker/Option A)
#        BASE_URL=http://localhost:8000 ./day2_replay.sh   (venv/Option B)

set -u
BASE_URL="${BASE_URL:-http://localhost:8000}"
FACILITY_ID="${FACILITY_ID:-00000000-0000-0000-0000-000000000001}"
ORG_UNIT_ID="${ORG_UNIT_ID:-00000000-0000-0000-0000-000000000002}"
TEST_MOBILE="${TEST_MOBILE:-+919876500002}"
TEST_PASSWORD="${TEST_PASSWORD:-Med1calOfficer!Pass}"

PASS=0
FAIL=0
STEP=0

step_result() {
  local name="$1" expected="$2" actual="$3"
  STEP=$((STEP + 1))
  if [ "$actual" = "$expected" ]; then
    echo "PASS  [$STEP] $name -> HTTP $actual"
    PASS=$((PASS + 1))
  else
    echo "FAIL  [$STEP] $name -> expected HTTP $expected, got HTTP $actual"
    FAIL=$((FAIL + 1))
  fi
}

echo "== SETU-Swasthya Day 2 replay against $BASE_URL =="
echo

# --- 1. GET /health -------------------------------------------------------
resp=$(curl -s -o /tmp/day2_health.json -w '%{http_code}' "$BASE_URL/health")
step_result "GET /health" 200 "$resp"

# --- 2. POST /login ---------------------------------------------------------
resp=$(curl -s -o /tmp/day2_login.json -w '%{http_code}' -X POST "$BASE_URL/login" \
  -H 'Content-Type: application/json' \
  -d "{\"mobile\": \"$TEST_MOBILE\", \"password\": \"$TEST_PASSWORD\"}")
step_result "POST /login" 200 "$resp"

ACCESS_TOKEN=$(jq -r '.access_token // empty' /tmp/day2_login.json)
if [ -z "$ACCESS_TOKEN" ]; then
  echo "FAIL  [-] no access_token in /login response -- aborting remaining steps"
  echo "$PASS passed, $((FAIL + 1)) failed"
  exit 1
fi
AUTH_HEADER="Authorization: Bearer $ACCESS_TOKEN"

# --- 3. GET /me ---------------------------------------------------------
resp=$(curl -s -o /tmp/day2_me.json -w '%{http_code}' "$BASE_URL/me" -H "$AUTH_HEADER")
step_result "GET /me" 200 "$resp"

# --- 4. POST /patients/ -- trailing slash matters, contract path is literal
resp=$(curl -s -o /tmp/day2_patient.json -w '%{http_code}' -X POST "$BASE_URL/patients/" \
  -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d "{\"name\": \"Test Patient Day2\", \"age\": 27, \"village\": \"Test Village\", \"phone\": \"+919000000099\", \"facility_id\": \"$FACILITY_ID\", \"client_uuid\": null}")
step_result "POST /patients/" 200 "$resp"

PATIENT_ID=$(jq -r '.id // empty' /tmp/day2_patient.json)
if [ -z "$PATIENT_ID" ]; then
  echo "FAIL  [-] no patient id returned -- aborting remaining steps"
  echo "$PASS passed, $((FAIL + 1)) failed"
  exit 1
fi

# --- 5. GET /patients/{id} -----------------------------------------------
resp=$(curl -s -o /tmp/day2_patient_get.json -w '%{http_code}' "$BASE_URL/patients/$PATIENT_ID" -H "$AUTH_HEADER")
step_result "GET /patients/{id}" 200 "$resp"

# --- 6. POST /triage/ -- ANC, BP 156/98, severe_headache -------------------
resp=$(curl -s -o /tmp/day2_triage.json -w '%{http_code}' -X POST "$BASE_URL/triage/" \
  -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d "{
    \"patient_id\": \"$PATIENT_ID\",
    \"facility_id\": \"$FACILITY_ID\",
    \"triage_disposition\": \"Manage here\",
    \"referral_urgency\": \"routine\",
    \"protocol\": \"ANC\",
    \"vitals\": {\"bp_systolic\": 156, \"bp_diastolic\": 98},
    \"symptoms\": [\"severe_headache\"],
    \"danger_signs\": [],
    \"sex\": \"FEMALE\",
    \"is_pregnant\": true,
    \"gestational_weeks\": 32,
    \"history\": {}
  }")
step_result "POST /triage/ (ANC, BP 156/98, severe_headache)" 200 "$resp"
echo "      decision.disposition=$(jq -r '.decision.disposition // "?"' /tmp/day2_triage.json) decision.engine=$(jq -r '.decision.engine // "?"' /tmp/day2_triage.json)"

# --- 7. POST /referrals/ --------------------------------------------------
resp=$(curl -s -o /tmp/day2_referral.json -w '%{http_code}' -X POST "$BASE_URL/referrals/" \
  -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d "{
    \"patient_id\": \"$PATIENT_ID\",
    \"from_facility_id\": \"$FACILITY_ID\",
    \"destination_facility_id\": \"$FACILITY_ID\",
    \"reason\": \"Specialist consultation required\",
    \"urgency\": \"routine\",
    \"receiving_unit\": \"General OPD\",
    \"owner\": \"Test User\"
  }")
step_result "POST /referrals/" 200 "$resp"

REFERRAL_ID=$(jq -r '.id // empty' /tmp/day2_referral.json)
if [ -z "$REFERRAL_ID" ]; then
  echo "FAIL  [-] no referral id returned -- aborting remaining steps"
  echo "$PASS passed, $((FAIL + 1)) failed"
  exit 1
fi

# --- 8. PATCH /referrals/{id}/status?status=SLOT_BOOKED ---------------------
# status is a QUERY param, not a body field. INITIATED -> SLOT_BOOKED
# requires slot_datetime + destination_org_unit_id in the body.
resp=$(curl -s -o /tmp/day2_referral_status.json -w '%{http_code}' -X PATCH \
  "$BASE_URL/referrals/$REFERRAL_ID/status?status=SLOT_BOOKED" \
  -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d "{\"slot_datetime\": \"2026-09-20T10:00:00Z\", \"destination_org_unit_id\": \"$ORG_UNIT_ID\"}")
step_result "PATCH /referrals/{id}/status (SLOT_BOOKED)" 200 "$resp"

# --- 9. GET /referrals/exceptions ------------------------------------------
resp=$(curl -s -o /tmp/day2_exceptions.json -w '%{http_code}' "$BASE_URL/referrals/exceptions" -H "$AUTH_HEADER")
step_result "GET /referrals/exceptions" 200 "$resp"

# --- 10. GET /dashboard/facility/{org_unit_id} ------------------------------
resp=$(curl -s -o /tmp/day2_dashboard.json -w '%{http_code}' "$BASE_URL/dashboard/facility/$ORG_UNIT_ID" -H "$AUTH_HEADER")
step_result "GET /dashboard/facility/{org_unit_id}" 200 "$resp"

# --- 11. POST /sync/ --------------------------------------------------------
resp=$(curl -s -o /tmp/day2_sync.json -w '%{http_code}' -X POST "$BASE_URL/sync/" \
  -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d '[
    {"client_uuid": "test-client-001", "name": "Offline Patient 1"},
    {"client_uuid": "test-client-002", "name": "Offline Patient 2"}
  ]')
step_result "POST /sync/" 200 "$resp"

echo
echo "== Result: $PASS passed, $FAIL failed (of $STEP) =="
[ "$FAIL" -eq 0 ]
exit $?
```

### FIRST run (clean checkout, before any fix)

```
== SETU-Swasthya Day 2 replay against http://localhost:8002 ==

PASS  [1] GET /health -> HTTP 200
PASS  [2] POST /login -> HTTP 200
PASS  [3] GET /me -> HTTP 200
FAIL  [4] POST /patients/ -> expected HTTP 201, got HTTP 200
PASS  [5] GET /patients/{id} -> HTTP 200
FAIL  [6] POST /triage/ (ANC, BP 156/98, severe_headache) -> expected HTTP 201, got HTTP 200
      decision.disposition=REFER decision.engine=fallback
FAIL  [7] POST /referrals/ -> expected HTTP 201, got HTTP 200
PASS  [8] PATCH /referrals/{id}/status (SLOT_BOOKED) -> HTTP 200
PASS  [9] GET /referrals/exceptions -> HTTP 200
PASS  [10] GET /dashboard/facility/{org_unit_id} -> HTTP 200
PASS  [11] POST /sync/ -> HTTP 200

== Result: 8 passed, 3 failed (of 11) ==
```

Note: the `/login` step in this first run only succeeded because
`bootstrap_medical_officer.py` had *already* been fixed and re-run by that
point (see bug #4) — it originally crashed with a `ForeignKeyViolation` on
a truly fresh database, before step 1 of this script could have logged in
at all. That failure and its fix are documented separately since it's a
seed-script bug, not a replay-script bug (bug #4 below).

### FINAL run (after fixing the 3 status-code assumptions — see bug #5)

```
== SETU-Swasthya Day 2 replay against http://localhost:8002 ==

PASS  [1] GET /health -> HTTP 200
PASS  [2] POST /login -> HTTP 200
PASS  [3] GET /me -> HTTP 200
PASS  [4] POST /patients/ -> HTTP 200
PASS  [5] GET /patients/{id} -> HTTP 200
PASS  [6] POST /triage/ (ANC, BP 156/98, severe_headache) -> HTTP 200
      decision.disposition=REFER decision.engine=fallback
PASS  [7] POST /referrals/ -> HTTP 200
PASS  [8] PATCH /referrals/{id}/status (SLOT_BOOKED) -> HTTP 200
PASS  [9] GET /referrals/exceptions -> HTTP 200
PASS  [10] GET /dashboard/facility/{org_unit_id} -> HTTP 200
PASS  [11] POST /sync/ -> HTTP 200

== Result: 11 passed, 0 failed (of 11) ==
```

Exit code `0`. Response bodies spot-checked (not just status codes): the
triage decision correctly computed `REFER`/`fallback` for BP 156/98 +
severe_headache under the ANC protocol; the `SLOT_BOOKED` PATCH returned
the full referral with `slot_datetime` and `destination_facility_id` set;
`/referrals/exceptions` and `/dashboard/facility/{id}` reflected the just-created
referral in their counts; `/sync/` accepted both offline records.

---

## 3. Bug table

| # | Sev | Endpoint | Symptom | Root cause | Fix | Verified by | Owner |
|---|---|---|---|---|---|---|---|
| 1 | P1 | N/A (setup doc) | Task instructions said to follow `backend/docs/DockerPrompt.md` "as written" — file does not exist anywhere in the repo (`find`/`Glob` for `*ocker*rompt*`, zero matches; only `Dockerfile`, `.dockerignore`, `docker-compose.yml` exist) | Dangling/nonexistent doc reference | Not fixed — inventing the file's content would be guessing at intent. Used the real documented path instead: `README.md` → "Backend setup" (confirmed consistent with `Day1.md` Appendix B and `Day2.md`'s migration expectations) | Confirmed missing by search; real path confirmed working by completing full setup and replay through it | unassigned — human should confirm whether `DockerPrompt.md` should exist |
| 2 | P1 | N/A (git onboarding) | `git checkout backend` (as literally instructed) fails on a fresh clone: `fatal: 'backend' could be both a local file and a tracking branch` | Repo has a top-level `backend/` directory colliding with the branch name of the same name | Not fixed (repo layout change is out of scope here) — workaround used and confirmed: `git checkout -b backend origin/backend` | Reproduced directly on the actual clean clone at `/tmp/setu-verify`; workaround confirmed to succeed | unassigned |
| 3 | P1 | N/A (setup doc) | README's "Backend setup" says `cp .env.example .env` then "fill in real values" — but the actual generation commands (`openssl genrsa`/`openssl rsa`/`openssl rand -hex 32`/`openssl rand -base64 24`) exist only as scattered inline comments in `.env.example` (duplicated verbatim in `Day1.md` Appendix B), not as one consolidated runbook step. A `.env` left with the placeholder `CHANGE_ME_64_HEX_CHARS` values crashes the app at import time (`bytes.fromhex()` on a non-hex string in `app/core/crypto.py`) | Setup doc doesn't walk through required-secret generation as an explicit numbered step | Not fixed — `app/core/crypto.py` already wraps this in a clear `CryptoConfigError` naming which key and why (confirmed by reading the module; it's already fail-fast with a good message, not a silent/mystifying failure), so this is a documentation consolidation gap, not a code defect. Recommend a follow-up doc PR adding the four `openssl` commands as one visible step in README's Option A/B, not a code change | Confirmed by reading `app/core/crypto.py`'s `_load_key()`; the actual setup in this run generated real values and booted cleanly in ~43s | unassigned |
| 4 | **P0** | `POST /login` (blocks the entire chain) | `backend/bootstrap_medical_officer.py` — the script that seeds the documented demo login (`+919876500002` / `Med1calOfficer!Pass`) — crashed on a genuinely fresh database: `psycopg.errors.ForeignKeyViolation: insert or update on table "users" violates foreign key constraint "users_created_by_user_id_fkey"` | The script hardcoded `SUPERUSER_ID = "f2014011-998c-48f1-8231-673c4be286bf"` as the `created_by_user_id` for the seeded medical officer. That UUID only ever existed on whichever laptop's local DB `bootstrap_superuser.py` happened to generate it on — `bootstrap_superuser.py` uses the database's `gen_random_uuid()` default, so the id is different on every fresh database. **This is the exact "works on my laptop" bug this exercise was built to catch** | **Fixed.** `bootstrap_medical_officer.py` now looks up an existing `SUPERUSER` dynamically (`SELECT id FROM users WHERE role='SUPERUSER' ORDER BY activated_at ASC LIMIT 1`) instead of a hardcoded literal, and exits with a clear message if none exists. Applied to both `/Users/pram/Desktop/SETU-Swasthya/backend/bootstrap_medical_officer.py` (real repo, uncommitted, ready for review) and mirrored into `/tmp/setu-verify` | Re-ran the exact failing command (`docker exec setu_swasthya_api python bootstrap_medical_officer.py`) on the same clean database — now succeeds: `Created MEDICAL_OFFICER id=cc46b501-f74a-415d-bfcb-6c62b3f0cfa2`. Then re-ran the full 11-step chain end-to-end, all green | unassigned |
| 5 | P2 | `POST /patients/`, `POST /triage/`, `POST /referrals/` | Replay script initially expected `HTTP 201` on all three creates; server returns `200` | My own replay-script assumption, not a backend bug — checked `API_CONTRACT.md` first per the task's own constraint: it never actually promises `201` for these three (only says "Returns the created X"; contrast with the invite endpoint, which explicitly documents `201`). Confirmed in route source: none of `create_patient`/`create_triage`/`create_referral` declare `status_code=201`, so FastAPI's default `200` is the real, intended behavior | Fixed the **script**, not the API, per the task's explicit rule ("if the contract and the [caller] disagree, the [caller] is wrong... unless the contract itself confirms the backend is wrong" — it doesn't here) | Re-ran the exact 3 requests — all now report the correct expected code and PASS. Full chain re-run, all green | n/a (script bug) |
| 6 | P2 | `GET /referrals/exceptions`, `GET /dashboard/facility/{org_unit_id}` | Both endpoints work correctly (verified live) but are **not documented** in `API_CONTRACT.md` at all — only in `Day2.md` (T4/T5) and route source | `API_CONTRACT.md` wasn't updated when the Day 2 T4/T5 endpoints shipped | LOG ONLY, not fixed — per task rules, P2s are not touched today | n/a — logged only | unassigned |

---

## Appendix — fix applied

`backend/bootstrap_medical_officer.py` diff (summary): removed the hardcoded
`SUPERUSER_ID` literal; added a dynamic lookup of the earliest existing
`SUPERUSER` row, with a clear `SystemExit` if none exists yet. No API
behavior changed — this is a dev-only seeding script, not a contract
endpoint, so `API_CONTRACT.md` was not touched.

Not committed — left as an uncommitted change in the working tree for
review/commit by a human or a git-manager agent.
