"""Staff registration schemas: common core, posting block, and the
discriminated union of all 18 staff role profiles, per Day1.md SS5.

WHAT IS VERBATIM VS THIS STEP'S OWN JOB, and where the boundary
deliberately sits -- read this before reviewing the models below:

- Every field name, type, required/optional flag, enum choice, and
  numeric/length range for CommonCore (SS5.2), PostingBlock (SS5.3),
  and each of the 18 role-specific blocks (SS5.4) is copied directly
  from those tables. Nothing here invents a field.

- PATIENT is deliberately NOT part of this union -- per this task's own
  instructions and per SS5.4's own framing ("PATIENT -- the only
  self-registration", a different endpoint, POST /auth/patient/register,
  with a materially different field set: age_years, abha_number,
  consent_*, otp_token, none of which exist for staff). SUPERUSER *is*
  included (SS5.4 gives it a full profile block), even though SS5.4
  notes it "is not creatable through the normal POST /users path in a
  fresh system" -- that's a creation-authority rule (SS9, already
  enforced by role_creation_grants having no SUPERUSER-creating-
  SUPERUSER-without-CLI path outside the bootstrap), not a reason to
  omit its schema.

- What this file CANNOT enforce, and does not pretend to: SS5.3's
  posting rules ("org_unit_id must exist, be active, be within the
  creator's scope, and have a unit_type allowed for the role";
  "reports_to_user_id ... must be an active user whose role may create
  this role") all require a database lookup against live org_units/
  users/role_creation_grants rows and knowledge of who the *creator*
  is. A stateless Pydantic schema has no database session and no
  concept of "the creator" -- those checks belong at the route/
  dependency layer (a later step), the same separation already kept
  between app/core/crypto.py (no DB) and anything that queries a
  table. What this file DOES enforce for the posting block is
  everything checkable from the payload alone: field shapes, and the
  two role-level-dependent requiredness rules that only need
  ROLE_LEVEL (already in app/models/enums.py, no DB needed) --
  `posting_order_ref`/`posting_order_date` required for L<=5.
  Likewise `email` required for L<=5 and `employee_code` required for
  L<=6 in CommonCore. Cross-field uniqueness ("unique mobile", "unique
  employee_code", "unique per state", HPR verification, org_units
  existence) is a database concern; this file validates *shape*, not
  *uniqueness against live data*.

- Discriminator mechanism: SS5.1's own payload shows `role` living
  OUTSIDE `profile` (`{"role": "CHO", "common": {...}, "posting":
  {...}, "profile": {...ROLE-SPECIFIC BLOCK...}}`), with `profile`
  containing only that role's own fields -- not a role tag repeated
  inside it. Pydantic v2's built-in `Field(discriminator=...)` expects
  the tag *inside* the union member being matched, so a literal
  reading of SS5.1's envelope needs a small amount of dispatch code
  that isn't a spec quote: `UserRegistrationRequest`'s own
  `model_validator(mode="before")` looks up the correct profile model
  from `ROLE_PROFILE_MAP` using the outer `role` field and validates
  `profile` against exactly that model -- achieving the same effect
  ("ASHA fields under role: CHO is a 422, not silently accepted",
  SS5.1's own words) without asking clients to repeat `role` a second
  time inside `profile`. `STAFF_PROFILE_UNION` (an
  `Annotated[Union[...], Field(discriminator="role")]`, each member
  carrying its own `role: Literal[...]`) is also exposed, for any
  future caller that already has `role` embedded and wants Pydantic's
  native tagged-union behaviour directly -- both paths validate
  against the identical set of 18 models.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from enum import Enum
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ROLE_LEVEL, RoleCode

# ============================================================
# Shared validation constants -- SS5.2/SS5.3, quoted where given.
# ============================================================

_MOBILE_RE = re.compile(r"^\+91[6-9]\d{9}$")
_FULL_NAME_RE = re.compile(r"^[A-Za-z .'\-]+$")
_ID_PROOF_LAST4_RE = re.compile(r"^\d{4}$")
_DEVICE_IMEI_RE = re.compile(r"^\d{15}$")


def _luhn_check(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class Sex(str, Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    OTHER = "OTHER"


class IdProofType(str, Enum):
    """SS5.2: AADHAAR deliberately not an option -- see SS11.4."""
    PAN = "PAN"
    VOTER_ID = "VOTER_ID"
    DL = "DL"
    PASSPORT = "PASSPORT"
    SERVICE_ID = "SERVICE_ID"


class EducationLevel(str, Enum):
    CLASS_8 = "CLASS_8"
    CLASS_10 = "CLASS_10"
    CLASS_12 = "CLASS_12"
    GRADUATE = "GRADUATE"
    OTHER = "OTHER"


class AnmQualification(str, Enum):
    ANM = "ANM"
    GNM = "GNM"
    BSC_NURSING = "BSC_NURSING"
    MPW_MALE = "MPW_MALE"


class ChoBaseQualification(str, Enum):
    BSC_NURSING = "BSC_NURSING"
    GNM = "GNM"
    BAMS = "BAMS"
    POST_BASIC_BSC = "POST_BASIC_BSC"


class MedicalOfficerQualification(str, Enum):
    MBBS = "MBBS"
    MD = "MD"
    MS = "MS"
    DNB = "DNB"
    BAMS = "BAMS"
    BHMS = "BHMS"


class Specialty(str, Enum):
    OBG = "OBG"
    MEDICINE = "MEDICINE"
    PAEDIATRICS = "PAEDIATRICS"
    PSYCHIATRY = "PSYCHIATRY"
    DERMATOLOGY = "DERMATOLOGY"
    OPHTHALMOLOGY = "OPHTHALMOLOGY"
    ORTHOPAEDICS = "ORTHOPAEDICS"
    SURGERY = "SURGERY"
    ANAESTHESIA = "ANAESTHESIA"


class PgQualification(str, Enum):
    MD = "MD"
    MS = "MS"
    DNB = "DNB"
    DIPLOMA = "DIPLOMA"


class WeekDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class LabQualification(str, Enum):
    DMLT = "DMLT"
    BMLT = "BMLT"
    MSC_MLT = "MSC_MLT"


class LabTestCategory(str, Enum):
    HAEMATOLOGY = "HAEMATOLOGY"
    BIOCHEMISTRY = "BIOCHEMISTRY"
    MICROBIOLOGY = "MICROBIOLOGY"
    SEROLOGY = "SEROLOGY"
    POC = "POC"


class PharmacistQualification(str, Enum):
    D_PHARM = "D_PHARM"
    B_PHARM = "B_PHARM"
    M_PHARM = "M_PHARM"
    PHARM_D = "PHARM_D"


class DhoQualification(str, Enum):
    MD_COMMUNITY_MEDICINE = "MD_COMMUNITY_MEDICINE"
    MBBS = "MBBS"
    MPH = "MPH"
    OTHER_PG = "OTHER_PG"


class EpidemiologistQualification(str, Enum):
    MPH = "MPH"
    MD_COMMUNITY_MEDICINE = "MD_COMMUNITY_MEDICINE"
    MSC_EPIDEMIOLOGY = "MSC_EPIDEMIOLOGY"
    FETP = "FETP"


class AnalyticsScopeArea(str, Enum):
    SURVEILLANCE = "SURVEILLANCE"
    MATERNAL = "MATERNAL"
    CHILD = "CHILD"
    NCD = "NCD"
    TB = "TB"
    QUALITY = "QUALITY"


class DpmQualification(str, Enum):
    MBA = "MBA"
    MHA = "MHA"
    MPH = "MPH"
    PGDM = "PGDM"
    OTHER = "OTHER"


class FunctionalArea(str, Enum):
    HR = "HR"
    FINANCE = "FINANCE"
    LOGISTICS = "LOGISTICS"
    PROCUREMENT = "PROCUREMENT"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class Programme(str, Enum):
    RCH = "RCH"
    NCD = "NCD"
    TB = "TB"
    IMMUNISATION = "IMMUNISATION"
    NVBDCP = "NVBDCP"
    BLINDNESS = "BLINDNESS"
    MENTAL_HEALTH = "MENTAL_HEALTH"


class TechnicalScopeArea(str, Enum):
    DEVICES = "DEVICES"
    CONNECTIVITY = "CONNECTIVITY"
    INTEGRATIONS = "INTEGRATIONS"
    SUPPORT = "SUPPORT"


class DpoScopeLevel(str, Enum):
    DISTRICT = "DISTRICT"
    STATE = "STATE"


class CollectorServiceType(str, Enum):
    IAS = "IAS"
    STATE_CIVIL_SERVICE = "STATE_CIVIL_SERVICE"


class VhsncPosition(str, Enum):
    CHAIRPERSON = "CHAIRPERSON"
    SECRETARY = "SECRETARY"
    MEMBER = "MEMBER"
    ASHA_SECRETARY = "ASHA_SECRETARY"


# ============================================================
# Common core -- SS5.2, every staff role.
# ============================================================

class CommonCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    full_name_local: Optional[str] = Field(default=None, min_length=2, max_length=120)
    mobile: str
    email: Optional[str] = None  # required for L<=5 -- enforced by UserRegistrationRequest, needs role/level
    date_of_birth: date
    sex: Sex
    preferred_language: str = Field(min_length=2, max_length=10)  # ISO 639-1 code from enabled set
    employee_code: Optional[str] = None  # required for L<=6 -- enforced by UserRegistrationRequest
    designation: str = Field(min_length=2, max_length=80)
    joining_date: date
    id_proof_type: IdProofType
    id_proof_last4: str
    photo_object_key: Optional[str] = None

    @field_validator("full_name", "full_name_local")
    @classmethod
    def _validate_name_chars(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _FULL_NAME_RE.match(v):
            raise ValueError("must contain only letters, space, '.', '-', or \"'\"")
        return v

    @field_validator("mobile")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        if not _MOBILE_RE.match(v):
            raise ValueError(r"mobile must match ^\+91[6-9]\d{9}$")
        return v

    @field_validator("id_proof_last4")
    @classmethod
    def _validate_id_proof_last4(cls, v: str) -> str:
        if not _ID_PROOF_LAST4_RE.match(v):
            raise ValueError("id_proof_last4 must be exactly 4 digits")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _validate_dob(cls, v: date) -> date:
        today = date.today()
        age_years = (today - v).days / 365.25
        if age_years < 18:
            raise ValueError("staff must be at least 18 years old")
        if age_years > 70:
            raise ValueError("staff must be at most 70 years old")
        return v

    @field_validator("joining_date")
    @classmethod
    def _validate_joining_date(cls, v: date) -> date:
        from datetime import timedelta
        if v > date.today() + timedelta(days=30):
            raise ValueError("joining_date must not be more than 30 days in the future")
        return v


# ============================================================
# Posting block -- SS5.3, every staff role.
# ============================================================

class PostingBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_unit_id: UUID
    reports_to_user_id: Optional[UUID] = None
    posting_order_ref: Optional[str] = None  # required for L<=5 -- enforced by UserRegistrationRequest
    posting_order_date: Optional[date] = None  # required for L<=5 -- enforced by UserRegistrationRequest
    is_officer_in_charge: Optional[bool] = None
    valid_until: Optional[date] = None

    @field_validator("posting_order_date")
    @classmethod
    def _validate_posting_order_date(cls, v: Optional[date]) -> Optional[date]:
        if v is not None and v > date.today():
            raise ValueError("posting_order_date must not be in the future")
        return v


# ============================================================
# Role-specific profiles -- SS5.4, one per staff role.
# Each carries its own `role: Literal[...]` discriminator field (see
# module docstring) and `extra="forbid"`.
# ============================================================

class AshaProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["ASHA"] = "ASHA"

    asha_state_code: str
    village_lgd_codes: list[str] = Field(min_length=1, max_length=3)
    sub_centre_org_unit_id: UUID
    population_covered: int = Field(ge=100, le=3000)
    education_level: EducationLevel
    induction_training_completed: bool
    training_modules_completed: list[str] = Field(default_factory=list)
    incentive_account_token: Optional[str] = None
    device_issued: Optional[bool] = None
    device_imei: Optional[str] = None
    works_offline_primarily: bool

    @field_validator("device_imei")
    @classmethod
    def _validate_imei(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _DEVICE_IMEI_RE.match(v):
            raise ValueError("device_imei must be exactly 15 digits")
        if not _luhn_check(v):
            raise ValueError("device_imei fails Luhn checksum")
        return v


class AnmMpwProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["ANM_MPW"] = "ANM_MPW"

    council_registration_number: str
    council_name: str
    council_registration_expiry: date
    qualification: AnmQualification
    sub_centre_org_unit_id: UUID
    village_lgd_codes: list[str] = Field(min_length=1, max_length=10)
    is_immunisation_certified: bool
    is_sba_certified: Optional[bool] = None

    @field_validator("council_registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("council_registration_expiry must be in the future")
        return v


class ChoProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["CHO"] = "CHO"

    hpr_id: str
    cch_certificate_number: str
    council_registration_number: str
    council_registration_expiry: date
    base_qualification: ChoBaseQualification
    hwc_org_unit_id: UUID
    teleconsult_enabled: bool
    dispensing_scope: list[str] = Field(min_length=1)

    @field_validator("council_registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("council_registration_expiry must be in the future")
        return v


class MedicalOfficerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["MEDICAL_OFFICER"] = "MEDICAL_OFFICER"

    hpr_id: str
    medical_council_registration_number: str
    medical_council_name: str
    registration_expiry: date
    qualification: MedicalOfficerQualification
    qualification_year: int
    facility_org_unit_id: UUID
    is_moic: bool
    prescribing_scope: list[str] = Field(min_length=1)
    telemedicine_certified: bool
    specialisation: Optional[str] = None

    @field_validator("registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("registration_expiry must be in the future")
        return v

    @field_validator("qualification_year")
    @classmethod
    def _validate_qualification_year(cls, v: int) -> int:
        if not (1960 <= v <= date.today().year):
            raise ValueError(f"qualification_year must be between 1960 and {date.today().year}")
        return v


class SpecialistProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["SPECIALIST"] = "SPECIALIST"

    hpr_id: str
    medical_council_registration_number: str
    registration_expiry: date
    specialty: Specialty
    pg_qualification: PgQualification
    tele_hub_org_unit_id: UUID
    telemedicine_certified: bool
    languages_spoken: list[str] = Field(min_length=1)
    roster_days: list[WeekDay] = Field(min_length=1)
    roster_start_time: time
    roster_end_time: time
    max_queue_length: int = Field(ge=1, le=50)
    accepts_store_and_forward: bool
    sla_response_hours_routine: int = 24
    sla_response_hours_urgent: int = 2

    @field_validator("registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("registration_expiry must be in the future")
        return v

    @field_validator("telemedicine_certified")
    @classmethod
    def _validate_telemedicine_certified(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("telemedicine_certified must be true to receive teleconsult requests")
        return v

    @model_validator(mode="after")
    def _validate_roster_times(self) -> "SpecialistProfile":
        if self.roster_end_time <= self.roster_start_time:
            raise ValueError("roster_end_time must be after roster_start_time")
        return self


class LabTechnicianProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["LAB_TECHNICIAN"] = "LAB_TECHNICIAN"

    qualification: LabQualification
    council_registration_number: Optional[str] = None
    facility_org_unit_id: UUID
    lab_code: str
    authorised_test_categories: list[LabTestCategory] = Field(min_length=1)
    can_release_results: bool
    can_acknowledge_critical: bool = False


class PharmacistProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["PHARMACIST"] = "PHARMACIST"

    pharmacy_council_registration_number: str
    council_registration_expiry: date
    qualification: PharmacistQualification
    facility_org_unit_id: UUID
    can_dispense_schedule_h: bool
    can_manage_stock: bool
    can_raise_indent: bool
    cold_chain_trained: bool

    @field_validator("council_registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("council_registration_expiry must be in the future")
        return v


class BmoProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["BMO"] = "BMO"

    hpr_id: str
    medical_council_registration_number: str
    registration_expiry: date
    block_org_unit_id: UUID
    facilities_supervised: list[UUID] = Field(min_length=1)
    can_reassign_referral_owner: bool = True
    escalation_contact_priority: int = Field(ge=1, le=5)

    @field_validator("registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("registration_expiry must be in the future")
        return v


class DhoCmoProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["DHO_CMO"] = "DHO_CMO"

    hpr_id: str
    medical_council_registration_number: str
    registration_expiry: date
    qualification: DhoQualification
    district_org_unit_id: UUID
    appointment_order_ref: str
    is_clinical_governance_chair: bool
    can_approve_l3_accounts: bool

    @field_validator("registration_expiry")
    @classmethod
    def _validate_expiry(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("registration_expiry must be in the future")
        return v


class DistrictEpidemiologistProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["DISTRICT_EPIDEMIOLOGIST"] = "DISTRICT_EPIDEMIOLOGIST"

    qualification: EpidemiologistQualification
    district_org_unit_id: UUID
    analytics_scope: list[AnalyticsScopeArea] = Field(min_length=1)
    deidentified_access_only: bool = True
    line_list_access_approved_by: Optional[UUID] = None
    line_list_access_expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_line_list_access(self) -> "DistrictEpidemiologistProfile":
        if self.line_list_access_approved_by is not None:
            if self.line_list_access_expires_at is None:
                raise ValueError(
                    "line_list_access_expires_at is required when "
                    "line_list_access_approved_by is set"
                )
            from datetime import timedelta
            max_expiry = datetime.now(self.line_list_access_expires_at.tzinfo) + timedelta(days=90)
            if self.line_list_access_expires_at > max_expiry:
                raise ValueError("line_list_access_expires_at must be at most 90 days out")
        return self


class HealthAdminDpmProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["HEALTH_ADMIN_DPM"] = "HEALTH_ADMIN_DPM"

    qualification: DpmQualification
    district_org_unit_id: UUID
    functional_areas: list[FunctionalArea] = Field(min_length=1)
    budget_approval_limit_inr: Optional[int] = Field(default=None, ge=0)
    can_approve_indent: bool
    phi_access: Literal[False] = False


class ProgrammeOfficerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["PROGRAMME_OFFICER"] = "PROGRAMME_OFFICER"

    programme: Programme
    district_org_unit_id: UUID
    national_portal_user_id: Optional[str] = None
    can_approve_protocol_changes: bool
    cohort_access_only: Literal[True] = True


class DistrictItOfficerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["DISTRICT_IT_OFFICER"] = "DISTRICT_IT_OFFICER"

    district_org_unit_id: UUID
    technical_scope: list[TechnicalScopeArea] = Field(min_length=1)
    can_manage_devices: bool
    can_view_sync_health: bool
    can_create_users: Literal[False] = False
    phi_access: Literal[False] = False


class DpoProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["DPO"] = "DPO"

    scope_level: DpoScopeLevel
    scope_org_unit_id: UUID
    appointment_order_ref: str
    published_contact_email: str
    published_contact_phone: str
    can_read_audit_log: Literal[True] = True
    can_read_consent_records: Literal[True] = True
    can_read_clinical_data: Literal[False] = False
    second_approver_user_id: UUID


class CollectorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["COLLECTOR"] = "COLLECTOR"

    service_type: CollectorServiceType
    district_org_unit_id: UUID
    tenure_start: date
    tenure_end: Optional[date] = None
    dashboard_access_only: Literal[True] = True
    phi_access: Literal[False] = False


class StateNhmProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["STATE_NHM"] = "STATE_NHM"

    state_code: str
    directorate_designation: str
    districts_overseen: list[UUID] = Field(default_factory=list)
    aggregate_access_only: Literal[True] = True
    can_approve_l2_l3_accounts: bool


class VhsncMemberProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["VHSNC_MEMBER"] = "VHSNC_MEMBER"

    village_lgd_code: str
    panchayat_name: str
    position: VhsncPosition
    term_start: date
    term_end: date
    aggregate_scorecard_only: Literal[True] = True
    phi_access: Literal[False] = False

    @model_validator(mode="after")
    def _validate_term(self) -> "VhsncMemberProfile":
        if self.term_end <= self.term_start:
            raise ValueError("term_end must be after term_start")
        return self


class SuperuserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["SUPERUSER"] = "SUPERUSER"

    full_name: str
    email: str
    mobile: str
    hardware_mfa_required: Literal[True] = True
    justification: str = Field(min_length=50)
    second_approver_user_id: UUID
    expires_at: datetime

    @field_validator("mobile")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        if not _MOBILE_RE.match(v):
            raise ValueError(r"mobile must match ^\+91[6-9]\d{9}$")
        return v

    @field_validator("expires_at")
    @classmethod
    def _validate_expires_at(cls, v: datetime) -> datetime:
        from datetime import timedelta
        max_expiry = datetime.now(v.tzinfo) + timedelta(days=365)
        if v > max_expiry:
            raise ValueError("expires_at must be at most 365 days out")
        return v


# ============================================================
# The discriminated union -- all 18 staff role profiles.
# PATIENT is deliberately excluded (see module docstring).
# ============================================================

STAFF_PROFILE_UNION = Annotated[
    Union[
        AshaProfile, AnmMpwProfile, ChoProfile, MedicalOfficerProfile,
        SpecialistProfile, LabTechnicianProfile, PharmacistProfile, BmoProfile,
        DhoCmoProfile, DistrictEpidemiologistProfile, HealthAdminDpmProfile,
        ProgrammeOfficerProfile, DistrictItOfficerProfile, DpoProfile,
        CollectorProfile, StateNhmProfile, VhsncMemberProfile, SuperuserProfile,
    ],
    Field(discriminator="role"),
]

ROLE_PROFILE_MAP: dict[str, type[BaseModel]] = {
    "ASHA": AshaProfile,
    "ANM_MPW": AnmMpwProfile,
    "CHO": ChoProfile,
    "MEDICAL_OFFICER": MedicalOfficerProfile,
    "SPECIALIST": SpecialistProfile,
    "LAB_TECHNICIAN": LabTechnicianProfile,
    "PHARMACIST": PharmacistProfile,
    "BMO": BmoProfile,
    "DHO_CMO": DhoCmoProfile,
    "DISTRICT_EPIDEMIOLOGIST": DistrictEpidemiologistProfile,
    "HEALTH_ADMIN_DPM": HealthAdminDpmProfile,
    "PROGRAMME_OFFICER": ProgrammeOfficerProfile,
    "DISTRICT_IT_OFFICER": DistrictItOfficerProfile,
    "DPO": DpoProfile,
    "COLLECTOR": CollectorProfile,
    "STATE_NHM": StateNhmProfile,
    "VHSNC_MEMBER": VhsncMemberProfile,
    "SUPERUSER": SuperuserProfile,
}

assert set(ROLE_PROFILE_MAP) == {r.value for r in RoleCode if r != RoleCode.PATIENT}, (
    "ROLE_PROFILE_MAP must cover exactly the 18 non-PATIENT roles in RoleCode"
)

# Roles whose CommonCore.email is required (SS5.2: "Required for supervisory
# and above" -- L<=5) and whose CommonCore.employee_code is required (L<=6),
# and whose PostingBlock.posting_order_ref/posting_order_date are required
# (SS5.3 -- L<=5).
_EMAIL_REQUIRED_MAX_LEVEL = 5
_EMPLOYEE_CODE_REQUIRED_MAX_LEVEL = 6
_POSTING_ORDER_REQUIRED_MAX_LEVEL = 5


class UserRegistrationRequest(BaseModel):
    """SS5.1's full envelope: role + common + posting + profile, with
    profile dispatched to the correct model per `role` (see module
    docstring) and the role-level-dependent CommonCore/PostingBlock
    requiredness rules applied here, since only this level has both
    `role` (hence ROLE_LEVEL) and the other blocks together."""
    model_config = ConfigDict(extra="forbid")

    role: str
    common: CommonCore
    posting: PostingBlock
    profile: STAFF_PROFILE_UNION

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in ROLE_PROFILE_MAP:
            raise ValueError(
                f"{v!r} is not a valid staff role for registration "
                f"(PATIENT self-registers via a separate endpoint)"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _dispatch_profile(cls, data):
        if not isinstance(data, dict):
            return data
        role = data.get("role")
        profile_cls = ROLE_PROFILE_MAP.get(role)
        raw_profile = data.get("profile")
        if profile_cls is not None and isinstance(raw_profile, dict):
            # Validate profile against the role-selected model now, so a
            # mismatch (e.g. ASHA fields under role: CHO) surfaces as a
            # normal 422 from *this* model rather than needing Pydantic's
            # union-matching to guess between all 18 (it would guess
            # wrong or fail ambiguously, since none of the profile dicts
            # carry `role` themselves).
            data = dict(data)
            data["profile"] = {**raw_profile, "role": role}
        return data

    @model_validator(mode="after")
    def _validate_role_dependent_requiredness(self) -> "UserRegistrationRequest":
        level = ROLE_LEVEL.get(RoleCode(self.role))
        if level is None:
            return self  # unreachable given _validate_role, but fail closed rather than crash

        if level <= _EMAIL_REQUIRED_MAX_LEVEL and not self.common.email:
            raise ValueError("email is required for this role (L<=5)")
        if level <= _EMPLOYEE_CODE_REQUIRED_MAX_LEVEL and not self.common.employee_code:
            raise ValueError("employee_code is required for this role (L<=6)")
        if level <= _POSTING_ORDER_REQUIRED_MAX_LEVEL:
            if not self.posting.posting_order_ref:
                raise ValueError("posting.posting_order_ref is required for this role (L<=5)")
            if not self.posting.posting_order_date:
                raise ValueError("posting.posting_order_date is required for this role (L<=5)")
        return self
