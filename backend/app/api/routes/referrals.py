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
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select, text

from app.core.authz import org_unit_is_within_scope, require
from app.db.database import get_session
from app.models import Patient, Referral
from app.services.escalation.factory import get_escalation_engine
from app.services.escalation.fallback import resolve_escalation_target
from app.services.escalation.port import EscalationInput
from app.services.referral.breach import compute_due_at, is_breached, normalize_urgency
from app.models.referral_state import (
    ALLOWED_TRANSITIONS,
    COMPLETED_STATES,
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


# ===========================================================================
# GET /referrals/exceptions -- new, additive (C1: does not touch any of the
# nine frozen endpoints or POST // PATCH .../status above). require(
# "referral:read"), always scope-filtered.
#
# THIS ROUTE'S OWN GAPS/DECISIONS -- every one flagged per this task's own
# instruction ("investigate and handle explicitly, don't silently guess"),
# not buried in a commit message:
#
# 1. Patient.sex: app/models/patient.py has NO `sex` column at all (checked
#    directly, not assumed -- the model has id/name/age/village/phone/
#    facility_id/created_at/client_uuid/created_by_user_id/org_unit_id and
#    nothing else). `patient.sex` in the response is therefore always
#    `null`, not invented data and not a crash.
#
# 2. `age_years`: the only age data that exists is `Patient.age` (a bare
#    int, no unit ever recorded beyond "age" itself). Mapped straight across
#    as `age_years` -- a field-name reconciliation, not a new value.
#
# 3. `from_facility_id`/`destination_facility_id` carry NO foreign key to
#    org_units (checked directly against every referral migration -- see
#    79a9d8f8db61's original `CREATE TABLE referral` and d4f1c9b7a582's own
#    docstring, neither adds one). They are free-standing UUIDs; the test
#    fixtures in this very repo (tests/test_breach_detection.py's own
#    `_make_referral`) populate them with plain `uuid.uuid4()` values that
#    reference nothing at all. Best-effort lookup, documented, not a crash:
#    try `org_units` first (id -> name), then fall back to the pre-existing
#    `facility` table (id -> name) for whatever isn't found there, then
#    `name: null` for anything found in neither. `origin_org_unit`/
#    `destination_org_unit` are named per this task's own spec even though
#    the underlying id may resolve to a `facility` row, not an `org_units`
#    row -- the spec's field names are kept, the lookup is just honest
#    about where the name actually came from (or that it couldn't be found).
#
# 4. `scope=mine` is not defined anywhere in Day1.md (which has no
#    escalation-dashboard spec at all) or in this task's own text beyond
#    "pick the most defensible reading". Resolved as: referrals whose
#    `owner_user_id` equals the caller's own id. This is ADDITIONAL
#    narrowing on top of -- never a replacement for -- the mandatory
#    "always filter to caller's own org subtree" baseline: a referral
#    reassigned away from the caller's own scope (e.g. after a transfer)
#    never leaks back in just because `owner_user_id` still matches.
#
# 5. `scope=facility` vs `scope=block`: also not literally defined.
#    Resolved using this repo's own org-unit hierarchy (STATE > DISTRICT >
#    DISTRICT_OFFICE > BLOCK > {PHC/CHC/HWC/SDH/DISTRICT_HOSPITAL/
#    TELE_HUB} > SUB_CENTRE > VILLAGE -- see tests/_fixtures.py's own
#    hierarchy docstring): `scope=block` (the default) is the caller's
#    FULL subtree (everything at or below their own posting -- the
#    baseline scope-containment rule with nothing extra narrowed);
#    `scope=facility` narrows to an EXACT match on the caller's own
#    posting only, no descendants (e.g. a BMO posted at a BLOCK sees only
#    referrals attributed to that exact BLOCK org_unit_id, not the PHCs
#    under it). If `org_unit_id` is also supplied, it takes precedence
#    over `scope`'s own org-unit narrowing (see point 6); `scope=mine`
#    still composes on top of either.
#
# 6. `org_unit_id` (drill-down): validated with the same
#    `org_unit_is_within_scope` gate used everywhere else in this codebase
#    -- out of scope -> 404 FACILITY_NOT_IN_SCOPE, never 403 (an attacker
#    probing facility ids must not be able to tell "exists elsewhere" from
#    "doesn't exist" -- app.core.authz's own module docstring). When
#    supplied, it REPLACES `scope`'s own org-unit dimension (filtering to
#    that target unit's own subtree, not the caller's whole one) --
#    `scope=mine` still applies on top if also given.
#
# 7. `stage` filters against the LIVE, per-request escalation output's own
#    `.stage` -- the exact same value returned in each item's
#    `escalation.stage` field -- not the persisted `referral.
#    escalation_stage` DB column (which is the background job's last-known
#    snapshot, not necessarily equal to what the engine would say about
#    the current instant `now`). "What you can filter on is what you see
#    in the response" was picked as the more defensible reading; flagged
#    here since the query param name doesn't itself say which one.
#
# 8. `summary` (breached/at_risk/total_open/breach_rate) is computed over
#    the SCOPE + org_unit_id + urgency-filtered set of open referrals --
#    i.e. before `breach_only`/`stage` narrow the exceptions view further.
#    `urgency` genuinely changes "the universe under consideration" (a
#    manager filtering to EMERGENCY-only wants the rate computed over
#    EMERGENCY referrals only); `breach_only`/`stage` are drill-downs on
#    an already-defined universe, and letting them shrink the denominator
#    too would make e.g. `breach_only=true` trivially report a 100% rate
#    every time, which is not a useful number.
#
# 9. Sort is server-fixed (a `sort` query param is accepted for
#    forward-compatibility but always ignored -- documented, not silently
#    dropped): EMERGENCY urgency first, then `overdue_hours` descending
#    (0.0 for anything not yet breached, so already-breached rows always
#    sort ahead of not-yet-breached ones within the same urgency tier).
#    THIS TASK'S OWN INSTRUCTION to "pick and document a sensible
#    secondary order for not-yet-breached rows" is resolved as: among rows
#    tied at `overdue_hours == 0.0`, break the tie by `due_at` ASCENDING
#    (the referral closest to breaching is shown first) -- this is this
#    route's own choice, not given verbatim anywhere.
#
# 10. Scope containment is always computed from a FRESH `org_units.path`
#     lookup (never from the possibly-stale `users.scope_path` cache
#     column), matching `org_unit_is_within_scope`'s own "always re-check
#     against the live table" philosophy.
#
# 11. An actor with NO posting at all (`current_user.scope_org_unit_id IS
#     NULL` -- true for every SUPERUSER, per `chk_scope_required`) is not
#     given special treatment here the way Gate 3/Gate 4 give SUPERUSER an
#     explicit creation-time exemption (app.core.authz). Day1.md does not
#     define what a scoped EXCEPTIONS LIST should show a SUPERUSER, and
#     `org_unit_is_within_scope` itself fails closed to False for a None
#     actor scope. Resolved here, fail-closed (C3): no posting -> an empty
#     result (`items: []`, all summary counts 0) for the base list, and a
#     404 FACILITY_NOT_IN_SCOPE for ANY `org_unit_id` drill-down (since
#     `org_unit_is_within_scope` can never return True for a None actor
#     scope either). This never crashes and never silently shows
#     everything; flagged here as a genuine product decision for the human
#     to confirm, not a guess buried in code.
#
# 12. A referral with `due_at IS NULL` (should not occur for any row
#     created after D2-S8, but older/malformed data is handled, not
#     trusted to be clean) is counted in `total_open`, is never breached
#     and never at_risk (both require a real `due_at`), and gets a
#     documented no-op escalation object ("cannot be evaluated") instead
#     of calling the engine with a missing required field.
#
# 13. `at_risk` with a malformed window (`due_at <= initiated_at`) is
#     treated as NOT at-risk rather than raising a ZeroDivision/negative-
#     window error or guessing a fallback percentage -- there is nothing
#     sensible to compute a "25% of window" against.
#
# 14. `breached_at` in each item is the PERSISTED `referral.breached_at`
#     column -- the background job's (app/jobs/breach_detection.py) own
#     snapshot of when it first detected the breach -- not something this
#     route stamps itself. This route's own "is this row breached right
#     now" decision (used for `breach_only`, `summary.breached`, and sort
#     order) is the LIVE `is_breached()` call, exactly like the job's own
#     "single source of truth" rule (app/services/referral/breach.py's own
#     docstring). The two can legitimately disagree for a short window:
#     a referral can satisfy `is_breached()` right now and still show
#     `breached_at: null` here if the background job simply hasn't run
#     since it crossed its `due_at` yet. This route deliberately does NOT
#     write `breached_at` itself -- doing so would give this read-only
#     route a second, competing writer for a column app/jobs/
#     breach_detection.py already owns exclusively. `overdue_hours > 0`
#     (not `breached_at IS NOT NULL`) is the reliable per-item signal that
#     a row is currently breached by this route's own reckoning.
# ===========================================================================

def _org_unit_path(session: Session, org_unit_id: Optional[UUID]) -> Optional[str]:
    if org_unit_id is None:
        return None
    row = session.exec(
        text("SELECT path FROM org_units WHERE id = :id"), params={"id": str(org_unit_id)}
    ).first()
    return row[0] if row else None


def _overdue_hours(referral: Referral, now: datetime) -> float:
    if referral.due_at is None:
        return 0.0
    delta_hours = (now - referral.due_at).total_seconds() / 3600.0
    return round(max(0.0, delta_hours), 1)


def _is_at_risk(referral: Referral, breached: bool, now: datetime) -> bool:
    """Open, not breached, time-remaining <= 25% of window (window =
    due_at - initiated_at). See point 13 above for the malformed-window
    fallback."""
    if breached or referral.due_at is None:
        return False
    window = referral.due_at - referral.initiated_at
    if window <= timedelta(0):
        return False
    remaining = referral.due_at - now
    return remaining <= (window * 0.25)


@router.get("/exceptions")
def list_referral_exceptions(
    scope: str = Query(default="block", pattern="^(block|facility|mine)$"),
    urgency: Optional[str] = Query(default=None, description="Comma-separated, e.g. EMERGENCY,URGENT"),
    stage: Optional[str] = Query(default=None, description="Comma-separated integers, e.g. 1,2,3"),
    breach_only: bool = Query(default=False),
    org_unit_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: Optional[str] = Query(default=None, description="Accepted but always ignored -- see route docstring point 9."),
    current_user=Depends(require("referral:read")),
    session: Session = Depends(get_session),
):
    now = datetime.now(timezone.utc)

    # ---- STEP 1: resolve the caller's own current scope path. Point 11. ----
    actor_path = _org_unit_path(session, current_user.scope_org_unit_id)
    if current_user.scope_org_unit_id is None or actor_path is None:
        empty_summary = {
            "breached": 0, "at_risk": 0, "total_open": 0,
            "breach_rate": {"numerator": 0, "denominator": 0, "rate_pct": 0.0},
        }
        return {"summary": empty_summary, "items": [],
                "pagination": {"limit": limit, "offset": offset, "total": 0}}

    # ---- STEP 2: org_unit_id drill-down -- validate scope, 404 not 403. ----
    # Point 6.
    effective_path = actor_path
    if org_unit_id is not None:
        if not org_unit_is_within_scope(session, org_unit_id, current_user.scope_org_unit_id):
            raise HTTPException(404, {"code": "FACILITY_NOT_IN_SCOPE", "detail": "Not found."})
        target_path = _org_unit_path(session, org_unit_id)
        # org_unit_is_within_scope already proved this org unit exists and
        # is reachable, so target_path cannot be None here.
        effective_path = target_path

    path_prefix = effective_path.rstrip("/") + "/%"

    # ---- STEP 3: base query -- open referrals, joined to org_units for
    # the path-prefix scope check (mirrors org_unit_is_within_scope's own
    # trailing-slash-safe logic, at the SQL level so this is one query,
    # not one org_unit_is_within_scope() call per row). Point 10. ----
    org_units_tbl = sa.table("org_units", sa.column("id"), sa.column("path"))
    non_open_statuses = list(COMPLETED_STATES) + [ReferralState.CANCELLED]

    stmt = (
        select(Referral)
        .join(org_units_tbl, org_units_tbl.c.id == Referral.org_unit_id)
        .where(Referral.status.not_in(non_open_statuses))
        .where(sa.or_(org_units_tbl.c.path == effective_path, org_units_tbl.c.path.like(path_prefix)))
    )

    # scope=facility: exact match on the caller's own posting only, no
    # descendants -- only meaningful when org_unit_id hasn't already
    # pinned a different (narrower or equal) target. Point 5.
    if scope == "facility" and org_unit_id is None:
        stmt = stmt.where(Referral.org_unit_id == current_user.scope_org_unit_id)

    # scope=mine: additional narrowing, composes with everything above.
    # Point 4.
    if scope == "mine":
        stmt = stmt.where(Referral.owner_user_id == current_user.id)

    if urgency:
        wanted_urgencies = {normalize_urgency(u) for u in urgency.split(",") if u.strip()}
        if wanted_urgencies:
            stmt = stmt.where(sa.func.upper(sa.func.trim(Referral.urgency)).in_(wanted_urgencies))

    stage_filter: Optional[set[int]] = None
    if stage:
        try:
            stage_filter = {int(s) for s in stage.split(",") if s.strip() != ""}
        except ValueError:
            raise HTTPException(422, {"code": "INVALID_STAGE",
                                       "detail": "stage must be a comma-separated list of integers."})

    candidates = session.exec(stmt).all()

    # ---- STEP 4: batch-fetch related rows -- no per-row queries. ----
    patient_ids = {r.patient_id for r in candidates}
    owner_ids = {r.owner_user_id for r in candidates if r.owner_user_id is not None}
    facility_ids: set = set()
    for r in candidates:
        facility_ids.add(r.from_facility_id)
        facility_ids.add(r.destination_facility_id)

    patients_by_id: dict = {}
    if patient_ids:
        for p in session.exec(select(Patient).where(Patient.id.in_(patient_ids))).all():
            patients_by_id[p.id] = p

    users_tbl = sa.table("users", sa.column("id"), sa.column("full_name"), sa.column("role"))
    owners_by_id: dict = {}
    if owner_ids:
        rows = session.exec(
            select(users_tbl.c.id, users_tbl.c.full_name, users_tbl.c.role)
            .where(users_tbl.c.id.in_(owner_ids))
        ).all()
        for row_id, row_name, row_role in rows:
            owners_by_id[row_id] = {"user_id": str(row_id), "name": row_name, "role": row_role}

    # Point 3: best-effort org_units -> facility fallback lookup.
    org_units_lookup_tbl = sa.table("org_units", sa.column("id"), sa.column("name"))
    facility_lookup_tbl = sa.table("facility", sa.column("id"), sa.column("name"))
    facility_names: dict = {}
    if facility_ids:
        rows = session.exec(
            select(org_units_lookup_tbl.c.id, org_units_lookup_tbl.c.name)
            .where(org_units_lookup_tbl.c.id.in_(facility_ids))
        ).all()
        for row_id, row_name in rows:
            facility_names[row_id] = row_name
        remaining = facility_ids - set(facility_names.keys())
        if remaining:
            rows2 = session.exec(
                select(facility_lookup_tbl.c.id, facility_lookup_tbl.c.name)
                .where(facility_lookup_tbl.c.id.in_(remaining))
            ).all()
            for row_id, row_name in rows2:
                facility_names[row_id] = row_name

    # ---- STEP 5: per-candidate breach/at-risk (pure, no DB) + summary. ----
    enriched = []
    for r in candidates:
        breached = is_breached(r, now)
        at_risk = _is_at_risk(r, breached, now)
        enriched.append({
            "referral": r, "breached": breached, "at_risk": at_risk,
            "overdue_hours": _overdue_hours(r, now),
        })

    total_open = len(enriched)
    breached_count = sum(1 for e in enriched if e["breached"])
    at_risk_count = sum(1 for e in enriched if e["at_risk"])
    rate_pct = round((breached_count / total_open) * 100, 1) if total_open else 0.0
    summary = {
        "breached": breached_count, "at_risk": at_risk_count, "total_open": total_open,
        "breach_rate": {"numerator": breached_count, "denominator": total_open, "rate_pct": rate_pct},
    }

    if breach_only:
        enriched = [e for e in enriched if e["breached"]]

    # ---- STEP 6: escalation engine, wired via the port/factory seam.
    # Point 7: resolve_escalation_target is called HERE (a real session),
    # never inside the fallback engine itself -- that's the whole point of
    # wiring it in at the route. ----
    engine = get_escalation_engine()
    resolve_cache: dict = {}

    def _compute_escalation(referral: Referral) -> dict:
        if referral.due_at is None:
            return {
                "stage": 0, "escalate_to_role": None, "escalate_to_user_id": None,
                "due_action_at": None,
                "message": "No due_at is set for this referral; escalation cannot be evaluated.",
                "engine": engine.name,
            }
        status_value = referral.status.value if isinstance(referral.status, ReferralState) else referral.status
        out = engine.escalate(EscalationInput(
            urgency=referral.urgency, initiated_at=referral.initiated_at, due_at=referral.due_at,
            now=now, current_stage=referral.escalation_stage, owner_user_id=referral.owner_user_id,
            status=status_value,
        ))
        escalate_to_user_id = out.escalate_to_user_id
        if out.escalate_to_role and escalate_to_user_id is None:
            cache_key = (referral.owner_user_id, out.escalate_to_role)
            if cache_key not in resolve_cache:
                resolve_cache[cache_key] = resolve_escalation_target(
                    session, referral.owner_user_id, out.escalate_to_role
                )
            escalate_to_user_id = resolve_cache[cache_key]
        return {
            "stage": out.stage, "escalate_to_role": out.escalate_to_role,
            "escalate_to_user_id": str(escalate_to_user_id) if escalate_to_user_id else None,
            "due_action_at": out.due_action_at.isoformat() if out.due_action_at else None,
            "message": out.message, "engine": out.engine,
        }

    # stage filtering needs the live escalation stage BEFORE pagination,
    # so it must be computed eagerly for the whole (already breach_only-
    # filtered) candidate set in that case. Otherwise it's deferred to
    # just the final page (point 7 + avoiding unnecessary
    # resolve_escalation_target DB walks for rows that won't be returned).
    if stage_filter is not None:
        for e in enriched:
            e["escalation"] = _compute_escalation(e["referral"])
        enriched = [e for e in enriched if e["escalation"]["stage"] in stage_filter]

    # ---- STEP 7: sort (server-fixed, point 9) -- client `sort` ignored. ----
    def _sort_key(e: dict):
        urgency_norm = normalize_urgency(e["referral"].urgency)
        emergency_first = 0 if urgency_norm == "EMERGENCY" else 1
        due_at = e["referral"].due_at or datetime.max.replace(tzinfo=timezone.utc)
        return (emergency_first, -e["overdue_hours"], due_at)

    enriched.sort(key=_sort_key)

    total = len(enriched)
    page = enriched[offset: offset + limit]

    for e in page:
        if "escalation" not in e:
            e["escalation"] = _compute_escalation(e["referral"])

    # ---- STEP 8: build the response. ----
    items = []
    for e in page:
        r = e["referral"]
        patient = patients_by_id.get(r.patient_id)
        owner = owners_by_id.get(r.owner_user_id) if r.owner_user_id else None
        current_status = r.status if isinstance(r.status, ReferralState) else ReferralState(r.status)
        items.append({
            "referral_id": str(r.id),
            "patient": {
                "id": str(patient.id) if patient else str(r.patient_id),
                "name": patient.name if patient else None,
                "age_years": patient.age if patient else None,  # point 2
                "sex": None,  # point 1 -- Patient has no `sex` column
            },
            "reason": r.reason,
            "urgency": r.urgency,
            "status": current_status.value,
            "allowed_next": _ordered_values(ALLOWED_TRANSITIONS.get(current_status, set())),
            "origin_org_unit": {"id": str(r.from_facility_id), "name": facility_names.get(r.from_facility_id)},
            "destination_org_unit": {
                "id": str(r.destination_facility_id), "name": facility_names.get(r.destination_facility_id),
            },
            "initiated_at": r.initiated_at.isoformat() if r.initiated_at else None,
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "breached_at": r.breached_at.isoformat() if r.breached_at else None,
            "overdue_hours": e["overdue_hours"],
            "escalation": e["escalation"],
            "owner": owner,
            "needs_owner": r.owner_user_id is None,
        })

    _write_audit(
        session, actor_user_id=str(current_user.id), action="REFERRAL_EXCEPTIONS_READ", outcome="SUCCESS",
        target_type="REFERRAL", target_id=None,
        metadata={"scope": scope, "org_unit_id": str(org_unit_id) if org_unit_id else None,
                  "urgency": urgency, "stage": stage, "breach_only": breach_only,
                  "returned": len(items), "total": total},
    )
    session.commit()

    return {
        "summary": summary,
        "items": items,
        "pagination": {"limit": limit, "offset": offset, "total": total},
    }
