"""Unit tests for ml/triage/rules.py -- SD-owned deterministic triage engine.

Pure unit tests: no database, no network calls, no app startup. rules.py
itself moved from backend/app/services/triage/ to ml/triage/ as part of
the ml/ integration (consolidating devansh-ml and sd-triage-automation)
-- see ml/README.md. The engine's consumers (adapter/factory/port) stay
in backend/, imported below at their original app.services.triage.*
paths; this file's own conftest.py puts backend/ on sys.path so those
still resolve when this test is run from ml/tests/.
"""
from __future__ import annotations

import inspect
from typing import get_args

from app.services.triage.adapter import RuleEngineAdapter
from app.services.triage.factory import _probe_readiness
from app.services.triage.port import Disposition, TriageInput, TriageOutput, Urgency
from ml.triage import rules
from ml.triage.rules import VERSION, evaluate_triage

_DISPOSITIONS = set(get_args(Disposition))
_URGENCIES = set(get_args(Urgency))


# ============================================================
# 1. Module & Interface Verification
# ============================================================

def test_module_imports_and_version():
    assert isinstance(VERSION, str)
    assert len(VERSION) > 0
    assert VERSION == "rules-v1.0"


def test_evaluate_triage_is_callable():
    assert callable(evaluate_triage)


def test_output_contains_all_required_fields():
    res = evaluate_triage({"protocol": "GENERAL"})
    assert isinstance(res, dict)
    required_keys = {
        "disposition",
        "urgency",
        "reason",
        "red_flags",
        "protocol_version",
        "insufficient_data",
        "missing_fields",
    }
    assert required_keys.issubset(res.keys())


def test_disposition_values_in_allowed_set():
    cases = [
        {"protocol": "GENERAL"},
        {"protocol": "ANC", "vitals": {"bp_systolic": 110, "bp_diastolic": 70}},
        {"protocol": "ANC", "vitals": {"bp_systolic": 165, "bp_diastolic": 115}},
        {"protocol": "ANC", "vitals": {}},
    ]
    for case in cases:
        out = evaluate_triage(case)
        assert out["disposition"] in _DISPOSITIONS


def test_urgency_values_in_allowed_set():
    cases = [
        {"protocol": "GENERAL"},
        {"protocol": "ANC", "vitals": {"bp_systolic": 110, "bp_diastolic": 70}},
        {"protocol": "ANC", "vitals": {"bp_systolic": 165, "bp_diastolic": 115}},
        {"protocol": "NCD", "vitals": {"bp_systolic": 145, "bp_diastolic": 92}},
    ]
    for case in cases:
        out = evaluate_triage(case)
        assert out["urgency"] in _URGENCIES


def test_protocol_version_non_empty_string():
    out = evaluate_triage({"protocol": "GENERAL"})
    assert isinstance(out["protocol_version"], str)
    assert len(out["protocol_version"]) > 0


def test_adapter_compatibility():
    adapter = RuleEngineAdapter()
    sample = TriageInput(protocol="GENERAL")
    res = adapter.evaluate(sample)
    assert isinstance(res, TriageOutput)
    assert res.disposition == "MANAGE_HERE"
    assert res.urgency == "ROUTINE"
    assert res.protocol_version == VERSION


def test_factory_readiness_probe_passes():
    ready, reason = _probe_readiness()
    assert ready is True
    assert reason is None


def test_purity_no_forbidden_source_tokens():
    source = inspect.getsource(rules).lower()
    for forbidden in ("session", "httpx", "requests", "open("):
        assert forbidden not in source, f"Forbidden token {forbidden!r} found in rules.py"


# ============================================================
# 2. Annexure A Obstetric Red-Flag Reference (ANC Protocol)
# ============================================================

def test_anc_severe_systolic_bp_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 165, "bp_diastolic": 95},
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "SEVERE_HYPERTENSION" in out["red_flags"]


def test_anc_severe_diastolic_bp_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 135, "bp_diastolic": 115},
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "SEVERE_HYPERTENSION" in out["red_flags"]


def test_anc_convulsions_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70},
        "danger_signs": ["convulsions"],
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "CONVULSIONS" in out["red_flags"]


