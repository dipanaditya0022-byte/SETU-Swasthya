"""Global exception handling + request-ID tracing (error-handling task).

WHY THIS FILE EXISTS: before this step, an unhandled exception anywhere
in this app (a bug, a bad assumption, a DB error nobody anticipated)
propagated all the way out to Starlette's own default 500 handler, which
in a public demo means a raw traceback -- file paths, library versions,
and (for a `sqlalchemy.exc.IntegrityError`, confirmed live and fixed
separately in app/api/routes/sync.py's own per-item error path -- see
that route's own comment) sometimes the actual SQL statement and bound
parameter VALUES, which for this schema can be patient PHI. This module
is the one place that guarantees no exception -- known or unknown --
ever reaches a client without going through a controlled, PHI-safe
response shape, and gives every response (success or failure) a
request ID a human can use to find the real detail in the server log,
which is where it belongs.

FOUR handlers, registered by `register_error_handlers(app)`:
  1. RequestValidationError -> 422
  2. AppError (new base class, below) -> exc.status_code
  3. sqlalchemy.exc.IntegrityError -> 409
  4. Exception (catch-all) -> 500

Plus `RequestIDMiddleware`: a UUID per request (or the client's own
`X-Request-ID`, if sent), echoed back in the response header on every
response -- success AND error -- and threaded into every structured log
line this codebase already emits, without editing any of the ~15
existing `logger.info/warning/error(...)` call sites across the repo
(see `configure_logging()`'s own docstring for how).

===========================================================================
RESPONSE-SHAPE DECISION -- READ BEFORE CHANGING/REMOVING THIS NOTE
===========================================================================
This task's own spec gives an `{"error": {...}}` top-level envelope for
all four handlers here. That is a DIFFERENT envelope than every
hand-written domain error already in this codebase (app/api/routes/
patients.py's PHONE_REQUIRED, triage.py's INVALID_PROTOCOL, referrals.py's
INVALID_TRANSITION, etc. -- all raised as `HTTPException(status, {"code":
..., ...})`, which FastAPI's OWN default handler wraps as `{"detail":
{...}}`, extensively built and tested across three earlier tasks today).

Decision, made explicitly rather than picked silently:
  - HTTPException call sites are UNTOUCHED. This module does not
    register a handler for `HTTPException`/`StarletteHTTPException` --
    FastAPI's own default handler for that exact class stays in the MRO
    lookup ahead of this module's `Exception` catch-all (confirmed live,
    see this task's own delivery notes), so every existing
    `HTTPException(...)` call keeps returning `{"detail": {...}}`,
    unchanged, exactly as tested all day. Touching ~30 already-tested
    call sites across 5 route files for a shape preference, on the same
    day they were built and verified, would be a much bigger blast
    radius than this task asked for.
  - RequestValidationError (pydantic/FastAPI's OWN automatic validation
    -- missing field, wrong type, bad enum, bad UUID, malformed JSON,
    a malformed batch item) is what THIS task's spec is actually about,
    and DOES move to the new `{"error": {...}}` envelope, per spec.
  - The validation-matrix task (earlier today) built SPECIFIC,
    differentiated codes for several RequestValidationError cases
    (INVALID_UUID, INVALID_STATUS listing valid values, INVALID_BATCH_ITEM
    naming the failing index, INVALID_FIELD_TYPE naming the field) --
    this handler PRESERVES those specific codes/messages (they are
    strictly more actionable than a single generic "VALIDATION_ERROR"
    for every case, which is this same task's own stated goal: "a
    message a non-technical person could act on"), while ALSO adding
    this task's own `detail` (the raw pydantic msg, always present) and
    `request_id` keys to every response, and using this task's own
    generic `"Check the '<field>' field."` message ONLY for the true
    fallback branch where nothing more specific was already derived.
    This is not a silent deviation -- it is the same "don't flatten
    away a more specific answer already required by an earlier
    instruction" judgement call this task's own text asks for
    elsewhere (see the AppError section below).
  - `tests/test_validation_matrix.py`'s own shape-reading helper is
    updated (in that file) to read whichever of `error`/`detail` the
    response actually used, since some of ITS OWN cases go through
    RequestValidationError (now `{"error": ...}`) and others through a
    route's own HTTPException (still `{"detail": ...}`).
===========================================================================

APPERROR DECISION -- READ BEFORE CHANGING THIS NOTE
===========================================================================
Nothing in this codebase raises `AppError` today -- every existing
domain error already uses `HTTPException(status, {"code": ...})` (see
above). Two options considered: (a) migrate every existing call site to
raise `AppError` instead, or (b) leave every existing call site exactly
as it is (already tested, already correct) and add `AppError` as NEW
infrastructure available for FUTURE code, with its own handler
registered and independently testable even though nothing raises it
yet. Chosen: (b) -- consistent with every earlier task's own "additive
only" instruction today, and because (a) would touch the same ~30
already-tested call sites the shape decision above already declined to
touch, for the same reason. `tests/test_error_contract.py` tests the
`AppError` handler by invoking it directly (not via a live HTTP route),
since there is no real call site to hit yet -- documented in that file.
===========================================================================
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.security_headers import SECURITY_HEADERS
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


# ============================================================
# Request ID: a contextvar (not just `request.state`) so it is readable
# from a logging.Filter attached to a plain stdlib Handler, which has no
# access to the current Request object at all -- this is the ONE
# mechanism that lets every existing `logger.info(...)` call site in
# this codebase pick up the current request's ID without being edited
# to pass it explicitly. `request.state.request_id` is ALSO set by the
# middleware below (confirmed live: Starlette's `Request.state` reads
# straight from `scope["state"]`) purely so exception-handler code below
# can read it the "normal" FastAPI way; `get_request_id()` tries that
# first and falls back to the contextvar, so either path works.
# ============================================================
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id(request: Optional[Request] = None) -> str:
    if request is not None:
        rid = getattr(request.state, "request_id", None)
        if rid:
            return rid
    return _request_id_ctx.get()


def _error_response(status_code: int, error_body: dict, request_id: str) -> JSONResponse:
    """Every handler in this module returns through this helper, never
    a bare `JSONResponse(...)` -- two things found ONLY by testing this
    live (not obvious from reading Starlette's source), both fixed here
    in one place:

    1. FastAPI/Starlette special-case a handler registered for the base
       `Exception` class: it becomes `ServerErrorMiddleware`'s OWN
       `handler=` argument (confirmed via the live traceback: the call
       stack shows `starlette/middleware/errors.py` -- ServerErrorMiddleware
       -- calling straight into our handler), NOT something dispatched
       through the normal `ExceptionMiddleware` path every OTHER
       registered handler in this module goes through. ServerErrorMiddleware
       sits OUTSIDE every `app.add_middleware(...)` layer, including
       RequestIDMiddleware -- so a response built by the catch-all
       `unhandled_exception_handler` would otherwise send() through a
       path RequestIDMiddleware's own header-injection never sees, and
       X-Request-ID would silently be missing on exactly the one
       response type ("something went catastrophically wrong") this
       whole task cares about most. Setting the header directly on the
       Response object, here, sidesteps that middleware-ordering
       subtlety for every handler, not just the one it was found on.

    2. By the time that same catch-all handler runs, the exception has
       already propagated OUT of RequestIDMiddleware's own `try` block,
       so its `finally: _request_id_ctx.reset(token)` has ALREADY run --
       any `logger.x(...)` call made from inside that handler would
       otherwise show `request_id=-` in its own log-line prefix (still
       correct in the RESPONSE body, since that reads `request.state`,
       untouched by the contextvar reset -- but wrong/confusing in the
       log). Re-`.set()` (not `.reset()` -- this response is on its way
       out, nothing downstream needs the old token back) the contextvar
       here too, so every handler's own log lines are consistent
       regardless of which of the two exception-dispatch paths above
       they were reached through.

    3. (deployment-hardening task) The SAME bare-Exception/ServerErrorMiddleware
       blind spot documented in point 1 also swallows the security headers
       app/core/security_headers.py's own `SecurityHeadersMiddleware` adds
       to every other response -- so those are applied directly here too,
       from the one shared dict, rather than duplicating the header list
       in two places that could drift apart.
    """
    _request_id_ctx.set(request_id)
    headers = {**SECURITY_HEADERS, "X-Request-ID": request_id}
    return JSONResponse(status_code=status_code, content=error_body, headers=headers)


class _RequestIDLogFilter(logging.Filter):
    """Attached to the ROOT logger's own handler (see configure_logging
    below), not to individual `logging.getLogger(__name__)` instances --
    a Filter on a HANDLER runs for every record that reaches that
    handler regardless of which logger emitted it, since every existing
    logger in this codebase (`app.core.tokens`, `app.api.routes.triage`,
    etc. -- grepped directly, ~8 modules) is created with
    `logging.getLogger(__name__)` and default `propagate=True`, so
    records flow up to root and through this one filter+formatter
    without any of those ~15 existing `logger.info/warning/error(...)`
    call sites needing to change."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Call once, at app startup (app/main.py). Before this step, this
    codebase had NO shared logging configuration at all (confirmed by
    grep: every module does `logger = logging.getLogger(__name__)` and
    nothing else) -- log lines went through Python's implicit
    "handler of last resort" with no request-id, no consistent format.
    This installs ONE handler on the root logger with a formatter that
    includes `request_id`; does not touch uvicorn's own `uvicorn`/
    `uvicorn.access`/`uvicorn.error` loggers (those attach their own
    handlers directly and don't propagate to root by default in
    uvicorn's own logging config, so this is additive, not a conflict)."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s request_id=%(request_id)s %(name)s: %(message)s"
    ))
    handler.addFilter(_RequestIDLogFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class RequestIDMiddleware:
    """Pure ASGI middleware (same style as app/main.py's own pre-existing
    BodySizeLimitMiddleware, not Starlette's BaseHTTPMiddleware, which
    buffers the whole response and would defeat streaming responses for
    no benefit here).

    MUST be the OUTERMOST middleware in this app (added to `app` AFTER
    every other `app.add_middleware(...)` call -- Starlette's own
    `add_middleware` inserts at position 0, making the LAST one added
    the outermost) so that even a request rejected by an EARLIER
    middleware (e.g. BodySizeLimitMiddleware's 413) still gets an
    X-Request-ID header and a request_id available to log lines emitted
    during that rejection. Verified live as part of this task -- see
    the delivery notes' curl output."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        request_id = incoming.decode("latin-1") if incoming else str(uuid.uuid4())

        # Readable via request.state.request_id (confirmed live:
        # Starlette's Request.state reads scope["state"] directly).
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        # Readable from anywhere else (a logging.Filter has no Request
        # object at all) via the contextvar.
        token = _request_id_ctx.set(request_id)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                # Don't double up -- _error_response() (app/core/errors.py)
                # already sets this header directly on responses from
                # THREE of the four handlers here (the fourth, the bare-
                # Exception catch-all, needs it set there regardless,
                # since that response never reaches this wrapper at all
                # -- see _error_response's own docstring). Only add it
                # here if nothing downstream already did.
                if not any(k.lower() == b"x-request-id" for k, _ in existing):
                    existing.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = existing
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id_ctx.reset(token)


# ============================================================
# AppError -- new base class for future domain errors. See this
# module's own docstring, "APPERROR DECISION", for why nothing raises
# this yet and why that's the deliberate, considered choice, not an
# oversight.
# ============================================================
class AppError(Exception):
    """Base class for application/domain errors that want this module's
    PHI-safe, request-id-bearing `{"error": {...}}` envelope. Subclass
    this for any FUTURE domain error instead of raising a bare
    `HTTPException(status, {"code": ...})` -- existing call sites are
    deliberately left as they are (see module docstring)."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        detail: Optional[str] = None,
        field: Optional[str] = None,
        **extra: Any,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail
        self.field = field
        self.extra = extra
        super().__init__(message)


# ============================================================
# Handler #1 -- RequestValidationError -> 422.
# ============================================================

def _first_error_field(loc: tuple) -> str:
    """pydantic v2 error `loc` tuples look like ("body", "vitals",
    "bp_systolic") or ("query", "status") or ("path", "patient_id").
    Strips the request-part marker, keeps the rest dotted -- e.g.
    "vitals.bp_systolic", "status", "patient_id". (Moved here from
    app/main.py, which used to own this handler before this task --
    single copy now, not duplicated.)"""
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) if parts else "request"


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = get_request_id(request)
    errors = exc.errors()
    first = errors[0] if errors else {}
    err_type = first.get("type", "")
    field = _first_error_field(first.get("loc", ()))
    pydantic_msg = first.get("msg", "Invalid request.")

    # ---- malformed JSON body: FastAPI reports this as a validation
    # error (type "json_invalid") rather than failing before validation
    # ever runs. 400, not 422, for this one specific case. ----
    if err_type == "json_invalid":
        return _error_response(400, {"error": {
            "code": "MALFORMED_JSON",
            "message": "The request body is not valid JSON.",
            "detail": pydantic_msg,
            "request_id": request_id,
        }}, request_id)

    # ---- UUID-typed path/query param that doesn't parse as a UUID. ----
    if err_type in ("uuid_parsing", "uuid_type"):
        return _error_response(422, {"error": {
            "code": "INVALID_UUID",
            "field": field,
            "message": f"'{field}' must be a valid UUID.",
            "detail": pydantic_msg,
            "request_id": request_id,
        }}, request_id)

    # ---- required field/param genuinely absent. ----
    if err_type == "missing":
        if field in ("age", "age_years", "date_of_birth"):
            code, message = "AGE_REQUIRED", "Either a date of birth or an age is required."
        else:
            code = f"{field.upper().replace('.', '_')}_REQUIRED"
            message = f"'{field}' is required."
        return _error_response(422, {"error": {
            "code": code, "field": field, "message": message,
            "detail": pydantic_msg, "request_id": request_id,
        }}, request_id)

    # ---- enum value not among the allowed set (e.g. the `status` query
    # param on PATCH /referrals/{id}/status). pydantic's own `msg` for
    # this error type already lists every valid value verbatim. ----
    if err_type == "enum":
        code = "INVALID_STATUS" if field == "status" else "INVALID_FIELD_VALUE"
        return _error_response(422, {"error": {
            "code": code, "field": field, "message": pydantic_msg,
            "detail": pydantic_msg, "request_id": request_id,
        }}, request_id)

    # ---- wrong type for a field that IS present -- OR, for a batch
    # endpoint like POST /sync/ (body is `list[dict]`), a batch ITEM
    # that isn't an object at all: loc is ("body", <index>), which
    # strips down to a bare numeric field name -- named explicitly as an
    # item index in that case. This is the STRUCTURAL case (the payload
    # doesn't even parse as a list of objects); a well-formed item with
    # bad DATA inside it is handled as a 200 partial-success result by
    # app/api/routes/sync.py's own per-item savepoint logic, unrelated
    # to this handler. ----
    if err_type in ("float_parsing", "float_type", "int_parsing", "int_type",
                     "string_type", "bool_parsing", "bool_type", "dict_type", "list_type"):
        if field.isdigit():
            return _error_response(422, {"error": {
                "code": "INVALID_BATCH_ITEM",
                "index": int(field),
                "message": f"Item at index {field} is not a valid record: {pydantic_msg}.",
                "detail": pydantic_msg, "request_id": request_id,
            }}, request_id)
        return _error_response(422, {"error": {
            "code": "INVALID_FIELD_TYPE",
            "field": field,
            "message": f"'{field}' has an invalid value: {pydantic_msg}.",
            "detail": pydantic_msg, "request_id": request_id,
        }}, request_id)

    # ---- fallback: this task's own generic shape, for anything not
    # more specifically categorised above. ----
    return _error_response(422, {"error": {
        "code": "VALIDATION_ERROR",
        "message": f"Check the '{field}' field.",
        "detail": pydantic_msg,
        "field": field,
        "request_id": request_id,
    }}, request_id)


