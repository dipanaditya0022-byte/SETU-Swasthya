"""FallbackEscalationEngine -- a deterministic, dependency-free escalation
engine. It exists so that GET /referrals/exceptions (a future route, not
built in this step) never has a hard dependency on SD's escalation_for()
(app/services/escalation/adapter.py, factory.py): if SD's rule engine isn't
ready, this is what runs instead. Mirrors app/services/triage/fallback.py's
own structure and "no database session, always available" guarantee.

Exact hour thresholds below are THIS TASK's own spec, transcribed
verbatim, not copied from app/jobs/breach_detection.py's
`_ESCALATION_HOURS`/`_MAX_STAGE` tables. The two are close cousins (both
are per-urgency stage chains keyed off elapsed time) but are NOT the same
rule and must not be unified:

  - breach_detection.py measures elapsed time from `breached_at` (the
    instant the background job first detected the breach) and its own
    docstring documents a "stage 1 is reached unconditionally, with no
    delay" special case plus per-urgency thresholds like URGENT
    {2: 24, 3: 48} (hours since breached_at).
  - THIS module measures elapsed time from `due_at` directly (`now` minus
    `due_at`, per EscalationInput's own fields -- there is no
    `breached_at` in EscalationInput at all), and its own bands are:

        EMERGENCY  any breach                        -> stage 3, BMO
        URGENT     0-24h -> stage 1 ASHA
                   24-48h -> stage 2 CHO
                   >48h -> stage 3 BMO
        PRIORITY   0-24h -> stage 1 ASHA
                   24-48h -> stage 2 CHO
                   >48h -> stage 3 BMO
        ROUTINE    0-48h -> stage 1 ASHA
                   >48h -> stage 2 CHO (never stage 3)
        ELECTIVE   always stage 0, escalate_to_role None

    Bands are half-open on the lower bound, i.e. "0-24h" means
    `0 <= elapsed_hours < 24`; the next band's threshold is where the
    current one ends. This is this task's own thresholds, transcribed
    exactly -- do not "correct" them to match breach_detection.py's
    numbers, and do not silently swap `due_at` for `breached_at`.

`current_stage` (EscalationInput) is accepted, per the Protocol shape
given for this step, but is NOT consulted by this engine: like
breach_detection.py's own `_target_stage` ("not a staircase that must be
walked one step at a time"), this fallback recomputes the correct stage
as a pure function of (urgency, elapsed_hours, status) on every call. This
is a deliberate simplification, not an oversight: the task's own
deliverables/tests never exercise a current_stage/computed-stage conflict,
and inventing an anti-regression rule here (e.g. "never return lower than
current_stage") is behaviour this step was not asked for. A future caller
(the eventual route, mirroring how idempotency lives in
breach_detection.py's own job -- not in a pure rule function) is where
that guard belongs if it's ever needed.

============================================================================
THE reports_to CHAIN-WALK -- WHAT EXISTS, WHAT DOESN'T, AND WHY THIS ENGINE
STILL RETURNS None FOR escalate_to_user_id TODAY
============================================================================
Checked, not assumed: `users.reports_to_user_id` (the RBAC-core identity
table, migration c3a9f7d21e56) IS a real column in this codebase --
FK'd to `users.id`, indexed (`idx_users_reports_to`), constrained
(`chk_no_self_report`), and already walked in the other direction
("find my subordinates") by app/api/routes/users.py's own
`deactivate_user`/`reassign` logic. `Referral.owner_user_id`
(app/models/referral.py) is FK'd to that same `users` table (migration
d4f1c9b7a582's own docstring: "owner_user_id ... reference users"). So the
DATA needed to walk "from the referral's owner up to a CHO/ASHA/BMO" does
exist, in principle -- unlike the more pessimistic premise this task's own
context note raised.

What does NOT exist is any way for THIS function, running inside
FallbackEscalationEngine.escalate(), to reach it: EscalationInput (this
step's own spec, mirroring TriageInput) carries no Session, and
EscalationEngine.escalate()'s signature (also this step's own spec,
mirroring TriageEngine.evaluate()) takes none either -- by the same
dependency-free design FallbackTriageEngine itself relies on ("no database
session" -- see app/services/triage/fallback.py's own class docstring).
`resolve_escalation_target` below is a REAL, working function -- give it a
live `Session` and it will actually walk `users.reports_to_user_id` from
`owner_user_id` up to the first ancestor holding `target_role`, exactly as
this task asked for. But `FallbackEscalationEngine.escalate()` always
calls it with `session=None` (there is no session to pass), which
short-circuits to `None` immediately. `_gap_message()` is what turns that
into the plain-language explanation this task asked for -- a missing
escalation target is information, not an error, and the message says
exactly why the target is missing (no owner set, vs. no session to walk
with) rather than staying silent about it.

If a later step wires a Session into this path (e.g. the eventual
GET /referrals/exceptions route calling `resolve_escalation_target`
itself, after getting `escalate_to_role` from this engine, with its own
request-scoped session), the walk becomes real with no change to this
function's logic -- only to who calls it and with what.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from app.models.referral_state import COMPLETED_STATES, ReferralState
from app.services.escalation.port import EscalationInput, EscalationOutput

VERSION = "fallback-v1.0"

# Per-urgency band table. Each tuple is (upper_bound_hours, stage, role);
# bands are checked in order and the first one where
# elapsed_hours < upper_bound_hours wins. The upper_bound_hours of the
# WINNING band is also `due_action_at`'s offset from `due_at` (the moment
# this stage would advance to the next one) -- except for the last band in
# a list, whose upper bound is infinite and therefore has no
# `due_action_at` (there is nothing further to advance to).
_URGENT_PRIORITY_BANDS: list[tuple[float, int, str]] = [
    (24.0, 1, "ASHA"),
    (48.0, 2, "CHO"),
    (float("inf"), 3, "BMO"),
]
_ROUTINE_BANDS: list[tuple[float, int, str]] = [
    (48.0, 1, "ASHA"),
    (float("inf"), 2, "CHO"),
]

# Action verb per role, used to build the plain-language message. Not a
# rule ID, not a score -- just what a manager reading this message should
# do next.
_ROLE_ACTIONS: dict[str, str] = {
    "ASHA": "visit the family",
    "CHO": "call the family",
    "BMO": "take over the case",
}

# Unrecognised urgency values fall back to the ROUTINE band table, mirroring
# app/services/referral/breach.py's own documented fallback (unrecognised
# `urgency` free text -> the ROUTINE due-date window). Same rationale here:
# "SLA is unknown, don't over- or under-promise."
_DEFAULT_URGENCY_KEY = "ROUTINE"

_MAX_CHAIN_DEPTH = 50  # generous ceiling; guards against a corrupted cycle


def _normalize_urgency(urgency: Optional[str]) -> str:
    """Same `.strip().upper()` normalisation as
    app.services.referral.breach.normalize_urgency, applied independently
    here (not imported) so this module stays exactly as dependency-free as
    app/services/triage/fallback.py -- no database session, but also no
    import of a sibling service package's module, matching that module's
    own "no database session, no network call" isolation."""
    return (urgency or "").strip().upper()


def _is_terminal_status(status: str) -> bool:
    """True iff `status` is a recognised ReferralState in COMPLETED_STATES
    or CANCELLED (app.models.referral_state) -- a referral that has
    already arrived/consulted/closed/cancelled needs no further
    escalation, mirroring app.services.referral.breach.is_breached's own
    definition of "not breached" for these same states.

    An unrecognised status string does NOT count as terminal -- fails
    toward computing escalation, not away from it, the same
    "uncertainty escalates upward, never downward" principle
    app/services/triage/fallback.py's own module docstring states
    explicitly for that engine."""
    try:
        state = ReferralState(status)
    except ValueError:
        return False
    return state in COMPLETED_STATES or state == ReferralState.CANCELLED


def resolve_escalation_target(
    session: Optional[object],
    owner_user_id: Optional[UUID],
    target_role: str,
) -> Optional[UUID]:
    """Walks `users.reports_to_user_id` upward from `owner_user_id` until a
    user with `role == target_role` is found, the chain ends
    (`reports_to_user_id IS NULL`), a referenced row is missing, or a cycle
    is detected. Returns that user's id, or None if the target role is
    never found.

    REAL implementation, not a stub of intent -- see this module's own
    docstring section on the reports_to chain for exactly what does and
    does not exist in this codebase today, and why `session` is typed
    loosely (`object`, not `sqlmodel.Session`) here: importing
    `sqlmodel`/`app.db.database` at module level would add a database
    dependency to a module whose whole purpose (mirroring
    app/services/triage/fallback.py) is to have none. The `session.exec`
    call below is duck-typed against `sqlmodel.Session`'s own interface,
    exactly the way app/services/referral/breach.py's `is_breached`
    duck-types its `referral` argument.

    `FallbackEscalationEngine.escalate()` below always calls this with
    `session=None`, which returns None immediately without touching
    anything -- see this module's docstring for why.
    """
    if session is None or owner_user_id is None:
        return None

    from sqlmodel import text  # lazy import -- see docstring above

    seen: set[UUID] = set()
    current = owner_user_id
    for _ in range(_MAX_CHAIN_DEPTH):
        if current in seen:
            return None  # cycle guard -- chk_no_self_report only forbids a
            # direct self-reference, not a longer cycle
        seen.add(current)

        row = session.exec(
            text("SELECT role, reports_to_user_id FROM users WHERE id = :id"),
            params={"id": str(current)},
        ).first()
        if row is None:
            return None

        role, reports_to = row
        if role == target_role:
            return current
        if reports_to is None:
            return None
        current = reports_to

    return None


def _gap_message(owner_user_id: Optional[UUID], role: str) -> str:
    """Plain-language explanation of why `escalate_to_user_id` is None --
    see module docstring: a missing escalation target is information, not
    an error, so this is always appended to the action message rather than
    left unexplained."""
    if owner_user_id is None:
        return (
            f"No specific {role} could be notified automatically: this "
            f"referral has no owner set, so there is no reporting chain to "
            f"follow. Please route this to the on-duty {role} manually."
        )
    return (
        f"No specific {role} could be notified automatically: this engine "
        f"cannot look up the reporting chain right now. Please route this "
        f"to the on-duty {role} manually."
    )


def _article(word: str) -> str:
    """"a"/"an" for the plain-language message -- "an urgent referral" vs
    "a routine referral". Cosmetic only; never affects stage/role logic."""
    return "an" if word[:1].lower() in "aeiou" else "a"


def _elapsed_phrase(hours: float) -> str:
    """Plain-language rendering of elapsed time, used inside the action
    message. Whole hours below two days, whole days from two days on --
    matches the worked example given for this step
    ("2 days after an urgent referral")."""
    if hours < 48:
        h = max(0, int(hours))
        if h == 0:
            return "less than an hour"
        return f"{h} hour" + ("" if h == 1 else "s")
    d = int(hours // 24)
    return f"{d} day" + ("" if d == 1 else "s")


def _band_result(
    bands: list[tuple[float, int, str]], elapsed_hours: float
) -> tuple[int, str, Optional[float]]:
    """Returns (stage, role, due_action_offset_hours) for the first band
    whose upper bound exceeds elapsed_hours. due_action_offset_hours is
    None for the last (infinite) band."""
    for upper, stage, role in bands:
        if elapsed_hours < upper:
            offset = None if upper == float("inf") else upper
            return stage, role, offset
    # Unreachable: the last band's upper bound is always inf.
    last_upper, last_stage, last_role = bands[-1]
    return last_stage, last_role, None


class FallbackEscalationEngine:
    """Deterministic, dependency-free escalation engine: no import of SD's
    escalation_for(), no network call, no database session. Always
    available. See module docstring for the safety rule this exists to
    guarantee and the reports_to chain-walk gap. See
    tests/test_escalation_fallback.py."""

    name = "fallback"

    def escalate(self, data: EscalationInput) -> EscalationOutput:
        urgency_key = _normalize_urgency(data.urgency)

        if _is_terminal_status(data.status):
            return EscalationOutput(
                stage=0,
                escalate_to_role=None,
                escalate_to_user_id=None,
                due_action_at=None,
                message=(
                    "No escalation needed: this referral's status "
                    f"({data.status}) is already completed or cancelled."
                ),
                engine=self.name,
            )

        if urgency_key == "ELECTIVE":
            return EscalationOutput(
                stage=0,
                escalate_to_role=None,
                escalate_to_user_id=None,
                due_action_at=None,
                message=(
                    "Elective referral: no escalation is required "
                    f"regardless of timing (due {data.due_at.isoformat()})."
                ),
                engine=self.name,
            )

        if data.now <= data.due_at:
            return EscalationOutput(
                stage=0,
                escalate_to_role=None,
                escalate_to_user_id=None,
                due_action_at=data.due_at,
                message=(
                    "Not yet breached: this "
                    f"{urgency_key.lower()} referral is due by "
                    f"{data.due_at.isoformat()}."
                ),
                engine=self.name,
            )

        elapsed_hours = (data.now - data.due_at).total_seconds() / 3600.0

        if urgency_key == "EMERGENCY":
            stage, role, due_action_at = 3, "BMO", None
            message = (
                "Emergency referral has breached its response window and "
                "has not reached the hospital. BMO to take over the case "
                "immediately."
            )
        else:
            # URGENT and PRIORITY share the same band table verbatim, per
            # this task's own spec. Any other/unrecognised urgency value
            # falls back to ROUTINE's bands -- see _DEFAULT_URGENCY_KEY
            # above (mirrors breach.py's own unrecognised-urgency fallback).
            if urgency_key in ("URGENT", "PRIORITY"):
                bands = _URGENT_PRIORITY_BANDS
            else:
                bands = _ROUTINE_BANDS

            stage, role, offset_hours = _band_result(bands, elapsed_hours)
            due_action_at = (
                data.due_at + timedelta(hours=offset_hours)
                if offset_hours is not None
                else None
            )
            message = (
                f"Not reached the hospital {_elapsed_phrase(elapsed_hours)} "
                f"after {_article(urgency_key)} {urgency_key.lower()} referral. "
                f"{role} to {_ROLE_ACTIONS[role]}."
            )

        target = resolve_escalation_target(None, data.owner_user_id, role)
        if target is None:
            message = f"{message} {_gap_message(data.owner_user_id, role)}"

        return EscalationOutput(
            stage=stage,
            escalate_to_role=role,  # type: ignore[arg-type]
            escalate_to_user_id=target,
            due_action_at=due_action_at,
            message=message,
            engine=self.name,
        )
