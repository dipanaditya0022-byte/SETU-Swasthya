"""POST /sync/ -- Aditya's original, contract-frozen Day 1 endpoint
(backend/docs/API_CONTRACT.md), extended per Day1.md SS14.1's own table:
"now requires an authenticated session; payload validated against the
actor's scope". S20.

Request shape (a bare list of dicts, matched by `client_uuid`) and the
top-level response shape (`{"synced": <count>, "records": [...]}`) are
UNCHANGED -- `synced` keeps its original meaning (count of records in
this batch), preserved exactly rather than silently redefined to mean
"count actually accepted", since every record was always "accepted"
before this step (there was no rejection path) and this step must not
change response semantics beyond the additive authorization requirement.

Day1.md gives no schema for an individual sync record -- there is no
CREATE TABLE, Pydantic model, or worked example anywhere beyond
SS14.1's one-line change description and API_CONTRACT.md's own
`{"client_uuid", "name"}` example, and the endpoint accepts arbitrary
dicts by design (it's a generic offline-queue intake, not tied to one
target table). Given no target schema to validate scope against per
record, this step's own concrete design (documented here rather than
silently assumed, matching the established pattern from S16's own
under-specified-endpoint handling): "payload validated against the
actor's scope" means -- for any record that itself carries an
`org_unit_id` key (the client's own claim about which org unit this
offline record belongs to) -- that org unit must be within the
authenticated actor's scope, via the same `org_unit_is_within_scope`
every other route in this step uses. A record without an `org_unit_id`
key has nothing to validate and is accepted as before. A record that
fails the check is marked `"status": "rejected"` with a reason, not
dropped silently and not failing the whole batch -- consistent with
sync's own nature as a best-effort offline reconciliation endpoint.

===========================================================================
Dashboard step (migration b9e4c7a2f815) -- additive `patient.synced_at`
stamping. Request shape and the top-level response shape
(`{"synced": N, "records": [...]}`) are UNTOUCHED by this addition; every
field on every existing `records[]` entry (`client_uuid`, `status`,
`reason`) is unchanged too.
===========================================================================

THE GAP THIS WIRING CANNOT CLOSE, STATED HERE AGAIN (see migration
b9e4c7a2f815's own docstring "THE SYNC/synced_at GAP" for the full
finding): only `patient` has a `client_uuid` column. `referral` and
`triageencounter` do not, and adding one is explicitly out of scope for
this step. So this wiring can only ever set `synced_at` on `patient`
rows -- for any accepted record whose `client_uuid` matches an existing
`patient.client_uuid`. It does NOT attempt this for `referral` or
`triageencounter` records; their `synced_at` stays NULL forever until a
future, separate migration gives them their own `client_uuid` column.
`app/api/routes/dashboard.py`'s own `synced_today` metric docstring
repeats this same limitation at the point a reader would actually see
its effect (a denominator that spans all three tables but a numerator
that, in practice, is only ever nonzero for `patient` rows).

MATCHING SCOPE, NOT JUST client_uuid: a matched `patient` row is only
stamped if ITS OWN `org_unit_id` is within the calling actor's scope
(the same `org_unit_is_within_scope` check used everywhere else in this
route and this codebase) -- fail-closed (C3). This matters because a
sync record in the incoming batch is not required to carry its own
`org_unit_id` at all (see this module's pre-existing docstring above);
without this second check, an actor could stamp `synced_at` on a
`patient` row outside their own scope just by guessing/replaying a
`client_uuid` that happens to exist elsewhere in the district. The
scope check is done as a single set-based SQL statement (a path-prefix
join against `org_units`, mirroring `org_unit_is_within_scope`'s own
trailing-slash-safe logic and app/api/routes/referrals.py's own
`/exceptions` route), not one `org_unit_is_within_scope` call per
matched row -- so this stays O(1) queries regardless of batch size.

An actor with no posting at all (`scope_org_unit_id IS NULL` -- true for
every SUPERUSER) can never pass that scope check for any org unit
(`org_unit_is_within_scope`'s own fail-closed rule), so this step is
skipped entirely for such an actor rather than stamping every matching
patient row district- or state-wide.

===========================================================================
ATOMICITY step (backend/docs/DAY3_BUGS.md follow-up task) -- PER-ITEM
transaction boundaries, deliberately NOT one-transaction-per-batch like
the other four write paths in this step.
===========================================================================

WHY DIFFERENT: a field worker syncing a full day's offline queue must not
lose 49 good records because item 23 is malformed. Previously this route
had no per-item isolation at all -- a single record whose `org_unit_id`
failed to parse as a UUID would raise INSIDE the for-loop (uncaught,
`org_unit_is_within_scope`'s raw SQL bound to a UUID column), a 500 for
the whole request, and (before this same step's other four fixes) the
implicit session lifecycle meant nothing else in the batch was even
attempted. Fix: each record's own writes now run inside their own
`session.begin_nested()` SAVEPOINT. A per-record exception rolls back
only that savepoint (verified: `SAVEPOINT ... ROLLBACK TO SAVEPOINT`
under the hood, via SQLAlchemy's nested-transaction support) -- the
outer transaction, and every already-flushed sibling record's writes
within it, are untouched. One `session.commit()` at the very end still
commits the whole batch's successful items together.

RESPONSE SHAPE -- ADDITIVE, not a replacement. `synced` (unchanged
meaning: count of records submitted) and `records[]` (unchanged
per-record `{client_uuid, status: "accepted"|"rejected"}` -- "rejected"
now also covers a per-item write failure, not only OUT_OF_SCOPE, a
natural widening of a word that already meant "did not go through", not
a narrowing of what it used to mean) are kept byte-for-byte compatible
with the existing, contract-frozen shape (backend/docs/API_CONTRACT.md,
tests/test_existing_endpoints.py::test_sync_requires_auth_and_validates_scope
-- both still pass unchanged). `created`/`duplicates`/`failed` (counts)
and `results[]` (`{index, status: "created"|"duplicate"|"failed", code,
message}`, one entry per record in request order) are new, additive
fields carrying the richer per-item detail this task's own spec asks
for.

CREATE vs DUPLICATE, given this route's own pre-existing, deliberate
"patient-only, never invents a new Patient row for an unrelated table"
design (see the GAP note above): a record whose `client_uuid` does NOT
already match an existing `patient` row is genuinely new offline-created
data -- this step now actually inserts it as a new `patient` row
(previously this route only ever UPDATEd `synced_at` on a row that
already had to exist from an earlier `POST /patients/` call; that meant
"sync" could never actually deliver a record that had never reached the
server before, which defeats the entire "field worker was offline all
day" scenario the WHY above describes). Required `patient` columns
(`age`/`village`/`facility_id`) that the incoming dict doesn't supply
default to `0`/`"Unknown"`/the actor's own posting respectively --
sync's own request schema is intentionally a generic, unvalidated dict
(module docstring above), so a minimal record must still succeed, not
422 -- exactly how the pre-existing frozen test's own minimal record
(`{"client_uuid": "c1", "name": "..."}`,  no age/village/facility_id)
already behaves. A record whose `client_uuid` DOES already match an
existing `patient` row is a resync (e.g. a retried batch after a
connectivity drop) -- no second row is inserted; `synced_at` is stamped
if not already set, and it's reported as `"duplicate"`, not `"created"`.
A record with no `client_uuid` at all can never be deduplicated, so it's
always treated as `"created"` (a fresh, unattributable offline record)
if it otherwise succeeds.
"""
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session, text

