# Day 2 — Integration

**SETU-Swasthya Backend · Specification & Definition of Done**

| Field | Value |
|---|---|
| Document | `Day2.md` |
| Integration Owner | **Iqra** (per blueprint rotation — heaviest cross-stream wiring today) |
| Builds on | `Day1.md` (identity, RBAC, registration) |
| Stack | FastAPI · SQLModel · PostgreSQL 15+ · Alembic · pytest |
| Branch | `backend` |
| Companion | `Day2Prompt.md` (self-contained build prompts) |
| Streams | **Iqra** (integration) · **Aditya** (referral core + dashboard) · **SD** (rule engine + escalation logic) |

---

## 0. The rules that carry over from Day 1

These are not restated per task. They apply to every line of Day 2 work.

| # | Rule |
|---|---|
| **C1** | **Additive only.** `/health`, `/patients/`, `/patients/{id}`, `/triage/`, `/referrals/`, `/referrals/{id}/status`, `/sync/`, `/login`, `/me` keep their exact paths, request fields and response fields. Day 2 **adds** fields to responses; it removes and renames nothing. |
| **C2** | No secrets in any file, comment, log line or fixture. |
| **C3** | Fail closed. Every authorisation check denies by default. |
| **C5** | Development data only. |
| **C6** | Never hide an environment error. A failing migration gets fixed, not worked around. |
| **C7** | No git from the developer agent. `git-manager` handles version control. |
| **RBAC** | Every endpoint added today carries a `require(...)` permission dependency **and** a scope check. An endpoint without both is not done. |

**The one new rule for Day 2:**

> **C8 — Never block on another stream.** Every cross-stream dependency is consumed through a port with a working fallback. If SD's function is not ready, the endpoint still returns a correct-shaped, safe answer, logs that it used the fallback, and records the decision. A blocked integration owner is an integration failure.

---

## 1. Task ownership and dependency map

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         DAY 2 BACKEND INTEGRATION                        │
└──────────────────────────────────────────────────────────────────────────┘

  SD (rule / logic stream)              provides
  ┌──────────────────────┐
  │ evaluate_triage()    │──────────┐
  │ escalation_for()     │────┐     │
  └──────────────────────┘    │     │
                              │     │  consumed through a PORT, never imported
                              │     │  directly into a route
                              ▼     ▼
  IQRA (integration)     ┌─────────────────────────────────────────┐
  ┌───────────────────┐  │  app/services/triage/port.py            │
  │ T1  Wire triage   │──┤  app/services/escalation/port.py        │
  │     decisioning   │  │  each with a Fallback implementation    │
  │     into /triage/ │  └─────────────────────────────────────────┘
  ├───────────────────┤
  │ T4  GET           │◄──────── depends on ────────┐
  │     /referrals/   │                             │
  │     exceptions    │                             │
  └───────────────────┘                             │
                                                    │
  ADITYA (referral core)                            │
  ┌────────────────────────────┐                    │
  │ T2  Referral state machine │────────────────────┘
  │     + invalid-transition   │   breach detection feeds the exceptions list
  │       guard                │
  │     + breach detection     │
  ├────────────────────────────┤
  │ T3  GET /dashboard/        │
  │     facility/{id}          │
  └────────────────────────────┘
