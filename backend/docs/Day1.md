# Day 1 — Role-Based Identity, Registration & Access Control

**SETU-Swasthya Backend · Specification & Implementation Guide**

| Field | Value |
|---|---|
| Document | `Day1.md` |
| Scope | Identity, registration, role hierarchy, creation authority, RBAC, session security, audit |
| Extends | `SETU_Swasthya_Iqra_Pre_Day2_ONLY_Clean_Checklist.pdf` |
| Stack | FastAPI · SQLModel · PostgreSQL 15+ · Alembic · python-jose (JWT) · passlib[argon2] · Docker |
| Branch | `backend` |
| Owners | Iqra Khan (backend developer) |

---

## 0. The two rules this document exists to enforce

> **RULE 1 — Only a Patient may self-register.**
> There is exactly one public registration endpoint in the entire system: `POST /auth/patient/register`. It is protected by mobile OTP. No other role can be created from outside an authenticated session.

> **RULE 2 — Every staff account is created by a higher official.**
> A staff user cannot exist unless an authenticated user with creation authority over that role, and organisational scope over that posting, created it. If no such creator exists, the account cannot be created. There is no fallback, no self-service path, and no "admin signup" page.

**Consequence for the superuser:** `SUPERUSER` sits above the entire chain and may create any role at any org unit. That is the bootstrap escape hatch and the disaster-recovery path. It is also the single most dangerous credential in the system, so §9 treats it accordingly.

**Non-negotiable additive rule (from the Pre-Day 2 checklist):** Day 1 endpoints already built and documented in `backend/docs/API_CONTRACT.md` — `/health`, `/patients/`, `/patients/{id}`, `/triage/`, `/referrals/`, `/referrals/{id}/status`, `/sync/`, `/login`, `/me` — **must not be renamed or have their payload fields changed.** Everything in this document is added alongside them. `/login` and `/me` remain as permanent aliases of `/auth/login` and `/auth/me`.

---

## Table of Contents