from app.core.authz import get_current_active_user, org_unit_is_within_scope
from app.core.rate_limit import limiter, user_or_ip_key
from app.db.database import get_session

logger = logging.getLogger(__name__)
from app.models import Patient

router = APIRouter(prefix="/sync", tags=["Sync"])


def _sync_one(session: Session, current_user, record: dict[str, Any]) -> dict[str, Any]:
    """Process exactly one record. Raises on any failure -- the caller
    wraps this in its own SAVEPOINT and turns a raise into a "failed"
    result, never letting one record's exception propagate out and abort
    the rest of the batch."""
    client_uuid = record.get("client_uuid")
    record_org_unit_id = record.get("org_unit_id")

    if record_org_unit_id and not org_unit_is_within_scope(
        session, record_org_unit_id, current_user.scope_org_unit_id
    ):
        raise ValueError("OUT_OF_SCOPE")

    now = datetime.now(timezone.utc)

    existing = None
    if client_uuid:
        existing = session.exec(
            text("SELECT id, synced_at, org_unit_id FROM patient WHERE client_uuid = :cu"),
            params={"cu": str(client_uuid)},
        ).first()

    if existing is not None:
        # Duplicate/resync. Same scope re-check the old batch UPDATE did
        # (module docstring, "MATCHING SCOPE, NOT JUST client_uuid") --
        # a client_uuid collision outside the actor's own scope is not
        # treated as this actor's own duplicate.
        existing_org_unit_id, existing_synced_at = existing[2], existing[1]
        if existing_org_unit_id is not None and current_user.scope_org_unit_id is not None:
            if not org_unit_is_within_scope(session, existing_org_unit_id, current_user.scope_org_unit_id):
                raise ValueError("OUT_OF_SCOPE")
        if existing_synced_at is None:
            session.exec(
                text("UPDATE patient SET synced_at = :now WHERE id = :id"),
                params={"now": now, "id": existing[0]},
            )
        return {"outcome": "duplicate"}

    # Genuinely new record -- insert. See module docstring's "CREATE vs
    # DUPLICATE" note for the default-filling rationale.
    facility_id = record.get("facility_id") or record_org_unit_id or current_user.scope_org_unit_id
    if facility_id is None:
        # No record-level facility/org_unit claim and the actor has no
        # posting to attribute it to either (e.g. a SUPERUSER) -- nothing
        # sensible to insert. Fail this one item, don't guess.
        raise ValueError("NO_FACILITY_CONTEXT")

    patient = Patient(
        name=str(record.get("name") or "Unknown"),
        age=int(record.get("age") or 0),
        village=str(record.get("village") or "Unknown"),
        phone=record.get("phone"),
        facility_id=UUID(str(facility_id)),
        client_uuid=str(client_uuid) if client_uuid else None,
        created_by_user_id=current_user.id,
        org_unit_id=UUID(str(record_org_unit_id)) if record_org_unit_id else current_user.scope_org_unit_id,
        synced_at=now,
    )
    session.add(patient)
    session.flush()
    return {"outcome": "created"}


