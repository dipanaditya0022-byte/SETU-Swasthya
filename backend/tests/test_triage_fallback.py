"""Tests for app/services/triage/fallback.py -- FallbackTriageEngine.

Pure unit tests: no database, no app startup, no fixtures with real
credentials. (Note: this repo's tests/conftest.py runs an autouse,
session-scoped fixture that creates/migrates a throwaway test database
regardless of what an individual test needs -- see conftest.py's own
docstring -- so a running Postgres is still required to *collect* this
file, even though none of these tests touch a session.)

Exercises, in this order: STEP 1 universal emergency triggers, each
protocol's own emergency/refer/teleconsult/manage_here paths, and --
the actual safety property this engine exists to guarantee -- that
insufficient data always escalates to REFER and is never silently
treated as MANAGE_HERE, for every protocol that has required vitals
(ANC, IMNCI, NCD).
"""
from app.services.triage.fallback import VERSION, FallbackTriageEngine
from app.services.triage.port import TriageInput

engine = FallbackTriageEngine()


def _eval(**kwargs) -> "TriageOutput":  # noqa: F821 -- type imported for annotation only, not needed at runtime
    return engine.evaluate(TriageInput(**kwargs))


# ============================================================
# Engine identity
# ============================================================

def test_engine_name_and_version():
    assert engine.name == "fallback"
    assert VERSION == "fallback-v1.0"


# ============================================================
# STEP 1 -- universal emergency (checked first, all protocols).
# ============================================================

def test_universal_low_spo2_is_emergency_regardless_of_protocol():
    for protocol in ("ANC", "IMNCI", "NCD", "TB", "FEVER", "INJURY", "GENERAL"):
        out = _eval(protocol=protocol, vitals={"spo2": 85})
        assert out.disposition == "EMERGENCY"
        assert out.urgency == "IMMEDIATE"
        assert "LOW_SPO2" in out.red_flags


def test_universal_high_pulse_is_emergency():
    out = _eval(protocol="GENERAL", vitals={"pulse": 140})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_universal_low_pulse_is_emergency():
    out = _eval(protocol="GENERAL", vitals={"pulse": 35})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_universal_high_temperature_is_emergency():
    out = _eval(protocol="GENERAL", vitals={"temperature_c": 39.7})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_universal_low_temperature_is_emergency():
    out = _eval(protocol="GENERAL", vitals={"temperature_c": 34.5})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_universal_unconscious_is_emergency():
    out = _eval(protocol="GENERAL", danger_signs=["unconscious"])
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_universal_emergency_short_circuits_protocol_rules():
    # A borderline-normal ANC BP would otherwise be MANAGE_HERE, but a
    # universal emergency vital must win regardless.
    out = _eval(
        protocol="ANC",
        vitals={"spo2": 80, "bp_systolic": 110, "bp_diastolic": 70},
    )
    assert out.disposition == "EMERGENCY"
    assert "LOW_SPO2" in out.red_flags


# ============================================================
# ANC
# ============================================================

def test_anc_severe_bp_is_emergency():
    out = _eval(protocol="ANC", vitals={"bp_systolic": 162, "bp_diastolic": 100})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_anc_convulsions_is_emergency():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70},
        danger_signs=["convulsions"],
    )
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_anc_pv_bleeding_is_emergency():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70},
        danger_signs=["pv_bleeding"],
    )
    assert out.disposition == "EMERGENCY"


def test_anc_severe_anaemia_is_emergency():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70, "haemoglobin": 4.2},
    )
    assert out.disposition == "EMERGENCY"


def test_anc_moderate_hypertension_is_refer_within_24h():
    out = _eval(protocol="ANC", vitals={"bp_systolic": 156, "bp_diastolic": 98})
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"


def test_anc_severe_headache_and_blurred_vision_is_refer():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70},
        symptoms=["severe_headache", "blurred_vision"],
    )
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"


def test_anc_only_one_of_headache_or_blurred_vision_does_not_refer():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70},
        symptoms=["severe_headache"],
    )
    assert out.disposition == "MANAGE_HERE"


def test_anc_reduced_fetal_movement_is_refer():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70},
        danger_signs=["reduced_fetal_movement"],
    )
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"


def test_anc_moderate_anaemia_is_refer_within_72h():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70, "haemoglobin": 6.5},
    )
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_72H"


