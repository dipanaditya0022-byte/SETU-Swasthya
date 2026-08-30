"""Creation gates, org-scope containment, and permission dependencies,
per Day1.md SS3.2 and SS4 (scope) and SS8.4 (permission model).

WHAT IS VERBATIM VS ADAPTED VS NEW -- read before reviewing:

- `CreationDenied` and `assert_can_create_user`'s four-gate body are
  SS3.2's own code, copied close to verbatim (see the sync-adaptation
  note below for the one necessary change).
- `org_unit_is_within_scope` is SS4.2's own code, including the exact
  trailing-slash protection SS4.2 itself calls out as the thing to
  regression-test first (`target_path.startswith(actor_path.rstrip("/")
  + "/")`).
- `require()` is SS8.4's own `require(*permissions)`, adapted.
- Two things are genuinely new here, not spec quotes:
    1. `get_current_active_user` -- SS8.4's own require()/require_scope()
       both call `Depends(get_current_active_user)` as something that
       already exists; nothing in Day1.md defines it. It's built here
       for real (Bearer token -> app.core.tokens.verify_access_token ->
       token_version check -> a live users row) so require()/
       require_scope_or_404() are actually testable as FastAPI
       dependencies, not just unit-testable Python functions.
    2. `get_effective_permissions` -- resolves a role's permission set
       from role_permissions (S11's real seed data), matching SS10.3's
       "server resolves permissions from cache keyed by [perms_hash]"
       framing at the resolution-logic level (an actual cache layer is
       out of scope here).

- Synchronous, not async: like app/core/tokens.py, this repo's actual
  DB layer (app/db/database.py) uses SQLModel's synchronous Session,
  confirmed by reading that file directly -- SS3.2/SS4.2/SS8.4's own
  code is all `async def`/`await session.exec(...)`. Adapted to
  synchronous functions throughout; no other change to the logic.

- 403 vs 404 for out-of-scope, resolved per this task's own explicit
  instruction, because Day1.md contains a genuine internal conflict
  here: SS8.4's own `require_scope` example raises `403 OUT_OF_SCOPE`.
  But SS16.2 (the authoritative error-contract section) states
  plainly: "Deliberate choice: 404, not 403, for out-of-scope
  records... Returning 403 for a record that exists elsewhere confirms
  its existence to an attacker probing IDs" -- and SS19's threat model
  (T3) says the same for "every write and read". SS16.3's codes table
  and SS19's Definition-of-Done checklist ("Cross-scope creation
  returns 403 OUT_OF_SCOPE") both confirm 403 specifically for
  *creation-time* scope failures (Gate 3 below -- there is no existing
  record to leak the existence of when you're asking "may I create
  something here"). So: `assert_can_create_user`'s Gate 3 keeps SS3.2's
  own 403 OUT_OF_SCOPE; a new `require_scope_or_404` (distinct from a
  literal reproduction of SS8.4's `require_scope`) is provided for
  *existing-record* access and returns 404, matching SS16.2/T3 and this
  task's own instruction.

- "Do not assume an ancestor can create every descendant" (this task's
  own instruction, matching SS3's own framing): Gate 2 below is the
  ONLY source of creation authority -- an explicit role_creation_grants
  row. Nothing here ever infers "may create" from org-unit ancestry,
  ROLE_LEVEL ordering, or a reports_to chain. ROLE_LEVEL is used only
  in Gate 4, and only as a belt-and-braces sanity check on top of an
  already-passed Gate 2, exactly as SS3.2 states ("Gate 4 exists even
  though Gate 2 already passed... turns that data error into a
  rejected request rather than a privilege escalation").
"""
from __future__ import annotations

from typing import Callable, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session, text

from app.core.audit import compute_row_hash
from app.core.tokens import InvalidTokenVersion, TokenError, verify_access_token
from app.db.database import get_session
from app.models.enums import ROLE_LEVEL, RoleCode


class CreationDenied(Exception):
    """Verbatim shape, Day1.md SS3.2."""
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail


# ============================================================
# Gate 3 support -- SS4.2, verbatim (sync-adapted).
# ============================================================

def org_unit_is_within_scope(session: Session, target_id: UUID, actor_scope_id: Optional[UUID]) -> bool:
    """True if target is the actor's own unit or any descendant of it.
    Fails closed: a missing scope (actor_scope_id is None -- e.g.
    SUPERUSER, which SS13.2's chk_scope_required exempts from having
    one) or a missing/unknown org unit returns False, never True."""
    if actor_scope_id is None:
        return False
    rows = session.exec(
        text("SELECT id, path FROM org_units WHERE id = :target_id OR id = :actor_id"),
        params={"target_id": str(target_id), "actor_id": str(actor_scope_id)},
    ).all()
    paths = {str(row[0]): row[1] for row in rows}
    target_path = paths.get(str(target_id))
    actor_path = paths.get(str(actor_scope_id))
    if target_path is None or actor_path is None:
        return False
    # Trailing-slash bug to avoid (SS4.2's own regression-test warning):
    # without rstrip("/") + "/", "/UP/KANPUR2" would match the prefix
    # "/UP/KANPUR" and a Kanpur Nagar officer would silently gain scope
    # over Kanpur Dehat.
    return target_path == actor_path or target_path.startswith(actor_path.rstrip("/") + "/")


