"""Triage safety-rule tests for POST /triage/ (app/api/routes/triage.py)
and its engine seam (app/services/triage/{port,fallback,adapter,factory}.py).

WHY THIS FILE EXISTS / WHY IT LOOKS DIFFERENT FROM THIS REPO'S OTHER
TEST FILES: the triage rules are the ones where a bug harms a patient
rather than annoying a user -- disposition/insufficient-data logic is
tested explicitly here, not assumed. This file REPLACES a prior
sync-TestClient version of itself (5 tests, same file path) with the
seven cases specified for this step, using pytest-asyncio +
httpx.AsyncClient per that spec, rather than this repo's existing
`client` (starlette TestClient) fixture.

REUSED, UNCHANGED, from tests/conftest.py / tests/_fixtures.py: `db`,
`org_units`, `org_units_b`, `make_actor`, `root_superuser` (via
make_actor), `auth_header`. Those are plain pytest fixtures/functions,
sync or not, and work identically regardless of whether the test that
consumes them is `def` or `async def` -- only the HTTP client itself
needs to be async to use httpx.AsyncClient. This repo's own `client`
fixture (conftest.py) is a synchronous starlette TestClient; there is
no pre-existing async-client fixture anywhere in this repo (grepped:
no hits for AsyncClient/pytest_asyncio/ASGITransport/pytest.mark.asyncio
before this file), so `async_client` below is defined locally in this
file rather than added to the shared conftest.py -- conftest.py is
shared with Aditya/Iqra's other test files and this task's own scope is
one file, not a shared-fixture change.

============================================================
DEPENDENCY GAP -- READ BEFORE RUNNING (see also this task's own report)
============================================================
`pytest-asyncio` is NOT listed in backend/requirements.txt (checked:
only `pytest==8.3.4` and `httpx==0.28.1` are present; no
pytest-asyncio, no explicit anyio pytest-plugin usage anywhere in this
repo). httpx.AsyncClient/ASGITransport themselves ARE available (httpx
is pinned and includes both). Without pytest-asyncio installed AND
registered, every `async def test_...` below marked
`@pytest.mark.asyncio` will either error at collection (unknown marker,
if strict-markers is ever enabled) or -- more likely with pytest 8's
default behaviour -- emit "coroutine was never awaited" / a
PytestUnraisableExceptionWarning and be reported as an error, not a
real pass. This file does not silently work around that: it uses
pytest-asyncio exactly as this task specified, and the report
accompanying this file says plainly whether it could be executed and,
if not, exactly what is missing (`pip install pytest-asyncio` into
backend/.venv, with `@pytest.mark.asyncio` already relying on strict
mode's default -- no pytest.ini change needed for that marker to work
once the plugin is installed). No production or test dependency was
installed by this step without being asked first.
"""
from __future__ import annotations

import logging
import sys
import uuid

import httpx
import pytest
from sqlmodel import text as sqltext

from app.main import app
from app.services.triage import factory as triage_factory
from tests._fixtures import auth_header

try:
    import pytest_asyncio
    _HAVE_PYTEST_ASYNCIO = True
except ImportError:  # pragma: no cover -- see module docstring's dependency-gap note
    pytest_asyncio = None
    _HAVE_PYTEST_ASYNCIO = False

_DISPOSITIONS = {"MANAGE_HERE", "TELECONSULT", "REFER", "EMERGENCY"}


# ============================================================
# async_client -- this repo's `client` fixture (conftest.py) is a
# synchronous starlette TestClient; there is no async equivalent in
# this repo yet, so it is defined here, scoped to this file only.
# ============================================================

if _HAVE_PYTEST_ASYNCIO:
    @pytest_asyncio.fixture
    async def async_client():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
else:  # pragma: no cover -- collection-time fallback so the file still imports; see dependency-gap note
    @pytest.fixture
    def async_client():
        pytest.skip("pytest-asyncio is not installed in this environment -- see module docstring.")


