"""GET /dashboard/facility/{org_unit_id} -- new, additive (C1: does not
touch any of the nine frozen endpoints or any other existing route).
`require("dashboard:facility")` (already seeded, e5a83c1f9d6b -- no new
permission row needed for this step).

WHAT IS VERBATIM VS THIS ROUTE'S OWN DESIGN -- read before reviewing:

- Real table names -- `referral`, `triageencounter`, `patient` (singular),
  confirmed directly against the live dev DB (`\\d referral` /
  `\\d triageencounter`), not the plural names used loosely in prose
  elsewhere. Both `referral` and `triageencounter` have a real, NOT NULL,
  FK'd `org_unit_id` column (migration 9d5f6b3e0a71) -- used for facility
  scoping on both. There is no `origin_org_unit_id` anywhere.
- `referral.status` is a real Postgres enum (`referral_status`, 13
  values -- app/models/referral_state.py). `triageencounter.created_at`
  and `patient.created_at` are naive `TIMESTAMP` columns, always written
  as naive-UTC (`default_factory=datetime.utcnow`, same convention as
  every other Day 1 table -- verified against 79a9d8f8db61's own
  `CREATE TABLE` for all three). `referral.created_at` is ALSO a naive
  `TIMESTAMP` (same migration, same convention) -- used here for the
  synced_today denominator's referral leg; `referral.initiated_at`
  (a separate, tz-aware `TIMESTAMPTZ` column, D2-S8) is NOT used by this
  route, since "records created on `date`" is this route's own choice
  to key off the same `created_at` column every other Day 1 table uses,
  not off a referral-only workflow timestamp.

===========================================================================
GAP 1 -- FACILITY TIMEZONE. Flagged, not silently guessed.
===========================================================================
`org_units` (0e21a4d7c6f5's own `CREATE TABLE`) has no timezone column,
and no other table in this schema carries one either (checked directly,
not assumed). Day1.md does not define one. This is a genuine, currently
unfillable gap: there is no way, today, to compute "midnight in this
specific facility's own timezone" from data that exists.

RESOLVED HERE (flagged for the human, not silently decided as gospel):
this system is India-only (every fixture, every org-unit hierarchy, every
role in Day1.md is India-specific), so a single fixed offset, IST
(UTC+05:30, `_FACILITY_TZ_OFFSET` below), is used for every facility --
NOT the server's own UTC clock silently relabelled as "the facility's
timezone". This is a placeholder for a real per-facility (or, more
realistically for India, a single national) timezone concept that does
not exist in this schema yet; if `org_units` ever needs to represent a
facility genuinely outside IST, this constant is the one place that
assumption would need to become real per-row data.

===========================================================================
GAP 2 -- synced_today's numerator. Real, structural, documented at every
site a reader would look -- see migration b9e4c7a2f815's own docstring
("THE SYNC/synced_at GAP") and app/api/routes/sync.py's own module
docstring for the full finding. Repeated concretely on `_synced_metrics`
below, at the exact point it bites.
===========================================================================

===========================================================================
CACHING -- 60s TTL, keyed on (org_unit_id, date).
===========================================================================
Checked for any existing generic cache mechanism before adding one:
`functools.lru_cache` is used exactly twice in this codebase
(app/services/triage/factory.py, app/services/escalation/factory.py),
both for a permanent, maxsize=1 *readiness probe* result -- a different
kind of cache (no TTL, no key), not reusable here. No `cachetools`, no
redis, no other generic cache layer exists anywhere in this codebase
(grepped directly). `cachetools` is also not in requirements.txt, so it
is not added as a new dependency for one route -- a small in-process
dict + monotonic-clock TTL cache is implemented locally below instead
(`_DashboardCache`).

LIMITATION, stated plainly: this cache is per-process. Under multiple
uvicorn workers (`--workers N`) or multiple horizontally-scaled
containers, each process holds its own independent cache, so the same
(org_unit_id, date) can be computed freshly once per process within any
given 60s window, and a write immediately after a read in a DIFFERENT
process is not reflected in the first process's still-warm cache entry
for up to 60s. Acceptable for a facility-level operational dashboard
(Day1.md gives no staleness SLA tighter than this), not acceptable if
this route is ever asked to back a real-time alerting path -- flagged
here for that future reader.

The 403/404 scope check (below) is NEVER cached -- it is re-evaluated on
every single request, for every actor, before any cache lookup happens.
Only the resulting METRICS PAYLOAD for a given (org_unit_id, date) is
cached; a cache hit for a facility one actor is scoped to is never
served to a second actor who is not (that second actor's own request
still gets its own fresh 404 first).
"""
from __future__ import annotations

