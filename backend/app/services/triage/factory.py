"""get_triage_engine() -- selects between RuleEngineAdapter (SD's rule
engine, wrapped) and FallbackTriageEngine, based on the TRIAGE_ENGINE
environment variable. No route imports this yet -- wiring a route to
call get_triage_engine() is a later step; this module only has to exist
and work correctly on its own.

Settings pattern: this repo has no app/core/config.py / Settings class
-- checked (grepped app/core and app/db for BaseSettings/
pydantic_settings: no hits). Every existing module that reads
configuration (app/core/tokens.py, app/db/database.py, app/core/
audit.py's callers) reads os.environ directly via os.environ.get(...).
TRIAGE_ENGINE follows that same convention here rather than introducing
a second settings mechanism this codebase doesn't otherwise have.

Readiness (R1-R6, see _probe_readiness) is probed ONCE per process and
cached via functools.lru_cache -- never per request, per this step's
own instruction -- so an import failure or a slow/broken rule engine
costs nothing beyond the first check.
"""
from __future__ import annotations

import inspect
import logging
import os
from functools import lru_cache
from typing import get_args

from app.services.triage.adapter import RuleEngineAdapter
from app.services.triage.fallback import FallbackTriageEngine
from app.services.triage.port import Disposition, TriageEngine, TriageEngineError, TriageInput

logger = logging.getLogger(__name__)

# R5's own forbidden tokens: a "pure" rule engine module must not touch
# a DB session, an HTTP client, or the filesystem.
_UNSAFE_SOURCE_TOKENS = ("session", "httpx", "requests", "open(")

_VALID_MODES = ("auto", "rule", "fallback")


class TriageEngineNotReady(Exception):
    """Raised when TRIAGE_ENGINE=rule forces the rule engine but it
    fails readiness -- per this step's own instruction, this must
    happen at startup (i.e. the first time get_triage_engine() is
    called), not silently fall back."""


def _probe_readiness() -> tuple[bool, str | None]:
    """Runs R1-R6 against the rule engine, in order, stopping at the
    first failure. Returns (ready, failure_reason); failure_reason is
    None iff ready is True."""
    # R1 -- module imports cleanly. Day2.md SS2.1's own check command is
    # `python -c "from app.services.triage.rules import evaluate_triage"`
    # -- module name `rules`, matching adapter.py's own import.
    try:
        from app.services.triage import rules as _rule_engine_module
    except Exception as exc:  # noqa: BLE001 -- absence/breakage is the exact thing being probed for
        return False, f"R1 (module import) failed: {exc}"

    # R5 -- pure: no session/httpx/requests/open( anywhere in the
    # module's own source. Checked via static source inspection, before
    # ever invoking it, so an impure module is rejected without being
    # run.
    try:
        source = inspect.getsource(_rule_engine_module)
    except (OSError, TypeError) as exc:
        return False, f"R5 (source inspection) failed: {exc}"
    lowered = source.lower()
    for token in _UNSAFE_SOURCE_TOKENS:
        if token in lowered:
            return False, f"R5 (purity) failed: forbidden token {token!r} found in module source"

    # R2/R3/R4/R6 -- invoke the adapter with a minimal, harmless sample
    # input and validate the shape of what comes back. RuleEngineAdapter
    # itself already enforces "all five required fields present" and
    # "disposition/urgency in range" (raising TriageEngineError
    # otherwise), which covers R2/R3/R4 in one call.
    adapter = RuleEngineAdapter()
    sample = TriageInput(protocol="GENERAL")
    try:
        result = adapter.evaluate(sample)
    except TriageEngineError as exc:
        return False, f"R2/R3/R4 (callable/shape/disposition) failed: {exc}"
    except Exception as exc:  # noqa: BLE001 -- any other exception also means "not ready"
        return False, f"R2 (callable with TriageInput) failed: {exc}"

    if result.disposition not in get_args(Disposition):
        return False, f"R4 (disposition range) failed: {result.disposition!r}"
    if not isinstance(result.protocol_version, str) or not result.protocol_version:
        return False, "R6 (protocol_version non-empty string) failed"

    return True, None


@lru_cache(maxsize=1)
def _cached_readiness() -> tuple[bool, str | None]:
    return _probe_readiness()


def get_triage_engine() -> TriageEngine:
    """Selects and returns the engine to use, per TRIAGE_ENGINE:

      auto     (default) probe readiness; use rule if ready, else fallback
      rule     force rule; raises TriageEngineNotReady if not ready
      fallback force fallback, no readiness probe run at all
    """
    mode = os.environ.get("TRIAGE_ENGINE", "auto").strip().lower()

    if mode not in _VALID_MODES:
        raise ValueError(
            f"Unknown TRIAGE_ENGINE value: {mode!r}. Expected one of: "
            f"{', '.join(_VALID_MODES)}."
        )

    if mode == "fallback":
        return FallbackTriageEngine()

    if mode == "rule":
        ready, reason = _cached_readiness()
        if not ready:
            raise TriageEngineNotReady(
                f"TRIAGE_ENGINE=rule was forced but the rule engine is not ready: {reason}"
            )
        return RuleEngineAdapter()

    # mode == "auto"
    ready, reason = _cached_readiness()
    if ready:
        return RuleEngineAdapter()
    logger.warning(
        "Triage engine: falling back to the deterministic fallback engine "
        "(rule engine not ready -- %s)", reason,
    )
    return FallbackTriageEngine()