# ============================================================
# Handler #2 -- AppError -> exc.status_code.
# ============================================================

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = get_request_id(request)
    body: dict[str, Any] = {"code": exc.code, "message": exc.message, "request_id": request_id}
    if exc.detail is not None:
        body["detail"] = exc.detail
    if exc.field is not None:
        body["field"] = exc.field
    body.update(exc.extra)  # e.g. allowed_next on an INVALID_TRANSITION
    return _error_response(exc.status_code, {"error": body}, request_id)


# ============================================================
# Handler #3 -- sqlalchemy.exc.IntegrityError -> 409.
# ============================================================

# Real constraint names in this schema (grepped directly against every
# file in alembic/versions/ -- CheckConstraint/UniqueConstraint `name=`
# kwargs, and `op.create_index(..., unique=True)` index names, which
# Postgres reports identically to a named constraint in an
# IntegrityError). Only constraints a normal API request could plausibly
# trigger get a specific, friendly message; the rest (data-integrity
# guards on columns no current public request can set directly, e.g.
# chk_scope_required/chk_superuser_expires) still get a message, just a
# more generic one -- never `str(exc)`.
_CONSTRAINT_MESSAGES: dict[str, str] = {
    # users -- unique partial indexes (idx_users_*), migration c3a9f7d21e56
    "idx_users_mobile_bi": "This mobile number is already registered.",
    "idx_users_email_bi": "This email address is already registered.",
    "idx_users_hpr": "This HPR ID is already registered.",
    "idx_users_emp_code": "This employee code is already registered.",
    # mfa_credentials, migration d6b1a94f2c3e
    "idx_mfa_webauthn_credential_id": "This security key is already registered to another account.",
    # org_units, migration 0e21a4d7c6f5
    "idx_org_units_lgd": "This LGD code is already in use by another org unit.",
    "idx_org_units_hfr": "This HFR ID is already in use by another org unit.",
    "uq_org_units_parent_name": "An org unit with this name already exists under the same parent.",
    "chk_path_starts_slash": "This org unit's path is invalid.",
    # idempotency_keys, migration f1c9a2e8b374
    "uq_idempotency_key_endpoint": "This request has already been submitted.",
    # referral, migration d4f1c9b7a582
    "fk_referral_arrival_confirmed_by": "The staff member referenced for arrival confirmation does not exist.",
    "fk_referral_owner_user_id": "The user referenced as the referral owner does not exist.",
    # governance, migration f2e7c81a5b93
    "chk_witness_for_spoken": "A witness name is required for this type of consent.",
    "chk_justification_length": "The justification provided is too short.",
    "chk_different_approver": "The approver must be a different person from whoever created this request.",
    # users -- other CHECK constraints, migration c3a9f7d21e56 (mostly
    # server-controlled fields, not directly request-writable today, but
    # still mapped rather than falling through to str(exc))
    "chk_creator_required": "This account is missing a required creator reference.",
    "chk_scope_required": "This account is missing a required posting.",
    "chk_suspension_reason": "A suspension reason is required.",
    "chk_deactivated_no_creds": "A deactivated account cannot retain credentials.",
    "chk_privileged_mfa": "This role requires multi-factor authentication to be enabled.",
    "chk_superuser_expires": "A superuser account must have an expiry date.",
    "chk_no_self_report": "A user cannot report to themselves.",
    # user_invitations / mfa_credentials, migration d6b1a94f2c3e
    "chk_invite_single_use": "This invitation has already been used.",
    "chk_mfa_credential_type_valid": "This MFA credential type is not recognised.",
    "chk_mfa_credential_fields_match_type": "The MFA credential fields do not match its type.",
}
_DEFAULT_CONSTRAINT_MESSAGE = "This request conflicts with existing data."


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    request_id = get_request_id(request)

    # psycopg3's own `.diag` (populated straight from Postgres's SQLSTATE
    # diagnostic fields) gives the constraint/table/column name WITHOUT
    # ever touching `str(exc)` -- deliberately NOT using message_detail
    # or str(exc) anywhere in this function, including in the SERVER-SIDE
    # log line below: message_detail/str(exc) for a unique-violation
    # includes the actual offending VALUE (e.g. "Key (mobile_blind_index)
    # =(...) already exists." or, for a NOT NULL violation, the full
    # failing row), which for this schema can be patient PHI (confirmed
    # live during an earlier task today -- a NOT NULL violation on
    # `patient.name` printed the patient's own submitted name in the
    # exception's own string form). The PHI-in-logs audit for this task
    # explicitly requires patient data never reach a log line either,
    # not just a client response -- so this function is deliberately
    # MORE conservative than typical "log everything server-side" advice
    # would suggest: only structural diagnostic fields (never bound
    # values) are logged, here or anywhere else.
    diag = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag else None
    table_name = getattr(diag, "table_name", None) if diag else None
    column_name = getattr(diag, "column_name", None) if diag else None
    message_primary = getattr(diag, "message_primary", None) if diag else None

    logger.error(
        "IntegrityError on %s %s: constraint=%s table=%s column=%s primary=%s",
        request.method, request.url.path, constraint_name, table_name, column_name, message_primary,
    )

    if constraint_name and constraint_name in _CONSTRAINT_MESSAGES:
        message = _CONSTRAINT_MESSAGES[constraint_name]
    elif column_name:
        message = f"A required value for '{column_name}' was missing or invalid."
    else:
        message = _DEFAULT_CONSTRAINT_MESSAGE

    return _error_response(409, {"error": {
        "code": "CONFLICT",
        "message": message,
        "request_id": request_id,
    }}, request_id)


