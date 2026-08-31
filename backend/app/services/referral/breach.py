"""Referral breach rule -- THE single source of truth for "is this referral
overdue" and "when is it due".

WHY THIS MODULE EXISTS: `due_at` was previously computed in exactly one
place (app/api/routes/referrals.py's RESCHEDULED branch, a hardcoded
`now + timedelta(days=7)`) and breach status was never computed anywhere at
all -- app/api/routes/referrals.py's own ARRIVED-transition comment
explicitly deferred it to "an external breach-detection job" that did not
yet exist. This module IS that shared rule. Both the read path (any future
"is this referral breached right now" check -- a dashboard, a GET response,
a filter) and the background job (app/jobs/breach_detection.py) call
`compute_due_at`/`is_breached` from here. No route or job may independently
recompute a due-date window or re-derive breach status with its own logic --
see app/api/routes/referrals.py's RESCHEDULED branch and
app/jobs/breach_detection.py, both of which now call into this module
instead of hand-rolling the calculation.

============================================================================
URGENCY CASING/VOCABULARY -- READ BEFORE CHANGING URGENCY_WINDOWS
============================================================================
`referral.urgency` is `TEXT NOT NULL`, client-supplied on `POST /referrals/`
(the whole `Referral` SQLModel is the request body there -- see
app/api/routes/referrals.py), with NO enum type and NO CHECK constraint
anywhere in the schema (verified directly against migration
79a9d8f8db61 -- the column that created it -- and d4f1c9b7a582 -- the most
recent migration to touch `referral`, which explicitly declined to touch
`urgency` at all; see that migration's own docstring). There is therefore no
DB-level guarantee about what strings actually land in this column.

Checked what's actually written today: tests/test_existing_endpoints.py's
own fixture POSTs `"urgency": "routine"` -- lowercase free text, not one of
this module's spec'd UPPERCASE keys (EMERGENCY/URGENT/PRIORITY/ROUTINE/
ELECTIVE). This is a genuine casing mismatch between the spec that produced
URGENCY_WINDOWS and the live data shape, found here and NOT silently
papered over:

  RESOLUTION (explicit, not a silent assumption): `compute_due_at`
  normalises by `.strip().upper()` before the URGENCY_WINDOWS lookup, so
  "routine", "Routine", " ROUTINE " and "ROUTINE" all resolve to the same
  window. This covers the casing half of the mismatch.

  The VOCABULARY half remains open: because there is no CHECK constraint,
  a client can send `urgency` values that are not any casing of the five
  known words at all (e.g. "asap", "whenever", empty string, or garbage).
  For any such unrecognised value, `compute_due_at` falls back to the
  ROUTINE window (7 days) rather than raising or defaulting to the
  shortest/most-urgent window -- ROUTINE is the same window the
  pre-existing RESCHEDULED-branch hardcode already used unconditionally
  for every referral regardless of urgency, so this fallback is a
  behavioural no-op for every case that hardcode already handled, and a
  defensible "SLA is unknown, don't over- or under-promise" default for
  the genuinely-new "unrecognised free text" case.

  FLAGGED FOR THE HUMAN, NOT DECIDED HERE: `referral.urgency` should
  probably become a real enum/CHECK constraint (mirroring what
  d4f1c9b7a582 already did for `referral.status`) so this fallback path
  stops being reachable in practice. That is a migration, and this task
  is explicitly "one concern per change" / migrations are out of scope
  for this step -- not added here.
============================================================================
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.referral_state import COMPLETED_STATES, ReferralState

# Spec'd verbatim, UPPERCASE keys. See module docstring for the
# casing/vocabulary normalisation strategy applied before lookup.
URGENCY_WINDOWS: dict[str, timedelta] = {
    "EMERGENCY": timedelta(hours=1),
    "URGENT": timedelta(hours=24),
    "PRIORITY": timedelta(hours=72),
    "ROUTINE": timedelta(days=7),
    "ELECTIVE": timedelta(days=30),
}

# Fallback window for urgency values that don't match any known key even
# after normalisation -- see module docstring's "VOCABULARY half" note.
_DEFAULT_WINDOW_KEY = "ROUTINE"


def normalize_urgency(urgency: Optional[str]) -> str:
    """`.strip().upper()` normalisation, applied consistently everywhere
    urgency needs to be compared against URGENCY_WINDOWS' keys (this
    module, and app/jobs/breach_detection.py's own escalation-chain
    lookup -- see that module for why it needs the same normalised key)."""
    return (urgency or "").strip().upper()


def compute_due_at(initiated_at: datetime, urgency: Optional[str]) -> datetime:
    """The single place `due_at` is ever computed, from `initiated_at` plus
    the urgency-keyed SLA window. Called at referral creation (`due_at =
    compute_due_at(initiated_at, urgency)`) and again on a RESCHEDULED
    transition (`due_at = compute_due_at(now, urgency)`, restarting the
    clock from the reschedule instant -- see this module's own docstring
    and app/api/routes/referrals.py's RESCHEDULED branch)."""
    key = normalize_urgency(urgency)
    window = URGENCY_WINDOWS.get(key, URGENCY_WINDOWS[_DEFAULT_WINDOW_KEY])
    return initiated_at + window


def is_breached(referral, now: Optional[datetime] = None) -> bool:
    """THE DEFINITION: a referral is breached when `now` is past its
    `due_at` AND its status is not in COMPLETED_STATES and not CANCELLED.
    A referral with no `due_at` set (should not happen for any row created
    or rescheduled after this step, but a defensive/fail-closed read for
    older data) is never considered breached -- there is nothing to be
    "past".

    `referral` is duck-typed (`.status`, `.due_at`) so this works against
    both a real `app.models.referral.Referral` ORM instance and any
    lightweight stand-in a test wants to pass."""
    now = now or datetime.now(timezone.utc)

    status = referral.status
    if not isinstance(status, ReferralState):
        status = ReferralState(status)

    if status in COMPLETED_STATES:
        return False
    if status == ReferralState.CANCELLED:
        return False
    if referral.due_at is None:
        return False
    return now > referral.due_at
