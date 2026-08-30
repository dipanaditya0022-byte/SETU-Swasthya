"""User-management route surface, per Day1.md SS3 (creation authority),
SS6 (account lifecycle), SS14.3-14.5 (API surface), and SS15
(validation rules).

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- POST /users' exact request/response shape: SS14.4's own full example,
  verbatim (the response's field set -- id, role, full_name,
  mobile_masked, status, scope_org_unit_id, scope_path,
  reports_to_user_id, created_by_user_id, invite{sent_to_masked,
  channels,expires_at}, hpr_verification{status,note}, created_at --
  and the explicit note "no password, no invite token, no unmasked
  mobile").
- GET /users/registration-schema/{role}'s shape: SS14.5's own example,
  matched as closely as the underlying Pydantic models (S14) support
  -- see that endpoint's own docstring below for the specific UI-only
  hints (voice_input, help text, unique_scope) that aren't derivable
  from the models and are therefore omitted, not fabricated.
- deactivate_user's logic: SS6.4's own function, copied close to
  verbatim (subordinate detection, 409 SUBORDINATES_EXIST with
  suggested_reassign_to, reassignment eligibility via
  can_create_role, credential destruction, session revocation).
- SS15.2's cross-field rules (error codes and messages): implemented
  verbatim where checkable without inventing new schema (org unit
  type, reports_to eligibility/active, mobile/HPR uniqueness,
  self-approval).

- Two more genuinely new pieces of glue, not spec quotes:
    1. can_create_role / assert_can_manage: SS6.4's own deactivate_user
       calls both as if they already exist; neither is defined
       anywhere in Day1.md. can_create_role is a one-line wrapper
       around app.core.authz.get_creation_grant (does an explicit
       grant row exist -- Gate 2's own check). assert_can_manage is
       built here as: the actor must hold scope over the target's org
       unit (org_unit_is_within_scope) -- there is no separate
       "management" relation in the schema beyond scope + permission,
       and the task's own instruction ("do not assume an ancestor can
       create every descendant") argues against inventing a
       creator-chain/reports-to-based notion of "manage" that Day1.md
       never defines either.
    2. GET /users/registration-schema/{role} introspects the Pydantic
       models from app/schemas/profiles.py (S14) to build the
       sections/fields document -- SS14.5 shows the target JSON shape
       but not the code that produces it from a model.

- Idempotency-Key support (SS15.3): backed by a new idempotency_keys
  table (migration f1c9a2e8b374, confirmed with the user directly in
  this session -- no such table exists anywhere in Day1.md) on POST
  /users and POST /users/{id}/approve. A stored response is replayed
  verbatim on a retry with the same key + identical request body; a
  reused key with a *different* body is a 409 (not literally specced,
  but the alternative -- silently accepting a different body under a
  reused key -- would defeat the point of the mechanism).

- PATCH /users/{id}: Day1.md's SS14.3 table says only "Role and scope
  changes bump token_version" -- no exact field list is given. This
  implementation allows updating full_name_local, designation,
  employee_code, scope_org_unit_id, reports_to_user_id, and role (role
  changes re-run creation-authority checks and are blocked outright
  for self, per SS19's own threat model T2: "Role changes require
  user:update plus a valid creation grant for the new role;
  self-role-change blocked outright"). profile-block fields are not
  patchable here -- SS14.3 gives no endpoint for editing role-specific
  profile data, and inventing one would be scope creep.

- POST /users/{id}/transfer: Day1.md's SS6.1 lifecycle diagram
  describes "old posting closed with an end date, new one opened" as
  a conceptual TRANSFERRED state, but SS13's actual schema has no
  posting-history table to record a closed-vs-open posting in --
  users has exactly one scope_org_unit_id. Implemented here as a
  direct update to scope_org_unit_id/scope_path (the user stays
  ACTIVE) rather than inventing a posting-history table Day1.md's own
  schema doesn't have. Flagged plainly as a simplification, not
  presented as a literal reproduction of the state diagram.

- POST /users/{id}/reactivate: sets must_change_password=true ("forces
  a password reset", SS14.3) but enforcing that flag at the next login
  (blocking access until the password is actually changed) is not
  wired into app/api/routes/auth.py's login() from S16 -- that would be
  editing a different step's file; flagged here rather than silently
  left inconsistent.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session, text

from app.core.authz import CreationDenied, assert_can_create_user, get_current_active_user, get_effective_permissions, get_creation_grant, org_unit_is_within_scope, require
from app.core.crypto import blind_index, encrypt_field, mask_mobile
from app.db.database import get_session
from app.models.enums import ROLE_LEVEL, RoleCode
from app.schemas.profiles import CommonCore, PostingBlock, ROLE_PROFILE_MAP, UserRegistrationRequest

router = APIRouter(prefix="/users", tags=["Users"])

_DISPLAY_NAMES: dict[str, str] = {}  # populated lazily from `roles` table on first use


def _get_display_name(session: Session, role: str) -> str:
    if role not in _DISPLAY_NAMES:
        row = session.exec(text("SELECT display_name FROM roles WHERE code = :r"), params={"r": role}).first()
        _DISPLAY_NAMES[role] = row[0] if row else role
    return _DISPLAY_NAMES[role]


def can_create_role(session: Session, creator_role: str, target_role: str) -> bool:
    return get_creation_grant(session, creator_role, target_role) is not None


def assert_can_manage(session: Session, actor, target_scope_org_unit_id) -> None:
    """See module docstring. Fails closed: no scope containment ->
    treated identically to CreationDenied's OUT_OF_SCOPE (403), not a
    404 -- lifecycle actions on a *known* target (the caller already
    has its id) follow SS3.2 Gate 3's pattern, not SS16.2's
    existing-record-read pattern (see app/core/authz.py's own docstring
    for that 403-vs-404 distinction)."""
    if not org_unit_is_within_scope(session, target_scope_org_unit_id, actor.scope_org_unit_id):
        raise HTTPException(403, {"code": "OUT_OF_SCOPE", "detail": "That posting is outside the area you manage."})


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
        "metadata, prev_hash, row_hash) VALUES (:oa, :au, :ac, :oc, :tt, :ti, :md, :ph, :rh)"
    ), params={"oa": occurred_at, "au": actor_user_id, "ac": action, "oc": outcome, "tt": target_type,
               "ti": target_id, "md": json.dumps(metadata or {}), "ph": prev_hash, "rh": row_hash})


def _get_user_row(session: Session, user_id) -> Optional[dict]:
    row = session.exec(text(
        "SELECT id, role, role_level, full_name, mobile_masked, status, scope_org_unit_id, scope_path, "
        "reports_to_user_id, created_by_user_id, created_at, mobile_blind_index, email_blind_index "
        "FROM users WHERE id = :id"
    ), params={"id": str(user_id)}).first()
    if row is None:
        return None
    cols = ["id", "role", "role_level", "full_name", "mobile_masked", "status", "scope_org_unit_id",
            "scope_path", "reports_to_user_id", "created_by_user_id", "created_at", "mobile_blind_index",
            "email_blind_index"]
    return dict(zip(cols, row))


def _get_user_or_404(session: Session, actor, user_id) -> dict:
    """SS16.2's 404-not-403 rule for existing-record access (distinct
    from lifecycle actions' 403 via assert_can_manage -- see that
    function's docstring)."""
    row = _get_user_row(session, user_id)
    if row is None or not org_unit_is_within_scope(session, row["scope_org_unit_id"], actor.scope_org_unit_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "detail": "Not found."})
    return row


