"""FallbackTriageEngine -- a deterministic, dependency-free triage
engine. It exists so that the eventual evaluation step behind
POST /triage/ never has a hard dependency on SD's rule engine
(app/services/triage/adapter.py, factory.py): if the rule engine isn't
ready, this is what runs instead. Exact rule order, thresholds and
plain-language reasons are this step's own spec, not copied from
Day1.md (which does not define a rule engine -- see
app/services/triage/port.py's own docstring for how this seam relates
to Day1.md's pre-existing, contract-frozen POST /triage/ endpoint).

THE SAFETY RULE this whole file exists to guarantee: the fallback NEVER
returns MANAGE_HERE for an incomplete assessment, and NEVER returns
silently on missing data. Concretely: every protocol handler below
computes its normal result first; only if that result would be
MANAGE_HERE/ROUTINE (i.e. nothing else "fired") does
_escalate_if_insufficient() check whether the vitals this protocol
needs to safely conclude "nothing wrong" were actually supplied. If
they weren't, the result is overridden to REFER/WITHIN_24H with
insufficient_data=True and missing_fields populated -- uncertainty
always escalates upward, never downward. See tests/test_triage_fallback.py.

Every branch sets a plain-language `reason`: something a health worker
could read aloud to a patient. No rule IDs, no scores, no jargon.
"""
from __future__ import annotations

from app.services.triage.port import Disposition, TriageInput, TriageOutput, Urgency

VERSION = "fallback-v1.0"

_INSUFFICIENT_DATA_REASON = (
    "Not enough information to be sure. Treating this as needing a "
    "doctor's opinion."
)

# STEP 3's own table: which vitals must be present for a protocol to
# safely conclude MANAGE_HERE/ROUTINE. Protocols not listed here (TB,
# FEVER, INJURY, GENERAL) require none.
_REQUIRED_VITALS: dict[str, list[str]] = {
    "ANC": ["bp_systolic", "bp_diastolic"],
    "IMNCI": ["temperature_c", "respiratory_rate"],
    "NCD": ["bp_systolic", "bp_diastolic"],
}


def _vital(vitals: dict[str, float], key: str) -> float | None:
    return vitals.get(key)


def _result(
    disposition: Disposition,
    urgency: Urgency,
    reason: str,
    red_flags: list[str] | None = None,
) -> TriageOutput:
    return TriageOutput(
        disposition=disposition,
        urgency=urgency,
        reason=reason,
        red_flags=red_flags or [],
        protocol_version=VERSION,
    )


# ============================================================
# STEP 1 -- universal emergency, checked first, for every protocol.
# ============================================================

def _universal_emergency(data: TriageInput) -> TriageOutput | None:
    v = data.vitals
    spo2 = _vital(v, "spo2")
    pulse = _vital(v, "pulse")
    temp = _vital(v, "temperature_c")

    if spo2 is not None and spo2 < 90:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Oxygen level is dangerously low. This needs emergency care right now.",
            ["LOW_SPO2"],
        )
    if pulse is not None and (pulse > 130 or pulse < 40):
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Heart rate is dangerously abnormal. This needs emergency care right now.",
            ["ABNORMAL_PULSE"],
        )
    if temp is not None and (temp >= 39.5 or temp <= 35.0):
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Body temperature is dangerously abnormal. This needs emergency care right now.",
            ["ABNORMAL_TEMPERATURE"],
        )
    if "unconscious" in data.danger_signs:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "The patient is unconscious. This needs emergency care right now.",
            ["UNCONSCIOUS"],
        )
    return None


# ============================================================
# STEP 2 -- protocol rules.
# ============================================================

