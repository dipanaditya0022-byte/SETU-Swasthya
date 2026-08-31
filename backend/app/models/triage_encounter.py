from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class TriageEncounter(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    patient_id: uuid.UUID
    facility_id: uuid.UUID
    triage_disposition: str
    referral_urgency: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # S20: see app/models/patient.py's identical note -- migration
    # 9d5f6b3e0a71 (S10) already added these as NOT NULL DB columns;
    # the route always sets both from the authenticated actor, never
    # trusts a client-supplied value.
    created_by_user_id: Optional[uuid.UUID] = None
    org_unit_id: Optional[uuid.UUID] = None

    # Triage decisioning step: migration a4d72f9e1c83 already added these
    # nine columns to the real `triageencounter` table; this class was not
    # updated to match until now (same gap as patient.py/referral.py's own
    # S20 notes -- see that migration's own docstring for the
    # nullable/default reasoning per column). The route
    # (app/api/routes/triage.py) always sets every one of these from the
    # triage engine's own TriageOutput, never from client input.
    disposition: Optional[str] = Field(default=None, sa_column=Column("disposition", Text))
    urgency: Optional[str] = Field(default=None, sa_column=Column("urgency", Text))
    reason: Optional[str] = Field(default=None, sa_column=Column("reason", Text))
    red_flags: list[str] = Field(default_factory=list, sa_column=Column("red_flags", JSONB, nullable=False))
    protocol_version: Optional[str] = Field(default=None, sa_column=Column("protocol_version", Text))
    insufficient_data: bool = Field(default=False, sa_column=Column("insufficient_data", Boolean, nullable=False))
    missing_fields: list[str] = Field(default_factory=list, sa_column=Column("missing_fields", JSONB, nullable=False))
    engine: Optional[str] = Field(default=None, sa_column=Column("engine", Text))
    evaluated_at: Optional[datetime] = Field(default=None, sa_column=Column("evaluated_at", DateTime(timezone=True)))
