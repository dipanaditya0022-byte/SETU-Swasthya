from datetime import datetime, timezone
from typing import Optional
import uuid

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

from app.models.referral_state import ReferralState


class Referral(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    patient_id: uuid.UUID
    from_facility_id: uuid.UUID
    destination_facility_id: uuid.UUID
    reason: str
    urgency: str

    # D2-S7: FIX -- `status` was previously declared `status: str = "INITIATED"`,
    # which SQLAlchemy bound as VARCHAR on every INSERT/UPDATE. Migration
    # d4f1c9b7a582 already converted the live `referral.status` column to a
    # real 13-state Postgres enum (`referral_status`), so every write through
    # the old `str` mapping failed with psycopg's DatatypeMismatch ("column
    # status is of type referral_status but expression is of type character
    # varying"). Fixed the same way app/models/triage_encounter.py's own
    # decision columns were fixed after their own migration (a4d72f9e1c83):
    # an explicit sa_column carrying the real SQLAlchemy type.
    # `create_type=False` is deliberate -- the Postgres type already exists
    # (created idempotently by the migration itself); SQLAlchemy must never
    # attempt to CREATE TYPE on table-create/metadata operations, which
    # would collide on every environment that already ran the migration.
    # ReferralState's members are a `str, Enum` with member NAME == member
    # VALUE for all 13 states (see app/models/referral_state.py), so
    # SQLAlchemy's default name-based enum binding already round-trips
    # correctly against the DB values written by the migration's own Phase-3
    # backfill -- no separate `values_callable` needed.
    status: ReferralState = Field(
        default=ReferralState.INITIATED,
        sa_column=Column(
            "status",
            sa.Enum(ReferralState, name="referral_status", create_type=False),
            nullable=False,
        ),
    )

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

    # ------------------------------------------------------------------
    # D2-S7: referral workflow columns added by migration d4f1c9b7a582.
    # This model was not updated to match until now -- same gap as
    # patient.py/triage_encounter.py's own earlier S20 notes (see that
    # migration's own docstring for the nullable/NOT-NULL reasoning per
    # column). The route (app/api/routes/referrals.py) is the only writer
    # of these; a client can technically submit them on POST /referrals/
    # (the whole model is the request body there, same pre-existing
    # pattern as created_by_user_id/org_unit_id above) but every one of
    # them is functionally inert at creation time since the referral is
    # always INITIATED on creation and these are all later-transition
    # fields -- fixing that (if desired) is a separate concern, out of
    # scope for this step, which is the PATCH .../status endpoint only.
    # ------------------------------------------------------------------
    # default_factory uses an explicit tz-aware UTC `now()`, not the naive
    # `datetime.utcnow` pattern `created_at` above uses -- `created_at` is
    # backed by a naive `DateTime()` column (migration 79a9d8f8db61) where
    # that's correct, but `initiated_at` is `TIMESTAMPTZ` (migration
    # d4f1c9b7a582), and the migration's own docstring flags exactly this
    # class of bug: inserting a naive datetime into a timestamptz column
    # is interpreted per the DB session's own `TimeZone` setting, not
    # assumed UTC. A tz-aware value removes that ambiguity entirely.
    initiated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column("initiated_at", DateTime(timezone=True), nullable=False),
    )
    due_at: Optional[datetime] = Field(default=None, sa_column=Column("due_at", DateTime(timezone=True)))
    breached_at: Optional[datetime] = Field(default=None, sa_column=Column("breached_at", DateTime(timezone=True)))
    breach_detected_by: Optional[str] = Field(default=None, sa_column=Column("breach_detected_by", Text))
    escalation_stage: int = Field(default=0, sa_column=Column("escalation_stage", SmallInteger, nullable=False))
    escalation_notified_at: Optional[datetime] = Field(
        default=None, sa_column=Column("escalation_notified_at", DateTime(timezone=True))
    )
    owner_user_id: Optional[uuid.UUID] = Field(default=None, sa_column=Column("owner_user_id", PGUUID(as_uuid=True)))
    arrived_at: Optional[datetime] = Field(default=None, sa_column=Column("arrived_at", DateTime(timezone=True)))
    back_referred_at: Optional[datetime] = Field(
        default=None, sa_column=Column("back_referred_at", DateTime(timezone=True))
    )
    closed_at: Optional[datetime] = Field(default=None, sa_column=Column("closed_at", DateTime(timezone=True)))
    slot_datetime: Optional[datetime] = Field(default=None, sa_column=Column("slot_datetime", DateTime(timezone=True)))
    transport_mode: Optional[str] = Field(default=None, sa_column=Column("transport_mode", Text))
    arrival_confirmed_by: Optional[uuid.UUID] = Field(
        default=None, sa_column=Column("arrival_confirmed_by", PGUUID(as_uuid=True))
    )
    arrival_scan_ref: Optional[str] = Field(default=None, sa_column=Column("arrival_scan_ref", Text))
    refusal_reason: Optional[str] = Field(default=None, sa_column=Column("refusal_reason", Text))
    loss_reason: Optional[str] = Field(default=None, sa_column=Column("loss_reason", Text))
    cancellation_reason: Optional[str] = Field(default=None, sa_column=Column("cancellation_reason", Text))
    back_referral_note: Optional[str] = Field(default=None, sa_column=Column("back_referral_note", Text))

    # Dashboard step: migration b9e4c7a2f815 added this nullable column.
    # NEVER set by any route today -- `referral` has no `client_uuid`
    # column to match an incoming sync batch record against (see that
    # migration's own docstring "THE SYNC/synced_at GAP" and
    # app/api/routes/sync.py's own module docstring). Stays NULL until a
    # future, separate migration adds `client_uuid` here.
    synced_at: Optional[datetime] = Field(default=None, sa_column=Column("synced_at", DateTime(timezone=True)))
