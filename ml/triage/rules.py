"""Deterministic triage rule engine for SETU-Swasthya.

SD stream component: provides evaluate_triage() for clinical red-flag
detection and initial disposition assessment.

Safety invariants:
1. Purity: purely deterministic function, no I/O, no network calls,
   no database access, no randomness, no ML model dependencies.
2. Incomplete assessment safety: never silently returns MANAGE_HERE
   when protocol-mandated required vitals are absent.
3. Rule precedence: emergency criteria take precedence over lower-urgency
   findings and missing-data checks.
4. Plain language: every disposition reason is an explanatory,
   patient-facing plain language sentence without bare rule codes.

Note on Clinical Validation:
Clinical rule thresholds in this module (including Annexure A obstetric
red flags) are illustrative for demo/testing workflows and require formal
clinical governance approval before use in real patient care.
"""
from __future__ import annotations

from typing import Any

VERSION = "rules-v1.0"

_INSUFFICIENT_DATA_REASON = (
    "Not enough information to be sure. Treating this as needing a "
    "doctor's opinion."
)

_REQUIRED_VITALS: dict[str, list[str]] = {
    "ANC": ["bp_systolic", "bp_diastolic"],
    "IMNCI": ["temperature_c", "respiratory_rate"],
    "NCD": ["bp_systolic", "bp_diastolic"],
}


def _get_vital(vitals: dict[str, Any], *aliases: str) -> float | None:
    for key in aliases:
        if key in vitals and vitals[key] is not None:
            val = vitals[key]
            if isinstance(val, (int, float)):
                return float(val)
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def _make_result(
    disposition: str,
    urgency: str,
    reason: str,
    red_flags: list[str] | None = None,
    insufficient_data: bool = False,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "urgency": urgency,
        "reason": reason,
        "red_flags": red_flags or [],
        "protocol_version": VERSION,
        "insufficient_data": insufficient_data,
        "missing_fields": missing_fields or [],
    }


def _check_universal_emergencies(
    vitals: dict[str, Any],
    danger_signs: set[str],
) -> dict[str, Any] | None:
    spo2 = _get_vital(vitals, "spo2", "oxygen_saturation")
    pulse = _get_vital(vitals, "pulse", "heart_rate")
    temp = _get_vital(vitals, "temperature_c", "temperature", "temp")

    if spo2 is not None and spo2 < 90.0:
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Oxygen level is dangerously low. Emergency medical care is required immediately.",
            ["LOW_SPO2"],
        )

    if pulse is not None and (pulse > 130.0 or pulse < 40.0):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Heart rate is dangerously abnormal. Emergency medical care is required immediately.",
            ["ABNORMAL_PULSE"],
        )

    if temp is not None and (temp >= 39.5 or temp <= 35.0):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Body temperature is critically abnormal. Immediate emergency medical evaluation is needed.",
            ["ABNORMAL_TEMPERATURE"],
        )

    if "unconscious" in danger_signs:
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "The patient is unconscious or unresponsive. Immediate emergency care is required.",
            ["UNCONSCIOUS"],
        )

    return None


