from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel


class TriageEncounter(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    patient_id: uuid.UUID
    facility_id: uuid.UUID
    triage_disposition: str
    referral_urgency: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