from datetime import date as date_type, datetime, time as time_type, timedelta, timezone
from time import monotonic
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, text

from app.core.authz import org_unit_is_within_scope, require
from app.db.database import get_session
from app.models.referral_state import COMPLETED_STATES, ReferralState, TERMINAL_STATES

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# GAP 1 (see module docstring): no per-facility timezone data exists
# anywhere in this schema. Fixed IST offset used for every facility.
_FACILITY_TZ_OFFSET = timedelta(hours=5, minutes=30)

_CACHE_TTL_SECONDS = 60.0


# ============================================================
# Simple in-process TTL cache -- see module docstring "CACHING" for why
# this exists instead of a generic dependency.
# ============================================================
class _DashboardCache:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[tuple[str, str], tuple[float, dict]] = {}

    def get(self, key: tuple[str, str]) -> Optional[dict]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: tuple[str, str], value: dict) -> None:
        self._store[key] = (monotonic() + self._ttl, value)


_cache = _DashboardCache(_CACHE_TTL_SECONDS)


def _sql_in_list(values) -> str:
    """Builds a literal SQL `(...)` list from a fixed, code-controlled set
    of enum values -- never from request input, so this is not a SQL
    injection surface (same reasoning as migration d4f1c9b7a582's own
    hand-written CASE list of the same 13 canonical values)."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# Open-referral exclusion, per this route's own `open_referrals` metric
# definition (task-specified verbatim): TERMINAL_STATES = {CLOSED,
# CANCELLED}.
_TERMINAL_SQL = _sql_in_list(s.value for s in TERMINAL_STATES)

# Breach exclusion, translating app/services/referral/breach.py's
# is_breached() RULE into SQL -- see _referral_metrics' own docstring for
# the full translation statement. is_breached() excludes COMPLETED_STATES
# ({ARRIVED, CONSULTED, BACK_REFERRED, CLOSED}) and CANCELLED; the union
# of those two sets is used here (CLOSED appears in both, so plain set
# union already dedupes it).
_BREACH_EXCLUDED_SQL = _sql_in_list(
    sorted({s.value for s in COMPLETED_STATES} | {ReferralState.CANCELLED.value})
)


def _org_unit_lookup(session: Session, org_unit_id: UUID) -> Optional[tuple]:
    row = session.exec(
        text("SELECT id, name, unit_type FROM org_units WHERE id = :id"),
        params={"id": str(org_unit_id)},
    ).first()
    return row


def _referral_metrics(session: Session, org_unit_id: UUID, now: datetime) -> tuple[int, int]:
    """`open_referrals` and `breached` in ONE query (they share the same
    base table and facility filter -- computing them separately would
    scan `referral` for this facility twice for no benefit).

    open_referrals -- numerator: referrals with org_unit_id = this
    facility whose status is NOT in TERMINAL_STATES ({CLOSED, CANCELLED}).
    No denominator.

    breached -- numerator: open referrals (as just defined) where
    is_breached() (app/services/referral/breach.py) would return True.
    denominator: open_referrals' own numerator.

    TRANSLATION OF is_breached() INTO SQL, STATED EXPLICITLY FOR AUDIT
    AGAINST THE PYTHON ORIGINAL: is_breached(referral, now) is:
        status not in COMPLETED_STATES
        and status != CANCELLED
        and due_at is not None
        and now > due_at
    This is NOT re-implemented differently here -- the SQL FILTER clause
    below applies the exact same four conditions: `status NOT IN
    <COMPLETED_STATES ∪ {CANCELLED}>` (which also implies "not
    TERMINAL_STATES", so the breached count is always a subset of the
    open_referrals count) AND `due_at IS NOT NULL` AND `due_at < :now`.
    If either is_breached() or COMPLETED_STATES/TERMINAL_STATES ever
    changes, `_BREACH_EXCLUDED_SQL`/`_TERMINAL_SQL` (derived from those
    same Python constants, not hand-duplicated values) change with it --
    only the raw SQL keyword shape (NOT IN / FILTER) is hand-written.
    """
    row = session.exec(
        text(
            f"""
            SELECT
                count(*) FILTER (WHERE status NOT IN {_TERMINAL_SQL}) AS open_count,
                count(*) FILTER (
                    WHERE status NOT IN {_BREACH_EXCLUDED_SQL}
                      AND due_at IS NOT NULL
                      AND due_at < :now
                ) AS breached_count
            FROM referral
            WHERE org_unit_id = :org_unit_id
            """
        ),
        params={"org_unit_id": str(org_unit_id), "now": now},
    ).first()
    open_count, breached_count = row
    return int(open_count), int(breached_count)


def _triage_today_count(session: Session, org_unit_id: UUID, start_naive: datetime, end_naive: datetime) -> int:
    """triage_today -- numerator: triage encounters created at this
    facility (org_unit_id = this facility) on `date`. No denominator.

    `created_at` is a naive TIMESTAMP written as naive-UTC (see module
    docstring); `start_naive`/`end_naive` are the [start, end) instant
    boundaries of the requested facility-local calendar day, already
    converted to that same naive-UTC representation by the route before
    this function is called -- this function does no timezone math of
    its own.
    """
    row = session.exec(
        text(
            "SELECT count(*) FROM triageencounter "
            "WHERE org_unit_id = :org_unit_id AND created_at >= :start AND created_at < :end"
        ),
        params={"org_unit_id": str(org_unit_id), "start": start_naive, "end": end_naive},
    ).first()
    return int(row[0])


def _synced_metrics(
    session: Session, org_unit_id: UUID,
    start_naive: datetime, end_naive: datetime,
    start_tz: datetime, end_tz: datetime,
) -> tuple[int, int]:
    """synced_today -- numerator: records from this facility with
    synced_at falling on `date` (facility-local calendar day), across
    patient/referral/triageencounter. denominator: records from this
    facility created on `date` (by org_unit_id + created_at), across the
    same three tables.

    ONE query: a UNION ALL CTE over the three tables (each already
    filtered to this facility + this day's `created_at` window, so the
    CTE itself is small), then a single pass computing both the
    denominator (count(*)) and the numerator (count(*) FILTER WHERE
    synced_at falls in this same day's window) over it.

    ***THE GAP THAT MAKES THIS METRIC HONEST, NOT SILENTLY WRONG***
    (see migration b9e4c7a2f815's own docstring "THE SYNC/synced_at GAP"
    and app/api/routes/sync.py's own module docstring for the full
    finding): only `patient` rows can ever have a non-NULL `synced_at`
    today, because only `patient` has a `client_uuid` column for
    POST /sync/ to match against. `referral` and `triageencounter` rows
    are included in this metric's DENOMINATOR (they were genuinely
    created at this facility on this day) but their `synced_at` is
    always NULL, so they can never contribute to the NUMERATOR. This
    means `synced_today.rate_pct` is structurally capped below 100%
    whenever this facility created any referral or triage encounter that
    day, even in a hypothetical world where every single patient record
    synced successfully -- this is not a bug in this query, it is this
    schema's real current sync-coverage gap, reported here instead of
    quietly averaged away.
    """
    row = session.exec(
        text(
            """
            WITH combined AS (
                SELECT synced_at FROM patient
                WHERE org_unit_id = :org_unit_id AND created_at >= :start AND created_at < :end
                UNION ALL
                SELECT synced_at FROM referral
                WHERE org_unit_id = :org_unit_id AND created_at >= :start AND created_at < :end
                UNION ALL
                SELECT synced_at FROM triageencounter
                WHERE org_unit_id = :org_unit_id AND created_at >= :start AND created_at < :end
            )
            SELECT
                count(*) AS denominator,
                count(*) FILTER (
                    WHERE synced_at IS NOT NULL AND synced_at >= :start_tz AND synced_at < :end_tz
                ) AS numerator
            FROM combined
            """
        ),
        params={
            "org_unit_id": str(org_unit_id), "start": start_naive, "end": end_naive,
            "start_tz": start_tz, "end_tz": end_tz,
        },
    ).first()
    denominator, numerator = row
    return int(numerator), int(denominator)


def _rate_pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


@router.get("/facility/{org_unit_id}")
def get_facility_dashboard(
    org_unit_id: UUID,
    date: Optional[date_type] = Query(default=None, description="Facility-local calendar date; defaults to today in the facility's own timezone (see route docstring GAP 1)."),
    current_user=Depends(require("dashboard:facility")),
    session: Session = Depends(get_session),
):
    # ---- STEP 1: scope check on the TARGET facility, 404 not 403 -- same
    # anti-enumeration reasoning as every other existing-record scope
    # check in this codebase (app.core.authz's own module docstring,
    # GET /referrals/exceptions's own org_unit_id drill-down). Never
    # cached -- re-checked on every request for every actor. ----
    if not org_unit_is_within_scope(session, org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(404, {"code": "FACILITY_NOT_IN_SCOPE", "detail": "Not found."})

    facility_row = _org_unit_lookup(session, org_unit_id)
    # org_unit_is_within_scope already proved this org unit exists and is
    # reachable, so facility_row cannot be None here.
    facility_id, facility_name, facility_type = facility_row

    # ---- STEP 2: resolve the effective date -- GAP 1 (module docstring):
    # "today" defaults to today in the fixed IST offset, not the server's
    # own UTC clock. ----
    effective_date = date or (datetime.now(timezone.utc) + _FACILITY_TZ_OFFSET).date()

    cache_key = (str(org_unit_id), effective_date.isoformat())
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # ---- STEP 3: day-boundary instants, both representations needed --
    # naive-UTC for the three tables' naive `created_at` columns, and
    # tz-aware for `synced_at` (TIMESTAMPTZ, migration b9e4c7a2f815) and
    # `due_at` (TIMESTAMPTZ, migration d4f1c9b7a582). Both pairs describe
    # the exact same real-world instants; only the Python representation
    # differs, matching each column's own storage type. ----
    day_start_local_naive = datetime.combine(effective_date, time_type.min)
    day_start_naive = day_start_local_naive - _FACILITY_TZ_OFFSET
    day_end_naive = day_start_naive + timedelta(days=1)
    day_start_tz = day_start_naive.replace(tzinfo=timezone.utc)
    day_end_tz = day_end_naive.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)

    # ---- STEP 4: the metrics -- three queries total (see each function's
    # own docstring for exactly what it computes and why it's one query). ----
    open_count, breached_count = _referral_metrics(session, org_unit_id, now)
    triage_count = _triage_today_count(session, org_unit_id, day_start_naive, day_end_naive)
    synced_numerator, synced_denominator = _synced_metrics(
        session, org_unit_id, day_start_naive, day_end_naive, day_start_tz, day_end_tz,
    )

    response = {
        "facility": {"id": str(facility_id), "name": facility_name, "type": facility_type},
        "date": effective_date.isoformat(),
        "metrics": {
            "open_referrals": {"count": open_count},
            "triage_today": {"count": triage_count},
            "breached": {
                "numerator": breached_count, "denominator": open_count,
                "rate_pct": _rate_pct(breached_count, open_count),
            },
            "synced_today": {
                "numerator": synced_numerator, "denominator": synced_denominator,
                "rate_pct": _rate_pct(synced_numerator, synced_denominator),
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _cache.set(cache_key, response)
    return response