def _evaluate_anc(
    vitals: dict[str, Any],
    symptoms: set[str],
    danger_signs: set[str],
    history: dict[str, bool],
    gestational_weeks: float | None,
) -> dict[str, Any]:
    bp_sys = _get_vital(vitals, "bp_systolic", "systolic_bp", "systolic")
    bp_dia = _get_vital(vitals, "bp_diastolic", "diastolic_bp", "diastolic")
    hb = _get_vital(vitals, "haemoglobin", "hb")
    temp = _get_vital(vitals, "temperature_c", "temperature", "temp")

    has_proteinuria = (
        bool(vitals.get("proteinuria"))
        or "proteinuria" in symptoms
        or "proteinuria" in danger_signs
    )

    # 1. Severe Hypertension (Emergency)
    if (bp_sys is not None and bp_sys >= 160.0) or (bp_dia is not None and bp_dia >= 110.0):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Blood pressure is dangerously high in pregnancy. Hospital admission is required immediately.",
            ["SEVERE_HYPERTENSION"],
        )

    # 2. Convulsions (Emergency)
    if "convulsions" in danger_signs or "convulsions" in symptoms or vitals.get("convulsions_or_loc"):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Convulsions during pregnancy indicate a life-threatening emergency. Hospital transfer is needed immediately.",
            ["CONVULSIONS"],
        )

    # 3. Severe headache + visual disturbance (Emergency)
    has_severe_headache = "severe_headache" in symptoms or "severe_headache" in danger_signs
    has_visual_disturb = (
        "visual_disturbance" in symptoms
        or "visual_disturbance" in danger_signs
        or "blurred_vision" in symptoms
        or "blurred_vision" in danger_signs
    )
    if has_severe_headache and has_visual_disturb:
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Severe headache combined with visual disturbance is an ominous danger sign in pregnancy. Immediate emergency evaluation is required.",
            ["SEVERE_HEADACHE_VISUAL_DISTURBANCE"],
        )

    # 4. PV bleeding (Emergency)
    if (
        "pv_bleeding" in danger_signs
        or "pv_bleeding" in symptoms
        or "bleeding_pv" in danger_signs
        or "bleeding_pv" in symptoms
        or vitals.get("bleeding_pv_pad_under_5min")
    ):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Vaginal bleeding during pregnancy is a medical emergency requiring immediate hospital care.",
            ["PV_BLEEDING"],
        )

    # 5. Severe anaemia (Emergency)
    if hb is not None and hb < 5.0:
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Blood count is dangerously low (severe anaemia). Immediate hospital emergency care is needed.",
            ["SEVERE_ANAEMIA"],
        )

    # 6. Preterm labour (< 37 weeks) (Emergency)
    is_preterm = gestational_weeks is not None and gestational_weeks < 37.0
    has_labour_signs = (
        "labour" in symptoms
        or "labour" in danger_signs
        or "labor" in symptoms
        or "labor" in danger_signs
        or "contractions" in symptoms
        or "contractions" in danger_signs
        or "preterm_labour" in symptoms
        or "preterm_labour" in danger_signs
    )
    if is_preterm and has_labour_signs:
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Signs of active labour before 37 weeks indicate preterm labour. Immediate emergency hospital transfer is required.",
            ["PRETERM_LABOUR"],
        )

    # 7. Moderate Hypertension (Referral within 24h)
    if (bp_sys is not None and bp_sys >= 140.0) or (bp_dia is not None and bp_dia >= 90.0):
        red_flags = ["HYPERTENSION"]
        if has_proteinuria:
            red_flags.append("PROTEINURIA")
        return _make_result(
            "REFER",
            "WITHIN_24H",
            "Blood pressure is elevated in pregnancy. A doctor evaluation is needed within 24 hours.",
            red_flags,
        )

    # 8. Reduced fetal movement (Referral within 24h)
    if "reduced_fetal_movement" in danger_signs or "reduced_fetal_movement" in symptoms:
        return _make_result(
            "REFER",
            "WITHIN_24H",
            "Reduced baby movement requires clinical evaluation and monitoring within 24 hours.",
            ["REDUCED_FETAL_MOVEMENT"],
        )

    # 9. Fever (>= 38 C)
    if temp is not None and temp >= 38.0:
        has_foul_discharge = "foul_discharge" in symptoms or "foul_discharge" in danger_signs
        if has_foul_discharge:
            return _make_result(
                "REFER",
                "WITHIN_24H",
                "Fever accompanied by foul discharge indicates possible maternal infection. Medical examination is needed within 24 hours.",
                ["FEVER_WITH_FOUL_DISCHARGE"],
            )
        return _make_result(
            "TELECONSULT",
            "WITHIN_24H",
            "Fever during pregnancy should be reviewed promptly. Teleconsultation is recommended within 24 hours.",
            ["FEVER"],
        )

    # 10. Anaemia (< 7.0 g/dL) (Referral within 72h)
    if hb is not None and hb < 7.0:
        return _make_result(
            "REFER",
            "WITHIN_72H",
            "Low haemoglobin level indicates significant anaemia requiring clinical assessment and treatment within 3 days.",
            ["ANAEMIA"],
        )

    # 11. Malpresentation at term (>= 37 weeks) (Referral within 7d)
    is_at_term = gestational_weeks is not None and gestational_weeks >= 37.0
    has_malpresentation = (
        "malpresentation" in symptoms
        or "malpresentation" in danger_signs
        or "breech" in symptoms
        or "breech" in danger_signs
        or history.get("malpresentation", False)
        or history.get("breech", False)
    )
    if is_at_term and has_malpresentation:
        return _make_result(
            "REFER",
            "WITHIN_7D",
            "Fetal malpresentation at term requires specialist obstetric evaluation within a week for delivery planning.",
            ["MALPRESENTATION_AT_TERM"],
        )

    return _make_result(
        "MANAGE_HERE",
        "ROUTINE",
        "No concerning signs found today. Continue routine antenatal care.",
    )


