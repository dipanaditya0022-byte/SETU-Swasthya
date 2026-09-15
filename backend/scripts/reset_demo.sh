#!/usr/bin/env bash
# reset_demo.sh -- fast demo-database reset (Day-3 demo-prep task).
#
# Re-seeds the deterministic demo dataset (scripts/seed_demo.py), then
# verifies row counts and prints the fixed-UUID table. Run this between
# rehearsal and the real thing, and possibly DURING -- must complete in
# well under 30 seconds (task's own hard requirement; timed for real,
# see backend/docs/DAY3_BUGS.md or the delivery report this script
# shipped with for the actual measured number, not an estimate).
#
# seed_demo.py itself already truncates the demo-owned tables before
# re-inserting (see that file's own module docstring) -- this script's
# job is: run it, verify the result actually landed correctly, and fail
# loudly (non-zero exit) if it didn't, rather than silently leaving a
# half-seeded demo database before someone walks on stage.
#
# Usage: ./scripts/reset_demo.sh
# Must be run with the same DATABASE_URL/.env the real API server uses
# (via docker exec into the running API container, matching how every
# other bootstrap/seed script in this repo already runs) -- NOT a
# separate DB connection that could point somewhere else by accident.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
API_CONTAINER="${API_CONTAINER:-setu_swasthya_api}"
DB_CONTAINER="${DB_CONTAINER:-setu_swasthya_db}"
DB_USER="${DB_USER:-setu_dev}"
DB_NAME="${DB_NAME:-setu_swasthya}"

START_TIME=$(date +%s.%N)

echo "== reset_demo.sh: re-seeding demo dataset =="

if ! docker exec "$API_CONTAINER" true 2>/dev/null; then
  echo "FATAL: container '$API_CONTAINER' is not running. Start the stack first (docker compose up -d)." >&2
  exit 1
fi

# --- run the seed script inside the API container (has app/ on its own
# image, correct DATABASE_URL via its own .env -- matches exactly how
# bootstrap_medical_officer.py/bootstrap_superuser.py already run). ---
docker exec -e PYTHONPATH=/app "$API_CONTAINER" python scripts/seed_demo.py

# --- verify row counts landed exactly as expected. Fails loudly (exit
# 1) rather than silently reporting success on a partially-seeded DB. ---
echo
echo "== verifying row counts =="

EXPECTED_ORG_UNITS=6      # 1 district + 1 block + 1 PHC + 1 HWC + 2 villages
EXPECTED_USERS=8          # 6 named staff + 1 patient-login account + 1 bootstrap SUPERUSER (plumbing only, see seed_demo.py)
EXPECTED_PATIENTS=12
EXPECTED_TRIAGE=8
EXPECTED_REFERRALS=5

ACTUAL=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "
  SELECT
    (SELECT count(*) FROM org_units WHERE id::text LIKE '00000000-0000-0000-0001%') || ',' ||
    (SELECT count(*) FROM users WHERE id::text LIKE '00000000-0000-0000-0002%') || ',' ||
    (SELECT count(*) FROM patient WHERE id::text LIKE '00000000-0000-0000-0003%') || ',' ||
    (SELECT count(*) FROM triageencounter WHERE id::text LIKE '00000000-0000-0000-0004%') || ',' ||
    (SELECT count(*) FROM referral WHERE id::text LIKE '00000000-0000-0000-0005%');
")

IFS=',' read -r ACTUAL_ORG ACTUAL_USERS ACTUAL_PATIENTS ACTUAL_TRIAGE ACTUAL_REFERRALS <<< "$ACTUAL"

FAILED=0
check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" != "$actual" ]; then
    echo "  FAIL  $label: expected $expected, got $actual" >&2
    FAILED=1
  else
    echo "  OK    $label: $actual"
  fi
}
check "org_units"       "$EXPECTED_ORG_UNITS"  "$ACTUAL_ORG"
check "users"            "$EXPECTED_USERS"      "$ACTUAL_USERS"
check "patient"          "$EXPECTED_PATIENTS"   "$ACTUAL_PATIENTS"
check "triageencounter"  "$EXPECTED_TRIAGE"     "$ACTUAL_TRIAGE"
check "referral"         "$EXPECTED_REFERRALS"  "$ACTUAL_REFERRALS"

END_TIME=$(date +%s.%N)
ELAPSED=$(python3 -c "print(f'{$END_TIME - $START_TIME:.2f}')")

echo
echo "== reset_demo.sh complete in ${ELAPSED}s =="

if [ "$FAILED" -ne 0 ]; then
  echo "FATAL: row-count verification failed -- demo database is NOT in a known-good state." >&2
  exit 1
fi

echo "Demo database verified: all row counts match expected."