async def _make_patient(async_client: httpx.AsyncClient, token: str, age: int = 28) -> str:
    r = await async_client.post("/patients/", headers=auth_header(token), json={
        "name": "Test Patient", "age": age, "village": "V",
        "phone": f"+9192220{uuid.uuid4().int % 100000:05d}",
        "facility_id": str(uuid.uuid4()),
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ============================================================
# TT1 -- real HTTP POST /triage/ returns a computed disposition, one of
# the four permitted values, on a real (non-mocked) request.
# ============================================================

@pytest.mark.asyncio
async def test_tt1_real_request_returns_computed_disposition_in_permitted_set(
    async_client, org_units, make_actor,
):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note", "protocol": "GENERAL",
    })
    assert r.status_code == 200, r.text
    disposition = r.json()["decision"]["disposition"]
    assert disposition in _DISPOSITIONS, f"disposition {disposition!r} not in permitted set {_DISPOSITIONS}"


# ============================================================
# TT2 -- caller-supplied disposition is ignored, in both the response
# AND the persisted row.
# ============================================================

@pytest.mark.asyncio
async def test_tt2_caller_supplied_disposition_is_ignored_in_response_and_db(
    async_client, db, org_units, make_actor,
):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "caller's own note", "referral_urgency": "routine",
        "protocol": "ANC",
        "vitals": {"bp_systolic": 156, "bp_diastolic": 98},
        "disposition": "MANAGE_HERE",  # caller-supplied, must be ignored
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"]["disposition"] == "REFER"
    assert body["decision"]["disposition"] != "MANAGE_HERE"

    row = db.exec(
        sqltext("SELECT disposition FROM triageencounter WHERE id = :id"),
        params={"id": body["id"]},
    ).first()
    assert row is not None
    assert row[0] == "REFER", f"persisted row disposition was {row[0]!r}, expected REFER"


# ============================================================
# TT3 -- emergency vitals -> EMERGENCY / IMMEDIATE. Three sub-cases, one
# test function each (this repo's own test-file style prefers one
# scenario per test function -- see tests/test_existing_endpoints.py).
# ============================================================

@pytest.mark.asyncio
async def test_tt3a_anc_severe_hypertension_is_emergency_immediate(
    async_client, org_units, make_actor,
):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note", "protocol": "ANC",
        "vitals": {"bp_systolic": 170, "bp_diastolic": 115},
    })
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert decision["disposition"] == "EMERGENCY"
    assert decision["urgency"] == "IMMEDIATE"


@pytest.mark.asyncio
async def test_tt3b_anc_convulsions_danger_sign_is_emergency_immediate(
    async_client, org_units, make_actor,
):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note", "protocol": "ANC",
        "danger_signs": ["convulsions"],
    })
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert decision["disposition"] == "EMERGENCY"
    assert decision["urgency"] == "IMMEDIATE"


@pytest.mark.asyncio
async def test_tt3c_low_spo2_is_emergency_immediate_on_any_protocol(
    async_client, org_units, make_actor,
):
    """The universal emergency rule (fallback.py's _universal_emergency)
    fires before any protocol-specific handler, on ANY protocol --
    demonstrated here with GENERAL, a protocol whose own handler
    (_default_protocol) has no opinion about spo2 at all."""
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note", "protocol": "GENERAL",
        "vitals": {"spo2": 88},
    })
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert decision["disposition"] == "EMERGENCY"
    assert decision["urgency"] == "IMMEDIATE"


# ============================================================
# TT4 -- missing required vitals -> REFER + insufficient_data, never a
# crash, never a silent MANAGE_HERE.
# ============================================================

