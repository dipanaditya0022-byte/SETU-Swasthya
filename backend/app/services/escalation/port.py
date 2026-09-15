"""The seam between a future GET /referrals/exceptions route and any
escalation-evaluation engine.

Mirrors app/services/triage/port.py exactly, one layer over: routes (and
app/services/escalation/factory.py) depend on EscalationEngine -- a
Protocol -- and are never allowed to import a concrete engine
implementation directly. This is what lets GET /referrals/exceptions ship
today whether or not SD's escalation_for() exists, is broken, or isn't
ready: swap the concrete engine, and the Protocol/route never change. No
route is touched in this step -- this module and its siblings
(fallback.py, adapter.py, factory.py) exist so that wiring, in a later
step, is a one-line dependency swap rather than new design.

EscalationInput/EscalationOutput's field names, types, and the three
permitted escalate_to_role values (ASHA / CHO / BMO, confirmed against
app/models/enums.py's RoleCode -- all three are real role codes in this
repo) are this step's own spec, given verbatim by the task that produced
this file. Nothing here is copied from Day1.md: Day1.md does not define an
escalation engine. `status` is carried as `str` here (not
app.models.referral_state.ReferralState) because EscalationInput is a
Protocol-boundary DTO, exactly like TriageInput/TriageOutput never import
a DB-backed SQLModel type either -- see FallbackEscalationEngine
(fallback.py) for where ReferralState is actually consulted, by value,
against this string.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

EscalateToRole = Literal["ASHA", "CHO", "BMO"]


class EscalationEngineError(Exception):
    """Raised by an EscalationEngine implementation (concretely, by
    RuleEscalationEngineAdapter in adapter.py) when it cannot produce a
    valid EscalationOutput -- the wrapped engine isn't importable, isn't
    callable, raised, or returned a shape that doesn't satisfy
    EscalationOutput. Callers (the factory's readiness probe, and
    eventually a route) use this single exception type to detect "this
    engine is not usable right now" without needing to know which
    underlying engine failed or why. Mirrors TriageEngineError
    (app/services/triage/port.py) exactly."""


class EscalationInput(BaseModel):
    urgency: str
    initiated_at: datetime
    due_at: datetime
    now: datetime
    current_stage: int
    owner_user_id: UUID | None = None
    status: str


class EscalationOutput(BaseModel):
    stage: int  # 0..3
    escalate_to_role: EscalateToRole | None = None
    escalate_to_user_id: UUID | None = None
    due_action_at: datetime | None = None
    message: str  # plain language, no rule IDs, no scores
    engine: str = "rule"


class EscalationEngine(Protocol):
    name: str

    def escalate(self, data: EscalationInput) -> EscalationOutput: ...