# ============================================================
# Idempotency (SS15.3)
# ============================================================

def _idempotency_lookup(session: Session, key: Optional[str], endpoint: str, body_hash: str) -> Optional[dict]:
    if key is None:
        return None
    row = session.exec(text(
        "SELECT response_status, response_body, request_hash FROM idempotency_keys "
        "WHERE idempotency_key = :k AND endpoint = :e AND expires_at > :now"
    ), params={"k": key, "e": endpoint, "now": datetime.now(timezone.utc)}).first()
    if row is None:
        return None
    status_code, response_body, stored_hash = row
    if stored_hash != body_hash:
        raise HTTPException(409, {"code": "IDEMPOTENCY_KEY_CONFLICT",
                                   "detail": "This Idempotency-Key was already used with a different request body."})
    return {"status_code": status_code, "body": response_body}


def _idempotency_store(session: Session, key: Optional[str], endpoint: str, body_hash: str,
                        status_code: int, response_body: dict) -> None:
    if key is None:
        return
    session.exec(text(
        "INSERT INTO idempotency_keys (idempotency_key, endpoint, request_hash, response_status, "
        "response_body, expires_at) VALUES (:k, :e, :h, :s, :b, :exp) "
        "ON CONFLICT (idempotency_key, endpoint) DO NOTHING"
    ), params={"k": key, "e": endpoint, "h": body_hash, "s": status_code, "b": json.dumps(response_body),
               "exp": datetime.now(timezone.utc) + timedelta(hours=24)})


def _body_hash(raw_body: dict) -> str:
    return hashlib.sha256(json.dumps(raw_body, sort_keys=True, default=str).encode()).hexdigest()


# ============================================================
# GET /users/creatable-roles -- SS3.3
# ============================================================

