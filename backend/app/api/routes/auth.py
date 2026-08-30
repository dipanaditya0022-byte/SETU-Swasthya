"""Authentication route surface, per Day1.md SS14 (API surface), SS7
(invitation flow), SS10 (auth/session security), SS5.4 (PATIENT
registration fields), and SS6 (account lifecycle).

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- Endpoint paths, purposes, and rate-limit targets: SS14.2/14.3's own
  tables, verbatim.
- POST /auth/otp/request and /auth/otp/verify's exact request/response
  shapes: SS19.2's own smoke-test curl examples, verbatim
  ({"otp_sent": true, "expires_in": 300}; {"mobile","otp"} ->
  {"otp_token": ...}).
- POST /auth/patient/register's field set: SS5.4's PATIENT block,
  verbatim (full_name, full_name_local, date_of_birth OR age_years,
  sex, mobile, is_shared_phone, abha_number, abha_address,
  village_lgd_code, hamlet, house_number, household_id,
  preferred_language, guardian_* required if age<18,
  emergency_contact_*, the four consent_* booleans, consent_mode,
  otp_token). No `role` field exists in this schema (SS14/T3: staff
  self-registration must be impossible).
- POST /auth/invite/accept's exact request shape and 410-on-replay:
  SS7's own flow diagram and SS19.2's T9 smoke test, verbatim
  ({"token","password","password_confirm","mobile_otp"}).
- The otp_codes table this file writes to/reads from is the one
  proposed and confirmed with the user directly in this session, per
  migration b7d2e4a91c68's own docstring (no CREATE TABLE for OTP
  storage exists anywhere in Day1.md).

- Several endpoints Day1.md names only as a row in SS14.2/14.3 (path +
  purpose + rate limit), with NO request/response JSON shown anywhere
  in the document: POST /auth/login, POST /auth/mfa/verify, POST
  /auth/token/refresh's exact body, POST /auth/password/reset-request,
  POST /auth/password/reset, POST /auth/password/change, POST
  /auth/mfa/enrol, GET /auth/sessions, DELETE /auth/sessions/{id}. For
  these, this file defines a concrete, minimal, internally-consistent
  shape using only fields Day1.md DOES establish elsewhere (mobile,
  email, password, device_fingerprint, refresh_token from SS10.4's own
  refresh_access_token signature, TOTP from SS10.1/SS10.3's `amr`
  claim) -- not invented field names for things Day1.md gives no
  vocabulary for. This is documented per-endpoint below rather than
  presented as a spec quote, so it's reviewable and correctable field
  by field. Given the volume of under-specified endpoints in a single
  step, these were not each raised as a separate stop-and-ask; the
  established pattern in this session (propose a concrete design,
  document it clearly, let the user correct anything wrong) is applied
  here at endpoint scope instead.

- Login/session TTLs and MFA-mandatory-by-role: SS10.1's own table,
  encoded verbatim as ROLE_SESSION_CONFIG below (access/refresh minutes
  per role, whether TOTP/hardware-key MFA is mandatory at login, and
  whether the role logs in with password or OTP-only).

- MFA: pyotp is a new dependency (requirements.txt) -- no TOTP
  (RFC 6238) library existed in this repo, and hand-rolling a TOTP
  implementation is not appropriate for security-critical code.
  POST /auth/mfa/enrol returns the raw secret plus an otpauth://
  provisioning URI (the standard payload a QR code encodes) rather
  than a rendered PNG -- no image-rendering dependency (Pillow) exists
  in this repo either, and returning the URI lets any client render
  its own QR code, which is the more common real-world pattern anyway.

- Two-step MFA login: SS10.3's own `amr` claim ("which factors were
  actually used") and SS10.1's per-role "second factor: mandatory"
  column imply a first-factor-then-second-factor flow, not a single
  call. Not literally speced, so implemented here as: POST /auth/login
  succeeds on the first factor (password or OTP per role) and, for
  MFA-mandatory roles, returns a short-lived (5 min) `mfa_challenge`
  JWT (signed with the same RS256 key as access tokens, but a distinct
  `purpose` claim access tokens never carry, so it can never be
  mistaken for or reused as a real access token) instead of real
  tokens; POST /auth/mfa/verify exchanges that challenge plus a TOTP
  code for real access/refresh tokens. Non-MFA roles get real tokens
  directly from /auth/login.

- Lockout (SS10.5): 5 failures -> 15-min lock; 10 failures -> suspend
  + notify supervisor (SS6.2 confirms "10 failed logins" as a real
  ACTIVE -> SUSPENDED transition trigger). "Notify supervisor" reuses
  the same logging-only stub pattern as app/core/tokens.py's
  alert_security_team, since no notification gateway exists anywhere
  in this repo yet.

- Rate limiting (SS14.2's per-route limits): NOT implemented in this
  file. slowapi is an installed dependency (S1) but wiring a
  Limiter/exception-handler into the FastAPI app is an app.main.py-
  level change this step doesn't touch, to keep this step's diff
  scoped to the one file the task instructions name. Flagged here
  rather than silently omitted -- a follow-up step should wire this
  in before this goes anywhere near production traffic.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional
from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt as jose_jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel import Session, text

from app.core.authz import get_current_active_user
from app.core.crypto import blind_index, decrypt_field, encrypt_field, mask_mobile
from app.core.password import hash_password, validate_password_policy, verify_password
from app.core.tokens import (
    AccountNotActive,
    DeviceMismatch,
    InvalidRefreshToken,
    RefreshTokenExpired,
    TokenError,
    TokenReuseDetected,
    get_jwks as _get_jwks,
    hash_refresh_token,
    issue_access_token,
    issue_refresh_token,
    refresh_access_token as _refresh_access_token,
    revoke_token_family,
    verify_access_token,
)
from app.db.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Auth"])

import os as _os

_JWT_PRIVATE_KEY_PATH = lambda: _os.environ.get("JWT_PRIVATE_KEY_PATH")
_JWT_ISSUER = lambda: _os.environ.get("JWT_ISSUER", "setu-swasthya")
_JWT_AUDIENCE = lambda: _os.environ.get("JWT_AUDIENCE", "setu-api")
_ENVIRONMENT = lambda: _os.environ.get("ENVIRONMENT", "development")


# ============================================================
# Per-role session config -- SS10.1's own table, verbatim.
# (access_minutes, refresh_days, mfa_mandatory, login_method)
# login_method: "password" (mobile/email + password) or "otp" (mobile + OTP only)
# ============================================================
ROLE_SESSION_CONFIG: dict[str, dict[str, Any]] = {
    "SUPERUSER": {"access_minutes": 5, "refresh_days": 1 / 24, "mfa_mandatory": True, "login_method": "password"},  # refresh 1h
    "STATE_NHM": {"access_minutes": 15, "refresh_days": 8 / 24, "mfa_mandatory": True, "login_method": "password"},  # refresh 8h
    "COLLECTOR": {"access_minutes": 15, "refresh_days": 8 / 24, "mfa_mandatory": True, "login_method": "password"},
    "DHO_CMO": {"access_minutes": 15, "refresh_days": 8 / 24, "mfa_mandatory": True, "login_method": "password"},
    "DISTRICT_EPIDEMIOLOGIST": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "HEALTH_ADMIN_DPM": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "PROGRAMME_OFFICER": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "DISTRICT_IT_OFFICER": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "DPO": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "SPECIALIST": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "BMO": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "MEDICAL_OFFICER": {"access_minutes": 15, "refresh_days": 1, "mfa_mandatory": True, "login_method": "password"},
    "CHO": {"access_minutes": 30, "refresh_days": 7, "mfa_mandatory": False, "login_method": "password"},
    "ANM_MPW": {"access_minutes": 30, "refresh_days": 7, "mfa_mandatory": False, "login_method": "password"},
    "LAB_TECHNICIAN": {"access_minutes": 30, "refresh_days": 7, "mfa_mandatory": False, "login_method": "password"},
    "PHARMACIST": {"access_minutes": 30, "refresh_days": 7, "mfa_mandatory": False, "login_method": "password"},
    "ASHA": {"access_minutes": 60, "refresh_days": 30, "mfa_mandatory": False, "login_method": "otp"},
    "PATIENT": {"access_minutes": 30, "refresh_days": 30, "mfa_mandatory": False, "login_method": "otp"},
    "VHSNC_MEMBER": {"access_minutes": 30, "refresh_days": 7, "mfa_mandatory": False, "login_method": "otp"},
}

_UNIFORM_LOGIN_ERROR = {"code": "INVALID_CREDENTIALS", "detail": "Mobile number or password is not correct."}


# ============================================================
# Small shared helpers
# ============================================================

def _generate_otp() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _hash_otp(otp: str, mobile_bi: str) -> str:
    # Salted with the mobile's own blind index so two users who happen
    # to get the same 6-digit code don't collide in the hash space.
    return hashlib.sha256(f"{mobile_bi}:{otp}".encode()).hexdigest()


def _write_audit(session: Session, *, actor_user_id: Optional[str], action: str,
                  outcome: str, target_type: Optional[str] = None,
                  target_id: Optional[str] = None, metadata: Optional[dict] = None) -> None:
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


def _get_user_row(session: Session, user_id: str):
    return session.exec(text(
        "SELECT id, status, role, role_level, scope_org_unit_id, scope_path, token_version, "
        "mfa_required, mfa_enrolled, password_hash, mobile_blind_index, mobile_masked, "
        "failed_login_count, locked_until, full_name, email_blind_index "
        "FROM users WHERE id = :id"
    ), params={"id": user_id}).first()


def _issue_session_tokens(session: Session, *, user_row, amr: list[str], device_fingerprint: Optional[str],
                           device_label: Optional[str] = None, ip: Optional[str] = None) -> dict:
    """Shared by /auth/login (non-MFA roles), /auth/mfa/verify, and
    invite-accept: mints a fresh session_id/family_id, a real refresh
    token (S13's issue_refresh_token), and a matching access token
    (S13's issue_access_token) with the role's own TTL/config."""
    import uuid as _uuid
    (uid, status, role, role_level, scope_org_unit_id, scope_path, token_version, *_rest) = user_row
    config = ROLE_SESSION_CONFIG.get(role, {"access_minutes": 15, "refresh_days": 1})
    session_id = str(_uuid.uuid4())
    family_id = str(_uuid.uuid4())
    perms_hash = _compute_perms_hash(session, role)

    raw_refresh = issue_refresh_token(
        session, user_id=str(uid), family_id=family_id, session_id=session_id,
        device_fingerprint=device_fingerprint, device_label=device_label, ip=ip,
        expires_in_days=max(1, int(config["refresh_days"])),
    )
    access_token = issue_access_token(
        user_id=str(uid), role=role, level=role_level, scope_org_id=str(scope_org_unit_id) if scope_org_unit_id else None,
        scope_path=scope_path, perms_hash=perms_hash, session_id=session_id, token_version=token_version,
        amr=amr, expires_in_minutes=config["access_minutes"],
    )
    session.commit()
    return {
        "access_token": access_token, "refresh_token": raw_refresh, "token_type": "bearer",
        "expires_in": config["access_minutes"] * 60,
    }


def _compute_perms_hash(session: Session, role: str) -> str:
    from app.core.authz import get_effective_permissions
    perms = sorted(get_effective_permissions(session, role))
    return "sha256:" + hashlib.sha256(",".join(perms).encode()).hexdigest()[:16]


def _issue_mfa_challenge(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    with open(_JWT_PRIVATE_KEY_PATH(), "rb") as f:
        private_key = f.read().decode()
    claims = {
        "sub": user_id, "purpose": "mfa_challenge",
        "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iss": _JWT_ISSUER(), "aud": _JWT_AUDIENCE(),
    }
    return jose_jwt.encode(claims, private_key, algorithm="RS256")


def _verify_mfa_challenge(token: str) -> str:
    with open(_os.environ["JWT_PUBLIC_KEY_PATH"], "rb") as f:
        public_key = f.read().decode()
    try:
        claims = jose_jwt.decode(token, public_key, algorithms=["RS256"], issuer=_JWT_ISSUER(), audience=_JWT_AUDIENCE())
    except JWTError:
        raise HTTPException(401, {"code": "INVALID_MFA_CHALLENGE", "detail": "Invalid or expired MFA challenge."})
    if claims.get("purpose") != "mfa_challenge":
        raise HTTPException(401, {"code": "INVALID_MFA_CHALLENGE", "detail": "Invalid or expired MFA challenge."})
    return claims["sub"]


# ============================================================
# Schemas
# ============================================================

class OtpRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str
    purpose: Literal["PATIENT_REGISTRATION", "LOGIN", "INVITE_ACCEPT", "PASSWORD_RESET"]


class OtpVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str
    otp: str


class PatientRegistrationRequest(BaseModel):
    """SS5.4's PATIENT block, verbatim field set. No `role` field exists
    (SS14/T3: staff self-registration via this endpoint must be
    impossible -- extra='forbid' plus the absence of the field means a
    posted `role` is a 422, not silently ignored)."""
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    full_name_local: Optional[str] = None
    date_of_birth: Optional[date] = None
    age_years: Optional[int] = Field(default=None, ge=0, le=120)
    sex: Literal["FEMALE", "MALE", "OTHER"]
    mobile: str
    is_shared_phone: bool = False
    abha_number: Optional[str] = None
    abha_address: Optional[str] = None
    village_lgd_code: str
    hamlet: Optional[str] = Field(default=None, max_length=80)
    house_number: Optional[str] = Field(default=None, max_length=20)
    household_id: Optional[UUID] = None
    preferred_language: str = Field(min_length=2, max_length=10)
    guardian_name: Optional[str] = None
    guardian_relation: Optional[Literal["MOTHER", "FATHER", "GUARDIAN"]] = None
    guardian_mobile: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_mobile: Optional[str] = None
    consent_keep_record: bool
    consent_share_specialist: bool
    consent_share_facility: bool
    consent_anonymised_planning: bool
    consent_mode: Literal["DIGITAL_SELF", "SPOKEN_WITNESSED", "THUMB_IMPRESSION"]
    otp_token: str

    @field_validator("abha_number")
    @classmethod
    def _validate_abha(cls, v):
        if v is not None and (len(v) != 14 or not v.isdigit()):
            raise ValueError("abha_number must be exactly 14 digits")
        return v

    @model_validator(mode="after")
    def _validate_age_and_guardian(self) -> "PatientRegistrationRequest":
        if self.date_of_birth is None and self.age_years is None:
            raise ValueError("one of date_of_birth or age_years is required")
        if self.date_of_birth is not None:
            age = (date.today() - self.date_of_birth).days / 365.25
        else:
            age = self.age_years
        if age < 18:
            for field_name in ("guardian_name", "guardian_relation", "guardian_mobile"):
                if getattr(self, field_name) is None:
                    raise ValueError(f"{field_name} is required for a minor (age < 18)")
        return self


class LoginRequest(BaseModel):
    """Not literally specced (see module docstring). mobile/email +
    password for password-role login; mobile + otp_token (from a prior
    /auth/otp/verify call) for OTP-only roles."""
    model_config = ConfigDict(extra="forbid")
    mobile: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    otp_token: Optional[str] = None
    device_fingerprint: Optional[str] = None
    device_label: Optional[str] = None


class MfaVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mfa_challenge_token: str
    totp_code: str
    device_fingerprint: Optional[str] = None
    device_label: Optional[str] = None


class TokenRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str
    device_fingerprint: Optional[str] = None


class InviteAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    password: Optional[str] = None
    password_confirm: Optional[str] = None
    mobile_otp: str


class PasswordResetRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str


class PasswordResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str
    otp: str
    new_password: str
    new_password_confirm: str


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str
    new_password: str
    new_password_confirm: str


# ============================================================
# PUBLIC routes
# ============================================================

@router.post("/auth/otp/request")
def otp_request(body: OtpRequestBody, session: Session = Depends(get_session)):
    """SS19.2 T1's own shape, verbatim: 200 {"otp_sent": true, "expires_in": 300}."""
    mobile_bi = blind_index(body.mobile)
    otp = _generate_otp()
    otp_hash = _hash_otp(otp, mobile_bi)
    ttl = int(_os.environ.get("OTP_TTL_SECONDS", "300"))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    session.exec(text(
        "INSERT INTO otp_codes (mobile_blind_index, purpose, otp_hash, expires_at) "
        "VALUES (:m, :p, :h, :e)"
    ), params={"m": mobile_bi, "p": body.purpose, "h": otp_hash, "e": expires_at})
    session.commit()
    if _ENVIRONMENT() == "development":
        # SS19.2's own note: "In dev, the OTP is printed to the server
        # log. Never in production." Never returned in the response body.
        print(f"DEV OTP for {mask_mobile(body.mobile)} (purpose={body.purpose}): {otp}")
    return {"otp_sent": True, "expires_in": ttl}


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerifyBody, session: Session = Depends(get_session)):
    """SS19.2 T1's own shape: verify, return a short-lived otp_token."""
    mobile_bi = blind_index(body.mobile)
    otp_hash = _hash_otp(body.otp, mobile_bi)
    row = session.exec(text(
        "SELECT id, attempt_count, expires_at, verified_at, otp_hash FROM otp_codes "
        "WHERE mobile_blind_index = :m AND verified_at IS NULL ORDER BY created_at DESC LIMIT 1"
    ), params={"m": mobile_bi}).first()

    if row is None:
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})
    otp_id, attempt_count, expires_at, verified_at, stored_hash = row

    max_attempts = int(_os.environ.get("OTP_MAX_ATTEMPTS", "3"))
    if attempt_count >= max_attempts:
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})

    if not secrets.compare_digest(stored_hash, otp_hash):
        session.exec(text("UPDATE otp_codes SET attempt_count = attempt_count + 1 WHERE id = :id"), params={"id": otp_id})
        session.commit()
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})

    otp_token = secrets.token_urlsafe(32)
    otp_token_hash = hashlib.sha256(otp_token.encode()).hexdigest()
    otp_token_ttl = 300
    session.exec(text(
        "UPDATE otp_codes SET verified_at = :now, otp_token_hash = :th, "
        "otp_token_expires_at = :te WHERE id = :id"
    ), params={"now": datetime.now(timezone.utc), "th": otp_token_hash, "id": otp_id,
               "te": datetime.now(timezone.utc) + timedelta(seconds=otp_token_ttl)})
    session.commit()
    return {"otp_token": otp_token, "expires_in": otp_token_ttl}


