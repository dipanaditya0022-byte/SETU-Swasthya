"""Tests for app/services/escalation/fallback.py -- FallbackEscalationEngine.

Pure unit tests: no database, no app startup, no fixtures with real
credentials. (Note: this repo's tests/conftest.py runs an autouse,
session-scoped fixture that creates/migrates a throwaway test database
regardless of what an individual test needs -- see conftest.py's own
docstring -- so a running Postgres is still required to *collect* this
file, even though none of these tests touch a session.)

Exercises this step's own stage-mapping table: EMERGENCY always stage
3/BMO once breached, URGENT/PRIORITY's three-band mapping, ROUTINE's
two-band cap (never stage 3), ELECTIVE always stage 0/None, and the
not-yet-breached (now <= due_at) safe-default case. Mirrors
tests/test_triage_fallback.py's own structure/naming convention.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.escalation.fallback import VERSION, FallbackEscalationEngine
from app.services.escalation.port import EscalationInput

engine = FallbackEscalationEngine()

DUE_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _eval(urgency: str, hours_past_due: float, **overrides) -> "EscalationOutput":  # noqa: F821
    now = DUE_AT + timedelta(hours=hours_past_due)
    kwargs = dict(
        urgency=urgency,
        initiated_at=DUE_AT - timedelta(days=1),
        due_at=DUE_AT,
        now=now,
        current_stage=0,
        owner_user_id=None,
        status="INITIATED",
    )
    kwargs.update(overrides)
    return engine.escalate(EscalationInput(**kwargs))


# ============================================================
# Engine identity
# ============================================================

def test_engine_name_and_version():
    assert engine.name == "fallback"
    assert VERSION == "fallback-v1.0"


# ============================================================
# Not-yet-breached -- safe default regardless of urgency.
# ============================================================

def test_not_yet_breached_is_stage_zero_no_role():
    for urgency in ("EMERGENCY", "URGENT", "PRIORITY", "ROUTINE", "ELECTIVE"):
        out = _eval(urgency, hours_past_due=-1)
        assert out.stage == 0
        assert out.escalate_to_role is None
        assert out.escalate_to_user_id is None
        assert "not yet breached" in out.message.lower() or "elective" in out.message.lower()


def test_exactly_at_due_at_is_not_breached():
    out = _eval("URGENT", hours_past_due=0)
    assert out.stage == 0
    assert out.escalate_to_role is None


# ============================================================
# EMERGENCY -- any breach jumps straight to stage 3 / BMO.
# ============================================================

def test_emergency_any_breach_is_stage_3_bmo():
    for hours in (0.01, 1, 5, 100):
        out = _eval("EMERGENCY", hours_past_due=hours)
        assert out.stage == 3
        assert out.escalate_to_role == "BMO"
        assert out.engine == "fallback"


# ============================================================
# URGENT / PRIORITY -- three-band mapping.
# ============================================================

def test_urgent_0_to_24h_is_stage_1_asha():
    out = _eval("URGENT", hours_past_due=10)
    assert out.stage == 1
    assert out.escalate_to_role == "ASHA"


def test_urgent_24_to_48h_is_stage_2_cho():
    out = _eval("URGENT", hours_past_due=30)
    assert out.stage == 2
    assert out.escalate_to_role == "CHO"


def test_urgent_over_48h_is_stage_3_bmo():
    out = _eval("URGENT", hours_past_due=60)
    assert out.stage == 3
    assert out.escalate_to_role == "BMO"


def test_urgent_boundary_at_24h_is_stage_2():
    out = _eval("URGENT", hours_past_due=24)
    assert out.stage == 2
    assert out.escalate_to_role == "CHO"


def test_urgent_boundary_at_48h_is_stage_3():
    out = _eval("URGENT", hours_past_due=48)
    assert out.stage == 3
    assert out.escalate_to_role == "BMO"


def test_priority_bands_match_urgent():
    assert _eval("PRIORITY", hours_past_due=10).stage == 1
    assert _eval("PRIORITY", hours_past_due=10).escalate_to_role == "ASHA"
    assert _eval("PRIORITY", hours_past_due=30).stage == 2
    assert _eval("PRIORITY", hours_past_due=30).escalate_to_role == "CHO"
    assert _eval("PRIORITY", hours_past_due=60).stage == 3
    assert _eval("PRIORITY", hours_past_due=60).escalate_to_role == "BMO"


# ============================================================
# ROUTINE -- two-band cap, never stage 3.
# ============================================================

def test_routine_0_to_48h_is_stage_1_asha():
    out = _eval("ROUTINE", hours_past_due=20)
    assert out.stage == 1
    assert out.escalate_to_role == "ASHA"


def test_routine_over_48h_is_stage_2_cho():
    out = _eval("ROUTINE", hours_past_due=100)
    assert out.stage == 2
    assert out.escalate_to_role == "CHO"


def test_routine_never_reaches_stage_3_even_far_past_due():
    out = _eval("ROUTINE", hours_past_due=10_000)
    assert out.stage == 2
    assert out.escalate_to_role == "CHO"


# ============================================================
# ELECTIVE -- always stage 0 / None, regardless of breach.
# ============================================================

def test_elective_always_stage_0_even_when_far_past_due():
    for hours in (-5, 0, 1, 1000):
        out = _eval("ELECTIVE", hours_past_due=hours)
        assert out.stage == 0
        assert out.escalate_to_role is None
        assert out.escalate_to_user_id is None


# ============================================================
# Terminal status short-circuits escalation entirely.
# ============================================================

def test_closed_status_short_circuits_to_stage_0():
    out = _eval("EMERGENCY", hours_past_due=1000, status="CLOSED")
    assert out.stage == 0
    assert out.escalate_to_role is None


def test_cancelled_status_short_circuits_to_stage_0():
    out = _eval("URGENT", hours_past_due=1000, status="CANCELLED")
    assert out.stage == 0
    assert out.escalate_to_role is None


# ============================================================
# escalate_to_user_id -- the reports_to chain-walk gap.
# ============================================================

def test_escalate_to_user_id_is_none_with_no_owner():
    out = _eval("URGENT", hours_past_due=30, owner_user_id=None)
    assert out.escalate_to_user_id is None
    assert "no owner" in out.message.lower() or "no specific" in out.message.lower()


def test_escalate_to_user_id_is_none_even_with_owner_set():
    # The fallback engine has no database session to walk the reports_to
    # chain with, regardless of whether an owner is set -- see fallback.py's
    # own module docstring.
    out = _eval("URGENT", hours_past_due=30, owner_user_id=uuid4())
    assert out.escalate_to_user_id is None


# ============================================================
# Message hygiene -- plain language, never a rule ID or a score.
# ============================================================

def test_message_is_plain_language_not_a_rule_id():
    out = _eval("URGENT", hours_past_due=60)
    assert out.message
    assert "RULE_" not in out.message
    assert not out.message[0].isdigit()