```

| ID | Task | Owner | Depends on | Blocked if dependency missing? |
|---|---|---|---|---|
| **T1** | Wire triage decisioning into `POST /triage/` | Iqra | SD `evaluate_triage()` | **No** — fallback engine |
| **T2** | Referral state machine + transition guard | Aditya | — | No |
| **T3** | Breach detection | Aditya | T2 | No |
| **T4** | `GET /referrals/exceptions` | Iqra | T2, T3, SD `escalation_for()` | **No** — fallback escalation |
| **T5** | `GET /dashboard/facility/{id}` | Aditya | T2, T3 | No |

**Nothing on Day 2 is blocked by another stream.** That is a design property, not luck — it comes from C8 and the port pattern in §2.

---

## 2. Cross-stream contracts

### 2.1 Definition of Ready — SD's `evaluate_triage()`

Iqra must confirm all six before wiring the real engine. Any single failure means the fallback is used and the decision is logged.

| # | Ready criterion | How to check |
|---|---|---|
| R1 | The module imports cleanly inside `.venv` | `python -c "from app.services.triage.rules import evaluate_triage"` |
| R2 | It is callable with the agreed input shape | Call it with the fixture in §3.3 |
| R3 | It returns all five required output fields | Assert on the returned object |
| R4 | `disposition` is one of the four permitted values | Assert membership |
| R5 | It is **pure** — no DB access, no network, no I/O | Read the source; grep for `session`, `requests`, `httpx`, `open(` |
| R6 | It carries a `protocol_version` string | Assert non-empty |

**If any of R1–R6 fails:** use `FallbackTriageEngine`, log a `WARNING` naming the failed criterion, set `engine: "fallback"` in the response, and write an audit row with action `TRIAGE_FALLBACK_USED`. Do not silently degrade — a fallback nobody knows about is worse than a missing feature.

### 2.2 The port pattern

Routes never import SD's code directly. They depend on a Protocol, and a factory selects the implementation.

```
app/services/triage/
├── port.py       TriageEngine Protocol · TriageInput · TriageOutput
├── fallback.py   FallbackTriageEngine — deterministic, always available
├── adapter.py    RuleEngineAdapter — wraps SD's evaluate_triage()
└── factory.py    get_triage_engine() — readiness probe + selection + logging
```

This means SD can change the internals of `evaluate_triage()` freely, and Iqra's endpoint keeps working as long as the port contract holds. It also means the fallback is testable in isolation, which is what makes T1 finishable today.

### 2.3 Engine selection

`TRIAGE_ENGINE` in `.env`:

| Value | Behaviour |
|---|---|
| `auto` | **Default.** Probe R1–R6 at startup. Use the rule engine if all pass, otherwise the fallback. Log the choice once at startup and include `engine` in every response |
| `rule` | Force the rule engine. **Fail startup loudly** if it is not ready — for CI and staging, where a silent fallback would mask a real regression |
| `fallback` | Force the fallback. For local development and for tests that assert fallback behaviour |

The probe runs **once at startup**, not per request. A per-request import probe is a latency and log-noise problem.

---

## 3. T1 — Wire triage decisioning into `POST /triage/`

**Owner: Iqra**

### 3.1 What changes and what does not

`POST /triage/` keeps its path, its method, and every existing request and response field. Day 2 adds computed fields to the response.

> **The core requirement: the disposition is computed by the server, never supplied by the caller.**
>
> If the request body contains `disposition`, `urgency`, `red_flags` or `reason`, those values are **ignored**, and an `INFO` line records that the client sent them. A caller-supplied disposition would let a client mark an eclamptic patient as `MANAGE_HERE`, which defeats the entire point of triage.

### 3.2 Order of operations inside the endpoint

```
1. AuthN + AuthZ            require("triage:create") + scope check on patient
2. Validate request body    Pydantic; ignore any caller-supplied decision fields
3. Load patient context     latest vitals, gestational age, age, sex, registries
4. CALL THE ENGINE          ← before persistence. This is the point of the task
5. Persist                  triage row INCLUDING the computed decision fields
6. Audit                    TRIAGE_EVALUATED with engine, version, disposition
7. Return                   existing fields + computed fields
```

**Step 4 must precede step 5.** If the engine is called after persistence, a row exists with no disposition, and any crash between the two leaves an un-triaged encounter in the database. Compute, then write once.

### 3.3 The port contract

```python
# app/services/triage/port.py
from typing import Protocol, Literal
from pydantic import BaseModel, Field

Disposition = Literal["MANAGE_HERE", "TELECONSULT", "REFER", "EMERGENCY"]
Urgency     = Literal["IMMEDIATE", "WITHIN_2H", "WITHIN_24H", "WITHIN_72H", "WITHIN_7D", "ROUTINE"]


class TriageInput(BaseModel):
    protocol: Literal["ANC", "IMNCI", "NCD", "TB", "FEVER", "INJURY", "GENERAL"]
    age_years: float | None = None
    sex: Literal["FEMALE", "MALE", "OTHER"] | None = None
    is_pregnant: bool = False
    gestational_weeks: float | None = None
    vitals: dict[str, float] = Field(default_factory=dict)   # bp_systolic, bp_diastolic,
                                                             # temperature_c, spo2, pulse,
                                                             # haemoglobin, respiratory_rate,
                                                             # blood_glucose, muac_cm, weight_kg
    symptoms: list[str] = Field(default_factory=list)        # coded symptom keys
    danger_signs: list[str] = Field(default_factory=list)
    history: dict[str, bool] = Field(default_factory=dict)   # prior_lscs, known_htn, etc.


class TriageOutput(BaseModel):
    disposition: Disposition
    urgency: Urgency
    reason: str                       # plain language, patient-facing safe, no rule IDs
    red_flags: list[str]              # coded flags that fired
    protocol_version: str             # e.g. "v1.2"
    insufficient_data: bool = False
    missing_fields: list[str] = Field(default_factory=list)


class TriageEngine(Protocol):
    name: str
    def evaluate(self, data: TriageInput) -> TriageOutput: ...
```

### 3.4 Fallback engine rules

Deterministic, auditable, biased toward escalation. **Illustrative thresholds — the Clinical Governance Committee signs off the real set before any patient use.**

```
PROTOCOL: ANC (pregnancy)
  bp_systolic >= 160 OR bp_diastolic >= 110      → EMERGENCY / IMMEDIATE
  "convulsions" in danger_signs                   → EMERGENCY / IMMEDIATE
  "pv_bleeding" in danger_signs                   → EMERGENCY / IMMEDIATE
  haemoglobin < 5.0                               → EMERGENCY / IMMEDIATE
  bp_systolic >= 140 OR bp_diastolic >= 90        → REFER / WITHIN_24H
  "severe_headache" AND "blurred_vision"          → REFER / WITHIN_24H
  haemoglobin < 7.0                               → REFER / WITHIN_72H
  temperature_c >= 38.0                           → TELECONSULT / WITHIN_24H
  "reduced_fetal_movement" in danger_signs        → REFER / WITHIN_24H
  otherwise                                        → MANAGE_HERE / ROUTINE

PROTOCOL: IMNCI (under-five)
  "convulsions" OR "unable_to_feed" OR "lethargic" → EMERGENCY / IMMEDIATE
  spo2 < 90                                        → EMERGENCY / IMMEDIATE
  respiratory_rate >= 60 (age < 2 months)          → EMERGENCY / IMMEDIATE
  respiratory_rate >= 50 (2-12 months)             → REFER / WITHIN_24H
  respiratory_rate >= 40 (12-59 months)            → REFER / WITHIN_24H
  muac_cm < 11.5                                   → REFER / WITHIN_72H
  temperature_c >= 38.5                            → TELECONSULT / WITHIN_24H
  otherwise                                         → MANAGE_HERE / ROUTINE

PROTOCOL: NCD
  bp_systolic >= 180 OR bp_diastolic >= 120        → EMERGENCY / IMMEDIATE
  blood_glucose > 400 OR blood_glucose < 54        → EMERGENCY / IMMEDIATE
  bp_systolic >= 160 OR bp_diastolic >= 100        → REFER / WITHIN_72H
  bp_systolic >= 140 OR bp_diastolic >= 90         → TELECONSULT / WITHIN_7D
  otherwise                                         → MANAGE_HERE / ROUTINE

ALL PROTOCOLS — checked FIRST, before anything above
  spo2 < 90 OR pulse > 130 OR pulse < 40
    OR temperature_c >= 39.5 OR temperature_c <= 35.0
    OR "unconscious" in danger_signs                → EMERGENCY / IMMEDIATE

INSUFFICIENT DATA — checked LAST, only if nothing above fired
  required vitals for the protocol are missing
    → REFER / WITHIN_24H
      insufficient_data = true
      missing_fields = [...]
      reason = "Not enough information to be sure. Treating this as needing
                a doctor's opinion."
```

Required vitals per protocol: **ANC** — `bp_systolic`, `bp_diastolic`. **IMNCI** — `temperature_c`, `respiratory_rate`. **NCD** — `bp_systolic`, `bp_diastolic`. **Others** — none.

> **The escalation-on-uncertainty rule is the safety heart of this task.** The engine never returns `MANAGE_HERE` for an incomplete assessment, and it never fails silently. Missing data escalates upward with an explicit reason. Write the test for this before you write the code.

### 3.5 Response shape

Existing fields unchanged; `decision` is added.

```json
{
  "id": "b3d1...",
  "patient_id": "9c1f...",
  "protocol": "ANC",
  "vitals": { "bp_systolic": 156, "bp_diastolic": 98 },
  "symptoms": ["severe_headache"],
  "created_at": "2026-08-30T09:41:00Z",

  "decision": {
    "disposition": "REFER",
    "urgency": "WITHIN_24H",
    "reason": "Blood pressure is 156/98 with a headache. Together these can be dangerous in pregnancy.",
    "red_flags": ["HYPERTENSION_MODERATE", "HEADACHE_SEVERE"],
    "protocol_version": "v1.2",
    "insufficient_data": false,
    "missing_fields": [],
    "engine": "rule",
    "evaluated_at": "2026-08-30T09:41:00Z"
  }
}
```

`engine` is `"rule"` or `"fallback"`. It is in the response deliberately — a clinician and a reviewer both need to know which logic produced the answer.

### 3.6 Definition of Done — T1

- [ ] A real HTTP `POST /triage/` returns a **computed** disposition
- [ ] A caller-supplied `disposition` in the body is ignored and logged
- [ ] Emergency vitals produce `EMERGENCY` / `IMMEDIATE`
- [ ] Missing required vitals produce `REFER` with `insufficient_data: true` — never `MANAGE_HERE`, never a silent pass
- [ ] The engine is called **before** persistence
- [ ] Every existing response field is still present and unchanged
- [ ] `engine` reports which implementation ran
- [ ] With `TRIAGE_ENGINE=rule` and SD's module absent, **startup fails loudly**
- [ ] With `TRIAGE_ENGINE=auto` and SD's module absent, the fallback runs, a `WARNING` is logged, and an audit row is written
- [ ] `require("triage:create")` and the patient scope check are both applied

---

## 4. T2 — Referral state machine

**Owner: Aditya**

### 4.1 States

```
                          ┌───────────────┐
                          │   INITIATED   │
                          └───────┬───────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
      ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
      │  SLOT_BOOKED  │   │  TRANSPORT_   │   │   CANCELLED   │ ◄─ terminal
      │               │   │   ARRANGED    │   └───────────────┘
      └───────┬───────┘   └───────┬───────┘
              │                   │
              └─────────┬─────────┘
                        ▼
                ┌───────────────┐        ┌───────────────┐
                │    ARRIVED    │        │  NOT_ARRIVED  │ ◄── breach detected
                └───────┬───────┘        └───────┬───────┘     or marked manually
                        │                        │
                        ▼                        ▼
                ┌───────────────┐        ┌───────────────┐
                │   CONSULTED   │        │    TRACED     │
                └───────┬───────┘        └───────┬───────┘
                        │                        │
                        ▼            ┌───────────┼───────────┐
                ┌───────────────┐    ▼           ▼           ▼
                │ BACK_REFERRED │  ┌────────┐┌────────┐┌────────┐
                └───────┬───────┘  │RESCHED-││REFUSED ││  LOST  │
                        │          │ ULED   │└───┬────┘└───┬────┘
                        │          └───┬────┘    │         │
                        │              │         │         │
                        │              └──► back to SLOT_BOOKED
                        │                        │         │
                        ▼                        ▼         ▼
                ┌────────────────────────────────────────────┐
                │                  CLOSED                    │ ◄─ terminal
                └────────────────────────────────────────────┘
```

### 4.2 Transition table — the authoritative source

```python
# app/models/referral_state.py
from enum import Enum

class ReferralStatus(str, Enum):
    INITIATED           = "INITIATED"
    SLOT_BOOKED         = "SLOT_BOOKED"
    TRANSPORT_ARRANGED  = "TRANSPORT_ARRANGED"
    ARRIVED             = "ARRIVED"
    CONSULTED           = "CONSULTED"
    BACK_REFERRED       = "BACK_REFERRED"
    CLOSED              = "CLOSED"
    CANCELLED           = "CANCELLED"
    NOT_ARRIVED         = "NOT_ARRIVED"
    TRACED              = "TRACED"
    RESCHEDULED         = "RESCHEDULED"
    REFUSED             = "REFUSED"
    LOST                = "LOST"


ALLOWED_TRANSITIONS: dict[ReferralStatus, set[ReferralStatus]] = {
    ReferralStatus.INITIATED:          {ReferralStatus.SLOT_BOOKED,
                                        ReferralStatus.TRANSPORT_ARRANGED,
                                        ReferralStatus.NOT_ARRIVED,
                                        ReferralStatus.CANCELLED},

    ReferralStatus.SLOT_BOOKED:        {ReferralStatus.TRANSPORT_ARRANGED,
                                        ReferralStatus.ARRIVED,
                                        ReferralStatus.NOT_ARRIVED,
                                        ReferralStatus.CANCELLED},

    ReferralStatus.TRANSPORT_ARRANGED: {ReferralStatus.ARRIVED,
                                        ReferralStatus.NOT_ARRIVED,
                                        ReferralStatus.CANCELLED},

    ReferralStatus.ARRIVED:            {ReferralStatus.CONSULTED,
                                        ReferralStatus.CANCELLED},

    ReferralStatus.CONSULTED:          {ReferralStatus.BACK_REFERRED,
                                        ReferralStatus.CLOSED},

    ReferralStatus.BACK_REFERRED:      {ReferralStatus.CLOSED},

    ReferralStatus.NOT_ARRIVED:        {ReferralStatus.TRACED,
                                        ReferralStatus.LOST},

    ReferralStatus.TRACED:             {ReferralStatus.RESCHEDULED,
                                        ReferralStatus.REFUSED,
                                        ReferralStatus.LOST},

    ReferralStatus.RESCHEDULED:        {ReferralStatus.SLOT_BOOKED,
                                        ReferralStatus.TRANSPORT_ARRANGED,
                                        ReferralStatus.CANCELLED},

    ReferralStatus.REFUSED:            {ReferralStatus.CLOSED},
    ReferralStatus.LOST:               {ReferralStatus.CLOSED},

    ReferralStatus.CLOSED:             set(),      # terminal
    ReferralStatus.CANCELLED:          set(),      # terminal
}

TERMINAL_STATES  = {ReferralStatus.CLOSED, ReferralStatus.CANCELLED}
COMPLETED_STATES = {ReferralStatus.ARRIVED, ReferralStatus.CONSULTED,
                    ReferralStatus.BACK_REFERRED, ReferralStatus.CLOSED}
```

### 4.3 The guard

```python
class InvalidTransition(Exception):
    def __init__(self, current, requested, allowed):
        self.current, self.requested, self.allowed = current, requested, allowed


def assert_transition_allowed(current: ReferralStatus, requested: ReferralStatus) -> None:
    if current in TERMINAL_STATES:
        raise InvalidTransition(current, requested, set())
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if requested not in allowed:
        raise InvalidTransition(current, requested, allowed)
```

`INITIATED → CLOSED` is the canonical rejection. It must return **409** with the allowed set named:

```json
{
  "error": {
    "code": "INVALID_TRANSITION",
    "message": "This referral cannot move to that stage yet.",
    "detail": "A referral in INITIATED can move to: SLOT_BOOKED, TRANSPORT_ARRANGED, NOT_ARRIVED, CANCELLED.",
    "current_status": "INITIATED",
    "requested_status": "CLOSED",
    "allowed_next": ["SLOT_BOOKED", "TRANSPORT_ARRANGED", "NOT_ARRIVED", "CANCELLED"],
    "request_id": "..."
  }
}
```

Naming the allowed set is deliberate: a client that receives only "invalid" has to guess, and a guessing client retries randomly.

### 4.4 Required side effects per transition

| Transition | Required field | Additional effect |
|---|---|---|
| `→ SLOT_BOOKED` | `slot_datetime`, `destination_org_unit_id` | Clears any prior breach flag |
| `→ TRANSPORT_ARRANGED` | `transport_mode` | — |
| `→ ARRIVED` | `arrival_confirmed_by` **or** `arrival_scan_ref` | **Stops the breach clock.** Sets `arrived_at` |
| `→ CONSULTED` | `consulted_by_user_id` | — |
| `→ BACK_REFERRED` | `back_referral_note` | Sets `back_referred_at` |
| `→ CLOSED` | — | Sets `closed_at`, `closure_outcome` |
| `→ NOT_ARRIVED` | — | Starts escalation. Sets `not_arrived_at`, `escalation_stage = 1` |
| `→ TRACED` | `traced_by_user_id` | — |
| `→ REFUSED` | `refusal_reason` (enum) | Feeds district planning data |
| `→ LOST` | `loss_reason` | — |
| `→ CANCELLED` | `cancellation_reason` | — |
| `→ RESCHEDULED` | — | Resets `breached_at` to NULL, restarts the clock |

`refusal_reason` enum: `COST`, `DISTANCE`, `FAMILY_DECIDED_AGAINST`, `ALREADY_RECOVERED`, `WENT_PRIVATE`, `COULD_NOT_BE_CONTACTED`, `OTHER`.

**Arrival requires proof.** `arrival_confirmed_by` with a manual-entry reason, or `arrival_scan_ref` from an ABHA scan. Without this, the referral completion rate becomes whatever people feel like ticking, and the indicator is worthless.

### 4.5 Transition audit table

Every transition writes a row. This is what makes the timeline reconstructable and the completion rate defensible.

```sql
CREATE TABLE referral_transitions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    referral_id       UUID NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
    from_status       TEXT,
    to_status         TEXT NOT NULL,
    actor_user_id     UUID REFERENCES users(id),
    actor_role        TEXT,
    reason            TEXT,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_referral_transitions_ref ON referral_transitions (referral_id, occurred_at);
```

### 4.6 Definition of Done — T2

- [ ] All 13 states in the enum
- [ ] `ALLOWED_TRANSITIONS` matches §4.2 exactly
- [ ] A full valid sequence `INITIATED → … → CLOSED` succeeds end to end
- [ ] `INITIATED → CLOSED` returns **409 INVALID_TRANSITION** naming `allowed_next`
- [ ] Every terminal state rejects all outbound transitions
- [ ] Required fields per transition are enforced with a specific `422`
- [ ] `ARRIVED` requires arrival proof
- [ ] `referral_transitions` records every change
- [ ] `PATCH /referrals/{id}/status` keeps its existing path and request shape
- [ ] A parametrised test covers **all 169** `(from, to)` pairs

---

## 5. T3 — Breach detection

**Owner: Aditya**

### 5.1 Urgency windows

| Urgency | Window from `initiated_at` | Escalation chain |
|---|---|---|
| `EMERGENCY` | 1 hour | Immediate — ASHA + CHO + BMO simultaneously |
| `URGENT` | 24 hours | ASHA D+1 → CHO D+1 → BMO D+2 |
| `PRIORITY` | 72 hours | ASHA D+3 → CHO D+4 → BMO D+5 |
| `ROUTINE` | 7 days | ASHA D+8 → CHO D+10 |
| `ELECTIVE` | 30 days | Registry recall only |

### 5.2 Breach definition

> A referral is **breached** when `now() > initiated_at + window(urgency)` and its status is **not** in `COMPLETED_STATES` and **not** `CANCELLED`.

`RESCHEDULED` resets `breached_at` to NULL and restarts the clock from the reschedule time. Without that reset, a rebooked referral stays permanently red and the exceptions list fills with noise nobody acts on.

### 5.3 Fields on `referrals`

```
urgency               TEXT NOT NULL DEFAULT 'ROUTINE'
initiated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
due_at                TIMESTAMPTZ            -- computed: initiated_at + window
breached_at           TIMESTAMPTZ            -- NULL until breached
breach_detected_by    TEXT                   -- 'JOB' | 'REQUEST'
escalation_stage      SMALLINT NOT NULL DEFAULT 0   -- 0 none, 1 ASHA, 2 CHO, 3 BMO
escalation_notified_at TIMESTAMPTZ
owner_user_id         UUID REFERENCES users(id)
arrived_at            TIMESTAMPTZ
back_referred_at      TIMESTAMPTZ
closed_at             TIMESTAMPTZ
```

### 5.4 Two detection paths, one function

```python
def is_breached(referral, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    if referral.status in COMPLETED_STATES or referral.status == ReferralStatus.CANCELLED:
        return False
    return now > referral.due_at
```

- **Lazy** — evaluated on read in `/referrals/exceptions`, so the list is correct even if the job has not run.
- **Job** — `detect_breaches()` runs every 15 minutes, stamps `breached_at`, advances `escalation_stage`, writes an audit row and notifies.

Both use the same `is_breached`. Two implementations of a breach rule will disagree, and the day they disagree is the day someone argues the dashboard is wrong.

### 5.5 Definition of Done — T3

- [ ] `due_at` computed on creation and on reschedule
- [ ] `is_breached()` is the single source of truth, used by both paths
- [ ] A referral past its window and not arrived is breached
- [ ] A referral that reached `ARRIVED` inside the window is **never** breached
- [ ] `CANCELLED` is never breached
- [ ] `RESCHEDULED` clears `breached_at` and recomputes `due_at`
- [ ] `detect_breaches()` is idempotent — running it twice does not double-escalate
- [ ] Escalation advances 0 → 1 → 2 → 3 and stops at 3

---

## 6. T4 — `GET /referrals/exceptions`

**Owner: Iqra** · Depends on T2, T3, and SD's `escalation_for()`

### 6.1 Purpose

The exception-first view. A manager opening this endpoint sees what is broken, who owns it, and by when — not a list of everything.

### 6.2 Escalation port

Same pattern as triage. SD provides `escalation_for()`; Iqra consumes it through a port with a fallback.

```python
# app/services/escalation/port.py
class EscalationInput(BaseModel):
    urgency: str
    initiated_at: datetime
    due_at: datetime
    now: datetime
    current_stage: int
    owner_user_id: UUID | None
    status: str

class EscalationOutput(BaseModel):
    stage: int                      # 0..3
    escalate_to_role: str | None    # 'ASHA' | 'CHO' | 'BMO' | None
    escalate_to_user_id: UUID | None
    due_action_at: datetime | None
    message: str
    engine: str = "rule"

class EscalationEngine(Protocol):
    name: str
    def escalate(self, data: EscalationInput) -> EscalationOutput: ...
```

Fallback implementation uses the fixed chain in §5.1 — hours elapsed past `due_at` maps to a stage. Readiness criteria mirror §2.1.

### 6.3 Request

```
GET /referrals/exceptions
    ?scope=block|facility|mine        default: caller's own scope
    &urgency=EMERGENCY,URGENT
    &stage=1,2,3
    &breach_only=true                 default true
    &org_unit_id=<uuid>               must be within the caller's scope
    &limit=50&offset=0
```

Permission: `referral:read`. Scope: results are always filtered to the caller's org subtree. An out-of-scope `org_unit_id` returns **404**, not 403 — consistent with `Day1.md` §16.2, so probing IDs reveals nothing.

### 6.4 Response

```json
{
  "summary": {
    "breached": 11,
    "at_risk": 4,
    "total_open": 63,
    "breach_rate": { "numerator": 11, "denominator": 63, "rate_pct": 17.5 }
  },
  "items": [
    {
      "referral_id": "7f3c...",
      "patient": { "id": "9c1f...", "name": "Rekha Devi", "age_years": 28, "sex": "FEMALE" },
      "reason": "High BP in pregnancy",
      "urgency": "URGENT",
      "status": "TRANSPORT_ARRANGED",
      "allowed_next": ["ARRIVED", "NOT_ARRIVED", "CANCELLED"],
      "origin_org_unit": { "id": "...", "name": "Nai Basti HWC" },
      "destination_org_unit": { "id": "...", "name": "District Hospital" },
      "initiated_at": "2026-08-28T09:00:00Z",
      "due_at": "2026-08-29T09:00:00Z",
      "breached_at": "2026-08-29T09:15:00Z",
      "overdue_hours": 48.7,
      "escalation": {
        "stage": 2,
        "escalate_to_role": "CHO",
        "escalate_to_user_id": "...",
        "due_action_at": "2026-08-30T09:00:00Z",
        "message": "Not reached the hospital 2 days after referral. CHO to call the family.",
        "engine": "fallback"
      },
      "owner": { "user_id": "...", "name": "Sunita Devi", "role": "ASHA" }
    }
  ],
  "pagination": { "limit": 50, "offset": 0, "total": 11 }
}
```

Every item carries an **owner and a due date**. An exception with no owner is rendered with `"owner": null` and `"needs_owner": true` — because unowned problems are the ones that persist.

Sort order is fixed and not client-controllable: `EMERGENCY` first, then by `overdue_hours` descending. A client that can re-sort by date can bury a breached emergency below a routine reminder.

### 6.5 Definition of Done — T4

- [ ] A deliberately breached referral appears in the list
- [ ] A referral inside its window does **not** appear when `breach_only=true`
- [ ] Every item carries owner, due date and escalation stage
- [ ] Scope filtering works; cross-block access returns 404
- [ ] `require("referral:read")` applied
- [ ] Works with the fallback escalation engine and reports `"engine": "fallback"`
- [ ] Sort order is server-fixed
- [ ] `breach_rate` is returned as numerator ÷ denominator ÷ rate, never a bare count

---

## 7. T5 — `GET /dashboard/facility/{id}`

**Owner: Aditya**

### 7.1 Request

```
GET /dashboard/facility/{org_unit_id}?date=2026-08-30
```

Permission: `dashboard:facility`. Scope: `org_unit_id` must be within the caller's subtree, else **404**. `date` defaults to today in the facility's timezone — not the server's, or a facility one timezone away gets yesterday's numbers.

### 7.2 Response — denominators always

```json
{
  "facility": { "id": "...", "name": "Rampur PHC", "type": "PHC" },
  "date": "2026-08-30",
  "metrics": {
    "open_referrals":   { "count": 63 },
    "triage_today":     { "count": 41 },
    "breached":         { "numerator": 11, "denominator": 63, "rate_pct": 17.5 },
    "synced_today":     { "numerator": 38, "denominator": 41, "rate_pct": 92.7 }
  },
  "generated_at": "2026-08-30T14:22:00Z"
}
```

### 7.3 Metric definitions — write these into the code as docstrings

| Metric | Numerator | Denominator |
|---|---|---|
| `open_referrals` | Referrals with `org_unit_id` = this facility and status **not** in `TERMINAL_STATES` | — |
| `triage_today` | Triage encounters created at this facility on `date` | — |
| `breached` | Open referrals where `is_breached()` is true | `open_referrals` |
| `synced_today` | Records from this facility with `synced_at` on `date` | Records created on `date` |

> **`synced_at` may not exist yet.** `Day1.md` never creates it, and the `/sync/` table schema is Aditya's Day 1 work, undocumented in either spec. Before implementing this metric, read the sync table from the repository. If no `synced_at` column exists on `patients`, `triage` and `referrals`, add it in migration `0012` as a nullable `TIMESTAMPTZ`, and set it in the `/sync/` handler on write. Do not compute this metric from a column you assumed into existence.

Ambiguity in a metric definition is how two dashboards end up disagreeing in a review meeting.

### 7.4 Implementation notes

- **One query per metric, or one CTE — not a Python loop over rows.** Counting 63 referrals in Python by fetching them all is fine today and unusable at district scale.
- Index `referrals (org_unit_id, status)` and `triage (org_unit_id, created_at)`. Note: the origin facility column is `org_unit_id`, created by `Day1.md` migration `0008` — there is no `origin_org_unit_id`. `destination_org_unit_id` is new in `0010`.
- Cache for 60 seconds keyed on `(org_unit_id, date)`. A dashboard does not need to be real-time; it needs to be fast and consistent within a page view.

### 7.5 Definition of Done — T5

- [ ] Seeded data produces the exact expected counts
- [ ] `breached` and `synced_today` carry numerator, denominator and rate
- [ ] Out-of-scope facility returns 404
- [ ] `require("dashboard:facility")` applied
- [ ] A facility with no activity returns zeros, not 404 and not an error
- [ ] No N+1 queries — verified by counting queries in a test

---

## 8. Migrations

| # | Revision | Contents |
|---|---|---|
| 1 | `0010_referral_state_machine` | `referral_status` enum; new columns on `referrals`; `referral_transitions` table; backfill existing rows |
| 2 | `0011_triage_decision` | Decision columns on `triage`; backfill existing rows as `UNEVALUATED` |
| 3 | `0012_dashboard_indexes` | Composite indexes for the aggregation queries |

### 8.1 The backfill that needs care — 0010

`referrals.status` already exists and holds Day 1 values. Adding an enum and new NOT NULL columns to a populated table needs the three-phase pattern from `Day1.md` §17.1.

```
Phase 1  CREATE TYPE referral_status
Phase 2  ADD COLUMN urgency, due_at, breached_at, escalation_stage … all NULLABLE
Phase 3  Backfill:
           urgency          → 'ROUTINE' where NULL
           initiated_at     → created_at
           due_at           → initiated_at + 7 days (ROUTINE window)
           escalation_stage → 0
         Map existing status text to the new enum; anything unrecognised
         → 'INITIATED', and LOG which rows were remapped
Phase 4  SET NOT NULL on urgency, initiated_at, escalation_stage
Phase 5  ALTER COLUMN status TYPE referral_status USING status::referral_status
```

Before running: `SELECT status, count(*) FROM referrals GROUP BY 1`. Any value not in the 13-state enum must be mapped explicitly and reported — not silently coerced.

Row counts before and after must be identical. If they differ, roll back.

### 8.2 0011 — triage decision columns

```
disposition        TEXT           -- nullable; existing rows have none
urgency            TEXT
reason             TEXT
red_flags          JSONB NOT NULL DEFAULT '[]'::jsonb
protocol_version   TEXT
insufficient_data  BOOLEAN NOT NULL DEFAULT FALSE
missing_fields     JSONB NOT NULL DEFAULT '[]'::jsonb
engine             TEXT
evaluated_at       TIMESTAMPTZ
```

`disposition` stays **nullable**. Pre-Day-2 triage rows were never evaluated, and stamping them with a fabricated disposition would put clinical decisions in the record that no engine ever made. A NULL disposition on an old row is honest.

---

## 9. API contract additions

Append to `backend/docs/API_CONTRACT.md`. **Edit no existing entry.**

| Method | Path | Permission | Status |
|---|---|---|---|
| POST | `/triage/` | `triage:create` | **Modified — additive.** Response gains `decision` |
| PATCH | `/referrals/{id}/status` | `referral:update_status` | **Modified — additive.** Guard + required fields |
| GET | `/referrals/exceptions` | `referral:read` | **New** |
| GET | `/dashboard/facility/{id}` | `dashboard:facility` | **New** |

## 10. New error codes

| Code | Status | Meaning |
|---|---|---|
| `INVALID_TRANSITION` | 409 | Not permitted from the current status; `allowed_next` returned |
| `TERMINAL_STATE` | 409 | Referral is CLOSED or CANCELLED |
| `TRANSITION_FIELD_REQUIRED` | 422 | Required field missing for this transition |
| `ARRIVAL_PROOF_REQUIRED` | 422 | `→ ARRIVED` without confirmation or scan |
| `TRIAGE_ENGINE_UNAVAILABLE` | 503 | `TRIAGE_ENGINE=rule` and the engine failed at runtime |
| `INVALID_PROTOCOL` | 422 | Unknown triage protocol |
| `FACILITY_NOT_IN_SCOPE` | 404 | Out of scope — deliberately not 403 |

---

## 11. Test plan

| ID | Test | Owner |
|---|---|---|
| **TT1** | Real HTTP POST /triage/ returns a computed disposition | Iqra |
| **TT2** | Caller-supplied `disposition` is ignored | Iqra |
| **TT3** | Emergency vitals → `EMERGENCY` / `IMMEDIATE` | Iqra |
| **TT4** | Missing required vitals → `REFER` + `insufficient_data: true` | Iqra |
| **TT5** | Response contains every pre-Day-2 field | Iqra |
| **TT6** | `TRIAGE_ENGINE=rule` with no engine → startup fails | Iqra |
| **TT7** | `TRIAGE_ENGINE=auto` with no engine → fallback + WARNING + audit row | Iqra |
| **RT1** | Full valid sequence INITIATED → CLOSED | Aditya |
| **RT2** | `INITIATED → CLOSED` → 409 with `allowed_next` | Aditya |
| **RT3** | All 169 `(from, to)` pairs match `ALLOWED_TRANSITIONS` | Aditya |
| **RT4** | Terminal states reject everything | Aditya |
| **RT5** | `→ ARRIVED` without proof → 422 | Aditya |
| **RT6** | Every transition writes a `referral_transitions` row | Aditya |
| **BT1** | Past window, not arrived → breached | Aditya |
| **BT2** | Arrived inside window → never breached | Aditya |
| **BT3** | `RESCHEDULED` clears the breach and recomputes `due_at` | Aditya |
| **BT4** | `detect_breaches()` twice → no double escalation | Aditya |
| **ET1** | Deliberately breached referral appears in `/referrals/exceptions` | Iqra |
| **ET2** | Non-breached referral absent when `breach_only=true` | Iqra |
| **ET3** | Every item has owner + due date + stage | Iqra |
| **ET4** | Cross-block request → 404 | Iqra |
| **DT1** | Seeded data → exact expected counts | Aditya |
| **DT2** | Rate metrics carry numerator and denominator | Aditya |
| **DT3** | Empty facility → zeros | Aditya |
| **CT1** | All nine Day 1 endpoints unchanged | Both |
| **CT2** | `alembic upgrade head` on a DB with Day 1 data | Both |

---

## 12. Day 2 Definition of Done

### Contract safety
- [ ] All nine Day 1 endpoints unchanged in path, request and response fields
- [ ] `/triage/` and `/referrals/{id}/status` gained fields, lost none
- [ ] `/docs` loads; `/openapi.json` valid
- [ ] `API_CONTRACT.md` extended additively

### T1 — triage
- [ ] Disposition computed server-side, never caller-supplied
- [ ] Engine runs before persistence
- [ ] Missing data escalates, never silent, never `MANAGE_HERE`
- [ ] Fallback works and reports itself

### T2 — state machine
- [ ] 13 states; guard rejects invalid transitions with 409 and `allowed_next`
- [ ] 169-pair parametrised test passes
- [ ] `ARRIVED` requires proof
- [ ] Every transition audited

### T3 — breach detection
- [ ] Single `is_breached()` used by both paths
- [ ] Job idempotent; escalation caps at stage 3

### T4 — exceptions
- [ ] Breached referral appears; non-breached does not
- [ ] Owner, due date, stage on every item
- [ ] Scope enforced; server-fixed sort

### T5 — dashboard
- [ ] Four metrics with correct definitions
- [ ] Denominators present; no N+1

### Cross-cutting
- [ ] Every new endpoint has a permission dependency **and** a scope check
- [ ] Fallback usage logged and audited, never silent
- [ ] `alembic upgrade head` succeeds on a Day 1 database; row counts unchanged
- [ ] No secret in any new file

---

*`Day2.md` · SETU-Swasthya backend · Integration · v1.0 · Companion: `Day2Prompt.md`*