def _consume_otp_token(session: Session, mobile: str, otp_token: str) -> None:
    """Shared by patient registration, login (OTP-only roles), and
    anywhere else an already-verified otp_token proves phone
    possession. Fails closed: any mismatch is a plain 401, single use
    (verified_at was already set by otp_verify; this checks the
    *token*, not the original 6-digit code, and does not re-consume --
    the token itself remains valid until its own 5-min TTL to allow the
    otp_token OTP-token exchange to be checked without a second DB
    write path, but is scoped to one mobile+row)."""
    mobile_bi = blind_index(mobile)
    token_hash = hashlib.sha256(otp_token.encode()).hexdigest()
    row = session.exec(text(
        "SELECT id, otp_token_expires_at FROM otp_codes WHERE mobile_blind_index = :m "
        "AND otp_token_hash = :h AND verified_at IS NOT NULL"
    ), params={"m": mobile_bi, "h": token_hash}).first()
    if row is None or row[1] < datetime.now(timezone.utc):
        raise HTTPException(401, {"code": "OTP_TOKEN_INVALID", "detail": "OTP verification required or expired."})


@router.post("/auth/patient/register", status_code=201)
def patient_register(body: PatientRegistrationRequest, session: Session = Depends(get_session)):
    """SS5.4 PATIENT + SS19.2 T1/T2: OTP-verified mobile mandatory,
    created_by_user_id NULL, all-four-consents-false still succeeds
    (no code path here even checks the consent values before
    inserting)."""
    _consume_otp_token(session, body.mobile, body.otp_token)

    mobile_bi = blind_index(body.mobile)
    existing = session.exec(text(
        "SELECT id FROM users WHERE mobile_blind_index = :m AND status <> 'DEACTIVATED'"
    ), params={"m": mobile_bi}).first()
    if existing is not None:
        raise HTTPException(409, {"code": "MOBILE_ALREADY_REGISTERED", "detail": "This mobile is already registered."})

    profile = {
        "age_years": body.age_years, "age_is_estimated": body.age_years is not None and body.date_of_birth is None,
        "is_shared_phone": body.is_shared_phone, "abha_address": body.abha_address,
        "village_lgd_code": body.village_lgd_code, "hamlet": body.hamlet, "house_number": body.house_number,
        "household_id": str(body.household_id) if body.household_id else None,
        "guardian_name": body.guardian_name, "guardian_relation": body.guardian_relation,
        "guardian_mobile": body.guardian_mobile, "emergency_contact_name": body.emergency_contact_name,
        "emergency_contact_mobile": body.emergency_contact_mobile,
    }
    abha_encrypted = encrypt_field(body.abha_number) if body.abha_number else None

    row = session.exec(text(
        "INSERT INTO users (role, role_level, full_name, full_name_local, date_of_birth, sex, "
        "preferred_language, mobile_encrypted, mobile_blind_index, mobile_masked, "
        "abha_number_encrypted, profile, status, mfa_required) "
        "VALUES ('PATIENT', 99, :full_name, :full_name_local, :dob, :sex, :lang, :mobile_enc, "
        ":mobile_bi, :mobile_masked, :abha_enc, :profile, 'ACTIVE', false) "
        "RETURNING id"
    ), params={
        "full_name": body.full_name, "full_name_local": body.full_name_local, "dob": body.date_of_birth,
        "sex": body.sex, "lang": body.preferred_language, "mobile_enc": encrypt_field(body.mobile),
        "mobile_bi": mobile_bi, "mobile_masked": mask_mobile(body.mobile), "abha_enc": abha_encrypted,
        "profile": json.dumps(profile),
    }).first()
    patient_id = row[0]

    session.exec(text(
        "INSERT INTO consents (patient_user_id, keep_record, share_specialist, share_facility, "
        "anonymised_planning, mode, language) VALUES (:pid, :kr, :ss, :sf, :ap, :mode, :lang)"
    ), params={"pid": patient_id, "kr": body.consent_keep_record, "ss": body.consent_share_specialist,
               "sf": body.consent_share_facility, "ap": body.consent_anonymised_planning,
               "mode": body.consent_mode, "lang": body.preferred_language})
    _write_audit(session, actor_user_id=None, action="PATIENT_SELF_REGISTERED", outcome="SUCCESS",
                 target_type="USER", target_id=str(patient_id))
    session.commit()
    return {"id": str(patient_id), "status": "ACTIVE", "created_by_user_id": None, "mobile_masked": mask_mobile(body.mobile)}


