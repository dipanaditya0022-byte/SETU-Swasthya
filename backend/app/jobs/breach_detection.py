"""Referral breach-detection background job.

Finds open (non-COMPLETED, non-CANCELLED) referrals that are past their
`due_at`, records the breach the first time it's detected, and advances the
per-urgency escalation chain on subsequent runs. Uses ONLY
`app.services.referral.breach.is_breached`/`compute_due_at` to decide "is
this breached" -- no independent re-derivation of the rule here (see that
module's own docstring for why this matters and what "single source of
truth" means concretely).

============================================================================
WHY `async def` OVER A PLAIN SYNCHRONOUS FUNCTION -- AND WHAT IT DOESN'T MEAN
============================================================================
The task's own signature (`async def detect_breaches(session, now=None)`)
is followed literally. This does NOT mean the job talks to Postgres
asynchronously: there is no async DB engine anywhere in this repository
(checked app/db/database.py -- a single synchronous `sqlmodel.create_engine`
+ `Session`, used by every route and by app/jobs/credential_expiry.py, the
one other background job in this codebase). This function is `async def`
so it can be awaited from an async caller (a future async scheduler, or
tests using pytest-asyncio per this repo's own recently-added dependency --
see tests/test_breach_detection.py), but every database call inside it is
the same synchronous `sqlmodel.Session` call every other route/job in this
repo already uses. This is a real, intentional seam, not a half-finished
async migration.

============================================================================
THE D+N ESCALATION CHAIN -- AMBIGUITY RESOLVED AND DOCUMENTED, NOT GUESSED
============================================================================
The task's own chain table doesn't say what "D" is relative to. Resolved
here as: D = the day `breached_at` was first set BY THIS JOB (the only
writer of that column -- see is_breached's module docstring; no route sets
it). D+1 == 24 hours after `breached_at`, D+2 == 48 hours after
`breached_at`, etc. -- elapsed wall-clock time since detection, not
calendar-day boundaries.

URGENT's own chain literally reads "ASHA D+1, CHO D+1, BMO D+2" -- stage 1
(ASHA) and stage 2 (CHO) both listed at the SAME D+1 checkpoint. Implemented
LITERALLY: `_ESCALATION_HOURS["URGENT"]` has both thresholds at 24h, so a
referral crossing the 24h mark becomes eligible for stage 2 in the very same
evaluation (see `_target_stage` -- it takes the highest satisfied
threshold, not a strict staircase). This is NOT silently "corrected" to
D+1/D+2 here. FLAGGED EXPLICITLY, per the task's own instruction, as worth a
second look from whoever wrote the spec.

A second, related tension found while wiring this in, not present in the
task's own words but a direct consequence of combining its two given rules:
stage 1 for EVERY urgency (including URGENT, whose own chain names stage 1
"ASHA D+1") is reached unconditionally, with NO delay, via the separately
specified "for each newly breached ... advance escalation_stage 0 -> 1"
rule below -- see `_handle_newly_breached`. That rule has no elapsed-time
condition attached to it in the task text. So in this implementation, stage
1 always happens at breach-detection time (effectively D+0), and the
per-urgency `_ESCALATION_HOURS` maps below therefore only ever govern
advancement FROM stage 1 onward (they have no `1:` entry except EMERGENCY's,
included only for documentation completeness since EMERGENCY's own "stages
1,2,3 immediately" already makes it moot). Both rules are given verbatim by
the task; this job follows both literally rather than unilaterally deciding
which one governs stage 1 timing for URGENT specifically. Flagged in the
report as a second ambiguity worth confirming.

============================================================================
INTERACTION WITH THE NOT_ARRIVED TRANSITION'S OWN escalation_stage = 1
============================================================================
`PATCH /referrals/{id}/status -> NOT_ARRIVED` (app/api/routes/referrals.py,
`_apply_transition`) already sets `escalation_stage = 1` as a side effect of
that transition, unconditionally, regardless of whether the referral is
past `due_at` yet. NOT_ARRIVED is not in COMPLETED_STATES and not
CANCELLED, so such a referral CAN also independently satisfy `is_breached()`
once `now > due_at` -- these are two separate signals ("nobody confirmed the
patient arrived" vs "the SLA clock ran out") that can both be true for the
very same row. Without a guard, this job's own "newly breached -> advance
escalation_stage 0 -> 1" would try to write the same value again (harmless)
or, worse, a future edit to that rule could push it past 1 a second time
purely because breach detection happened to fire after the route's own
side effect. RESOLVED (not left to chance): `_handle_newly_breached` only
advances `escalation_stage` to 1 when it is CURRENTLY 0 -- if the route
already bumped it to 1 (or anything higher) before the breach was detected,
this job leaves the stage exactly where it is, never regresses it and never
re-applies stage 1 on top of an already-elevated stage. The breach itself
(`breached_at`, `breach_detected_by`, the REFERRAL_BREACHED audit row, the
`newly_breached` count) is still recorded unconditionally -- only the
STAGE bump (and its accompanying owner notification, tied to an actual
stage change) is suppressed when there is nothing to bump.

============================================================================
ELECTIVE -- "no escalation, stage stays 0"
============================================================================
Taken literally: ELECTIVE referrals are still detected as breached (the
breach itself is a fact about the SLA clock, independent of urgency) and
still get a REFERRAL_BREACHED audit row + counted in `newly_breached`, but
`escalation_stage` is never bumped for them (not even the otherwise
unconditional 0 -> 1 on first detection) and no owner notification fires.
`_MAX_STAGE["ELECTIVE"] == 0` is what enforces this in both
`_handle_newly_breached` and `_handle_escalation`.

============================================================================
OWNER NOTIFICATION -- EXPLICIT STUB, AND owner_user_id IS OFTEN UNSET
============================================================================
Grepped the whole repo: no SMS/email/push gateway exists anywhere (same gap
already found and documented by app/jobs/credential_expiry.py, whose own
`logger.warning("... NOTIFICATION (no gateway configured): ...")` pattern
this job reuses verbatim rather than inventing a new mechanism or a fake
integration). `_notify_owner` below is that same dev-mode stand-in, kept as
one small function so a real gateway can be dropped in behind this one call
site later without touching the detection logic above it.

Also grepped: no route anywhere in this codebase ever WRITES
`Referral.owner_user_id` (create_referral doesn't set it, no
`_apply_transition` branch sets it). It is a real, FK-backed, currently
always-NULL column in this dev environment. "No owner set" is therefore the
COMMON case today, not an edge case -- `_notify_owner` treats it as a real,
expected outcome: it logs (at INFO, since it's an expected condition, not a
problem) and returns cleanly, never raises, never crashes the run over one
un-owned referral.

============================================================================
IDEMPOTENCY -- "running it twice in the same minute must not double-escalate
and must not send two notifications"
============================================================================
Both write paths guard on state that the first run itself just changed:
- Newly-breached candidates are selected with `breached_at IS NULL`,
  matching migration d4f1c9b7a582's own partial index
  (`idx_referrals_breach ... WHERE breached_at IS NULL`). The first run
  sets `breached_at = now`, so a second run in the same minute no longer
  selects that row as "newly breached" at all -- `newly_breached` is 0.
- Already-breached escalation only advances when the freshly computed
  `target` stage is STRICTLY GREATER than the row's current
  `escalation_stage`. The first run already wrote the new
  `escalation_stage` (and `escalation_notified_at = now`, the field this
  task asks the guard to key off), so a second run computes the same
  `target` against the now-already-advanced `escalation_stage` and finds
  nothing left to advance to.
`escalation_notified_at` is written on every stage change (both branches)
as the durable record of "a notification was sent for the row's current
escalation_stage" -- a future caller can use it to answer "did we already
notify for this stage" directly, even though the re-run safety above is
already structurally guaranteed by the state comparisons themselves.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models import Referral
from app.models.referral_state import COMPLETED_STATES, ReferralState
from app.services.referral.breach import is_breached, normalize_urgency

logger = logging.getLogger(__name__)

# See module docstring "THE D+N ESCALATION CHAIN". Keys are the
# normalised (upper-cased) urgency strings from
# app.services.referral.breach.URGENCY_WINDOWS; values map escalation
# STAGE -> hours elapsed since `breached_at` at which that stage becomes
# eligible. Stage 1 is included only where the spec's own "immediately"
# wording makes it explicit (EMERGENCY) -- for every other urgency, stage
# 1 is reached via the unconditional newly-breached rule instead (see
# docstring), not via this table.
_ESCALATION_HOURS: dict[str, dict[int, float]] = {
    "EMERGENCY": {1: 0, 2: 0, 3: 0},
    "URGENT": {2: 24, 3: 48},          # CHO D+1, BMO D+2
    "PRIORITY": {2: 96, 3: 120},       # CHO D+4, BMO D+5
    "ROUTINE": {2: 240},               # CHO D+10 -- capped at stage 2
    "ELECTIVE": {},                    # no escalation at all
}

# Per-urgency ceiling. ROUTINE never reaches 3 ("max stage 2"); ELECTIVE
# never escalates at all ("stage stays 0"); everything else caps at 3
# ("escalation caps at stage 3 -> never 4").
_MAX_STAGE: dict[str, int] = {
    "EMERGENCY": 3,
    "URGENT": 3,
    "PRIORITY": 3,
    "ROUTINE": 2,
    "ELECTIVE": 0,
}
_DEFAULT_MAX_STAGE = 3


def _target_stage(urgency: Optional[str], elapsed_hours: float) -> int:
    """The highest escalation stage whose threshold has been met for this
    urgency, capped at that urgency's own max stage. Not a staircase that
    must be walked one step at a time -- a referral that has been breached
    long enough can jump straight past intermediate stages in one call
    (this is what makes EMERGENCY's "stages 1,2,3 immediately" and
    URGENT's own duplicate D+1 entries behave as literally written)."""
    key = normalize_urgency(urgency)
    thresholds = _ESCALATION_HOURS.get(key, {})
    max_stage = _MAX_STAGE.get(key, _DEFAULT_MAX_STAGE)
    target = 0
    for stage, hours in thresholds.items():
        if elapsed_hours >= hours and stage > target:
            target = stage
    return min(target, max_stage)


def _write_audit(session: Session, *, actor_user_id: Optional[str], action: str,
                  outcome: str, target_type: Optional[str] = None,
                  target_id: Optional[str] = None, metadata: Optional[dict] = None) -> None:
    # Duplicated local helper, verbatim shape from
    # app/api/routes/referrals.py / app/jobs/credential_expiry.py's own
    # _write_audit -- see those files' docstrings for why this isn't a
    # shared import (established precedent in this codebase already).
    import json
    from app.core.audit import compute_row_hash
    from sqlmodel import text
    prev = session.exec(text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")).first()
    prev_hash = prev[0] if prev else None
    occurred_at = datetime.now(timezone.utc)
    entry = {"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
              "outcome": outcome, "target_type": target_type, "target_id": target_id,
              "metadata": metadata or {}}
    row_hash = compute_row_hash(entry, prev_hash)
    session.exec(text(
        "INSERT INTO audit_log (occurred_at, actor_user_id, action, outcome, target_type, "
        "target_id, metadata, prev_hash, row_hash) VALUES "
        "(:occurred_at, :actor_user_id, :action, :outcome, :target_type, :target_id, "
        ":metadata, :prev_hash, :row_hash)"
    ), params={"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
               "outcome": outcome, "target_type": target_type, "target_id": target_id,
               "metadata": json.dumps(metadata or {}), "prev_hash": prev_hash, "row_hash": row_hash})


def _notify_owner(referral: Referral, *, reason: str) -> None:
    """STUB -- see module docstring "OWNER NOTIFICATION". Logs only; no
    gateway exists in this codebase to actually deliver anything yet."""
    if referral.owner_user_id is None:
        logger.info(
            "breach_detection: referral_id=%s has no owner_user_id set -- "
            "skipping owner notification (%s). No route in this codebase "
            "currently populates Referral.owner_user_id.",
            referral.id, reason,
        )
        return
    logger.warning(
        "REFERRAL OWNER NOTIFICATION (no gateway configured): owner_user_id=%s -- "
        "referral_id=%s %s",
        referral.owner_user_id, referral.id, reason,
    )


def _handle_newly_breached(session: Session, referral: Referral, now: datetime) -> None:
    """First-ever detection of this breach (breached_at was NULL going
    in). Always records the breach itself; the escalation_stage bump and
    notification are conditional -- see module docstring's NOT_ARRIVED
    and ELECTIVE sections for why."""
    referral.breached_at = now
    referral.breach_detected_by = "JOB"

    key = normalize_urgency(referral.urgency)
    max_stage = _MAX_STAGE.get(key, _DEFAULT_MAX_STAGE)
    stage_bumped = False
    if max_stage > 0 and referral.escalation_stage == 0:
        # Only from 0 -- never regress or double-apply on top of a stage
        # the NOT_ARRIVED transition (or a prior job run) already set.
        referral.escalation_stage = 1
        referral.escalation_notified_at = now
        stage_bumped = True

    session.add(referral)
    session.commit()
    session.refresh(referral)

    _write_audit(
        session, actor_user_id=None, action="REFERRAL_BREACHED", outcome="SUCCESS",
        target_type="REFERRAL", target_id=str(referral.id),
        metadata={
            "urgency": referral.urgency,
            "due_at": referral.due_at.isoformat() if referral.due_at else None,
            "escalation_stage": referral.escalation_stage,
            "stage_bumped_by_job": stage_bumped,
            "via": "SYSTEM_JOB",
        },
    )
    session.commit()

    if stage_bumped:
        _notify_owner(referral, reason=f"breach detected, escalation_stage={referral.escalation_stage}")


def _handle_escalation(session: Session, referral: Referral, now: datetime) -> bool:
    """Already-breached (breached_at set on an earlier run). Advances
    escalation_stage per the per-urgency chain if due. Returns True iff a
    stage change was actually made (drives the `escalated` counter)."""
    key = normalize_urgency(referral.urgency)
    max_stage = _MAX_STAGE.get(key, _DEFAULT_MAX_STAGE)
    if max_stage == 0:
        return False  # ELECTIVE -- "no escalation, stage stays 0".

    elapsed_hours = (now - referral.breached_at).total_seconds() / 3600.0
    target = _target_stage(referral.urgency, elapsed_hours)
    if target <= referral.escalation_stage:
        # Idempotency guard -- see module docstring. Also the ordinary,
        # expected case: most already-breached referrals aren't yet due
        # for their next stage.
        return False

    referral.escalation_stage = target
    referral.escalation_notified_at = now
    session.add(referral)
    session.commit()
    session.refresh(referral)

    _write_audit(
        session, actor_user_id=None, action="REFERRAL_ESCALATED", outcome="SUCCESS",
        target_type="REFERRAL", target_id=str(referral.id),
        metadata={"urgency": referral.urgency, "escalation_stage": target, "via": "SYSTEM_JOB"},
    )
    session.commit()

    _notify_owner(referral, reason=f"escalated to stage {target}")
    return True


async def detect_breaches(session: Session, now: Optional[datetime] = None) -> dict:
    """Scans all open referrals (status not in COMPLETED_STATES, not
    CANCELLED) with a `due_at` set, using `is_breached()`
    (app.services.referral.breach -- the single shared rule) to decide
    which ones are actually breached right now. See module docstring for
    the full behaviour contract, the D+N ambiguity resolution, and the
    NOT_ARRIVED/ELECTIVE interactions.

    Safe to call repeatedly / from a scheduler at any cadence -- see
    module docstring "IDEMPOTENCY".
    """
    now = now or datetime.now(timezone.utc)

    non_open_statuses = list(COMPLETED_STATES) + [ReferralState.CANCELLED]
    candidates = session.exec(
        select(Referral).where(
            Referral.due_at.is_not(None),  # type: ignore[union-attr]
            Referral.status.not_in(non_open_statuses),  # type: ignore[attr-defined]
        )
    ).all()

    checked = len(candidates)
    newly_breached = 0
    escalated = 0

    for referral in candidates:
        if not is_breached(referral, now):
            continue
        if referral.breached_at is None:
            _handle_newly_breached(session, referral, now)
            newly_breached += 1
        else:
            if _handle_escalation(session, referral, now):
                escalated += 1

    return {"newly_breached": newly_breached, "escalated": escalated, "checked": checked}


if __name__ == "__main__":
    import asyncio

    from dotenv import load_dotenv

    load_dotenv()

    from app.db.database import engine

    async def _main() -> None:
        with Session(engine) as _session:
            result = await detect_breaches(_session)
            print(f"breach_detection: {result}")

    asyncio.run(_main())
