"""Rate limiting (deployment-hardening task). `slowapi` was already an
installed dependency (requirements.txt) but never wired into the app --
app/api/routes/auth.py's own module docstring flags this exact gap
("Rate limiting (SS14.2's per-route limits): NOT implemented in this
file... a follow-up step should wire this in before this goes anywhere
near production traffic"). This module is that follow-up.

Per-route limits (this task's own spec):
  POST /login, /auth/login          20 per 15 min per IP
  POST /auth/otp/request             5/hour per mobile, 20/hour per IP
  POST /auth/patient/register        3/hour per mobile
  POST /sync/                        60/hour per user
  everything else                    300/min per user

Every 429 carries a real `Retry-After` header (never a dropped
connection).

===========================================================================
REAL BUG FOUND LIVE -- slowapi's OWN `SlowAPIMiddleware` + `default_limits`
combination does not work in this app, confirmed empirically, not assumed
===========================================================================
The five explicitly-decorated routes below (`@limiter.limit(...)` on
login/otp/patient-register/sync) work correctly -- confirmed live: hammering
POST /login past 20/15min produces a real 429 with a real Retry-After
header. But the "everything else: 300/min per user" CATCH-ALL, wired the
"normal" slowapi way (`Limiter(default_limits=["300/minute"], ...)` +
`app.add_middleware(SlowAPIMiddleware)`), did NOT work: 305 consecutive
requests to an undecorated route (`GET /me`) all returned 200, with NO
`X-RateLimit-*` headers ever appearing at all -- meaning slowapi's own
middleware-side default-limit check was never actually being applied,
despite `Limiter._check_request_limit`'s own source (read directly,
installed version slowapi==0.1.10) appearing to show it should. Root cause
not fully isolated inside slowapi's own internals (a `BaseHTTPMiddleware`-
based `SlowAPIMiddleware` combined with this app's own ASGI middleware
stack is the leading suspect, but not confirmed further -- not worth more
time chasing a third-party library's own bug when a direct, verifiable fix
is available).

FIX: the five explicitly-decorated routes still use slowapi's own
decorator mechanism (`@limiter.limit(...)`, proven working). The catch-all
is implemented directly, below, as `DefaultRateLimitMiddleware` -- calling
slowapi's own underlying `limiter.limiter.hit(...)`/`.get_window_stats(...)`
(the real `limits`-library `FixedWindowRateLimiter`, the same storage
`SlowAPIMiddleware` itself would have used) from a small, self-contained
ASGI middleware, bypassing only the specific broken integration layer.
Verified live after this fix -- see this task's own delivery report.
===========================================================================
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from limits import parse as parse_limit
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import get_request_id
from app.core.security_headers import SECURITY_HEADERS

logger = logging.getLogger(__name__)


def user_or_ip_key(request: Request) -> str:
    """Default key for the global catch-all ("everything else: 300/min
    per user"). Prefers the authenticated actor's own id -- stashed onto
    `request.state.user_id` by `app.core.authz.get_current_active_user`
    (see that function's own comment for why: FastAPI resolves ALL of a
    route's `Depends(...)` -- including the auth dependency -- BEFORE
    calling the (rate-limit-decorated) route function itself, so by the
    time slowapi's key_func runs, `request.state.user_id` is already
    set for any route that actually requires auth). Falls back to the
    client's IP for routes with no authenticated user yet (public
    routes, or a request whose token never resolved to a user)."""
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


def mobile_key(request: Request) -> str:
    """Per-mobile key for OTP-request / patient-registration limits --
    the task's own spec keys these on the submitted mobile number, not
    IP, so one phone number can't be hammered from many different IPs.

    slowapi calls key_func(request) SYNCHRONOUSLY (confirmed against the
    installed slowapi==0.1.10 source: `Limiter`'s own dispatch does
    `lim.key_func(request)` with no await) -- Starlette's own
    `Request.json()` is async-only, so a synchronous key_func can't call
    it directly. Reads the raw body bytes Starlette ALREADY cached on
    `request._body` instead: FastAPI resolves a route's own
    `body: OtpRequestBody`/`PatientRegistrationRequest` parameter (which
    internally reads the request body) as part of dependency resolution,
    which completes BEFORE the (rate-limit-wrapped) route function is
    ever invoked -- so by the time this key_func runs, the bytes are
    already buffered in memory; this is a second read of an
    already-cached value, not a second read of the network stream, and
    does not interfere with FastAPI's own subsequent Pydantic parsing.
    Falls back to per-IP if the body isn't cached for any reason (e.g. a
    malformed request that never reaches body parsing), rather than
    raising and breaking the request."""
    try:
        raw: Optional[bytes] = getattr(request, "_body", None)
        if raw:
            payload = json.loads(raw)
            mobile = payload.get("mobile")
            if mobile:
                return f"mobile:{mobile}"
    except Exception:  # noqa: BLE001 -- a rate-limit key derivation must never break the request
        logger.warning("mobile_key: could not extract mobile from body, falling back to IP", exc_info=True)
    return f"ip:{get_remote_address(request)}"


# The Limiter -- backs the five explicitly-decorated routes'
# @limiter.limit(...) checks (proven working live). headers_enabled=True
# is REQUIRED for those decorated routes' own Retry-After/X-RateLimit-*
# headers to be added at all (confirmed: defaults to False in
# slowapi==0.1.10). No `default_limits` here any more -- see this
# module's own "REAL BUG FOUND LIVE" docstring above for why the catch-all
# is handled separately, by DefaultRateLimitMiddleware below, instead.
limiter = Limiter(
    key_func=user_or_ip_key,
    headers_enabled=True,
)

# Routes with their OWN @limiter.limit(...) decorator -- DefaultRateLimitMiddleware
# skips these by path, so a request never gets counted against BOTH its
# own specific limit AND the catch-all in the same request.
_EXPLICITLY_LIMITED_PATHS = {
    "/login", "/auth/login", "/auth/otp/request", "/auth/patient/register", "/sync/",
}

_DEFAULT_LIMIT = parse_limit("300/minute")


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Handler for the FIVE explicitly-decorated routes' own
    @limiter.limit(...) violations (confirmed live: this path works).
    This app's own {"error": {...}} envelope, not slowapi's default bare
    {"error": "Rate limit exceeded: ..."} string -- but reuses slowapi's
    OWN `_inject_headers` (the same mechanism its own default
    `_rate_limit_exceeded_handler` uses) to get a correct Retry-After +
    X-RateLimit-* header set, rather than recomputing the rate-limit
    window by hand."""
    request_id = get_request_id(request)
    response = JSONResponse(
        status_code=429,
        content={"error": {
            "code": "RATE_LIMITED",
            "message": "Too many requests. Please slow down and try again shortly.",
            "request_id": request_id,
        }},
        headers={**SECURITY_HEADERS, "X-Request-ID": request_id},
    )
    response = request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)
    return response


