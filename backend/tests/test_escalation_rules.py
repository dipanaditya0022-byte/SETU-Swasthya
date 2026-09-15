"""Comprehensive tests for the SD-owned escalation rule engine.

Tests:
- app.services.escalation.rules.escalation_for()
- Integration with RuleEscalationEngineAdapter
- Factory readiness probe (_probe_readiness())
- Engine purity, determinism, and exact boundary threshold requirements.
"""
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.escalation.adapter import RuleEscalationEngineAdapter
from app.services.escalation.factory import _UNSAFE_SOURCE_TOKENS, _probe_readiness
from app.services.escalation.port import EscalationInput
from app.services.escalation.rules import VERSION, escalation_for

DUE_AT = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
INITIATED_AT = DUE_AT - timedelta(days=1)


def _make_payload(urgency: str, hours_past_due: float, **overrides) -> dict:
    now = DUE_AT + timedelta(hours=hours_past_due)
    payload = {
        "urgency": urgency,
        "initiated_at": INITIATED_AT,
        "due_at": DUE_AT,
        "now": now,
        "current_stage": 0,
        "owner_user_id": None,
        "status": "INITIATED",
    }
    payload.update(overrides)
    return payload


# ==============================================================================
# 1. EMERGENCY Tests
# ==============================================================================

def test_emergency_before_due_is_stage_0():
    payload = _make_payload("EMERGENCY", hours_past_due=-1.0)
    out = escalation_for(payload)
    assert out["stage"] == 0
    assert out["escalate_to_role"] is None
    assert out["escalate_to_user_id"] is None
    assert out["due_action_at"] == DUE_AT


def test_emergency_exactly_at_due_is_stage_0():
    payload = _make_payload("EMERGENCY", hours_past_due=0.0)
    out = escalation_for(payload)
    assert out["stage"] == 0
    assert out["escalate_to_role"] is None
    assert out["due_action_at"] == DUE_AT


def test_emergency_after_due_is_stage_3_bmo():
    for hours in (0.001, 0.5, 1.0, 24.0, 100.0):
        payload = _make_payload("EMERGENCY", hours_past_due=hours)
        out = escalation_for(payload)
        assert out["stage"] == 3
        assert out["escalate_to_role"] == "BMO"
        assert out["escalate_to_user_id"] is None
        assert out["due_action_at"] is None
        assert "BMO" in out["message"]


# ==============================================================================
# 2. URGENT Tests (Three-Band Mapping)
# ==============================================================================

def test_urgent_before_due_is_stage_0():
    payload = _make_payload("URGENT", hours_past_due=-2.0)
    out = escalation_for(payload)
    assert out["stage"] == 0
    assert out["escalate_to_role"] is None
    assert out["due_action_at"] == DUE_AT


def test_urgent_exactly_at_due_is_stage_0():
    payload = _make_payload("URGENT", hours_past_due=0.0)
    out = escalation_for(payload)
    assert out["stage"] == 0
    assert out["escalate_to_role"] is None
    assert out["due_action_at"] == DUE_AT


def test_urgent_just_after_due_is_stage_1_asha():
    payload = _make_payload("URGENT", hours_past_due=0.5)
    out = escalation_for(payload)
    assert out["stage"] == 1
    assert out["escalate_to_role"] == "ASHA"
    assert out["due_action_at"] == DUE_AT + timedelta(hours=24)
    assert "ASHA" in out["message"]


def test_urgent_at_23_9_hours_is_stage_1_asha():
    payload = _make_payload("URGENT", hours_past_due=23.9)
    out = escalation_for(payload)
    assert out["stage"] == 1
    assert out["escalate_to_role"] == "ASHA"
    assert out["due_action_at"] == DUE_AT + timedelta(hours=24)


def test_urgent_boundary_at_24h_is_stage_2_cho():
    payload = _make_payload("URGENT", hours_past_due=24.0)
    out = escalation_for(payload)
    assert out["stage"] == 2
    assert out["escalate_to_role"] == "CHO"
    assert out["due_action_at"] == DUE_AT + timedelta(hours=48)
    assert "CHO" in out["message"]


