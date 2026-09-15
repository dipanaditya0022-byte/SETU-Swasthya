"""Guard: no real patient data can be in the demo database (Day-3
demo-prep task).

WHY THIS IS NOT OPTIONAL: a public demo backend is not permission to use
real patient data. Under the DPDP Act, the moment a real person's health
data enters the demo backend it becomes a data fiduciary with every
obligation that follows. This is the cheapest possible insurance against
someone testing with their own family's details.

============================================================
RUNS AGAINST THE REAL DEMO DATABASE, NOT THE PYTEST TEST DATABASE
============================================================
Every other test file in this repo points at `TEST_DATABASE_URL` (a
throwaway DB, TRUNCATEd per test by conftest.py's own `_reset_db`
fixture). This file is the opposite on purpose: its entire job is to
guard the REAL demo/dev database's actual content, so it connects
directly to `DATABASE_URL` (falling back to this repo's own documented
local-dev default if unset), completely bypassing conftest.py's
test-DB machinery and its `_test_database`/`_reset_db` fixtures (this
file does not use the `db` fixture from conftest.py at all, deliberately
-- import that fixture here and you're back to guarding the wrong
database). Run this file ON PURPOSE, pointed at wherever the demo is
about to go live, as the last CI/pre-flight gate before a public
smoke test -- not as part of the routine `pytest tests/ -q` run.
============================================================

Three checks, each failing LOUDLY with the offending row's id:
  1. Every `patient` mobile starts with the seed prefix +9190000000.
     `Patient.phone` is a PLAIN, unencrypted column (confirmed directly
     against app/models/patient.py before writing this -- no
     blind_index/decrypt needed for this table, unlike `users.
     mobile_encrypted`).
  2. No `patient.name` matches a small, obviously-illustrative denylist
     of genuinely well-known public figures' names kept in this file's
     own fixture below -- never anyone's actual private data.
  3. No ABHA number is present anywhere that is not in the seeded set.
     GAP FOUND, STATED PLAINLY: `patient` has NO abha column at all
     (confirmed against app/models/patient.py) -- ABHA only exists on
     `users.abha_number_encrypted`, populated only via the real
     self-registration path (`POST /auth/patient/register`'s own
     `abha_number`/`abha_address` fields, app/api/routes/auth.py). This
     seed dataset (backend/scripts/seed_demo.py) does not populate ANY
     ABHA number for ANY seeded user -- the seeded set is the EMPTY
     set. So this check is, correctly and not by omission: assert NO
     `users.abha_number_encrypted` is non-null at all. If a future demo
     seed ever legitimately adds a fake ABHA number, this test's own
     `SEEDED_ABHA_ENCRYPTED_VALUES` set below is the one place to widen
     it -- do not just delete the assertion.
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# REAL BUG FOUND LIVE, fixed here -- tests/conftest.py's own module-level
# code unconditionally does `os.environ["DATABASE_URL"] = TEST_DATABASE_URL`
# (it must run before app.* is ever imported, for every OTHER test file's
# own good reasons) -- and pytest loads conftest.py for ANY test file in
# this directory, even a single-file, isolated `pytest tests/
# test_no_real_data.py` invocation. Without `override=True` here,
# python-dotenv's own default ("don't clobber an already-set env var")
# means this file would silently read conftest's TEST database URL
# instead of the real demo DATABASE_URL from .env -- confirmed live: an
# injected real-name violation row in the actual demo DB was NOT caught
# until this fix, because the guard was querying the wrong, empty
# database the whole time and finding nothing. `override=True` forces
# THIS file's own later `.env` read to win.
load_dotenv(override=True)

# The seed prefix every backend/scripts/seed_demo.py PATIENT row's
# mobile must start with -- the exact detection mechanism this whole
# guard relies on. Keep in sync with that script's own module docstring
# if it's ever changed.
SEED_PATIENT_MOBILE_PREFIX = "+9190000000"

# A small, DELIBERATELY obvious set of genuinely well-known public
# figures' names -- not anyone's private data, safe to keep in a
# checked-in test file read by humans. If a seeded/real patient name
# ever matches one of these (exactly, case-insensitive), something has
# gone wrong -- either real data landed in the demo DB, or someone
# picked a joke name that happens to collide with a public figure's.
REAL_NAME_DENYLIST = {
    "narendra modi",
    "mahatma gandhi",
    "amitabh bachchan",
    "sachin tendulkar",
    "indira gandhi",
}

# See module docstring point 3 -- the demo seed writes NO abha numbers
# at all, so the seeded set is empty. Widen this (with real encrypted
# values, not plaintext) if a future seed ever legitimately adds one.
SEEDED_ABHA_ENCRYPTED_VALUES: set[bytes] = set()


def _demo_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://setu_dev:setu_dev_pw@localhost:5432/setu_swasthya",
    )


@pytest.fixture(scope="module")
def demo_engine():
    return create_engine(_demo_database_url())


def test_every_patient_mobile_has_the_seed_prefix(demo_engine):
    with demo_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, phone FROM patient WHERE phone IS NULL OR phone NOT LIKE :prefix"
        ), {"prefix": SEED_PATIENT_MOBILE_PREFIX + "%"}).all()

    offenders = [(str(r[0]), r[1]) for r in rows]
    assert not offenders, (
        f"REAL-DATA GUARD FAILED: {len(offenders)} patient row(s) with a mobile number that does "
        f"NOT start with the seed prefix {SEED_PATIENT_MOBILE_PREFIX!r} (or is NULL). "
        f"Offending rows (id, phone): {offenders}"
    )


def test_no_patient_name_matches_the_real_name_denylist(demo_engine):
    with demo_engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name FROM patient")).all()

    offenders = [(str(r[0]), r[1]) for r in rows if r[1] and r[1].strip().lower() in REAL_NAME_DENYLIST]
    assert not offenders, (
        f"REAL-DATA GUARD FAILED: {len(offenders)} patient row(s) whose name matches the "
        f"real-name denylist. Offending rows (id, name): {offenders}"
    )


def test_no_unseeded_abha_number_present(demo_engine):
    """See this module's own docstring point 3 for the real schema
    finding this check is built around: ABHA lives on `users.
    abha_number_encrypted`, not `patient` (which has no ABHA column at
    all), and the demo seed populates none -- so the seeded set is
    empty and ANY non-null value here is, by definition, unseeded."""
    with demo_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, abha_number_encrypted FROM users WHERE abha_number_encrypted IS NOT NULL"
        )).all()

    offenders = [
        (str(r[0]))
        for r in rows
        if bytes(r[1]) not in SEEDED_ABHA_ENCRYPTED_VALUES
    ]
    assert not offenders, (
        f"REAL-DATA GUARD FAILED: {len(offenders)} users row(s) carry an ABHA number not in the "
        f"seeded set (which is empty by design -- see this module's own docstring). "
        f"Offending row ids: {offenders}"
    )