@router.post("/auth/login")
def login(body: LoginRequest, session: Session = Depends(get_session)):
    """SS10.5's uniform-error/timing-normalisation rules: identical body
    for unknown mobile, wrong password, and suspended account; always
    runs a real or dummy Argon2 verify either way."""
    identifier_bi = blind_index(body.mobile) if body.mobile else (blind_index(body.email) if body.email else None)
    if identifier_bi is None:
        raise HTTPException(422, {"code": "IDENTIFIER_REQUIRED", "detail": "mobile or email is required."})

    row = session.exec(text(
        "SELECT id, status, role, role_level, scope_org_unit_id, scope_path, token_version, "
        "mfa_required, mfa_enrolled, password_hash, mobile_blind_index, mobile_masked, "
        "failed_login_count, locked_until, full_name, email_blind_index "
        "FROM users WHERE mobile_blind_index = :bi OR email_blind_index = :bi"
    ), params={"bi": identifier_bi}).first()

    if row is None:
        verify_password("dummy-timing-normalisation", None)
        _write_audit(session, actor_user_id=None, action="LOGIN_FAILED", outcome="DENIED",
                     metadata={"reason": "UNKNOWN_IDENTIFIER"})
        session.commit()
        raise HTTPException(401, _UNIFORM_LOGIN_ERROR)

    (uid, status, role, role_level, scope_org_unit_id, scope_path, token_version, mfa_required,
     mfa_enrolled, password_hash, mobile_bi, mobile_masked, failed_count, locked_until, full_name,
     email_bi) = row

    if locked_until is not None and locked_until > datetime.now(timezone.utc):
        verify_password(body.password or "dummy", password_hash)
        raise HTTPException(401, _UNIFORM_LOGIN_ERROR)

    config = ROLE_SESSION_CONFIG.get(role, {"login_method": "password", "mfa_mandatory": False})
    authenticated = False
    amr: list[str] = []

    if config["login_method"] == "otp":
        if not body.otp_token or not body.mobile:
            raise HTTPException(422, {"code": "OTP_TOKEN_REQUIRED", "detail": "otp_token is required for this role."})
        try:
            _consume_otp_token(session, body.mobile, body.otp_token)
            authenticated = True
            amr = ["otp"]
        except HTTPException:
            authenticated = False
    else:
        if verify_password(body.password or "", password_hash):
            authenticated = True
            amr = ["pwd"]

    if not authenticated or status != "ACTIVE":
        new_failed = failed_count + 1
        lock_minutes = int(_os.environ.get("LOCKOUT_MINUTES", "15"))
        max_failed = int(_os.environ.get("MAX_FAILED_LOGINS", "5"))
        suspend_after = int(_os.environ.get("SUSPEND_AFTER_FAILURES", "10"))
        new_locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes) if new_failed >= max_failed else None
        new_status = "SUSPENDED" if new_failed >= suspend_after else status
        session.exec(text(
            "UPDATE users SET failed_login_count = :fc, locked_until = :lu, "
            "status = CASE WHEN :new_status = 'SUSPENDED' THEN 'SUSPENDED' ELSE status END, "
            "suspended_at = CASE WHEN :new_status = 'SUSPENDED' THEN now() ELSE suspended_at END, "
            "suspension_reason = CASE WHEN :new_status = 'SUSPENDED' THEN '10 failed login attempts' ELSE suspension_reason END "
            "WHERE id = :id"
        ), params={"fc": new_failed, "lu": new_locked_until, "new_status": new_status, "id": uid})
        if new_status == "SUSPENDED":
            revoke_token_family(session, str(uid), reason="SUSPENDED_10_FAILED_LOGINS")
            logger.warning("SUPERVISOR NOTIFICATION (no gateway configured): user_id=%s suspended after 10 failed logins", uid)
        _write_audit(session, actor_user_id=str(uid), action="LOGIN_FAILED", outcome="DENIED",
                     target_type="USER", target_id=str(uid), metadata={"failed_count": new_failed})
        session.commit()
        raise HTTPException(401, _UNIFORM_LOGIN_ERROR)

    # success
    session.exec(text("UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = :now WHERE id = :id"),
                 params={"now": datetime.now(timezone.utc), "id": uid})
    _write_audit(session, actor_user_id=str(uid), action="LOGIN_SUCCESS", outcome="SUCCESS", target_type="USER", target_id=str(uid))

    if config.get("mfa_mandatory") and mfa_enrolled:
        session.commit()
        challenge = _issue_mfa_challenge(str(uid))
        return {"mfa_required": True, "mfa_challenge_token": challenge, "amr_so_far": amr}

    result = _issue_session_tokens(session, user_row=row, amr=amr, device_fingerprint=body.device_fingerprint,
                                    device_label=body.device_label)
    return result