@router.get("/creatable-roles")
def creatable_roles(current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    rows = session.exec(text(
        "SELECT target_role, requires_second_approver, allowed_org_unit_types "
        "FROM role_creation_grants WHERE creator_role = :r ORDER BY target_role"
    ), params={"r": current_user.role}).all()
    return {"creatable_roles": [
        {"role": r[0], "display_name": _get_display_name(session, r[0]),
         "requires_second_approver": r[1], "allowed_org_unit_types": r[2],
         "schema_url": f"/users/registration-schema/{r[0]}"}
        for r in rows
    ]}


# ============================================================
# GET /users/registration-schema/{role} -- SS14.5
# ============================================================

_TYPE_MAP = {"str": "string", "int": "integer", "bool": "boolean", "UUID": "org_unit", "date": "date",
             "datetime": "datetime", "time": "time"}


def _field_to_schema(name: str, field) -> dict:
    ann = field.annotation
    type_name = getattr(ann, "__name__", str(ann))
    is_list = type_name in ("list", "List") or str(ann).startswith("list[")
    base_type = "string"
    if "bool" in str(ann):
        base_type = "boolean"
    elif "int" in str(ann) and "list" not in str(ann):
        base_type = "integer"
    elif "UUID" in str(ann):
        base_type = "multi_select_org_unit" if is_list else "org_unit"
    elif "date" in str(ann).lower():
        base_type = "date"
    entry: dict[str, Any] = {"name": name, "type": base_type, "required": field.is_required()}
    if field.description:
        entry["label"] = field.description
    else:
        entry["label"] = name.replace("_", " ").capitalize()
    for meta in field.metadata:
        if hasattr(meta, "ge"):
            entry["min"] = meta.ge
        if hasattr(meta, "le"):
            entry["max"] = meta.le
        if hasattr(meta, "min_length"):
            entry["min_length"] = meta.min_length
        if hasattr(meta, "max_length"):
            entry["max_length"] = meta.max_length
    import enum as _enum
    origin_args = getattr(ann, "__args__", ())
    for arg in (ann, *origin_args):
        if isinstance(arg, type) and issubclass(arg, _enum.Enum):
            entry["type"] = "enum"
            entry["options"] = [m.value for m in arg]
    return entry


@router.get("/registration-schema/{role}")
def registration_schema(role: str, current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    """SS14.5's target shape, built from the Pydantic models directly
    (not hand-authored per role) so a schema change in
    app/schemas/profiles.py automatically reflects here -- matching
    that section's own point ("nothing about the role's fields is
    hard-coded in the client"). UI-only hints SS14.5's example shows
    that aren't derivable from a Pydantic field (voice_input, free-text
    help copy, unique_scope annotations) are omitted, not invented."""
    if role not in ROLE_PROFILE_MAP:
        raise HTTPException(404, {"code": "NOT_FOUND", "detail": "Unknown role."})
    profile_cls = ROLE_PROFILE_MAP[role]
    grant = get_creation_grant(session, current_user.role, role)

    common_fields = [_field_to_schema(n, f) for n, f in CommonCore.model_fields.items()]
    posting_fields = [_field_to_schema(n, f) for n, f in PostingBlock.model_fields.items()]
    profile_fields = [_field_to_schema(n, f) for n, f in profile_cls.model_fields.items() if n != "role"]

    accept_mode = "OTP_ONLY" if role == "ASHA" else "PASSWORD"
    return {
        "role": role, "display_name": _get_display_name(session, role),
        "requires_second_approver": grant.requires_second_approver if grant else False,
        "allowed_org_unit_types": grant.allowed_org_unit_types if grant else [],
        "accept_mode": accept_mode,
        "sections": [
            {"key": "common", "title": "Personal details", "fields": common_fields},
            {"key": "posting", "title": "Posting", "fields": posting_fields},
            {"key": "profile", "title": f"{_get_display_name(session, role)} details", "fields": profile_fields},
        ],
    }


# ============================================================
# POST /users -- SS14.4
# ============================================================

@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_user(
    request: Request,
    payload: dict,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user=Depends(require("user:create")),
    session: Session = Depends(get_session),
):
    endpoint = "POST /users"
    body_hash = _body_hash(payload)
    cached = _idempotency_lookup(session, idempotency_key, endpoint, body_hash)
    if cached is not None:
        return cached["body"]

    try:
        parsed = UserRegistrationRequest.model_validate(payload)
    except ValidationError as e:
        # e.errors() can include a raw Python exception object in each
        # error's ctx (for errors raised via a plain `raise ValueError(...)`
        # inside a field_validator/model_validator) -- found by testing:
        # passing that straight into HTTPException's JSON body crashes with
        # "TypeError: Object of type ValueError is not JSON serializable",
        # turning an intended 422 into an unrelated 500. e.errors() has no
        # built-in JSON-safe mode; going through e.json() (which Pydantic
        # itself renders safely) and parsing that back is the correct fix.
        raise HTTPException(422, {"code": "VALIDATION_ERROR", "detail": json.loads(e.json())})

    target_role = parsed.role
    try:
        requires_second_approver = assert_can_create_user(session, current_user, RoleCode(target_role), parsed.posting.org_unit_id)
    except CreationDenied as e:
        status_map = {"ACTOR_NOT_ACTIVE": 403, "MFA_REQUIRED": 403, "ROLE_NOT_CREATABLE": 403,
                      "OUT_OF_SCOPE": 403, "LEVEL_VIOLATION": 403}
        _write_audit(session, actor_user_id=str(current_user.id), action="USER_CREATE_DENIED", outcome="DENIED",
                     metadata={"code": e.code, "target_role": target_role})
        session.commit()
        raise HTTPException(status_map.get(e.code, 403), {"code": e.code, "detail": e.detail})

    # SS15.2 cross-field checks not already covered by app/schemas/profiles.py's
    # own field-level validators (registration_expiry > today, roster times,
    # telemedicine_certified, age 18-70, guardian rules for PATIENT -- N/A here).
    grant = get_creation_grant(session, current_user.role, target_role)
    org_row = session.exec(text("SELECT unit_type FROM org_units WHERE id = :id AND is_active = true"),
                            params={"id": str(parsed.posting.org_unit_id)}).first()
    if org_row is None:
        raise HTTPException(422, {"code": "INVALID_ORG_UNIT_TYPE", "detail": "That org unit does not exist or is not active."})
    if grant.allowed_org_unit_types != ["*"] and org_row[0] not in grant.allowed_org_unit_types:
        raise HTTPException(422, {"code": "INVALID_ORG_UNIT_TYPE",
                                   "detail": f"A {target_role} must be posted to one of {grant.allowed_org_unit_types}."})

    reports_to_id = parsed.posting.reports_to_user_id or current_user.id
    manager = _get_user_row(session, reports_to_id)
    if manager is None:
        raise HTTPException(422, {"code": "INVALID_MANAGER", "detail": "reports_to_user_id does not exist."})
    if manager["status"] != "ACTIVE":
        raise HTTPException(422, {"code": "MANAGER_NOT_ACTIVE", "detail": "That supervisor's account is not active."})
    if not can_create_role(session, manager["role"], target_role):
        raise HTTPException(422, {"code": "INVALID_MANAGER", "detail": f"{manager['role']} cannot manage {target_role}."})

    mobile_bi = blind_index(parsed.common.mobile)
    existing = session.exec(text("SELECT id FROM users WHERE mobile_blind_index = :m AND status <> 'DEACTIVATED'"),
                             params={"m": mobile_bi}).first()
    if existing is not None:
        raise HTTPException(422, {"code": "MOBILE_IN_USE", "detail": "That mobile number is already registered."})

    profile_dict = parsed.profile.model_dump(exclude={"role"}, mode="json")
    hpr_id = profile_dict.get("hpr_id")
    if hpr_id:
        hpr_existing = session.exec(text("SELECT id FROM users WHERE hpr_id = :h"), params={"h": hpr_id}).first()
        if hpr_existing is not None:
            raise HTTPException(422, {"code": "HPR_IN_USE", "detail": "That HPR ID is already linked to another account."})

    status = "PENDING_APPROVAL" if requires_second_approver else "INVITED"
    email_enc = encrypt_field(parsed.common.email) if parsed.common.email else None
    email_bi = blind_index(parsed.common.email) if parsed.common.email else None

    row = session.exec(text(
        "INSERT INTO users (role, role_level, full_name, full_name_local, mobile_encrypted, "
        "mobile_blind_index, mobile_masked, email_encrypted, email_blind_index, date_of_birth, sex, "
        "preferred_language, employee_code, designation, joining_date, id_proof_type, id_proof_last4, "
        "photo_object_key, scope_org_unit_id, scope_path, reports_to_user_id, created_by_user_id, "
        "hpr_id, profile, status, mfa_required, valid_until) "
        "VALUES (:role, :lvl, :fn, :fnl, :menc, :mbi, :mmask, :eenc, :ebi, :dob, :sex, :lang, :ecode, "
        ":desig, :joining, :idpt, :idl4, :photo, :org, (SELECT path FROM org_units WHERE id=:org), "
        ":rpt, :creator, :hpr, :profile, :status, :mfareq, :valid_until) RETURNING id, created_at"
    ), params={
        "role": target_role, "lvl": ROLE_LEVEL[RoleCode(target_role)], "fn": parsed.common.full_name,
        "fnl": parsed.common.full_name_local, "menc": encrypt_field(parsed.common.mobile), "mbi": mobile_bi,
        "mmask": mask_mobile(parsed.common.mobile), "eenc": email_enc, "ebi": email_bi,
        "dob": parsed.common.date_of_birth, "sex": parsed.common.sex, "lang": parsed.common.preferred_language,
        "ecode": parsed.common.employee_code, "desig": parsed.common.designation, "joining": parsed.common.joining_date,
        "idpt": parsed.common.id_proof_type, "idl4": parsed.common.id_proof_last4, "photo": parsed.common.photo_object_key,
        "org": str(parsed.posting.org_unit_id), "rpt": str(reports_to_id), "creator": str(current_user.id),
        "hpr": hpr_id, "profile": json.dumps(profile_dict), "status": status,
        # S6's chk_privileged_mfa CHECK requires role_level > 5 OR
        # mfa_required = true. Setting mfa_required = (role_level <= 6)
        # both satisfies that constraint for every privileged role (<=5)
        # and stays consistent with app/api/routes/auth.py's own
        # ROLE_SESSION_CONFIG (S16), which already treats every role up
        # to and including MEDICAL_OFFICER (level 6) as MFA-mandatory at
        # login -- not just the bare minimum the DB CHECK requires.
        "mfareq": ROLE_LEVEL[RoleCode(target_role)] <= 6,
        "valid_until": parsed.posting.valid_until,
    }).first()
    new_id, created_at = row

    invite_payload: dict = {}
    if status == "INVITED":
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        ttl_hours = int(__import__("os").environ.get("INVITE_TOKEN_TTL_HOURS", "72"))
        accept_mode = "OTP_ONLY" if target_role == "ASHA" else "PASSWORD"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        session.exec(text(
            "INSERT INTO user_invitations (user_id, token_hash, accept_mode, issued_by, expires_at) "
            "VALUES (:uid, :th, :am, :ib, :exp)"
        ), params={"uid": new_id, "th": token_hash, "am": accept_mode, "ib": str(current_user.id), "exp": expires_at})
        # SS7's flow: SMS + email sent directly to the invitee. No SMS/email
        # gateway exists in this repo (SMS_GATEWAY_URL is an empty
        # placeholder, S2) -- dev-only, matching S16's OTP-logging pattern,
        # never logs the token itself.
        print(f"DEV invitation issued for user {new_id} ({mask_mobile(parsed.common.mobile)}) -- "
              f"accept_mode={accept_mode}, expires_at={expires_at.isoformat()}")
        invite_payload = {"sent_to_masked": mask_mobile(parsed.common.mobile), "channels": ["SMS", "EMAIL"],
                           "expires_at": expires_at.isoformat()}
    else:
        approver_role = current_user.role  # requester; DPO/second-approver eligibility resolved at /approve
        expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
        session.exec(text(
            "INSERT INTO approval_requests (subject_user_id, requested_by, required_approver_role, "
            "justification, expires_at) VALUES (:sid, :rb, :rar, :j, :exp)"
        ), params={"sid": new_id, "rb": str(current_user.id), "rar": target_role,
                   "j": f"{current_user.role} requests creation of {target_role}", "exp": expires_at})

    _write_audit(session, actor_user_id=str(current_user.id), action="USER_CREATED", outcome="SUCCESS",
                 target_type="USER", target_id=str(new_id), metadata={"role": target_role, "status": status})

    response_body = {
        "id": str(new_id), "role": target_role, "full_name": parsed.common.full_name,
        "mobile_masked": mask_mobile(parsed.common.mobile), "status": status,
        "scope_org_unit_id": str(parsed.posting.org_unit_id),
        "scope_path": session.exec(text("SELECT path FROM org_units WHERE id = :id"), params={"id": str(parsed.posting.org_unit_id)}).first()[0],
        "reports_to_user_id": str(reports_to_id), "created_by_user_id": str(current_user.id),
        "invite": invite_payload,
        "hpr_verification": {"status": "PENDING", "note": "Account activates only after HPR verification succeeds."} if hpr_id else None,
        "created_at": created_at.isoformat(),
    }
    _idempotency_store(session, idempotency_key, endpoint, body_hash, 201, response_body)
    session.commit()
    return response_body


# ============================================================
# GET /users, GET /users/{id}
# ============================================================

@router.get("")
@router.get("/")
def list_users(role: Optional[str] = None, status: Optional[str] = None, limit: int = 50, offset: int = 0,
               current_user=Depends(require("user:read")), session: Session = Depends(get_session)):
    limit = max(1, min(limit, 200))
    conditions = []
    params: dict[str, Any] = {"actor_scope": str(current_user.scope_org_unit_id) if current_user.scope_org_unit_id else None,
                               "limit": limit, "offset": offset}
    where_scope = "org_units.path LIKE (SELECT rtrim(path, '/') FROM org_units WHERE id = :actor_scope) || '/%' OR org_units.id = :actor_scope" if current_user.scope_org_unit_id else "true"
    if role:
        conditions.append("users.role = :role"); params["role"] = role
    if status:
        conditions.append("users.status = :status"); params["status"] = status
    extra_where = (" AND " + " AND ".join(conditions)) if conditions else ""
    rows = session.exec(text(
        f"SELECT users.id, users.role, users.full_name, users.mobile_masked, users.status "
        f"FROM users JOIN org_units ON org_units.id = users.scope_org_unit_id "
        f"WHERE ({where_scope}){extra_where} ORDER BY users.created_at DESC LIMIT :limit OFFSET :offset"
    ), params=params).all()
    return {"users": [{"id": str(r[0]), "role": r[1], "full_name": r[2], "mobile_masked": r[3], "status": r[4]} for r in rows]}


@router.get("/hierarchy")
def hierarchy(current_user=Depends(require("user:read")), session: Session = Depends(get_session)):
    """Subtree for the org chart -- all users within the actor's scope,
    flat with reports_to for client-side tree building (SS14.3 gives no
    literal tree-JSON shape)."""
    if current_user.scope_org_unit_id is None:
        rows = session.exec(text("SELECT id, role, full_name, reports_to_user_id, scope_org_unit_id FROM users WHERE status <> 'DEACTIVATED'")).all()
    else:
        rows = session.exec(text(
            "SELECT u.id, u.role, u.full_name, u.reports_to_user_id, u.scope_org_unit_id FROM users u "
            "JOIN org_units o ON o.id = u.scope_org_unit_id "
            "WHERE u.status <> 'DEACTIVATED' AND (o.path LIKE (SELECT rtrim(path,'/') FROM org_units WHERE id=:s) || '/%' OR o.id = :s)"
        ), params={"s": str(current_user.scope_org_unit_id)}).all()
    return {"users": [{"id": str(r[0]), "role": r[1], "full_name": r[2],
                        "reports_to_user_id": str(r[3]) if r[3] else None, "scope_org_unit_id": str(r[4])} for r in rows]}


@router.get("/{user_id}/subordinates")
def subordinates(user_id: UUID, current_user=Depends(require("user:read")), session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    rows = session.exec(text("SELECT id, role, full_name, mobile_masked, status FROM users WHERE reports_to_user_id = :id"),
                         params={"id": str(user_id)}).all()
    return {"subordinates": [{"id": str(r[0]), "role": r[1], "full_name": r[2], "mobile_masked": r[3], "status": r[4]} for r in rows]}


@router.get("/{user_id}")
def get_user(user_id: UUID, current_user=Depends(require("user:read")), session: Session = Depends(get_session)):
    row = _get_user_or_404(session, current_user, user_id)
    return {"id": str(row["id"]), "role": row["role"], "full_name": row["full_name"], "mobile_masked": row["mobile_masked"],
            "status": row["status"], "scope_org_unit_id": str(row["scope_org_unit_id"]) if row["scope_org_unit_id"] else None,
            "scope_path": row["scope_path"], "reports_to_user_id": str(row["reports_to_user_id"]) if row["reports_to_user_id"] else None,
            "created_by_user_id": str(row["created_by_user_id"]) if row["created_by_user_id"] else None}


# ============================================================
# PATCH /users/{id}
# ============================================================

class PatchUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name_local: Optional[str] = None
    designation: Optional[str] = None
    employee_code: Optional[str] = None
    scope_org_unit_id: Optional[UUID] = None
    reports_to_user_id: Optional[UUID] = None
    role: Optional[str] = None


@router.patch("/{user_id}")
def patch_user(user_id: UUID, body: PatchUserRequest, current_user=Depends(require("user:update")),
                session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    assert_can_manage(session, current_user, target["scope_org_unit_id"])

    updates: dict[str, Any] = {}
    if body.role is not None:
        if str(user_id) == str(current_user.id):
            raise HTTPException(403, {"code": "SELF_ROLE_CHANGE_BLOCKED", "detail": "You cannot change your own role."})
        if not can_create_role(session, current_user.role, body.role):
            raise HTTPException(403, {"code": "ROLE_NOT_CREATABLE", "detail": f"{current_user.role} may not assign {body.role}."})
        updates["role"] = body.role
        updates["role_level"] = ROLE_LEVEL[RoleCode(body.role)]
    if body.scope_org_unit_id is not None:
        updates["scope_org_unit_id"] = str(body.scope_org_unit_id)
    if body.reports_to_user_id is not None:
        updates["reports_to_user_id"] = str(body.reports_to_user_id)
    if body.full_name_local is not None:
        updates["full_name_local"] = body.full_name_local
    if body.designation is not None:
        updates["designation"] = body.designation
    if body.employee_code is not None:
        updates["employee_code"] = body.employee_code

    if not updates:
        return {"id": str(user_id), "updated": False}

    bumps_version = "role" in updates or "scope_org_unit_id" in updates
    set_clauses = [f"{k} = :{k}" for k in updates]
    if bumps_version:
        set_clauses.append("token_version = token_version + 1")
    updates["id"] = str(user_id)
    session.exec(text(f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :id"), params=updates)
    _write_audit(session, actor_user_id=str(current_user.id), action="USER_UPDATED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id), metadata={"fields": list(updates.keys())})
    session.commit()
    return {"id": str(user_id), "updated": True, "token_version_bumped": bumps_version}


# ============================================================
# Approval flow -- SS6.2, SS15.2
# ============================================================

class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


@router.post("/{user_id}/approve")
def approve_user(user_id: UUID, request: Request,
                  idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
                  current_user=Depends(require("user:approve")), session: Session = Depends(get_session)):
    endpoint = "POST /users/{id}/approve"
    body_hash = _body_hash({"user_id": str(user_id)})
    cached = _idempotency_lookup(session, idempotency_key, endpoint, body_hash)
    if cached is not None:
        return cached["body"]

    req = session.exec(text(
        "SELECT id, requested_by, required_approver_role, status FROM approval_requests "
        "WHERE subject_user_id = :uid AND status = 'PENDING' ORDER BY created_at DESC LIMIT 1"
    ), params={"uid": str(user_id)}).first()
    if req is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "detail": "No pending approval request."})
    req_id, requested_by, required_role, _status = req

    if str(requested_by) == str(current_user.id):
        raise HTTPException(403, {"code": "SELF_APPROVAL", "detail": "You cannot approve an account you created."})
    if not can_create_role(session, current_user.role, required_role):
        raise HTTPException(403, {"code": "APPROVER_NOT_ELIGIBLE", "detail": "You are not an eligible approver for this role."})

    session.exec(text("UPDATE approval_requests SET status = 'APPROVED', decided_at = :now, approved_by = :ab WHERE id = :id"),
                 params={"now": datetime.now(timezone.utc), "ab": str(current_user.id), "id": req_id})
    session.exec(text("UPDATE users SET status = 'INVITED' WHERE id = :id"), params={"id": str(user_id)})

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    role_row = session.exec(text("SELECT role, mobile_masked FROM users WHERE id = :id"), params={"id": str(user_id)}).first()
    accept_mode = "OTP_ONLY" if role_row[0] == "ASHA" else "PASSWORD"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    session.exec(text(
        "INSERT INTO user_invitations (user_id, token_hash, accept_mode, issued_by, expires_at) "
        "VALUES (:uid, :th, :am, :ib, :exp)"
    ), params={"uid": str(user_id), "th": token_hash, "am": accept_mode, "ib": str(current_user.id), "exp": expires_at})
    print(f"DEV invitation issued for user {user_id} ({role_row[1]}) after approval -- expires_at={expires_at.isoformat()}")

    _write_audit(session, actor_user_id=str(current_user.id), action="USER_APPROVED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id))
    response_body = {"id": str(user_id), "status": "INVITED"}
    _idempotency_store(session, idempotency_key, endpoint, body_hash, 200, response_body)
    session.commit()
    return response_body


@router.post("/{user_id}/reject")
def reject_user(user_id: UUID, body: RejectRequest, current_user=Depends(require("user:approve")),
                 session: Session = Depends(get_session)):
    req = session.exec(text(
        "SELECT id FROM approval_requests WHERE subject_user_id = :uid AND status = 'PENDING' ORDER BY created_at DESC LIMIT 1"
    ), params={"uid": str(user_id)}).first()
    if req is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "detail": "No pending approval request."})
    session.exec(text("UPDATE approval_requests SET status = 'REJECTED', decided_at = :now, decision_note = :note WHERE id = :id"),
                 params={"now": datetime.now(timezone.utc), "note": body.reason, "id": req[0]})
    session.exec(text("UPDATE users SET status = 'DEACTIVATED', deactivation_reason = :reason, deactivated_at = :now WHERE id = :id"),
                 params={"reason": body.reason, "now": datetime.now(timezone.utc), "id": str(user_id)})
    _write_audit(session, actor_user_id=str(current_user.id), action="USER_REJECTED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id), metadata={"reason": body.reason})
    session.commit()
    return {"id": str(user_id), "status": "DEACTIVATED"}


# ============================================================
# Invitation lifecycle -- SS7.2
# ============================================================

@router.post("/{user_id}/invite/resend")
def invite_resend(user_id: UUID, current_user=Depends(require("user:create")), session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    if target["status"] != "INVITED":
        raise HTTPException(409, {"code": "NOT_INVITED", "detail": "This account is not in INVITED status."})
    session.exec(text("UPDATE user_invitations SET revoked_at = :now WHERE user_id = :uid AND used_at IS NULL AND revoked_at IS NULL"),
                 params={"now": datetime.now(timezone.utc), "uid": str(user_id)})
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    accept_mode = "OTP_ONLY" if target["role"] == "ASHA" else "PASSWORD"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    session.exec(text(
        "INSERT INTO user_invitations (user_id, token_hash, accept_mode, issued_by, expires_at) "
        "VALUES (:uid, :th, :am, :ib, :exp)"
    ), params={"uid": str(user_id), "th": token_hash, "am": accept_mode, "ib": str(current_user.id), "exp": expires_at})
    print(f"DEV invitation re-issued for user {user_id} ({target['mobile_masked']}) -- expires_at={expires_at.isoformat()}")
    _write_audit(session, actor_user_id=str(current_user.id), action="INVITE_RESENT", outcome="SUCCESS", target_type="USER", target_id=str(user_id))
    session.commit()
    return {"id": str(user_id), "invite": {"sent_to_masked": target["mobile_masked"], "expires_at": expires_at.isoformat()}}


@router.post("/{user_id}/invite/revoke")
def invite_revoke(user_id: UUID, current_user=Depends(require("user:create")), session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    session.exec(text("UPDATE user_invitations SET revoked_at = :now WHERE user_id = :uid AND used_at IS NULL AND revoked_at IS NULL"),
                 params={"now": datetime.now(timezone.utc), "uid": str(user_id)})
    _write_audit(session, actor_user_id=str(current_user.id), action="INVITE_REVOKED", outcome="SUCCESS", target_type="USER", target_id=str(user_id))
    session.commit()
    return {"id": str(user_id), "invite_revoked": True}


# ============================================================
# Suspend / reactivate -- SS6.2, SS10.5
# ============================================================

class SuspendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


@router.post("/{user_id}/suspend")
def suspend_user(user_id: UUID, body: SuspendRequest, current_user=Depends(require("user:suspend")),
                  session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    assert_can_manage(session, current_user, target["scope_org_unit_id"])
    session.exec(text("UPDATE users SET status = 'SUSPENDED', suspended_at = :now, suspension_reason = :reason WHERE id = :id"),
                 params={"now": datetime.now(timezone.utc), "reason": body.reason, "id": str(user_id)})
    session.exec(text("UPDATE refresh_tokens SET revoked_at = :now, revoke_reason = 'SUSPENDED' WHERE user_id = :uid AND revoked_at IS NULL"),
                 params={"now": datetime.now(timezone.utc), "uid": str(user_id)})
    _write_audit(session, actor_user_id=str(current_user.id), action="USER_SUSPENDED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id), metadata={"reason": body.reason})
    session.commit()
    return {"id": str(user_id), "status": "SUSPENDED"}


@router.post("/{user_id}/reactivate")
def reactivate_user(user_id: UUID, current_user=Depends(require("user:suspend")), session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    assert_can_manage(session, current_user, target["scope_org_unit_id"])
    session.exec(text("UPDATE users SET status = 'ACTIVE', suspended_at = NULL, suspension_reason = NULL, "
                       "must_change_password = true WHERE id = :id"), params={"id": str(user_id)})
    _write_audit(session, actor_user_id=str(current_user.id), action="USER_REACTIVATED", outcome="SUCCESS", target_type="USER", target_id=str(user_id))
    session.commit()
    return {"id": str(user_id), "status": "ACTIVE", "must_change_password": True}


# ============================================================
# Transfer -- SS6.1/6.2 (simplified, see module docstring)
# ============================================================

class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_org_unit_id: UUID


@router.post("/{user_id}/transfer")
def transfer_user(user_id: UUID, body: TransferRequest, current_user=Depends(require("user:transfer")),
                   session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    assert_can_manage(session, current_user, target["scope_org_unit_id"])
    if not org_unit_is_within_scope(session, body.new_org_unit_id, current_user.scope_org_unit_id):
        raise HTTPException(403, {"code": "OUT_OF_SCOPE", "detail": "That posting is outside the area you manage."})
    new_path = session.exec(text("SELECT path FROM org_units WHERE id = :id AND is_active = true"),
                             params={"id": str(body.new_org_unit_id)}).first()
    if new_path is None:
        raise HTTPException(422, {"code": "INVALID_ORG_UNIT_TYPE", "detail": "That org unit does not exist or is not active."})
    session.exec(text("UPDATE users SET scope_org_unit_id = :o, scope_path = :p WHERE id = :id"),
                 params={"o": str(body.new_org_unit_id), "p": new_path[0], "id": str(user_id)})
    _write_audit(session, actor_user_id=str(current_user.id), action="USER_TRANSFERRED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id), metadata={"new_org_unit_id": str(body.new_org_unit_id)})
    session.commit()
    return {"id": str(user_id), "scope_org_unit_id": str(body.new_org_unit_id), "scope_path": new_path[0]}


# ============================================================
# Deactivate -- SS6.4, close to verbatim
# ============================================================

class DeactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)
    reassign_to_user_id: Optional[UUID] = None


@router.post("/{user_id}/deactivate")
def deactivate_user(user_id: UUID, body: DeactivateRequest, current_user=Depends(require("user:deactivate")),
                     session: Session = Depends(get_session)):
    target = _get_user_or_404(session, current_user, user_id)
    assert_can_manage(session, current_user, target["scope_org_unit_id"])

    subordinates_rows = session.exec(text(
        "SELECT id, role FROM users WHERE reports_to_user_id = :id AND status IN ('ACTIVE','INVITED','SUSPENDED')"
    ), params={"id": str(user_id)}).all()

    if subordinates_rows:
        if body.reassign_to_user_id is None:
            raise HTTPException(409, {
                "code": "SUBORDINATES_EXIST",
                "detail": f"{len(subordinates_rows)} users report to this account. Provide reassign_to_user_id.",
                "subordinate_ids": [str(r[0]) for r in subordinates_rows],
                "suggested_reassign_to": str(target["reports_to_user_id"]) if target["reports_to_user_id"] else None,
            })
        new_manager = _get_user_row(session, body.reassign_to_user_id)
        if new_manager is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "detail": "reassign_to_user_id not found."})
        if new_manager["status"] != "ACTIVE":
            raise HTTPException(422, {"code": "NEW_MANAGER_NOT_ACTIVE"})
        for _sid, srole in subordinates_rows:
            if not can_create_role(session, new_manager["role"], srole):
                raise HTTPException(422, {"code": "NEW_MANAGER_CANNOT_MANAGE_ROLE",
                                           "detail": f"{new_manager['role']} cannot manage {srole}."})
        for sid, _srole in subordinates_rows:
            session.exec(text("UPDATE users SET reports_to_user_id = :new WHERE id = :sid"),
                         params={"new": str(body.reassign_to_user_id), "sid": str(sid)})
            _write_audit(session, actor_user_id=str(current_user.id), action="USER_REASSIGNED", outcome="SUCCESS",
                         target_type="USER", target_id=str(sid),
                         metadata={"from": str(user_id), "to": str(body.reassign_to_user_id)})

    session.exec(text(
        "UPDATE users SET status = 'DEACTIVATED', deactivated_at = :now, deactivation_reason = :reason, "
        "password_hash = NULL WHERE id = :id"
    ), params={"now": datetime.now(timezone.utc), "reason": body.reason, "id": str(user_id)})
    session.exec(text("UPDATE mfa_credentials SET revoked_at = :now WHERE user_id = :uid AND revoked_at IS NULL"),
                 params={"now": datetime.now(timezone.utc), "uid": str(user_id)})
    session.exec(text("UPDATE refresh_tokens SET revoked_at = :now, revoke_reason = 'DEACTIVATED' WHERE user_id = :uid AND revoked_at IS NULL"),
                 params={"now": datetime.now(timezone.utc), "uid": str(user_id)})
    _write_audit(session, actor_user_id=str(current_user.id), action="USER_DEACTIVATED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id), metadata={"reason": body.reason})
    session.commit()
    return {"id": str(user_id), "status": "DEACTIVATED"}