# ============================================================
# The four creation gates -- SS3.2, verbatim (sync-adapted).
# ============================================================

def get_creation_grant(session: Session, creator_role: str, target_role: str):
    """Gate 2 support. Returns the role_creation_grants row (as a
    lightweight object with .requires_second_approver and
    .allowed_org_unit_types) or None if no such grant exists. This is
    the ONLY source of creation authority this module consults -- see
    module docstring."""
    row = session.exec(
        text(
            "SELECT requires_second_approver, allowed_org_unit_types "
            "FROM role_creation_grants WHERE creator_role = :c AND target_role = :t"
        ),
        params={"c": creator_role, "t": target_role},
    ).first()
    if row is None:
        return None

    class _Grant:
        def __init__(self, requires_second_approver, allowed_org_unit_types):
            self.requires_second_approver = requires_second_approver
            self.allowed_org_unit_types = allowed_org_unit_types

    return _Grant(row[0], row[1])


def assert_can_create_user(
    session: Session, actor, target_role: RoleCode, target_org_unit_id: UUID
) -> bool:
    """
    Four independent gates. All must pass. Order matters: cheapest and
    most common failure first, so a probing attacker learns as little
    as possible. `actor` is expected to expose .status, .mfa_required,
    .mfa_enrolled, .role, .scope_org_unit_id (a live users row).
    Returns requires_second_approver on success; raises CreationDenied
    on any gate failure.
    """
    # GATE 1 -- the actor's account must itself be usable
    if actor.status != "ACTIVE":
        raise CreationDenied("ACTOR_NOT_ACTIVE", "Your account is not active.")
    if actor.mfa_required and not actor.mfa_enrolled:
        raise CreationDenied("MFA_REQUIRED", "Enrol MFA before creating users.")

    # GATE 2 -- an explicit grant row must exist. No implicit level comparison.
    grant = get_creation_grant(session, actor.role, target_role.value if isinstance(target_role, RoleCode) else target_role)
    if grant is None:
        raise CreationDenied(
            "ROLE_NOT_CREATABLE",
            f"{actor.role} may not create {target_role}.",
        )

    # GATE 3 -- org scope containment. The target posting must sit inside
    # the actor's subtree. A Rampur BMO cannot create staff in Bilhaur block.
    if not org_unit_is_within_scope(session, target_org_unit_id, actor.scope_org_unit_id):
        raise CreationDenied(
            "OUT_OF_SCOPE",
            "That posting is outside the area you manage.",
        )

    # GATE 4 -- level sanity. Belt-and-braces against a bad grant row.
    # SUPERUSER is the only role permitted to create at its own level.
    target_role_enum = target_role if isinstance(target_role, RoleCode) else RoleCode(target_role)
    actor_role_enum = actor.role if isinstance(actor.role, RoleCode) else RoleCode(actor.role)
    if actor_role_enum != RoleCode.SUPERUSER:
        if ROLE_LEVEL[target_role_enum] <= ROLE_LEVEL[actor_role_enum]:
            raise CreationDenied(
                "LEVEL_VIOLATION",
                "You cannot create a role at or above your own level.",
            )

    return grant.requires_second_approver


# ============================================================
# Auth/permission dependencies -- SS8.4, adapted (see module docstring).
# ============================================================

def _audit_denied(session: Session, actor_user_id: Optional[str], action: str, detail: dict) -> None:
    """Minimal real audit_log writer, hash-chained via S9's
    compute_row_hash -- same pattern as app/core/tokens.py's
    _write_audit_log, kept local here rather than imported since it's
    a private helper in that module too."""
    import json
    from datetime import datetime, timezone

    prev_hash_row = session.exec(
        text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    ).first()
    prev_hash = prev_hash_row[0] if prev_hash_row else None
    occurred_at = datetime.now(timezone.utc)
    entry = {
        "occurred_at": occurred_at, "actor_user_id": actor_user_id,
        "action": action, "outcome": "DENIED",
        "target_type": None, "target_id": None, "metadata": detail,
    }
    row_hash = compute_row_hash(entry, prev_hash)
    session.exec(
        text(
            "INSERT INTO audit_log (occurred_at, actor_user_id, action, outcome, "
            "metadata, prev_hash, row_hash) "
            "VALUES (:occurred_at, :actor_user_id, :action, 'DENIED', :metadata, :prev_hash, :row_hash)"
        ),
        params={
            "occurred_at": occurred_at, "actor_user_id": actor_user_id,
            "action": action, "metadata": json.dumps(detail),
            "prev_hash": prev_hash, "row_hash": row_hash,
        },
    )
    session.commit()