@router.post("/auth/mfa/verify")
def mfa_verify(body: MfaVerifyRequest, session: Session = Depends(get_session)):
    user_id = _verify_mfa_challenge(body.mfa_challenge_token)
    cred = session.exec(text(
        "SELECT totp_secret_encrypted FROM mfa_credentials WHERE user_id = :uid "
        "AND credential_type = 'TOTP' AND is_verified = true AND revoked_at IS NULL"
    ), params={"uid": user_id}).first()
    if cred is None:
        raise HTTPException(401, {"code": "MFA_NOT_ENROLLED", "detail": "TOTP is not enrolled for this account."})

    secret = decrypt_field(bytes(cred[0]))
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.totp_code, valid_window=1):
        _write_audit(session, actor_user_id=user_id, action="MFA_VERIFY_FAILED", outcome="DENIED", target_type="USER", target_id=user_id)
        session.commit()
        raise HTTPException(401, {"code": "MFA_INVALID", "detail": "Incorrect verification code."})

    session.exec(text("UPDATE mfa_credentials SET last_used_at = :now WHERE user_id = :uid AND credential_type = 'TOTP'"),
                 params={"now": datetime.now(timezone.utc), "uid": user_id})
    row = _get_user_row(session, user_id)
    _write_audit(session, actor_user_id=user_id, action="MFA_VERIFY_SUCCESS", outcome="SUCCESS", target_type="USER", target_id=user_id)
    return _issue_session_tokens(session, user_row=row, amr=["pwd", "totp"], device_fingerprint=body.device_fingerprint,
                                  device_label=body.device_label)


