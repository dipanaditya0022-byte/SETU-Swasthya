from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel


class Patient(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    age: int
    village: str
    phone: Optional[str] = None
    facility_id: uuid.UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    client_uuid: Optional[str] = None

    # S20: migration 9d5f6b3e0a71 (S10) already added these two columns
    # to the real `patient` table as NOT NULL, but this SQLModel class
    # was never updated to match -- meaning POST /patients/ was broken
    # (would fail a NOT NULL violation) until this step. Optional here
    # only at the Python/request-schema level: the route always sets
    # both from the authenticated actor before insert, never trusts a
    # client-supplied value for either (S20 report, "PART 1").
    created_by_user_id: Optional[uuid.UUID] = None
    org_unit_id: Optional[uuid.UUID] = None
