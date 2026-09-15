"""Deterministic synthetic demo data service for SETU-Swasthya.

Provides 100% synthetic, realistic clinical and operational demonstration cases
for system verification, rehearsal, and hackathon presentation.

Contains zero real patient information. All names, addresses, and identifiers
are synthetic demo mocks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

# Default deterministic reference timestamp for reproducible testing/demo runs
DEFAULT_REFERENCE_NOW = datetime(2026, 8, 30, 10, 0, 0, tzinfo=timezone.utc)

# Fixed deterministic synthetic mock identifiers (RFC 4122 v4 format with non-numeric hex)
MOCK_PATIENT_1 = UUID("00000001-0000-4000-a000-000000000001")
MOCK_PATIENT_2 = UUID("00000001-0000-4000-a000-000000000002")
MOCK_PATIENT_3 = UUID("00000001-0000-4000-a000-000000000003")
MOCK_PATIENT_4 = UUID("00000001-0000-4000-a000-000000000004")
MOCK_PATIENT_5 = UUID("00000001-0000-4000-a000-000000000005")
MOCK_PATIENT_6 = UUID("00000001-0000-4000-a000-000000000006")
MOCK_PATIENT_7 = UUID("00000001-0000-4000-a000-000000000007")
MOCK_PATIENT_8 = UUID("00000001-0000-4000-a000-000000000008")

MOCK_FACILITY_HWC = UUID("00000002-0000-4000-a000-000000000001")
MOCK_FACILITY_DH = UUID("00000002-0000-4000-a000-000000000002")
MOCK_OWNER_ASHA = UUID("00000003-0000-4000-a000-000000000001")


def get_synthetic_demo_cases(
    reference_now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Generate the 8 representative synthetic demonstration scenarios.

    Args:
        reference_now: Deterministic evaluation instant. If None, defaults to
            DEFAULT_REFERENCE_NOW (2026-08-30T10:00:00Z).

    Returns:
        Dictionary keyed by scenario identifiers covering:
        1. NORMAL_ROUTINE
        2. EMERGENCY_RED_FLAG
        3. URGENT_REFERRAL
        4. APPROACHING_DUE_DATE
        5. OVERDUE_REFERRAL
        6. MULTI_STAGE_ESCALATION
        7. INCOMPLETE_ASSESSMENT
        8. MULTIPLE_URGENCIES
    """
    now = reference_now or DEFAULT_REFERENCE_NOW
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # --------------------------------------------------------------------------
    # Case 1: Normal Routine ANC
    # --------------------------------------------------------------------------
    case_normal_routine = {
        "scenario_id": "CASE_1_NORMAL_ROUTINE",
        "description": "Routine ANC checkup with normal vital signs.",
        "target_engine": "triage",
        "patient": {
            "id": str(MOCK_PATIENT_1),
            "name": "Sunita Sharma (Synthetic Demo)",
            "village": "Rampur (Synthetic)",
            "age": 24,
            "sex": "FEMALE",
        },
        "triage_input": {
            "protocol": "ANC",
            "age_years": 24.0,
            "sex": "FEMALE",
            "is_pregnant": True,
            "gestational_weeks": 28.0,
            "vitals": {
                "bp_systolic": 115.0,
                "bp_diastolic": 75.0,
                "haemoglobin": 11.2,
                "temperature_c": 36.8,
            },
            "symptoms": [],
            "danger_signs": [],
            "history": {},
        },
        "expected": {
            "disposition": "MANAGE_HERE",
            "urgency": "ROUTINE",
            "insufficient_data": False,
        },
    }

    # --------------------------------------------------------------------------
    # Case 2: Emergency Red Flag (Severe Hypertension + Headache)
    # --------------------------------------------------------------------------
    case_emergency_red_flag = {
        "scenario_id": "CASE_2_EMERGENCY_RED_FLAG",
        "description": (
            "ANC severe hypertension with severe headache indicating "
            "pre-eclampsia/eclampsia danger."
        ),
        "target_engine": "triage",
        "patient": {
            "id": str(MOCK_PATIENT_2),
            "name": "Rekha Devi (Synthetic Demo)",
            "village": "Nai Basti (Synthetic)",
            "age": 28,
            "sex": "FEMALE",
        },
        "triage_input": {
            "protocol": "ANC",
            "age_years": 28.0,
            "sex": "FEMALE",
            "is_pregnant": True,
            "gestational_weeks": 34.0,
            "vitals": {
                "bp_systolic": 165.0,
                "bp_diastolic": 110.0,
                "temperature_c": 37.0,
            },
            "symptoms": ["severe_headache"],
            "danger_signs": [],
            "history": {},
        },
        "expected": {
            "disposition": "EMERGENCY",
            "urgency": "IMMEDIATE",
            "red_flags": ["SEVERE_HYPERTENSION"],
        },
    }

    # --------------------------------------------------------------------------
    # Case 3: Urgent Referral (Stage 1 Gestational Hypertension)
    # --------------------------------------------------------------------------
    case_urgent_referral = {
        "scenario_id": "CASE_3_URGENT_REFERRAL",
        "description": "ANC stage 1 gestational hypertension requiring referral within 24h.",
        "target_engine": "triage",
        "patient": {
            "id": str(MOCK_PATIENT_3),
            "name": "Anjali Kumari (Synthetic Demo)",
            "village": "Kalyanpur (Synthetic)",
            "age": 22,
            "sex": "FEMALE",
        },
        "triage_input": {
            "protocol": "ANC",
            "age_years": 22.0,
            "sex": "FEMALE",
            "is_pregnant": True,
            "gestational_weeks": 30.0,
            "vitals": {
                "bp_systolic": 145.0,
                "bp_diastolic": 95.0,
                "temperature_c": 36.9,
            },
            "symptoms": [],
            "danger_signs": [],
            "history": {},
        },
        "expected": {
            "disposition": "REFER",
            "urgency": "WITHIN_24H",
            "red_flags": ["HYPERTENSION"],
        },
    }

    # --------------------------------------------------------------------------
    # Case 4: Approaching Due Date (Due in 4 Hours)
    # --------------------------------------------------------------------------
    case_approaching_due_date = {
        "scenario_id": "CASE_4_APPROACHING_DUE_DATE",
        "description": "Referral due in 4 hours, within the 24-hour advance lookahead window.",
        "target_engine": "reminder",
        "referral": {
            "id": UUID("00000004-0000-4000-a000-000000000001"),
            "patient_id": MOCK_PATIENT_4,
            "patient_name": "Meera Patel (Synthetic Demo)",
            "urgency": "URGENT",
            "status": "INITIATED",
            "initiated_at": now - timedelta(hours=20),
            "due_at": now + timedelta(hours=4),
            "owner_user_id": MOCK_OWNER_ASHA,
        },
        "expected": {
            "type": "UPCOMING",
            "hours_until_due": 4.0,
            "escalation_stage": 0,
        },
    }

    # --------------------------------------------------------------------------
    # Case 5: Overdue Referral (Overdue by 10 Hours)
    # --------------------------------------------------------------------------
    case_overdue_referral = {
        "scenario_id": "CASE_5_OVERDUE_REFERRAL",
        "description": "Urgent referral overdue by 10 hours requiring ASHA home visit.",
        "target_engine": "escalation",
        "referral": {
            "id": UUID("00000005-0000-4000-a000-000000000001"),
            "patient_id": MOCK_PATIENT_5,
            "patient_name": "Kavita Singh (Synthetic Demo)",
            "urgency": "URGENT",
            "status": "INITIATED",
            "initiated_at": now - timedelta(hours=34),
            "due_at": now - timedelta(hours=10),
            "now": now,
            "current_stage": 0,
            "owner_user_id": MOCK_OWNER_ASHA,
        },
        "expected": {
            "stage": 1,
            "escalate_to_role": "ASHA",
        },
    }

    # --------------------------------------------------------------------------
    # Case 6: Multi-Stage Escalation (Overdue by 50 Hours)
    # --------------------------------------------------------------------------
    case_multi_stage_escalation = {
        "scenario_id": "CASE_6_MULTI_STAGE_ESCALATION",
        "description": "Urgent referral overdue by 50 hours requiring BMO administrative takeover.",
        "target_engine": "escalation",
        "referral": {
            "id": UUID("00000006-0000-4000-a000-000000000001"),
            "patient_id": MOCK_PATIENT_6,
            "patient_name": "Priyanka Das (Synthetic Demo)",
            "urgency": "URGENT",
            "status": "INITIATED",
            "initiated_at": now - timedelta(hours=74),
            "due_at": now - timedelta(hours=50),
            "now": now,
            "current_stage": 1,
            "owner_user_id": MOCK_OWNER_ASHA,
        },
        "expected": {
            "stage": 3,
            "escalate_to_role": "BMO",
        },
    }

    # --------------------------------------------------------------------------
    # Case 7: Incomplete Assessment (Missing Blood Pressure Vitals)
    # --------------------------------------------------------------------------
    case_incomplete_assessment = {
        "scenario_id": "CASE_7_INCOMPLETE_ASSESSMENT",
        "description": (
            "ANC encounter with missing required blood pressure vitals, safely "
            "escalating upward to doctor referral."
        ),
        "target_engine": "triage",
        "patient": {
            "id": str(MOCK_PATIENT_7),
            "name": "Geeta Yadav (Synthetic Demo)",
            "village": "Shivpur (Synthetic)",
            "age": 26,
            "sex": "FEMALE",
        },
        "triage_input": {
            "protocol": "ANC",
            "age_years": 26.0,
            "sex": "FEMALE",
            "is_pregnant": True,
            "gestational_weeks": 20.0,
            "vitals": {
                "temperature_c": 36.6,
            },
            "symptoms": [],
            "danger_signs": [],
            "history": {},
        },
        "expected": {
            "disposition": "REFER",
            "urgency": "WITHIN_24H",
            "insufficient_data": True,
            "missing_fields": ["bp_systolic", "bp_diastolic"],
        },
    }

    # --------------------------------------------------------------------------
    # Case 8: Multiple Different Urgencies Portfolio
    # --------------------------------------------------------------------------
    case_multiple_urgencies = {
        "scenario_id": "CASE_8_MULTIPLE_URGENCIES",
        "description": "Portfolio of referrals spanning all five supported urgency levels.",
        "target_engine": "escalation_portfolio",
        "referrals": [
            {
                "urgency": "EMERGENCY",
                "initiated_at": now - timedelta(hours=3),
                "due_at": now - timedelta(hours=2),
                "now": now,
                "current_stage": 0,
                "owner_user_id": MOCK_OWNER_ASHA,
                "status": "INITIATED",
                "expected_stage": 3,
                "expected_role": "BMO",
            },
            {
                "urgency": "URGENT",
                "initiated_at": now - timedelta(hours=49),
                "due_at": now - timedelta(hours=25),
                "now": now,
                "current_stage": 0,
                "owner_user_id": MOCK_OWNER_ASHA,
                "status": "INITIATED",
                "expected_stage": 2,
                "expected_role": "CHO",
            },
            {
                "urgency": "PRIORITY",
                "initiated_at": now - timedelta(hours=82),
                "due_at": now - timedelta(hours=10),
                "now": now,
                "current_stage": 0,
                "owner_user_id": MOCK_OWNER_ASHA,
                "status": "INITIATED",
                "expected_stage": 1,
                "expected_role": "ASHA",
            },
            {
                "urgency": "ROUTINE",
                "initiated_at": now - timedelta(days=9),
                "due_at": now - timedelta(hours=50),
                "now": now,
                "current_stage": 0,
                "owner_user_id": MOCK_OWNER_ASHA,
                "status": "INITIATED",
                "expected_stage": 2,
                "expected_role": "CHO",
            },
            {
                "urgency": "ELECTIVE",
                "initiated_at": now - timedelta(days=35),
                "due_at": now - timedelta(hours=100),
                "now": now,
                "current_stage": 0,
                "owner_user_id": MOCK_OWNER_ASHA,
                "status": "INITIATED",
                "expected_stage": 0,
                "expected_role": None,
            },
        ],
    }

    return {
        "reference_now": now.isoformat(),
        "CASE_1_NORMAL_ROUTINE": case_normal_routine,
        "CASE_2_EMERGENCY_RED_FLAG": case_emergency_red_flag,
        "CASE_3_URGENT_REFERRAL": case_urgent_referral,
        "CASE_4_APPROACHING_DUE_DATE": case_approaching_due_date,
        "CASE_5_OVERDUE_REFERRAL": case_overdue_referral,
        "CASE_6_MULTI_STAGE_ESCALATION": case_multi_stage_escalation,
        "CASE_7_INCOMPLETE_ASSESSMENT": case_incomplete_assessment,
        "CASE_8_MULTIPLE_URGENCIES": case_multiple_urgencies,
    }