def test_anc_fever_is_teleconsult():
    out = _eval(
        protocol="ANC",
        vitals={"bp_systolic": 110, "bp_diastolic": 70, "temperature_c": 38.2},
    )
    assert out.disposition == "TELECONSULT"
    assert out.urgency == "WITHIN_24H"


def test_anc_manage_here_when_nothing_fires_and_required_vitals_present():
    out = _eval(protocol="ANC", vitals={"bp_systolic": 110, "bp_diastolic": 70})
    assert out.disposition == "MANAGE_HERE"
    assert out.urgency == "ROUTINE"
    assert out.insufficient_data is False


# ============================================================
# IMNCI
# ============================================================

def test_imnci_danger_sign_is_emergency():
    for sign in ("convulsions", "unable_to_feed", "lethargic"):
        out = _eval(
            protocol="IMNCI",
            age_years=2,
            vitals={"temperature_c": 37.0, "respiratory_rate": 30},
            danger_signs=[sign],
        )
        assert out.disposition == "EMERGENCY", sign
        assert out.urgency == "IMMEDIATE"


def test_imnci_young_infant_fast_breathing_is_emergency():
    out = _eval(
        protocol="IMNCI", age_years=0.1,
        vitals={"temperature_c": 37.0, "respiratory_rate": 65},
    )
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_imnci_infant_fast_breathing_is_refer_within_24h():
    out = _eval(
        protocol="IMNCI", age_years=0.5,
        vitals={"temperature_c": 37.0, "respiratory_rate": 55},
    )
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"


def test_imnci_child_fast_breathing_is_refer_within_24h():
    out = _eval(
        protocol="IMNCI", age_years=3,
        vitals={"temperature_c": 37.0, "respiratory_rate": 45},
    )
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"


def test_imnci_severe_malnutrition_is_refer_within_72h():
    out = _eval(
        protocol="IMNCI", age_years=2,
        vitals={"temperature_c": 37.0, "respiratory_rate": 30, "muac_cm": 10.8},
    )
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_72H"


def test_imnci_fever_is_teleconsult():
    out = _eval(
        protocol="IMNCI", age_years=2,
        vitals={"temperature_c": 38.9, "respiratory_rate": 30},
    )
    assert out.disposition == "TELECONSULT"
    assert out.urgency == "WITHIN_24H"


def test_imnci_manage_here_when_nothing_fires_and_required_vitals_present():
    out = _eval(
        protocol="IMNCI", age_years=2,
        vitals={"temperature_c": 37.0, "respiratory_rate": 30},
    )
    assert out.disposition == "MANAGE_HERE"
    assert out.urgency == "ROUTINE"
    assert out.insufficient_data is False


# ============================================================
# NCD
# ============================================================

def test_ncd_hypertensive_crisis_is_emergency():
    out = _eval(protocol="NCD", vitals={"bp_systolic": 185, "bp_diastolic": 90})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_ncd_glucose_crisis_is_emergency():
    out = _eval(protocol="NCD", vitals={"bp_systolic": 110, "bp_diastolic": 70, "blood_glucose": 420})
    assert out.disposition == "EMERGENCY"
    assert out.urgency == "IMMEDIATE"


def test_ncd_low_glucose_is_emergency():
    out = _eval(protocol="NCD", vitals={"bp_systolic": 110, "bp_diastolic": 70, "blood_glucose": 45})
    assert out.disposition == "EMERGENCY"


def test_ncd_severe_hypertension_is_refer_within_72h():
    out = _eval(protocol="NCD", vitals={"bp_systolic": 165, "bp_diastolic": 95})
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_72H"


def test_ncd_moderate_hypertension_is_teleconsult_within_7d():
    out = _eval(protocol="NCD", vitals={"bp_systolic": 145, "bp_diastolic": 85})
    assert out.disposition == "TELECONSULT"
    assert out.urgency == "WITHIN_7D"


def test_ncd_manage_here_when_nothing_fires_and_required_vitals_present():
    out = _eval(protocol="NCD", vitals={"bp_systolic": 110, "bp_diastolic": 70})
    assert out.disposition == "MANAGE_HERE"
    assert out.urgency == "ROUTINE"
    assert out.insufficient_data is False


# ============================================================
# TB / FEVER / INJURY / GENERAL -- default protocol behaviour.
# ============================================================

def test_default_protocols_manage_here_with_no_danger_signs():
    for protocol in ("TB", "FEVER", "INJURY", "GENERAL"):
        out = _eval(protocol=protocol)
        assert out.disposition == "MANAGE_HERE", protocol
        assert out.urgency == "ROUTINE"
        assert out.insufficient_data is False


