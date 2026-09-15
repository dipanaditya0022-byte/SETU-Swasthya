"""Deployment-hardening security headers (deployment-hardening task --
"harden the deployment BEFORE the public smoke test").

Every response from this app -- success or error -- must carry:
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: no-referrer
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Cache-Control: no-store          -- responses can carry PHI, never cached
and must NOT carry `Server`/`X-Powered-By` (confirmed live: uvicorn sets
`server: uvicorn` by default; this codebase's stack -- FastAPI/Starlette --
never sets `X-Powered-By` at all, so there is nothing to strip there, but
the removal step still runs defensively in case that ever changes).

SECURITY_HEADERS is a plain dict, not baked only into the middleware below
-- app/core/errors.py's `_error_response()` helper also applies it
directly. WHY: this task's own earlier sibling (the global-error-handlers
task) found, live, that a handler registered for the base `Exception`
class is dispatched by Starlette's `ServerErrorMiddleware`, which sits
OUTSIDE every `app.add_middleware(...)` layer -- so a genuine 500's
response NEVER passes through `SecurityHeadersMiddleware.__call__`'s own
send-wrapping, the same blind spot `X-Request-ID` had before that earlier
fix. Importing this same dict into `_error_response()` closes that gap at
the one shared choke point, rather than teaching two different modules
two different lists of headers that could drift apart.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cache-Control": "no-store",
}

# Headers to strip if present. Checked live before writing this: uvicorn's
# default response DOES carry `server: uvicorn`; this stack never sets
# `x-powered-by` at all (that header is characteristic of Express/PHP, not
# FastAPI/Starlette) -- stripped anyway, defensively, in case a future
# reverse proxy or dependency ever adds one.
_STRIP_HEADERS = {b"server", b"x-powered-by"}
_SECURITY_HEADERS_ENCODED = [
    (k.encode("latin-1"), v.encode("latin-1")) for k, v in SECURITY_HEADERS.items()
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware, same style as this app's other middleware
    (BodySizeLimitMiddleware in app/main.py, RequestIDMiddleware in
    app/core/errors.py). Must be registered so it wraps every response
    that DOES pass through the normal middleware stack (everything except
    the bare-Exception 500 case handled directly in errors.py, per this
    module's own docstring above)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                existing = [
                    (k, v) for k, v in message.get("headers", [])
                    if k.lower() not in _STRIP_HEADERS
                ]
                existing_keys = {k.lower() for k, _ in existing}
                for key, value in _SECURITY_HEADERS_ENCODED:
                    if key.lower() not in existing_keys:
                        existing.append((key, value))
                message["headers"] = existing
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
