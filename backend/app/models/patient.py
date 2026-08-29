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