def test_urgent_at_47_9_hours_is_stage_2_cho():
    payload = _make_payload("URGENT", hours_past_due=47.9)
    out = escalation_for(payload)
    assert out["stage"] == 2
    assert out["escalate_to_role"] == "CHO"
    assert out["due_action_at"] == DUE_AT + timedelta(hours=48)


def test_urgent_boundary_at_48h_is_stage_3_bmo():
    payload = _make_payload("URGENT", hours_past_due=48.0)
    out = escalation_for(payload)
    assert out["stage"] == 3
    assert out["escalate_to_role"] == "BMO"
    assert out["due_action_at"] is None
    assert "BMO" in out["message"]


def test_urgent_far_overdue_remains_stage_3_bmo():
    payload = _make_payload("URGENT", hours_past_due=200.0)
    out = escalation_for(payload)
    assert out["stage"] == 3
    assert out["escalate_to_role"] == "BMO"
    assert out["due_action_at"] is None


# ==============================================================================
# 3. PRIORITY Tests (Identical Thresholds to URGENT)
# ==============================================================================

def test_priority_threshold_behavior_matches_urgent():
    assert escalation_for(_make_payload("PRIORITY", -1.0))["stage"] == 0
    assert escalation_for(_make_payload("PRIORITY", 0.0))["stage"] == 0

    p_1 = escalation_for(_make_payload("PRIORITY", 10.0))
    assert p_1["stage"] == 1
    assert p_1["escalate_to_role"] == "ASHA"
    assert p_1["due_action_at"] == DUE_AT + timedelta(hours=24)

    p_24 = escalation_for(_make_payload("PRIORITY", 24.0))
    assert p_24["stage"] == 2
    assert p_24["escalate_to_role"] == "CHO"
    assert p_24["due_action_at"] == DUE_AT + timedelta(hours=48)

    p_48 = escalation_for(_make_payload("PRIORITY", 48.0))
    assert p_48["stage"] == 3
    assert p_48["escalate_to_role"] == "BMO"
    assert p_48["due_action_at"] is None


# ==============================================================================
# 4. ROUTINE Tests (Capped at Stage 2 / CHO)
# ==============================================================================

def test_routine_before_due_is_stage_0():
    payload = _make_payload("ROUTINE", hours_past_due=-5.0)
    out = escalation_for(payload)
    assert out["stage"] == 0
    assert out["escalate_to_role"] is None
    assert out["due_action_at"] == DUE_AT


def test_routine_just_after_due_is_stage_1_asha():
    payload = _make_payload("ROUTINE", hours_past_due=1.0)
    out = escalation_for(payload)
    assert out["stage"] == 1
    assert out["escalate_to_role"] == "ASHA"
    assert out["due_action_at"] == DUE_AT + timedelta(hours=48)
    assert "ASHA" in out["message"]


def test_routine_at_47_9_hours_is_stage_1_asha():
    payload = _make_payload("ROUTINE", hours_past_due=47.9)
    out = escalation_for(payload)
    assert out["stage"] == 1
    assert out["escalate_to_role"] == "ASHA"
    assert out["due_action_at"] == DUE_AT + timedelta(hours=48)


def test_routine_boundary_at_48h_is_stage_2_cho():
    payload = _make_payload("ROUTINE", hours_past_due=48.0)
    out = escalation_for(payload)
    assert out["stage"] == 2
    assert out["escalate_to_role"] == "CHO"
    assert out["due_action_at"] is None
    assert "CHO" in out["message"]


def test_routine_never_reaches_stage_3_even_far_overdue():
    for hours in (48.1, 100.0, 1000.0, 10000.0):
        out = escalation_for(_make_payload("ROUTINE", hours_past_due=hours))
        assert out["stage"] == 2
        assert out["escalate_to_role"] == "CHO"
        assert out["due_action_at"] is None


# ==============================================================================
# 5. ELECTIVE Tests (Always Stage 0)
# ==============================================================================