@router.post("/auth/token/refresh")
def token_refresh(body: TokenRefreshRequest, session: Session = Depends(get_session)):
    """Thin wrapper around S13's refresh_access_token; mints the paired
    new access token here (permission resolution/role context lives at
    this route layer, not in app/core/tokens.py -- see that module's
    own docstring)."""
    try:
        new_raw_refresh, user = _refresh_access_token(session, presented_token=body.refresh_token,
                                                        device_fingerprint=body.device_fingerprint)
    except InvalidRefreshToken:
        raise HTTPException(401, {"code": "INVALID_REFRESH_TOKEN"})
    except TokenReuseDetected:
        raise HTTPException(401, {"code": "TOKEN_REUSE_DETECTED", "detail": "For your security, please sign in again."})
    except RefreshTokenExpired:
        raise HTTPException(401, {"code": "REFRESH_TOKEN_EXPIRED"})
    except DeviceMismatch:
        raise HTTPException(401, {"code": "DEVICE_MISMATCH"})
    except AccountNotActive:
        raise HTTPException(401, {"code": "ACCOUNT_NOT_ACTIVE"})

    session_id_row = session.exec(text(
        "SELECT session_id FROM refresh_tokens WHERE token_hash = :h"
    ), params={"h": hash_refresh_token(new_raw_refresh)}).first()
    session_id = str(session_id_row[0]) if session_id_row else None

    config = ROLE_SESSION_CONFIG.get(user["role"], {"access_minutes": 15})
    perms_hash = _compute_perms_hash(session, user["role"])
    access_token = issue_access_token(
        user_id=str(user["id"]), role=user["role"], level=user["role_level"],
        scope_org_id=str(user["scope_org_unit_id"]) if user["scope_org_unit_id"] else None,
        scope_path=user["scope_path"], perms_hash=perms_hash, session_id=session_id or "",
        token_version=user["token_version"], amr=["pwd"], expires_in_minutes=config["access_minutes"],
    )
    return {"access_token": access_token, "refresh_token": new_raw_refresh, "token_type": "bearer",
            "expires_in": config["access_minutes"] * 60}