@pytest.mark.asyncio
async def test_tt4_anc_missing_vitals_refers_with_insufficient_data(
    async_client, org_units, make_actor,
):
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "note", "protocol": "ANC",
        "vitals": {},
    })
    assert r.status_code == 200, r.text  # never silent, never a crash
    decision = r.json()["decision"]
    assert decision["disposition"] == "REFER"
    assert decision["insufficient_data"] is True
    assert "bp_systolic" in decision["missing_fields"]
    assert decision["disposition"] != "MANAGE_HERE"  # the point of this test


# ============================================================
# TT5 -- no breaking change: every key present in a pre-Day-2-shaped
# response is still present. Only additions allowed.
# ============================================================

# Exact response key set documented for POST /triage/ before the
# triage-decisioning step (backend/docs/API_CONTRACT.md's own pre-Day-2
# example, and this repo's original Aditya-authored fields) -- the
# `decision` object is the only addition made by this step.
_PRE_DAY2_RESPONSE_KEYS = {
    "id", "patient_id", "facility_id", "triage_disposition",
    "referral_urgency", "created_at", "created_by_user_id", "org_unit_id",
}


@pytest.mark.asyncio
async def test_tt5_pre_day2_shaped_request_response_keeps_all_original_keys(
    async_client, org_units, make_actor,
):
    """Exact request shape test_existing_endpoints.py's own
    test_triage_and_referral_and_status_update_flow sends -- no
    protocol/vitals at all."""
    _, token = make_actor("BMO", org_units["BLOCK"])
    patient_id = await _make_patient(async_client, token)

    r = await async_client.post("/triage/", headers=auth_header(token), json={
        "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
        "triage_disposition": "Manage here", "referral_urgency": "routine",
    })
    assert r.status_code == 200, r.text
    body_keys = set(r.json().keys())
    missing = _PRE_DAY2_RESPONSE_KEYS - body_keys
    assert not missing, f"pre-Day-2 response key(s) missing -- breaking change: {missing}"
    added = body_keys - _PRE_DAY2_RESPONSE_KEYS
    assert added == {"decision"}, f"expected only 'decision' added, got: {added}"


# ============================================================
# TT6 -- TRIAGE_ENGINE=rule with SD's module absent.
#
# HONESTY NOTE (see also module docstring / this task's own report):
# the spec says "-> startup FAILS". As of this step, app/main.py has no
# startup/lifespan hook at all (checked -- grepped for @app.on_event and
# `lifespan=`: no hits), and app/services/triage/factory.py's own
# docstring is explicit that readiness is probed lazily, the FIRST time
# get_triage_engine() is called -- which happens per-request, inside
# app/api/routes/triage.py's create_triage(), not at app startup. This
# test does NOT add a startup hook to make the literal wording true (that
# would be a production-code change made unilaterally, against this
# task's own instruction). Instead it tests the behaviour as it actually
# exists: TRIAGE_ENGINE=rule + an absent rule-engine module fails closed
# (a) at the factory level (get_triage_engine() itself raises
# TriageEngineNotReady) and (b) at the route level (every request gets a
# 503 TRIAGE_ENGINE_UNAVAILABLE, not a 200 with a silently-wrong
# decision, and not an unhandled crash). A real "fails at process
# startup" test would need a FastAPI lifespan/startup event that calls
# get_triage_engine() eagerly and lets TriageEngineNotReady propagate --
# that hook does not exist today; commissioning it is a separate,
# reviewable step, not something this test file should add on its own.
# ============================================================

def test_tt6_forced_rule_engine_absent_module_fails_closed_at_factory_level(monkeypatch):
    # Force "module absent" deterministically via sys.modules, regardless
    # of whether app/services/triage/rules.py happens to exist in this
    # checkout right now (it does not, as of this step -- confirmed:
    # no such file in app/services/triage/).
    monkeypatch.setitem(sys.modules, "app.services.triage.rules", None)
    monkeypatch.setenv("TRIAGE_ENGINE", "rule")
    triage_factory._cached_readiness.cache_clear()
    try:
        with pytest.raises(triage_factory.TriageEngineNotReady):
            triage_factory.get_triage_engine()
    finally:
        triage_factory._cached_readiness.cache_clear()


