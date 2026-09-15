"""seed RBAC reference data: roles, permissions, role_permissions, role_creation_grants

Revision ID: e5a83c1f9d6b
Revises: 9d5f6b3e0a71
Create Date: 2026-08-30 00:00:00.000000

Day1.md SS1 / SS3 / SS8 / SS18 (migration 0009 in the doc's numbering,
`0009_seed_reference_data`): the complete RBAC reference-data seed.

This is a DATA migration, deliberately separate from the schema
migrations that created these tables (a1f3c8e6b204) -- per SS17.2's own
rule: "a failed seed should not roll back a schema change."

WHAT IS VERBATIM VS INTERPRETED, and why -- read this before reviewing
the data below, since the four tables differ sharply in how directly
Day1.md specifies them:

=== roles (19 rows) -- fully verbatim ===
code/display_name/level/self_register/is_clinical copied directly from
SS1's role taxonomy table. No gaps, no interpretation. Uses ON CONFLICT
DO UPDATE (not DO NOTHING): 9d5f6b3e0a71 already bootstrapped a minimal
SUPERUSER row (display_name 'Superuser', just enough to satisfy an FK)
before this seed runs -- this seed's SS1-sourced values must overwrite
that placeholder, not silently lose to it.

=== permissions (51 rows) -- fully verbatim ===
Every permission code in SS8.2's catalogue, extracted completely and
literally (SS8.2 lists every code explicitly; nothing here required
inference). Note this is 51, not SS18.1's own approximate "~60" --
SS18.1's figure is stated with a "~", this is an exact count from the
literal catalogue.

=== role_creation_grants (65 rows) -- mostly verbatim, two resolved gaps ===
47 of 65 rows (every non-SUPERUSER creator: STATE_NHM 11, COLLECTOR 5,
DHO_CMO 14, HEALTH_ADMIN_DPM 2, BMO 7, MEDICAL_OFFICER 5, CHO 2,
ANM_MPW 1) are copied verbatim, unchanged, from SS18.2's GRANTS list --
that list is complete and unambiguous for every creator except
SUPERUSER.

SUPERUSER's row in SS18.2 is explicitly truncated ("... one row per
remaining role, all allowed ..."), giving only 4 of 19 possible target
rows literally (SUPERUSER, STATE_NHM, COLLECTOR, DHO_CMO). Two gaps,
both confirmed with the user directly in this session (2026-08-30):

  1. allowed_org_unit_types for SUPERUSER's other 14 targets (target
     PATIENT is handled separately, see below): confirmed to reuse the
     allowed_org_unit_types other creators already use for that same
     target elsewhere in this same SS18.2 list, taking the widest set
     where creators disagree (e.g. DPO: STATE_NHM allows
     ["DISTRICT_OFFICE","STATE"], DHO_CMO allows ["DISTRICT_OFFICE"]
     only -- SUPERUSER's row uses the wider ["DISTRICT_OFFICE","STATE"],
     consistent with SUPERUSER's top-of-hierarchy authority). Every
     value below is therefore data already present in Day1.md, reused,
     not invented from nothing.

  2. SUPERUSER -> PATIENT: the raw SS3 matrix table shows a checkmark
     in this cell, but SS3.1's own prose is explicit -- "Nobody may
     create PATIENT except assisted-registration, which is a different
     endpoint" -- and Rule 1 (SS0) states there is exactly one public
     registration path. Confirmed with the user: trust the prose rule
     over the matrix cell. No (SUPERUSER, PATIENT, ...) row exists in
     this seed. Total row count is therefore 65 (18 SUPERUSER rows,
     not 19) rather than the 66 a literal cell-count of the raw SS3
     matrix would suggest.

requires_second_approver for SUPERUSER's filled-in rows: False for all
14, matching the pattern already established by the 4 given rows
(only SUPERUSER->SUPERUSER needs dual approval) and SS9.3's own text
("Only via CLI on an empty system, or by an existing superuser with a
second superuser approving" -- i.e. dual approval is specifically for
minting a peer SUPERUSER, not a general SUPERUSER-as-creator rule).

=== role_permissions (209 rows) -- INTERPRETED, not verbatim ===
SS8.3 explicitly labels itself "abridged; full map lives in
seed_permissions.py" -- a file that does not exist anywhere in this
repository or in Day1.md. Its actual content per role is prose
("user:* per matrix", "all clinical read", "full clinical at
facility", "limited prescription:create"), not a literal permission-
code list Day1.md ever states directly for any role except SUPERUSER
("All").

Confirmed with the user directly in this session (2026-08-30): produce
a best-effort translation of that prose into explicit codes from the
51-code SS8.2 catalogue, documented per role below, for the user's own
review rather than presented as spec-derived fact. Two interpretation
rules applied consistently:

  - A permission is included only if SS8.3's prose for that role
    states it unconditionally. Explicitly CONDITIONAL grants are
    omitted from this static seed, not approximated as always-on:
    DISTRICT_EPIDEMIOLOGIST's analytics:line_list ("only when time-
    boxed approval exists") and LAB_TECHNICIAN's lab:release_result /
    lab:acknowledge_critical ("only if flagged") are both left out.
    Granting those conditionally is a runtime/approval concern for a
    later step, not a static role_permissions row.
  - A prose phrase with no matching permission code is flagged and
    omitted, not guessed at: PATIENT's "appointment booking" has no
    corresponding code anywhere in SS8.2's catalogue (no appointment:*
    group exists at all).

Resulting total (209 rows) is notably below SS18.1's own approximate
"~450" estimate -- that gap is a direct consequence of the two rules
above (omitting conditional and unmappable grants rather than
inflating counts to approximate a target number) and of SS8.3 being
genuinely abridged prose, not a undercount error in this migration.
Per-role code below states the exact SS8.3 phrase being translated and
which SS8.2 codes it maps to, so this can be reviewed and corrected
line by line without re-deriving the whole thing.

Idempotent: every INSERT uses ON CONFLICT DO NOTHING (roles.code,
permissions.code, role_permissions' composite PK, role_creation_grants'
composite PK are each the natural conflict target), so re-running this
migration -- or running it after 9d5f6b3e0a71's own SUPERUSER-role
bootstrap row -- never errors or duplicates.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a83c1f9d6b'
down_revision: Union[str, Sequence[str], None] = '9d5f6b3e0a71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ============================================================
# roles -- verbatim, Day1.md SS1.
# (code, display_name, level, self_register, is_clinical)
# ============================================================
ROLES: list[tuple[str, str, int, bool, bool]] = [
    ("SUPERUSER", "System Administrator", 0, False, False),
    ("STATE_NHM", "State NHM / Directorate", 1, False, False),
    ("COLLECTOR", "District Magistrate / Collector", 2, False, False),
    ("DHO_CMO", "DHO / CMO / CMHO", 3, False, True),
    ("DISTRICT_EPIDEMIOLOGIST", "District Epidemiologist / Public Health Analyst", 4, False, False),
    ("HEALTH_ADMIN_DPM", "Health Administrator / DPM / DPMU", 4, False, False),
    ("PROGRAMME_OFFICER", "District Programme Officer (RCH/NCD/TB/Imm.)", 4, False, False),
    ("DISTRICT_IT_OFFICER", "District IT Officer", 4, False, False),
    ("DPO", "Data Protection Officer", 4, False, False),
    ("SPECIALIST", "Specialist (OBG, Med, Paed, Psy, Derm, Ophth, Ortho)", 4, False, True),
    ("BMO", "Block Medical Officer (BMO / MOIC)", 5, False, True),
    ("MEDICAL_OFFICER", "Medical Officer (MO / MOIC) — PHC", 6, False, True),
    ("CHO", "Community Health Officer", 7, False, True),
    ("ANM_MPW", "ANM / MPW", 8, False, True),
    ("LAB_TECHNICIAN", "Lab Technician", 8, False, True),
    ("PHARMACIST", "Pharmacist", 8, False, True),
    ("ASHA", "ASHA", 9, False, True),
    ("VHSNC_MEMBER", "VHSNC / PRI (Panchayat) member", 10, False, False),
    ("PATIENT", "Patient / family", 99, True, False),
]

# ============================================================
# permissions -- verbatim, every code in Day1.md SS8.2.
# ============================================================
PERMISSIONS: list[str] = [
    # User management
    "user:create", "user:read", "user:update", "user:suspend",
    "user:deactivate", "user:approve", "user:transfer",
    # Patient
    "patient:create", "patient:read", "patient:read_deidentified", "patient:update",
    # Clinical
    "triage:create", "triage:read", "encounter:create", "encounter:read",
    "vitals:create", "prescription:create", "prescription:dispense",
    # Referral
    "referral:create", "referral:read", "referral:update_status", "referral:reassign_owner",
    # Lab
    "lab:order", "lab:collect", "lab:enter_result", "lab:release_result",
    "lab:acknowledge_critical",
    # Teleconsult
    "teleconsult:request", "teleconsult:accept", "teleconsult:complete",
    # Stock
    "stock:read", "stock:update", "stock:indent", "stock:approve_indent",
    # Registry
    "registry:read", "registry:update", "registry:record_outcome",
    # Dashboards
    "dashboard:facility", "dashboard:block", "dashboard:district", "dashboard:state",
    "analytics:deidentified", "analytics:line_list",
    # Governance
    "audit:read", "consent:read", "consent:revoke", "protocol:approve",
    # System
    "system:config", "system:device_manage", "system:integration_manage",
    "system:break_glass",
]

_USER_STAR = ["user:create", "user:read", "user:update", "user:suspend",
              "user:deactivate", "user:approve", "user:transfer"]
_STOCK_STAR = ["stock:read", "stock:update", "stock:indent", "stock:approve_indent"]
_REGISTRY_STAR = ["registry:read", "registry:update", "registry:record_outcome"]
_TRIAGE_STAR = ["triage:create", "triage:read"]
_PATIENT_STAR = ["patient:create", "patient:read", "patient:read_deidentified", "patient:update"]
# "full clinical" (BMO/MEDICAL_OFFICER) = patient:* + all Clinical + create/read/
# update_status on Referral (not reassign_owner, listed separately where granted)
# + all Lab + all Teleconsult + registry:*
_FULL_CLINICAL = (
    _PATIENT_STAR
    + ["triage:create", "triage:read", "encounter:create", "encounter:read",
       "vitals:create", "prescription:create", "prescription:dispense"]
    + ["referral:create", "referral:read", "referral:update_status"]
    + ["lab:order", "lab:collect", "lab:enter_result", "lab:release_result",
       "lab:acknowledge_critical"]
    + ["teleconsult:request", "teleconsult:accept", "teleconsult:complete"]
    + _REGISTRY_STAR
)

# ============================================================
# role_permissions -- INTERPRETED from Day1.md SS8.3's abridged prose.
# Each block quotes the exact SS8.3 phrase being translated.
# ============================================================
ROLE_PERMISSIONS: dict[str, list[str]] = {
    # "All, plus system:break_glass" -- system:break_glass is already one
    # of the 51 PERMISSIONS, so "All" already covers it.
    "SUPERUSER": list(PERMISSIONS),

    # "user:* (per matrix) · dashboard:state · analytics:deidentified · audit:read"
    "STATE_NHM": _USER_STAR + ["dashboard:state", "analytics:deidentified", "audit:read"],

    # "user:create/approve (per matrix) · dashboard:district · analytics:deidentified"
    "COLLECTOR": ["user:create", "user:approve", "dashboard:district", "analytics:deidentified"],

    # "user:* · all clinical read · dashboard:district · protocol:approve ·
    #  analytics:line_list · referral:reassign_owner"
    # "all clinical read" interpreted as every *:read-type code across the
    # Patient/Clinical/Referral/Registry groups (no lab:read code exists).
    "DHO_CMO": (
        _USER_STAR
        + ["patient:read", "patient:read_deidentified", "triage:read",
           "encounter:read", "referral:read", "registry:read"]
        + ["dashboard:district", "protocol:approve", "analytics:line_list",
           "referral:reassign_owner"]
    ),

    # "analytics:deidentified · dashboard:district · registry:read ·
    #  patient:read_deidentified. analytics:line_list only when time-boxed
    #  approval exists" -- conditional grant omitted, see module docstring.
    "DISTRICT_EPIDEMIOLOGIST": [
        "analytics:deidentified", "dashboard:district", "registry:read",
        "patient:read_deidentified",
    ],

    # "user:create (LT, Pharmacist) · stock:* · dashboard:district ·
    #  analytics:deidentified"
    "HEALTH_ADMIN_DPM": ["user:create"] + _STOCK_STAR + ["dashboard:district", "analytics:deidentified"],

    # "registry:read · dashboard:district · analytics:deidentified,
    #  all filtered to programme"
    "PROGRAMME_OFFICER": ["registry:read", "dashboard:district", "analytics:deidentified"],

    # "system:device_manage · system:integration_manage · sync health only.
    #  No patient:*, no user:create" -- no sync:* code exists in SS8.2.
    "DISTRICT_IT_OFFICER": ["system:device_manage", "system:integration_manage"],

    # "audit:read · consent:read · consent:revoke. Nothing clinical"
    "DPO": ["audit:read", "consent:read", "consent:revoke"],

    # "teleconsult:accept/complete · patient:read (queue + consented) ·
    #  prescription:create · referral:create"
    "SPECIALIST": ["teleconsult:accept", "teleconsult:complete", "patient:read",
                   "prescription:create", "referral:create"],

    # "user:* (per matrix) · all clinical in block · dashboard:block ·
    #  referral:reassign_owner"
    "BMO": _USER_STAR + _FULL_CLINICAL + ["dashboard:block", "referral:reassign_owner"],

    # "user:create (per matrix) · full clinical at facility ·
    #  prescription:create · lab:* · dashboard:facility"
    # prescription:create and lab:* are already inside _FULL_CLINICAL;
    # their separate mention in SS8.3 is emphasis, not an addition.
    "MEDICAL_OFFICER": ["user:create"] + _FULL_CLINICAL + ["dashboard:facility"],

    # "user:create (ANM, ASHA) · patient:* · triage:* · teleconsult:request ·
    #  limited prescription:create · dashboard:facility"
    "CHO": (
        ["user:create"] + _PATIENT_STAR + _TRIAGE_STAR
        + ["teleconsult:request", "prescription:create", "dashboard:facility"]
    ),

    # "user:create (ASHA) · patient:create/read/update · triage:* ·
    #  vitals:create · registry:*"
    "ANM_MPW": (
        ["user:create", "patient:create", "patient:read", "patient:update"]
        + _TRIAGE_STAR + ["vitals:create"] + _REGISTRY_STAR
    ),

    # "lab:collect/enter_result · patient:read limited to ordered tests.
    #  lab:release_result and lab:acknowledge_critical only if flagged"
    # -- conditional grants omitted, see module docstring.
    "LAB_TECHNICIAN": ["lab:collect", "lab:enter_result", "patient:read"],

    # "prescription:dispense · stock:* · patient:read limited to the
    #  dispensing episode"
    "PHARMACIST": ["prescription:dispense"] + _STOCK_STAR + ["patient:read"],

    # "patient:create/read/update (own villages) · triage:create ·
    #  vitals:create · referral:create · registry:read/record_outcome"
    "ASHA": (
        ["patient:create", "patient:read", "patient:update", "triage:create",
         "vitals:create", "referral:create", "registry:read", "registry:record_outcome"]
    ),

    # "dashboard:facility restricted to village aggregates. No patient:*"
    "VHSNC_MEMBER": ["dashboard:facility"],

    # "patient:read (self + linked) · consent:read/revoke ·
    #  teleconsult:request · appointment booking" -- "appointment booking"
    # has no matching SS8.2 code, omitted (see module docstring).
    "PATIENT": ["patient:read", "consent:read", "consent:revoke", "teleconsult:request"],
}

# ============================================================
# role_creation_grants -- Day1.md SS18.2, verbatim for every creator
# except SUPERUSER (see module docstring for the two resolved gaps).
# (creator_role, target_role, requires_second_approver, allowed_org_unit_types)
# ============================================================
GRANTS: list[tuple[str, str, bool, list[str]]] = [
    # SUPERUSER -- 4 rows verbatim from SS18.2, 14 rows filled per the
    # confirmed rule (reuse the widest allowed_org_unit_types another
    # creator already uses for that same target). PATIENT deliberately
    # excluded (see module docstring, gap 2).
    ("SUPERUSER", "SUPERUSER", True, ["*"]),
    ("SUPERUSER", "STATE_NHM", False, ["STATE"]),
    ("SUPERUSER", "COLLECTOR", False, ["DISTRICT"]),
    ("SUPERUSER", "DHO_CMO", False, ["DISTRICT_OFFICE"]),
    ("SUPERUSER", "DISTRICT_EPIDEMIOLOGIST", False, ["DISTRICT_OFFICE"]),
    ("SUPERUSER", "HEALTH_ADMIN_DPM", False, ["DISTRICT_OFFICE"]),
    ("SUPERUSER", "PROGRAMME_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("SUPERUSER", "DISTRICT_IT_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("SUPERUSER", "DPO", False, ["DISTRICT_OFFICE", "STATE"]),
    ("SUPERUSER", "SPECIALIST", False, ["TELE_HUB", "DISTRICT_HOSPITAL"]),
    ("SUPERUSER", "BMO", False, ["BLOCK"]),
    ("SUPERUSER", "MEDICAL_OFFICER", False, ["PHC", "CHC", "SDH"]),
    ("SUPERUSER", "CHO", False, ["HWC", "SUB_CENTRE"]),
    ("SUPERUSER", "ANM_MPW", False, ["SUB_CENTRE", "HWC"]),
    ("SUPERUSER", "LAB_TECHNICIAN", False, ["PHC", "CHC", "SDH", "DISTRICT_HOSPITAL"]),
    ("SUPERUSER", "PHARMACIST", False, ["PHC", "CHC", "SDH", "DISTRICT_HOSPITAL"]),
    ("SUPERUSER", "ASHA", False, ["VILLAGE"]),
    ("SUPERUSER", "VHSNC_MEMBER", False, ["VILLAGE"]),

    # STATE_NHM -- verbatim, SS18.2.
    ("STATE_NHM", "STATE_NHM", True, ["STATE"]),
    ("STATE_NHM", "COLLECTOR", True, ["DISTRICT"]),
    ("STATE_NHM", "DHO_CMO", True, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "DPO", True, ["DISTRICT_OFFICE", "STATE"]),
    ("STATE_NHM", "DISTRICT_EPIDEMIOLOGIST", False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "HEALTH_ADMIN_DPM", False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "PROGRAMME_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "DISTRICT_IT_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "SPECIALIST", False, ["TELE_HUB", "DISTRICT_HOSPITAL"]),
    ("STATE_NHM", "BMO", False, ["BLOCK"]),
    ("STATE_NHM", "MEDICAL_OFFICER", False, ["PHC", "CHC", "SDH"]),

    # COLLECTOR -- verbatim, SS18.2.
    ("COLLECTOR", "DHO_CMO", True, ["DISTRICT_OFFICE"]),
    ("COLLECTOR", "HEALTH_ADMIN_DPM", False, ["DISTRICT_OFFICE"]),
    ("COLLECTOR", "DISTRICT_IT_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("COLLECTOR", "BMO", False, ["BLOCK"]),
    ("COLLECTOR", "VHSNC_MEMBER", False, ["VILLAGE"]),

    # DHO_CMO -- verbatim, SS18.2.
    ("DHO_CMO", "DISTRICT_EPIDEMIOLOGIST", False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "HEALTH_ADMIN_DPM", False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "PROGRAMME_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "DISTRICT_IT_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "DPO", True, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "SPECIALIST", False, ["TELE_HUB", "DISTRICT_HOSPITAL"]),
    ("DHO_CMO", "BMO", False, ["BLOCK"]),
    ("DHO_CMO", "MEDICAL_OFFICER", False, ["PHC", "CHC", "SDH"]),
    ("DHO_CMO", "CHO", False, ["HWC", "SUB_CENTRE"]),
    ("DHO_CMO", "ANM_MPW", False, ["SUB_CENTRE", "HWC"]),
    ("DHO_CMO", "LAB_TECHNICIAN", False, ["PHC", "CHC", "SDH", "DISTRICT_HOSPITAL"]),
    ("DHO_CMO", "PHARMACIST", False, ["PHC", "CHC", "SDH", "DISTRICT_HOSPITAL"]),
    ("DHO_CMO", "ASHA", False, ["VILLAGE"]),
    ("DHO_CMO", "VHSNC_MEMBER", False, ["VILLAGE"]),

    # HEALTH_ADMIN_DPM -- verbatim, SS18.2.
    ("HEALTH_ADMIN_DPM", "LAB_TECHNICIAN", False, ["PHC", "CHC", "SDH", "DISTRICT_HOSPITAL"]),
    ("HEALTH_ADMIN_DPM", "PHARMACIST", False, ["PHC", "CHC", "SDH", "DISTRICT_HOSPITAL"]),

    # BMO -- verbatim, SS18.2.
    ("BMO", "MEDICAL_OFFICER", False, ["PHC", "CHC"]),
    ("BMO", "CHO", False, ["HWC", "SUB_CENTRE"]),
    ("BMO", "ANM_MPW", False, ["SUB_CENTRE", "HWC"]),
    ("BMO", "LAB_TECHNICIAN", False, ["PHC", "CHC"]),
    ("BMO", "PHARMACIST", False, ["PHC", "CHC"]),
    ("BMO", "ASHA", False, ["VILLAGE"]),
    ("BMO", "VHSNC_MEMBER", False, ["VILLAGE"]),

    # MEDICAL_OFFICER -- verbatim, SS18.2.
    ("MEDICAL_OFFICER", "CHO", False, ["HWC", "SUB_CENTRE"]),
    ("MEDICAL_OFFICER", "ANM_MPW", False, ["SUB_CENTRE", "HWC"]),
    ("MEDICAL_OFFICER", "LAB_TECHNICIAN", False, ["PHC", "CHC"]),
    ("MEDICAL_OFFICER", "PHARMACIST", False, ["PHC", "CHC"]),
    ("MEDICAL_OFFICER", "ASHA", False, ["VILLAGE"]),

    # CHO -- verbatim, SS18.2.
    ("CHO", "ANM_MPW", False, ["SUB_CENTRE", "HWC"]),
    ("CHO", "ASHA", False, ["VILLAGE"]),

    # ANM_MPW -- verbatim, SS18.2.
    ("ANM_MPW", "ASHA", False, ["VILLAGE"]),

    # Deliberately absent (SS18.2's own note): DISTRICT_EPIDEMIOLOGIST,
    # PROGRAMME_OFFICER, DISTRICT_IT_OFFICER, DPO, SPECIALIST,
    # LAB_TECHNICIAN, PHARMACIST, ASHA, VHSNC_MEMBER, PATIENT as
    # creators -- these roles create nobody.
]


def upgrade() -> None:
    conn = op.get_bind()

    for code, display_name, level, self_register, is_clinical in ROLES:
        # ON CONFLICT DO UPDATE, not DO NOTHING: migration 9d5f6b3e0a71
        # already bootstrapped a minimal SUPERUSER row (display_name
        # 'Superuser', just enough to satisfy an FK) before this seed
        # runs. This seed's SS1-sourced values are authoritative, so
        # they must overwrite that placeholder rather than lose to it.
        conn.execute(
            sa.text(
                "INSERT INTO roles (code, display_name, level, self_register, is_clinical) "
                "VALUES (:code, :display_name, :level, :self_register, :is_clinical) "
                "ON CONFLICT (code) DO UPDATE SET "
                "display_name = EXCLUDED.display_name, "
                "level = EXCLUDED.level, "
                "self_register = EXCLUDED.self_register, "
                "is_clinical = EXCLUDED.is_clinical"
            ),
            {"code": code, "display_name": display_name, "level": level,
             "self_register": self_register, "is_clinical": is_clinical},
        )

    for code in PERMISSIONS:
        conn.execute(
            sa.text("INSERT INTO permissions (code) VALUES (:code) ON CONFLICT (code) DO NOTHING"),
            {"code": code},
        )

    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        for perm_code in perm_codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_code, permission_code) "
                    "VALUES (:role_code, :perm_code) "
                    "ON CONFLICT (role_code, permission_code) DO NOTHING"
                ),
                {"role_code": role_code, "perm_code": perm_code},
            )

    for creator_role, target_role, requires_second_approver, allowed_org_unit_types in GRANTS:
        conn.execute(
            sa.text(
                "INSERT INTO role_creation_grants "
                "(creator_role, target_role, requires_second_approver, allowed_org_unit_types) "
                "VALUES (:creator_role, :target_role, :requires_second_approver, :allowed_types) "
                "ON CONFLICT (creator_role, target_role) DO NOTHING"
            ),
            {"creator_role": creator_role, "target_role": target_role,
             "requires_second_approver": requires_second_approver,
             "allowed_types": allowed_org_unit_types},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # Only role_creation_grants and role_permissions are removed here.
    # roles and permissions are deliberately left in place -- confirmed
    # by testing: migration 9d5f6b3e0a71's bootstrap system attribution
    # user has role='SUPERUSER', so `DELETE FROM roles WHERE
    # code='SUPERUSER'` fails on users_role_fkey (ForeignKeyViolation),
    # and the whole downgrade rolled back. This is the same "don't tear
    # down foundational rows other data may depend on" reasoning already
    # applied to app_user's role in 8c4e29a7d1f0's downgrade -- roles/
    # permissions are reference data other rows can legitimately point
    # at, not objects exclusively owned by this migration.
    for creator_role, target_role, _, _ in GRANTS:
        conn.execute(
            sa.text(
                "DELETE FROM role_creation_grants "
                "WHERE creator_role = :c AND target_role = :t"
            ),
            {"c": creator_role, "t": target_role},
        )
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        for perm_code in perm_codes:
            conn.execute(
                sa.text(
                    "DELETE FROM role_permissions "
                    "WHERE role_code = :r AND permission_code = :p"
                ),
                {"r": role_code, "p": perm_code},
            )
