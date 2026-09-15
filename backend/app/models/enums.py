"""
Enumerations and static mappings for the Day 1 identity/RBAC model.

Source of truth: backend/docs/Day1.md

- RoleCode, ROLE_LEVEL, SELF_REGISTERABLE_ROLES
    -> Day1.md SS1 "Role taxonomy" (copied verbatim from the code block there).
- UserStatus
    -> Day1.md SS13.2, `CREATE TYPE user_status AS ENUM (...)` (copied verbatim).
- OrgUnitType
    -> Day1.md SS4 "Organisational scope model" / SS13.2 (`org_units.unit_type org_unit_type`).
       Day1.md references this SQL type repeatedly but never spells out a single
       `CREATE TYPE org_unit_type AS ENUM (...)` statement or an explicit canonical
       list the way it does for `user_status`. The 12-value set below was assembled
       from every unit_type token used across SS4.1 (org hierarchy diagram) and
       SS5.4 (role posting-field validations):
       STATE, DISTRICT, BLOCK, PHC, CHC, SDH, SUB_CENTRE, HWC, VILLAGE,
       DISTRICT_HOSPITAL, TELE_HUB, DISTRICT_OFFICE.
       SUB_CENTRE and HWC are kept as two distinct enum members: SS4.1 draws them as
       one node ("SUB_CENTRE / HWC"), but SS5.4 validation tuples (e.g.
       `sub_centre_org_unit_id` -> unit_type in (SUB_CENTRE, HWC)) use them as two
       distinct allowed values, so collapsing them would silently narrow what the
       spec's own validations accept.
       Day1.md does not spell out a canonical list for this type; this assembly was
       approved by Iqra Khan (document owner) in the implementation session, 2026-08-30.

ROLE_LEVEL is a convenience for fast hierarchy comparisons only. It is NOT the
authorisation mechanism — authorisation is the explicit `role_creation_grants`
table (see app/core/authz.py and Day1.md SS3). Do not use ROLE_LEVEL alone to
decide whether a creation is allowed.
"""
from enum import Enum


class RoleCode(str, Enum):
    SUPERUSER = "SUPERUSER"
    STATE_NHM = "STATE_NHM"
    COLLECTOR = "COLLECTOR"
    DHO_CMO = "DHO_CMO"
    DISTRICT_EPIDEMIOLOGIST = "DISTRICT_EPIDEMIOLOGIST"
    HEALTH_ADMIN_DPM = "HEALTH_ADMIN_DPM"
    PROGRAMME_OFFICER = "PROGRAMME_OFFICER"
    DISTRICT_IT_OFFICER = "DISTRICT_IT_OFFICER"
    DPO = "DPO"
    SPECIALIST = "SPECIALIST"
    BMO = "BMO"
    MEDICAL_OFFICER = "MEDICAL_OFFICER"
    CHO = "CHO"
    ANM_MPW = "ANM_MPW"
    LAB_TECHNICIAN = "LAB_TECHNICIAN"
    PHARMACIST = "PHARMACIST"
    ASHA = "ASHA"
    VHSNC_MEMBER = "VHSNC_MEMBER"
    PATIENT = "PATIENT"


ROLE_LEVEL: dict[RoleCode, int] = {
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

SELF_REGISTERABLE_ROLES = {RoleCode.PATIENT}


class UserStatus(str, Enum):
    """Day1.md SS13.2 -- CREATE TYPE user_status AS ENUM (...), copied verbatim."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRANSFERRED = "TRANSFERRED"
    EXPIRED = "EXPIRED"
    DEACTIVATED = "DEACTIVATED"


class OrgUnitType(str, Enum):
    """
    Day1.md SS4 / SS13.2 -- org_unit_type.
    See module docstring: 12-value set confirmed with the document owner,
    since Day1.md does not spell out a single canonical CREATE TYPE statement.
    """

    STATE = "STATE"
    DISTRICT = "DISTRICT"
    BLOCK = "BLOCK"
    PHC = "PHC"
    CHC = "CHC"
    SDH = "SDH"
    SUB_CENTRE = "SUB_CENTRE"
    HWC = "HWC"
    VILLAGE = "VILLAGE"
    DISTRICT_HOSPITAL = "DISTRICT_HOSPITAL"
    TELE_HUB = "TELE_HUB"
    DISTRICT_OFFICE = "DISTRICT_OFFICE"