def test_default_protocols_refer_when_any_danger_sign_present():
    for protocol in ("TB", "FEVER", "INJURY", "GENERAL"):
        out = _eval(protocol=protocol, danger_signs=["some_danger_sign"])
        assert out.disposition == "REFER", protocol
        assert out.urgency == "WITHIN_24H"


def test_default_protocols_never_insufficient_even_with_no_vitals_at_all():
    # Spec: "others -> none" required vitals -- these protocols never
    # escalate for missing data.
    for protocol in ("TB", "FEVER", "INJURY", "GENERAL"):
        out = _eval(protocol=protocol, vitals={})
        assert out.insufficient_data is False
        assert out.disposition == "MANAGE_HERE"


# ============================================================
# STEP 3 -- insufficient data escalation. THE SAFETY RULE: never
# MANAGE_HERE on an incomplete assessment, never silent on missing data.
# ============================================================

def test_anc_insufficient_data_escalates_to_refer():
    out = _eval(protocol="ANC", vitals={})
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"
    assert out.insufficient_data is True
    assert set(out.missing_fields) == {"bp_systolic", "bp_diastolic"}
    assert out.reason == (
        "Not enough information to be sure. Treating this as needing a "
        "doctor's opinion."
    )


def test_anc_partially_missing_vitals_still_escalates():
    out = _eval(protocol="ANC", vitals={"bp_systolic": 110})
    assert out.disposition == "REFER"
    assert out.insufficient_data is True
    assert out.missing_fields == ["bp_diastolic"]


def test_imnci_insufficient_data_escalates_to_refer():
    out = _eval(protocol="IMNCI", age_years=2, vitals={})
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"
    assert out.insufficient_data is True
    assert set(out.missing_fields) == {"temperature_c", "respiratory_rate"}


def test_ncd_insufficient_data_escalates_to_refer():
    out = _eval(protocol="NCD", vitals={})
    assert out.disposition == "REFER"
    assert out.urgency == "WITHIN_24H"
    assert out.insufficient_data is True
    assert set(out.missing_fields) == {"bp_systolic", "bp_diastolic"}


def test_insufficient_data_never_returns_manage_here_for_protocols_with_required_vitals():
    """The core safety property: for every protocol that has required
    vitals, omitting them must never produce MANAGE_HERE."""
    for protocol, required in (
        ("ANC", ["bp_systolic", "bp_diastolic"]),
        ("IMNCI", ["temperature_c", "respiratory_rate"]),
        ("NCD", ["bp_systolic", "bp_diastolic"]),
    ):
        out = _eval(protocol=protocol, age_years=2, vitals={})
        assert out.disposition != "MANAGE_HERE", protocol
        assert out.insufficient_data is True
        assert set(out.missing_fields) == set(required)


def test_an_emergency_or_refer_finding_is_not_reclassified_as_insufficient():
    # If a real rule already fired (e.g. severe ANC hypertension), that
    # result must win even though other required vitals (bp_diastolic
    # here is present, but haemoglobin/temperature_c are not required
    # at all) are absent -- insufficient-data escalation only ever
    # applies to the MANAGE_HERE branch, never overrides a real finding.
    out = _eval(protocol="ANC", vitals={"bp_systolic": 162, "bp_diastolic": 100})
    assert out.disposition == "EMERGENCY"
    assert out.insufficient_data is False


# ============================================================
# Every branch's reason is plain language: non-empty, safe to read
# aloud, no bare rule IDs or scores.
# ============================================================

def test_reason_is_always_plain_language_and_non_empty():
    cases = [
        dict(protocol="GENERAL", vitals={"spo2": 80}),
        dict(protocol="ANC", vitals={"bp_systolic": 110, "bp_diastolic": 70}),
        dict(protocol="ANC", vitals={}),
        dict(protocol="IMNCI", age_years=2, vitals={"temperature_c": 37.0, "respiratory_rate": 30}),
        dict(protocol="NCD", vitals={"bp_systolic": 110, "bp_diastolic": 70}),
        dict(protocol="TB"),
    ]
    for kwargs in cases:
        out = _eval(**kwargs)
        assert isinstance(out.reason, str)
        assert len(out.reason.strip()) > 0
        # no bare rule-ID-looking tokens like "R3" or "RULE_7" standing
        # in for an actual sentence
        assert not out.reason.strip().upper().startswith("R")
        assert out.protocol_version == VERSION
