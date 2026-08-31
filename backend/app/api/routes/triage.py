"""POST /triage/ -- Aditya's original, contract-frozen Day 1 endpoint
(backend/docs/API_CONTRACT.md), extended per Day1.md SS14.1's own table's
"now requires triage:create + scope" (S20), and now (this step) wired to
an actual triage decision engine (app/services/triage/port.py, fallback.py,
adapter.py, factory.py).

Request fields (patient_id/facility_id/triage_disposition/
referral_urgency) and the response shape's pre-existing fields are
UNCHANGED. The only addition to the response is a new `decision` object.
See TriageEvaluationRequest/TriageEvaluationResponse below for the exact
shapes.

WHY THIS STEP EXISTS: before this, the endpoint stored whatever
disposition/urgency the caller sent. A caller could mark an eclamptic
patient "manage here" and nothing would stop it -- that defeats triage
entirely. From this step on, the server computes the disposition itself;
a client-supplied disposition/urgency/reason/red_flags (or any of the
other engine-output field names) is accepted (so old clients don't 422)
but always ignored, and the attempt is logged.

ORDER OF OPERATIONS inside create_triage, deliberately preserved in
comments below, matching this step's own instruction:
  1. AuthN + AuthZ (require("triage:create") + patient scope check --
     same pattern as app/api/routes/patients.py / referrals.py).
  2. Request body validation (TriageEvaluationRequest, pydantic).
  3. Ignore + log any caller-supplied decision fields.
  4. Load patient context (age, from Patient -- the only patient
     attribute this data model actually stores; see the request schema's
     own docstring for why vitals/sex/pregnancy/registries are NOT
     patient-master-data in this repo and are instead this encounter's
     own point-of-care observations).
  5. CALL THE ENGINE -- get_triage_engine().evaluate(...). Strictly
     before step 6: a crash between the two must never leave an
     un-triaged encounter in the database.
  6. Persist the row, including all nine decision columns (migration
     a4d72f9e1c83).
  7. Audit: TRIAGE_EVALUATED.
  8. Return existing fields + the new `decision` object.

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
TriageEncounter model in S20 -- see app/models/triage_encounter.py) are
always set from the authenticated actor, never trusted from client
input.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, text

from app.core.authz import org_unit_is_within_scope, require
from app.db.database import get_session
from app.models import Patient, TriageEncounter
from app.services.triage.factory import TriageEngineNotReady, get_triage_engine
from app.services.triage.fallback import FallbackTriageEngine
from app.services.triage.port import Disposition, TriageEngineError, TriageInput, Urgency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triage", tags=["Triage"])

# Mirrors app/services/triage/port.py's own TriageInput.protocol Literal
# set verbatim (also duplicated the same way in fallback.py's own
# _PROTOCOL_HANDLERS/_REQUIRED_VITALS dict keys -- same established
# pattern in this package, not a new one).
_VALID_PROTOCOLS: set[str] = {"ANC", "IMNCI", "NCD", "TB", "FEVER", "INJURY", "GENERAL"}

# The nine engine-computed columns (migration a4d72f9e1c83). A client
# sending any of these is never authoritative -- see STEP 3 below.
_DECISION_OUTPUT_FIELDS: set[str] = {
    "disposition", "urgency", "reason", "red_flags", "protocol_version",
    "insufficient_data", "missing_fields", "engine", "evaluated_at",
}


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


# ============================================================
# Schemas
# ============================================================

class TriageEvaluationRequest(BaseModel):
    """POST /triage/ request body. `patient_id`/`facility_id`/
    `triage_disposition`/`referral_urgency` are Aditya's original,
    contract-frozen fields (backend/docs/API_CONTRACT.md) -- UNCHANGED.

    Every other field is additive: this encounter's own point-of-care
    observations, needed to actually run a decision engine
    (app/services/triage/*). None of these (vitals, symptoms,
    danger_signs, sex, pregnancy, gestational weeks, history) exist
    anywhere in the Patient data model today (checked: app/models/
    patient.py stores only name/age/village/phone/facility_id -- no
    vitals/sex/pregnancy/registry columns, and no separate vitals or
    registry table exists in this repo yet). So they're supplied
    per-encounter here, the same way any other point-of-care vitals
    entry works, rather than inventing new patient-master-data tables
    in this step. `age_years` is deliberately NOT one of these fields:
    it is loaded from the Patient row itself (the one piece of this
    context the data model actually has) and is never client-supplied,
    so it can't be spoofed to a different age than the record on file.

    extra="allow" (not "forbid", unlike this repo's other request
    schemas in app/api/routes/auth.py) is deliberate: an old client may
    still send a caller-computed disposition/urgency/reason/red_flags
    (or any other engine-output field name). Those are never
    authoritative -- the engine always recomputes them (see
    create_triage's own STEP 3) -- and must not be rejected with a 422
    just because the client sent extra keys; only ignored, and logged.
    """
    model_config = ConfigDict(extra="allow")

    patient_id: UUID
    facility_id: UUID
    triage_disposition: str
    referral_urgency: Optional[str] = None

    protocol: Optional[str] = None
    vitals: dict[str, float] = Field(default_factory=dict)
    symptoms: list[str] = Field(default_factory=list)
    danger_signs: list[str] = Field(default_factory=list)
    sex: Optional[Literal["FEMALE", "MALE", "OTHER"]] = None
    is_pregnant: bool = False
    gestational_weeks: Optional[float] = None
    history: dict[str, bool] = Field(default_factory=dict)


class TriageDecisionOut(BaseModel):
    """The new, additive `decision` object -- exactly TriageOutput's own
    fields (app/services/triage/port.py) plus `engine` (which produced
    this decision: "rule" or "fallback" -- deliberately surfaced, a
    clinician and a reviewer both need to know which logic answered)."""
    disposition: Disposition
    urgency: Urgency
    reason: str
    red_flags: list[str]
    protocol_version: str
    insufficient_data: bool
    missing_fields: list[str]
    engine: Literal["rule", "fallback"]
    evaluated_at: datetime


class TriageEvaluationResponse(BaseModel):
    """Existing response fields (id/patient_id/facility_id/
    triage_disposition/referral_urgency/created_at/created_by_user_id/
    org_unit_id) UNCHANGED. `decision` is the only addition."""
    id: UUID
    patient_id: UUID
    facility_id: UUID
    triage_disposition: str
    referral_urgency: Optional[str] = None
    created_at: datetime
    created_by_user_id: Optional[UUID] = None
    org_unit_id: Optional[UUID] = None
    decision: TriageDecisionOut


@router.post("/", response_model=TriageEvaluationResponse)
def create_triage(
    triage_in: TriageEvaluationRequest,
    current_user=Depends(require("triage:create")),
    session: Session = Depends(get_session),
):
    # ------------------------------------------------------------
    # STEP 1 -- AuthN + AuthZ. require("triage:create") already ran (see
    # the Depends above); this is the scope check on the patient the
    # encounter is about.
    # ------------------------------------------------------------
    if current_user.scope_org_unit_id is None:
        raise HTTPException(403, {"code": "OUT_OF_SCOPE",
                                   "detail": "Your account has no posting to attribute this record to."})

    patient = session.get(Patient, triage_in.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not org_unit_is_within_scope(session, patient.org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(403, {"code": "OUT_OF_SCOPE", "detail": "That patient is outside the area you manage."})

    # ------------------------------------------------------------
    # STEP 2 -- request body validation already happened via
    # TriageEvaluationRequest (FastAPI/pydantic), before this function
    # body even started running.
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # STEP 3 -- never trust a caller-supplied decision. Ignore, don't
    # 4xx (old clients may still send these), but log the attempt so
    # it's traceable. Only field NAMES and patient_id/actor_id are
    # logged -- not the client's disposition/reason/etc. values
    # themselves, since those are exactly the unverified data we're
    # refusing to trust and there's no reason to persist them anywhere.
    # ------------------------------------------------------------
    sent_decision_fields = sorted(set(triage_in.model_extra or {}) & _DECISION_OUTPUT_FIELDS)
    if sent_decision_fields:
        logger.info(
            "POST /triage/: client sent engine-computed decision field(s) %s "
            "(ignored -- server always recomputes). patient_id=%s actor_id=%s",
            sent_decision_fields, triage_in.patient_id, current_user.id,
        )

    # ------------------------------------------------------------
    # STEP 4 -- load patient context. See TriageEvaluationRequest's own
    # docstring: age_years is the one piece of this context the data
    # model actually stores today (Patient.age); sex/pregnancy/
    # gestational-weeks/vitals/symptoms/danger-signs/history/active
    # registries are NOT present anywhere in the data model (no such
    # columns or tables exist), so they come from this encounter's own
    # request payload instead of being invented as new persistent
    # fields in this step.
    # ------------------------------------------------------------
    protocol = triage_in.protocol or "GENERAL"
    if protocol not in _VALID_PROTOCOLS:
        raise HTTPException(422, {"code": "INVALID_PROTOCOL",
                                   "detail": f"Unknown triage protocol: {protocol!r}."})

    engine_input = TriageInput(
        protocol=protocol,
        age_years=float(patient.age) if patient.age is not None else None,
        sex=triage_in.sex,
        is_pregnant=triage_in.is_pregnant,
        gestational_weeks=triage_in.gestational_weeks,
        vitals=triage_in.vitals,
        symptoms=triage_in.symptoms,
        danger_signs=triage_in.danger_signs,
        history=triage_in.history,
    )

    # ------------------------------------------------------------
    # STEP 5 -- CALL THE ENGINE. Strictly before STEP 6 (persistence):
    # a crash between the two must never leave an un-triaged encounter
    # in the database.
    # ------------------------------------------------------------
    mode = os.environ.get("TRIAGE_ENGINE", "auto").strip().lower()
    try:
        engine = get_triage_engine()
    except TriageEngineNotReady as exc:
        # TRIAGE_ENGINE=rule was forced and the rule engine isn't ready.
        logger.error("Triage engine unavailable (TRIAGE_ENGINE=rule forced, not ready): %s", exc)
        raise HTTPException(503, {"code": "TRIAGE_ENGINE_UNAVAILABLE",
                                   "detail": "The triage decision engine is not available."})

    engine_name = engine.name
    try:
        decision = engine.evaluate(engine_input)
    except TriageEngineError as exc:
        if mode == "rule":
            # TRIAGE_ENGINE=rule forced: no fallback permitted, fail closed.
            logger.error("Triage engine (TRIAGE_ENGINE=rule) raised during evaluate(): %s", exc)
            raise HTTPException(503, {"code": "TRIAGE_ENGINE_UNAVAILABLE",
                                       "detail": "The triage decision engine is not available."})
        # auto/fallback mode: get_triage_engine() already probed
        # readiness (auto) and/or already IS the fallback engine
        # (fallback), so evaluate() itself raising here is not expected
        # in normal operation. Don't fail the request over it -- log
        # ERROR and fall back to the deterministic engine directly.
        logger.error(
            "Triage engine %r raised during evaluate() outside forced-rule mode; "
            "falling back to the deterministic engine: %s", engine_name, exc,
        )
        try:
            decision = FallbackTriageEngine().evaluate(engine_input)
            engine_name = "fallback"
        except Exception as fallback_exc:  # noqa: BLE001 -- fail closed, never silently
            logger.error("Fallback engine also failed: %s", fallback_exc)
            raise HTTPException(503, {"code": "TRIAGE_ENGINE_UNAVAILABLE",
                                       "detail": "The triage decision engine is not available."})

    # ------------------------------------------------------------
    # STEP 6 -- persist, including all nine decision columns. Comes
    # strictly after STEP 5.
    # ------------------------------------------------------------
    triage = TriageEncounter(
        patient_id=triage_in.patient_id,
        facility_id=triage_in.facility_id,
        triage_disposition=triage_in.triage_disposition,
        referral_urgency=triage_in.referral_urgency,
    )
    triage.created_by_user_id = current_user.id
    triage.org_unit_id = current_user.scope_org_unit_id
    triage.disposition = decision.disposition
    triage.urgency = decision.urgency
    triage.reason = decision.reason
    triage.red_flags = decision.red_flags
    triage.protocol_version = decision.protocol_version
    triage.insufficient_data = decision.insufficient_data
    triage.missing_fields = decision.missing_fields
    triage.engine = engine_name
    triage.evaluated_at = datetime.now(timezone.utc)

    session.add(triage)
    session.commit()
    session.refresh(triage)

    # ------------------------------------------------------------
    # STEP 7 -- audit.
    # ------------------------------------------------------------
    _write_audit(session, actor_user_id=str(current_user.id), action="TRIAGE_EVALUATED", outcome="SUCCESS",
                 target_type="TRIAGE", target_id=str(triage.id),
                 metadata={"engine": engine_name, "protocol_version": triage.protocol_version,
                           "disposition": triage.disposition, "insufficient_data": triage.insufficient_data})
    session.commit()
    # SQLAlchemy's default expire_on_commit=True means this second commit
    # expires `triage`'s cached attributes -- found by testing on
    # app/api/routes/patients.py's identical pattern; response
    # serialization would otherwise return an empty body.
    session.refresh(triage)

    # ------------------------------------------------------------
    # STEP 8 -- return existing fields + the new `decision` object.
    # ------------------------------------------------------------
    return {
        "id": triage.id,
        "patient_id": triage.patient_id,
        "facility_id": triage.facility_id,
        "triage_disposition": triage.triage_disposition,
        "referral_urgency": triage.referral_urgency,
        "created_at": triage.created_at,
        "created_by_user_id": triage.created_by_user_id,
        "org_unit_id": triage.org_unit_id,
        "decision": {
            "disposition": triage.disposition,
            "urgency": triage.urgency,
            "reason": triage.reason,
            "red_flags": triage.red_flags,
            "protocol_version": triage.protocol_version,
            "insufficient_data": triage.insufficient_data,
            "missing_fields": triage.missing_fields,
            "engine": triage.engine,
            "evaluated_at": triage.evaluated_at,
        },
    }