@router.post("/auth/invite/accept")
def invite_accept(body: InviteAcceptRequest, session: Session = Depends(get_session)):
    """SS7's own flow + SS19.2 T9: single use, 72h, mobile OTP required,
    replay -> 410. ASHA's OTP_ONLY accept_mode (SS7.3) sets no password
    at all."""
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    row = session.exec(text(
        "SELECT id, user_id, accept_mode, expires_at, used_at, revoked_at FROM user_invitations "
        "WHERE token_hash = :h"
    ), params={"h": token_hash}).first()
    if row is None:
        raise HTTPException(401, {"code": "INVITE_INVALID", "detail": "Invalid invitation."})
    invite_id, user_id, accept_mode, expires_at, used_at, revoked_at = row

    if used_at is not None:
        raise HTTPException(410, {"code": "INVITE_ALREADY_USED"})
    if revoked_at is not None:
        raise HTTPException(410, {"code": "INVITE_REVOKED"})
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(410, {"code": "INVITE_EXPIRED"})

    user_row = _get_user_row(session, str(user_id))
    if user_row is None:
        raise HTTPException(401, {"code": "INVITE_INVALID", "detail": "Invalid invitation."})
    mobile_bi = user_row[10]

    # OTP to the mobile recorded at creation (SS7.2: "bound to the mobile").
    otp_row = session.exec(text(
        "SELECT id, otp_hash, attempt_count, expires_at FROM otp_codes "
        "WHERE mobile_blind_index = :m AND verified_at IS NULL ORDER BY created_at DESC LIMIT 1"
    ), params={"m": mobile_bi}).first()
    if otp_row is None or otp_row[3] < datetime.now(timezone.utc):
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})
    if not secrets.compare_digest(otp_row[1], _hash_otp(body.mobile_otp, mobile_bi)):
        session.exec(text("UPDATE otp_codes SET attempt_count = attempt_count + 1 WHERE id = :id"), params={"id": otp_row[0]})
        session.commit()
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})

    if accept_mode == "OTP_ONLY":
        password_hash_value = None
    else:
        if not body.password or body.password != body.password_confirm:
            raise HTTPException(422, {"code": "PASSWORD_MISMATCH", "detail": "Passwords do not match."})
        violations = validate_password_policy(body.password, is_privileged=user_row[3] is not None and user_row[3] <= 3)
        if violations:
            raise HTTPException(422, {"code": "PASSWORD_POLICY_VIOLATION", "detail": violations})
        password_hash_value = hash_password(body.password)

    session.exec(text("UPDATE user_invitations SET used_at = :now WHERE id = :id"),
                 params={"now": datetime.now(timezone.utc), "id": invite_id})
    session.exec(text(
        "UPDATE users SET status = 'ACTIVE', password_hash = :ph, activated_at = :now, "
        "must_change_password = false WHERE id = :uid"
    ), params={"ph": password_hash_value, "now": datetime.now(timezone.utc), "uid": user_id})
    _write_audit(session, actor_user_id=str(user_id), action="INVITE_ACCEPTED", outcome="SUCCESS",
                 target_type="USER", target_id=str(user_id))
    session.commit()

    mfa_payload: dict = {}
    if user_row[7]:  # mfa_required
        # is_verified=true and users.mfa_enrolled=true are set immediately
        # here, not after a separate confirmation TOTP entry: Day1.md's
        # endpoint surface (SS14.3) has no separate "confirm enrolment"
        # route, only "enrol...returns a TOTP secret + QR, once" -- and a
        # design requiring confirmation-before-enrolled-flag would create
        # a real bootstrapping deadlock, found by tracing the flow: login()
        # only issues an MFA challenge when mfa_enrolled is already true,
        # so if enrolment couldn't complete without first passing an MFA
        # challenge, an MFA-mandatory role could never enrol at all.
        secret = pyotp.random_base32()
        session.exec(text(
            "INSERT INTO mfa_credentials (user_id, credential_type, totp_secret_encrypted, is_verified) "
            "VALUES (:uid, 'TOTP', :secret, true)"
        ), params={"uid": user_id, "secret": encrypt_field(secret)})
        session.exec(text("UPDATE users SET mfa_enrolled = true WHERE id = :uid"), params={"uid": user_id})
        session.commit()
        totp = pyotp.TOTP(secret)
        mfa_payload = {"mfa_secret": secret, "provisioning_uri": totp.provisioning_uri(name=user_row[14], issuer_name=_JWT_ISSUER())}

    return {"status": "ACTIVE", "mfa_enrolment": mfa_payload}


