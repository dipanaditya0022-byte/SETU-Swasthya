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
"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, text

from app.core.authz import get_current_active_user, org_unit_is_within_scope
from app.db.database import get_session

router = APIRouter(prefix="/sync", tags=["Sync"])


@router.post("/")
def sync_records(
    records: list[dict[str, Any]],
    current_user=Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    results = []
    accepted_client_uuids: list[str] = []
    for record in records:
        client_uuid = record.get("client_uuid")
        record_org_unit_id = record.get("org_unit_id")
        if record_org_unit_id and not org_unit_is_within_scope(
            session, record_org_unit_id, current_user.scope_org_unit_id
        ):
            results.append({"client_uuid": client_uuid, "status": "rejected", "reason": "OUT_OF_SCOPE"})
            continue
        results.append({"client_uuid": client_uuid, "status": "accepted"})
        if client_uuid:
            accepted_client_uuids.append(str(client_uuid))

    # ---- additive: stamp patient.synced_at for accepted records whose
    # client_uuid matches an existing patient row -- see module docstring
    # above for why this is patient-only and why the scope re-check is a
    # single set-based statement. Fail-closed: an actor with no posting
    # (scope_org_unit_id is None) never matches anything here. ----
    if accepted_client_uuids and current_user.scope_org_unit_id is not None:
        actor_row = session.exec(
            text("SELECT path FROM org_units WHERE id = :id"),
            params={"id": str(current_user.scope_org_unit_id)},
        ).first()
        if actor_row is not None:
            actor_path = actor_row[0]
            session.exec(
                text(
                    "UPDATE patient SET synced_at = :now "
                    "WHERE client_uuid = ANY(:uuids) "
                    "AND org_unit_id IN ("
                    "  SELECT id FROM org_units WHERE path = :actor_path OR path LIKE :path_prefix"
                    ")"
                ),
                params={
                    "now": datetime.now(timezone.utc),
                    "uuids": accepted_client_uuids,
                    "actor_path": actor_path,
                    "path_prefix": actor_path.rstrip("/") + "/%",
                },
            )
            session.commit()

    return {
        "synced": len(records),
        "records": results,
    }