def _anc(data: TriageInput) -> TriageOutput:
    v = data.vitals
    bp_sys = _vital(v, "bp_systolic")
    bp_dia = _vital(v, "bp_diastolic")
    hb = _vital(v, "haemoglobin")
    temp = _vital(v, "temperature_c")

    if (bp_sys is not None and bp_sys >= 160) or (bp_dia is not None and bp_dia >= 110):
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Blood pressure is dangerously high. This is an emergency -- get to a hospital immediately.",
            ["SEVERE_HYPERTENSION"],
        )
    if "convulsions" in data.danger_signs:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Convulsions (fits) during pregnancy are a medical emergency. Get to a hospital immediately.",
            ["CONVULSIONS"],
        )
    if "pv_bleeding" in data.danger_signs:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Vaginal bleeding during pregnancy is a medical emergency. Get to a hospital immediately.",
            ["PV_BLEEDING"],
        )
    if hb is not None and hb < 5.0:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Blood count is dangerously low (severe anaemia). This is an emergency -- get to a hospital immediately.",
            ["SEVERE_ANAEMIA"],
        )
    if (bp_sys is not None and bp_sys >= 140) or (bp_dia is not None and bp_dia >= 90):
        return _result(
            "REFER", "WITHIN_24H",
            "Blood pressure is high. A doctor needs to see this within the next day.",
            ["HYPERTENSION"],
        )
    if "severe_headache" in data.symptoms and "blurred_vision" in data.symptoms:
        return _result(
            "REFER", "WITHIN_24H",
            "Severe headache with blurred vision can be a warning sign in pregnancy. "
            "See a doctor within the next day.",
            ["SEVERE_HEADACHE_BLURRED_VISION"],
        )
    if "reduced_fetal_movement" in data.danger_signs:
        return _result(
            "REFER", "WITHIN_24H",
            "Reduced baby movement needs a doctor's check within the next day.",
            ["REDUCED_FETAL_MOVEMENT"],
        )
    if hb is not None and hb < 7.0:
        return _result(
            "REFER", "WITHIN_72H",
            "Blood count is low (anaemia). See a doctor within the next three days.",
            ["ANAEMIA"],
        )
    if temp is not None and temp >= 38.0:
        return _result(
            "TELECONSULT", "WITHIN_24H",
            "Fever during pregnancy should be checked by a doctor soon. "
            "A teleconsultation is recommended within the next day.",
            ["FEVER"],
        )
    return _result(
        "MANAGE_HERE", "ROUTINE",
        "No concerning signs found today. Continue routine antenatal care.",
    )


def _imnci(data: TriageInput) -> TriageOutput:
    v = data.vitals
    spo2 = _vital(v, "spo2")
    rr = _vital(v, "respiratory_rate")
    muac = _vital(v, "muac_cm")
    temp = _vital(v, "temperature_c")
    age = data.age_years

    if ("convulsions" in data.danger_signs or "unable_to_feed" in data.danger_signs
            or "lethargic" in data.danger_signs):
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "This child has a danger sign that needs emergency care right now.",
            ["IMNCI_DANGER_SIGN"],
        )
    # Spec lists spo2 < 90 again here, but STEP 1's universal check
    # (same threshold) has already run for every protocol before this
    # function is ever called -- this branch is therefore unreachable
    # in practice. Kept for fidelity to the spec's own IMNCI rule list.
    if spo2 is not None and spo2 < 90:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Oxygen level is dangerously low. This needs emergency care right now.",
            ["LOW_SPO2"],
        )
    if rr is not None and age is not None and rr >= 60 and age < 0.17:
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "This baby is breathing very fast for their age. This needs emergency care right now.",
            ["FAST_BREATHING_YOUNG_INFANT"],
        )
    if rr is not None and age is not None and rr >= 50 and 0.17 <= age < 1:
        return _result(
            "REFER", "WITHIN_24H",
            "Fast breathing needs a doctor's check within the next day.",
            ["FAST_BREATHING"],
        )
    if rr is not None and age is not None and rr >= 40 and 1 <= age < 5:
        return _result(
            "REFER", "WITHIN_24H",
            "Fast breathing needs a doctor's check within the next day.",
            ["FAST_BREATHING"],
        )
    if muac is not None and muac < 11.5:
        return _result(
            "REFER", "WITHIN_72H",
            "This child is severely malnourished (low arm circumference). "
            "See a doctor within the next three days.",
            ["SEVERE_MALNUTRITION"],
        )
    if temp is not None and temp >= 38.5:
        return _result(
            "TELECONSULT", "WITHIN_24H",
            "This child has a fever. A teleconsultation is recommended within the next day.",
            ["FEVER"],
        )
    return _result(
        "MANAGE_HERE", "ROUTINE",
        "No concerning signs found today. Continue routine child care.",
    )


