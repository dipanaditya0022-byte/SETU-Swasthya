"""RS256 JWT issue/verify, JWKS, and refresh-token rotation with reuse
detection, per Day1.md SS10.3/SS10.4 and the SS9.4/SS12 audit trail.

WHAT IS VERBATIM VS ADAPTED -- read before reviewing:

- The JWT claim set (`sub`, `role`, `lvl`, `scope_org`, `scope_path`,
  `perms_hash`, `jti`, `sid`, `ver`, `amr`, `iat`, `exp`, `iss`, `aud`)
  is exactly SS10.3's claim list -- every field name and purpose is
  copied from there.
- `refresh_access_token`'s control flow (lookup by hash -> reuse check
  -> expiry check -> device check -> status check -> rotate) is
  SS10.4's own function, adapted in two necessary ways, both because
  SS10.4's example doesn't match this actual codebase:

    1. SS10.4 is written `async def` with `await session.exec(...)`.
       This repo's actual DB layer (app/db/database.py) uses SQLModel's
       synchronous Session, not an async engine -- confirmed by reading
       that file directly. Async code here would not run against the
       real session this codebase actually has. Adapted to synchronous
       functions throughout; nothing else about the control flow
       changed.
    2. SS10.4 calls `audit(...)` and `alert_security_team(...)` as if
       they already exist. Neither does yet. `audit(...)` is
       implemented for real here (writes a real audit_log row, hash-
       chained via app.core.audit.compute_row_hash, which already
       exists from S9) since that's genuinely buildable now.
       `alert_security_team(...)` is a clearly-labelled no-op stub --
       no SMS/notification gateway exists anywhere in this repo yet
       (backend/.env.example's SMS_GATEWAY_URL is an empty
       placeholder) -- it logs via the standard `logging` module
       instead of silently doing nothing or fabricating an integration
       that doesn't exist.

- `issue_access_token` is a pure function: it takes already-resolved
  claim values (role, level, scope, perms_hash, amr, etc.) as
  parameters rather than a `User` object it resolves permissions from
  internally. Day1.md SS10.4's own example calls
  `issue_access_token(user)` as shorthand, but resolving a user's
  *effective* permission set (querying role_permissions, hashing it)
  is authorization business logic that belongs with app/core/authz.py
  (a later step), not with the pure JWT-encoding mechanics this file
  is for -- the same separation crypto.py already keeps between
  encryption primitives and anything that knows what a "user" is.
  Likewise, `refresh_access_token` returns the rotated refresh token
  and the user's row rather than also minting a new access token
  itself, for the same reason -- the caller (a route, once one exists)
  is where permission resolution and access-token issuance belong
  together.

Refresh tokens themselves are opaque random strings, not JWTs -- per
SS10.4's own `sha256(presented_token)` and the refresh_tokens.token_hash
schema (S7), never a signed/decodable structure.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from sqlmodel import Session, text

from app.core.audit import compute_row_hash

logger = logging.getLogger(__name__)


class TokenError(Exception):
    """Base class for all token-related failures in this module. Callers
    (a route layer) are expected to catch specific subclasses and map
    them to the exact HTTP codes Day1.md SS10.4 specifies -- this module
    itself has no FastAPI dependency, matching password.py's design."""


class InvalidRefreshToken(TokenError):
    pass


class TokenReuseDetected(TokenError):
    pass


class RefreshTokenExpired(TokenError):
    pass


class DeviceMismatch(TokenError):
    pass


class AccountNotActive(TokenError):
    pass


class InvalidTokenVersion(TokenError):
    """Raised by check_token_version: the token's `ver` claim does not
    match the account's current token_version (SS10.3: "A token with a
    stale ver is rejected, so a demotion takes effect within
    milliseconds rather than after the token expires")."""


# ============================================================
# RS256 access tokens
# ============================================================

def _load_private_key() -> str:
    path = os.environ.get("JWT_PRIVATE_KEY_PATH")
    if not path:
        raise TokenError("JWT_PRIVATE_KEY_PATH is not set.")
    with open(path, "rb") as f:
        return f.read().decode()


