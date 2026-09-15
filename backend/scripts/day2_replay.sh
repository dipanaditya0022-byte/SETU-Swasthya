#!/usr/bin/env bash
#
# day2_replay.sh -- Day 2 end-to-end replay against a freshly booted backend.
#
# STATUS: WRITTEN BUT NEVER EXECUTED.
# The agent that authored this script had no shell/exec tool available in
# its session (Read/Write/Edit/Grep/Glob only) and could not start Docker,
# run alembic, boot uvicorn, or invoke curl. Every field name, method, path,
# and enum value below was taken directly from backend/docs/API_CONTRACT.md
# and backend/docs/Day2.md (and, where the contract was silent, from the
# route source in app/api/routes/*.py) -- NOT guessed -- but the script
# itself has not been run once. Treat every line as "should be right per
# the docs" not "confirmed working." Run it, fix whatever curl/jq
# incompatibilities show up, and re-verify before trusting it in a demo.
#
# Prereqs: curl, jq. Server must already be up (see README.md "Backend
# setup -> Option B" for the plain-venv path, or Option A for Docker) and
# a MEDICAL_OFFICER test account must already exist -- this repo already
# ships backend/bootstrap_medical_officer.py for that (fake dev creds:
# mobile +919876500002 / password Med1calOfficer!Pass, matching C5 --
# development data only, not a real credential).
#
# Usage: BASE_URL=http://localhost:8000 ./day2_replay.sh

set -u
BASE_URL="${BASE_URL:-http://localhost:8000}"
FACILITY_ID="${FACILITY_ID:-00000000-0000-0000-0000-000000000001}"
ORG_UNIT_ID="${ORG_UNIT_ID:-00000000-0000-0000-0000-000000000002}"
TEST_MOBILE="${TEST_MOBILE:-+919876500002}"
TEST_PASSWORD="${TEST_PASSWORD:-Med1calOfficer!Pass}"

PASS=0
FAIL=0
STEP=0

# step <name> <expected_status> <actual_status>
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

# --- 1. GET /health -----------------------------------------------------
resp=$(curl -s -o /tmp/day2_health.json -w '%{http_code}' "$BASE_URL/health")
step_result "GET /health" 200 "$resp"

# --- 2. POST /login -------------------------------------------------------
# Contract: backend/docs/API_CONTRACT.md "POST /login" -- mobile+password
# for a password-login role (MEDICAL_OFFICER).
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

# --- 3. GET /me -------------------------------------------------------
resp=$(curl -s -o /tmp/day2_me.json -w '%{http_code}' "$BASE_URL/me" -H "$AUTH_HEADER")
step_result "GET /me" 200 "$resp"

# --- 4. POST /patients/ -------------------------------------------------
# Trailing slash matters -- contract path is literally "POST /patients/".
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

# --- 5. GET /patients/{id} ---------------------------------------------
resp=$(curl -s -o /tmp/day2_patient_get.json -w '%{http_code}' "$BASE_URL/patients/$PATIENT_ID" -H "$AUTH_HEADER")
step_result "GET /patients/{id}" 200 "$resp"

# --- 6. POST /triage/ -- ANC, BP 156/98, severe_headache ----------------
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

# --- 7. POST /referrals/ ------------------------------------------------
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

# --- 8. PATCH /referrals/{id}/status?status=SLOT_BOOKED -----------------
# status is a QUERY param per the contract, not a body field.
# INITIATED -> SLOT_BOOKED requires slot_datetime + destination_org_unit_id
# in the (additive, optional-at-schema-level) body -- see
# app/api/routes/referrals.py ReferralStatusUpdateBody / TRANSITION_REQUIRED_FIELDS.
resp=$(curl -s -o /tmp/day2_referral_status.json -w '%{http_code}' -X PATCH \
  "$BASE_URL/referrals/$REFERRAL_ID/status?status=SLOT_BOOKED" \
  -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -d "{\"slot_datetime\": \"2026-09-20T10:00:00Z\", \"destination_org_unit_id\": \"$ORG_UNIT_ID\"}")
step_result "PATCH /referrals/{id}/status (SLOT_BOOKED)" 200 "$resp"

# --- 9. GET /referrals/exceptions ---------------------------------------
# NOTE: not documented in API_CONTRACT.md (only in Day2.md T4) -- see
# DAY3_BUGS.md finding on the contract doc gap.
resp=$(curl -s -o /tmp/day2_exceptions.json -w '%{http_code}' "$BASE_URL/referrals/exceptions" -H "$AUTH_HEADER")
step_result "GET /referrals/exceptions" 200 "$resp"

# --- 10. GET /dashboard/facility/{org_unit_id} ---------------------------
# NOTE: not documented in API_CONTRACT.md (only in Day2.md T5).
resp=$(curl -s -o /tmp/day2_dashboard.json -w '%{http_code}' "$BASE_URL/dashboard/facility/$ORG_UNIT_ID" -H "$AUTH_HEADER")
step_result "GET /dashboard/facility/{org_unit_id}" 200 "$resp"

# --- 11. POST /sync/ ------------------------------------------------------
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