def test_anc_severe_headache_and_visual_disturbance_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 120, "bp_diastolic": 80},
        "symptoms": ["severe_headache", "visual_disturbance"],
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "SEVERE_HEADACHE_VISUAL_DISTURBANCE" in out["red_flags"]


def test_anc_severe_headache_and_blurred_vision_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 120, "bp_diastolic": 80},
        "symptoms": ["severe_headache", "blurred_vision"],
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "SEVERE_HEADACHE_VISUAL_DISTURBANCE" in out["red_flags"]


def test_anc_pv_bleeding_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70},
        "danger_signs": ["pv_bleeding"],
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "PV_BLEEDING" in out["red_flags"]


def test_anc_severe_anaemia_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70, "haemoglobin": 4.5},
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "SEVERE_ANAEMIA" in out["red_flags"]


def test_anc_preterm_labour_is_emergency():
    out = evaluate_triage({
        "protocol": "ANC",
        "gestational_weeks": 32.0,
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70},
        "symptoms": ["contractions"],
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "PRETERM_LABOUR" in out["red_flags"]


def test_anc_moderate_hypertension_is_refer_within_24h():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 145, "bp_diastolic": 85},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert "HYPERTENSION" in out["red_flags"]


def test_anc_reduced_fetal_movement_is_refer_within_24h():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70},
        "danger_signs": ["reduced_fetal_movement"],
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert "REDUCED_FETAL_MOVEMENT" in out["red_flags"]


def test_anc_fever_with_foul_discharge_is_refer_within_24h():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70, "temperature_c": 38.4},
        "symptoms": ["foul_discharge"],
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert "FEVER_WITH_FOUL_DISCHARGE" in out["red_flags"]


def test_anc_fever_without_foul_discharge_is_teleconsult():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70, "temperature_c": 38.3},
    })
    assert out["disposition"] == "TELECONSULT"
    assert out["urgency"] == "WITHIN_24H"
    assert "FEVER" in out["red_flags"]


def test_anc_moderate_anaemia_is_refer_within_72h():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70, "haemoglobin": 6.2},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_72H"
    assert "ANAEMIA" in out["red_flags"]


def test_anc_malpresentation_at_term_is_refer_within_7d():
    out = evaluate_triage({
        "protocol": "ANC",
        "gestational_weeks": 38.5,
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70},
        "history": {"breech": True},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_7D"
    assert "MALPRESENTATION_AT_TERM" in out["red_flags"]


def test_anc_normal_findings_returns_manage_here():
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 115, "bp_diastolic": 75},
    })
    assert out["disposition"] == "MANAGE_HERE"
    assert out["urgency"] == "ROUTINE"
    assert out["insufficient_data"] is False
    assert out["missing_fields"] == []


# ============================================================
# 3. Universal Emergency Checks & Precedence
# ============================================================

def test_universal_emergency_low_spo2():
    for proto in ("ANC", "IMNCI", "NCD", "GENERAL"):
        out = evaluate_triage({"protocol": proto, "vitals": {"spo2": 86}})
        assert out["disposition"] == "EMERGENCY"
        assert out["urgency"] == "IMMEDIATE"
        assert "LOW_SPO2" in out["red_flags"]


def test_universal_emergency_abnormal_pulse():
    out_high = evaluate_triage({"protocol": "GENERAL", "vitals": {"pulse": 138}})
    assert out_high["disposition"] == "EMERGENCY"
    assert out_high["urgency"] == "IMMEDIATE"

    out_low = evaluate_triage({"protocol": "GENERAL", "vitals": {"pulse": 38}})
    assert out_low["disposition"] == "EMERGENCY"
    assert out_low["urgency"] == "IMMEDIATE"


def test_universal_emergency_abnormal_temperature():
    out_high = evaluate_triage({"protocol": "GENERAL", "vitals": {"temperature_c": 40.1}})
    assert out_high["disposition"] == "EMERGENCY"
    assert out_high["urgency"] == "IMMEDIATE"

    out_low = evaluate_triage({"protocol": "GENERAL", "vitals": {"temperature_c": 34.2}})
    assert out_low["disposition"] == "EMERGENCY"
    assert out_low["urgency"] == "IMMEDIATE"