1. [Role taxonomy](#1-role-taxonomy)
2. [Management hierarchy — who manages whom](#2-management-hierarchy--who-manages-whom)
3. [Creation authority matrix](#3-creation-authority-matrix)
4. [Organisational scope model](#4-organisational-scope-model)
5. [Registration field specification — every role](#5-registration-field-specification--every-role)
6. [Account lifecycle](#6-account-lifecycle)
7. [The invitation flow](#7-the-invitation-flow)
8. [Permission model](#8-permission-model)
9. [Superuser and bootstrap](#9-superuser-and-bootstrap)
10. [Authentication and session security](#10-authentication-and-session-security)
11. [Data protection and encryption](#11-data-protection-and-encryption)
12. [Audit logging](#12-audit-logging)
13. [Database schema](#13-database-schema)
14. [API surface](#14-api-surface)
15. [Validation rules](#15-validation-rules)
16. [Error contract](#16-error-contract)
17. [Alembic migration plan](#17-alembic-migration-plan)
18. [Seed data](#18-seed-data)
19. [Smoke tests](#19-smoke-tests)
20. [Security threat model](#20-security-threat-model)
21. [Definition of Done](#21-definition-of-done)

---

## 1. Role taxonomy

Nineteen roles across eight layers. `level` is an integer used for fast hierarchy comparison; **it is a convenience, not the authorisation mechanism** — authorisation is the explicit grant table in §3.

| Layer | Role code | Display name | Level | Self-register | Clinical | PHI access |
|---|---|---|---|:--:|:--:|---|
| System / Governance | `SUPERUSER` | System Administrator | 0 | ✗ | ✗ | Break-glass, logged |
| Leadership & Oversight | `STATE_NHM` | State NHM / Directorate | 1 | ✗ | ✗ | Aggregate only |
| Leadership & Oversight | `COLLECTOR` | District Magistrate / Collector | 2 | ✗ | ✗ | Aggregate only |
| District Management | `DHO_CMO` | DHO / CMO / CMHO | 3 | ✗ | ✓ | District subtree |
| District Management | `DISTRICT_EPIDEMIOLOGIST` | District Epidemiologist / Public Health Analyst | 4 | ✗ | ✗ | De-identified + line-list on approval |
| District Management | `HEALTH_ADMIN_DPM` | Health Administrator / DPM / DPMU | 4 | ✗ | ✗ | Aggregate + operational |
| District Management | `PROGRAMME_OFFICER` | District Programme Officer (RCH/NCD/TB/Imm.) | 4 | ✗ | ✗ | Programme cohort only |
| District Management | `DISTRICT_IT_OFFICER` | District IT Officer | 4 | ✗ | ✗ | **None by default** |
| System / Governance | `DPO` | Data Protection Officer | 4 | ✗ | ✗ | Audit + consent only |
| Specialist / Tele-hub | `SPECIALIST` | Specialist (OBG, Med, Paed, Psy, Derm, Ophth, Ortho) | 4 | ✗ | ✓ | Consult queue + consented history |
| Supervisory / Block | `BMO` | Block Medical Officer (BMO / MOIC) | 5 | ✗ | ✓ | Block subtree |
| Facility Clinical | `MEDICAL_OFFICER` | Medical Officer (MO / MOIC) — PHC | 6 | ✗ | ✓ | Facility + referred-in |
| Facility Clinical | `CHO` | Community Health Officer | 7 | ✗ | ✓ | HWC catchment |
| Field / Community | `ANM_MPW` | ANM / MPW | 8 | ✗ | ✓ | Sub-centre catchment |
| Facility Clinical | `LAB_TECHNICIAN` | Lab Technician | 8 | ✗ | ✓ | Lab orders only |
| Facility Clinical | `PHARMACIST` | Pharmacist | 8 | ✗ | ✓ | Prescriptions + stock only |
| Field / Community | `ASHA` | ASHA | 9 | ✗ | ✓ | Own village population |
| Patient / Community | `VHSNC_MEMBER` | VHSNC / PRI (Panchayat) member | 10 | ✗ | ✗ | Village aggregate only |
| Patient / Community | `PATIENT` | Patient / family | 99 | **✓** | ✗ | Own + linked family records |

```python
# app/models/enums.py
from enum import Enum

class RoleCode(str, Enum):
    SUPERUSER                = "SUPERUSER"
    STATE_NHM                = "STATE_NHM"
    COLLECTOR                = "COLLECTOR"
    DHO_CMO                  = "DHO_CMO"
    DISTRICT_EPIDEMIOLOGIST  = "DISTRICT_EPIDEMIOLOGIST"
    HEALTH_ADMIN_DPM         = "HEALTH_ADMIN_DPM"
    PROGRAMME_OFFICER        = "PROGRAMME_OFFICER"
    DISTRICT_IT_OFFICER      = "DISTRICT_IT_OFFICER"
    DPO                      = "DPO"
    SPECIALIST               = "SPECIALIST"
    BMO                      = "BMO"
    MEDICAL_OFFICER          = "MEDICAL_OFFICER"
    CHO                      = "CHO"
    ANM_MPW                  = "ANM_MPW"
    LAB_TECHNICIAN           = "LAB_TECHNICIAN"
    PHARMACIST               = "PHARMACIST"
    ASHA                     = "ASHA"
    VHSNC_MEMBER             = "VHSNC_MEMBER"
    PATIENT                  = "PATIENT"

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
```

---

## 2. Management hierarchy — who manages whom

### 2.1 The management tree

```
                            ┌──────────────────────────────┐
                            │        SUPERUSER             │  L0
                            │  System Administrator        │
                            │  (bootstrap · may create ANY │
                            │   role at ANY org unit)      │
                            └──────────────┬───────────────┘
                                           │ creates
                                           ▼
                            ┌──────────────────────────────┐
                            │        STATE_NHM             │  L1
                            │  State NHM / Directorate     │
                            └──────────────┬───────────────┘
                                           │ creates
                                           ▼
                            ┌──────────────────────────────┐
                            │        COLLECTOR             │  L2
                            │  District Magistrate         │
                            └──────────────┬───────────────┘
                                           │ creates
                                           ▼
                            ┌──────────────────────────────┐
                            │         DHO_CMO              │  L3
                            │  District Health Officer /   │
                            │  CMO / CMHO                  │
                            └──────────────┬───────────────┘
                                           │ creates
        ┌───────────┬───────────┬──────────┼──────────┬───────────┬──────────┐
        ▼           ▼           ▼          ▼          ▼           ▼          ▼
  ┌──────────┐┌──────────┐┌─────────┐┌─────────┐┌─────────┐┌──────────┐┌──────────┐
  │ DISTRICT ││  HEALTH  ││PROGRAMME││DISTRICT ││   DPO   ││SPECIALIST││   BMO    │
  │  EPIDEM. ││ADMIN_DPM ││ OFFICER ││IT_OFFICER││  (L4)   ││   (L4)   ││  (L5)   │
  │   (L4)   ││   (L4)   ││  (L4)   ││  (L4)   ││ ⚠ dual  ││          ││          │
  └──────────┘└──────────┘└─────────┘└─────────┘└──────────┘└──────────┘└────┬────┘
                                                                              │ creates
                                                          ┌───────────────────┼──────────────┐
                                                          ▼                   ▼              ▼
                                                  ┌───────────────┐   ┌──────────────┐  ┌──────────┐
                                                  │MEDICAL_OFFICER│   │ VHSNC_MEMBER │  │(re-post  │
                                                  │     (L6)      │   │    (L10)     │  │ CHO/MO)  │
                                                  └───────┬───────┘   └──────────────┘  └──────────┘
                                                          │ creates
                              ┌───────────────────────────┼───────────────────────────┐
                              ▼                           ▼                           ▼
                      ┌───────────────┐          ┌────────────────┐          ┌──────────────┐
                      │      CHO      │          │ LAB_TECHNICIAN │          │  PHARMACIST  │
                      │     (L7)      │          │      (L8)      │          │     (L8)     │
                      └───────┬───────┘          └────────────────┘          └──────────────┘
                              │ creates
                    ┌─────────┴─────────┐
                    ▼                   ▼
            ┌───────────────┐   ┌──────────────┐
            │   ANM_MPW     │   │     ASHA     │
            │     (L8)      │   │     (L9)     │
            └───────┬───────┘   └──────────────┘
                    │ creates
                    ▼
            ┌───────────────┐
            │     ASHA      │
            │     (L9)      │
            └───────────────┘


  ═══════════════════════════════════════════════════════════════════════════
                      OUTSIDE THE MANAGEMENT CHAIN
  ═══════════════════════════════════════════════════════════════════════════

            ┌──────────────────────────────────────────────┐
            │                  PATIENT  (L99)              │
            │                                              │
            │   SELF-REGISTERS via POST /auth/patient/     │
            │   register, verified by mobile OTP.          │
            │                                              │
            │   created_by = NULL  ·  reports_to = NULL    │
            │                                              │
            │   May optionally be assisted-registered by   │
            │   ASHA / ANM / CHO / MO, in which case       │
            │   created_by = that worker and consent mode  │
            │   is recorded as ASSISTED.                   │
            └──────────────────────────────────────────────┘
```

### 2.2 Same tree as Mermaid (renders on GitHub / GitLab)

```mermaid
graph TD
    SU["SUPERUSER · L0<br/>System Administrator"]
    ST["STATE_NHM · L1"]
    DM["COLLECTOR · L2<br/>District Magistrate"]
    DHO["DHO_CMO · L3<br/>District Health Officer"]

    EPI["DISTRICT_EPIDEMIOLOGIST · L4"]
    DPM["HEALTH_ADMIN_DPM · L4"]
    PO["PROGRAMME_OFFICER · L4"]
    ITO["DISTRICT_IT_OFFICER · L4"]
    DPO["DPO · L4<br/>needs dual approval"]
    SPE["SPECIALIST · L4"]
    BMO["BMO · L5<br/>Block Medical Officer"]

    MO["MEDICAL_OFFICER · L6<br/>PHC"]
    VH["VHSNC_MEMBER · L10"]

    CHO["CHO · L7"]
    LT["LAB_TECHNICIAN · L8"]
    PH["PHARMACIST · L8"]

    ANM["ANM_MPW · L8"]
    ASHA["ASHA · L9"]

    PAT["PATIENT · L99<br/>SELF-REGISTERS<br/>no creator"]

    SU -->|creates any role| ST
    ST --> DM
    DM --> DHO
    DHO --> EPI
    DHO --> DPM
    DHO --> PO
    DHO --> ITO
    DHO --> DPO
    DHO --> SPE
    DHO --> BMO
    BMO --> MO
    BMO --> VH
    MO --> CHO
    MO --> LT
    MO --> PH
    CHO --> ANM
    CHO --> ASHA
    ANM --> ASHA

    PAT -.->|"outside the chain<br/>OTP self-registration"| PAT
```

### 2.3 Reading the tree

- **A solid arrow means "may create and manages."** The parent is the default `reports_to` for the child.
- **A role may always create roles its own parent could create at or below its own level, only within its own org scope.** For example a `DHO_CMO` may directly create an `ASHA` in an emergency; a `CHO` may never create an `MEDICAL_OFFICER`.
- **`SUPERUSER` bypasses the tree entirely** for creation, and only for creation. It does not silently acquire clinical data access (see §9.3).
- **`PATIENT` has no parent.** `created_by` is `NULL` for self-registration. Assisted registration sets `created_by` to the assisting worker but never establishes a management relationship — a patient is not managed by anyone.

### 2.4 Why the tree is not the authorisation mechanism

A tree alone would let any ancestor create any descendant, which is too permissive. `DISTRICT_IT_OFFICER` sits at L4 but must never create clinical staff. The tree describes *reporting*; §3 describes *authority*. Both are enforced, and both must pass.

---

## 3. Creation authority matrix

This table is the authoritative source. It is stored in the database as `role_creation_grants` rather than hard-coded, so it can be audited, queried and changed by migration — never by editing a Python dict in production.

Legend: **✓** = may create · **✓✓** = may create, requires a second approver · **—** = may not create

| Creator ↓ / Target → | SUPER | STATE | COLL | DHO | EPI | DPM | PROG | ITO | DPO | SPEC | BMO | MO | CHO | ANM | LT | PHARM | ASHA | VHSNC | PATIENT |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **SUPERUSER** | ✓✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **STATE_NHM** | — | ✓✓ | ✓✓ | ✓✓ | ✓ | ✓ | ✓ | ✓ | ✓✓ | ✓ | ✓ | ✓ | — | — | — | — | — | — | — |
| **COLLECTOR** | — | — | — | ✓✓ | — | ✓ | — | ✓ | — | — | ✓ | — | — | — | — | — | — | ✓ | — |
| **DHO_CMO** | — | — | — | — | ✓ | ✓ | ✓ | ✓ | ✓✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| **DISTRICT_EPIDEMIOLOGIST** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **HEALTH_ADMIN_DPM** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | — | — | — |
| **PROGRAMME_OFFICER** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **DISTRICT_IT_OFFICER** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **DPO** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **SPECIALIST** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **BMO** | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| **MEDICAL_OFFICER** | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| **CHO** | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | ✓ | — | — |
| **ANM_MPW** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — |
| **LAB_TECHNICIAN** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **PHARMACIST** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **ASHA** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **VHSNC_MEMBER** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **PATIENT** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **(unauthenticated)** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | **✓ self** |

### 3.1 Design decisions embedded in this matrix

| Decision | Reason |
|---|---|
| Seven roles can create **nothing** — Epidemiologist, Programme Officer, IT Officer, DPO, Specialist, LT, Pharmacist, ASHA, VHSNC, Patient | Least privilege. An analyst does not need to mint accounts, and an account-minting analyst is an attractive compromise target. |
| `DISTRICT_IT_OFFICER` creates nothing | The person with server access must not also be able to create clinical identities. Separating those two powers is what stops a single compromised admin from becoming a silent clinical actor. |
| `DPO` creates nothing and needs dual approval to be created | The Data Protection Officer audits the system. If they could create accounts, they would be auditing themselves. |
| `DPO` and all L≤3 roles require a second approver (`✓✓`) | Two-person rule on high-privilege accounts. A single compromised DHO session cannot mint a second DHO. |
| `HEALTH_ADMIN_DPM` may create only LT and Pharmacist | The DPM owns logistics and diagnostics operations; that is the entire justification, so that is the entire grant. |
| `ANM_MPW` may create `ASHA` | The ANM is the ASHA's day-to-day supervisor in practice. Requiring a CHO for every ASHA onboarding would put the onboarding into a queue and the ASHA would work unregistered. |
| `COLLECTOR` may create `VHSNC_MEMBER` | Panchayat nominations route through the district administration. |
| Nobody may create `PATIENT` except assisted-registration, which is a different endpoint | Patient identity is consent-bearing. It is created *with* the patient, never *for* them. |

### 3.2 Enforcement — all four gates must pass

```python
# app/core/authz.py
from uuid import UUID
from app.models.enums import RoleCode, ROLE_LEVEL

class CreationDenied(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail


async def assert_can_create_user(
    session, actor, target_role: RoleCode, target_org_unit_id: UUID
) -> bool:
    """
    Four independent gates. All must pass. Order matters: cheapest and most
    common failure first, so a probing attacker learns as little as possible.
    """

    # GATE 1 — the actor's account must itself be usable
    if actor.status != "ACTIVE":
        raise CreationDenied("ACTOR_NOT_ACTIVE", "Your account is not active.")
    if actor.mfa_required and not actor.mfa_enrolled:
        raise CreationDenied("MFA_REQUIRED", "Enrol MFA before creating users.")

    # GATE 2 — an explicit grant row must exist. No implicit level comparison.
    grant = await get_creation_grant(session, actor.role, target_role)
    if grant is None:
        raise CreationDenied(
            "ROLE_NOT_CREATABLE",
            f"{actor.role} may not create {target_role}.",
        )

    # GATE 3 — org scope containment. The target posting must sit inside the
    # actor's subtree. A Rampur BMO cannot create staff in Bilhaur block.
    if not await org_unit_is_within_scope(session, target_org_unit_id, actor.scope_org_unit_id):
        raise CreationDenied(
            "OUT_OF_SCOPE",
            "That posting is outside the area you manage.",
        )

    # GATE 4 — level sanity. Belt-and-braces against a bad grant row.
    # SUPERUSER is the only role permitted to create at its own level.
    if actor.role != RoleCode.SUPERUSER:
        if ROLE_LEVEL[target_role] <= ROLE_LEVEL[actor.role]:
            raise CreationDenied(
                "LEVEL_VIOLATION",
                "You cannot create a role at or above your own level.",
            )

    return grant.requires_second_approver
```

**Why Gate 4 exists even though Gate 2 already passed.** A future migration could insert a wrong grant row. Gate 4 turns that data error into a rejected request rather than a privilege escalation. Defence in depth means a single mistake is never sufficient.

### 3.3 Driving the frontend from the matrix

The frontend must never hard-code which roles a user may create — that would drift from the backend and produce confusing 403s.

```
GET /users/creatable-roles
Authorization: Bearer <access_token>

200 OK
{
  "creatable_roles": [
    {
      "role": "CHO",
      "display_name": "Community Health Officer",
      "requires_second_approver": false,
      "allowed_org_unit_types": ["HWC", "SUB_CENTRE"],
      "schema_url": "/users/registration-schema/CHO"
    },
    {
      "role": "ANM_MPW",
      "display_name": "ANM / MPW",
      "requires_second_approver": false,
      "allowed_org_unit_types": ["SUB_CENTRE"],
      "schema_url": "/users/registration-schema/ANM_MPW"
    },
    {
      "role": "ASHA",
      "display_name": "ASHA",
      "requires_second_approver": false,
      "allowed_org_unit_types": ["VILLAGE"],
      "schema_url": "/users/registration-schema/ASHA"
    }
  ]
}
```

An authenticated `ASHA` calling this endpoint receives `{"creatable_roles": []}` — a valid, non-error response. The frontend hides the "Add user" button. The backend would refuse anyway.

---

## 4. Organisational scope model

Every user is pinned to exactly one `org_unit`. Authorisation asks two questions: *what may you do* (role) and *where may you do it* (scope).

### 4.1 Hierarchy

```
STATE  (Uttar Pradesh)
  └── DISTRICT  (Kanpur Nagar)
        └── BLOCK  (Rampur)
              ├── PHC  (Rampur PHC)            ← MEDICAL_OFFICER, LAB_TECHNICIAN, PHARMACIST
              │     └── SUB_CENTRE / HWC  (Nai Basti HWC)   ← CHO, ANM_MPW
              │           └── VILLAGE  (Nai Basti)          ← ASHA, VHSNC_MEMBER, PATIENT
              ├── CHC  (Rampur CHC)
              └── ...
        └── DISTRICT_HOSPITAL  (Kanpur DH)     ← SPECIALIST
        └── TELE_HUB  (Kanpur Tele-hub)        ← SPECIALIST
        └── DISTRICT_OFFICE                    ← DHO_CMO, EPI, DPM, PROG, ITO, DPO
```

### 4.2 Materialised path for O(1) subtree checks

A recursive CTE per request is too slow when every endpoint does a scope check. Store the path.

```sql
CREATE TABLE org_units (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       UUID REFERENCES org_units(id) ON DELETE RESTRICT,
    unit_type       org_unit_type NOT NULL,
    name            TEXT NOT NULL,
    name_local      TEXT,
    lgd_code        TEXT,                     -- Local Government Directory
    hfr_id          TEXT,                     -- ABDM Health Facility Registry
    path            TEXT NOT NULL,            -- '/UP/KANPUR/RAMPUR/PHC001/SC004/V0012'
    depth           SMALLINT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (parent_id, name),
    CONSTRAINT chk_path_starts_slash CHECK (path LIKE '/%')
);

CREATE INDEX idx_org_units_path        ON org_units (path text_pattern_ops);
CREATE INDEX idx_org_units_parent      ON org_units (parent_id);
CREATE UNIQUE INDEX idx_org_units_lgd  ON org_units (lgd_code) WHERE lgd_code IS NOT NULL;
CREATE UNIQUE INDEX idx_org_units_hfr  ON org_units (hfr_id)   WHERE hfr_id IS NOT NULL;
```

```python
async def org_unit_is_within_scope(session, target_id: UUID, actor_scope_id: UUID) -> bool:
    """True if target is the actor's own unit or any descendant of it."""
    rows = await session.exec(
        select(OrgUnit.id, OrgUnit.path).where(OrgUnit.id.in_([target_id, actor_scope_id]))
    )
    paths = {r.id: r.path for r in rows}
    target_path, actor_path = paths.get(target_id), paths.get(actor_scope_id)
    if target_path is None or actor_path is None:
        return False
    return target_path == actor_path or target_path.startswith(actor_path.rstrip("/") + "/")
```

**Trailing-slash bug to avoid.** Without `rstrip("/") + "/"`, the path `/UP/KANPUR2` would match the prefix `/UP/KANPUR` and a Kanpur Nagar officer would silently gain scope over Kanpur Dehat. Write the regression test for this before you write the function.

### 4.3 Additional scopes

Some roles need scope narrower or wider than their org unit. Stored as a JSONB column `scope_extras`.

| Role | Extra scope |
|---|---|
| `ASHA` | `{"village_ids": [...]}` — may cover 1–3 villages, not the whole sub-centre |
| `ANM_MPW` | `{"village_ids": [...]}` — sub-centre catchment |
| `SPECIALIST` | `{"specialties": ["OBG"], "tele_hub_ids": [...]}` — sees consult queue across the district, not one facility |
| `PROGRAMME_OFFICER` | `{"programmes": ["RCH"]}` — district-wide but one programme cohort |
| `PATIENT` | `{"linked_patient_ids": [...]}` — self plus consented family members |

---

## 5. Registration field specification — every role

### 5.1 How the forms differ

Every staff role shares a **common core**. Each role then adds a **role-specific block**. The API exposes the composed schema at `GET /users/registration-schema/{role}`, so the frontend renders a different form per role without hard-coding any of it.

```
POST /users
{
  "role": "CHO",
  "common": { ...COMMON CORE FIELDS... },
  "posting": { ...POSTING FIELDS... },
  "profile": { ...ROLE-SPECIFIC BLOCK, validated by a discriminated union... }
}
```

Pydantic validates `profile` against the correct model using `role` as the discriminator, so sending `ASHA` fields under `role: "CHO"` is a `422`, not a silently accepted record.

### 5.2 Common core — every staff role

| Field | Type | Required | Validation | Notes |
|---|---|:--:|---|---|
| `full_name` | str | ✓ | 2–120 chars, letters/space/`.`/`-`/`'` | |
| `full_name_local` | str | ✗ | 2–120 chars | Devanagari or local script |
| `mobile` | str | ✓ | E.164, `^\+91[6-9]\d{9}$` | **Unique across all users.** Login identifier. Stored encrypted + blind index |
| `email` | str | ✗ (✓ for L≤5) | RFC 5322, unique | Required for supervisory and above |
| `date_of_birth` | date | ✓ | ≥18 years, ≤70 years | |
| `sex` | enum | ✓ | `FEMALE` `MALE` `OTHER` | |
| `preferred_language` | enum | ✓ | ISO 639-1 from enabled set | Drives all notifications |
| `employee_code` | str | ✗ (✓ for L≤6) | Unique per state | Government service ID |
| `designation` | str | ✓ | 2–80 chars | Free text as printed on the posting order |
| `joining_date` | date | ✓ | ≤ today + 30 days | Post-dated postings permitted |
| `id_proof_type` | enum | ✓ | `PAN` `VOTER_ID` `DL` `PASSPORT` `SERVICE_ID` | **`AADHAAR` is deliberately not an option — see §11.4** |
| `id_proof_last4` | str | ✓ | exactly 4 digits | Only the last 4, never the full number |
| `photo_object_key` | str | ✗ | object-store key | Never a base64 blob in the request body |

### 5.3 Posting block — every staff role

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `org_unit_id` | UUID | ✓ | Must exist, be active, be within the creator's scope, and have a `unit_type` allowed for the role |
| `reports_to_user_id` | UUID | ✗ | Defaults to the creator. If given, must be an active user whose role may create this role |
| `posting_order_ref` | str | ✗ (✓ for L≤5) | Government order number authorising the posting |
| `posting_order_date` | date | ✗ (✓ for L≤5) | ≤ today |
| `is_officer_in_charge` | bool | ✗ | Only meaningful for `MEDICAL_OFFICER` and `BMO` |
| `valid_until` | date | ✗ | Auto-suspends on expiry. Use for deputation and temporary charge |

### 5.4 Role-specific blocks

---

#### `PATIENT` — the only self-registration

**Endpoint:** `POST /auth/patient/register` · **Auth:** public, OTP-verified

| Field | Type | Required | Validation | Notes |
|---|---|:--:|---|---|
| `full_name` | str | ✓ | 2–120 chars | |
| `full_name_local` | str | ✗ | | |
| `date_of_birth` | date | ○ | ≤ today, ≥120 years ago | **One of `date_of_birth` or `age_years` required** |
| `age_years` | int | ○ | 0–120 | Sets `age_is_estimated = true` |
| `sex` | enum | ✓ | `FEMALE` `MALE` `OTHER` | |
| `mobile` | str | ✓ | E.164 | Must match the OTP-verified number |
| `is_shared_phone` | bool | ✓ | default `false` | Household phones are the norm; model it |
| `abha_number` | str | ✗ | 14 digits, Verhoeff checksum | |
| `abha_address` | str | ✗ | `name@sbx` format | |
| `village_lgd_code` | str | ✓ | must exist in `org_units` | |
| `hamlet` | str | ✗ | ≤80 chars | |
| `house_number` | str | ✗ | ≤20 chars | |
| `household_id` | UUID | ✗ | must exist | Links family members |
| `preferred_language` | enum | ✓ | | |
| `guardian_name` | str | ○ | **required if age < 18** | |
| `guardian_relation` | enum | ○ | **required if age < 18** | `MOTHER` `FATHER` `GUARDIAN` |
| `guardian_mobile` | str | ○ | **required if age < 18** | |
| `emergency_contact_name` | str | ✗ | | |
| `emergency_contact_mobile` | str | ✗ | | |
| `consent_keep_record` | bool | ✓ | | Four independent consents |
| `consent_share_specialist` | bool | ✓ | | |
| `consent_share_facility` | bool | ✓ | | |
| `consent_anonymised_planning` | bool | ✓ | | |
| `consent_mode` | enum | ✓ | `DIGITAL_SELF` `SPOKEN_WITNESSED` `THUMB_IMPRESSION` | |
| `otp_token` | str | ✓ | single-use, 5-min TTL | Proves phone possession |

**Critical rule.** All four consents may be `false`. Registration still succeeds and the patient still receives care. Refusing consent must never be harder than granting it, and must never block account creation. Enforce with a test.

**Assisted registration.** A worker registering a patient in the field uses `POST /patients/` (the existing Day 1 endpoint, unchanged), which now additionally writes a `users` row with `role = PATIENT`, `created_by = <worker>`, `consent_mode = SPOKEN_WITNESSED`, and no credentials. The patient may later claim the account via OTP on their own number.

---

#### `ASHA`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `asha_state_code` | str | ✓ | Unique per state; the ASHA's official code |
| `village_lgd_codes` | list[str] | ✓ | 1–3 entries, each must exist and sit under the parent sub-centre |
| `sub_centre_org_unit_id` | UUID | ✓ | `unit_type` in (`SUB_CENTRE`, `HWC`) |
| `population_covered` | int | ✓ | 100–3000 |
| `education_level` | enum | ✓ | `CLASS_8` `CLASS_10` `CLASS_12` `GRADUATE` `OTHER` |
| `induction_training_completed` | bool | ✓ | |
| `training_modules_completed` | list[str] | ✗ | e.g. `["MODULE_6","MODULE_7","HBNC"]` |
| `incentive_account_token` | str | ✗ | Tokenised bank reference. **Never store an account number** |
| `device_issued` | bool | ✗ | |
| `device_imei` | str | ✗ | 15 digits, Luhn |
| `works_offline_primarily` | bool | ✓ | Drives sync policy and OTP-over-SMS login preference |

**Login method:** mobile + OTP (no password). ASHAs share and change devices; a memorised password is a support burden and gets written on the phone case.

---

#### `ANM_MPW`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `council_registration_number` | str | ✓ | State Nursing Council; unique |
| `council_name` | str | ✓ | e.g. `UP Nurses and Midwives Council` |
| `council_registration_expiry` | date | ✓ | **> today; expiry auto-suspends clinical scope** |
| `qualification` | enum | ✓ | `ANM` `GNM` `BSC_NURSING` `MPW_MALE` |
| `sub_centre_org_unit_id` | UUID | ✓ | |
| `village_lgd_codes` | list[str] | ✓ | 1–10 |
| `is_immunisation_certified` | bool | ✓ | Gates immunisation endpoints |
| `is_sba_certified` | bool | ✗ | Skilled Birth Attendant |

---

#### `CHO`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `hpr_id` | str | ✓ | ABDM Healthcare Professionals Registry ID; **verified against HPR before activation** |
| `cch_certificate_number` | str | ✓ | Certificate in Community Health |
| `council_registration_number` | str | ✓ | Nursing or AYUSH council |
| `council_registration_expiry` | date | ✓ | > today |
| `base_qualification` | enum | ✓ | `BSC_NURSING` `GNM` `BAMS` `POST_BASIC_BSC` |
| `hwc_org_unit_id` | UUID | ✓ | `unit_type = HWC` |
| `teleconsult_enabled` | bool | ✓ | May facilitate an assisted teleconsultation |
| `dispensing_scope` | list[str] | ✓ | Drug categories permitted at HWC level |

---

#### `MEDICAL_OFFICER`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `hpr_id` | str | ✓ | HPR-verified before activation |
| `medical_council_registration_number` | str | ✓ | Unique |
| `medical_council_name` | str | ✓ | NMC or State Medical Council |
| `registration_expiry` | date | ✓ | **> today; expiry auto-suspends prescribing** |
| `qualification` | enum | ✓ | `MBBS` `MD` `MS` `DNB` `BAMS` `BHMS` |
| `qualification_year` | int | ✓ | 1960 ≤ y ≤ current year |
| `facility_org_unit_id` | UUID | ✓ | `unit_type` in (`PHC`,`CHC`,`SDH`) |
| `is_moic` | bool | ✓ | Officer-in-charge flag |
| `prescribing_scope` | list[str] | ✓ | Drug schedules permitted. **Schedule X and narcotics require an explicit grant** |
| `telemedicine_certified` | bool | ✓ | Gates remote prescribing per telemedicine guidelines |
| `specialisation` | str | ✗ | If PG-qualified but posted as MO |

---

#### `SPECIALIST`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `hpr_id` | str | ✓ | HPR-verified |
| `medical_council_registration_number` | str | ✓ | |
| `registration_expiry` | date | ✓ | > today |
| `specialty` | enum | ✓ | `OBG` `MEDICINE` `PAEDIATRICS` `PSYCHIATRY` `DERMATOLOGY` `OPHTHALMOLOGY` `ORTHOPAEDICS` `SURGERY` `ANAESTHESIA` |
| `pg_qualification` | enum | ✓ | `MD` `MS` `DNB` `DIPLOMA` |
| `tele_hub_org_unit_id` | UUID | ✓ | `unit_type` in (`TELE_HUB`,`DISTRICT_HOSPITAL`) |
| `telemedicine_certified` | bool | ✓ | **Must be `true` to receive teleconsult requests** |
| `languages_spoken` | list[str] | ✓ | ≥1. Used to match patients by preferred language |
| `roster_days` | list[enum] | ✓ | `MON`…`SUN` |
| `roster_start_time` / `roster_end_time` | time | ✓ | end > start |
| `max_queue_length` | int | ✓ | 1–50. Overflow routes to the state hub |
| `accepts_store_and_forward` | bool | ✓ | |
| `sla_response_hours_routine` | int | ✓ | default 24 |
| `sla_response_hours_urgent` | int | ✓ | default 2 |

---

#### `LAB_TECHNICIAN`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `qualification` | enum | ✓ | `DMLT` `BMLT` `MSC_MLT` |
| `council_registration_number` | str | ✗ | Where the state paramedical council requires it |
| `facility_org_unit_id` | UUID | ✓ | |
| `lab_code` | str | ✓ | Internal lab identifier |
| `authorised_test_categories` | list[str] | ✓ | `HAEMATOLOGY` `BIOCHEMISTRY` `MICROBIOLOGY` `SEROLOGY` `POC` |
| `can_release_results` | bool | ✓ | Separates entering a result from releasing it |
| `can_acknowledge_critical` | bool | ✓ | **Default `false`** — a critical value must reach a clinician |

---

#### `PHARMACIST`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `pharmacy_council_registration_number` | str | ✓ | Unique |
| `council_registration_expiry` | date | ✓ | > today |
| `qualification` | enum | ✓ | `D_PHARM` `B_PHARM` `M_PHARM` `PHARM_D` |
| `facility_org_unit_id` | UUID | ✓ | |
| `can_dispense_schedule_h` | bool | ✓ | |
| `can_manage_stock` | bool | ✓ | |
| `can_raise_indent` | bool | ✓ | |
| `cold_chain_trained` | bool | ✓ | Gates vaccine and oxytocin handling |

---

#### `BMO`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `hpr_id` | str | ✓ | |
| `medical_council_registration_number` | str | ✓ | |
| `registration_expiry` | date | ✓ | > today |
| `block_org_unit_id` | UUID | ✓ | `unit_type = BLOCK` |
| `facilities_supervised` | list[UUID] | ✓ | Must all be descendants of the block |
| `can_reassign_referral_owner` | bool | ✓ | default `true` |
| `escalation_contact_priority` | int | ✓ | 1–5. Position in the breach escalation chain |

---

#### `DHO_CMO`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `hpr_id` | str | ✓ | |
| `medical_council_registration_number` | str | ✓ | |
| `registration_expiry` | date | ✓ | > today |
| `qualification` | enum | ✓ | `MD_COMMUNITY_MEDICINE` `MBBS` `MPH` `OTHER_PG` |
| `district_org_unit_id` | UUID | ✓ | `unit_type = DISTRICT` |
| `appointment_order_ref` | str | ✓ | |
| `is_clinical_governance_chair` | bool | ✓ | Gates approval of triage protocol versions |
| `can_approve_l3_accounts` | bool | ✓ | Second-approver capability |

---

#### `DISTRICT_EPIDEMIOLOGIST`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `qualification` | enum | ✓ | `MPH` `MD_COMMUNITY_MEDICINE` `MSC_EPIDEMIOLOGY` `FETP` |
| `district_org_unit_id` | UUID | ✓ | |
| `analytics_scope` | list[str] | ✓ | `SURVEILLANCE` `MATERNAL` `CHILD` `NCD` `TB` `QUALITY` |
| `deidentified_access_only` | bool | ✓ | **Default `true`** |
| `line_list_access_approved_by` | UUID | ✗ | If identifiable line-lists are needed, a DHO must approve and it is time-boxed |
| `line_list_access_expires_at` | timestamptz | ✗ | **Required if the above is set. Max 90 days** |

---

#### `HEALTH_ADMIN_DPM`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `qualification` | enum | ✓ | `MBA` `MHA` `MPH` `PGDM` `OTHER` |
| `district_org_unit_id` | UUID | ✓ | |
| `functional_areas` | list[str] | ✓ | `HR` `FINANCE` `LOGISTICS` `PROCUREMENT` `INFRASTRUCTURE` |
| `budget_approval_limit_inr` | int | ✗ | 0 means no financial authority |
| `can_approve_indent` | bool | ✓ | |
| `phi_access` | bool | ✓ | **Hard-coded `false`. A manager needs counts, not names** |

---

#### `PROGRAMME_OFFICER`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `programme` | enum | ✓ | `RCH` `NCD` `TB` `IMMUNISATION` `NVBDCP` `BLINDNESS` `MENTAL_HEALTH` |
| `district_org_unit_id` | UUID | ✓ | |
| `national_portal_user_id` | str | ✗ | e.g. Ni-kshay ID for the TB officer |
| `can_approve_protocol_changes` | bool | ✓ | Within their programme only |
| `cohort_access_only` | bool | ✓ | **Hard-coded `true`.** An NCD officer sees NCD patients, not every patient |

---

#### `DISTRICT_IT_OFFICER`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `district_org_unit_id` | UUID | ✓ | |
| `technical_scope` | list[str] | ✓ | `DEVICES` `CONNECTIVITY` `INTEGRATIONS` `SUPPORT` |
| `can_manage_devices` | bool | ✓ | |
| `can_view_sync_health` | bool | ✓ | Device sync status only — no clinical payloads |
| `can_create_users` | bool | ✓ | **Hard-coded `false`. Not overridable via the API** |
| `phi_access` | bool | ✓ | **Hard-coded `false`. Break-glass only, DPO-notified** |

---

#### `DPO`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `scope_level` | enum | ✓ | `DISTRICT` `STATE` |
| `scope_org_unit_id` | UUID | ✓ | |
| `appointment_order_ref` | str | ✓ | |
| `published_contact_email` | str | ✓ | **Public** — the DPDP grievance contact |
| `published_contact_phone` | str | ✓ | Public |
| `can_read_audit_log` | bool | ✓ | Hard-coded `true` |
| `can_read_consent_records` | bool | ✓ | Hard-coded `true` |
| `can_read_clinical_data` | bool | ✓ | **Hard-coded `false`** |
| `second_approver_user_id` | UUID | ✓ | Must be `STATE_NHM`. Dual approval enforced |

---

#### `COLLECTOR`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `service_type` | enum | ✓ | `IAS` `STATE_CIVIL_SERVICE` |
| `district_org_unit_id` | UUID | ✓ | |
| `tenure_start` | date | ✓ | |
| `tenure_end` | date | ✗ | **Auto-deactivates on this date** — transfers are frequent |
| `dashboard_access_only` | bool | ✓ | **Hard-coded `true`** |
| `phi_access` | bool | ✓ | **Hard-coded `false`** |

---

#### `STATE_NHM`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `state_code` | str | ✓ | LGD state code |
| `directorate_designation` | str | ✓ | e.g. `Mission Director`, `GM (Digital Health)` |
| `districts_overseen` | list[UUID] | ✓ | Empty list means all districts in the state |
| `aggregate_access_only` | bool | ✓ | **Hard-coded `true`** |
| `can_approve_l2_l3_accounts` | bool | ✓ | Second-approver capability |

---

#### `VHSNC_MEMBER`

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `village_lgd_code` | str | ✓ | |
| `panchayat_name` | str | ✓ | |
| `position` | enum | ✓ | `CHAIRPERSON` `SECRETARY` `MEMBER` `ASHA_SECRETARY` |
| `term_start` | date | ✓ | |
| `term_end` | date | ✓ | **Auto-deactivates.** Panchayat terms are fixed |
| `aggregate_scorecard_only` | bool | ✓ | **Hard-coded `true`** |
| `phi_access` | bool | ✓ | **Hard-coded `false`** |

---

#### `SUPERUSER`

Not creatable through the normal `POST /users` path in a fresh system — see §9.

| Field | Type | Required | Validation |
|---|---|:--:|---|
| `full_name` | str | ✓ | |
| `email` | str | ✓ | Unique |
| `mobile` | str | ✓ | Unique |
| `hardware_mfa_required` | bool | ✓ | **Hard-coded `true`** — TOTP alone is insufficient |
| `justification` | str | ✓ | ≥50 chars. Recorded in the audit log |
| `second_approver_user_id` | UUID | ✓ | Must be another active `SUPERUSER` |
| `expires_at` | timestamptz | ✓ | **Max 365 days.** No permanent superuser accounts |

### 5.5 Field-count summary — proof the forms genuinely differ

| Role | Common | Posting | Role-specific | **Total** |
|---|:--:|:--:|:--:|:--:|
| `PATIENT` | — | — | 24 | **24** |
| `ASHA` | 14 | 6 | 11 | **31** |
| `ANM_MPW` | 14 | 6 | 8 | **28** |
| `CHO` | 14 | 6 | 8 | **28** |
| `MEDICAL_OFFICER` | 14 | 6 | 11 | **31** |
| `SPECIALIST` | 14 | 6 | 14 | **34** |
| `LAB_TECHNICIAN` | 14 | 6 | 7 | **27** |
| `PHARMACIST` | 14 | 6 | 8 | **28** |
| `BMO` | 14 | 6 | 7 | **27** |
| `DHO_CMO` | 14 | 6 | 8 | **28** |
| `DISTRICT_EPIDEMIOLOGIST` | 14 | 6 | 6 | **26** |
| `HEALTH_ADMIN_DPM` | 14 | 6 | 6 | **26** |
| `PROGRAMME_OFFICER` | 14 | 6 | 5 | **25** |
| `DISTRICT_IT_OFFICER` | 14 | 6 | 6 | **26** |
| `DPO` | 14 | 6 | 8 | **28** |
| `COLLECTOR` | 14 | 6 | 6 | **26** |
| `STATE_NHM` | 14 | 6 | 5 | **25** |
| `VHSNC_MEMBER` | 14 | 6 | 7 | **27** |
| `SUPERUSER` | — | — | 7 | **7** |

---

## 6. Account lifecycle

### 6.1 State machine

```
                    ┌──────────────────────────────────────────────────┐
                    │  Higher official calls POST /users               │
                    │  (all four authz gates pass)                     │
                    └────────────────────┬─────────────────────────────┘
                                         ▼
                              ┌─────────────────────┐
                              │  PENDING_APPROVAL   │  only when the grant
                              │  (dual-approval     │  has requires_second_
                              │   roles only)       │  approver = true
                              └──────────┬──────────┘
                                         │ POST /users/{id}/approve
                                         │ by a DIFFERENT eligible approver
                                         ▼
                              ┌─────────────────────┐
                              │      INVITED        │  invite token issued,
                              │  no credentials yet │  SMS + email sent,
                              │  cannot log in      │  TTL 72 hours
                              └──────────┬──────────┘
                                         │ POST /auth/invite/accept
                                         │ (sets password, enrols MFA)
                                         ▼
                              ┌─────────────────────┐
                              │       ACTIVE        │ ◄──────┐
                              └──┬───────┬───────┬──┘        │
                                 │       │       │           │ POST /users/{id}/reactivate
             registration expiry │       │       │ transfer  │
             or manual suspend   │       │       │           │
                                 ▼       │       ▼           │
                        ┌─────────────┐  │  ┌──────────────┐ │
                        │  SUSPENDED  │──┼─►│ TRANSFERRED  │─┘
                        │ login blocked│ │  │ old posting  │
                        │ data intact │  │  │ closed, new  │
                        └──────┬──────┘  │  │ one opened   │
                               │         │  └──────────────┘
                               │         │
                               │         │ tenure_end / term_end reached
                               │         │ or POST /users/{id}/deactivate
                               ▼         ▼
                        ┌──────────────────────────┐
                        │      DEACTIVATED         │  terminal.
                        │  credentials destroyed   │  Row is NEVER deleted —
                        │  sessions revoked        │  clinical records must
                        │  subordinates reassigned │  keep an attributable author
                        └──────────────────────────┘

  INVITED + 72h with no acceptance  ──►  EXPIRED  ──► resend or deactivate
```

### 6.2 Transition rules

| From | To | Trigger | Who | Side effects |
|---|---|---|---|---|
| — | `PENDING_APPROVAL` | `POST /users` on a `✓✓` grant | Creator | Approval request created; approver notified |
| — | `INVITED` | `POST /users` on a `✓` grant | Creator | Invite token issued and dispatched |
| `PENDING_APPROVAL` | `INVITED` | `POST /users/{id}/approve` | A **different** eligible approver | Invite issued |
| `PENDING_APPROVAL` | `DEACTIVATED` | `POST /users/{id}/reject` | Approver | Reason recorded |
| `INVITED` | `ACTIVE` | `POST /auth/invite/accept` | The invitee | Password set, MFA enrolled, token burned |
| `INVITED` | `EXPIRED` | 72 h elapsed | System job | Token invalidated |
| `ACTIVE` | `SUSPENDED` | Manual, or credential expiry, or 10 failed logins | Creator chain / system | **All refresh tokens revoked immediately** |
| `ACTIVE` | `TRANSFERRED` | `POST /users/{id}/transfer` | Creator chain | Old posting closed with an end date; subordinates reassigned |
| `SUSPENDED` | `ACTIVE` | `POST /users/{id}/reactivate` | Creator chain | Password reset forced |
| any | `DEACTIVATED` | `POST /users/{id}/deactivate`, or `tenure_end`, or `valid_until` | Creator chain / system | Credentials destroyed, sessions killed, subordinates reassigned |

### 6.3 Automatic suspension — the credential-expiry job

Runs nightly. This is the mechanism that stops an expired medical registration from continuing to prescribe.

```python
# app/jobs/credential_expiry.py
async def suspend_expired_credentials(session) -> int:
    """
    Nightly. Suspends any user whose professional registration has lapsed.
    Notifies the user 30, 14 and 7 days before, then on the day.
    """
    today = date.today()
    expiring = await session.exec(
        select(User).where(
            User.status == "ACTIVE",
            User.role.in_([
                "MEDICAL_OFFICER", "CHO", "ANM_MPW",
                "PHARMACIST", "SPECIALIST", "BMO", "DHO_CMO",
            ]),
        )
    )
    suspended = 0
    for user in expiring:
        expiry = user.profile.get("registration_expiry") or \
                 user.profile.get("council_registration_expiry")
        if expiry is None:
            continue
        expiry = date.fromisoformat(expiry)
        days_left = (expiry - today).days

        if days_left <= 0:
            await set_status(session, user, "SUSPENDED",
                             reason="PROFESSIONAL_REGISTRATION_EXPIRED",
                             actor="SYSTEM")
            await revoke_all_sessions(session, user.id)
            await notify_supervisor(user, "SUBORDINATE_SUSPENDED_REGISTRATION_EXPIRED")
            suspended += 1
        elif days_left in (30, 14, 7, 1):
            await notify_user(user, "REGISTRATION_EXPIRING", days_left=days_left)
    return suspended
```

### 6.4 Orphan prevention — the rule most systems get wrong

When a user is deactivated, everyone reporting to them becomes unmanaged. Nobody can then reset their password, approve their leave, or reassign their referrals. In practice this is how field workers get quietly locked out three months after their MO transfers.

**The rule: deactivation is blocked unless the subordinates are dealt with in the same transaction.**

```python
async def deactivate_user(session, actor, target_id: UUID, reason: str,
                          reassign_to_user_id: UUID | None = None):
    target = await get_user_or_404(session, target_id)
    await assert_can_manage(session, actor, target)

    subordinates = await session.exec(
        select(User).where(User.reports_to_user_id == target_id,
                           User.status.in_(["ACTIVE", "INVITED", "SUSPENDED"]))
    )
    subordinates = list(subordinates)

    if subordinates:
        if reassign_to_user_id is None:
            raise HTTPException(409, {
                "code": "SUBORDINATES_EXIST",
                "detail": f"{len(subordinates)} users report to this account. "
                          f"Provide reassign_to_user_id.",
                "subordinate_ids": [str(s.id) for s in subordinates],
                "suggested_reassign_to": str(target.reports_to_user_id)
                                          if target.reports_to_user_id else None,
            })
        new_manager = await get_user_or_404(session, reassign_to_user_id)
        if new_manager.status != "ACTIVE":
            raise HTTPException(422, {"code": "NEW_MANAGER_NOT_ACTIVE"})
        for s in subordinates:
            if not await can_create_role(session, new_manager.role, s.role):
                raise HTTPException(422, {
                    "code": "NEW_MANAGER_CANNOT_MANAGE_ROLE",
                    "detail": f"{new_manager.role} cannot manage {s.role}.",
                })
        for s in subordinates:
            s.reports_to_user_id = reassign_to_user_id
            session.add(s)
            await audit(session, actor, "USER_REASSIGNED", s.id,
                        {"from": str(target_id), "to": str(reassign_to_user_id)})

    target.status = "DEACTIVATED"
    target.deactivated_at = datetime.now(timezone.utc)
    target.deactivation_reason = reason
    target.password_hash = None            # destroy credentials
    target.mfa_secret_encrypted = None
    session.add(target)
    await revoke_all_sessions(session, target_id)
    await audit(session, actor, "USER_DEACTIVATED", target_id, {"reason": reason})
    await session.commit()
```

**The user row is never deleted.** Clinical records reference their author. A deleted author turns every record they wrote into an unattributable one, which fails both clinical governance and any audit.

---

## 7. The invitation flow

### 7.1 Why the creator never sets the password

If a BMO types a password for a new MO and sends it over WhatsApp, then: the BMO knows the MO's credentials, the password exists in a chat log, and every prescription that MO signs is repudiable. The invitation flow removes all three problems.

```
┌──────────────┐                                          ┌────────────────┐
│     BMO      │                                          │  New MO        │
│  (creator)   │                                          │  (invitee)     │
└──────┬───────┘                                          └────────┬───────┘
       │                                                           │
       │ 1. POST /users                                            │
       │    { role: MEDICAL_OFFICER, common, posting, profile }    │
       │    NO password field exists in this schema                │
       ├────────────────────────────────────────────────►          │
       │                                                           │
       │    Server: validates all 4 gates                          │
       │            creates user (status=INVITED)                  │
       │            token = secrets.token_urlsafe(32)              │
       │            stores sha256(token), TTL 72h, single use      │
       │                                                           │
       │ 2. 201 Created                                            │
       │    { id, status: "INVITED", invite_expires_at }           │
       │    ⚠ the token is NOT in this response                    │
       │◄────────────────────────────────────────────────          │
       │                                                           │
       │              3. SMS + email sent directly to the invitee  │
       │                 "Set up your SETU-Swasthya account:       │
       │                  https://…/invite/accept?token=…"         │
       │                 ─────────────────────────────────────────►│
       │                                                           │
       │              4. POST /auth/invite/accept                  │
       │                 { token, password, password_confirm,      │
       │                   mobile_otp }                            │
       │                 ◄─────────────────────────────────────────┤
       │                                                           │
       │                 Server: token valid & unused?             │
       │                         mobile OTP matches the mobile     │
       │                           recorded at creation?           │
       │                         password meets policy?            │
       │                         → argon2id hash, status=ACTIVE,   │
       │                           burn token, force MFA enrolment │
       │                                                           │
       │              5. 200 OK + MFA enrolment QR                 │
       │                 ─────────────────────────────────────────►│
       │                                                           │
       │ 6. Notification: "Dr Anil Verma has activated             │
       │    their account."                                        │
       │◄────────────────────────────────────────────────          │
```

### 7.2 Token security properties

| Property | Implementation | Why |
|---|---|---|
| Unguessable | `secrets.token_urlsafe(32)` → 256 bits | Brute force is infeasible |
| Not stored in plaintext | Only `sha256(token)` in the DB | A database dump does not yield working invites |
| Single use | `used_at` set inside the same transaction as activation | A forwarded or leaked link cannot be replayed |
| Short-lived | 72 h, configurable down to 24 h | Bounds the exposure window |
| Bound to the mobile | Acceptance also requires an OTP to the number recorded at creation | A stolen link alone is not enough — the attacker needs the phone too |
| Never echoed to the creator | Absent from the `201` response body and from all logs | The creator cannot impersonate the invitee |
| Rate limited | 5 acceptance attempts per token, 10 per IP per hour | Slows enumeration |
| Revocable | `POST /users/{id}/invite/revoke` | Wrong number, changed decision |

### 7.3 The one exception — ASHA passwordless onboarding

ASHAs mostly cannot use a password reliably; they share devices and have low literacy. `accept_mode` for `ASHA` is `OTP_ONLY`:

- No password is set. `password_hash` stays `NULL`.
- Login is mobile + OTP every time, with a device-bound 30-day refresh token so the OTP is not needed daily.
- A local 4-digit app PIN protects the device, stored and verified **on the device only** — it never reaches the server.
- Device binding is mandatory: a new device requires a fresh OTP plus a notification to the supervising ANM/CHO.

This is a deliberate, documented deviation. It trades password strength for a factor the user actually possesses, which is the right trade for this cadre.

---

## 8. Permission model

### 8.1 Structure

Permissions are `resource:action` strings. Roles map to permission sets. Scope narrows every permission to the org subtree. **Both must pass.**

```
Effective authority  =  (role grants the permission)
                        AND (target record is inside the user's scope)
                        AND (any role-specific hard flag permits it)
```

### 8.2 Permission catalogue

| Group | Permission | Meaning |
|---|---|---|
| **User management** | `user:create` | Create staff (further narrowed by the §3 matrix) |
| | `user:read` | View user records in scope |
| | `user:update` | Edit profile fields |
| | `user:suspend` | Suspend / reactivate |
| | `user:deactivate` | Terminal deactivation |
| | `user:approve` | Act as second approver |
| | `user:transfer` | Move a posting |
| **Patient** | `patient:create` | Register a patient |
| | `patient:read` | Read identifiable patient records in scope |
| | `patient:read_deidentified` | Read with identifiers stripped |
| | `patient:update` | Edit demographics |
| **Clinical** | `triage:create` · `triage:read` | |
| | `encounter:create` · `encounter:read` | |
| | `vitals:create` | |
| | `prescription:create` | Gated additionally by `prescribing_scope` |
| | `prescription:dispense` | |
| **Referral** | `referral:create` · `referral:read` · `referral:update_status` | |
| | `referral:reassign_owner` | |
| **Lab** | `lab:order` · `lab:collect` · `lab:enter_result` · `lab:release_result` | |
| | `lab:acknowledge_critical` | Clinicians only |
| **Teleconsult** | `teleconsult:request` · `teleconsult:accept` · `teleconsult:complete` | |
| **Stock** | `stock:read` · `stock:update` · `stock:indent` · `stock:approve_indent` | |
| **Registry** | `registry:read` · `registry:update` · `registry:record_outcome` | |
| **Dashboards** | `dashboard:facility` · `dashboard:block` · `dashboard:district` · `dashboard:state` | |
| | `analytics:deidentified` · `analytics:line_list` | |
| **Governance** | `audit:read` · `consent:read` · `consent:revoke` | |
| | `protocol:approve` | Sign off triage rule versions |
| **System** | `system:config` · `system:device_manage` · `system:integration_manage` | |
| | `system:break_glass` | Emergency PHI access with justification |

### 8.3 Role → permission map (abridged; full map lives in `seed_permissions.py`)

| Role | Permissions |
|---|---|
| `SUPERUSER` | **All**, plus `system:break_glass`. PHI reads are logged and notify the DPO |
| `STATE_NHM` | `user:*` (per matrix) · `dashboard:state` · `analytics:deidentified` · `audit:read` |
| `COLLECTOR` | `user:create/approve` (per matrix) · `dashboard:district` · `analytics:deidentified` |
| `DHO_CMO` | `user:*` · all clinical read · `dashboard:district` · `protocol:approve` · `analytics:line_list` · `referral:reassign_owner` |
| `DISTRICT_EPIDEMIOLOGIST` | `analytics:deidentified` · `dashboard:district` · `registry:read` · `patient:read_deidentified`. `analytics:line_list` only when time-boxed approval exists |
| `HEALTH_ADMIN_DPM` | `user:create` (LT, Pharmacist) · `stock:*` · `dashboard:district` · `analytics:deidentified` |
| `PROGRAMME_OFFICER` | `registry:read` · `dashboard:district` · `analytics:deidentified`, all filtered to `programme` |
| `DISTRICT_IT_OFFICER` | `system:device_manage` · `system:integration_manage` · sync health only. **No `patient:*`, no `user:create`** |
| `DPO` | `audit:read` · `consent:read` · `consent:revoke`. **Nothing clinical** |
| `SPECIALIST` | `teleconsult:accept/complete` · `patient:read` (queue + consented) · `prescription:create` · `referral:create` |
| `BMO` | `user:*` (per matrix) · all clinical in block · `dashboard:block` · `referral:reassign_owner` |
| `MEDICAL_OFFICER` | `user:create` (per matrix) · full clinical at facility · `prescription:create` · `lab:*` · `dashboard:facility` |
| `CHO` | `user:create` (ANM, ASHA) · `patient:*` · `triage:*` · `teleconsult:request` · limited `prescription:create` · `dashboard:facility` |
| `ANM_MPW` | `user:create` (ASHA) · `patient:create/read/update` · `triage:*` · `vitals:create` · `registry:*` |
| `LAB_TECHNICIAN` | `lab:collect/enter_result` · `patient:read` limited to ordered tests. `lab:release_result` and `lab:acknowledge_critical` only if flagged |
| `PHARMACIST` | `prescription:dispense` · `stock:*` · `patient:read` limited to the dispensing episode |
| `ASHA` | `patient:create/read/update` (own villages) · `triage:create` · `vitals:create` · `referral:create` · `registry:read/record_outcome` |
| `VHSNC_MEMBER` | `dashboard:facility` restricted to village aggregates. **No `patient:*`** |
| `PATIENT` | `patient:read` (self + linked) · `consent:read/revoke` · `teleconsult:request` · appointment booking |

### 8.4 Dependency-level enforcement

```python
# app/core/deps.py
def require(*permissions: str):
    """FastAPI dependency. Fails closed."""
    async def _check(current_user: User = Depends(get_current_active_user)) -> User:
        granted = await get_effective_permissions(current_user)
        missing = [p for p in permissions if p not in granted]
        if missing:
            await audit_denied(current_user, permissions, missing)
            raise HTTPException(403, {
                "code": "PERMISSION_DENIED",
                "detail": "You do not have permission to do this.",
                # Deliberately does NOT list which permission was missing —
                # that would map the permission model for an attacker.
            })
        return current_user
    return _check


def require_scope(get_org_unit_id):
    """Second gate. Permission alone is never sufficient."""
    async def _check(request: Request, current_user: User = Depends(get_current_active_user)):
        target_org = await get_org_unit_id(request)
        if not await org_unit_is_within_scope(request.state.session, target_org,
                                              current_user.scope_org_unit_id):
            await audit_denied(current_user, ["scope"], [str(target_org)])
            raise HTTPException(403, {"code": "OUT_OF_SCOPE",
                                      "detail": "That record is outside your area."})
        return current_user
    return _check


# Usage
@router.post("/users", status_code=201)
async def create_user(
    payload: CreateUserRequest,
    actor: User = Depends(require("user:create")),
    session: AsyncSession = Depends(get_session),
):
    ...
```

---

## 9. Superuser and bootstrap

### 9.1 The chicken-and-egg problem

Rule 2 says every staff account is created by a higher official. The first account has no higher official. This is resolved outside the API.

### 9.2 Bootstrap via CLI only

```bash
# Run ONCE, on the server, by a human with shell access. Never exposed over HTTP.
python -m app.cli bootstrap-superuser \
    --email "sysadmin@setu-swasthya.example" \
    --mobile "+919876500001" \
    --full-name "System Administrator" \
    --justification "Initial system bootstrap for Kanpur Nagar deployment, order DHS/2026/114" \
    --expires-days 90
```

```python
# app/cli.py
async def bootstrap_superuser(email, mobile, full_name, justification, expires_days):
    existing = await session.exec(
        select(func.count()).select_from(User).where(User.role == RoleCode.SUPERUSER)
    )
    if existing.one() > 0:
        raise SystemExit(
            "A SUPERUSER already exists. Bootstrap may only run on an empty system.\n"
            "To add another superuser, use POST /users with an existing superuser "
            "session and a second approver."
        )
    if len(justification) < 50:
        raise SystemExit("Justification must be at least 50 characters.")

    user = User(
        role=RoleCode.SUPERUSER, email=email, mobile_encrypted=encrypt(mobile),
        mobile_blind_index=blind_index(mobile), full_name=full_name,
        status="INVITED", created_by=None,
        mfa_required=True, hardware_mfa_required=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
    )
    session.add(user)
    token = secrets.token_urlsafe(32)
    session.add(UserInvitation(
        user_id=user.id, token_hash=sha256(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ))
    await audit(session, actor=None, action="SUPERUSER_BOOTSTRAP",
                target_user_id=user.id,
                metadata={"justification": justification, "via": "CLI"})
    await session.commit()

    # Printed ONCE to the operator's terminal. Never logged, never emailed.
    print("\n" + "=" * 72)
    print("BOOTSTRAP INVITE TOKEN (valid 24 hours, single use, shown once):")
    print(f"  {token}")
    print("Complete setup at POST /auth/invite/accept, then rotate immediately.")
    print("=" * 72 + "\n")
```

### 9.3 Superuser constraints

| Constraint | Rule |
|---|---|
| Creation | Only via CLI on an empty system, or by an existing superuser **with a second superuser approving** |
| MFA | Hardware key mandatory. TOTP alone is rejected at login |
| Expiry | Maximum 365 days. The account auto-deactivates. Renewal is a fresh dual-approved creation |
| Session TTL | Access token 5 minutes (not 15). Refresh token 1 hour (not 7 days) |
| IP allowlist | Optional but strongly recommended; configured in `SUPERUSER_IP_ALLOWLIST` |
| PHI access | Requires `POST /system/break-glass` with a ≥50-character justification. Grants 60 minutes. **Notifies the DPO immediately.** Every record touched is logged individually |
| Audit immunity | None. A superuser cannot edit or delete audit rows — the DB role has `INSERT` only on `audit_log` |
| Minimum count | At least 2 must exist in production, so dual approval is always possible. At most 4 |
| Deactivating the last one | Blocked with `409 LAST_SUPERUSER` |

### 9.4 The audit-log privilege split

```sql
-- The application connects as app_user. It cannot rewrite history.
CREATE ROLE app_user LOGIN PASSWORD :'app_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;

REVOKE UPDATE, DELETE ON audit_log FROM app_user;
GRANT  INSERT, SELECT ON audit_log TO app_user;

CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
```

Even a full application compromise cannot erase the evidence of itself. This is the single highest-value security control in this document and it costs four lines of SQL.

---

## 10. Authentication and session security

### 10.1 Login methods by role

| Role group | Primary | Second factor | Session TTL |
|---|---|---|---|
| `SUPERUSER` | Email + password | **Hardware key (WebAuthn), mandatory** | access 5 min · refresh 1 h |
| L1–L3 (`STATE_NHM`, `COLLECTOR`, `DHO_CMO`) | Mobile/email + password | TOTP, mandatory | access 15 min · refresh 8 h |
| L4–L6 (district officers, Specialist, BMO, MO) | Mobile + password | TOTP, mandatory | access 15 min · refresh 24 h |
| `CHO`, `ANM_MPW`, `LAB_TECHNICIAN`, `PHARMACIST` | Mobile + password | SMS OTP on a new device | access 30 min · refresh 7 d |
| `ASHA` | **Mobile + OTP only** | Device binding | access 60 min · refresh 30 d |
| `PATIENT` | **Mobile + OTP only** | — | access 30 min · refresh 30 d |
| `VHSNC_MEMBER` | Mobile + OTP | — | access 30 min · refresh 7 d |

The long field-worker refresh windows are deliberate: an ASHA in a village with no signal for five days must not be logged out. The compensating controls are device binding, a short access-token life, and instant server-side revocation.

### 10.2 Password policy

```python
# app/core/password.py
from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2"],
    argon2__time_cost=3,
    argon2__memory_cost=65536,   # 64 MiB
    argon2__parallelism=4,
    deprecated="auto",
)

PASSWORD_RULES = {
    "min_length": 12,
    "min_length_privileged": 16,        # L ≤ 3
    "require_categories": 3,            # of lower, upper, digit, symbol
    "max_length": 128,                  # DoS guard on the KDF
    "forbid_user_attributes": True,     # name, mobile, email, employee_code
    "forbid_common_passwords": True,    # top-10k list bundled offline
    "forbid_sequential": True,          # 1234, qwerty, abcd
    "history_count": 5,
    "max_age_days": 180,                # privileged roles: 90
    "min_age_hours": 24,                # blocks instant cycling through history
}
```

**Argon2id, not bcrypt.** `python-jose` handles JWTs only; it does not hash passwords. Argon2id is memory-hard and resists GPU cracking in a way bcrypt no longer does at commodity prices. Add `passlib[argon2]` to the dependency file.

### 10.3 JWT claims

```json
{
  "sub": "9c1f7c62-3b0a-4e5b-9c33-1a2b3c4d5e6f",
  "role": "MEDICAL_OFFICER",
  "lvl": 6,
  "scope_org": "3f2a1b4c-...",
  "scope_path": "/UP/KANPUR/RAMPUR/PHC001",
  "perms_hash": "sha256:8e4b...",
  "jti": "7d3e9a11-...",
  "sid": "c4f2b8e0-...",
  "ver": 3,
  "amr": ["pwd", "totp"],
  "iat": 1756483200,
  "exp": 1756484100,
  "iss": "setu-swasthya",
  "aud": "setu-api"
}
```

| Claim | Purpose |
|---|---|
| `perms_hash` | Hash of the effective permission set, **not the set itself**. Keeps the token small and prevents an attacker reading the permission model out of a captured token. The server resolves permissions from cache keyed by this hash |
| `ver` | Incremented on any role, scope or status change. **A token with a stale `ver` is rejected**, so a demotion takes effect within milliseconds rather than after the token expires |
| `sid` | Session id, so one device can be revoked without killing the others |
| `amr` | Which factors were actually used. Endpoints can require `"totp" in amr` |
| `jti` | Replay detection and targeted revocation |

**Algorithm:** RS256 with a rotating key pair, not HS256. A shared secret means every service that verifies a token can also mint one. Publish the public key at `/.well-known/jwks.json`.

### 10.4 Refresh-token rotation with reuse detection

```python
async def refresh_access_token(session, presented_token: str, device_fingerprint: str):
    row = await get_refresh_token_by_hash(session, sha256(presented_token))
    if row is None:
        raise HTTPException(401, {"code": "INVALID_REFRESH_TOKEN"})

    # Reuse detection: an already-rotated token has reappeared. Either it was
    # stolen and replayed, or the legitimate client raced. Both are handled the
    # same way — kill the whole family and force a fresh login.
    if row.rotated_at is not None:
        await revoke_token_family(session, row.family_id)
        await audit(session, None, "REFRESH_TOKEN_REUSE_DETECTED", row.user_id,
                    {"family_id": str(row.family_id), "device": device_fingerprint})
        await alert_security_team(row.user_id, "possible token theft")
        raise HTTPException(401, {
            "code": "TOKEN_REUSE_DETECTED",
            "detail": "For your security, please sign in again.",
        })

    if row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, {"code": "REFRESH_TOKEN_EXPIRED"})
    if row.device_fingerprint != device_fingerprint:
        await audit(session, None, "REFRESH_DEVICE_MISMATCH", row.user_id, {})
        raise HTTPException(401, {"code": "DEVICE_MISMATCH"})

    user = await get_user(session, row.user_id)
    if user.status != "ACTIVE":
        raise HTTPException(401, {"code": "ACCOUNT_NOT_ACTIVE"})

    row.rotated_at = datetime.now(timezone.utc)
    new_refresh = issue_refresh_token(session, user, family_id=row.family_id,
                                      device_fingerprint=device_fingerprint)
    new_access = issue_access_token(user)
    await session.commit()
    return new_access, new_refresh
```

### 10.5 Brute-force and enumeration defence

| Control | Setting |
|---|---|
| Failed-login lockout | 5 failures → 15-min lock · 10 → suspend + notify supervisor |
| Per-IP rate limit | 20 login attempts / 15 min |
| Per-mobile rate limit | 5 OTP requests / hour, 20 / day |
| OTP properties | 6 digits, 5-min TTL, 3 verify attempts, single use, hashed at rest |
| Constant-time comparison | `secrets.compare_digest` for every token and OTP check |
| **Uniform error text** | `POST /auth/login` returns the identical message for unknown user, wrong password and suspended account: *"Mobile number or password is not correct."* Only the audit log records which |
| Timing normalisation | On unknown-user, still run a dummy Argon2 verify so the response time does not reveal existence |
| CAPTCHA | After 3 failures from one IP |
| New-device alert | SMS to the user and to their supervisor on first login from an unseen device |

### 10.6 What the API must never return

- A password hash, in any response, ever
- An MFA secret after enrolment
- An invitation token, in any response body or any log line
- A refresh token in a response body when a cookie is usable (web clients use `HttpOnly; Secure; SameSite=Strict`)
- Whether a mobile number exists in the system
- Which specific permission was missing on a `403`
- A stack trace or SQL fragment on a `500`

---

## 11. Data protection and encryption

### 11.1 Classification

| Class | Examples | At rest | In transit | In logs |
|---|---|---|---|---|
| **Secret** | Passwords, MFA secrets, refresh tokens, invite tokens | Argon2id or SHA-256; never reversible | TLS 1.3 | **Never** |
| **Sensitive PII** | Mobile, email, ID-proof last 4, ABHA number, bank token | AES-256-GCM, app-level | TLS 1.3 | Masked: `+91XXXXX43210` |
| **PHI** | Diagnoses, vitals, results, prescriptions | AES-256-GCM (column) + full-disk | TLS 1.3 | **Never** |
| **Operational** | Org units, roles, stock counts | Full-disk only | TLS 1.3 | Permitted |
| **Public** | DPO published contact, facility names and hours | None | TLS 1.3 | Permitted |

### 11.2 Searchable encryption via a blind index

Mobile numbers must be encrypted, yet login requires looking a user up by mobile. Randomised encryption makes the ciphertext unsearchable. The standard resolution is a keyed hash alongside the ciphertext.

```python
# app/core/crypto.py
import hmac, hashlib, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DEK = bytes.fromhex(os.environ["FIELD_ENCRYPTION_KEY"])      # 32 bytes
_BLIND_INDEX_KEY = bytes.fromhex(os.environ["BLIND_INDEX_KEY"])  # 32 bytes


def encrypt_field(plaintext: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_DEK).encrypt(nonce, plaintext.encode(), None)


def decrypt_field(blob: bytes) -> str:
    return AESGCM(_DEK).decrypt(blob[:12], blob[12:], None).decode()


def blind_index(plaintext: str) -> str:
    """Deterministic keyed hash. Enables exact-match lookup on encrypted data."""
    normalised = plaintext.strip().lower()
    return hmac.new(_BLIND_INDEX_KEY, normalised.encode(), hashlib.sha256).hexdigest()


# Lookup by mobile without ever decrypting the whole table
user = await session.exec(
    select(User).where(User.mobile_blind_index == blind_index(mobile))
)
```

**Known limitation, stated honestly:** a blind index is deterministic, so an attacker with the database *and* the blind-index key can confirm whether a guessed number is present. Mitigations: keep `BLIND_INDEX_KEY` in a KMS separate from `FIELD_ENCRYPTION_KEY`, rotate it on a schedule, and accept that the alternative — plaintext mobiles — is strictly worse.

### 11.3 Key management

| Key | Storage | Rotation |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | KMS / Docker secret. **Never in `.env` committed to Git** | 12 months, with re-encryption migration |
| `BLIND_INDEX_KEY` | Separate KMS entry | 12 months, with index rebuild |
| JWT signing key (RS256) | KMS; private key never leaves the signer | 90 days, overlapping validity |
| DB password | Docker secret / KMS | 90 days |

Development uses locally generated keys in `backend/.env.local`, which is in `.gitignore`. **Per the Pre-Day 2 checklist: never commit secrets, and never paste them into team chat.**

### 11.4 Why Aadhaar is not an accepted ID type

`id_proof_type` deliberately excludes Aadhaar. Storing Aadhaar numbers pulls the project into a separate statutory regime with its own security, audit and purpose-limitation obligations, and creates a high-value breach target for no operational benefit — the system already has ABHA for patients and HPR for professionals. If a state mandates Aadhaar-based staff verification, do it via an authorised authentication API and store only the resulting yes/no token, never the number.

### 11.5 DPDP Act 2023 mapping

| Obligation | Implementation |
|---|---|
| Lawful basis and notice | Consent captured at registration; plain-language notice with audio |
| Purpose limitation | Purpose recorded per consent; enforced at query time by scope |
| Data minimisation | Role-specific schemas request only what the role needs; ID proof stores last 4 only |
| Accuracy | Correction endpoints; every edit audited |
| Storage limitation | Retention schedule per record class; automated purge job |
| Security safeguards | §10, §11 |
| Breach notification | Detection rules on the audit log; DPO alerted; notification runbook |
| Data-principal rights | Access, correction, erasure request and consent-withdrawal endpoints |
| Grievance officer | `DPO` role with a published contact, seeded at deployment |
| Children's data | Guardian consent mandatory below 18; no behavioural tracking or profiling of minors |

---

## 12. Audit logging

### 12.1 What is logged

Every one of these, without exception:

- Authentication: success, failure, logout, token refresh, reuse detection, lockout
- User management: create, approve, reject, invite issue/accept/revoke/expire, update, suspend, reactivate, transfer, deactivate, reassign
- Authorisation denials: permission denied, out of scope, level violation
- PHI access: every read of an identifiable patient record, with the reason
- Consent: grant, change, withdrawal
- Break-glass: activation, every record touched, expiry
- Configuration: role grant changes, permission changes, org-unit changes
- Data export: any bulk read

### 12.2 Schema

```sql
CREATE TABLE audit_log (
    id                BIGSERIAL PRIMARY KEY,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_user_id     UUID,                       -- NULL for system/anonymous
    actor_role        TEXT,
    actor_ip          INET,
    actor_user_agent  TEXT,
    session_id        UUID,
    action            TEXT NOT NULL,              -- 'USER_CREATED'
    outcome           TEXT NOT NULL,              -- 'SUCCESS' | 'DENIED' | 'ERROR'
    target_type       TEXT,                       -- 'USER' | 'PATIENT' | 'REFERRAL'
    target_id         UUID,
    target_org_unit   UUID,
    reason            TEXT,                       -- break-glass / override justification
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_id        UUID,
    prev_hash         TEXT,                       -- tamper-evident chain
    row_hash          TEXT NOT NULL
);

CREATE INDEX idx_audit_actor   ON audit_log (actor_user_id, occurred_at DESC);
CREATE INDEX idx_audit_target  ON audit_log (target_type, target_id, occurred_at DESC);
CREATE INDEX idx_audit_action  ON audit_log (action, occurred_at DESC);
CREATE INDEX idx_audit_time    ON audit_log (occurred_at DESC);
CREATE INDEX idx_audit_meta    ON audit_log USING GIN (metadata);
```

### 12.3 Tamper-evident hash chain

```python
def compute_row_hash(entry: dict, prev_hash: str | None) -> str:
    canonical = json.dumps({
        "occurred_at": entry["occurred_at"].isoformat(),
        "actor_user_id": str(entry.get("actor_user_id") or ""),
        "action": entry["action"],
        "outcome": entry["outcome"],
        "target_type": entry.get("target_type") or "",
        "target_id": str(entry.get("target_id") or ""),
        "metadata": entry.get("metadata", {}),
        "prev_hash": prev_hash or "",
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

A nightly verifier walks the chain and alerts the DPO on any break. Combined with the `INSERT`-only grant in §9.4, an attacker cannot quietly rewrite the record — they can only append, and a gap is detectable.

### 12.4 Never in the audit log

Passwords, hashes, MFA secrets, tokens, full mobile numbers (mask to `+91XXXXX43210`), clinical values, free-text clinical notes. The audit log records **that** a record was read, never **what** it said.

### 12.5 Retention

| Category | Retention | Rationale |
|---|---|---|
| Authentication | 1 year | Incident investigation |
| User management | 7 years | Employment and posting record |
| PHI access | 7 years | Clinical governance |
| Consent | Life of record + 7 years | DPDP evidence |
| Break-glass | 10 years | Highest-risk action |
| Denials | 2 years | Attack pattern analysis |

---

## 13. Database schema

### 13.1 Entity relationships

```
org_units ──┬──< users >──┬──< user_invitations
            │             ├──< refresh_tokens
            │             ├──< mfa_credentials
            │             ├──< login_attempts
            │             ├──< password_history
            │             ├──< approval_requests
            │             └──< consents          (PATIENT only)
            │
            └──< (Day 1 tables: patients, triage, referrals, sync)

roles ──< role_permissions >── permissions
roles ──< role_creation_grants >── roles          (creator_role → target_role)

audit_log        (append-only, references users by id, no FK to allow retention)
break_glass_sessions ──> users
```

### 13.2 `users` — the base table

```sql
CREATE TYPE user_status AS ENUM (
    'PENDING_APPROVAL','INVITED','ACTIVE','SUSPENDED',
    'TRANSFERRED','EXPIRED','DEACTIVATED'
);

CREATE TABLE users (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- identity
    role                    TEXT NOT NULL REFERENCES roles(code),
    role_level              SMALLINT NOT NULL,
    full_name               TEXT NOT NULL,
    full_name_local         TEXT,
    date_of_birth           DATE,
    sex                     TEXT,
    preferred_language      TEXT NOT NULL DEFAULT 'en',

    -- contact (encrypted + blind index)
    mobile_encrypted        BYTEA NOT NULL,
    mobile_blind_index      TEXT  NOT NULL,
    mobile_masked           TEXT  NOT NULL,          -- '+91XXXXX43210' for display
    email_encrypted         BYTEA,
    email_blind_index       TEXT,

    -- credentials
    password_hash           TEXT,                    -- NULL for OTP-only roles
    password_changed_at     TIMESTAMPTZ,
    must_change_password    BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_required            BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_enrolled            BOOLEAN NOT NULL DEFAULT FALSE,
    hardware_mfa_required   BOOLEAN NOT NULL DEFAULT FALSE,

    -- posting and hierarchy
    scope_org_unit_id       UUID REFERENCES org_units(id),
    scope_path              TEXT,                    -- denormalised for fast checks
    scope_extras            JSONB NOT NULL DEFAULT '{}'::jsonb,
    reports_to_user_id      UUID REFERENCES users(id),
    created_by_user_id      UUID REFERENCES users(id),
    approved_by_user_id     UUID REFERENCES users(id),

    -- role-specific profile, validated by a Pydantic discriminated union
    profile                 JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- verification
    hpr_id                  TEXT,
    hpr_verified_at         TIMESTAMPTZ,
    abha_number_encrypted   BYTEA,                   -- PATIENT only
    employee_code           TEXT,
    id_proof_type           TEXT,
    id_proof_last4          TEXT,

    -- lifecycle
    status                  user_status NOT NULL DEFAULT 'INVITED',
    token_version           INTEGER NOT NULL DEFAULT 1,
    joining_date            DATE,
    valid_until             DATE,
    expires_at              TIMESTAMPTZ,
    activated_at            TIMESTAMPTZ,
    suspended_at            TIMESTAMPTZ,
    suspension_reason       TEXT,
    deactivated_at          TIMESTAMPTZ,
    deactivation_reason     TEXT,
    last_login_at           TIMESTAMPTZ,
    failed_login_count      SMALLINT NOT NULL DEFAULT 0,
    locked_until            TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- ── integrity constraints: the rules, enforced by the database ──

    -- Rule 2: only PATIENT may exist without a creator
    CONSTRAINT chk_creator_required CHECK (
        role = 'PATIENT' OR role = 'SUPERUSER' OR created_by_user_id IS NOT NULL
    ),
    -- an active staff account must have a posting
    CONSTRAINT chk_scope_required CHECK (
        role IN ('PATIENT','SUPERUSER') OR scope_org_unit_id IS NOT NULL
    ),
    -- a suspended account must say why
    CONSTRAINT chk_suspension_reason CHECK (
        status <> 'SUSPENDED' OR suspension_reason IS NOT NULL
    ),
    -- deactivation destroys credentials
    CONSTRAINT chk_deactivated_no_creds CHECK (
        status <> 'DEACTIVATED' OR password_hash IS NULL
    ),
    -- privileged roles must carry the MFA requirement
    CONSTRAINT chk_privileged_mfa CHECK (
        role_level > 5 OR mfa_required = TRUE
    ),
    -- superusers expire
    CONSTRAINT chk_superuser_expires CHECK (
        role <> 'SUPERUSER' OR expires_at IS NOT NULL
    ),
    -- a user cannot report to themselves
    CONSTRAINT chk_no_self_report CHECK (reports_to_user_id <> id)
);

CREATE UNIQUE INDEX idx_users_mobile_bi  ON users (mobile_blind_index)
    WHERE status <> 'DEACTIVATED';
CREATE UNIQUE INDEX idx_users_email_bi   ON users (email_blind_index)
    WHERE email_blind_index IS NOT NULL AND status <> 'DEACTIVATED';
CREATE UNIQUE INDEX idx_users_hpr        ON users (hpr_id) WHERE hpr_id IS NOT NULL;
CREATE UNIQUE INDEX idx_users_emp_code   ON users (employee_code) WHERE employee_code IS NOT NULL;
CREATE INDEX idx_users_role_status       ON users (role, status);
CREATE INDEX idx_users_scope_path        ON users (scope_path text_pattern_ops);
CREATE INDEX idx_users_reports_to        ON users (reports_to_user_id);
CREATE INDEX idx_users_profile           ON users USING GIN (profile);
```

**`chk_creator_required` is the most important line in this file.** Even if every layer of application logic were bypassed, PostgreSQL itself refuses to store a staff account with no creator. Rule 2 is enforced in the database, not merely in Python.

### 13.3 `role_creation_grants` — §3 as data

```sql
CREATE TABLE role_creation_grants (
    creator_role             TEXT NOT NULL REFERENCES roles(code),
    target_role              TEXT NOT NULL REFERENCES roles(code),
    requires_second_approver BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_org_unit_types   TEXT[] NOT NULL,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (creator_role, target_role)
);
```

Changing who may create whom is a migration with a reviewable diff, not a code edit. That is the difference between a policy you can audit and one you have to read the source to discover.

### 13.4 Supporting tables

```sql
CREATE TABLE user_invitations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    accept_mode     TEXT NOT NULL DEFAULT 'PASSWORD',   -- 'PASSWORD' | 'OTP_ONLY'
    issued_by       UUID REFERENCES users(id),
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    attempt_count   SMALLINT NOT NULL DEFAULT 0,
    delivery_channel TEXT NOT NULL DEFAULT 'SMS_EMAIL',
    CONSTRAINT chk_invite_single_use CHECK (used_at IS NULL OR revoked_at IS NULL)
);
CREATE INDEX idx_invitations_user ON user_invitations (user_id);

CREATE TABLE refresh_tokens (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id           UUID NOT NULL,
    token_hash          TEXT NOT NULL UNIQUE,
    session_id          UUID NOT NULL,
    device_fingerprint  TEXT,
    device_label        TEXT,
    ip                  INET,
    issued_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    rotated_at          TIMESTAMPTZ,
    revoked_at          TIMESTAMPTZ,
    revoke_reason       TEXT
);
CREATE INDEX idx_refresh_user   ON refresh_tokens (user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_refresh_family ON refresh_tokens (family_id);

CREATE TABLE approval_requests (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_by       UUID NOT NULL REFERENCES users(id),
    required_approver_role TEXT NOT NULL,
    approved_by        UUID REFERENCES users(id),
    status             TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING|APPROVED|REJECTED|EXPIRED
    justification      TEXT NOT NULL,
    decision_note      TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at         TIMESTAMPTZ,
    expires_at         TIMESTAMPTZ NOT NULL,
    -- the two-person rule, enforced by the database
    CONSTRAINT chk_different_approver CHECK (approved_by IS NULL OR approved_by <> requested_by)
);

CREATE TABLE break_glass_sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id),
    justification  TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ,
    dpo_notified_at TIMESTAMPTZ,
    records_accessed JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT chk_justification_length CHECK (char_length(justification) >= 50)
);

CREATE TABLE password_history (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE login_attempts (
    id           BIGSERIAL PRIMARY KEY,
    identifier_bi TEXT,                    -- blind index; never the raw mobile
    user_id      UUID,
    ip           INET,
    user_agent   TEXT,
    outcome      TEXT NOT NULL,            -- SUCCESS|BAD_PASSWORD|UNKNOWN_USER|LOCKED|MFA_FAIL
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_login_attempts_ip ON login_attempts (ip, occurred_at DESC);
CREATE INDEX idx_login_attempts_id ON login_attempts (identifier_bi, occurred_at DESC);

CREATE TABLE consents (                    -- PATIENT only
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    keep_record       BOOLEAN NOT NULL,
    share_specialist  BOOLEAN NOT NULL,
    share_facility    BOOLEAN NOT NULL,
    anonymised_planning BOOLEAN NOT NULL,
    mode              TEXT NOT NULL,       -- DIGITAL_SELF|SPOKEN_WITNESSED|THUMB_IMPRESSION
    recorded_by       UUID REFERENCES users(id),
    witness_name      TEXT,
    language          TEXT NOT NULL,
    audio_version     TEXT,                -- version of the audio actually played
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at     TIMESTAMPTZ,
    CONSTRAINT chk_witness_for_spoken CHECK (
        mode <> 'SPOKEN_WITNESSED' OR witness_name IS NOT NULL
    )
);
CREATE INDEX idx_consents_patient ON consents (patient_user_id, recorded_at DESC);
```

**Consent is append-only.** A change writes a new row and stamps `superseded_at` on the old one. The full history of what a patient agreed to, and when, is reconstructable — which is precisely what a DPDP audit asks for.

---

## 14. API surface

### 14.1 Existing Day 1 endpoints — unchanged

Per the Pre-Day 2 checklist, these keep their exact names and payload fields. Behaviour is extended only by adding authorisation.

| Method | Path | Change |
|---|---|---|
| GET | `/health` | none — stays public |
| POST | `/patients/` | now requires `patient:create` + scope; also creates a `PATIENT` user row |
| GET | `/patients/{patient_id}` | now requires `patient:read` + scope; PHI read audited |
| POST | `/triage/` | now requires `triage:create` + scope |
| POST | `/referrals/` | now requires `referral:create` + scope |
| PATCH | `/referrals/{referral_id}/status` | now requires `referral:update_status` + scope |
| POST | `/sync/` | now requires an authenticated session; payload validated against the actor's scope |
| POST | `/login` | **permanent alias of `/auth/login`** |
| GET | `/me` | **permanent alias of `/auth/me`**; response gains `role`, `permissions`, `scope` |

### 14.2 New — public

| Method | Path | Purpose | Rate limit |
|---|---|---|---|
| POST | `/auth/otp/request` | Send an OTP to a mobile | 5/h per mobile, 20/h per IP |
| POST | `/auth/otp/verify` | Verify, return a short-lived `otp_token` | 10/h per mobile |
| POST | `/auth/patient/register` | **The only public registration** | 3/h per mobile, 10/h per IP |
| POST | `/auth/login` | Password or OTP login | 20/15 min per IP |
| POST | `/auth/mfa/verify` | Second factor | 5 per login attempt |
| POST | `/auth/token/refresh` | Rotate tokens | 60/h per session |
| POST | `/auth/invite/accept` | Activate an invited account | 5 per token |
| POST | `/auth/password/reset-request` | Begin reset | 3/h per mobile |
| POST | `/auth/password/reset` | Complete reset | 5 per token |
| GET | `/.well-known/jwks.json` | JWT public keys | none |

### 14.3 New — authenticated

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/auth/me` | — | Self, permissions, scope |
| POST | `/auth/logout` | — | Revokes the current session |
| POST | `/auth/logout-all` | — | Revokes every session |
| POST | `/auth/password/change` | — | Requires the current password |
| POST | `/auth/mfa/enrol` | — | Returns a TOTP secret + QR, once |
| GET | `/auth/sessions` | — | Active devices |
| DELETE | `/auth/sessions/{id}` | — | Revoke one device |
| **GET** | **`/users/creatable-roles`** | `user:create` | **Drives the frontend role picker** |
| **GET** | **`/users/registration-schema/{role}`** | `user:create` | **Drives the dynamic form** |
| **POST** | **`/users`** | `user:create` | **Staff creation. No password field exists** |
| GET | `/users` | `user:read` | Scoped list, filter + paginate |
| GET | `/users/{id}` | `user:read` | Scoped |
| PATCH | `/users/{id}` | `user:update` | Role and scope changes bump `token_version` |
| POST | `/users/{id}/approve` | `user:approve` | Second approver; must differ from the requester |
| POST | `/users/{id}/reject` | `user:approve` | Reason required |
| POST | `/users/{id}/invite/resend` | `user:create` | New token, old one burned |
| POST | `/users/{id}/invite/revoke` | `user:create` | |
| POST | `/users/{id}/suspend` | `user:suspend` | Reason required; sessions revoked |
| POST | `/users/{id}/reactivate` | `user:suspend` | Forces a password reset |
| POST | `/users/{id}/transfer` | `user:transfer` | New org unit; subordinates handled |
| POST | `/users/{id}/deactivate` | `user:deactivate` | `reassign_to_user_id` required if subordinates exist |
| GET | `/users/{id}/subordinates` | `user:read` | Direct reports |
| GET | `/users/hierarchy` | `user:read` | Subtree, for the org chart |
| GET | `/audit` | `audit:read` | DPO and above |
| GET | `/consents/{patient_id}` | `consent:read` | |
| POST | `/consents/{patient_id}/revoke` | `consent:revoke` | Patient or DPO |
| POST | `/system/break-glass` | `system:break_glass` | Justification ≥50 chars; DPO notified |

### 14.4 `POST /users` — full example

**Request**

```http
POST /users HTTP/1.1
Authorization: Bearer <BMO access token>
Content-Type: application/json
Idempotency-Key: 7f3c1e2a-9b44-4d81-a0c5-2e6f8b1d4a37

{
  "role": "MEDICAL_OFFICER",
  "common": {
    "full_name": "Anil Verma",
    "full_name_local": "अनिल वर्मा",
    "mobile": "+919876543210",
    "email": "anil.verma@up.gov.in",
    "date_of_birth": "1989-04-12",
    "sex": "MALE",
    "preferred_language": "hi",
    "employee_code": "UP-KNP-MO-2291",
    "designation": "Medical Officer",
    "joining_date": "2026-09-01",
    "id_proof_type": "SERVICE_ID",
    "id_proof_last4": "2291"
  },
  "posting": {
    "org_unit_id": "3f2a1b4c-77de-4a19-9b02-5c8e1d6f2a90",
    "reports_to_user_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
    "posting_order_ref": "CMO/KNP/2026/1142",
    "posting_order_date": "2026-08-20",
    "is_officer_in_charge": true
  },
  "profile": {
    "hpr_id": "12-3456-7890-1234",
    "medical_council_registration_number": "UPMC-2014-55231",
    "medical_council_name": "Uttar Pradesh Medical Council",
    "registration_expiry": "2029-03-31",
    "qualification": "MBBS",
    "qualification_year": 2014,
    "facility_org_unit_id": "3f2a1b4c-77de-4a19-9b02-5c8e1d6f2a90",
    "is_moic": true,
    "prescribing_scope": ["SCHEDULE_H", "SCHEDULE_H1", "OTC"],
    "telemedicine_certified": true
  }
}
```

**Response — 201**

```json
{
  "id": "9c1f7c62-3b0a-4e5b-9c33-1a2b3c4d5e6f",
  "role": "MEDICAL_OFFICER",
  "full_name": "Anil Verma",
  "mobile_masked": "+91XXXXX43210",
  "status": "INVITED",
  "scope_org_unit_id": "3f2a1b4c-77de-4a19-9b02-5c8e1d6f2a90",
  "scope_path": "/UP/KANPUR/RAMPUR/PHC001",
  "reports_to_user_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
  "created_by_user_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
  "invite": {
    "sent_to_masked": "+91XXXXX43210",
    "channels": ["SMS", "EMAIL"],
    "expires_at": "2026-09-01T10:32:00Z"
  },
  "hpr_verification": {
    "status": "PENDING",
    "note": "Account activates only after HPR verification succeeds."
  },
  "created_at": "2026-08-29T10:32:00Z"
}
```

Note what is absent: no password, no invite token, no unmasked mobile. **If the token appears in this response, the whole invitation design is defeated** — write a test that asserts the response body contains no 43-character URL-safe string.

### 14.5 `GET /users/registration-schema/{role}` — the dynamic form driver

```json
{
  "role": "ASHA",
  "display_name": "ASHA",
  "requires_second_approver": false,
  "allowed_org_unit_types": ["VILLAGE"],
  "accept_mode": "OTP_ONLY",
  "sections": [
    {
      "key": "common",
      "title": "Personal details",
      "fields": [
        { "name": "full_name", "label": "Full name", "type": "string",
          "required": true, "min_length": 2, "max_length": 120,
          "voice_input": true },
        { "name": "mobile", "label": "Mobile number", "type": "phone",
          "required": true, "pattern": "^\\+91[6-9]\\d{9}$",
          "help": "This will be her login. Must be her own number." },
        { "name": "preferred_language", "label": "Language", "type": "enum",
          "required": true,
          "options": [
            { "value": "hi", "label": "हिंदी" },
            { "value": "en", "label": "English" }
          ]}
      ]
    },
    {
      "key": "profile",
      "title": "ASHA details",
      "fields": [
        { "name": "asha_state_code", "label": "ASHA code", "type": "string",
          "required": true, "unique_scope": "STATE" },
        { "name": "village_lgd_codes", "label": "Villages covered",
          "type": "multi_select_org_unit", "required": true,
          "min_items": 1, "max_items": 3, "org_unit_type": "VILLAGE" },
        { "name": "population_covered", "label": "Population covered",
          "type": "integer", "required": true, "min": 100, "max": 3000 },
        { "name": "education_level", "label": "Education", "type": "enum",
          "required": true,
          "options": ["CLASS_8","CLASS_10","CLASS_12","GRADUATE","OTHER"] },
        { "name": "works_offline_primarily", "label": "Works mostly without internet",
          "type": "boolean", "required": true, "default": true }
      ]
    }
  ]
}
```

The frontend renders the form from this response. Adding a field to a role is a backend change plus a migration, and the form updates itself. **Nothing about the role's fields is hard-coded in the client.**

---

## 15. Validation rules

### 15.1 Discriminated union — wrong fields for a role are a 422

```python
# app/schemas/profiles.py
from typing import Literal, Annotated, Union
from pydantic import BaseModel, Field, field_validator

class AshaProfile(BaseModel):
    role: Literal["ASHA"]
    asha_state_code: str = Field(min_length=3, max_length=32)
    village_lgd_codes: list[str] = Field(min_length=1, max_length=3)
    sub_centre_org_unit_id: UUID
    population_covered: int = Field(ge=100, le=3000)
    education_level: Literal["CLASS_8","CLASS_10","CLASS_12","GRADUATE","OTHER"]
    induction_training_completed: bool
    works_offline_primarily: bool = True
    model_config = {"extra": "forbid"}       # unknown field → 422, never silently kept


class MedicalOfficerProfile(BaseModel):
    role: Literal["MEDICAL_OFFICER"]
    hpr_id: str = Field(pattern=r"^\d{2}-\d{4}-\d{4}-\d{4}$")
    medical_council_registration_number: str
    medical_council_name: str
    registration_expiry: date
    qualification: Literal["MBBS","MD","MS","DNB","BAMS","BHMS"]
    qualification_year: int = Field(ge=1960, le=2100)
    facility_org_unit_id: UUID
    is_moic: bool = False
    prescribing_scope: list[str]
    telemedicine_certified: bool
    model_config = {"extra": "forbid"}

    @field_validator("registration_expiry")
    @classmethod
    def must_be_current(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError(
                "Medical council registration has expired. "
                "A doctor with a lapsed registration cannot be given a prescribing account."
            )
        return v


UserProfile = Annotated[
    Union[AshaProfile, AnmMpwProfile, ChoProfile, MedicalOfficerProfile,
          SpecialistProfile, LabTechnicianProfile, PharmacistProfile,
          BmoProfile, DhoCmoProfile, EpidemiologistProfile, HealthAdminProfile,
          ProgrammeOfficerProfile, ItOfficerProfile, DpoProfile,
          CollectorProfile, StateNhmProfile, VhsncProfile],
    Field(discriminator="role"),
]
```

### 15.2 Cross-field rules

| Rule | Error code | Message |
|---|---|---|
| `org_unit.unit_type` must be allowed for the role | `INVALID_ORG_UNIT_TYPE` | "An ASHA must be posted to a village, not a PHC." |
| `reports_to_user_id` must be able to manage this role | `INVALID_MANAGER` | "A Pharmacist cannot manage an ANM." |
| `reports_to` must be `ACTIVE` | `MANAGER_NOT_ACTIVE` | "That supervisor's account is not active." |
| `registration_expiry` > today | `CREDENTIAL_EXPIRED` | See above |
| `date_of_birth` implies age 18–70 | `INVALID_AGE` | "Staff must be between 18 and 70 years old." |
| `mobile` unique among non-deactivated users | `MOBILE_IN_USE` | "That mobile number is already registered." |
| `hpr_id` unique | `HPR_IN_USE` | "That HPR ID is already linked to another account." |
| `village_lgd_codes` all under the parent sub-centre | `VILLAGE_OUT_OF_CATCHMENT` | "Village Bhairampur is not in this sub-centre's area." |
| Patient under 18 → guardian fields required | `GUARDIAN_REQUIRED` | "A guardian's name and number are needed for a child." |
| `SPECIALIST` needs `telemedicine_certified = true` | `TELEMEDICINE_CERT_REQUIRED` | "A specialist must be telemedicine-certified to take teleconsultations." |
| `roster_end_time` > `roster_start_time` | `INVALID_ROSTER` | "The end time must be after the start time." |
| `tenure_end` / `term_end` > today | `INVALID_TENURE` | "The end date must be in the future." |
| Dual-approval role → `second_approver_user_id` present and eligible | `APPROVER_REQUIRED` | "This role needs a second approver." |
| Approver ≠ requester | `SELF_APPROVAL` | "You cannot approve an account you created." |

### 15.3 Idempotency

`POST /users`, `POST /auth/patient/register` and `POST /users/{id}/approve` accept an `Idempotency-Key` header. The key plus a hash of the request body is stored for 24 hours with the original response. A retry after a network timeout returns the original `201` rather than creating a duplicate account.

This matters enormously in the field, where a BMO on 2G will tap Submit twice.

---

## 16. Error contract

### 16.1 Shape

```json
{
  "error": {
    "code": "ROLE_NOT_CREATABLE",
    "message": "You cannot create this type of user.",
    "detail": "A CHO may create ANM/MPW and ASHA accounts only.",
    "field": null,
    "request_id": "5f8c2a91-4b6d-4e0a-9c17-3d2e1f0a8b7c"
  }
}
```

`message` is safe to show a user in any language. `detail` is for developers. `request_id` correlates with the audit log for support.

### 16.2 Status codes

| Code | When |
|---|---|
| `400` | Malformed body, bad JSON |
| `401` | Missing, expired, or stale-`ver` token |
| `403` | Authenticated but not permitted — permission, scope or level |
| `404` | Not found, **or found but outside your scope** (see below) |
| `409` | Conflict — duplicate mobile, subordinates exist, last superuser |
| `422` | Validation failure — wrong fields for role, bad format, cross-field rule |
| `423` | Account locked |
| `429` | Rate limited; includes `Retry-After` |
| `500` | Server error. Body carries only `request_id` |

**Deliberate choice: `404`, not `403`, for out-of-scope records.** Returning `403` for a record that exists elsewhere confirms its existence to an attacker probing IDs. `404` reveals nothing. The audit log records the true reason.

### 16.3 Codes reference

| Code | Status | Meaning |
|---|---|---|
| `ROLE_NOT_CREATABLE` | 403 | No grant row for this creator/target pair |
| `OUT_OF_SCOPE` | 403 | Target org unit is outside the actor's subtree |
| `LEVEL_VIOLATION` | 403 | Target role is at or above the actor's level |
| `SECOND_APPROVER_REQUIRED` | 422 | Dual-approval role created without an approver |
| `SELF_APPROVAL` | 403 | Approver equals requester |
| `ACTOR_NOT_ACTIVE` | 403 | Creator's own account is suspended |
| `MFA_REQUIRED` | 403 | Creator has not enrolled MFA |
| `MOBILE_IN_USE` | 409 | Duplicate mobile |
| `SUBORDINATES_EXIST` | 409 | Deactivation blocked; reassignment needed |
| `LAST_SUPERUSER` | 409 | Cannot remove the final superuser |
| `INVITE_EXPIRED` / `INVITE_ALREADY_USED` / `INVITE_REVOKED` | 410 | Invitation no longer valid |
| `CREDENTIAL_EXPIRED` | 422 | Professional registration has lapsed |
| `HPR_VERIFICATION_FAILED` | 422 | HPR lookup did not confirm the ID |
| `TOKEN_REUSE_DETECTED` | 401 | Refresh family revoked |
| `ACCOUNT_LOCKED` | 423 | Too many failed logins |
| `SELF_REGISTRATION_NOT_ALLOWED` | 403 | A non-PATIENT role attempted the public endpoint |

---

## 17. Alembic migration plan

Sequenced so that every migration is independently reversible and none leaves the schema in a state the running application cannot handle.

| # | Revision | Contents |
|---|---|---|
| 1 | `0002_org_units` | `org_unit_type` enum, `org_units`, path indexes, path-maintenance trigger |
| 2 | `0003_roles_permissions` | `roles`, `permissions`, `role_permissions`, `role_creation_grants` |
| 3 | `0004_users_core` | `user_status` enum, `users` with all CHECK constraints and indexes |
| 4 | `0005_auth_tables` | `user_invitations`, `refresh_tokens`, `mfa_credentials`, `password_history`, `login_attempts` |
| 5 | `0006_governance` | `approval_requests`, `break_glass_sessions`, `consents` |
| 6 | `0007_audit_log` | `audit_log`, indexes, `INSERT`-only rules, `app_user` grant changes |
| 7 | `0008_link_day1_tables` | Adds `created_by_user_id`, `org_unit_id` to `patients`, `triage`, `referrals`; backfills to a system user; then sets `NOT NULL` |
| 8 | `0009_seed_reference_data` | Roles, permissions, role_permissions, role_creation_grants (data migration) |

### 17.1 Migration 0008 — the backfill that needs care

Existing Day 1 rows have no author. Adding `NOT NULL` in one step fails on a non-empty table.

```python
def upgrade() -> None:
    # 1. add nullable
    op.add_column("patients", sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True))
    op.add_column("patients", sa.Column("org_unit_id", UUID(as_uuid=True), nullable=True))

    # 2. ensure a system attribution user exists
    op.execute("""
        INSERT INTO users (id, role, role_level, full_name, mobile_encrypted,
                           mobile_blind_index, mobile_masked, status, expires_at)
        VALUES ('00000000-0000-0000-0000-000000000001', 'SUPERUSER', 0,
                'System (pre-RBAC migration)', '\\x00', 'system-migration',
                '+91XXXXXXXXXX', 'DEACTIVATED', now())
        ON CONFLICT (id) DO NOTHING;
    """)

    # 3. backfill
    op.execute("""
        UPDATE patients
        SET created_by_user_id = '00000000-0000-0000-0000-000000000001',
            org_unit_id = (SELECT id FROM org_units WHERE path = '/UP/KANPUR' LIMIT 1)
        WHERE created_by_user_id IS NULL;
    """)

    # 4. now enforce
    op.alter_column("patients", "created_by_user_id", nullable=False)
    op.alter_column("patients", "org_unit_id", nullable=False)
    op.create_foreign_key("fk_patients_created_by", "patients", "users",
                          ["created_by_user_id"], ["id"])
```

The attribution user is created `DEACTIVATED` with no credentials, so it can never be logged into. Every pre-RBAC record remains attributable, and it is obvious from the name that the attribution is historical rather than real.

### 17.2 Rules

- Every revision has a working `downgrade()`.
- No `DROP COLUMN` on a table with production data without a two-release deprecation.
- Data migrations are separate revisions from schema migrations — a failed seed should not roll back a schema change.
- `alembic upgrade head` must succeed on an empty database **and** on a database with Day 1 data. Test both.
- Per the Pre-Day 2 checklist: if a migration fails, fix the database or environment problem. Do not edit application code to hide the error.

---

## 18. Seed data

### 18.1 Ordering

```
1. roles                    (19 rows)
2. permissions              (~60 rows)
3. role_permissions         (~450 rows)
4. role_creation_grants     (~55 rows, exactly the §3 matrix)
5. org_units                (dev tree: 1 state → 1 district → 2 blocks → 4 PHCs → 8 SCs → 24 villages)
6. SUPERUSER                (CLI only, never in the seed script)
7. Demo users               (dev/test only, guarded by ENVIRONMENT != 'production')
```

### 18.2 Grants seed — the matrix as code

```python
# app/db/seed_grants.py
GRANTS: list[tuple[str, str, bool, list[str]]] = [
    # (creator_role, target_role, requires_second_approver, allowed_org_unit_types)

    # SUPERUSER — may create everything
    ("SUPERUSER", "SUPERUSER",   True,  ["*"]),
    ("SUPERUSER", "STATE_NHM",   False, ["STATE"]),
    ("SUPERUSER", "COLLECTOR",   False, ["DISTRICT"]),
    ("SUPERUSER", "DHO_CMO",     False, ["DISTRICT_OFFICE"]),
    # … one row per remaining role, all allowed …

    # STATE_NHM
    ("STATE_NHM", "STATE_NHM",              True,  ["STATE"]),
    ("STATE_NHM", "COLLECTOR",              True,  ["DISTRICT"]),
    ("STATE_NHM", "DHO_CMO",                True,  ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "DPO",                    True,  ["DISTRICT_OFFICE", "STATE"]),
    ("STATE_NHM", "DISTRICT_EPIDEMIOLOGIST",False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "HEALTH_ADMIN_DPM",       False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "PROGRAMME_OFFICER",      False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "DISTRICT_IT_OFFICER",    False, ["DISTRICT_OFFICE"]),
    ("STATE_NHM", "SPECIALIST",             False, ["TELE_HUB","DISTRICT_HOSPITAL"]),
    ("STATE_NHM", "BMO",                    False, ["BLOCK"]),
    ("STATE_NHM", "MEDICAL_OFFICER",        False, ["PHC","CHC","SDH"]),

    # COLLECTOR
    ("COLLECTOR", "DHO_CMO",          True,  ["DISTRICT_OFFICE"]),
    ("COLLECTOR", "HEALTH_ADMIN_DPM", False, ["DISTRICT_OFFICE"]),
    ("COLLECTOR", "DISTRICT_IT_OFFICER", False, ["DISTRICT_OFFICE"]),
    ("COLLECTOR", "BMO",              False, ["BLOCK"]),
    ("COLLECTOR", "VHSNC_MEMBER",     False, ["VILLAGE"]),

    # DHO_CMO
    ("DHO_CMO", "DISTRICT_EPIDEMIOLOGIST", False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "HEALTH_ADMIN_DPM",        False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "PROGRAMME_OFFICER",       False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "DISTRICT_IT_OFFICER",     False, ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "DPO",                     True,  ["DISTRICT_OFFICE"]),
    ("DHO_CMO", "SPECIALIST",              False, ["TELE_HUB","DISTRICT_HOSPITAL"]),
    ("DHO_CMO", "BMO",                     False, ["BLOCK"]),
    ("DHO_CMO", "MEDICAL_OFFICER",         False, ["PHC","CHC","SDH"]),
    ("DHO_CMO", "CHO",                     False, ["HWC","SUB_CENTRE"]),
    ("DHO_CMO", "ANM_MPW",                 False, ["SUB_CENTRE","HWC"]),
    ("DHO_CMO", "LAB_TECHNICIAN",          False, ["PHC","CHC","SDH","DISTRICT_HOSPITAL"]),
    ("DHO_CMO", "PHARMACIST",              False, ["PHC","CHC","SDH","DISTRICT_HOSPITAL"]),
    ("DHO_CMO", "ASHA",                    False, ["VILLAGE"]),
    ("DHO_CMO", "VHSNC_MEMBER",            False, ["VILLAGE"]),

    # HEALTH_ADMIN_DPM — narrow by design
    ("HEALTH_ADMIN_DPM", "LAB_TECHNICIAN", False, ["PHC","CHC","SDH","DISTRICT_HOSPITAL"]),
    ("HEALTH_ADMIN_DPM", "PHARMACIST",     False, ["PHC","CHC","SDH","DISTRICT_HOSPITAL"]),

    # BMO
    ("BMO", "MEDICAL_OFFICER", False, ["PHC","CHC"]),
    ("BMO", "CHO",             False, ["HWC","SUB_CENTRE"]),
    ("BMO", "ANM_MPW",         False, ["SUB_CENTRE","HWC"]),
    ("BMO", "LAB_TECHNICIAN",  False, ["PHC","CHC"]),
    ("BMO", "PHARMACIST",      False, ["PHC","CHC"]),
    ("BMO", "ASHA",            False, ["VILLAGE"]),
    ("BMO", "VHSNC_MEMBER",    False, ["VILLAGE"]),

    # MEDICAL_OFFICER
    ("MEDICAL_OFFICER", "CHO",            False, ["HWC","SUB_CENTRE"]),
    ("MEDICAL_OFFICER", "ANM_MPW",        False, ["SUB_CENTRE","HWC"]),
    ("MEDICAL_OFFICER", "LAB_TECHNICIAN", False, ["PHC","CHC"]),
    ("MEDICAL_OFFICER", "PHARMACIST",     False, ["PHC","CHC"]),
    ("MEDICAL_OFFICER", "ASHA",           False, ["VILLAGE"]),

    # CHO
    ("CHO", "ANM_MPW", False, ["SUB_CENTRE","HWC"]),
    ("CHO", "ASHA",    False, ["VILLAGE"]),

    # ANM_MPW
    ("ANM_MPW", "ASHA", False, ["VILLAGE"]),

    # Deliberately absent: DISTRICT_EPIDEMIOLOGIST, PROGRAMME_OFFICER,
    # DISTRICT_IT_OFFICER, DPO, SPECIALIST, LAB_TECHNICIAN, PHARMACIST,
    # ASHA, VHSNC_MEMBER, PATIENT. These roles create nobody.
]
```

A test asserts that `len(GRANTS)` matches the number of `✓` and `✓✓` cells in §3, and that no grant exists for any role marked as creating nothing. **The document and the code are checked against each other by CI**, so the table above cannot silently drift from the running system.

---

## 19. Smoke tests

These extend Step 13 of the Pre-Day 2 checklist. Development and test data only.

### 19.1 The nine existing Day 1 tests — must still pass unchanged

```bash
BASE=http://localhost:8000

curl -s $BASE/health | jq                                   # 1
# 2–9: /patients/, /patients/{id}, /triage/, /referrals/,
#      /referrals/{id}/status, /sync/, /login, /me
# Run exactly as documented in backend/docs/API_CONTRACT.md.
# If any of these now fails, the RBAC layer has broken an existing contract. Fix that first.
```

### 19.2 New tests — registration and hierarchy

```bash
# ── T1. A patient can self-register ──────────────────────────────────────────
curl -s -X POST $BASE/auth/otp/request \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+919000000001","purpose":"PATIENT_REGISTRATION"}'
# → 200 {"otp_sent": true, "expires_in": 300}
# In dev, the OTP is printed to the server log. Never in production.

OTP_TOKEN=$(curl -s -X POST $BASE/auth/otp/verify \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+919000000001","otp":"123456"}' | jq -r .otp_token)

curl -s -X POST $BASE/auth/patient/register \
  -H 'Content-Type: application/json' \
  -d "{\"full_name\":\"Rekha Devi\",\"age_years\":28,\"sex\":\"FEMALE\",
       \"mobile\":\"+919000000001\",\"is_shared_phone\":false,
       \"village_lgd_code\":\"V0012\",\"preferred_language\":\"hi\",
       \"consent_keep_record\":true,\"consent_share_specialist\":true,
       \"consent_share_facility\":false,\"consent_anonymised_planning\":false,
       \"consent_mode\":\"DIGITAL_SELF\",\"otp_token\":\"$OTP_TOKEN\"}"
# EXPECT 201, status ACTIVE, created_by_user_id null


# ── T2. A patient refusing ALL consent still registers ───────────────────────
# same body with all four consents false
# EXPECT 201. If this returns 4xx, the consent design is wrong — fix it.


# ── T3. Staff self-registration is impossible ────────────────────────────────
curl -s -X POST $BASE/auth/patient/register \
  -H 'Content-Type: application/json' \
  -d '{"role":"MEDICAL_OFFICER","full_name":"Fake Doctor", ...}'
# EXPECT 403 SELF_REGISTRATION_NOT_ALLOWED, or 422 (role is not in the schema at all)

curl -s -X POST $BASE/users \
  -H 'Content-Type: application/json' \
  -d '{"role":"ASHA", ...}'          # no Authorization header
# EXPECT 401


# ── T4. A BMO can create an MO ───────────────────────────────────────────────
BMO_TOKEN=$(login_as bmo@test)
curl -s -X POST $BASE/users -H "Authorization: Bearer $BMO_TOKEN" \
  -H 'Content-Type: application/json' -d @fixtures/create_mo.json
# EXPECT 201, status INVITED, NO token in the response body


# ── T5. A CHO CANNOT create an MO ────────────────────────────────────────────
CHO_TOKEN=$(login_as cho@test)
curl -s -X POST $BASE/users -H "Authorization: Bearer $CHO_TOKEN" \
  -H 'Content-Type: application/json' -d @fixtures/create_mo.json
# EXPECT 403 ROLE_NOT_CREATABLE


# ── T6. An ASHA can create nobody ────────────────────────────────────────────
ASHA_TOKEN=$(login_as asha@test)
curl -s $BASE/users/creatable-roles -H "Authorization: Bearer $ASHA_TOKEN"
# EXPECT 200 {"creatable_roles": []}
curl -s -X POST $BASE/users -H "Authorization: Bearer $ASHA_TOKEN" \
  -d @fixtures/create_asha.json
# EXPECT 403


# ── T7. Cross-block creation is refused ──────────────────────────────────────
# Rampur BMO tries to create a CHO in Bilhaur block
# EXPECT 403 OUT_OF_SCOPE


# ── T8. Dual approval is enforced ────────────────────────────────────────────
DHO_TOKEN=$(login_as dho@test)
DPO_ID=$(create_dpo_with $DHO_TOKEN)          # EXPECT 201 status PENDING_APPROVAL
curl -s -X POST $BASE/users/$DPO_ID/approve -H "Authorization: Bearer $DHO_TOKEN"
# EXPECT 403 SELF_APPROVAL — the creator cannot approve their own request
STATE_TOKEN=$(login_as state@test)
curl -s -X POST $BASE/users/$DPO_ID/approve -H "Authorization: Bearer $STATE_TOKEN"
# EXPECT 200, status becomes INVITED


# ── T9. Invitation acceptance ────────────────────────────────────────────────
# Read the token from the dev mail/SMS sink, not from the API response.
curl -s -X POST $BASE/auth/invite/accept -H 'Content-Type: application/json' \
  -d '{"token":"<token>","password":"Correct-Horse-42!","password_confirm":"Correct-Horse-42!","mobile_otp":"123456"}'
# EXPECT 200, status ACTIVE, MFA enrolment payload returned
# Replay the SAME token → EXPECT 410 INVITE_ALREADY_USED


# ── T10. The superuser can create every role ─────────────────────────────────
SU_TOKEN=$(login_as superuser)
curl -s $BASE/users/creatable-roles -H "Authorization: Bearer $SU_TOKEN" | jq '.creatable_roles | length'
# EXPECT 19


# ── T11. The IT Officer cannot create users ──────────────────────────────────
ITO_TOKEN=$(login_as ito@test)
curl -s $BASE/users/creatable-roles -H "Authorization: Bearer $ITO_TOKEN"
# EXPECT {"creatable_roles": []}


# ── T12. Deactivation with subordinates is blocked ───────────────────────────
curl -s -X POST $BASE/users/$MO_ID/deactivate -H "Authorization: Bearer $BMO_TOKEN" \
  -d '{"reason":"TRANSFERRED_OUT"}'
# EXPECT 409 SUBORDINATES_EXIST with subordinate_ids listed
# Retry with reassign_to_user_id → EXPECT 200, subordinates now report to the new manager


# ── T13. A role change invalidates existing tokens ───────────────────────────
OLD=$(login_as cho@test)
curl -s -X PATCH $BASE/users/$CHO_ID -H "Authorization: Bearer $BMO_TOKEN" \
  -d '{"role":"ANM_MPW"}'
curl -s $BASE/auth/me -H "Authorization: Bearer $OLD"
# EXPECT 401 — token_version bumped, stale token rejected


# ── T14. Login errors do not leak account existence ──────────────────────────
# unknown mobile vs known mobile with wrong password
# EXPECT identical body AND response times within 50 ms of each other


# ── T15. The audit log is append-only ────────────────────────────────────────
docker compose exec -T db psql -U app_user -d setu -c \
  "UPDATE audit_log SET action='TAMPERED' WHERE id=1;"
# EXPECT 0 rows affected (the RULE swallows it) or a permission error


# ── T16. A response never contains an invite token ───────────────────────────
pytest tests/test_no_token_leakage.py
# Asserts no 43-char URL-safe string appears in any /users response body
```

### 19.3 Test matrix — every creator × every target

CI generates 19 × 19 = 361 cases from the §3 matrix. Each asserts `201`/`403` according to the table. **This is the single test that proves the whole authority model.** Run it on every commit; it takes about 40 seconds.

```python
@pytest.mark.parametrize("creator_role", ALL_ROLES)
@pytest.mark.parametrize("target_role", ALL_ROLES)
async def test_creation_authority_matrix(client, creator_role, target_role):
    expected_allowed = (creator_role, target_role) in EXPECTED_GRANTS
    token = await login_as_role(client, creator_role)
    resp = await client.post("/users", headers=auth(token),
                             json=valid_payload_for(target_role))
    if expected_allowed:
        assert resp.status_code == 201, f"{creator_role} should create {target_role}"
    else:
        assert resp.status_code == 403, f"{creator_role} must NOT create {target_role}"
        assert resp.json()["error"]["code"] in ("ROLE_NOT_CREATABLE", "LEVEL_VIOLATION")
```

---

## 20. Security threat model

| # | Threat | Vector | Control |
|---|---|---|---|
| T1 | Privilege escalation via self-registration | Attacker posts `role: DHO_CMO` to the public endpoint | Public endpoint accepts no `role` field at all; hard-coded to `PATIENT`; DB CHECK requires a creator for staff |
| T2 | Privilege escalation via a crafted `PATCH` | Attacker updates their own `role` | Role changes require `user:update` **plus** a valid creation grant for the new role; self-role-change blocked outright |
| T3 | Horizontal movement across districts | Guessed org unit IDs | Scope containment on every write and read; `404` not `403` on out-of-scope |
| T4 | Stolen invitation link | Intercepted SMS | Token is single use, 72 h, hashed at rest, **and** requires an OTP to the recorded mobile |
| T5 | Credential stuffing | Reused passwords | Argon2id, breach list, lockout, per-IP limits, MFA for L≤6 |
| T6 | Session hijack | Stolen refresh token | Rotation with reuse detection, device fingerprint, family revocation, `token_version` |
| T7 | Insider mass data export | A legitimate DHO dumps the district | Bulk reads audited and rate-limited; anomaly alert on >500 PHI reads/hour; DPO dashboard |
| T8 | Audit tampering | DB access after app compromise | `INSERT`-only grant, `DO INSTEAD NOTHING` rules, hash chain, nightly verifier |
| T9 | Superuser abuse | Compromised bootstrap credential | Hardware MFA, 5-min tokens, expiry, dual approval for creating peers, break-glass with DPO notification, no audit immunity |
| T10 | Enumeration of staff | Probing `/auth/login` | Uniform errors, timing normalisation, rate limits, CAPTCHA |
| T11 | Expired clinician still prescribing | Registration lapses unnoticed | Nightly expiry job auto-suspends; warnings at 30/14/7/1 days |
| T12 | Orphaned accounts after transfer | Manager leaves | Deactivation blocked until subordinates are reassigned |
| T13 | Duplicate identities | Retry on a flaky network | Idempotency keys; unique blind indexes on mobile, HPR ID, employee code |
| T14 | Secrets in Git | `.env` committed | `.gitignore`, pre-commit secret scan, CI gitleaks, KMS in production. **Checklist Step 9 rule** |
| T15 | Wrong-role field injection | Sending ASHA fields as an MO | Pydantic discriminated union with `extra: "forbid"` → `422` |
| T16 | Consent bypass | Reading records without consent | Consent checked at query time; every PHI read audited with the consent id used |
| T17 | Token minted by a verifying service | HS256 shared secret | RS256; only the auth service holds the private key |
| T18 | Path-prefix scope bug | `/UP/KANPUR` matching `/UP/KANPUR2` | Trailing-separator comparison; explicit regression test |

---

## 21. Definition of Done

Day 1 is complete when **every** box is ticked. Partial completion is not a state this feature can safely ship in — a half-built authorisation layer is more dangerous than none, because it invites false confidence.

### Schema and migrations
- [ ] `alembic upgrade head` succeeds on an empty database
- [ ] `alembic upgrade head` succeeds on a database containing Day 1 data
- [ ] `alembic downgrade -1` works for every revision
- [ ] All CHECK constraints from §13.2 exist and are verified by a test that attempts to violate each
- [ ] `audit_log` rejects `UPDATE` and `DELETE` from `app_user`

### Identity and registration
- [ ] `POST /auth/patient/register` is the only public registration endpoint
- [ ] A patient with all four consents `false` registers successfully
- [ ] Every one of the 18 staff roles has a distinct, validated profile schema
- [ ] `GET /users/registration-schema/{role}` returns a complete, renderable schema for all 19 roles
- [ ] `POST /users` accepts no password field in any code path

### Authority
- [ ] `role_creation_grants` is seeded and exactly matches §3
- [ ] The 361-case creator × target matrix test passes
- [ ] `GET /users/creatable-roles` returns `[]` for all nine create-nothing roles
- [ ] `SUPERUSER` returns all 19 creatable roles
- [ ] Cross-scope creation returns `403 OUT_OF_SCOPE`
- [ ] Dual approval is enforced; self-approval returns `403`

### Lifecycle
- [ ] Invitation flow works end to end; token replay returns `410`
- [ ] The invite token appears in no response body and no log line (automated test)
- [ ] The credential-expiry job suspends a lapsed registration and warns beforehand
- [ ] Deactivation with subordinates returns `409` until reassignment is supplied
- [ ] No user row is ever hard-deleted

### Authentication
- [ ] Argon2id hashing; `passlib[argon2]` in the dependency file
- [ ] RS256 JWTs; JWKS endpoint live
- [ ] `token_version` bump invalidates existing tokens within one request
- [ ] Refresh rotation with reuse detection revokes the family
- [ ] MFA mandatory for L≤6; hardware MFA for `SUPERUSER`
- [ ] Login errors are uniform in body and in timing

### Data protection
- [ ] Mobile and email are encrypted at rest with a working blind index
- [ ] No secret is present in Git; gitleaks passes in CI
- [ ] Consent records are append-only with full history
- [ ] `id_proof_type` does not offer Aadhaar

### Audit
- [ ] All 8 event categories from §12.1 are logged
- [ ] The hash chain verifies; the nightly verifier alerts on a break
- [ ] No password, token or clinical value appears in any audit row
- [ ] `GET /audit` is restricted to `audit:read`

### Compatibility with existing work
- [ ] All nine Day 1 endpoints respond with unchanged names and payload fields
- [ ] `/login` and `/me` still work as before
- [ ] `backend/docs/API_CONTRACT.md` is updated additively; no existing entry is edited
- [ ] Swagger at `/docs` loads and lists both old and new routes
- [ ] `/openapi.json` is valid

### Process
- [ ] Both developers can run the full suite on their own laptops
- [ ] No force-push, no destructive reset of the shared `backend` branch
- [ ] Any deviation from the API contract was raised with Aditya before the change

---

## Appendix A — Quick reference: who creates whom

```
PATIENT ................... self-registers (OTP). Created by nobody.
ASHA ...................... ANM_MPW · CHO · MEDICAL_OFFICER · BMO · DHO_CMO · SUPERUSER
ANM_MPW ................... CHO · MEDICAL_OFFICER · BMO · DHO_CMO · SUPERUSER
CHO ....................... MEDICAL_OFFICER · BMO · DHO_CMO · SUPERUSER
LAB_TECHNICIAN ............ MEDICAL_OFFICER · BMO · HEALTH_ADMIN_DPM · DHO_CMO · SUPERUSER
PHARMACIST ................ MEDICAL_OFFICER · BMO · HEALTH_ADMIN_DPM · DHO_CMO · SUPERUSER
MEDICAL_OFFICER ........... BMO · DHO_CMO · STATE_NHM · SUPERUSER
SPECIALIST ................ DHO_CMO · STATE_NHM · SUPERUSER
BMO ....................... DHO_CMO · COLLECTOR · STATE_NHM · SUPERUSER
DISTRICT_EPIDEMIOLOGIST ... DHO_CMO · STATE_NHM · SUPERUSER
HEALTH_ADMIN_DPM .......... DHO_CMO · COLLECTOR · STATE_NHM · SUPERUSER
PROGRAMME_OFFICER ......... DHO_CMO · STATE_NHM · SUPERUSER
DISTRICT_IT_OFFICER ....... DHO_CMO · COLLECTOR · STATE_NHM · SUPERUSER
DPO ....................... DHO_CMO ✓✓ · STATE_NHM ✓✓ · SUPERUSER      (dual approval)
VHSNC_MEMBER .............. BMO · COLLECTOR · DHO_CMO · SUPERUSER
DHO_CMO ................... COLLECTOR ✓✓ · STATE_NHM ✓✓ · SUPERUSER    (dual approval)
COLLECTOR ................. STATE_NHM ✓✓ · SUPERUSER                    (dual approval)
STATE_NHM ................. STATE_NHM ✓✓ · SUPERUSER                    (dual approval)
SUPERUSER ................. CLI bootstrap, or SUPERUSER ✓✓              (dual approval)

Creates nobody: DISTRICT_EPIDEMIOLOGIST · PROGRAMME_OFFICER · DISTRICT_IT_OFFICER ·
                DPO · SPECIALIST · LAB_TECHNICIAN · PHARMACIST · ASHA ·
                VHSNC_MEMBER · PATIENT
```

## Appendix B — Environment variables

```bash
# backend/.env.example  — commit THIS file. Never commit .env itself.

ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://app_user:CHANGE_ME@localhost:5432/setu

# JWT (RS256) — generate with:
#   openssl genrsa -out jwt_private.pem 2048
#   openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
JWT_PRIVATE_KEY_PATH=./secrets/jwt_private.pem
JWT_PUBLIC_KEY_PATH=./secrets/jwt_public.pem
JWT_ALGORITHM=RS256
JWT_ISSUER=setu-swasthya
JWT_AUDIENCE=setu-api
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=7

# Field encryption — generate with: openssl rand -hex 32
FIELD_ENCRYPTION_KEY=CHANGE_ME_64_HEX_CHARS
BLIND_INDEX_KEY=CHANGE_ME_DIFFERENT_64_HEX_CHARS

# Invitations
INVITE_TOKEN_TTL_HOURS=72
INVITE_MAX_ATTEMPTS=5

# OTP
OTP_TTL_SECONDS=300
OTP_MAX_ATTEMPTS=3
OTP_RATE_LIMIT_PER_HOUR=5

# Lockout
MAX_FAILED_LOGINS=5
LOCKOUT_MINUTES=15
SUSPEND_AFTER_FAILURES=10

# Superuser
SUPERUSER_ACCESS_TOKEN_MINUTES=5
SUPERUSER_MAX_ACCOUNTS=4
SUPERUSER_IP_ALLOWLIST=

# External
HPR_VERIFY_URL=
SMS_GATEWAY_URL=
DPO_NOTIFICATION_EMAIL=
```

**Checklist Step 9 applies without exception: never commit secrets, private keys, tokens or a populated `.env` to Git, and never paste them into team chat.**

---

*`Day1.md` · SETU-Swasthya backend · Role-Based Identity, Registration & Access Control · v1.0*
