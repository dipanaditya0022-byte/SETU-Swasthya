"""get_escalation_engine() -- selects between RuleEscalationEngineAdapter
(SD's escalation_for(), wrapped) and FallbackEscalationEngine, based on the
ESCALATION_ENGINE environment variable. No route imports this yet -- wiring
GET /referrals/exceptions to call get_escalation_engine() is a later step;
this module only has to exist and work correctly on its own. Mirrors
app/services/triage/factory.py's own structure exactly.

Settings pattern: same as the triage factory -- this repo has no
app/core/config.py / Settings class (checked, same grep as
app/services/triage/factory.py's own docstring). ESCALATION_ENGINE follows
the same os.environ.get(...) convention every other config read in this
codebase uses.

Readiness (R1-R6, see _probe_readiness) is probed ONCE per process and
cached via functools.lru_cache -- never per request, same as the triage
factory -- so an import failure or a slow/broken rule engine costs nothing
beyond the first check.
"""
from __future__ import annotations

import inspect
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import uuid4

from app.services.escalation.adapter import RuleEscalationEngineAdapter
from app.services.escalation.fallback import FallbackEscalationEngine
from app.services.escalation.port import (
    EscalationEngine,
    EscalationEngineError,
    EscalationInput,
)

logger = logging.getLogger(__name__)

# R5's own forbidden tokens: a "pure" rule engine module must not touch a
# DB session, an HTTP client, or the filesystem. Same list as the triage
# factory's own R5.
_UNSAFE_SOURCE_TOKENS = ("session", "httpx", "requests", "open(")

_VALID_MODES = ("auto", "rule", "fallback")
_VALID_STAGES = (0, 1, 2, 3)
_VALID_ROLES = ("ASHA", "CHO", "BMO", None)


class EscalationEngineNotReady(Exception):
    """Raised when ESCALATION_ENGINE=rule forces the rule engine but it
    fails readiness -- this must happen at startup (i.e. the first time
    get_escalation_engine() is called), not silently fall back. Mirrors
    TriageEngineNotReady (app/services/triage/factory.py)."""


def _probe_readiness() -> tuple[bool, str | None]:
    """Runs R1-R6 against the escalation rule engine, in order, stopping at
    the first failure. Returns (ready, failure_reason); failure_reason is
    None iff ready is True. Mirrors app/services/triage/factory.py's own
    _probe_readiness structure and R-numbering."""
    # R1 -- module imports cleanly, at the path this adapter itself
    # documents as an assumption (see adapter.py's own docstring: no
    # pinned spec for this path exists anywhere in this repo, unlike
    # triage's Day2.md SS2.1).
    try:
        from app.services.escalation import rules as _rule_engine_module
    except Exception as exc:  # noqa: BLE001 -- absence/breakage is the exact thing being probed for
        return False, f"R1 (module import) failed: {exc}"

    # R5 -- pure: no session/httpx/requests/open( anywhere in the module's
    # own source. Checked via static source inspection, before ever
    # invoking it.
    try:
        source = inspect.getsource(_rule_engine_module)
    except (OSError, TypeError) as exc:
        return False, f"R5 (source inspection) failed: {exc}"
    lowered = source.lower()
    for token in _UNSAFE_SOURCE_TOKENS:
        if token in lowered:
            return False, f"R5 (purity) failed: forbidden token {token!r} found in module source"

    # R2/R3/R4/R6 -- invoke the adapter with a minimal, harmless sample
    # input and validate the shape of what comes back. RuleEscalationEngineAdapter
    # itself already enforces "both required fields present" and
    # "stage/escalate_to_role in range" (raising EscalationEngineError
    # otherwise), which covers R2/R3/R4 in one call.
    adapter = RuleEscalationEngineAdapter()
    now = datetime.now(timezone.utc)
    sample = EscalationInput(
        urgency="ROUTINE",
        initiated_at=now - timedelta(days=1),
        due_at=now - timedelta(hours=1),
        now=now,
        current_stage=0,
        owner_user_id=uuid4(),
        status="INITIATED",
    )
    try:
        result = adapter.escalate(sample)
    except EscalationEngineError as exc:
        return False, f"R2/R3/R4 (callable/shape/stage) failed: {exc}"
    except Exception as exc:  # noqa: BLE001 -- any other exception also means "not ready"
        return False, f"R2 (callable with EscalationInput) failed: {exc}"

    if result.stage not in _VALID_STAGES:
        return False, f"R4 (stage range) failed: {result.stage!r}"
    if result.escalate_to_role not in _VALID_ROLES:
        return False, f"R4 (escalate_to_role range) failed: {result.escalate_to_role!r}"
    if not isinstance(result.message, str) or not result.message:
        return False, "R6 (message non-empty string) failed"

    return True, None


@lru_cache(maxsize=1)
def _cached_readiness() -> tuple[bool, str | None]:
    return _probe_readiness()


def get_escalation_engine() -> EscalationEngine:
    """Selects and returns the engine to use, per ESCALATION_ENGINE:

      auto     (default) probe readiness; use rule if ready, else fallback
      rule     force rule; raises EscalationEngineNotReady if not ready
      fallback force fallback, no readiness probe run at all
    """
    mode = os.environ.get("ESCALATION_ENGINE", "auto").strip().lower()

    if mode not in _VALID_MODES:
        raise ValueError(
            f"Unknown ESCALATION_ENGINE value: {mode!r}. Expected one of: "
            f"{', '.join(_VALID_MODES)}."
        )

    if mode == "fallback":
        return FallbackEscalationEngine()

    if mode == "rule":
        ready, reason = _cached_readiness()
        if not ready:
            raise EscalationEngineNotReady(
                f"ESCALATION_ENGINE=rule was forced but the rule engine is "
                f"not ready: {reason}"
            )
        return RuleEscalationEngineAdapter()

    # mode == "auto"
    ready, reason = _cached_readiness()
    if ready:
        return RuleEscalationEngineAdapter()
    logger.warning(
        "Escalation engine: falling back to the deterministic fallback "
        "engine (rule engine not ready -- %s)", reason,
    )
    return FallbackEscalationEngine()