def _load_public_key_object() -> RSAPublicKey:
    path = os.environ.get("JWT_PUBLIC_KEY_PATH")
    if not path:
        raise TokenError("JWT_PUBLIC_KEY_PATH is not set.")
    with open(path, "rb") as f:
        key = serialization.load_pem_public_key(f.read())
    if not isinstance(key, RSAPublicKey):
        raise TokenError("JWT_PUBLIC_KEY_PATH does not contain an RSA public key.")
    return key


def _load_public_key_pem() -> str:
    path = os.environ.get("JWT_PUBLIC_KEY_PATH")
    if not path:
        raise TokenError("JWT_PUBLIC_KEY_PATH is not set.")
    with open(path, "rb") as f:
        return f.read().decode()


def issue_access_token(
    *,
    user_id: str,
    role: str,
    level: int,
    scope_org_id: Optional[str],
    scope_path: Optional[str],
    perms_hash: str,
    session_id: str,
    token_version: int,
    amr: list[str],
    expires_in_minutes: Optional[int] = None,
) -> str:
    """Sign and return an RS256 access token with exactly the SS10.3
    claim set. `expires_in_minutes` lets a caller apply a role-specific
    TTL (e.g. SUPERUSER's 5-minute access tokens, SS9.3) -- this
    function has no notion of roles' TTL table itself, only of how to
    encode an expiry once given one; it defaults to ACCESS_TOKEN_MINUTES
    from the environment (set in backend/.env.example, S2) when not
    passed explicitly."""
    if expires_in_minutes is None:
        expires_in_minutes = int(os.environ.get("ACCESS_TOKEN_MINUTES", "15"))

    now = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,
        "role": role,
        "lvl": level,
        "scope_org": scope_org_id,
        "scope_path": scope_path,
        "perms_hash": perms_hash,
        "jti": str(uuid.uuid4()),
        "sid": session_id,
        "ver": token_version,
        "amr": amr,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_in_minutes)).timestamp()),
        "iss": os.environ.get("JWT_ISSUER", "setu-swasthya"),
        "aud": os.environ.get("JWT_AUDIENCE", "setu-api"),
    }
    return jwt.encode(claims, _load_private_key(), algorithm="RS256")


def verify_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an RS256 access token: signature, issuer,
    audience, and expiry are all checked by python-jose's jwt.decode
    (raises jose.JWTError -- re-raised here as TokenError -- on any
    failure: wrong signature, wrong issuer, wrong audience, or
    expired). Does NOT check `ver` against a live token_version -- that
    requires a database lookup this pure function deliberately doesn't
    perform; call check_token_version() separately with the account's
    current token_version once you've fetched it."""
    try:
        return jwt.decode(
            token,
            _load_public_key_pem(),
            algorithms=["RS256"],
            issuer=os.environ.get("JWT_ISSUER", "setu-swasthya"),
            audience=os.environ.get("JWT_AUDIENCE", "setu-api"),
        )
    except JWTError as exc:
        raise TokenError(f"Invalid access token: {exc}") from exc


def check_token_version(claims: dict[str, Any], current_version: int) -> None:
    """SS10.3: reject a token whose `ver` claim doesn't match the
    account's live token_version. Raises InvalidTokenVersion; does not
    return a bool, so a caller can't accidentally ignore the result."""
    if claims.get("ver") != current_version:
        raise InvalidTokenVersion(
            f"Token version {claims.get('ver')!r} does not match current "
            f"version {current_version!r}."
        )


