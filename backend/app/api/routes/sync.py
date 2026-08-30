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
"""
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

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
    for record in records:
        client_uuid = record.get("client_uuid")
        record_org_unit_id = record.get("org_unit_id")
        if record_org_unit_id and not org_unit_is_within_scope(
            session, record_org_unit_id, current_user.scope_org_unit_id
        ):
            results.append({"client_uuid": client_uuid, "status": "rejected", "reason": "OUT_OF_SCOPE"})
            continue
        results.append({"client_uuid": client_uuid, "status": "accepted"})

    return {
        "synced": len(records),
        "records": results,
    }