@pytest.mark.asyncio
async def test_tt6_forced_rule_engine_absent_module_returns_503_not_crash_or_silent_200(
    async_client, org_units, make_actor, monkeypatch,
):
    monkeypatch.setitem(sys.modules, "app.services.triage.rules", None)
    monkeypatch.setenv("TRIAGE_ENGINE", "rule")
    triage_factory._cached_readiness.cache_clear()
    try:
        _, token = make_actor("BMO", org_units["BLOCK"])
        patient_id = await _make_patient(async_client, token)

        r = await async_client.post("/triage/", headers=auth_header(token), json={
            "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
            "triage_disposition": "note",
        })
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "TRIAGE_ENGINE_UNAVAILABLE"
    finally:
        triage_factory._cached_readiness.cache_clear()


# ============================================================
# TT7 -- TRIAGE_ENGINE=auto with SD's module absent -> fallback runs.
#
# HONESTY NOTE (see also module docstring / this task's own report):
# the spec asserts "an audit row exists with action TRIAGE_FALLBACK_USED".
# As of this step, app/api/routes/triage.py's create_triage() writes
# exactly ONE audit row per request, always action="TRIAGE_EVALUATED",
# with `engine` recorded inside that row's own `metadata` JSONB
# (metadata={"engine": ..., "protocol_version": ..., "disposition": ...,
# "insufficient_data": ...} -- see _write_audit's call site). There is no
# separate TRIAGE_FALLBACK_USED action/row anywhere in this codebase
# today (grepped app/api/routes/triage.py and app/core/audit.py -- no
# hits). This test asserts what is actually true today: one
# TRIAGE_EVALUATED row whose metadata.engine == "fallback". Adding a
# genuinely separate TRIAGE_FALLBACK_USED action would need a second
# _write_audit(...) call (or a conditional action name) inside
# create_triage's own STEP 7 -- a route change, out of scope for this
# test-only step and not made here.
# ============================================================

@pytest.mark.asyncio
async def test_tt7_auto_mode_falls_back_and_logs_and_audits_when_rule_engine_absent(
    async_client, db, org_units, make_actor, monkeypatch, caplog,
):
    monkeypatch.setitem(sys.modules, "app.services.triage.rules", None)
    monkeypatch.setenv("TRIAGE_ENGINE", "auto")
    triage_factory._cached_readiness.cache_clear()
    try:
        _, token = make_actor("BMO", org_units["BLOCK"])
        patient_id = await _make_patient(async_client, token)

        with caplog.at_level(logging.WARNING, logger="app.services.triage.factory"):
            r = await async_client.post("/triage/", headers=auth_header(token), json={
                "patient_id": patient_id, "facility_id": str(uuid.uuid4()),
                "triage_disposition": "note", "protocol": "GENERAL",
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"]["engine"] == "fallback"

        warning_records = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
        assert any("fallback" in rec.getMessage().lower() for rec in warning_records), (
            f"expected a WARNING log line about falling back to the deterministic "
            f"engine; got: {[rec.getMessage() for rec in warning_records]}"
        )

        row = db.exec(sqltext(
            "SELECT action, metadata FROM audit_log WHERE target_type = 'TRIAGE' "
            "AND target_id = :tid ORDER BY id DESC LIMIT 1"
        ), params={"tid": body["id"]}).first()
        assert row is not None, "expected an audit_log row for this triage encounter"
        action, metadata = row
        # See this test's own HONESTY NOTE above: action is TRIAGE_EVALUATED,
        # not a separate TRIAGE_FALLBACK_USED (which does not exist today).
        assert action == "TRIAGE_EVALUATED"
        if not isinstance(metadata, dict):
            import json as _json
            metadata = _json.loads(metadata)
        assert metadata.get("engine") == "fallback"
    finally:
        triage_factory._cached_readiness.cache_clear()
