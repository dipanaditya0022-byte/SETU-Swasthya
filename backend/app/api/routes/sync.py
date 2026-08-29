from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/sync", tags=["Sync"])


@router.post("/")
def sync_records(records: list[dict[str, Any]]):
    return {
        "synced": len(records),
        "records": [
            {
                "client_uuid": record.get("client_uuid"),
                "status": "accepted",
            }
            for record in records
        ],
    }