def _identity_key_from_scope(scope: Scope) -> str:
    """Same identity preference as `user_or_ip_key` (authenticated user
    over IP), but derived directly from the ASGI scope rather than a
    FastAPI `Request`/`request.state.user_id` -- this middleware runs
    BEFORE routing/dependency-resolution, so `get_current_active_user`
    has not run yet and `request.state.user_id` does not exist at this
    point. Decodes the bearer token's own `sub` claim WITHOUT signature
    verification -- this is a RATE-LIMIT BUCKETING KEY ONLY, not a trust
    decision; the real, fully-verified auth check still happens later in
    the normal request lifecycle regardless of what key this middleware
    picked. Worst case if someone forges a `sub` to dodge this specific
    limit: they get their own separate bucket -- a minor gaming
    possibility, not a security hole."""
    headers = dict(scope.get("headers") or [])
    auth_header = headers.get(b"authorization", b"").decode("latin-1", errors="ignore")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            from jose import jwt as _jose_jwt
            claims = _jose_jwt.get_unverified_claims(token)
            sub = claims.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001 -- malformed/garbage token -- fall back to IP below
            pass
    client = scope.get("client")
    ip = client[0] if client else "unknown"
    return f"ip:{ip}"


class DefaultRateLimitMiddleware:
    """"Everything else: 300/min per user" -- see this module's own
    "REAL BUG FOUND LIVE" docstring for why this is a direct, self-
    contained ASGI middleware rather than slowapi's own
    `SlowAPIMiddleware` + `default_limits` (confirmed broken in this
    app). Uses slowapi's own underlying `limiter.limiter` (the real
    `limits`-library `FixedWindowRateLimiter` + storage) directly, so
    this shares the exact same counting backend/algorithm the five
    decorated routes use -- not a second, parallel rate-limit
    implementation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in _EXPLICITLY_LIMITED_PATHS:
            await self.app(scope, receive, send)
            return

        key = _identity_key_from_scope(scope)
        allowed = limiter.limiter.hit(_DEFAULT_LIMIT, key)
        window_reset, window_remaining = limiter.limiter.get_window_stats(_DEFAULT_LIMIT, key)

        if not allowed:
            request_id = (scope.get("state") or {}).get("request_id", "-")
            body = json.dumps({"error": {
                "code": "RATE_LIMITED",
                "message": "Too many requests. Please slow down and try again shortly.",
                "request_id": request_id,
            }}).encode()
            headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in SECURITY_HEADERS.items()]
            headers.append((b"x-request-id", request_id.encode("latin-1")))
            headers.append((b"x-ratelimit-limit", str(_DEFAULT_LIMIT.amount).encode()))
            headers.append((b"x-ratelimit-remaining", b"0"))
            headers.append((b"x-ratelimit-reset", str(window_reset).encode()))
            headers.append((b"retry-after", str(max(0, int(window_reset - time.time()))).encode()))
            headers.append((b"content-type", b"application/json"))
            await send({"type": "http.response.start", "status": 429, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_ratelimit_headers(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                existing.append((b"x-ratelimit-limit", str(_DEFAULT_LIMIT.amount).encode()))
                existing.append((b"x-ratelimit-remaining", str(window_remaining).encode()))
                existing.append((b"x-ratelimit-reset", str(window_reset).encode()))
                message["headers"] = existing
            await send(message)

        await self.app(scope, receive, send_with_ratelimit_headers)


def register_rate_limiting(app: FastAPI) -> None:
    """Call once from app/main.py. Order note: DefaultRateLimitMiddleware
    must be added via app.add_middleware BEFORE register_error_handlers
    (app)'s own RequestIDMiddleware registration -- see app/main.py's own
    ordering comment (RequestIDMiddleware must stay outermost so a 429
    still gets X-Request-ID; this middleware sits inside it, which is
    fine since it builds its own 429 response directly rather than going
    through the bare-Exception/ServerErrorMiddleware path documented in
    app/core/errors.py)."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(DefaultRateLimitMiddleware)