def _evaluate_imnci(
    vitals: dict[str, Any],
    danger_signs: set[str],
    age_years: float | None,
) -> dict[str, Any]:
    rr = _get_vital(vitals, "respiratory_rate", "rr")
    muac = _get_vital(vitals, "muac_cm", "muac")
    temp = _get_vital(vitals, "temperature_c", "temperature", "temp")

    if (
        "convulsions" in danger_signs
        or "unable_to_feed" in danger_signs
        or "lethargic" in danger_signs
    ):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "The child exhibits a general danger sign requiring emergency hospital care right now.",
            ["IMNCI_DANGER_SIGN"],
        )

    # Young infant fast breathing (< 2 months / 0.17 years)
    if age_years is not None and age_years < 0.17 and rr is not None and rr >= 60.0:
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Rapid breathing in a young infant indicates high risk of severe illness. Emergency hospital care is needed right away.",
            ["FAST_BREATHING_YOUNG_INFANT"],
        )

    # Infant fast breathing (2 to 12 months)
    if age_years is not None and 0.17 <= age_years < 1.0 and rr is not None and rr >= 50.0:
        return _make_result(
            "REFER",
            "WITHIN_24H",
            "Fast breathing in this infant requires medical review within 24 hours.",
            ["FAST_BREATHING"],
        )

    # Child fast breathing (1 to 5 years)
    if age_years is not None and 1.0 <= age_years < 5.0 and rr is not None and rr >= 40.0:
        return _make_result(
            "REFER",
            "WITHIN_24H",
            "Fast breathing in this child requires medical review within 24 hours.",
            ["FAST_BREATHING"],
        )

    if muac is not None and muac < 11.5:
        return _make_result(
            "REFER",
            "WITHIN_72H",
            "Arm circumference indicates severe acute malnutrition. Referral for nutritional management is needed within 3 days.",
            ["SEVERE_MALNUTRITION"],
        )

    if temp is not None and temp >= 38.5:
        return _make_result(
            "TELECONSULT",
            "WITHIN_24H",
            "The child has high fever. Teleconsultation with a medical officer is recommended within 24 hours.",
            ["FEVER"],
        )

    return _make_result(
        "MANAGE_HERE",
        "ROUTINE",
        "No concerning signs found today. Continue routine child care.",
    )


def _evaluate_ncd(vitals: dict[str, Any]) -> dict[str, Any]:
    bp_sys = _get_vital(vitals, "bp_systolic", "systolic_bp", "systolic")
    bp_dia = _get_vital(vitals, "bp_diastolic", "diastolic_bp", "diastolic")
    glucose = _get_vital(vitals, "blood_glucose", "glucose")

    if (bp_sys is not None and bp_sys >= 180.0) or (bp_dia is not None and bp_dia >= 120.0):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Blood pressure is dangerously high (hypertensive crisis). Immediate emergency medical attention is needed.",
            ["HYPERTENSIVE_CRISIS"],
        )

    if glucose is not None and (glucose > 400.0 or glucose < 54.0):
        return _make_result(
            "EMERGENCY",
            "IMMEDIATE",
            "Blood sugar level is at a critical crisis value. Immediate emergency care is needed.",
            ["BLOOD_GLUCOSE_CRISIS"],
        )

    if (bp_sys is not None and bp_sys >= 160.0) or (bp_dia is not None and bp_dia >= 100.0):
        return _make_result(
            "REFER",
            "WITHIN_72H",
            "Blood pressure is very high and needs clinical evaluation and treatment adjustment within 3 days.",
            ["SEVERE_HYPERTENSION"],
        )

    if (bp_sys is not None and bp_sys >= 140.0) or (bp_dia is not None and bp_dia >= 90.0):
        return _make_result(
            "TELECONSULT",
            "WITHIN_7D",
            "Blood pressure is elevated above target. A teleconsultation is advised within the week.",
            ["HYPERTENSION"],
        )

    return _make_result(
        "MANAGE_HERE",
        "ROUTINE",
        "No concerning signs found today. Continue routine care.",
    )