def test_universal_emergency_unconscious():
    out = evaluate_triage({"protocol": "GENERAL", "danger_signs": ["unconscious"]})
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "UNCONSCIOUS" in out["red_flags"]


def test_emergency_precedence_over_lower_severity():
    # Patient with fever (teleconsult) + low SpO2 (emergency) -> emergency wins
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {
            "bp_systolic": 110,
            "bp_diastolic": 70,
            "temperature_c": 38.3,
            "spo2": 85,
        },
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"


def test_emergency_precedence_over_missing_required_data():
    # Severe hypertension is an emergency even if diastolic is absent
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 175},
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert out["insufficient_data"] is False


def test_rule_finding_not_downgraded_by_missing_data():
    # Moderate hypertension (referral) is not replaced by insufficient data
    out = evaluate_triage({
        "protocol": "ANC",
        "vitals": {"bp_systolic": 150},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert "HYPERTENSION" in out["red_flags"]


# ============================================================
# 4. Incomplete Data Safety (The Safety Invariant)
# ============================================================

def test_anc_missing_all_required_vitals_escalates_to_refer():
    out = evaluate_triage({"protocol": "ANC", "vitals": {}})
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert out["insufficient_data"] is True
    assert set(out["missing_fields"]) == {"bp_systolic", "bp_diastolic"}
    assert out["reason"] == (
        "Not enough information to be sure. Treating this as needing a "
        "doctor's opinion."
    )


def test_anc_partially_missing_vitals_escalates():
    out = evaluate_triage({"protocol": "ANC", "vitals": {"bp_systolic": 115}})
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert out["insufficient_data"] is True
    assert out["missing_fields"] == ["bp_diastolic"]


def test_imnci_missing_required_vitals_escalates():
    out = evaluate_triage({"protocol": "IMNCI", "age_years": 2.0, "vitals": {}})
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert out["insufficient_data"] is True
    assert set(out["missing_fields"]) == {"temperature_c", "respiratory_rate"}


def test_ncd_missing_required_vitals_escalates():
    out = evaluate_triage({"protocol": "NCD", "vitals": {}})
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"
    assert out["insufficient_data"] is True
    assert set(out["missing_fields"]) == {"bp_systolic", "bp_diastolic"}


def test_protocols_without_required_vitals_do_not_escalate_for_missing_data():
    for proto in ("TB", "FEVER", "INJURY", "GENERAL"):
        out = evaluate_triage({"protocol": proto, "vitals": {}})
        assert out["disposition"] == "MANAGE_HERE"
        assert out["urgency"] == "ROUTINE"
        assert out["insufficient_data"] is False


def test_missing_data_never_silently_returns_manage_here():
    for proto, req in (
        ("ANC", ["bp_systolic", "bp_diastolic"]),
        ("IMNCI", ["temperature_c", "respiratory_rate"]),
        ("NCD", ["bp_systolic", "bp_diastolic"]),
    ):
        out = evaluate_triage({"protocol": proto, "vitals": {}})
        assert out["disposition"] != "MANAGE_HERE", proto
        assert out["insufficient_data"] is True
        assert set(out["missing_fields"]) == set(req)


# ============================================================
# 5. Determinism & Purity
# ============================================================

def test_deterministic_behaviour():
    payload = {
        "protocol": "ANC",
        "vitals": {"bp_systolic": 142, "bp_diastolic": 92},
        "symptoms": ["severe_headache"],
    }
    first = evaluate_triage(payload)
    for _ in range(5):
        assert evaluate_triage(payload) == first


# ============================================================
# 6. Plain-Language Reasons
# ============================================================

def test_plain_language_reasons_non_empty_and_no_bare_rule_ids():
    cases = [
        {"protocol": "GENERAL"},
        {"protocol": "GENERAL", "vitals": {"spo2": 82}},
        {"protocol": "ANC", "vitals": {"bp_systolic": 115, "bp_diastolic": 75}},
        {"protocol": "ANC", "vitals": {"bp_systolic": 165, "bp_diastolic": 105}},
        {"protocol": "ANC", "vitals": {}},
        {"protocol": "IMNCI", "age_years": 2.0, "vitals": {"temperature_c": 37.0, "respiratory_rate": 30}},
        {"protocol": "NCD", "vitals": {"bp_systolic": 110, "bp_diastolic": 70}},
    ]
    for case in cases:
        out = evaluate_triage(case)
        reason = out["reason"]
        assert isinstance(reason, str)
        assert len(reason.strip()) > 0
        assert not reason.strip().upper().startswith("R1")
        assert not reason.strip().upper().startswith("RULE_")


# ============================================================
# 7. Other Protocols (IMNCI & NCD)
# ============================================================

def test_imnci_general_danger_signs_are_emergency():
    for sign in ("convulsions", "unable_to_feed", "lethargic"):
        out = evaluate_triage({
            "protocol": "IMNCI",
            "age_years": 2.0,
            "vitals": {"temperature_c": 37.0, "respiratory_rate": 30},
            "danger_signs": [sign],
        })
        assert out["disposition"] == "EMERGENCY"
        assert out["urgency"] == "IMMEDIATE"


def test_imnci_young_infant_fast_breathing_is_emergency():
    out = evaluate_triage({
        "protocol": "IMNCI",
        "age_years": 0.1,
        "vitals": {"temperature_c": 37.0, "respiratory_rate": 65},
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"


def test_imnci_infant_fast_breathing_is_refer_within_24h():
    out = evaluate_triage({
        "protocol": "IMNCI",
        "age_years": 0.5,
        "vitals": {"temperature_c": 37.0, "respiratory_rate": 55},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"


def test_imnci_child_fast_breathing_is_refer_within_24h():
    out = evaluate_triage({
        "protocol": "IMNCI",
        "age_years": 3.0,
        "vitals": {"temperature_c": 37.0, "respiratory_rate": 45},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_24H"


def test_imnci_severe_malnutrition_is_refer_within_72h():
    out = evaluate_triage({
        "protocol": "IMNCI",
        "age_years": 2.0,
        "vitals": {"temperature_c": 37.0, "respiratory_rate": 30, "muac_cm": 11.0},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_72H"


def test_imnci_child_fever_is_teleconsult():
    out = evaluate_triage({
        "protocol": "IMNCI",
        "age_years": 2.0,
        "vitals": {"temperature_c": 38.9, "respiratory_rate": 30},
    })
    assert out["disposition"] == "TELECONSULT"
    assert out["urgency"] == "WITHIN_24H"


def test_ncd_hypertensive_crisis_is_emergency():
    out = evaluate_triage({
        "protocol": "NCD",
        "vitals": {"bp_systolic": 185, "bp_diastolic": 90},
    })
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"


def test_ncd_glucose_crisis_is_emergency():
    out_high = evaluate_triage({
        "protocol": "NCD",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70, "blood_glucose": 450},
    })
    assert out_high["disposition"] == "EMERGENCY"
    assert out_high["urgency"] == "IMMEDIATE"

    out_low = evaluate_triage({
        "protocol": "NCD",
        "vitals": {"bp_systolic": 110, "bp_diastolic": 70, "blood_glucose": 45},
    })
    assert out_low["disposition"] == "EMERGENCY"
    assert out_low["urgency"] == "IMMEDIATE"


def test_ncd_severe_hypertension_is_refer_within_72h():
    out = evaluate_triage({
        "protocol": "NCD",
        "vitals": {"bp_systolic": 165, "bp_diastolic": 95},
    })
    assert out["disposition"] == "REFER"
    assert out["urgency"] == "WITHIN_72H"


def test_ncd_moderate_hypertension_is_teleconsult_within_7d():
    out = evaluate_triage({
        "protocol": "NCD",
        "vitals": {"bp_systolic": 145, "bp_diastolic": 85},
    })
    assert out["disposition"] == "TELECONSULT"
    assert out["urgency"] == "WITHIN_7D"


def test_bare_vitals_dict_without_protocol_defaults_to_general():
    out = evaluate_triage({"spo2": 85})
    assert out["disposition"] == "EMERGENCY"
    assert out["urgency"] == "IMMEDIATE"
    assert "LOW_SPO2" in out["red_flags"]
