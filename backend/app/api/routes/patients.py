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

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, text

from app.core.authz import org_unit_is_within_scope, require
from app.core.crypto import blind_index, encrypt_field, mask_mobile
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
    if not patient.phone:
        # Deliberate, user-confirmed contract change -- see module
        # docstring point 1. backend/docs/API_CONTRACT.md amended to match.
        raise HTTPException(422, {"code": "PHONE_REQUIRED",
                                   "detail": "phone is required to register a patient."})
    if current_user.scope_org_unit_id is None:
        raise HTTPException(403, {"code": "OUT_OF_SCOPE",
                                   "detail": "Your account has no posting to attribute this record to."})

    # Never trust client-supplied attribution fields, even though they
    # exist on the model now (see app/models/patient.py's own note).
    patient.created_by_user_id = current_user.id
    patient.org_unit_id = current_user.scope_org_unit_id

    session.add(patient)
    session.commit()
    session.refresh(patient)

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
    # Found by testing: SQLAlchemy's default expire_on_commit=True means
    # this second commit (the first happens right after the initial
    # insert, to get an id for the identity-linking work above) expires
    # `patient`'s cached attributes -- response_model serialization would
    # otherwise return an empty body. Re-refresh before returning.
    session.refresh(patient)
    return patient


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
        raise HTTPException(status_code=404, detail="Patient not found")

    _write_audit(session, actor_user_id=str(current_user.id), action="PATIENT_PHI_READ", outcome="SUCCESS",
                 target_type="PATIENT", target_id=str(patient.id))
    session.commit()
    # Same expire_on_commit note as create_patient above.
    session.refresh(patient)

    return patient
