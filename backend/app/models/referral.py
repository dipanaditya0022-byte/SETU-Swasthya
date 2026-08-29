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
