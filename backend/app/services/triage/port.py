"""The seam between routes and any triage-evaluation engine.

Routes (and app/services/triage/factory.py) depend on TriageEngine -- a
Protocol -- and are never allowed to import a concrete engine
implementation directly. This is what lets the eventual evaluation step
of POST /triage/ work whether SD's rule engine is ready, broken, or
doesn't exist yet: swap the concrete engine, and the Protocol/routes
never change. No route is touched in this step -- this module and its
siblings (fallback.py, adapter.py, factory.py) exist so that wiring, in
a later step, is a one-line dependency swap rather than new design.

TriageInput/TriageOutput's field names, types, and the four permitted
Disposition / six permitted Urgency values are this step's own spec.
Nothing here is copied from Day1.md: Day1.md's own triage surface is
the pre-existing, contract-frozen `POST /triage/` endpoint (a coarser
shape -- see app/models/triage_encounter.py and
app/api/routes/triage.py) and is not to be confused with this engine
seam, which sits *behind* that endpoint and is not wired to it yet.
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

Disposition = Literal["MANAGE_HERE", "TELECONSULT", "REFER", "EMERGENCY"]
Urgency = Literal["IMMEDIATE", "WITHIN_2H", "WITHIN_24H", "WITHIN_72H", "WITHIN_7D", "ROUTINE"]


class TriageEngineError(Exception):
    """Raised by a TriageEngine implementation (concretely, by
    RuleEngineAdapter in adapter.py) when it cannot produce a valid
    TriageOutput -- the wrapped engine isn't importable, isn't
    callable, raised, or returned a shape that doesn't satisfy
    TriageOutput. Callers (the factory's readiness probe, and
    eventually a route) use this single exception type to detect "this
    engine is not usable right now" without needing to know which
    underlying engine failed or why."""


class TriageInput(BaseModel):
    protocol: Literal["ANC", "IMNCI", "NCD", "TB", "FEVER", "INJURY", "GENERAL"]
    age_years: float | None = None
    sex: Literal["FEMALE", "MALE", "OTHER"] | None = None
    is_pregnant: bool = False
    gestational_weeks: float | None = None
    vitals: dict[str, float] = Field(default_factory=dict)
    symptoms: list[str] = Field(default_factory=list)
    danger_signs: list[str] = Field(default_factory=list)
    history: dict[str, bool] = Field(default_factory=dict)


class TriageOutput(BaseModel):
    disposition: Disposition
    urgency: Urgency
    reason: str  # plain language, no rule IDs, safe to read aloud
    red_flags: list[str]
    protocol_version: str
    insufficient_data: bool = False
    missing_fields: list[str] = Field(default_factory=list)


class TriageEngine(Protocol):
    name: str

    def evaluate(self, data: TriageInput) -> TriageOutput: ...
