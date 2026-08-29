"""
Tests for app/models/enums.py against Day1.md SS1 (role taxonomy) and SS13.2
(user_status), plus the org_unit_type value set confirmed with the document
owner on 2026-08-30 (see the module docstring in app/models/enums.py for why
org_unit_type required confirmation rather than a direct quote from Day1.md).

Pure unit tests: no database, no app startup, no fixtures with real credentials.
"""
from app.models.enums import (
    ROLE_LEVEL,
    SELF_REGISTERABLE_ROLES,
    OrgUnitType,
    RoleCode,
    UserStatus,
)

EXPECTED_ROLE_LEVELS = {
    RoleCode.SUPERUSER: 0,
    RoleCode.STATE_NHM: 1,
    RoleCode.COLLECTOR: 2,
    RoleCode.DHO_CMO: 3,
    RoleCode.DISTRICT_EPIDEMIOLOGIST: 4,
    RoleCode.HEALTH_ADMIN_DPM: 4,
    RoleCode.PROGRAMME_OFFICER: 4,
    RoleCode.DISTRICT_IT_OFFICER: 4,
    RoleCode.DPO: 4,
    RoleCode.SPECIALIST: 4,
    RoleCode.BMO: 5,
    RoleCode.MEDICAL_OFFICER: 6,
    RoleCode.CHO: 7,
    RoleCode.ANM_MPW: 8,
    RoleCode.LAB_TECHNICIAN: 8,
    RoleCode.PHARMACIST: 8,
    RoleCode.ASHA: 9,
    RoleCode.VHSNC_MEMBER: 10,
    RoleCode.PATIENT: 99,
}

REQUIRED_USER_STATUSES = {
    "PENDING_APPROVAL",
    "INVITED",
    "ACTIVE",
    "SUSPENDED",
    "TRANSFERRED",
    "EXPIRED",
    "DEACTIVATED",
}

REQUIRED_ORG_UNIT_TYPES = {
    "STATE",
    "DISTRICT",
    "BLOCK",
    "PHC",
    "CHC",
    "SDH",
    "SUB_CENTRE",
    "HWC",
    "VILLAGE",
    "DISTRICT_HOSPITAL",
    "TELE_HUB",
    "DISTRICT_OFFICE",
}


def test_exactly_19_role_codes():
    assert len(list(RoleCode)) == 19
    assert len({r.value for r in RoleCode}) == 19  # no duplicate values


def test_role_levels_match_day1_exactly():
    assert ROLE_LEVEL == EXPECTED_ROLE_LEVELS
    # every RoleCode member has a level, and no extras exist
    assert set(ROLE_LEVEL.keys()) == set(RoleCode)


def test_only_patient_is_self_registerable():
    assert SELF_REGISTERABLE_ROLES == {RoleCode.PATIENT}
    for role in RoleCode:
        if role is RoleCode.PATIENT:
            assert role in SELF_REGISTERABLE_ROLES
        else:
            assert role not in SELF_REGISTERABLE_ROLES


def test_all_required_user_statuses_exist():
    actual = {s.value for s in UserStatus}
    assert actual == REQUIRED_USER_STATUSES


def test_all_required_org_unit_types_exist():
    actual = {t.value for t in OrgUnitType}
    assert actual == REQUIRED_ORG_UNIT_TYPES


def test_sub_centre_and_hwc_are_distinct_org_unit_types():
    # Day1.md SS5.4 validation tuples treat SUB_CENTRE and HWC as two distinct
    # allowed unit_type values (e.g. sub_centre_org_unit_id -> (SUB_CENTRE, HWC)),
    # even though SS4.1's diagram draws them as one node.
    assert OrgUnitType.SUB_CENTRE != OrgUnitType.HWC
    assert OrgUnitType.SUB_CENTRE.value == "SUB_CENTRE"
    assert OrgUnitType.HWC.value == "HWC"