def get_current_active_user(
    authorization: str = Header(...),
    session: Session = Depends(get_session),
):
    """New glue code (see module docstring) -- resolves the bearer token
    to a live, ACTIVE users row: verifies RS256 signature/issuer/
    audience/expiry, checks token_version against the live row (SS10.3:
    "a token with a stale ver is rejected... a demotion takes effect
    within milliseconds"), and confirms status == ACTIVE. Fails closed:
    any problem raises 401, never returns a partially-valid user."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, {"code": "INVALID_TOKEN", "detail": "Missing bearer token."})
    token = authorization[len("Bearer "):]
    try:
        claims = verify_access_token(token)
    except TokenError:
        raise HTTPException(401, {"code": "INVALID_TOKEN", "detail": "Invalid or expired token."})

    row = session.exec(
        text(
            "SELECT id, status, role, role_level, scope_org_unit_id, scope_path, "
            "token_version, mfa_required, mfa_enrolled "
            "FROM users WHERE id = :id"
        ),
        params={"id": claims.get("sub")},
    ).first()
    if row is None:
        raise HTTPException(401, {"code": "INVALID_TOKEN", "detail": "Account no longer exists."})

    class _CurrentUser:
        def __init__(self, r):
            (self.id, self.status, self.role, self.role_level, self.scope_org_unit_id,
             self.scope_path, self.token_version, self.mfa_required, self.mfa_enrolled) = r

    user = _CurrentUser(row)
    try:
        from app.core.tokens import check_token_version
        check_token_version(claims, user.token_version)
    except InvalidTokenVersion:
        raise HTTPException(401, {"code": "INVALID_TOKEN", "detail": "Token has been superseded."})

    if user.status != "ACTIVE":
        raise HTTPException(401, {"code": "ACCOUNT_NOT_ACTIVE", "detail": "Account is not active."})

    return user


def get_effective_permissions(session: Session, role: str) -> set[str]:
    """Resolves a role's granted permission codes from role_permissions
    (S11's real seed data). Fails closed: an unrecognised role or a DB
    miss returns an empty set, never "everything"."""
    rows = session.exec(
        text("SELECT permission_code FROM role_permissions WHERE role_code = :r"),
        params={"r": role},
    ).all()
    return {row[0] for row in rows}


def require(*permissions: str) -> Callable:
    """FastAPI dependency factory. Fails closed: any permission not in
    the actor's effective set is a 403, with no indication of *which*
    permission was missing in the response body (Day1.md SS10.6: "Which
    specific permission was missing on a 403" must never be returned --
    "that would map the permission model for an attacker"). SS8.4's own
    `require(*permissions)`, adapted to synchronous dependencies."""
    def _check(
        current_user=Depends(get_current_active_user),
        session: Session = Depends(get_session),
    ):
        granted = get_effective_permissions(session, current_user.role)
        missing = [p for p in permissions if p not in granted]
        if missing:
            _audit_denied(session, str(current_user.id), "PERMISSION_DENIED",
                           {"required": list(permissions)})
            raise HTTPException(403, {
                "code": "PERMISSION_DENIED",
                "detail": "You do not have permission to do this.",
            })
        return current_user
    return _check


def require_scope_or_404(get_org_unit_id: Callable[[Request], UUID]) -> Callable:
    """FastAPI dependency factory for EXISTING-RECORD access (not
    creation -- see module docstring for the 403-vs-404 distinction and
    why this deliberately diverges from SS8.4's own `require_scope`
    example, which uses 403). `get_org_unit_id` extracts the target
    record's org_unit_id from the request (e.g. by looking up the
    record first) -- callers are responsible for that lookup; this
    dependency only gates on the result. Fails closed as 404 either
    way, whether the record doesn't exist or exists outside scope --
    identical response, so neither case leaks information the other
    doesn't (SS16.2's own reasoning)."""
    def _check(
        request: Request,
        current_user=Depends(get_current_active_user),
        session: Session = Depends(get_session),
    ):
        target_org = get_org_unit_id(request)
        if target_org is None or not org_unit_is_within_scope(
            session, target_org, current_user.scope_org_unit_id
        ):
            _audit_denied(session, str(current_user.id), "OUT_OF_SCOPE_ACCESS",
                           {"target_org_unit_id": str(target_org) if target_org else None})
            raise HTTPException(404, {"code": "NOT_FOUND", "detail": "Not found."})
        return current_user
    return _check
