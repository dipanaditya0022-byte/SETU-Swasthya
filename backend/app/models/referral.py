from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel


class Referral(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    patient_id: uuid.UUID
    from_facility_id: uuid.UUID
    destination_facility_id: uuid.UUID
    reason: str
    urgency: str
    status: str = "INITIATED"
    receiving_unit: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # S20: see app/models/patient.py's identical note -- migration
    # 9d5f6b3e0a71 (S10) already added these as NOT NULL DB columns;
    # the route always sets both from the authenticated actor, never
    # trusts a client-supplied value.
    created_by_user_id: Optional[uuid.UUID] = None
    org_unit_id: Optional[uuid.UUID] = None
