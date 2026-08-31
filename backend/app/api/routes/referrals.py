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

===========================================================================
D2-S7 -- the referral state machine wired into PATCH .../status.
===========================================================================

`status` (the query parameter) is Aditya's original, contract-frozen
field -- UNCHANGED, still a query parameter, same name. Everything else
below is additive: an optional JSON request body carrying per-transition
data (`ReferralStatusUpdateBody`), and additive response fields
(`allowed_next`). A client sending no body at all still works for any
transition that requires no extra data (e.g. -> CLOSED, -> RESCHEDULED,
-> NOT_ARRIVED).

GAP FOUND AND HANDLED, NOT SILENTLY DROPPED -- three of
app.models.referral_state.TRANSITION_REQUIRED_FIELDS' field names do not
have a backing column on `referral`, verified against migration
d4f1c9b7a582's own column list (checked directly, not assumed):

  - `consulted_by_user_id` (required for -> CONSULTED)
  - `traced_by_user_id`    (required for -> TRACED)
  - `not_arrived_at`       (side effect of -> NOT_ARRIVED)

None of these three exist as first-class `referral` columns today. Per
this task's own explicit instruction, they are NOT silently dropped and
this step does NOT sneak in a new migration to add them (out of scope --
"one concern per change"). Instead they are persisted in
`referral_transitions.metadata` (JSONB), which already exists on the
append-only transition-history table this route writes to on *every*
transition regardless (see STEP 6 below) -- the natural place for
per-transition contextual data that doesn't (yet) have a first-class
`referral` column. A future migration could promote any of these to
real `referral` columns if the product wants them directly queryable
(e.g. "list all referrals currently awaiting consult, filterable by
consulting officer") without a JSONB scan.

SUBSTITUTION FOUND AND DOCUMENTED: TRANSITION_REQUIRED_FIELDS lists
`destination_org_unit_id` as required for -> SLOT_BOOKED. No column by
that exact name exists on `referral`. The column that actually serves
this purpose is `destination_facility_id` (already on the table since
the very first referral migration, 79a9d8f8db61, `NOT NULL`, already set
at creation time). So `destination_org_unit_id` in the request body is
mapped onto the existing `destination_facility_id` column -- not a new
column, and not silently ignored either.

REQUEST ID: no request-id generation/propagation mechanism exists
anywhere else in this repo today (checked: no middleware, no other
route's error body carries one). A uuid4 is generated per request here,
local to this function, purely for the two new 409 error bodies' own
`request_id` field -- not wired into logging or any other cross-cutting
concern, since none exists yet to hook into.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, text

from app.core.authz import org_unit_is_within_scope, require
from app.db.database import get_session
from app.models import Patient, Referral
from app.services.referral.breach import compute_due_at
from app.models.referral_state import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    ReferralState,
    RefusalReason,
    TERMINAL_STATES,
    TRANSITION_REQUIRED_FIELDS,
    assert_transition_allowed,
)

router = APIRouter(prefix="/referrals", tags=["Referrals"])

# Canonical display order for `allowed_next` / the `detail` sentence --
# ALLOWED_TRANSITIONS' values are Python `set`s, which have no reliable
# iteration order. Per this task's own instruction ("build detail's
# sentence and allowed_next's list from the actual ... allowed set ...
# don't hand-write per-state detail strings"), the CONTENT is always
# derived live from `InvalidTransition.allowed`; only the ORDER used to
# render that content is fixed here, by each state's declaration
# position in ReferralState (app/models/referral_state.py) -- so the
# response is deterministic and stable across processes/runs instead of
# depending on Python's set-hashing order.
_STATE_ORDER = {state: index for index, state in enumerate(ReferralState)}


def _ordered_values(states) -> list[str]:
    return [s.value for s in sorted(states, key=lambda s: _STATE_ORDER[s])]


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


def _write_transition(session: Session, *, referral_id: UUID, from_status: Optional[str],
                       to_status: str, actor_user_id: UUID, actor_role: str,
                       reason: Optional[str], metadata: dict) -> None:
    """Append-only row on `referral_transitions` (migration d4f1c9b7a582).
    Written on EVERY transition, no exceptions -- STEP 6 of this route's
    own BEHAVIOUR contract."""
    import json
    session.exec(text(
        "INSERT INTO referral_transitions "
        "(referral_id, from_status, to_status, actor_user_id, actor_role, reason, metadata) "
        "VALUES (:referral_id, :from_status, :to_status, :actor_user_id, :actor_role, :reason, :metadata)"
    ), params={
        "referral_id": str(referral_id), "from_status": from_status, "to_status": to_status,
        "actor_user_id": str(actor_user_id), "actor_role": actor_role, "reason": reason,
        "metadata": json.dumps(metadata),
    })


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

    # D2-S8: `due_at` was previously never set at creation (migration
    # d4f1c9b7a582 only backfilled EXISTING rows' due_at as part of its
    # own Phase 3; new rows created after that migration got due_at=NULL
    # until now). Always server-computed from the shared breach rule
    # (app/services/referral/breach.py) -- same reasoning as
    # created_by_user_id/org_unit_id just above, never trusts a
    # client-supplied due_at. Additive: no existing request/response
    # field is touched, this only fills in a column that already exists
    # and was already nullable.
    referral.due_at = compute_due_at(referral.initiated_at, referral.urgency)

    session.add(referral)
    session.commit()
    session.refresh(referral)

    _write_audit(session, actor_user_id=str(current_user.id), action="REFERRAL_CREATED", outcome="SUCCESS",
                 target_type="REFERRAL", target_id=str(referral.id))
    session.commit()
    # Same expire_on_commit note as app/api/routes/patients.py/triage.py.
    session.refresh(referral)

    return referral


# ============================================================
# D2-S7 -- PATCH /referrals/{referral_id}/status, state-machine wiring.
# ============================================================

class ReferralStatusUpdateBody(BaseModel):
    """Additive request body. `status` (the query parameter, Aditya's
    original contract-frozen field) is untouched. Every field here is
    new and optional at the schema level -- a transition with no
    required fields (e.g. -> CLOSED) needs none of them; enforcement of
    which fields are required for which transition happens inside the
    route, from TRANSITION_REQUIRED_FIELDS, not from this schema.

    See this module's own docstring for the two documented deviations:
    `destination_org_unit_id` is mapped onto the existing
    `destination_facility_id` column, and `consulted_by_user_id` /
    `traced_by_user_id` have no first-class `referral` column and are
    persisted on `referral_transitions.metadata` only (GAP note above).
    """
    model_config = ConfigDict(extra="ignore")

    # Generic transition note -- stored on referral_transitions.reason.
    reason: Optional[str] = None

    # -> SLOT_BOOKED
    slot_datetime: Optional[datetime] = None
    destination_org_unit_id: Optional[UUID] = None

    # -> TRANSPORT_ARRANGED
    transport_mode: Optional[str] = None

    # -> ARRIVED (proof: either one satisfies the requirement)
    arrival_confirmed_by: Optional[UUID] = None
    arrival_scan_ref: Optional[str] = None

    # -> CONSULTED (GAP: metadata-only, no `referral` column)
    consulted_by_user_id: Optional[UUID] = None

    # -> BACK_REFERRED
    back_referral_note: Optional[str] = None

    # -> TRACED (GAP: metadata-only, no `referral` column)
    traced_by_user_id: Optional[UUID] = None

    # -> REFUSED / LOST / CANCELLED
    refusal_reason: Optional[RefusalReason] = None
    loss_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None


# Field name -> extractor from the body, for the generic required-field
# check driven by TRANSITION_REQUIRED_FIELDS. ARRIVED is deliberately
# NOT in this map -- it has its own, more specific ARRIVAL_PROOF_REQUIRED
# handling (see _apply_transition), not the generic
# TRANSITION_FIELD_REQUIRED path.
_FIELD_GETTERS = {
    "slot_datetime": lambda b: b.slot_datetime,
    "destination_org_unit_id": lambda b: b.destination_org_unit_id,
    "transport_mode": lambda b: b.transport_mode,
    "consulted_by_user_id": lambda b: b.consulted_by_user_id,
    "back_referral_note": lambda b: b.back_referral_note,
    "traced_by_user_id": lambda b: b.traced_by_user_id,
    "refusal_reason": lambda b: b.refusal_reason,
    "loss_reason": lambda b: b.loss_reason,
    "cancellation_reason": lambda b: b.cancellation_reason,
}

# GAP fields (see module docstring): destination for the transition's
# extra metadata, never a `referral` column.
_METADATA_ONLY_FIELDS = {"consulted_by_user_id", "traced_by_user_id"}


# SHAPE NOTE, found while wiring this in and deliberately resolved, not
# silently mismatched: the task's own illustrative JSON for these errors
# shows a top-level `{"error": {...}}` body. That is NOT what this
# codebase actually produces for ANY existing error today -- every route
# in this repo raises `HTTPException(status, {...dict...})`, and
# FastAPI's own default exception handler always wraps that second
# argument under a top-level `"detail"` key (confirmed directly: e.g.
# app/api/routes/patients.py's PHONE_REQUIRED, app/api/routes/triage.py's
# INVALID_PROTOCOL, and tests/test_existing_endpoints.py's own
# `r.json()["detail"]["code"] == "PHONE_REQUIRED"` assertion). Nesting an
# extra `"error"` key inside the dict passed to HTTPException would
# therefore produce `{"detail": {"error": {...}}}` -- a NEW, doubly-
# nested shape not used anywhere else in this project, and not what
# either reading of the spec's own example actually intends. Per this
# task's own "reuse this repo's existing patterns, don't invent a second
# way" instruction, these helpers return the flat fields dict directly
# (code/message/detail/current_status/requested_status/allowed_next/
# request_id, or code/message/field/current_status/requested_status/
# request_id) as HTTPException's own `detail=`, so the real response
# body is `{"detail": {"code": ..., ...}}` -- same wrapping convention as
# every other error in this codebase, just with more fields than the
# older ones had.
def _transition_error(code: str, message: str, current: ReferralState,
                       requested: ReferralState, allowed: set, request_id: str) -> dict:
    allowed_list = _ordered_values(allowed)
    if allowed_list:
        detail = f"A referral in {current.value} can move to: {', '.join(allowed_list)}."
    else:
        detail = f"A referral in {current.value} is in a terminal state and cannot move to any other stage."
    return {
        "code": code,
        "message": message,
        "detail": detail,
        "current_status": current.value,
        "requested_status": requested.value,
        "allowed_next": allowed_list,
        "request_id": request_id,
    }


def _field_required_error(code: str, message: str, field: str, current: ReferralState,
                           requested: ReferralState, request_id: str) -> dict:
    return {
        "code": code,
        "message": message,
        "field": field,
        "current_status": current.value,
        "requested_status": requested.value,
        "request_id": request_id,
    }


def _apply_transition(
    referral: Referral, requested: ReferralState, body: ReferralStatusUpdateBody,
    current: ReferralState, request_id: str, now: datetime,
) -> dict:
    """STEP 4 (required-field enforcement) + STEP 5 (side effects),
    combined since a field can't be applied before it's been validated
    as present. Mutates `referral` in place. Returns the metadata dict
    to be written onto the referral_transitions row for this transition
    (GAP fields + anything else worth keeping in the history that has no
    first-class column). Raises HTTPException(422, ...) on any missing
    required field, fail-closed."""
    metadata: dict = {}

    # ---- ARRIVED: specific proof requirement, not the generic path ----
    if requested == ReferralState.ARRIVED:
        if body.arrival_confirmed_by is None and body.arrival_scan_ref is None:
            # Same flat-dict-as-`detail` convention as _transition_error/
            # _field_required_error above -- see that comment for why
            # this is not wrapped in an extra "error" key.
            raise HTTPException(422, {
                "code": "ARRIVAL_PROOF_REQUIRED",
                "message": "Arrival must be confirmed by a named staff member (manual entry) "
                           "or by an ABHA scan reference. Neither was provided.",
                "current_status": current.value,
                "requested_status": requested.value,
                "request_id": request_id,
            })
        referral.arrival_confirmed_by = body.arrival_confirmed_by
        referral.arrival_scan_ref = body.arrival_scan_ref
        referral.arrived_at = now
        # "STOPS the breach clock": the only breach-tracking machinery
        # that exists today is `idx_referrals_breach ON referral(status,
        # due_at) WHERE breached_at IS NULL` (migration d4f1c9b7a582) --
        # a partial index for an external breach-detection job, not part
        # of this route. That job is expected to filter on `status`
        # (pre-arrival states) as well as the index's own WHERE clause;
        # once `status` leaves those pre-arrival states (this
        # transition), the referral naturally falls out of that job's
        # own query. There is no separate "clock" column to zero out --
        # `breached_at` itself is deliberately left as-is (if the
        # referral was already breached before arriving, that fact isn't
        # erased by finally arriving late).
        return metadata

    # ---- generic required-field enforcement, TRANSITION_REQUIRED_FIELDS ----
    for field_name in TRANSITION_REQUIRED_FIELDS.get(requested, []):
        getter = _FIELD_GETTERS[field_name]
        value = getter(body)
        if value is None:
            raise HTTPException(422, _field_required_error(
                "TRANSITION_FIELD_REQUIRED",
                f"'{field_name}' is required to move this referral to {requested.value}.",
                field_name, current, requested, request_id,
            ))
        if field_name in _METADATA_ONLY_FIELDS:
            # GAP fields -- no `referral` column; see module docstring.
            metadata[field_name] = str(value)

    # ---- side effects, per BEHAVIOUR table ----
    if requested == ReferralState.SLOT_BOOKED:
        referral.slot_datetime = body.slot_datetime
        # SUBSTITUTION (see module docstring): destination_org_unit_id ->
        # the existing destination_facility_id column.
        referral.destination_facility_id = body.destination_org_unit_id
        referral.breached_at = None
    elif requested == ReferralState.TRANSPORT_ARRANGED:
        referral.transport_mode = body.transport_mode
    elif requested == ReferralState.CONSULTED:
        pass  # consulted_by_user_id already captured into `metadata` above (GAP)
    elif requested == ReferralState.BACK_REFERRED:
        referral.back_referral_note = body.back_referral_note
        referral.back_referred_at = now
    elif requested == ReferralState.CLOSED:
        referral.closed_at = now
    elif requested == ReferralState.NOT_ARRIVED:
        # not_arrived_at has no `referral` column (GAP) -- metadata only.
        metadata["not_arrived_at"] = now.isoformat()
        referral.escalation_stage = 1
    elif requested == ReferralState.TRACED:
        pass  # traced_by_user_id already captured into `metadata` above (GAP)
    elif requested == ReferralState.REFUSED:
        referral.refusal_reason = body.refusal_reason.value if body.refusal_reason else None
    elif requested == ReferralState.LOST:
        referral.loss_reason = body.loss_reason
    elif requested == ReferralState.CANCELLED:
        referral.cancellation_reason = body.cancellation_reason
    elif requested == ReferralState.RESCHEDULED:
        # D2-S8: was a hardcoded `now + timedelta(days=7)` (a second,
        # independent due-date calculation living outside the shared
        # rule). Now calls the SAME compute_due_at used at referral
        # creation (app/services/referral/breach.py) -- "ONE shared rule
        # used by both the read path and a background job" extends here
        # too: no route may independently recompute a due-date window.
        # "restarts the clock from the reschedule time" -- `now` (the
        # reschedule instant), not `referral.initiated_at` (the original
        # creation instant), is the base passed in.
        referral.breached_at = None
        referral.due_at = compute_due_at(now, referral.urgency)

    return metadata


@router.patch("/{referral_id}/status")
# No response_model here (unlike POST / above, which keeps response_model=
# Referral unchanged): response_model=Referral would silently strip the
# additive `allowed_next` field this task requires (STEP 8) since
# FastAPI's response_model filtering only serializes fields declared on
# the model. Every existing field this endpoint used to return is still
# returned -- `Referral.model_dump()` below includes all of them
# unchanged -- this only removes the automatic *filtering*, not any
# field.
def update_referral_status(
    referral_id: UUID,
    status: ReferralState = Query(...),
    body: Optional[ReferralStatusUpdateBody] = Body(default=None),
    current_user=Depends(require("referral:update_status")),
    session: Session = Depends(get_session),
):
    request_id = str(uuid4())
    body = body or ReferralStatusUpdateBody()

    # ------------------------------------------------------------
    # STEP 1 -- AuthN (require() dependency already ran) + scope check
    # on the referral's own org_unit_id.
    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # STEP 2 -- load the referral, read current status.
    # ------------------------------------------------------------
    referral = session.get(Referral, referral_id)
    if not referral or not org_unit_is_within_scope(session, referral.org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(status_code=404, detail="Referral not found")

    current_status = referral.status if isinstance(referral.status, ReferralState) else ReferralState(referral.status)
    requested_status = status

    # ------------------------------------------------------------
    # STEP 3 -- transition guard.
    # ------------------------------------------------------------
    try:
        assert_transition_allowed(current_status, requested_status)
    except InvalidTransition as exc:
        code = "TERMINAL_STATE" if current_status in TERMINAL_STATES else "INVALID_TRANSITION"
        message = (
            "This referral is already in a final stage and cannot be updated further."
            if code == "TERMINAL_STATE" else
            "This referral cannot move to that stage yet."
        )
        raise HTTPException(409, _transition_error(
            code, message, current_status, requested_status, exc.allowed, request_id,
        ))

    # ------------------------------------------------------------
    # STEP 4 + 5 -- required-field enforcement and side effects.
    # ------------------------------------------------------------
    now = datetime.now(timezone.utc)
    extra_metadata = _apply_transition(referral, requested_status, body, current_status, request_id, now)

    old_status_value = current_status.value
    referral.status = requested_status

    session.add(referral)
    session.commit()
    session.refresh(referral)

    # ------------------------------------------------------------
    # STEP 6 -- append-only referral_transitions row, every transition.
    # ------------------------------------------------------------
    _write_transition(
        session, referral_id=referral.id, from_status=old_status_value,
        to_status=requested_status.value, actor_user_id=current_user.id,
        actor_role=current_user.role, reason=body.reason, metadata=extra_metadata,
    )

    # ------------------------------------------------------------
    # STEP 7 -- audit.
    # ------------------------------------------------------------
    _write_audit(session, actor_user_id=str(current_user.id), action="REFERRAL_STATUS_CHANGED", outcome="SUCCESS",
                 target_type="REFERRAL", target_id=str(referral.id),
                 metadata={"from": old_status_value, "to": requested_status.value, **extra_metadata})
    session.commit()
    # Same expire_on_commit note as create_referral above.
    session.refresh(referral)

    # ------------------------------------------------------------
    # STEP 8 -- response: existing fields UNCHANGED, plus additive
    # `allowed_next` for the referral's NEW status.
    # ------------------------------------------------------------
    response = referral.model_dump()
    response["allowed_next"] = _ordered_values(ALLOWED_TRANSITIONS.get(requested_status, set()))
    return response
