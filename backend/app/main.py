import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session, text
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.routes.patients import router as patients_router
from app.core.errors import configure_logging, register_error_handlers
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.database import get_session

configure_logging()

app = FastAPI(title="SETU-Swasthya API")

# Fixed per-build demo tag (deployment-hardening task's own literal
# example value) -- not derived from anything; bump by hand when this
# actually is a different demo build.
_DEMO_VERSION = "demo-v1.0"


@app.get("/health")
def health(session: Session = Depends(get_session)):
    """Public, unauthenticated -- deliberately so (this task's own spec:
    "it stays PUBLIC"). Answers "is it up, and is it the build we tested?"
    in one call, for demo day. Audited before shipping this handler:
    every field here is a boolean/version-tag/timestamp/engine-name --
    NO counts, NO names, NO connection strings, NO PHI, matching this
    task's own explicit constraint.
    """
    try:
        session.exec(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001 -- health check must never itself 500
        database_ok = False

    # Real current alembic head, read live from the DB -- never hardcoded.
    # If the query itself fails (e.g. the table doesn't exist on a truly
    # broken deploy), fall back to "unknown" rather than crashing /health.
    migration_head = "unknown"
    try:
        row = session.exec(text("SELECT version_num FROM alembic_version")).first()
        if row is not None:
            migration_head = row[0]
    except Exception:  # noqa: BLE001
        pass

    # Which engine is ACTUALLY active right now -- reuses the exact same
    # factories app/api/routes/triage.py and referrals.py's escalation
    # wiring already call, not a re-implementation. TRIAGE_ENGINE/
    # ESCALATION_ENGINE should be explicitly set (never left on "auto" --
    # see this task's own deployment checklist); this reports the REAL
    # resolved engine either way, so /health is honest even if that
    # checklist line was somehow missed.
    from app.services.escalation.factory import get_escalation_engine
    from app.services.triage.factory import get_triage_engine

    try:
        triage_engine_name = get_triage_engine().name
    except Exception:  # noqa: BLE001 -- e.g. TRIAGE_ENGINE=rule forced and not ready
        triage_engine_name = "unavailable"
    try:
        escalation_engine_name = get_escalation_engine().name
    except Exception:  # noqa: BLE001
        escalation_engine_name = "unavailable"

    overall_status = "ok" if database_ok else "error"
    body = {
        "status": overall_status,
        "version": _DEMO_VERSION,
        "commit": os.environ.get("GIT_COMMIT") or "unknown",
        "migration_head": migration_head,
        "database": "ok" if database_ok else "error",
        "triage_engine": triage_engine_name,
        "escalation_engine": escalation_engine_name,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(status_code=200 if database_ok else 503, content=body)


app.include_router(patients_router)

from app.api.routes.triage import router as triage_router

app.include_router(triage_router)

from app.api.routes.referrals import router as referrals_router

app.include_router(referrals_router)

from app.api.routes.sync import router as sync_router

app.include_router(sync_router)

from app.api.routes.auth import router as auth_router

app.include_router(auth_router)

from app.api.routes.users import router as users_router

app.include_router(users_router)

from app.api.routes.governance import router as governance_router

app.include_router(governance_router)

from app.api.routes.dashboard import router as dashboard_router

app.include_router(dashboard_router)


# ============================================================
# Body-size limit -- 413 PAYLOAD_TOO_LARGE over 1 MB. Pure ASGI
# middleware (no existing body-size mechanism anywhere in this codebase
# to reuse -- grepped directly): reads Content-Length when the client
# sends one (rejects immediately, before touching the body at all), and
# separately counts bytes as the body actually streams in, so a client
# that omits Content-Length (e.g. chunked transfer) can't bypass the
# limit either. Runs before routing, so it applies to every endpoint
# uniformly -- the one shared place this rule belongs, per the
# validation-matrix task's own "implement ANY-endpoint rows as shared,
# reusable behaviour" instruction.
#
# Left as its own raw-JSON `{"detail": {...}}` response shape (not this
# step's new `{"error": {...}}` envelope, app/core/errors.py) --
# deliberate: this middleware rejects a request BEFORE it ever reaches
# routing or exception handling at all, so it's outside the literal
# scope of "register FOUR handlers" this step asked for. Still gets an
# X-Request-ID header, because RequestIDMiddleware (added below, LAST --
# see its own docstring for why LAST matters) wraps this middleware, not
# the other way around.
# ============================================================
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                pass  # malformed Content-Length -- let normal request handling surface the error

        # Fully drain the body into a bounded buffer, rejecting the
        # instant it would exceed the cap -- covers a client that omits
        # Content-Length (e.g. chunked transfer) too, not just the header
        # check above. Never buffers more than max_bytes + 1 byte before
        # giving up, so this is bounded regardless of what the client
        # claims or sends. Once fully (and validly) drained, replay the
        # exact same message sequence to the real app -- avoids ever
        # calling `send` twice (once to reject, once for the app's own
        # response), which the ASGI protocol forbids.
        buffered: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        index = 0

        async def _replay_receive():
            nonlocal index
            if index < len(buffered):
                msg = buffered[index]
                index += 1
                return msg
            return {"type": "http.disconnect"}

        await self.app(scope, _replay_receive, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        import json
        body = json.dumps({"detail": {
            "code": "PAYLOAD_TOO_LARGE",
            "message": "The request body is too large. The limit is 1 MB.",
        }}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})


app.add_middleware(BodySizeLimitMiddleware, max_bytes=_MAX_BODY_BYTES)

# ============================================================
# Deployment hardening -- security headers, CORS, rate limiting.
# Registration ORDER matters (Starlette's `add_middleware` inserts at
# position 0, so the LAST middleware added ends up OUTERMOST -- see
# RequestIDMiddleware's own docstring in app/core/errors.py, which this
# ordering must keep satisfying): SecurityHeadersMiddleware, then rate
# limiting, then CORS, then (last, below) RequestIDMiddleware via
# register_error_handlers -- giving the outer-to-inner stack:
#   RequestIDMiddleware (outermost)
#   -> CORSMiddleware
#   -> DefaultRateLimitMiddleware (catch-all rate limiting; the five
#      explicitly-named routes' own limits are decorator-based, not
#      middleware-based -- see app/core/rate_limit.py's own docstring)
#   -> SecurityHeadersMiddleware
#   -> BodySizeLimitMiddleware (innermost of the custom stack)
#   -> ExceptionMiddleware -> router
# CORS sits outside rate limiting so a preflight OPTIONS request is
# never itself rate-limited or body-size-checked.
# ============================================================
app.add_middleware(SecurityHeadersMiddleware)

from app.core.rate_limit import register_rate_limiting

register_rate_limiting(app)

# CORS -- explicit origins only, read from CORS_ORIGINS (comma-separated,
# see .env.example's own note on this var). allow_origins=["*"] with
# allow_credentials=True is both rejected by browsers outright and a
# genuine vulnerability (any origin could ride an authenticated user's
# credentials) -- grepped this codebase before writing this: no
# CORSMiddleware was registered anywhere before this task, so there was
# no existing wildcard-plus-credentials vulnerability to fix here; this
# is the first CORS config this app has ever had, built correctly from
# the start.
_cors_origins = [
    origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# MUST be the LAST middleware registration in this file -- see
# RequestIDMiddleware's own docstring (app/core/errors.py) for why it
# needs to be the OUTERMOST middleware (wrapping everything above, not
# wrapped BY it) so every response, including one rejected by an earlier
# middleware, still gets an X-Request-ID header and a request_id
# available to whatever log line was emitted along the way.
register_error_handlers(app)