def test_elective_before_and_after_due_is_stage_0():
    for hours in (-10.0, 0.0, 1.0, 50.0, 1000.0):
        out = escalation_for(_make_payload("ELECTIVE", hours_past_due=hours))
        assert out["stage"] == 0
        assert out["escalate_to_role"] is None
        assert out["escalate_to_user_id"] is None
        assert out["due_action_at"] is None
        assert "elective" in out["message"].lower()


# ==============================================================================
# 6. Terminal Statuses (Short-Circuit to Stage 0)
# ==============================================================================

@pytest.mark.parametrize("status", ["ARRIVED", "CONSULTED", "BACK_REFERRED", "CLOSED", "CANCELLED"])
def test_terminal_statuses_short_circuit_to_stage_0(status):
    for urgency in ("EMERGENCY", "URGENT", "PRIORITY", "ROUTINE"):
        payload = _make_payload(urgency, hours_past_due=100.0, status=status)
        out = escalation_for(payload)
        assert out["stage"] == 0
        assert out["escalate_to_role"] is None
        assert out["escalate_to_user_id"] is None
        assert out["due_action_at"] is None
        assert "completed or cancelled" in out["message"].lower()


# ==============================================================================
# 7. Unknown Urgency and Normalization Tests
# ==============================================================================

def test_unknown_urgency_uses_routine_behavior():
    for unknown in ("asap", "whenever", "HIGH", "garbage", "", None):
        # Breached by 10 hours -> Routine Stage 1 / ASHA
        out_10 = escalation_for(_make_payload(unknown, hours_past_due=10.0))
        assert out_10["stage"] == 1
        assert out_10["escalate_to_role"] == "ASHA"
        assert out_10["due_action_at"] == DUE_AT + timedelta(hours=48)

        # Breached by 60 hours -> Routine Stage 2 / CHO (capped at 2)
        out_60 = escalation_for(_make_payload(unknown, hours_past_due=60.0))
        assert out_60["stage"] == 2
        assert out_60["escalate_to_role"] == "CHO"
        assert out_60["due_action_at"] is None


def test_urgency_whitespace_and_case_normalization():
    variations = [" urgent ", "Urgent", "URGENT\n", "\turgent\t"]
    for var in variations:
        out = escalation_for(_make_payload(var, hours_past_due=25.0))
        assert out["stage"] == 2
        assert out["escalate_to_role"] == "CHO"


def test_status_whitespace_and_case_normalization():
    variations = [" closed ", "Closed", "CLOSED\n", "  cancelled "]
    for var in variations:
        out = escalation_for(_make_payload("EMERGENCY", hours_past_due=50.0, status=var))
        assert out["stage"] == 0
        assert out["escalate_to_role"] is None


# ==============================================================================
# 8. CURRENT_STAGE Does NOT Control Target Stage (Anti-max Rule)
# ==============================================================================

def test_current_stage_does_not_control_target_stage():
    # current_stage is 2, but referral is only 5 hours overdue for URGENT (target is 1)
    payload_1 = _make_payload("URGENT", hours_past_due=5.0, current_stage=2)
    out_1 = escalation_for(payload_1)
    assert out_1["stage"] == 1  # must return 1, NOT max(2, 1)

    # current_stage is 3, but referral is CLOSED (target is 0)
    payload_2 = _make_payload("EMERGENCY", hours_past_due=50.0, current_stage=3, status="CLOSED")
    out_2 = escalation_for(payload_2)
    assert out_2["stage"] == 0

    # current_stage is 2, but referral is not yet breached (target is 0)
    payload_3 = _make_payload("ROUTINE", hours_past_due=-1.0, current_stage=2)
    out_3 = escalation_for(payload_3)
    assert out_3["stage"] == 0


# ==============================================================================
# 9. Timing and Timestamp Verification
# ==============================================================================