# ============================================================
# Handler #4 -- catch-all Exception -> 500. THE handler this whole task
# exists for: no exception type, no exception message, no traceback,
# nothing but a request_id -- the detail lives ONLY in the server log,
# via log.exception (includes the full traceback there, deliberately --
# that's the one place it's safe and useful).
# ============================================================

async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id(request)
    # Re-set BEFORE logging, not just inside _error_response below (which
    # runs after this log line) -- this is the ONE handler reached via
    # ServerErrorMiddleware (see _error_response's own docstring, point
    # 2), where RequestIDMiddleware's `finally` has already reset the
    # contextvar by the time this function runs; without this, the log
    # line's own `request_id=%(request_id)s` prefix (from the shared
    # logging.Filter) would show "-" even though it's explicitly passed
    # as a %s argument below too.
    _request_id_ctx.set(request_id)
    logger.exception(
        "Unhandled exception on %s %s (request_id=%s)",
        request.method, request.url.path, request_id,
    )
    return _error_response(500, {"error": {
        "code": "INTERNAL_ERROR",
        "message": "Something went wrong. Please try again.",
        "request_id": request_id,
    }}, request_id)


def register_error_handlers(app: FastAPI) -> None:
    """Call once from app/main.py, AFTER every other `app.add_middleware`
    call in that file (see RequestIDMiddleware's own docstring for why
    the ordering matters) and after every router is included."""
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_middleware(RequestIDMiddleware)