def _ncd(data: TriageInput) -> TriageOutput:
    v = data.vitals
    bp_sys = _vital(v, "bp_systolic")
    bp_dia = _vital(v, "bp_diastolic")
    glucose = _vital(v, "blood_glucose")

    if (bp_sys is not None and bp_sys >= 180) or (bp_dia is not None and bp_dia >= 120):
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Blood pressure is extremely high. This is an emergency -- get to a hospital immediately.",
            ["HYPERTENSIVE_CRISIS"],
        )
    if glucose is not None and (glucose > 400 or glucose < 54):
        return _result(
            "EMERGENCY", "IMMEDIATE",
            "Blood sugar is at a dangerous level. This is an emergency -- get to a hospital immediately.",
            ["BLOOD_GLUCOSE_CRISIS"],
        )
    if (bp_sys is not None and bp_sys >= 160) or (bp_dia is not None and bp_dia >= 100):
        return _result(
            "REFER", "WITHIN_72H",
            "Blood pressure is very high. See a doctor within the next three days.",
            ["SEVERE_HYPERTENSION"],
        )
    if (bp_sys is not None and bp_sys >= 140) or (bp_dia is not None and bp_dia >= 90):
        return _result(
            "TELECONSULT", "WITHIN_7D",
            "Blood pressure is high. A teleconsultation is recommended within the next week.",
            ["HYPERTENSION"],
        )
    return _result(
        "MANAGE_HERE", "ROUTINE",
        "No concerning signs found today. Continue routine care.",
    )


def _default_protocol(data: TriageInput) -> TriageOutput:
    """TB, FEVER, INJURY, GENERAL: after Step 1 (already checked before
    this is called), any reported danger sign escalates to REFER;
    otherwise routine."""
    if data.danger_signs:
        return _result(
            "REFER", "WITHIN_24H",
            "A danger sign was reported. See a doctor within the next day.",
            list(data.danger_signs),
        )
    return _result(
        "MANAGE_HERE", "ROUTINE",
        "No concerning signs found today. Continue routine care.",
    )


_PROTOCOL_HANDLERS = {
    "ANC": _anc,
    "IMNCI": _imnci,
    "NCD": _ncd,
    "TB": _default_protocol,
    "FEVER": _default_protocol,
    "INJURY": _default_protocol,
    "GENERAL": _default_protocol,
}


# ============================================================
# STEP 3 -- insufficient data. Only reached when the protocol handler
# fell all the way through to its own MANAGE_HERE/ROUTINE branch --
# every other branch already "fired" and is returned untouched.
# ============================================================

def _escalate_if_insufficient(data: TriageInput, result: TriageOutput) -> TriageOutput:
    if result.disposition != "MANAGE_HERE":
        return result

    required = _REQUIRED_VITALS.get(data.protocol, [])
    missing = [key for key in required if _vital(data.vitals, key) is None]
    if not missing:
        return result

    return TriageOutput(
        disposition="REFER",
        urgency="WITHIN_24H",
        reason=_INSUFFICIENT_DATA_REASON,
        red_flags=[],
        protocol_version=VERSION,
        insufficient_data=True,
        missing_fields=missing,
    )


class FallbackTriageEngine:
    """Deterministic, dependency-free triage engine: no import of SD's
    rule engine, no network call, no database session. Always
    available. See module docstring for the safety rule this exists to
    guarantee."""

    name = "fallback"

    def evaluate(self, data: TriageInput) -> TriageOutput:
        emergency = _universal_emergency(data)
        if emergency is not None:
            return emergency

        handler = _PROTOCOL_HANDLERS[data.protocol]
        result = handler(data)
        return _escalate_if_insufficient(data, result)