def test_due_action_at_exact_threshold_timestamps():
    # URGENT Stage 1 -> due_at + 24h
    out_u1 = escalation_for(_make_payload("URGENT", hours_past_due=10.0))
    assert out_u1["due_action_at"] == DUE_AT + timedelta(hours=24)

    # URGENT Stage 2 -> due_at + 48h
    out_u2 = escalation_for(_make_payload("URGENT", hours_past_due=30.0))
    assert out_u2["due_action_at"] == DUE_AT + timedelta(hours=48)

    # URGENT Stage 3 -> None
    out_u3 = escalation_for(_make_payload("URGENT", hours_past_due=50.0))
    assert out_u3["due_action_at"] is None

    # ROUTINE Stage 1 -> due_at + 48h
    out_r1 = escalation_for(_make_payload("ROUTINE", hours_past_due=10.0))
    assert out_r1["due_action_at"] == DUE_AT + timedelta(hours=48)

    # ROUTINE Stage 2 -> None
    out_r2 = escalation_for(_make_payload("ROUTINE", hours_past_due=50.0))
    assert out_r2["due_action_at"] is None


def test_iso_string_datetime_inputs_supported():
    payload = {
        "urgency": "URGENT",
        "initiated_at": INITIATED_AT.isoformat(),
        "due_at": DUE_AT.isoformat(),
        "now": (DUE_AT + timedelta(hours=30)).isoformat(),
        "current_stage": 0,
        "owner_user_id": None,
        "status": "INITIATED",
    }
    out = escalation_for(payload)
    assert out["stage"] == 2
    assert out["escalate_to_role"] == "CHO"


# ==============================================================================
# 10. Escalate To User ID and Determinism
# ==============================================================================

def test_escalate_to_user_id_is_always_none():
    out1 = escalation_for(_make_payload("URGENT", hours_past_due=30.0, owner_user_id=None))
    assert out1["escalate_to_user_id"] is None

    out2 = escalation_for(_make_payload("URGENT", hours_past_due=30.0, owner_user_id=uuid4()))
    assert out2["escalate_to_user_id"] is None


def test_engine_is_strictly_deterministic():
    payload = _make_payload("URGENT", hours_past_due=30.0)
    out1 = escalation_for(payload)
    out2 = escalation_for(payload)
    assert out1 == out2


# ==============================================================================
# 11. Output Hygiene & Safety
# ==============================================================================

def test_output_schema_and_message_hygiene():
    for urgency in ("EMERGENCY", "URGENT", "PRIORITY", "ROUTINE", "ELECTIVE"):
        for hours in (-5.0, 0.0, 10.0, 30.0, 60.0):
            out = escalation_for(_make_payload(urgency, hours_past_due=hours))
            assert out["stage"] in (0, 1, 2, 3)
            assert out["escalate_to_role"] in ("ASHA", "CHO", "BMO", None)
            assert isinstance(out["message"], str)
            assert len(out["message"]) > 0
            assert "RULE_" not in out["message"]
            assert not out["message"][0].isdigit()


# ==============================================================================
# 12. Adapter Compatibility and Factory Readiness Probe
# ==============================================================================

def test_adapter_compatibility_with_escalation_rules():
    adapter = RuleEscalationEngineAdapter()
    sample = EscalationInput(
        urgency="URGENT",
        initiated_at=INITIATED_AT,
        due_at=DUE_AT,
        now=DUE_AT + timedelta(hours=25),
        current_stage=0,
        owner_user_id=uuid4(),
        status="INITIATED",
    )
    result = adapter.escalate(sample)
    assert result.engine == "rule"
    assert result.stage == 2
    assert result.escalate_to_role == "CHO"
    assert result.escalate_to_user_id is None
    assert result.due_action_at == DUE_AT + timedelta(hours=48)
    assert "CHO" in result.message


def test_factory_readiness_probe_passes():
    ready, reason = _probe_readiness()
    assert ready is True, f"Factory readiness probe failed: {reason}"
    assert reason is None


def test_engine_source_purity_check():
    import app.services.escalation.rules as rules_mod
    source = inspect.getsource(rules_mod).lower()
    for token in _UNSAFE_SOURCE_TOKENS:
        assert token not in source, f"Forbidden unsafe token {token!r} found in rules.py source!"