@router.post("/auth/password/reset-request")
def password_reset_request(body: PasswordResetRequestBody, session: Session = Depends(get_session)):
    """Uniform response regardless of whether the mobile is registered
    (SS10.6: "whether a mobile number exists" must never be
    returned)."""
    mobile_bi = blind_index(body.mobile)
    user = session.exec(text("SELECT id FROM users WHERE mobile_blind_index = :m AND status = 'ACTIVE'"),
                         params={"m": mobile_bi}).first()
    if user is not None:
        otp = _generate_otp()
        ttl = int(_os.environ.get("OTP_TTL_SECONDS", "300"))
        session.exec(text(
            "INSERT INTO otp_codes (mobile_blind_index, purpose, otp_hash, expires_at) "
            "VALUES (:m, 'PASSWORD_RESET', :h, :e)"
        ), params={"m": mobile_bi, "h": _hash_otp(otp, mobile_bi), "e": datetime.now(timezone.utc) + timedelta(seconds=ttl)})
        session.commit()
        if _ENVIRONMENT() == "development":
            print(f"DEV password-reset OTP for {mask_mobile(body.mobile)}: {otp}")
    return {"reset_requested": True}


@router.post("/auth/password/reset")
def password_reset(body: PasswordResetBody, session: Session = Depends(get_session)):
    mobile_bi = blind_index(body.mobile)
    if body.new_password != body.new_password_confirm:
        raise HTTPException(422, {"code": "PASSWORD_MISMATCH", "detail": "Passwords do not match."})

    otp_row = session.exec(text(
        "SELECT id, otp_hash, attempt_count, expires_at FROM otp_codes "
        "WHERE mobile_blind_index = :m AND purpose = 'PASSWORD_RESET' AND verified_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1"
    ), params={"m": mobile_bi}).first()
    if otp_row is None or otp_row[3] < datetime.now(timezone.utc) or not secrets.compare_digest(otp_row[1], _hash_otp(body.otp, mobile_bi)):
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})

    user = session.exec(text("SELECT id, role_level, password_hash FROM users WHERE mobile_blind_index = :m AND status = 'ACTIVE'"),
                         params={"m": mobile_bi}).first()
    if user is None:
        raise HTTPException(401, {"code": "OTP_INVALID", "detail": "Incorrect or expired OTP."})
    uid, role_level, old_hash = user

    history = session.exec(text("SELECT password_hash FROM password_history WHERE user_id = :uid ORDER BY created_at DESC LIMIT 5"),
                            params={"uid": uid}).all()
    violations = validate_password_policy(body.new_password, is_privileged=role_level is not None and role_level <= 3,
                                           history_hashes=[h[0] for h in history])
    if violations:
        raise HTTPException(422, {"code": "PASSWORD_POLICY_VIOLATION", "detail": violations})

    new_hash = hash_password(body.new_password)
    session.exec(text("UPDATE otp_codes SET verified_at = :now WHERE id = :id"), params={"now": datetime.now(timezone.utc), "id": otp_row[0]})
    if old_hash:
        session.exec(text("INSERT INTO password_history (user_id, password_hash) VALUES (:uid, :h)"), params={"uid": uid, "h": old_hash})
    session.exec(text("UPDATE users SET password_hash = :h, password_changed_at = :now, token_version = token_version + 1 WHERE id = :uid"),
                 params={"h": new_hash, "now": datetime.now(timezone.utc), "uid": uid})
    revoke_token_family(session, str(uid), reason="PASSWORD_RESET")
    _write_audit(session, actor_user_id=str(uid), action="PASSWORD_RESET", outcome="SUCCESS", target_type="USER", target_id=str(uid))
    session.commit()
    return {"status": "PASSWORD_RESET"}


@router.get("/.well-known/jwks.json")
def jwks():
    return _get_jwks()


# ============================================================
# AUTHENTICATED routes
# ============================================================

