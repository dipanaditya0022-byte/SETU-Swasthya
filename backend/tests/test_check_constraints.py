"""Every users-table CHECK constraint from Day1.md SS13.2 (migration
c3a9f7d21e56, S6) -- one test per constraint, each attempting to
violate it directly via raw SQL and asserting the database itself
rejects the row (SS21's own Definition-of-Done: "All CHECK constraints
from SS13.2 exist and are verified by a test that attempts to violate
each"). Deliberately below the app layer (raw INSERT/UPDATE), since the
point is proving the DATABASE enforces these regardless of what the
application does -- SS13.2's own words: "Even if every layer of
application logic were bypassed, PostgreSQL itself refuses...".
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import text

from tests._fixtures import make_active_actor


def _bare_user_insert(db, **overrides):
    """Minimal valid users row, overridable per test."""
    defaults = {
        "role": "PATIENT", "role_level": 99, "full_name": "Constraint Test",
        "mobile_encrypted": b"\x00", "mobile_blind_index": f"bi-{uuid.uuid4().hex}",
        "mobile_masked": "+91XXXXX00000", "status": "ACTIVE",
        "scope_org_unit_id": None, "created_by_user_id": None,
        "mfa_required": False, "suspension_reason": None,
        "password_hash": None, "reports_to_user_id": None, "expires_at": None,
    }
    defaults.update(overrides)
    db.exec(text(
        "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
        "mobile_masked, status, scope_org_unit_id, created_by_user_id, mfa_required, "
        "suspension_reason, password_hash, reports_to_user_id, expires_at) "
        "VALUES (:role, :role_level, :full_name, :mobile_encrypted, :mobile_blind_index, "
        ":mobile_masked, :status, :scope_org_unit_id, :created_by_user_id, :mfa_required, "
        ":suspension_reason, :password_hash, :reports_to_user_id, :expires_at)"
    ), params=defaults)
    db.commit()


def test_chk_creator_required(db):
    """A staff role with no created_by_user_id must be rejected (PATIENT
    and SUPERUSER are the only exemptions)."""
    with pytest.raises(IntegrityError, match="chk_creator_required"):
        _bare_user_insert(db, role="BMO", role_level=5, created_by_user_id=None, mfa_required=True)
    db.rollback()


def test_chk_creator_required_allows_patient(db):
    _bare_user_insert(db, role="PATIENT", role_level=99, created_by_user_id=None)  # must not raise


def test_chk_scope_required(db):
    """A staff role with no scope_org_unit_id must be rejected (PATIENT
    and SUPERUSER exempted)."""
    root = make_active_actor(db, role="SUPERUSER", org_unit_id=None, mobile="+919888800001")
    db.commit()
    with pytest.raises(IntegrityError, match="chk_scope_required"):
        _bare_user_insert(db, role="BMO", role_level=5, created_by_user_id=root,
                           scope_org_unit_id=None, mfa_required=True)
    db.rollback()


def test_chk_suspension_reason(db):
    """A SUSPENDED row with no suspension_reason must be rejected."""
    with pytest.raises(IntegrityError, match="chk_suspension_reason"):
        _bare_user_insert(db, status="SUSPENDED", suspension_reason=None)
    db.rollback()


def test_chk_deactivated_no_creds(db):
    """A DEACTIVATED row that still has a password_hash must be rejected."""
    with pytest.raises(IntegrityError, match="chk_deactivated_no_creds"):
        _bare_user_insert(db, status="DEACTIVATED", password_hash="not-null-hash")
    db.rollback()


def test_chk_privileged_mfa(db):
    """A privileged role (role_level <= 5) with mfa_required=false must
    be rejected."""
    root = make_active_actor(db, role="SUPERUSER", org_unit_id=None, mobile="+919888800002")
    db.commit()
    with pytest.raises(IntegrityError, match="chk_privileged_mfa"):
        _bare_user_insert(db, role="BMO", role_level=5, created_by_user_id=root, mfa_required=False)
    db.rollback()


def test_chk_superuser_expires(db):
    """A SUPERUSER row with no expires_at must be rejected."""
    with pytest.raises(IntegrityError, match="chk_superuser_expires"):
        _bare_user_insert(db, role="SUPERUSER", role_level=0, expires_at=None, mfa_required=True)
    db.rollback()


def test_chk_no_self_report(db):
    """A user cannot report to themselves."""
    root = make_active_actor(db, role="SUPERUSER", org_unit_id=None, mobile="+919888800003")
    db.commit()
    new_id = uuid.uuid4()
    with pytest.raises(IntegrityError, match="chk_no_self_report"):
        db.exec(text(
            "INSERT INTO users (id, role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
            "mobile_masked, status, created_by_user_id, mfa_required, reports_to_user_id) "
            "VALUES (:id, 'PATIENT', 99, 'X', :menc, :mbi, :mmask, 'ACTIVE', NULL, false, :id)"
        ), params={"id": str(new_id), "menc": b"\x00", "mbi": f"bi-{uuid.uuid4().hex}", "mmask": "+91XXXXX00000"})
        db.commit()
    db.rollback()
