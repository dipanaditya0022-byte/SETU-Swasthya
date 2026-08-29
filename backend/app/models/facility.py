from datetime import datetime
import uuid

from sqlmodel import Field, SQLModel


class Facility(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    facility_type: str
    village: str
    district: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
