"""Shared pytest fixtures for the Day 1 test suite (S21).

Test database: a dedicated `setu_swasthya_test` database (never the dev
DB), created and migrated by this file, matching the throwaway-DB
pattern used for every manual testing session since S18. Overridable
via the TEST_DATABASE_URL env var for CI (see README section in the
S21 final response for the exact CI command).

DATABASE_URL is pointed at the test DB *before* any `app.*` module is
imported (app/db/database.py builds its `engine` from that env var at
import time) -- this is why the env var is set at the very top of this
file, ahead of every other import.

Isolation: rather than per-test transaction/savepoint rollback (which
would require overriding every route's own session lifecycle -- several
routes call session.commit() more than once per request, found and
relied on already in S20's own bug-fix), each test gets a full
TRUNCATE ... CASCADE of every app-mutable table before it runs. Slower
than a rollback-based approach but simple, correct, and exercises the
exact same commit pattern the app uses in production. Reference seed
data (roles, permissions, role_permissions, role_creation_grants) is
migrated once per session and never truncated.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://setu_dev:setu_dev_pw@localhost:5432/setu_swasthya_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text as satext
from sqlmodel import Session

from app.db.database import engine  # noqa: E402  -- must come after DATABASE_URL is set
from app.main import app  # noqa: E402

from tests._fixtures import (  # noqa: E402
    build_org_hierarchy,
    build_second_org_tree,
    make_active_actor,
    pick_target_org_unit,
    registration_body,
    token_for,
)

_MUTABLE_TABLES = [
    "approval_requests", "audit_log", "break_glass_sessions", "consents",
    "facility", "idempotency_keys", "login_attempts", "mfa_credentials",
    "org_units", "otp_codes", "password_history", "patient", "referral",
    "refresh_tokens", "triageencounter", "user_invitations", "users",
]


def _admin_url() -> str:
    # swap the test DB name for the always-present `postgres` maintenance
    # DB, needed to CREATE/DROP the test DB itself.
    prefix, _, _dbname = TEST_DATABASE_URL.rpartition("/")
    return prefix + "/postgres"


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Creates (or reuses) the test database and runs migrations once
    per test session."""
    dbname = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            satext("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
        ).first()
        if not exists:
            conn.execute(satext(f'CREATE DATABASE "{dbname}"'))
    admin_engine.dispose()

    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed for test DB:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    yield


@pytest.fixture(autouse=True)
def _reset_db():
    """Truncates every app-mutable table before each test -- see module
    docstring for why this (not per-test transaction rollback) was
    chosen."""
    with engine.begin() as conn:
        conn.execute(satext("TRUNCATE " + ", ".join(_MUTABLE_TABLES) + " CASCADE"))
    yield


@pytest.fixture
def db() -> Session:
    with Session(engine) as session:
        yield session


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def org_units(db: Session) -> dict:
    units = build_org_hierarchy(db)
    db.commit()
    return units


@pytest.fixture
def org_units_b(db: Session) -> dict:
    units = build_second_org_tree(db)
    db.commit()
    return units


@pytest.fixture
def root_superuser(db: Session) -> "uuid.UUID":
    """One SUPERUSER row per test, exempt from chk_creator_required,
    that every other fixture-created actor is attributed to (the FK is
    real, not just a NOT NULL check -- see _fixtures.make_active_actor's
    own docstring)."""
    import uuid
    from tests._fixtures import _next_mobile
    uid = make_active_actor(db, role="SUPERUSER", org_unit_id=None, mobile=_next_mobile())
    db.commit()
    return uid


@pytest.fixture
def make_actor(db: Session, root_superuser):
    """Factory fixture: make_actor(role, org_unit_id, mobile=None) ->
    (user_id, token). See _fixtures.make_active_actor/token_for."""
    def _make(role: str, org_unit_id, mobile: str | None = None):
        from tests._fixtures import _next_mobile
        creator = None if role in ("SUPERUSER", "PATIENT") else root_superuser
        uid = make_active_actor(db, role=role, org_unit_id=org_unit_id,
                                 mobile=mobile or _next_mobile(), created_by_user_id=creator)
        db.commit()
        return uid, token_for(uid, role)
    return _make


@pytest.fixture
def build_payload(db: Session):
    """Factory fixture: build_payload(target_role, actor_org_unit_id,
    allowed_types, units, second_approver_id=None) -> full POST /users
    body, with the target's own posting chosen to be reachable from the
    actor's scope."""
    def _build(target_role: str, actor_org_unit_id, allowed_types: list[str],
               units: dict, second_approver_id=None):
        target_org = pick_target_org_unit(db, units, actor_org_unit_id, allowed_types)
        return registration_body(target_role, target_org, second_approver_id=second_approver_id)
    return _build
