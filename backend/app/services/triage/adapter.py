"""RuleEngineAdapter -- wraps SD's evaluate_triage() rule engine behind
the TriageEngine Protocol (app/services/triage/port.py), so that routes
and app/services/triage/factory.py never import SD's module directly.
That indirection is the whole point: SD's module may not exist yet, or
may exist but not be ready, and a blocked integration owner must not be
able to block this endpoint.

MODULE PATH, pinned by the actual spec (not guessed): nothing in this
repository defines `evaluate_triage` yet -- grepped repo-wide, the only
hits are this triage/ package itself and backend/docs/Day2.md. Day2.md
Section 2.1's own readiness check (R1) is explicit and unambiguous
about where SD's module lives:

    python -c "from app.services.triage.rules import evaluate_triage"

so this adapter targets that exact path -- `app.services.triage.rules`,
module name `rules`, not `rule_engine` -- rather than inventing one.
The function is called with a single `dict` argument (`TriageInput.
model_dump()`) and is expected to return a `dict` carrying, at minimum,
the five required TriageOutput fields: disposition, urgency, reason,
red_flags, protocol_version. Day2.md does not spell out
evaluate_triage's exact parameter/return typing beyond that, so this
adapter's job -- translate in, validate out -- is what absorbs any
mismatch.

If SD's actual module differs from this (different path, different
argument shape), THIS file is what needs updating -- not port.py's
Protocol, and not the factory's readiness probe, both of which are
shape-agnostic.

The import of app.services.triage.rules happens ONLY inside evaluate()
below, never at module import time: importing this adapter module (or
the factory, which imports this module) must never fail just because
SD's module doesn't exist yet.
"""
from __future__ import annotations

from typing import Any, get_args

from pydantic import ValidationError

from app.services.triage.port import (
    Disposition,
    TriageEngineError,
    TriageInput,
    TriageOutput,
    Urgency,
)

_REQUIRED_FIELDS = ("disposition", "urgency", "reason", "red_flags", "protocol_version")


class RuleEngineAdapter:
    """Adapts SD's evaluate_triage() to the TriageEngine Protocol."""

    name = "rule"

    def evaluate(self, data: TriageInput) -> TriageOutput:
        try:
            from app.services.triage.rules import evaluate_triage
        except Exception as exc:  # noqa: BLE001 -- module absent/broken is expected until SD ships it
            raise TriageEngineError(
                f"Rule engine module (app.services.triage.rules) is not "
                f"importable: {exc}"
            ) from exc

        payload: dict[str, Any] = data.model_dump()

        try:
            raw: Any = evaluate_triage(payload)
        except Exception as exc:  # noqa: BLE001 -- any failure inside SD's code is a readiness failure, not ours
            raise TriageEngineError(
                f"Rule engine raised during evaluate_triage(): {exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise TriageEngineError(
                f"Rule engine returned {type(raw).__name__}, expected a dict."
            )

        missing = [field for field in _REQUIRED_FIELDS if field not in raw]
        if missing:
            raise TriageEngineError(f"Rule engine response is missing field(s): {missing}")

        if raw["disposition"] not in get_args(Disposition):
            raise TriageEngineError(
                f"Rule engine returned an out-of-range disposition: {raw['disposition']!r}"
            )
        if raw["urgency"] not in get_args(Urgency):
            raise TriageEngineError(
                f"Rule engine returned an out-of-range urgency: {raw['urgency']!r}"
            )

        try:
            return TriageOutput(**raw)
        except ValidationError as exc:
            raise TriageEngineError(f"Rule engine response failed validation: {exc}") from exc
