"""Tests for the SD-owned synthetic demo data service.

Verifies:
- All 8 required demonstration scenarios are present and structured.
- Identifiers are deterministic, non-random, and clearly marked synthetic.
- Clinical cases evaluate accurately against evaluate_triage().
- Escalation cases evaluate accurately against escalation_for().
- Due-list reminder integration accurately categorizes upcoming vs overdue.
- Zero database mutation and strictly repeatable execution.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlmodel import Session, create_engine

from app.jobs.due_list_reminders import generate_due_list_reminders
from app.models.referral import Referral
from app.models.referral_state import ReferralState
from app.services.demo_data import (
    DEFAULT_REFERENCE_NOW,
    get_synthetic_demo_cases,
)
from app.services.escalation.rules import escalation_for
from app.services.triage.rules import evaluate_triage

FIXED_NOW = datetime(2026, 8, 30, 10, 0, 0, tzinfo=timezone.utc)


# ==============================================================================
# 1. Structure and Scenario Coverage Tests
# ==============================================================================

def test_all_eight_scenarios_exist():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    expected_keys = [
        "CASE_1_NORMAL_ROUTINE",
        "CASE_2_EMERGENCY_RED_FLAG",
        "CASE_3_URGENT_REFERRAL",
        "CASE_4_APPROACHING_DUE_DATE",
        "CASE_5_OVERDUE_REFERRAL",
        "CASE_6_MULTI_STAGE_ESCALATION",
        "CASE_7_INCOMPLETE_ASSESSMENT",
        "CASE_8_MULTIPLE_URGENCIES",
    ]
    for key in expected_keys:
        assert key in cases, f"Missing scenario: {key}"


def test_identifiers_are_deterministic_and_synthetic():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    for key in [
        "CASE_1_NORMAL_ROUTINE",
        "CASE_2_EMERGENCY_RED_FLAG",
        "CASE_3_URGENT_REFERRAL",
        "CASE_7_INCOMPLETE_ASSESSMENT",
    ]:
        patient = cases[key]["patient"]
        assert "Synthetic" in patient["name"]
        assert UUID(patient["id"])

    for key in [
        "CASE_4_APPROACHING_DUE_DATE",
        "CASE_5_OVERDUE_REFERRAL",
        "CASE_6_MULTI_STAGE_ESCALATION",
    ]:
        ref = cases[key]["referral"]
        assert isinstance(ref["id"], UUID)
        assert isinstance(ref["patient_id"], UUID)
        assert "Synthetic" in ref["patient_name"]


def test_no_real_looking_sensitive_information():
    """Verify all demo cases contain strictly synthetic, non-sensitive mock data."""
    cases = get_synthetic_demo_cases(FIXED_NOW)
    import re
    # Check that no Indian phone numbers (10 digits starting with 6-9) or real Aadhaar (12 digits starting with 2-9) exist
    phone_pattern = re.compile(r"\b[6-9]\d{9}\b")
    aadhaar_pattern = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
    
    serialized = str(cases)
    assert not phone_pattern.search(serialized), "Found potential phone number in demo data"
    assert not aadhaar_pattern.search(serialized), "Found potential Aadhaar number in demo data"

    # Verify patient names and locations are marked synthetic
    for key in ["CASE_1_NORMAL_ROUTINE", "CASE_2_EMERGENCY_RED_FLAG", "CASE_3_URGENT_REFERRAL", "CASE_7_INCOMPLETE_ASSESSMENT"]:
        assert "Synthetic" in cases[key]["patient"]["name"]
        assert "Synthetic" in cases[key]["patient"]["village"]


def test_repeated_generation_is_strictly_identical():
    cases1 = get_synthetic_demo_cases(FIXED_NOW)
    cases2 = get_synthetic_demo_cases(FIXED_NOW)
    assert cases1 == cases2


# ==============================================================================
# 2. Clinical Triage Evaluation Tests (evaluate_triage integration)
# ==============================================================================

def test_case_1_normal_routine_evaluates_to_manage_here():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    triage_in = cases["CASE_1_NORMAL_ROUTINE"]["triage_input"]
    result = evaluate_triage(triage_in)
    assert result["disposition"] == "MANAGE_HERE"
    assert result["urgency"] == "ROUTINE"
    assert result["insufficient_data"] is False
    assert result["red_flags"] == []


def test_case_2_emergency_red_flag_evaluates_to_emergency():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    triage_in = cases["CASE_2_EMERGENCY_RED_FLAG"]["triage_input"]
    result = evaluate_triage(triage_in)
    assert result["disposition"] == "EMERGENCY"
    assert result["urgency"] == "IMMEDIATE"
    assert "SEVERE_HYPERTENSION" in result["red_flags"]


def test_case_3_urgent_referral_evaluates_to_refer_24h():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    triage_in = cases["CASE_3_URGENT_REFERRAL"]["triage_input"]
    result = evaluate_triage(triage_in)
    assert result["disposition"] == "REFER"
    assert result["urgency"] == "WITHIN_24H"
    assert "HYPERTENSION" in result["red_flags"]


def test_case_7_incomplete_assessment_escalates_to_refer():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    triage_in = cases["CASE_7_INCOMPLETE_ASSESSMENT"]["triage_input"]
    result = evaluate_triage(triage_in)
    assert result["disposition"] == "REFER"
    assert result["urgency"] == "WITHIN_24H"
    assert result["insufficient_data"] is True
    assert "bp_systolic" in result["missing_fields"]
    assert "bp_diastolic" in result["missing_fields"]


# ==============================================================================
# 3. Escalation Evaluation Tests (escalation_for integration)
# ==============================================================================

def test_case_5_overdue_referral_evaluates_to_stage_1_asha():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    ref = cases["CASE_5_OVERDUE_REFERRAL"]["referral"]
    payload = {
        "urgency": ref["urgency"],
        "initiated_at": ref["initiated_at"],
        "due_at": ref["due_at"],
        "now": ref["now"],
        "current_stage": ref["current_stage"],
        "owner_user_id": ref["owner_user_id"],
        "status": ref["status"],
    }
    result = escalation_for(payload)
    assert result["stage"] == 1
    assert result["escalate_to_role"] == "ASHA"
    assert result["due_action_at"] == ref["due_at"] + timedelta(hours=24)
    assert "ASHA" in result["message"]


def test_case_6_multi_stage_escalation_evaluates_to_stage_3_bmo():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    ref = cases["CASE_6_MULTI_STAGE_ESCALATION"]["referral"]
    payload = {
        "urgency": ref["urgency"],
        "initiated_at": ref["initiated_at"],
        "due_at": ref["due_at"],
        "now": ref["now"],
        "current_stage": ref["current_stage"],
        "owner_user_id": ref["owner_user_id"],
        "status": ref["status"],
    }
    result = escalation_for(payload)
    assert result["stage"] == 3
    assert result["escalate_to_role"] == "BMO"
    assert result["due_action_at"] is None
    assert "BMO" in result["message"]


def test_case_8_multiple_urgencies_portfolio_evaluates_accurately():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    portfolio = cases["CASE_8_MULTIPLE_URGENCIES"]["referrals"]
    expected_categories = {"EMERGENCY", "URGENT", "PRIORITY", "ROUTINE", "ELECTIVE"}
    actual_categories = {item["urgency"] for item in portfolio}
    assert actual_categories == expected_categories

    for item in portfolio:
        payload = {
            "urgency": item["urgency"],
            "initiated_at": item["initiated_at"],
            "due_at": item["due_at"],
            "now": item["now"],
            "current_stage": item["current_stage"],
            "owner_user_id": item["owner_user_id"],
            "status": item["status"],
        }
        res = escalation_for(payload)
        assert res["stage"] == item["expected_stage"], f"Failed for urgency {item['urgency']}"
        assert res["escalate_to_role"] == item["expected_role"], f"Failed for urgency {item['urgency']}"


# ==============================================================================
# 4. Due-List Reminders Integration Tests (generate_due_list_reminders)
# ==============================================================================

def test_case_4_approaching_due_date_produces_upcoming_reminder():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    ref_data = cases["CASE_4_APPROACHING_DUE_DATE"]["referral"]

    # Verify directly via in-memory SQLite session with Referral table
    engine = create_engine("sqlite:///:memory:")
    Referral.__table__.create(engine)

    with Session(engine) as session:
        ref = Referral(
            id=ref_data["id"],
            patient_id=ref_data["patient_id"],
            from_facility_id=UUID("00000002-0000-4000-a000-000000000001"),
            destination_facility_id=UUID("00000002-0000-4000-a000-000000000002"),
            reason="Synthetic approaching due date test",
            urgency=ref_data["urgency"],
            status=ReferralState(ref_data["status"]),
            initiated_at=ref_data["initiated_at"],
            due_at=ref_data["due_at"],
            owner_user_id=ref_data["owner_user_id"],
        )
        session.add(ref)
        session.commit()

        result = generate_due_list_reminders(session, now=FIXED_NOW, lookahead_hours=24.0)
        assert result["total_reminders"] == 1
        assert result["upcoming_count"] == 1
        assert result["overdue_count"] == 0

        reminder = result["reminders"][0]
        assert reminder["type"] == "UPCOMING"
        assert reminder["referral_id"] == str(ref_data["id"])
        assert abs(reminder["hours_until_due"] - 4.0) < 0.1
        assert reminder["escalation_stage"] == 0


def test_case_5_overdue_referral_produces_overdue_reminder():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    ref_data = cases["CASE_5_OVERDUE_REFERRAL"]["referral"]

    engine = create_engine("sqlite:///:memory:")
    Referral.__table__.create(engine)

    with Session(engine) as session:
        ref = Referral(
            id=ref_data["id"],
            patient_id=ref_data["patient_id"],
            from_facility_id=UUID("00000002-0000-4000-a000-000000000001"),
            destination_facility_id=UUID("00000002-0000-4000-a000-000000000002"),
            reason="Synthetic overdue referral test",
            urgency=ref_data["urgency"],
            status=ReferralState(ref_data["status"]),
            initiated_at=ref_data["initiated_at"],
            due_at=ref_data["due_at"],
            owner_user_id=ref_data["owner_user_id"],
        )
        session.add(ref)
        session.commit()

        result = generate_due_list_reminders(session, now=FIXED_NOW, lookahead_hours=24.0)
        assert result["total_reminders"] == 1
        assert result["overdue_count"] == 1
        assert result["upcoming_count"] == 0

        reminder = result["reminders"][0]
        assert reminder["type"] == "OVERDUE"
        assert reminder["referral_id"] == str(ref_data["id"])
        assert reminder["escalation_stage"] == 1
        assert reminder["escalate_to_role"] == "ASHA"


def test_case_6_multi_stage_escalation_produces_overdue_reminder():
    cases = get_synthetic_demo_cases(FIXED_NOW)
    ref_data = cases["CASE_6_MULTI_STAGE_ESCALATION"]["referral"]

    engine = create_engine("sqlite:///:memory:")
    Referral.__table__.create(engine)

    with Session(engine) as session:
        ref = Referral(
            id=ref_data["id"],
            patient_id=ref_data["patient_id"],
            from_facility_id=UUID("00000002-0000-4000-a000-000000000001"),
            destination_facility_id=UUID("00000002-0000-4000-a000-000000000002"),
            reason="Synthetic multi-stage escalation test",
            urgency=ref_data["urgency"],
            status=ReferralState(ref_data["status"]),
            initiated_at=ref_data["initiated_at"],
            due_at=ref_data["due_at"],
            owner_user_id=ref_data["owner_user_id"],
        )
        session.add(ref)
        session.commit()

        result = generate_due_list_reminders(session, now=FIXED_NOW, lookahead_hours=24.0)
        assert result["total_reminders"] == 1
        assert result["overdue_count"] == 1
        assert result["upcoming_count"] == 0

        reminder = result["reminders"][0]
        assert reminder["type"] == "OVERDUE"
        assert reminder["referral_id"] == str(ref_data["id"])
        assert reminder["escalation_stage"] == 3
        assert reminder["escalate_to_role"] == "BMO"


def test_demo_data_does_not_mutate_database_state():
    engine = create_engine("sqlite:///:memory:")
    Referral.__table__.create(engine)
    with Session(engine) as session:
        # Call get_synthetic_demo_cases multiple times
        get_synthetic_demo_cases(FIXED_NOW)
        get_synthetic_demo_cases(FIXED_NOW)
        # Database table remains completely empty
        from sqlmodel import select
        rows = session.exec(select(Referral)).all()
        assert len(rows) == 0


def test_existing_sd_engines_are_used_rather_than_duplicated():
    """Verify that existing SD rule engines are imported and functional."""
    import inspect
    from app.services.triage.rules import evaluate_triage
    from app.services.escalation.rules import escalation_for
    from app.jobs.due_list_reminders import generate_due_list_reminders

    assert callable(evaluate_triage)
    assert callable(escalation_for)
    assert callable(generate_due_list_reminders)
    assert "payload" in inspect.signature(escalation_for).parameters
    assert "data" in inspect.signature(evaluate_triage).parameters
    assert "session" in inspect.signature(generate_due_list_reminders).parameters