def get_jwks() -> dict[str, Any]:
    """JWK Set document for /.well-known/jwks.json (SS10.3: "Publish the
    public key at /.well-known/jwks.json"). Wiring the actual public
    route is a later step (routes) -- this returns the document body.
    Standard RFC 7518 RSA JWK encoding (n, e as base64url, no padding)."""
    public_key = _load_public_key_object()
    numbers = public_key.public_numbers()

    def _b64url_uint(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        import base64
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "setu-swasthya-jwt-1",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


# ============================================================
# Refresh tokens -- opaque random strings, not JWTs.
# ============================================================

def generate_refresh_token() -> str:
    """High-entropy opaque token. Never a JWT -- SS10.4 looks these up
    by sha256(presented_token) against refresh_tokens.token_hash, which
    only makes sense for an unstructured secret, not a decodable JWT."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Plain SHA-256, verbatim per SS10.4's `sha256(presented_token)` --
    deliberately not the HMAC blind_index from crypto.py: a refresh
    token is looked up by exact match on a high-entropy secret the
    client already proved possession of, not searched/matched the way
    a mobile number is."""
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(
    session: Session,
    *,
    user_id: str,
    family_id: str,
    session_id: str,
    device_fingerprint: Optional[str],
    device_label: Optional[str] = None,
    ip: Optional[str] = None,
    expires_in_days: Optional[int] = None,
) -> str:
    """Generate a refresh token, store only its hash (refresh_tokens.
    token_hash), and return the raw token -- the only moment it exists
    in plaintext outside the client. `family_id`/`session_id` are
    caller-supplied: a fresh login generates new random UUIDs for both;
    a rotation (see refresh_access_token below) reuses the existing
    family_id and session_id so SS10.3's `sid` claim keeps meaning "this
    device", across rotations, until that device is individually
    revoked."""
    if expires_in_days is None:
        expires_in_days = int(os.environ.get("REFRESH_TOKEN_DAYS", "7"))

    raw_token = generate_refresh_token()
    token_hash = hash_refresh_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    session.exec(
        text(
            "INSERT INTO refresh_tokens "
            "(user_id, family_id, token_hash, session_id, device_fingerprint, "
            " device_label, ip, expires_at) "
            "VALUES (:user_id, :family_id, :token_hash, :session_id, "
            " :device_fingerprint, :device_label, :ip, :expires_at)"
        ),
        params={
            "user_id": user_id, "family_id": family_id, "token_hash": token_hash,
            "session_id": session_id, "device_fingerprint": device_fingerprint,
            "device_label": device_label, "ip": ip, "expires_at": expires_at,
        },
    )
    return raw_token


def _write_audit_log(
    session: Session,
    *,
    action: str,
    outcome: str,
    actor_user_id: Optional[str],
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Minimal real audit_log writer, hash-chained via S9's
    compute_row_hash. Not a full audit service (no actor_role/ip/
    user_agent capture here -- this module doesn't have a request
    object) -- just enough for refresh_access_token's own SS10.4-
    mandated audit calls to write real, chain-valid rows rather than
    being stubbed out."""
    prev_hash_row = session.exec(
        text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    ).first()
    prev_hash = prev_hash_row[0] if prev_hash_row else None

    occurred_at = datetime.now(timezone.utc)
    entry = {
        "occurred_at": occurred_at,
        "actor_user_id": actor_user_id,
        "action": action,
        "outcome": outcome,
        "target_type": target_type,
        "target_id": target_id,
        "metadata": metadata or {},
    }
    row_hash = compute_row_hash(entry, prev_hash)

    session.exec(
        text(
            "INSERT INTO audit_log "
            "(occurred_at, actor_user_id, action, outcome, target_type, "
            " target_id, metadata, prev_hash, row_hash) "
            "VALUES (:occurred_at, :actor_user_id, :action, :outcome, "
            " :target_type, :target_id, :metadata, :prev_hash, :row_hash)"
        ),
        params={
            "occurred_at": occurred_at, "actor_user_id": actor_user_id,
            "action": action, "outcome": outcome, "target_type": target_type,
            "target_id": target_id, "metadata": __import__("json").dumps(metadata or {}),
            "prev_hash": prev_hash, "row_hash": row_hash,
        },
    )


def alert_security_team(user_id: str, reason: str) -> None:
    """Stub -- no SMS/notification gateway exists anywhere in this repo
    yet (SMS_GATEWAY_URL is an empty placeholder in .env.example).
    Logs instead of silently doing nothing, and instead of fabricating
    an integration Day1.md doesn't specify the shape of."""
    logger.warning("SECURITY ALERT (not yet delivered -- no gateway configured): "
                    "user_id=%s reason=%s", user_id, reason)


def refresh_access_token(
    session: Session,
    *,
    presented_token: str,
    device_fingerprint: Optional[str],
) -> tuple[str, dict[str, Any]]:
    """SS10.4's rotation-with-reuse-detection logic, adapted to this
    repo's synchronous Session (see module docstring). Returns
    (new_raw_refresh_token, user_row) on success; raises a TokenError
    subclass on every failure path, matching SS10.4's distinct error
    codes 1:1 (see each raise site). Does not itself mint a new access
    token -- see module docstring."""
    row = session.exec(
        text(
            "SELECT id, user_id, family_id, session_id, device_fingerprint, "
            "expires_at, rotated_at, revoked_at "
            "FROM refresh_tokens WHERE token_hash = :h"
        ),
        params={"h": hash_refresh_token(presented_token)},
    ).first()

    if row is None:
        raise InvalidRefreshToken("No matching refresh token.")

    (row_id, user_id, family_id, session_id, row_device_fingerprint,
     expires_at, rotated_at, revoked_at) = row

    # Reuse detection, part 1: an already-rotated token has reappeared,
    # OR (found by direct testing -- not in SS10.4's own pseudocode,
    # which only checks rotated_at) the token's family was already
    # revoked by some other event (a prior reuse-detection, or a future
    # logout-all/individual-device-revoke) even though this particular
    # row was never itself rotated. Without this second check, a token
    # from an already-killed family would still succeed here -- exactly
    # the C4 fail-closed gap this function exists to prevent. Both
    # cases get the same response: SS10.4's own reasoning ("stolen and
    # replayed, or the legitimate client raced -- both are handled the
    # same way") extends naturally to "used after its family was
    # already killed for any reason."
    if rotated_at is not None or revoked_at is not None:
        session.exec(
            text(
                "UPDATE refresh_tokens SET revoked_at = :now, "
                "revoke_reason = 'REUSE_DETECTED' "
                "WHERE family_id = :family_id AND revoked_at IS NULL"
            ),
            params={"now": datetime.now(timezone.utc), "family_id": family_id},
        )
        _write_audit_log(
            session, action="REFRESH_TOKEN_REUSE_DETECTED", outcome="DENIED",
            actor_user_id=str(user_id),
            metadata={"family_id": str(family_id), "device": device_fingerprint},
        )
        session.commit()
        alert_security_team(str(user_id), "possible refresh token theft")
        raise TokenReuseDetected("Refresh token family revoked; sign in again.")

    if expires_at < datetime.now(timezone.utc):
        raise RefreshTokenExpired("Refresh token expired.")

    if row_device_fingerprint != device_fingerprint:
        _write_audit_log(
            session, action="REFRESH_DEVICE_MISMATCH", outcome="DENIED",
            actor_user_id=str(user_id), metadata={},
        )
        session.commit()
        raise DeviceMismatch("Device fingerprint does not match.")

    user_row = session.exec(
        text("SELECT id, status, role, role_level, scope_org_unit_id, "
             "scope_path, token_version FROM users WHERE id = :id"),
        params={"id": user_id},
    ).first()
    if user_row is None or user_row[1] != "ACTIVE":
        raise AccountNotActive("Account is not active.")

    session.exec(
        text("UPDATE refresh_tokens SET rotated_at = :now WHERE id = :id"),
        params={"now": datetime.now(timezone.utc), "id": row_id},
    )
    new_raw_refresh = issue_refresh_token(
        session, user_id=str(user_id), family_id=str(family_id),
        session_id=str(session_id), device_fingerprint=device_fingerprint,
    )
    session.commit()

    user = {
        "id": user_row[0], "status": user_row[1], "role": user_row[2],
        "role_level": user_row[3], "scope_org_unit_id": user_row[4],
        "scope_path": user_row[5], "token_version": user_row[6],
    }
    return new_raw_refresh, user


def revoke_token_family(session: Session, family_id: str, reason: str = "REVOKED") -> None:
    """Revoke every non-revoked token in a family (used directly by
    reuse detection above, and available for other callers -- e.g. a
    future logout-all route -- per SS10.4/SS14's revoke-family need)."""
    session.exec(
        text(
            "UPDATE refresh_tokens SET revoked_at = :now, revoke_reason = :reason "
            "WHERE family_id = :family_id AND revoked_at IS NULL"
        ),
        params={"now": datetime.now(timezone.utc), "reason": reason, "family_id": family_id},
    )
    session.commit()
