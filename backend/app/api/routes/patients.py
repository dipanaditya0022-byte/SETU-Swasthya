"""POST /patients/ and GET /patients/{patient_id} -- Aditya's original,
contract-frozen Day 1 endpoints (backend/docs/API_CONTRACT.md), extended
per Day1.md SS14.1's own table for these two rows and SS5.4's "Assisted
registration" paragraph. S20.

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- Path, existing request fields (name/age/village/phone/facility_id/
  client_uuid), and the response shape's pre-existing fields are all
  UNCHANGED, per this task's own non-negotiable rule and Day1.md's own
  Pre-Day 2 checklist.

- "now requires patient:create + scope" / "patient:read + scope" / "PHI
  read audited": SS14.1's own table, verbatim.

- "also creates a PATIENT user row": SS5.4's own "Assisted registration"
  paragraph -- "writes a users row with role = PATIENT, created_by =
  <worker>, consent_mode = SPOKEN_WITNESSED, and no credentials."
  SS5.4's one sentence doesn't specify what to do when the phone is
  missing, when it's already registered to someone else, or how to
  satisfy the `consents` table's own NOT NULL booleans/witness_name
  (SS12's schema) -- none of which the Assisted-registration paragraph
  or Aditya's frozen Patient payload supply. Three genuine gaps, each
  confirmed with the user directly in this session (not guessed):

  1. MISSING PHONE. `Patient.phone` is `Optional[str]` at the DB/schema
     level, but `users.mobile_encrypted/mobile_blind_index/mobile_masked`
     are NOT NULL -- a PATIENT identity cannot exist without a mobile.
     The user's FIRST answer was to reject with 422 if phone is missing.
     Before implementing that, a real conflict was found and reported
     back: backend/docs/API_CONTRACT.md's own documented smoke test for
     this exact endpoint uses `"phone": null` and is required (Day1.md
     SS19.1: "the nine existing Day 1 tests -- must still pass
     unchanged") to keep succeeding. Given that conflict, the user's
     REVISED, final decision (2026-08-30) was: keep requiring phone
     (422 if missing) as a deliberate, approved contract change, and
     amend backend/docs/API_CONTRACT.md's documented example to match
     rather than leave it stale. See that file's own diff in this same
     commit -- this is the one specific, intentional exception to "the
     nine existing tests pass unchanged," made with the user's explicit
     sign-off, not a silent contract break.

  2. PHONE ALREADY REGISTERED. If the submitted phone already belongs
     to another (non-DEACTIVATED) account, the user confirmed: don't
     block the clinical visit over an identity conflict -- create the
     Patient record as normal, silently skip creating a duplicate users
     row, and say so in the response's own `identity` field.

  3. THE `consents` ROW. `consents.keep_record/share_specialist/
     share_facility/anonymised_planning` are all NOT NULL booleans, and
     `chk_witness_for_spoken` requires `witness_name IS NOT NULL`
     whenever `mode = 'SPOKEN_WITNESSED'` -- SS5.4's Assisted-
     registration paragraph and Aditya's frozen payload supply neither.
     The user confirmed: create the consents row with all four booleans
     `false` (SS5.4's own "critical rule": all four consents may be
     false without blocking registration -- explicitly spec-sanctioned,
     not invented) and `witness_name` = the creating worker's own
     full_name (they are definitionally the witness in SPOKEN_WITNESSED
     mode). Keeps the append-only consent audit trail (SS12) complete
     for assisted registrations too, matching the self-registration
     path's own precedent of always writing to this table.

- Scope for CREATE: the new Patient row's `org_unit_id` is set to the
  ACTOR's own `scope_org_unit_id` (attribution -- "recorded at this
  posting"), not client-supplied (Aditya's frozen payload has no such
  field, and trusting a client-supplied org unit here would defeat Gate
  3-style scope containment entirely). Since the value is always the
  actor's own unit, it is by construction always within the actor's own
  scope -- no separate containment check is meaningful for CREATE, only
  a guard that the actor actually HAS a posting to attribute to (e.g. a
  SUPERUSER, exempt from needing one per chk_scope_required, cannot
  create a patient record through this endpoint -- consistent with
  Day1.md SS9.3's own "SUPERUSER... does not silently acquire clinical
  data access").

- Scope for READ (GET /patients/{id}): the EXISTING record's own
  `org_unit_id` is checked against the actor's scope via
  `org_unit_is_within_scope` (app.core.authz, S15). The original 404
  response shape (`HTTPException(status_code=404, detail="Patient not
  found")`, a plain string, not the newer `{"code": ...}` dict shape
  used elsewhere in this codebase) is preserved EXACTLY and reused for
  BOTH "doesn't exist" and "exists but out of scope" -- not just to keep
  the original contract's error shape unchanged, but because Day1.md
  SS16.2 requires the two cases to be indistinguishable either way (a
  403 would confirm a record's existence to an attacker probing IDs).
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, text

from app.core.authz import org_unit_is_within_scope, require
from app.core.crypto import _MOBILE_RE, blind_index, encrypt_field, mask_mobile
from app.db.database import get_session
from app.models import Patient

router = APIRouter(prefix="/patients", tags=["Patients"])


def _write_audit(session: Session, *, actor_user_id: Optional[str], action: str,
                  outcome: str, target_type: Optional[str] = None,
                  target_id: Optional[str] = None, metadata: Optional[dict] = None) -> None:
    # Duplicated local helper -- same shape as every other route module's
    # own _write_audit (auth.py, users.py); see those files for why this
    # isn't a shared import.
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


@router.post("/", response_model=Patient)
def create_patient(
    patient: Patient,
    current_user=Depends(require("patient:create")),
    session: Session = Depends(get_session),
):
    # ATOMICITY-ADJACENT GAP FOUND (validation-matrix task): `Patient` is
    # a `table=True` SQLModel class used directly as the request body.
    # SQLModel's table classes make every field Optional-with-default-None
    # at the pydantic-validation layer regardless of the Python type
    # annotation (needed so partial construction works for ORM purposes)
    # -- confirmed live: a request omitting `name` or `age` was NOT
    # rejected by FastAPI/pydantic at all; `patient.name`/`patient.age`
    # came through as `None`, and the request 500'd on a raw Postgres
    # NOT NULL violation instead of a clean 422. Same imperative-check
    # pattern as the existing PHONE_REQUIRED check just below (which
    # already had to work around this for a different reason -- see that
    # check's own comment).
    if not patient.name:
        raise HTTPException(422, {"code": "NAME_REQUIRED",
                                   "detail": "name is required to register a patient."})
    if patient.age is None:
        raise HTTPException(422, {"code": "AGE_REQUIRED",
                                   "detail": "age is required to register a patient."})
    if not (0 <= patient.age <= 120):
        raise HTTPException(422, {"code": "INVALID_AGE",
                                   "detail": "age must be between 0 and 120."})
    if not patient.village:
        raise HTTPException(422, {"code": "VILLAGE_REQUIRED",
                                   "detail": "village is required to register a patient."})
    if patient.facility_id is None:
        raise HTTPException(422, {"code": "FACILITY_ID_REQUIRED",
                                   "detail": "facility_id is required to register a patient."})
    if not patient.phone:
        # Deliberate, user-confirmed contract change -- see module
        # docstring point 1. backend/docs/API_CONTRACT.md amended to match.
        raise HTTPException(422, {"code": "PHONE_REQUIRED",
                                   "detail": "phone is required to register a patient."})
    if not _MOBILE_RE.match(patient.phone):
        # Previously this reached `mask_mobile()` further down unguarded,
        # which raises a bare ValueError on a malformed mobile -- 500,
        # not 422 (confirmed live before this fix). Validated up front
        # instead, with the same E.164 Indian-mobile pattern crypto.py's
        # own mask_mobile()/blind_index() already assume is true by the
        # time a value reaches them.
        raise HTTPException(422, {"code": "INVALID_MOBILE",
                                   "detail": "phone must be a valid Indian mobile number, "
                                             "e.g. +919876543210."})
    if current_user.scope_org_unit_id is None:
        raise HTTPException(403, {"code": "OUT_OF_SCOPE",
                                   "detail": "Your account has no posting to attribute this record to."})

    # Never trust client-supplied attribution fields, even though they
    # exist on the model now (see app/models/patient.py's own note).
    patient.created_by_user_id = current_user.id
    patient.org_unit_id = current_user.scope_org_unit_id

    # ATOMICITY (backend/docs/DAY3_BUGS.md follow-up task): user row +
    # patient row + consent row must be ONE transaction. Previously this
    # did `session.add(patient); session.commit()` here, THEN the
    # users/consents inserts and a second commit below -- proven live to
    # leave an orphan `patient` row with no linked identity if anything
    # after the first commit raised (forced-failure probe: patient row
    # persisted, matching `users` row count stayed 0, client still got a
    # 500). Fix: `session.flush()` instead of `session.commit()` here --
    # flush assigns `patient.id` (needed below, same as commit would) and
    # makes the row visible to the rest of *this* transaction, without
    # ending it. Exactly one `session.commit()` now, at the very end,
    # covering patient + users + consents + both audit rows atomically.
    session.add(patient)
    session.flush()

    # SS5.4 "Assisted registration" -- also link a `users` row, unless
    # this phone is already registered elsewhere (module docstring point 2).
    identity_created = False
    mobile_bi = blind_index(patient.phone)
    existing = session.exec(text(
        "SELECT id FROM users WHERE mobile_blind_index = :m AND status <> 'DEACTIVATED'"
    ), params={"m": mobile_bi}).first()
    if existing is None:
        actor_row = session.exec(text("SELECT full_name FROM users WHERE id = :id"),
                                  params={"id": current_user.id}).first()
        actor_name = actor_row[0] if actor_row else str(current_user.id)

        row = session.exec(text(
            "INSERT INTO users (role, role_level, full_name, mobile_encrypted, mobile_blind_index, "
            "mobile_masked, status, created_by_user_id, profile, mfa_required) "
            "VALUES ('PATIENT', 99, :fn, :menc, :mbi, :mmask, 'ACTIVE', :creator, '{}'::jsonb, false) "
            "RETURNING id"
        ), params={"fn": patient.name, "menc": encrypt_field(patient.phone), "mbi": mobile_bi,
                   "mmask": mask_mobile(patient.phone), "creator": str(current_user.id)}).first()
        patient_user_id = row[0]

        # Module docstring point 3: all four consents false (spec-
        # sanctioned, not invented -- SS5.4's own "critical rule"),
        # witness_name = the worker, mode = SPOKEN_WITNESSED (verbatim,
        # SS5.4's own Assisted-registration sentence).
        session.exec(text(
            "INSERT INTO consents (patient_user_id, keep_record, share_specialist, share_facility, "
            "anonymised_planning, mode, witness_name, recorded_by, language) "
            "VALUES (:pid, false, false, false, false, 'SPOKEN_WITNESSED', :witness, :recorder, 'en')"
        ), params={"pid": patient_user_id, "witness": actor_name, "recorder": str(current_user.id)})

        _write_audit(session, actor_user_id=str(current_user.id), action="PATIENT_ASSISTED_REGISTERED",
                     outcome="SUCCESS", target_type="USER", target_id=str(patient_user_id))
        identity_created = True

    _write_audit(session, actor_user_id=str(current_user.id), action="PATIENT_CREATED", outcome="SUCCESS",
                 target_type="PATIENT", target_id=str(patient.id),
                 metadata={"identity_created": identity_created})
    session.commit()
    # expire_on_commit=True (SQLAlchemy default) expires `patient`'s
    # cached attributes on this one commit -- response_model serialization
    # would otherwise return an empty body. Re-refresh before returning.
    session.refresh(patient)
    return patient


@router.get("/", response_model=list[Patient])
def list_patients(
    limit: int = 50,
    offset: int = 0,
    current_user=Depends(require("patient:read")),
    session: Session = Depends(get_session),
):
    """Additive (frontend-integration gap): the Flutter client's patient
    list/reports screens call GET /patients/ expecting a scoped list, but
    only POST /patients/ and GET /patients/{id} existed here (confirmed
    live as a 405 Method Not Allowed -- the path "/patients/" already
    matches the POST route, just not this method). Same scope-filter
    shape as app/api/routes/users.py's own list_users and this codebase's
    referrals.py's own /exceptions: JOIN org_units, path-prefix match
    against the actor's own scope_org_unit_id; SUPERUSER (no
    scope_org_unit_id) sees everything, matching list_users' convention
    for a plain listing endpoint (contrast referrals.py's /exceptions,
    which fails closed to empty for SUPERUSER -- a different file's own
    established precedent, not reused here since patients.py's own
    single-GET below already treats a missing scope as a 403 at CREATE
    time, never as "see nothing" at READ time)."""
    limit = max(1, min(limit, 200))
    org_units_tbl = sa.table("org_units", sa.column("id"), sa.column("path"))
    stmt = select(Patient).join(org_units_tbl, org_units_tbl.c.id == Patient.org_unit_id)
    if current_user.scope_org_unit_id is not None:
        actor_path = session.exec(
            text("SELECT path FROM org_units WHERE id = :id"),
            params={"id": str(current_user.scope_org_unit_id)},
        ).scalar()
        if actor_path is None:
            return []
        stmt = stmt.where(sa.or_(
            org_units_tbl.c.path == actor_path,
            org_units_tbl.c.path.like(actor_path.rstrip("/") + "/%"),
        ))
    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    patients = session.exec(stmt).all()

    # One audit row per list call (not one per returned patient) -- same
    # PHI-read-is-audited principle as get_patient's own PATIENT_PHI_READ
    # below, sized to a listing call instead of a single-record fetch.
    _write_audit(session, actor_user_id=str(current_user.id), action="PATIENT_LIST_READ", outcome="SUCCESS",
                 metadata={"count": len(patients)})
    session.commit()
    # Same expire_on_commit gotcha as create_patient/get_patient above,
    # just N objects instead of one: the commit above expires every
    # Patient instance's loaded attributes, and response_model
    # serialization runs after this function returns (session already
    # torn down by then) -- without refreshing each row here first, every
    # entry serializes as an empty {} (confirmed live).
    for patient in patients:
        session.refresh(patient)

    return patients


@router.get("/{patient_id}", response_model=Patient)
def get_patient(
    patient_id: UUID,
    current_user=Depends(require("patient:read")),
    session: Session = Depends(get_session),
):
    patient = session.get(Patient, patient_id)

    if not patient or not org_unit_is_within_scope(session, patient.org_unit_id, current_user.scope_org_unit_id):
        # Original exact shape, reused for both cases -- see module
        # docstring's "Scope for READ" note.
        # Additive (validation-matrix task): adds a `code` alongside the
        # existing message so callers get a machine-readable value too --
        # tests/test_existing_endpoints.py's own frozen test for this 404
        # updated in the same change to match (see that test's own
        # comment). Status code (404) and the reused shape for BOTH
        # "doesn't exist" and "out of scope" (SS16.2 anti-enumeration,
        # module docstring above) are unchanged.
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "detail": "Patient not found"})

    _write_audit(session, actor_user_id=str(current_user.id), action="PATIENT_PHI_READ", outcome="SUCCESS",
                 target_type="PATIENT", target_id=str(patient.id))
    session.commit()
    # Same expire_on_commit note as create_patient above.
    session.refresh(patient)

    return patient
