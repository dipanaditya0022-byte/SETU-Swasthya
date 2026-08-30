"""Governance route surface: GET /audit, GET /consents/{patient_id},
POST /consents/{patient_id}/revoke, POST /system/break-glass. Day1.md
SS14.3's own table lists all four as part of the Day 1 API surface
(permissions: audit:read, consent:read, consent:revoke,
system:break_glass), and role_permissions/permissions (S11's seed) were
already fully seeded for them -- but no route existed for any of the
four anywhere in this codebase until now. Found while starting S22
(a documentation step), confirmed with the user directly before
building real endpoints instead of documenting fictional ones.

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- Permissions, purposes, and the DB tables themselves (audit_log,
  consents, break_glass_sessions) are all already-existing, already-
  seeded/migrated Day1.md SS8.2/SS12.2/SS13.4 material (S9/S11) --
  nothing new invented at the schema level.
- SS9.3's own break-glass row is followed exactly: "Requires POST
  /system/break-glass with a >=50-character justification. Grants 60
  minutes. Notifies the DPO immediately." -- expires_at =
  now + 60 minutes, justification length enforced both at the Pydantic
  layer (a clean 422) and by the DB's own chk_justification_length
  (already present, S8), DPO notification via the same dev-mode
  logger.warning pattern app/core/tokens.py's alert_security_team
  already established (no real notification gateway exists anywhere in
  this repo).
- Day1.md gives no literal request/response JSON for any of these four
  endpoints (unlike POST /users' full SS14.4 example) -- these shapes
  are this step's own concrete, minimal design, following the same
  "propose clearly, document per-endpoint, let the user correct"
  pattern already established and confirmed for auth.py's own several
  under-specified endpoints in S16:
    * GET /audit: query-param filters (actor_user_id, action,
      target_type, target_id, occurred_at range, limit/offset),
      returns rows including prev_hash/row_hash (not secrets -- the
      whole point of exposing them to an audit:read holder is so they
      can verify the hash chain themselves, matching SS12.3's own
      "a nightly verifier walks the chain" framing extended to a human
      reviewer).
    * GET/POST /consents/{patient_id}[/revoke]: SS8.3's own role map
      is explicit that PATIENT's consent:read/revoke is scoped to
      "self" while DPO/SUPERUSER are unscoped ("DPO ... nothing
      clinical" but full oversight) -- enforced here as: the
      permission check (require("consent:read"/"consent:revoke"))
      gates whether the role can do this AT ALL, then a PATIENT actor
      is additionally restricted to their own patient_id (404, not 403,
      matching this codebase's established anti-enumeration convention
      for existing-record scope failures -- app.core.authz's own
      docstring on the 403-vs-404 split). Revoke follows SS12's own
      already-stated design for the *table* ("Consent is append-only.
      A change writes a new row and stamps superseded_at on the old
      one") -- revoke supersedes the current row and inserts a new one
      with all four consent booleans false, not a destructive update.
    * POST /system/break-glass: returns the new break_glass_sessions
      row's id/expires_at; SS9.3's "every record touched is logged
      individually" (the PHI-access-during-break-glass audit trail
      itself) is out of scope for this one activation endpoint -- no
      route in this codebase yet reads PHI by record ID in a way that
      would consult an active break-glass session, so there is nothing
      for this step to wire that check into without inventing a new
      PHI-read endpoint Day1.md doesn't ask for here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, text

from app.core.authz import require
from app.db.database import get_session

router = APIRouter(tags=["Governance"])
logger = logging.getLogger(__name__)


def _write_audit(session: Session, *, actor_user_id: Optional[str], action: str, outcome: str,
                  target_type: Optional[str] = None, target_id: Optional[str] = None,
                  metadata: Optional[dict] = None) -> None:
    from app.core.audit import compute_row_hash
    prev = session.exec(text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")).first()
    prev_hash = prev[0] if prev else None
    occurred_at = datetime.now(timezone.utc)
    entry = {"occurred_at": occurred_at, "actor_user_id": actor_user_id, "action": action,
              "outcome": outcome, "target_type": target_type, "target_id": target_id, "metadata": metadata or {}}
    row_hash = compute_row_hash(entry, prev_hash)
    session.exec(text(
        "INSERT INTO audit_log (occurred_at, actor_user_id, action, outcome, target_type, target_id, "
        "metadata, prev_hash, row_hash) VALUES "
        "(:oa, :au, :ac, :oc, :tt, :ti, :md, :ph, :rh)"
    ), params={"oa": occurred_at, "au": actor_user_id, "ac": action, "oc": outcome, "tt": target_type,
               "ti": target_id, "md": json.dumps(metadata or {}), "ph": prev_hash, "rh": row_hash})


# ============================================================
# GET /audit -- SS14.3, permission audit:read (DPO, STATE_NHM, SUPERUSER)
# ============================================================

@router.get("/audit")
def list_audit_log(
    actor_user_id: Optional[UUID] = None, action: Optional[str] = None,
    target_type: Optional[str] = None, target_id: Optional[str] = None,
    occurred_from: Optional[datetime] = None, occurred_to: Optional[datetime] = None,
    limit: int = Query(default=50, le=200), offset: int = 0,
    current_user=Depends(require("audit:read")), session: Session = Depends(get_session),
):
    conditions = []
    params: dict[str, Any] = {"limit": max(1, min(limit, 200)), "offset": max(0, offset)}
    if actor_user_id is not None:
        conditions.append("actor_user_id = :actor_user_id")
        params["actor_user_id"] = str(actor_user_id)
    if action is not None:
        conditions.append("action = :action")
        params["action"] = action
    if target_type is not None:
        conditions.append("target_type = :target_type")
        params["target_type"] = target_type
    if target_id is not None:
        conditions.append("target_id = :target_id")
        params["target_id"] = target_id
    if occurred_from is not None:
        conditions.append("occurred_at >= :occurred_from")
        params["occurred_from"] = occurred_from
    if occurred_to is not None:
        conditions.append("occurred_at <= :occurred_to")
        params["occurred_to"] = occurred_to
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = session.exec(text(
        f"SELECT id, occurred_at, actor_user_id, action, outcome, target_type, target_id, "
        f"metadata, prev_hash, row_hash FROM audit_log {where_clause} "
        f"ORDER BY id DESC LIMIT :limit OFFSET :offset"
    ), params=params).all()

    return {"entries": [
        {"id": r[0], "occurred_at": r[1].isoformat(), "actor_user_id": str(r[2]) if r[2] else None,
         "action": r[3], "outcome": r[4], "target_type": r[5], "target_id": r[6],
         "metadata": r[7], "prev_hash": r[8], "row_hash": r[9]}
        for r in rows
    ], "limit": params["limit"], "offset": params["offset"]}


# ============================================================
# GET /consents/{patient_id}, POST /consents/{patient_id}/revoke --
# SS14.3, permissions consent:read/consent:revoke (DPO, PATIENT self, SUPERUSER)
# ============================================================

def _assert_consent_scope(current_user, patient_id: UUID) -> None:
    """PATIENT is scoped to self; DPO/SUPERUSER are unscoped (SS8.3's own
    role map). 404, not 403, for the same anti-enumeration reason every
    other existing-record scope failure in this codebase uses."""
    if current_user.role == "PATIENT" and str(current_user.id) != str(patient_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "detail": "Not found."})


def _get_patient_or_404(session: Session, patient_id: UUID) -> None:
    row = session.exec(text("SELECT id FROM users WHERE id = :id AND role = 'PATIENT'"),
                        params={"id": str(patient_id)}).first()
    if row is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "detail": "Not found."})


@router.get("/consents/{patient_id}")
def get_consents(patient_id: UUID, current_user=Depends(require("consent:read")),
                  session: Session = Depends(get_session)):
    _assert_consent_scope(current_user, patient_id)
    _get_patient_or_404(session, patient_id)

    rows = session.exec(text(
        "SELECT id, keep_record, share_specialist, share_facility, anonymised_planning, mode, "
        "witness_name, language, recorded_by, recorded_at, superseded_at "
        "FROM consents WHERE patient_user_id = :pid ORDER BY recorded_at DESC"
    ), params={"pid": str(patient_id)}).all()

    _write_audit(session, actor_user_id=str(current_user.id), action="CONSENT_READ", outcome="SUCCESS",
                 target_type="USER", target_id=str(patient_id))
    session.commit()

    return {"patient_id": str(patient_id), "consents": [
        {"id": str(r[0]), "keep_record": r[1], "share_specialist": r[2], "share_facility": r[3],
         "anonymised_planning": r[4], "mode": r[5], "witness_name": r[6], "language": r[7],
         "recorded_by": str(r[8]) if r[8] else None, "recorded_at": r[9].isoformat(),
         "superseded_at": r[10].isoformat() if r[10] else None, "active": r[10] is None}
        for r in rows
    ]}


class ConsentRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = None


@router.post("/consents/{patient_id}/revoke")
def revoke_consent(patient_id: UUID, body: ConsentRevokeRequest,
                    current_user=Depends(require("consent:revoke")), session: Session = Depends(get_session)):
    _assert_consent_scope(current_user, patient_id)
    _get_patient_or_404(session, patient_id)

    current = session.exec(text(
        "SELECT id, mode, language, witness_name FROM consents "
        "WHERE patient_user_id = :pid AND superseded_at IS NULL ORDER BY recorded_at DESC LIMIT 1"
    ), params={"pid": str(patient_id)}).first()
    if current is None:
        raise HTTPException(404, {"code": "NO_ACTIVE_CONSENT", "detail": "No active consent record to revoke."})
    current_id, mode, language, witness_name = current

    now = datetime.now(timezone.utc)
    session.exec(text("UPDATE consents SET superseded_at = :now WHERE id = :id"),
                 params={"now": now, "id": current_id})

    new_row = session.exec(text(
        "INSERT INTO consents (patient_user_id, keep_record, share_specialist, share_facility, "
        "anonymised_planning, mode, witness_name, recorded_by, language) "
        "VALUES (:pid, false, false, false, false, :mode, :witness, :recorder, :lang) "
        "RETURNING id, recorded_at"
    ), params={"pid": str(patient_id), "mode": mode, "witness": witness_name,
               "recorder": str(current_user.id), "lang": language}).first()

    _write_audit(session, actor_user_id=str(current_user.id), action="CONSENT_REVOKED", outcome="SUCCESS",
                 target_type="USER", target_id=str(patient_id), metadata={"reason": body.reason})
    session.commit()

    return {"patient_id": str(patient_id), "id": str(new_row[0]), "recorded_at": new_row[1].isoformat(),
            "keep_record": False, "share_specialist": False, "share_facility": False,
            "anonymised_planning": False}


# ============================================================
# POST /system/break-glass -- SS14.3/SS9.3, permission system:break_glass (SUPERUSER)
# ============================================================

class BreakGlassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    justification: str = Field(min_length=50)


@router.post("/system/break-glass")
def break_glass(body: BreakGlassRequest, current_user=Depends(require("system:break_glass")),
                 session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=60)

    row = session.exec(text(
        "INSERT INTO break_glass_sessions (user_id, justification, started_at, expires_at, dpo_notified_at) "
        "VALUES (:uid, :just, :now, :exp, :now) RETURNING id"
    ), params={"uid": str(current_user.id), "just": body.justification, "now": now, "exp": expires_at}).first()
    session_id = row[0]

    # No SMS/email/pager gateway exists anywhere in this repo (SMS_GATEWAY_URL
    # is an empty placeholder, S2) -- same dev-mode pattern as
    # app/core/tokens.py's alert_security_team.
    logger.warning("DPO NOTIFICATION (no gateway configured): break-glass session %s activated by user_id=%s -- %s",
                    session_id, current_user.id, body.justification)

    _write_audit(session, actor_user_id=str(current_user.id), action="BREAK_GLASS_ACTIVATED", outcome="SUCCESS",
                 target_type="BREAK_GLASS_SESSION", target_id=str(session_id),
                 metadata={"justification": body.justification, "expires_at": expires_at.isoformat()})
    session.commit()

    return {"id": str(session_id), "expires_at": expires_at.isoformat(), "dpo_notified": True}
