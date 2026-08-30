"""POST /referrals/ and PATCH /referrals/{referral_id}/status -- Aditya's
original, contract-frozen Day 1 endpoints (backend/docs/API_CONTRACT.md),
extended per Day1.md SS14.1's own table: "now requires referral:create +
scope" / "referral:update_status + scope". S20.

Request fields and the response shapes' pre-existing fields are
UNCHANGED.

Scope for CREATE: same reasoning as app/api/routes/triage.py -- the
referenced PATIENT (the only existing record the request points to) is
looked up and checked; missing -> 404 (no such check existed before,
since `referral.patient_id` carries no DB-level FK -- migration
79a9d8f8db61); out of scope -> 403 OUT_OF_SCOPE (creation-time
semantics). `created_by_user_id`/`org_unit_id` (added to the Referral
model this step) are always actor-derived, never client-trusted.

Scope for the status PATCH: the REFERRAL itself is now the existing
target record (it already carries its own `org_unit_id`, set at
creation), so its own scope is checked directly -- no need to re-look-up
the patient. The original 404 response shape (`HTTPException(
status_code=404, detail="Referral not found")`, a plain string) is
preserved exactly and reused for both "doesn't exist" and "exists but
out of scope", for the same anti-enumeration reasoning as GET
/patients/{id} (see that route's own docstring / app.core.authz's
module docstring on the 403-vs-404 split for existing records).
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, text

from app.core.authz import org_unit_is_within_scope, require
from app.db.database import get_session
from app.models import Patient, Referral

router = APIRouter(prefix="/referrals", tags=["Referrals"])


def _write_audit(session: Session, *, actor_user_id: Optional[str], action: str,
                  outcome: str, target_type: Optional[str] = None,
                  target_id: Optional[str] = None, metadata: Optional[dict] = None) -> None:
    import json
    from app.core.audit import compute_row_hash
    prev = session.exec(text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")).first()
    prev_hash = prev[0] if prev else None
    occurred_at = datetime.now(timezone.utc)
    entry = {"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
              "outcome": outcome, "target_type": target_type, "target_id": target_id,
              "metadata": metadata or {}}
    row_hash = compute_row_hash(entry, prev_hash)
    session.exec(text(
        "INSERT INTO audit_log (occurred_at, actor_user_id, action, outcome, target_type, "
        "target_id, metadata, prev_hash, row_hash) VALUES "
        "(:occurred_at, :actor_user_id, :action, :outcome, :target_type, :target_id, "
        ":metadata, :prev_hash, :row_hash)"
    ), params={"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
               "outcome": outcome, "target_type": target_type, "target_id": target_id,
               "metadata": json.dumps(metadata or {}), "prev_hash": prev_hash, "row_hash": row_hash})


@router.post("/", response_model=Referral)
def create_referral(
    referral: Referral,
    current_user=Depends(require("referral:create")),
    session: Session = Depends(get_session),
):
    if current_user.scope_org_unit_id is None:
        raise HTTPException(403, {"code": "OUT_OF_SCOPE",
                                   "detail": "Your account has no posting to attribute this record to."})

    patient = session.get(Patient, referral.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not org_unit_is_within_scope(session, patient.org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(403, {"code": "OUT_OF_SCOPE", "detail": "That patient is outside the area you manage."})

    referral.created_by_user_id = current_user.id
    referral.org_unit_id = current_user.scope_org_unit_id

    session.add(referral)
    session.commit()
    session.refresh(referral)

    _write_audit(session, actor_user_id=str(current_user.id), action="REFERRAL_CREATED", outcome="SUCCESS",
                 target_type="REFERRAL", target_id=str(referral.id))
    session.commit()
    # Same expire_on_commit note as app/api/routes/patients.py/triage.py.
    session.refresh(referral)

    return referral


@router.patch("/{referral_id}/status", response_model=Referral)
def update_referral_status(
    referral_id: UUID,
    status: str,
    current_user=Depends(require("referral:update_status")),
    session: Session = Depends(get_session),
):
    referral = session.get(Referral, referral_id)

    if not referral or not org_unit_is_within_scope(session, referral.org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(status_code=404, detail="Referral not found")

    old_status = referral.status
    referral.status = status
    session.add(referral)
    session.commit()
    session.refresh(referral)

    _write_audit(session, actor_user_id=str(current_user.id), action="REFERRAL_STATUS_UPDATED", outcome="SUCCESS",
                 target_type="REFERRAL", target_id=str(referral.id),
                 metadata={"from": old_status, "to": status})
    session.commit()
    # Same expire_on_commit note as create_referral above.
    session.refresh(referral)

    return referral