def _evaluate_default_protocol(danger_signs: set[str]) -> dict[str, Any]:
    if danger_signs:
        return _make_result(
            "REFER",
            "WITHIN_24H",
            "A clinical danger sign was reported. Doctor examination is required within 24 hours.",
            sorted(danger_signs),
        )

    return _make_result(
        "MANAGE_HERE",
        "ROUTINE",
        "No concerning signs found today. Continue routine care.",
    )


def _escalate_if_incomplete(
    protocol: str,
    vitals: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    # Only escalate when no actual finding fired (i.e. currently MANAGE_HERE).
    # Real emergency, referral, or teleconsult findings are never downgraded.
    if result["disposition"] != "MANAGE_HERE":
        return result

    required = _REQUIRED_VITALS.get(protocol, [])
    missing = [field for field in required if _get_vital(vitals, field) is None]

    if not missing:
        return result

    return _make_result(
        disposition="REFER",
        urgency="WITHIN_24H",
        reason=_INSUFFICIENT_DATA_REASON,
        red_flags=[],
        insufficient_data=True,
        missing_fields=missing,
    )


def evaluate_triage(data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Evaluates triage observations deterministically.

    Accepts either:
    1. Full encounter payload (dict containing protocol, vitals, symptoms, etc.)
    2. Bare vitals dictionary (with optional protocol/symptoms in kwargs)
    """
    payload: dict[str, Any] = {}
    if isinstance(data, dict):
        payload.update(data)
    if kwargs:
        payload.update(kwargs)

    # Normalize protocol
    raw_protocol = payload.get("protocol", "GENERAL")
    protocol = str(raw_protocol).strip().upper() if raw_protocol else "GENERAL"

    # Normalize vitals dictionary
    raw_vitals = payload.get("vitals")
    if isinstance(raw_vitals, dict):
        vitals = dict(raw_vitals)
    else:
        # Caller provided bare vitals directly in the payload
        vitals = {k: v for k, v in payload.items() if isinstance(v, (int, float))}

    # Normalize symptoms and danger signs to lowercase strings
    raw_symptoms = payload.get("symptoms", [])
    symptoms = {
        str(s).strip().lower()
        for s in (raw_symptoms if isinstance(raw_symptoms, (list, set, tuple)) else [])
    }

    raw_danger_signs = payload.get("danger_signs", [])
    danger_signs = {
        str(d).strip().lower()
        for d in (raw_danger_signs if isinstance(raw_danger_signs, (list, set, tuple)) else [])
    }

    raw_history = payload.get("history", {})
    history = dict(raw_history) if isinstance(raw_history, dict) else {}

    raw_age = payload.get("age_years")
    age_years = float(raw_age) if raw_age is not None else None

    raw_weeks = payload.get("gestational_weeks")
    gestational_weeks = float(raw_weeks) if raw_weeks is not None else None

    # Step 1: Universal emergency check across all protocols
    universal_emergency = _check_universal_emergencies(vitals, danger_signs)
    if universal_emergency is not None:
        return universal_emergency

    # Step 2: Protocol-specific clinical rules
    if protocol == "ANC":
        result = _evaluate_anc(vitals, symptoms, danger_signs, history, gestational_weeks)
    elif protocol == "IMNCI":
        result = _evaluate_imnci(vitals, danger_signs, age_years)
    elif protocol == "NCD":
        result = _evaluate_ncd(vitals)
    else:
        result = _evaluate_default_protocol(danger_signs)

    # Step 3: Insufficient data check for required vitals
    return _escalate_if_incomplete(protocol, vitals, result)
