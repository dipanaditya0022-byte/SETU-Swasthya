"""ml/tests/ own conftest.py -- makes `app.*` importable from here.

These tests (moved from backend/tests/ as part of the ml/ integration,
see ml/README.md) exercise ml/triage/rules.py and ml/escalation/rules.py
directly, but also import their consumers -- RuleEngineAdapter,
_probe_readiness, the TriageInput/TriageOutput port types -- which stay
in backend/app/services/*, deliberately not moved (they're API-layer
code, not rule-engine code; see ml/README.md's "what moved and why").

Running `pytest ml/tests/` from the repo root puts the repo root on
sys.path (pytest's own rootdir insertion, since ml/ and ml/tests/ both
carry __init__.py), which is enough for `import ml.triage.rules` etc.
but NOT enough for `import app.services...` -- that package lives at
backend/app/, one directory ml/tests/ does not sit under. This conftest
adds backend/ to sys.path explicitly, mirroring the same "explicit,
don't rely on cwd" convention backend/tests/test_no_real_data.py's own
conftest-adjacent setup already uses in this repo.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
