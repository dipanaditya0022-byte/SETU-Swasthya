"""POST /triage/ -- Aditya's original, contract-frozen Day 1 endpoint
(backend/docs/API_CONTRACT.md), extended per Day1.md SS14.1's own table:
"now requires triage:create + scope". S20.

Request fields (patient_id/facility_id/triage_disposition/
referral_urgency) and the response shape's pre-existing fields are
UNCHANGED.

Scope: SS8.1's own formula -- "target record is inside user's scope" --
is applied to the PATIENT this encounter is about (the only existing
record the request references). The referenced patient is looked up;
if it doesn't exist, 404 (this endpoint had no such check before, since
`triageencounter.patient_id` carries no DB-level foreign key -- see
migration 79a9d8f8db61 -- but a scope check is meaningless without first
resolving the record to check); if it exists but sits outside the
actor's scope, 403 OUT_OF_SCOPE (creation-time semantics, matching
app.core.authz's own Gate-3 precedent for creation-time scope failures
-- see that module's docstring for the 403-vs-404 reasoning). The new
encounter's own `created_by_user_id`/`org_unit_id` (added to the
TriageEncounter model in this step -- see app/models/triage_encounter.py)
are always set from the authenticated actor, never trusted from client
input.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, text

from app.core.authz import org_unit_is_within_scope, require
from app.db.database import get_session
from app.models import Patient, TriageEncounter

router = APIRouter(prefix="/triage", tags=["Triage"])


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


@router.post("/", response_model=TriageEncounter)
def create_triage(
    triage: TriageEncounter,
    current_user=Depends(require("triage:create")),
    session: Session = Depends(get_session),
):
    if current_user.scope_org_unit_id is None:
        raise HTTPException(403, {"code": "OUT_OF_SCOPE",
                                   "detail": "Your account has no posting to attribute this record to."})

    patient = session.get(Patient, triage.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not org_unit_is_within_scope(session, patient.org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(403, {"code": "OUT_OF_SCOPE", "detail": "That patient is outside the area you manage."})

    triage.created_by_user_id = current_user.id
    triage.org_unit_id = current_user.scope_org_unit_id

    session.add(triage)
    session.commit()
    session.refresh(triage)

    _write_audit(session, actor_user_id=str(current_user.id), action="TRIAGE_CREATED", outcome="SUCCESS",
                 target_type="TRIAGE", target_id=str(triage.id))
    session.commit()
    # SQLAlchemy's default expire_on_commit=True means this second commit
    # expires `triage`'s cached attributes -- found by testing on
    # app/api/routes/patients.py's identical pattern; response_model
    # serialization would otherwise return an empty body.
    session.refresh(triage)

    return triage
