# ml/

Top-level, sibling to `backend/` -- the consolidated home for this
repo's ML/rule-engine work, integrated from two previously separate
branches (`devansh-ml`, `sd-triage-automation`) onto one `ml` branch, per
the explicit decision to keep `ml/` and `backend/` modular rather than
nesting one inside the other.

## What's here, and why it's split this way

This folder holds two genuinely different things that happened to both
be called "ML" work on their source branches:

- **`data/`, `models/`, `scripts/`, `src/`, `test_setup.py`** -- from
  `devansh-ml`. A real, standalone data-science pipeline: synthetic
  patient data (`data/synthetic_patients.csv`), a trained risk model
  (`models/risk_model.joblib`), and the scripts that generate/train/test
  it (`scripts/generate_synthetic_data.py`, `src/train_risk_model.py`,
  `src/check_data.py`, `src/test_prediction.py`). Confirmed at
  integration time: none of these import anything from `backend/app/` --
  they're pandas/scikit-learn/joblib only, run standalone, not wired
  into the live API. Its own dependencies live in `ml/requirements.txt`,
  separate from `backend/requirements.txt` -- the API server does not
  need pandas/sklearn installed, and shouldn't.

- **`triage/rules.py`, `escalation/rules.py`** -- from
  `sd-triage-automation`. The real, deterministic triage/escalation
  *rule engine* -- pure Python (stdlib only: `typing`, `datetime`; no
  DB session, no HTTP client, no filesystem access -- this is enforced,
  not just described, by each factory's own R5 purity check). This is
  the module `backend/app/services/triage/factory.py` and
  `backend/app/services/escalation/factory.py` have always been designed
  to probe for at import time -- it was simply absent all along, which
  is why every triage/escalation decision defaulted to the deterministic
  fallback engine before this integration. It moved here (rather than
  staying at its original `backend/app/services/{triage,escalation}/
  rules.py` path) specifically to honor "one ml folder, modular from
  backend" -- see the two `factory.py`/`adapter.py` files in
  `backend/app/services/` for exactly how the import now crosses that
  boundary, and `backend/docker-compose.yml`'s `PYTHONPATH`/volume
  wiring for how `import ml...` resolves at runtime.

`backend/app/services/demo_data.py` and
`backend/app/jobs/due_list_reminders.py` (also from
`sd-triage-automation`) deliberately stayed in `backend/` -- they're
API-layer/ops service code (demo dataset generation, a scheduled
reminders job), not rule-engine logic, even though
`due_list_reminders.py` itself *consumes*
`ml.escalation.rules.escalation_for` the same way the adapter does.

## Running ml/'s own tests

`ml/tests/test_triage_rules.py` and `ml/tests/test_escalation_rules.py`
are pure unit tests of `rules.py` plus their `backend/`-side
adapter/factory (RuleEngineAdapter, RuleEscalationEngineAdapter,
`_probe_readiness`) -- no database, no app startup. Run from the repo
root:

```bash
python -m pytest ml/tests/
```

`ml/tests/conftest.py` puts `backend/` on `sys.path` so the
`app.services.*` imports inside these test files resolve regardless of
invocation directory; see that file's own docstring for why this is
needed (`ml/tests/` and `backend/app/` are siblings, not nested).

## Importing ml/ from the live API

Both `factory.py`s use a plain `from ml.triage import rules` / `from
ml.escalation import rules` -- a dotted import, meaning whatever process
imports `app.services.triage.factory` (or `.escalation.factory`) needs
the repo root (or wherever `ml/` actually sits) on `PYTHONPATH`. Inside
Docker this is handled by `backend/docker-compose.yml` (a `../ml:/ml`
bind mount plus `PYTHONPATH: /` on the `api` service). Outside Docker
(e.g. running `uvicorn` directly from `backend/` on a host), set
`PYTHONPATH` to include the repo root's parent of `ml/` yourself --
this repo's documented, supported way to run the stack is via
`docker compose` (see `backend/DEMO_RUNBOOK.md`), which already carries
this wiring.
