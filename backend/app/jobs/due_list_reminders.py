"""Scheduled job for generating referral due-list reminders.

Identifies open referrals requiring operational follow-up:
1. Upcoming referrals approaching their SLA window (within lookahead_hours).
2. Breached/overdue referrals requiring active escalation follow-up.

Consumes the pure SD escalation rule engine (ml.escalation.rules.escalation_for
-- moved from backend/app/services/escalation/ as part of the ml/
integration, see ml/README.md) to annotate overdue reminders with
deterministic escalation stages and roles.

Standalone CLI-runnable module matching existing jobs (breach_detection, credential_expiry).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models.referral import Referral
from app.models.referral_state import COMPLETED_STATES, ReferralState
from app.services.referral.breach import is_breached, normalize_urgency
from ml.escalation.rules import escalation_for

logger = logging.getLogger(__name__)


def _notify_reminder(reminder: dict) -> None:
    """Log plain-language reminder notification (dev-mode standard stub)."""
    logger.warning(
        "DUE-LIST REMINDER (no gateway configured): type=%s urgency=%s referral_id=%s owner_user_id=%s -- %s",
        reminder.get("type"),
        reminder.get("urgency"),
        reminder.get("referral_id"),
        reminder.get("owner_user_id"),
        reminder.get("message"),
    )


def generate_due_list_reminders(
    session: Session,
    now: Optional[datetime] = None,
    lookahead_hours: float = 24.0,
) -> dict:
    """Scan open referrals and generate action-oriented due-list reminders.

    Args:
        session: Active database session.
        now: Evaluation timestamp (defaults to current UTC time).
        lookahead_hours: Forward window in hours for upcoming due referrals.

    Returns:
        Summary dict containing counts and ordered reminder items.
    """
    now = now or datetime.now(timezone.utc)

    # Exclude terminal/completed states: ARRIVED, CONSULTED, BACK_REFERRED, CLOSED, CANCELLED
    non_open_statuses = list(COMPLETED_STATES) + [ReferralState.CANCELLED]

    candidates = session.exec(
        select(Referral).where(
            Referral.due_at.is_not(None),  # type: ignore[union-attr]
            Referral.status.not_in(non_open_statuses),  # type: ignore[attr-defined]
        )
    ).all()

    overdue_reminders: list[dict] = []
    upcoming_reminders: list[dict] = []

    for referral in candidates:
        if referral.due_at is None:
            continue

        due_at = referral.due_at
        # Align timezones if mixed aware/naive
        if due_at.tzinfo is None and now.tzinfo is not None:
            due_at = due_at.replace(tzinfo=now.tzinfo)
        elif due_at.tzinfo is not None and now.tzinfo is None:
            due_at = due_at.replace(tzinfo=None)
        referral.due_at = due_at

        status_val = (
            referral.status.value
            if hasattr(referral.status, "value")
            else str(referral.status)
        )

        if is_breached(referral, now):
            # Case 1: Overdue referral - compute escalation details via SD rule engine
            esc_payload = {
                "urgency": referral.urgency,
                "initiated_at": referral.initiated_at,
                "due_at": due_at,
                "now": now,
                "current_stage": referral.escalation_stage,
                "owner_user_id": referral.owner_user_id,
                "status": status_val,
            }
            esc_out = escalation_for(esc_payload)
            elapsed_hours = (now - due_at).total_seconds() / 3600.0

            reminder = {
                "referral_id": str(referral.id),
                "patient_id": str(referral.patient_id),
                "type": "OVERDUE",
                "urgency": referral.urgency,
                "status": status_val,
                "due_at": due_at.isoformat(),
                "overdue_hours": round(elapsed_hours, 2),
                "escalation_stage": esc_out["stage"],
                "escalate_to_role": esc_out.get("escalate_to_role"),
                "due_action_at": (
                    esc_out["due_action_at"].isoformat()
                    if esc_out.get("due_action_at")
                    else None
                ),
                "owner_user_id": (
                    str(referral.owner_user_id) if referral.owner_user_id else None
                ),
                "message": esc_out["message"],
            }
            _notify_reminder(reminder)
            overdue_reminders.append(reminder)

        elif now <= due_at <= now + timedelta(hours=lookahead_hours):
            # Case 2: Upcoming referral within lookahead window
            hours_until_due = (due_at - now).total_seconds() / 3600.0
            urgency_norm = normalize_urgency(referral.urgency)
            urgency_label = urgency_norm.capitalize() if urgency_norm else "Routine"

            reminder = {
                "referral_id": str(referral.id),
                "patient_id": str(referral.patient_id),
                "type": "UPCOMING",
                "urgency": referral.urgency,
                "status": status_val,
                "due_at": due_at.isoformat(),
                "hours_until_due": round(hours_until_due, 2),
                "escalation_stage": 0,
                "escalate_to_role": None,
                "due_action_at": due_at.isoformat(),
                "owner_user_id": (
                    str(referral.owner_user_id) if referral.owner_user_id else None
                ),
                "message": (
                    f"Upcoming {urgency_label.lower()} referral due in {round(hours_until_due, 1)} hour(s). "
                    "Please confirm patient travel arrangements."
                ),
            }
            _notify_reminder(reminder)
            upcoming_reminders.append(reminder)

    # Sort exception-first: Overdue EMERGENCY first, then overdue_hours desc, then upcoming hours_until_due asc
    def _sort_key(item: dict) -> tuple:
        is_overdue = 0 if item["type"] == "OVERDUE" else 1
        is_emergency = 0 if normalize_urgency(item.get("urgency")) == "EMERGENCY" else 1
        neg_overdue = -item.get("overdue_hours", 0.0)
        hours_until = item.get("hours_until_due", 0.0)
        return (is_overdue, is_emergency, neg_overdue, hours_until)

    sorted_reminders = sorted(overdue_reminders + upcoming_reminders, key=_sort_key)

    return {
        "total_checked": len(candidates),
        "overdue_count": len(overdue_reminders),
        "upcoming_count": len(upcoming_reminders),
        "total_reminders": len(sorted_reminders),
        "reminders": sorted_reminders,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from app.db.database import engine

    with Session(engine) as _session:
        res = generate_due_list_reminders(_session)
        print(
            f"due_list_reminders: generated {res['total_reminders']} reminder(s) "
            f"({res['overdue_count']} overdue, {res['upcoming_count']} upcoming, "
            f"checked {res['total_checked']})"
        )
