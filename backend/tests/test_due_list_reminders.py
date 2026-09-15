"""Tests for the SD-owned scheduled due-list reminders job.

Exercises app.jobs.due_list_reminders.generate_due_list_reminders:
- Query filtering (excluding completed/cancelled, null due_at)
- Upcoming referral detection within lookahead window
- Overdue referral detection and integration with SD escalation engine
- Exception-first sorting (EMERGENCY first, overdue before upcoming)
- Missing owner safety
- Logging hygiene and idempotency
"""
from datetime import datetime, timedelta, timezone
import logging
import uuid
import pytest
from sqlmodel import Session, create_engine

from app.jobs.due_list_reminders import generate_due_list_reminders
from app.models.referral import Referral
from app.models.referral_state import ReferralState


@pytest.fixture
def sqlite_session():
    """In-memory SQLite session with Referral table for pure, fast testing."""
    engine = create_engine("sqlite:///:memory:")
    Referral.__table__.create(engine)
    with Session(engine) as session:
        yield session


def _create_referral(
    session: Session,
    *,
    urgency: str = "ROUTINE",
    status: ReferralState = ReferralState.INITIATED,
    due_at: datetime | None = None,
    initiated_at: datetime | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> Referral:
    now = datetime.now(timezone.utc)
    ref = Referral(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        from_facility_id=uuid.uuid4(),
        destination_facility_id=uuid.uuid4(),
        reason="Due-list test case",
        urgency=urgency,
        status=status,
        initiated_at=initiated_at or (now - timedelta(days=2)),
        due_at=due_at,
        owner_user_id=owner_user_id,
        escalation_stage=0,
    )
    session.add(ref)
    session.commit()
    session.refresh(ref)
    return ref


# ==============================================================================
# 1. Base Functionality & Filtering Tests
# ==============================================================================

def test_empty_database_returns_zero_reminders(sqlite_session):
    result = generate_due_list_reminders(sqlite_session)
    assert result["total_checked"] == 0
    assert result["overdue_count"] == 0
    assert result["upcoming_count"] == 0
    assert result["total_reminders"] == 0
    assert result["reminders"] == []


def test_referral_with_null_due_at_is_excluded(sqlite_session):
    _create_referral(sqlite_session, due_at=None)
    result = generate_due_list_reminders(sqlite_session)
    assert result["total_checked"] == 0
    assert result["total_reminders"] == 0


@pytest.mark.parametrize(
    "completed_status",
    [
        ReferralState.ARRIVED,
        ReferralState.CONSULTED,
        ReferralState.BACK_REFERRED,
        ReferralState.CLOSED,
        ReferralState.CANCELLED,
    ],
)
def test_completed_and_cancelled_statuses_are_excluded(sqlite_session, completed_status):
    now = datetime.now(timezone.utc)
    # Severely overdue, but completed or cancelled
    _create_referral(
        sqlite_session,
        status=completed_status,
        due_at=now - timedelta(hours=50),
    )
    result = generate_due_list_reminders(sqlite_session, now=now)
    assert result["total_checked"] == 0
    assert result["total_reminders"] == 0


# ==============================================================================
# 2. Upcoming Reminders Tests
# ==============================================================================

def test_upcoming_referral_within_lookahead_window(sqlite_session):
    now = datetime.now(timezone.utc)
    due_at = now + timedelta(hours=6)
    owner_id = uuid.uuid4()
    ref = _create_referral(
        sqlite_session,
        urgency="URGENT",
        status=ReferralState.INITIATED,
        due_at=due_at,
        owner_user_id=owner_id,
    )

    result = generate_due_list_reminders(sqlite_session, now=now, lookahead_hours=24.0)
    assert result["total_checked"] == 1
    assert result["upcoming_count"] == 1
    assert result["overdue_count"] == 0
    assert result["total_reminders"] == 1

    item = result["reminders"][0]
    assert item["referral_id"] == str(ref.id)
    assert item["type"] == "UPCOMING"
    assert item["urgency"] == "URGENT"
    assert item["escalation_stage"] == 0
    assert item["escalate_to_role"] is None
    assert item["owner_user_id"] == str(owner_id)
    assert "upcoming" in item["message"].lower()
    assert abs(item["hours_until_due"] - 6.0) < 0.1


def test_upcoming_referral_outside_lookahead_window_is_excluded(sqlite_session):
    now = datetime.now(timezone.utc)
    # Due in 30 hours, but lookahead is 24 hours
    _create_referral(
        sqlite_session,
        urgency="ROUTINE",
        status=ReferralState.INITIATED,
        due_at=now + timedelta(hours=30),
    )

    result = generate_due_list_reminders(sqlite_session, now=now, lookahead_hours=24.0)
    assert result["total_checked"] == 1
    assert result["upcoming_count"] == 0
    assert result["total_reminders"] == 0


def test_custom_lookahead_window_includes_further_referrals(sqlite_session):
    now = datetime.now(timezone.utc)
    _create_referral(
        sqlite_session,
        urgency="ROUTINE",
        status=ReferralState.INITIATED,
        due_at=now + timedelta(hours=30),
    )

    result = generate_due_list_reminders(sqlite_session, now=now, lookahead_hours=48.0)
    assert result["upcoming_count"] == 1
    assert result["total_reminders"] == 1


# ==============================================================================
# 3. Overdue & Escalation Engine Integration Tests
# ==============================================================================

def test_overdue_urgent_referral_annotated_with_escalation_stage_1(sqlite_session):
    now = datetime.now(timezone.utc)
    due_at = now - timedelta(hours=10)  # 10h overdue -> Stage 1 / ASHA
    ref = _create_referral(
        sqlite_session,
        urgency="URGENT",
        status=ReferralState.INITIATED,
        due_at=due_at,
    )

    result = generate_due_list_reminders(sqlite_session, now=now)
    assert result["overdue_count"] == 1
    assert result["upcoming_count"] == 0

    item = result["reminders"][0]
    assert item["referral_id"] == str(ref.id)
    assert item["type"] == "OVERDUE"
    assert item["escalation_stage"] == 1
    assert item["escalate_to_role"] == "ASHA"
    assert "ASHA" in item["message"]


def test_overdue_urgent_referral_annotated_with_escalation_stage_3_bmo(sqlite_session):
    now = datetime.now(timezone.utc)
    due_at = now - timedelta(hours=50)  # 50h overdue -> Stage 3 / BMO
    ref = _create_referral(
        sqlite_session,
        urgency="URGENT",
        status=ReferralState.INITIATED,
        due_at=due_at,
    )

    result = generate_due_list_reminders(sqlite_session, now=now)
    item = result["reminders"][0]
    assert item["escalation_stage"] == 3
    assert item["escalate_to_role"] == "BMO"
    assert "BMO" in item["message"]


def test_overdue_emergency_referral_immediately_stage_3_bmo(sqlite_session):
    now = datetime.now(timezone.utc)
    due_at = now - timedelta(minutes=15)  # 15 min overdue emergency -> Stage 3 / BMO
    ref = _create_referral(
        sqlite_session,
        urgency="EMERGENCY",
        status=ReferralState.INITIATED,
        due_at=due_at,
    )

    result = generate_due_list_reminders(sqlite_session, now=now)
    item = result["reminders"][0]
    assert item["type"] == "OVERDUE"
    assert item["escalation_stage"] == 3
    assert item["escalate_to_role"] == "BMO"
    assert "BMO" in item["message"]


# ==============================================================================
# 4. Sorting & Prioritization Tests (Exception-First)
# ==============================================================================

def test_sorting_prioritizes_emergency_and_overdue(sqlite_session):
    now = datetime.now(timezone.utc)

    # 1. Upcoming routine
    r_upcoming = _create_referral(
        sqlite_session,
        urgency="ROUTINE",
        status=ReferralState.INITIATED,
        due_at=now + timedelta(hours=2),
    )
    # 2. Overdue routine (10h)
    r_overdue_routine = _create_referral(
        sqlite_session,
        urgency="ROUTINE",
        status=ReferralState.INITIATED,
        due_at=now - timedelta(hours=10),
    )
    # 3. Overdue emergency (1h)
    r_overdue_emerg = _create_referral(
        sqlite_session,
        urgency="EMERGENCY",
        status=ReferralState.INITIATED,
        due_at=now - timedelta(hours=1),
    )
    # 4. Overdue urgent (20h)
    r_overdue_urgent = _create_referral(
        sqlite_session,
        urgency="URGENT",
        status=ReferralState.INITIATED,
        due_at=now - timedelta(hours=20),
    )

    result = generate_due_list_reminders(sqlite_session, now=now)
    assert result["total_reminders"] == 4

    reminders = result["reminders"]
    # First must be the overdue emergency
    assert reminders[0]["referral_id"] == str(r_overdue_emerg.id)
    # Second must be the most overdue non-emergency (20h overdue urgent)
    assert reminders[1]["referral_id"] == str(r_overdue_urgent.id)
    # Third must be the other overdue (10h overdue routine)
    assert reminders[2]["referral_id"] == str(r_overdue_routine.id)
    # Last must be the upcoming reminder
    assert reminders[3]["referral_id"] == str(r_upcoming.id)


# ==============================================================================
# 5. Determinism & Logging Tests
# ==============================================================================

def test_repeated_execution_is_deterministic(sqlite_session):
    now = datetime.now(timezone.utc)
    _create_referral(sqlite_session, urgency="URGENT", due_at=now - timedelta(hours=5))
    _create_referral(sqlite_session, urgency="ROUTINE", due_at=now + timedelta(hours=5))

    out1 = generate_due_list_reminders(sqlite_session, now=now)
    out2 = generate_due_list_reminders(sqlite_session, now=now)
    assert out1 == out2


def test_notification_logging_emits_warnings(sqlite_session, caplog):
    now = datetime.now(timezone.utc)
    _create_referral(sqlite_session, urgency="URGENT", due_at=now - timedelta(hours=5))

    with caplog.at_level(logging.WARNING):
        generate_due_list_reminders(sqlite_session, now=now)

    assert any("DUE-LIST REMINDER" in record.message for record in caplog.records)