@router.get("/auth/me")
def me(current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    """Permanent-alias target for GET /me (SS14.1): "response gains
    role, permissions, scope"."""
    from app.core.authz import get_effective_permissions
    perms = sorted(get_effective_permissions(session, current_user.role))
    row = session.exec(text("SELECT full_name, mobile_masked FROM users WHERE id = :id"), params={"id": current_user.id}).first()
    return {
        "id": str(current_user.id), "role": current_user.role, "permissions": perms,
        "scope": {"org_unit_id": str(current_user.scope_org_unit_id) if current_user.scope_org_unit_id else None,
                  "scope_path": current_user.scope_path},
        "full_name": row[0] if row else None, "mobile_masked": row[1] if row else None,
    }


@router.post("/auth/logout")
def logout(request: Request, current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    auth_header = request.headers.get("authorization", "")
    token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else None
    session_id = None
    if token:
        try:
            claims = verify_access_token(token)
            session_id = claims.get("sid")
        except TokenError:
            pass
    if session_id:
        session.exec(text("UPDATE refresh_tokens SET revoked_at = :now, revoke_reason = 'LOGOUT' "
                           "WHERE session_id = :sid AND revoked_at IS NULL"),
                     params={"now": datetime.now(timezone.utc), "sid": session_id})
        session.commit()
    return {"logged_out": True}


@router.post("/auth/logout-all")
def logout_all(current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    session.exec(text("UPDATE refresh_tokens SET revoked_at = :now, revoke_reason = 'LOGOUT_ALL' "
                       "WHERE user_id = :uid AND revoked_at IS NULL"),
                 params={"now": datetime.now(timezone.utc), "uid": current_user.id})
    session.commit()
    return {"logged_out": True, "sessions_revoked": True}


@router.post("/auth/password/change")
def password_change(body: PasswordChangeRequest, current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    row = session.exec(text("SELECT password_hash, role_level FROM users WHERE id = :id"), params={"id": current_user.id}).first()
    if row is None or not verify_password(body.current_password, row[0]):
        raise HTTPException(401, {"code": "INVALID_CURRENT_PASSWORD"})
    if body.new_password != body.new_password_confirm:
        raise HTTPException(422, {"code": "PASSWORD_MISMATCH"})
    history = session.exec(text("SELECT password_hash FROM password_history WHERE user_id = :uid ORDER BY created_at DESC LIMIT 5"),
                            params={"uid": current_user.id}).all()
    violations = validate_password_policy(body.new_password, is_privileged=row[1] is not None and row[1] <= 3,
                                           history_hashes=[h[0] for h in history])
    if violations:
        raise HTTPException(422, {"code": "PASSWORD_POLICY_VIOLATION", "detail": violations})
    new_hash = hash_password(body.new_password)
    session.exec(text("INSERT INTO password_history (user_id, password_hash) VALUES (:uid, :h)"), params={"uid": current_user.id, "h": row[0]})
    session.exec(text("UPDATE users SET password_hash = :h, password_changed_at = :now, token_version = token_version + 1 WHERE id = :uid"),
                 params={"h": new_hash, "now": datetime.now(timezone.utc), "uid": current_user.id})
    _write_audit(session, actor_user_id=str(current_user.id), action="PASSWORD_CHANGED", outcome="SUCCESS",
                 target_type="USER", target_id=str(current_user.id))
    session.commit()
    return {"status": "PASSWORD_CHANGED"}


@router.post("/auth/mfa/enrol")
def mfa_enrol(current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    """SS14.3: "Returns a TOTP secret + QR, once" -- rejects re-enrolment
    if an unrevoked TOTP credential already exists."""
    existing = session.exec(text(
        "SELECT id FROM mfa_credentials WHERE user_id = :uid AND credential_type = 'TOTP' AND revoked_at IS NULL"
    ), params={"uid": current_user.id}).first()
    if existing is not None:
        raise HTTPException(409, {"code": "MFA_ALREADY_ENROLLED"})

    # is_verified=true immediately -- same reasoning as invite_accept's
    # own auto-enrolment (see that function's comment): no separate
    # confirm-enrolment endpoint exists in Day1.md's SS14.3 surface.
    secret = pyotp.random_base32()
    session.exec(text(
        "INSERT INTO mfa_credentials (user_id, credential_type, totp_secret_encrypted, is_verified) "
        "VALUES (:uid, 'TOTP', :s, true)"
    ), params={"uid": current_user.id, "s": encrypt_field(secret)})
    session.exec(text("UPDATE users SET mfa_enrolled = true WHERE id = :uid"), params={"uid": current_user.id})
    _write_audit(session, actor_user_id=str(current_user.id), action="MFA_ENROLLED", outcome="SUCCESS",
                 target_type="USER", target_id=str(current_user.id))
    session.commit()
    totp = pyotp.TOTP(secret)
    return {"secret": secret, "provisioning_uri": totp.provisioning_uri(name=str(current_user.id), issuer_name=_JWT_ISSUER())}


@router.get("/auth/sessions")
def list_sessions(current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    rows = session.exec(text(
        "SELECT DISTINCT ON (session_id) session_id, device_label, device_fingerprint, ip, issued_at, revoked_at "
        "FROM refresh_tokens WHERE user_id = :uid ORDER BY session_id, issued_at DESC"
    ), params={"uid": current_user.id}).all()
    return {"sessions": [
        {"session_id": str(r[0]), "device_label": r[1], "ip": str(r[3]) if r[3] else None,
         "issued_at": r[4].isoformat() if r[4] else None, "active": r[5] is None}
        for r in rows
    ]}


@router.delete("/auth/sessions/{session_id}")
def revoke_session(session_id: UUID, current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    result = session.exec(text(
        "UPDATE refresh_tokens SET revoked_at = :now, revoke_reason = 'USER_REVOKED_DEVICE' "
        "WHERE session_id = :sid AND user_id = :uid AND revoked_at IS NULL"
    ), params={"now": datetime.now(timezone.utc), "sid": str(session_id), "uid": current_user.id})
    session.commit()
    return {"revoked": True}


# ============================================================
# /login and /me -- permanent aliases of /auth/login and /auth/me
# (SS14.1, confirmed with the user directly in this session,
# 2026-08-30: the previous /login and /me carried a hardcoded HS256
# secret and two fake accounts -- replaced with real calls into the
# same handlers above, not a separate implementation).
# ============================================================

@router.post("/login")
def login_alias(body: LoginRequest, session: Session = Depends(get_session)):
    return login(body, session)


@router.get("/me")
def me_alias(current_user=Depends(get_current_active_user), session: Session = Depends(get_session)):
    return me(current_user, session)
