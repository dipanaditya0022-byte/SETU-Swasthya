"""Deterministic escalation rule engine for SETU-Swasthya referrals.

Evaluates referral SLA breach status and maps elapsed overdue time to
deterministic escalation stages (0..3), supervisor action roles
(ASHA, CHO, BMO), and actionable plain-language next steps.

Pure, synchronous, deterministic function with no database, no network,
no filesystem I/O, and no machine learning dependencies.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

VERSION = "rules-v1.0"

# Terminal statuses where referral resolution has concluded;
# no escalation required.
_TERMINAL_STATUSES = {
    "ARRIVED",
    "CONSULTED",
    "BACK_REFERRED",
    "CLOSED",
    "CANCELLED",
}

# Recognized roles for escalation routing
_ROLE_ASHA = "ASHA"
_ROLE_CHO = "CHO"
_ROLE_BMO = "BMO"


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse datetime from datetime instance or ISO string defensively."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    return None


def escalation_for(payload: dict) -> dict:
    """Evaluate escalation stage, role, and action message for a referral.

    Args:
        payload: Dictionary adhering to EscalationInput shape:
            - urgency: str
            - initiated_at: datetime | str
            - due_at: datetime | str
            - now: datetime | str
            - current_stage: int (accepted for compatibility, not consulted)
            - owner_user_id: UUID | str | None
            - status: str

    Returns:
        dict with:
            - stage: int (0..3)
            - escalate_to_role: 'ASHA' | 'CHO' | 'BMO' | None
            - escalate_to_user_id: None (pure rule engine)
            - due_action_at: datetime | None
            - message: str (actionable, plain-language instruction)
    """
    raw_status = payload.get("status")
    status = (raw_status or "").strip().upper() if isinstance(raw_status, str) else ""

    if status in _TERMINAL_STATUSES:
        return {
            "stage": 0,
            "escalate_to_role": None,
            "escalate_to_user_id": None,
            "due_action_at": None,
            "message": "Referral is completed or cancelled; no escalation required.",
        }

    raw_urgency = payload.get("urgency")
    urgency = (raw_urgency or "").strip().upper() if isinstance(raw_urgency, str) else ""

    if urgency == "ELECTIVE":
        return {
            "stage": 0,
            "escalate_to_role": None,
            "escalate_to_user_id": None,
            "due_action_at": None,
            "message": "Elective referral: registry recall only; no escalation required.",
        }

    now = _parse_datetime(payload.get("now"))
    due_at = _parse_datetime(payload.get("due_at"))

    if now is None or due_at is None:
        return {
            "stage": 0,
            "escalate_to_role": None,
            "escalate_to_user_id": None,
            "due_action_at": None,
            "message": "Incomplete timing data; escalation cannot be evaluated.",
        }

    # Timezone alignment if one is aware and the other naive
    if now.tzinfo is None and due_at.tzinfo is not None:
        now = now.replace(tzinfo=due_at.tzinfo)
    elif now.tzinfo is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=now.tzinfo)

    if now <= due_at:
        return {
            "stage": 0,
            "escalate_to_role": None,
            "escalate_to_user_id": None,
            "due_action_at": due_at,
            "message": "Referral is within SLA window; not yet breached.",
        }

    elapsed_hours = (now - due_at).total_seconds() / 3600.0

    # EMERGENCY: Any breach jumps immediately to Stage 3 / BMO
    if urgency == "EMERGENCY":
        return {
            "stage": 3,
            "escalate_to_role": _ROLE_BMO,
            "escalate_to_user_id": None,
            "due_action_at": None,
            "message": (
                "Emergency referral has breached its response window and patient has "
                "not arrived. Immediate BMO administrative takeover required."
            ),
        }

    # URGENT / PRIORITY: Three-band mapping
    if urgency in ("URGENT", "PRIORITY"):
        urgency_label = urgency.capitalize()
        if elapsed_hours < 24.0:
            return {
                "stage": 1,
                "escalate_to_role": _ROLE_ASHA,
                "escalate_to_user_id": None,
                "due_action_at": due_at + timedelta(hours=24),
                "message": (
                    f"{urgency_label} referral overdue by less than 24 hours. "
                    "ASHA field visit to patient required."
                ),
            }
        if elapsed_hours < 48.0:
            return {
                "stage": 2,
                "escalate_to_role": _ROLE_CHO,
                "escalate_to_user_id": None,
                "due_action_at": due_at + timedelta(hours=48),
                "message": (
                    f"{urgency_label} referral overdue by 24 to 48 hours. "
                    "CHO supervisory contact with family required."
                ),
            }
        return {
            "stage": 3,
            "escalate_to_role": _ROLE_BMO,
            "escalate_to_user_id": None,
            "due_action_at": None,
            "message": (
                f"{urgency_label} referral overdue by 48 hours or more. "
                "BMO administrative takeover required."
            ),
        }

    # ROUTINE and any unknown/unrecognised urgency: Two-band mapping (capped at Stage 2)
    label = "Routine" if urgency == "ROUTINE" else f"Unspecified ({urgency})" if urgency else "Routine"
    if elapsed_hours < 48.0:
        return {
            "stage": 1,
            "escalate_to_role": _ROLE_ASHA,
            "escalate_to_user_id": None,
            "due_action_at": due_at + timedelta(hours=48),
            "message": (
                f"{label} referral overdue by less than 48 hours. "
                "ASHA field visit to patient required."
            ),
        }

    return {
        "stage": 2,
        "escalate_to_role": _ROLE_CHO,
        "escalate_to_user_id": None,
        "due_action_at": None,
        "message": (
            f"{label} referral overdue by 48 hours or more. "
            "CHO supervisory contact with family required."
        ),
    }