@router.post("/")
@limiter.limit("60/hour", key_func=user_or_ip_key)
def sync_records(
    request: Request,
    response: Response,
    records: list[dict[str, Any]],
    current_user=Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    records_out = []
    results = []
    created = duplicates = failed = 0

    for index, record in enumerate(records):
        client_uuid = record.get("client_uuid")
        try:
            with session.begin_nested():  # SAVEPOINT -- see module docstring.
                outcome = _sync_one(session, current_user, record)
        except Exception as exc:  # noqa: BLE001 -- fail this ITEM only, never the batch
            failed += 1
            code = str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "SYNC_ITEM_FAILED"
            # SECURITY FIX (error-handling task, PHI-in-logs audit finding):
            # this branch previously fell through to `f"{type(exc).__name__}:
            # {exc}"` for any exception that wasn't one of this function's
            # own recognised ValueError codes -- including a raw SQLAlchemy/
            # psycopg exception. Confirmed live during an earlier task today
            # (a malformed org_unit_id UUID) that str(exc) for a DB-layer
            # exception includes the full SQL statement AND bound parameter
            # VALUES verbatim -- for this route, that can include a
            # patient's name, phone, and other submitted PHI, returned
            # straight to the client in a 200 response body. Never again:
            # log the real exception server-side only; the client gets a
            # generic, stable message, same pattern as this task's own
            # IntegrityError/catch-all handlers (app/core/errors.py).
            if code not in ("OUT_OF_SCOPE", "NO_FACILITY_CONTEXT"):
                logger.error("POST /sync/ item %d failed: %s: %s", index, type(exc).__name__, exc)
                code = "SYNC_ITEM_FAILED"
            message = "Out of scope for this account." if code == "OUT_OF_SCOPE" else \
                      "No facility/org_unit context available to attribute this record to." if code == "NO_FACILITY_CONTEXT" else \
                      "This record could not be processed. Please check its fields and try again."
            records_out.append({"client_uuid": client_uuid, "status": "rejected", "reason": code})
            results.append({"index": index, "status": "failed", "code": code, "message": message})
            continue

        if outcome["outcome"] == "duplicate":
            duplicates += 1
            results.append({"index": index, "status": "duplicate", "code": "ALREADY_SYNCED",
                             "message": "A record with this client_uuid already exists; no new row created."})
        else:
            created += 1
            results.append({"index": index, "status": "created", "code": "OK", "message": "Record created."})
        records_out.append({"client_uuid": client_uuid, "status": "accepted"})

    session.commit()

    return {
        # ---- unchanged, contract-frozen fields ----
        "synced": len(records),
        "records": records_out,
        # ---- additive: per-item detail ----
        "created": created,
        "duplicates": duplicates,
        "failed": failed,
        "results": results,
    }
