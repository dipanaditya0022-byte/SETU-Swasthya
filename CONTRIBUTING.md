# Contributing to SETU-Swasthya

SETU-Swasthya is a hybrid offline/online health platform under active MVP
development. This document covers the backend (FastAPI + PostgreSQL), which is
the part of the repo with an established workflow today; the same spirit
applies once the Flutter frontend and ML layer gain their own conventions.

## Ground rules (non-negotiable)

These come from the project's own build discipline (see `backend/docs/Day1.md`,
`Day2.md`, `Day3.md`) and apply to every change, not just backend work:

- **Additive only.** Endpoints already documented in
  `backend/docs/API_CONTRACT.md` must not be renamed or have their payload
  fields changed. Extend, don't break.
- **No real patient data, ever.** All patient/village/facility data in the MVP
  is synthetic. Never commit, log, or paste anything that could be real PHI.
- **No secrets in the repo.** No `.env` files, keys, tokens, or credentials.
  `secrets/` and `.env*` (except `.env.example`) are gitignored — keep it that
  way. If you generate local keys or a `.env`, they stay local.
- **Fail closed.** When a check is ambiguous or a dependency is unavailable,
  the safe default is to deny/reject, not to silently allow.
- **Never hide an environment error.** If something is broken (DB down,
  migration missing, engine unavailable), surface it — don't swallow it into a
  fake success.
- **No feature work during a stabilization freeze.** If the branch is in a
  Day-3-style freeze window (see `backend/docs/Day3.md`), only P0/P1 fixes
  land; everything else goes to the backlog.

## Getting set up

Follow the [Backend setup](README.md#-getting-started) section in the root
README — Docker is the recommended path and matches deployment. In short:

```bash
cd backend
cp .env.example .env      # fill in real local values; never commit this file
docker compose up --build
```

Migrations run automatically on container start. After changing a model:

```bash
docker compose exec api alembic revision --autogenerate -m "describe the change"
docker compose exec api alembic upgrade head
```

## Branching and commits

- Branch off the branch you were told to base work on (currently `backend`
  for backend work, `dev` more generally per the README) — never commit
  directly to `main`.
- Use a short, descriptive branch name: `feature/short-description`,
  `fix/short-description`.
- Keep changes scoped to the module/area you're touching to minimize merge
  conflicts and keep review focused.
- Write commits as `type(scope): description`, matching the existing history,
  e.g. `feat(backend): add referral breach detection`,
  `fix(backend): dynamic SUPERUSER lookup in demo seed script`. Common types:
  `feat`, `fix`, `test`, `docs`, `chore`, `refactor`.

## Before opening a pull request

- **Tests pass.** From `backend/`: `pytest` (or
  `docker compose exec api pytest` if running via Docker). Add or update
  tests for the behavior you changed — this codebase treats reference test
  suites (e.g. the triage TT1–TT7 cases, the validation matrix) as part of the
  contract, not optional coverage.
- **Migrations are included** for any model change, generated via
  `alembic revision --autogenerate` and verified with `alembic upgrade head`
  against a clean database.
- **No secrets, no generated artifacts.** Double-check `git status`/`git diff`
  before staging — watch for accidentally-added `.env`, key files, or archives
  that don't belong in version control.
- **API contract respected.** If you touched a documented endpoint, confirm
  `backend/docs/API_CONTRACT.md` still matches reality, and update it if you
  added new endpoints or fields.
- **Offline/sync behavior verified**, if relevant: the offline → reconnect →
  sync loop is the platform's most important behavior; changes to sync,
  triage, or referral logic should be exercised through that loop, not just
  unit tests in isolation.

## Code review expectations

- Only demonstration-ready, reviewed builds are merged toward `main`.
- A fix should be verified by re-running the exact request/scenario that
  failed, then the surrounding flow it sits in — not just a similar-looking
  test.
- Don't bundle unrelated cleanup or new features into a bug-fix PR; open a
  separate PR (or note it for the backlog) instead.

## Reporting issues

Use the project's issue tracker for bugs and feature requests. For backend
bugs found during a stabilization pass, note the severity (P0–P3, see
`backend/docs/Day3.md` §0.1) so triage priority is clear.
