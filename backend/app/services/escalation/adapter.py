"""RuleEscalationEngineAdapter -- wraps SD's escalation_for() rule engine
behind the EscalationEngine Protocol (app/services/escalation/port.py), so
that a future route and app/services/escalation/factory.py never import
SD's module directly. That indirection is the whole point: SD's module may
not exist yet, or may exist but not be ready, and a blocked integration
owner must not be able to block GET /referrals/exceptions.

MODULE PATH: grepped this repository (and backend/docs/) repo-wide for
`escalation_for` -- no hits anywhere, including Day2.md. Unlike
app/services/triage/adapter.py, which had Day2.md SS2.1's own explicit R1
readiness-check command to pin the exact import path, nothing in this
repository currently pins where SD's escalation engine will live. Per this
step's own instruction, this adapter therefore ASSUMES the path by direct
analogy with the triage adapter's own precedent:

    app.services.escalation.rules, module name `rules` (not `rule_engine`
    or `engine`), exposing a single function `escalation_for(payload:
    dict) -> dict`.

This is a documented assumption, not a confirmed fact -- if SD's actual
module differs (different path, different function name, different
argument shape), THIS file is what needs updating, not port.py's Protocol
and not the factory's readiness probe, both of which are shape-agnostic,
exactly per the triage adapter's own precedent.

The function is called with a single `dict` argument
(`EscalationInput.model_dump()`) and is expected to return a `dict`
carrying, at minimum, the two fields this adapter can validate without
guessing at SD's own semantics: `stage` and `message`. `escalate_to_role`,
`escalate_to_user_id`, `due_action_at`, and `engine` are all optional on
the way in (EscalationOutput itself defaults `escalate_to_role`,
`escalate_to_user_id`, and `due_action_at` to None, and `engine` to
"rule") -- this adapter overrides any caller-supplied `engine` value to
`self.name` ("rule") after validation, exactly the way this file, not
SD's module, is responsible for knowing which engine actually produced a
result.

The import of app.services.escalation.rules happens ONLY inside
escalate() below, never at module import time: importing this adapter
module (or the factory, which imports this module) must never fail just
because SD's module doesn't exist yet.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.services.escalation.port import (
    EscalationEngineError,
    EscalationInput,
    EscalationOutput,
)

_REQUIRED_FIELDS = ("stage", "message")
_VALID_STAGES = (0, 1, 2, 3)
_VALID_ROLES = ("ASHA", "CHO", "BMO", None)


class RuleEscalationEngineAdapter:
    """Adapts SD's escalation_for() to the EscalationEngine Protocol."""

    name = "rule"

    def escalate(self, data: EscalationInput) -> EscalationOutput:
        try:
            from app.services.escalation.rules import escalation_for
        except Exception as exc:  # noqa: BLE001 -- module absent/broken is expected until SD ships it
            raise EscalationEngineError(
                f"Escalation rule engine module "
                f"(app.services.escalation.rules) is not importable: {exc}"
            ) from exc

        payload: dict[str, Any] = data.model_dump()

        try:
            raw: Any = escalation_for(payload)
        except Exception as exc:  # noqa: BLE001 -- any failure inside SD's code is a readiness failure, not ours
            raise EscalationEngineError(
                f"Escalation rule engine raised during escalation_for(): {exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise EscalationEngineError(
                f"Escalation rule engine returned {type(raw).__name__}, expected a dict."
            )

        missing = [field for field in _REQUIRED_FIELDS if field not in raw]
        if missing:
            raise EscalationEngineError(
                f"Escalation rule engine response is missing field(s): {missing}"
            )

        if raw["stage"] not in _VALID_STAGES:
            raise EscalationEngineError(
                f"Escalation rule engine returned an out-of-range stage: {raw['stage']!r}"
            )
        if raw.get("escalate_to_role") not in _VALID_ROLES:
            raise EscalationEngineError(
                f"Escalation rule engine returned an out-of-range "
                f"escalate_to_role: {raw.get('escalate_to_role')!r}"
            )

        raw = {**raw, "engine": self.name}

        try:
            return EscalationOutput(**raw)
        except ValidationError as exc:
            raise EscalationEngineError(
                f"Escalation rule engine response failed validation: {exc}"
            ) from exc
