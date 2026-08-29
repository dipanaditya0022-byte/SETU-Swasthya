from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.database import get_session
from app.models import Referral

router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.post("/", response_model=Referral)
def create_referral(
    referral: Referral,
    session: Session = Depends(get_session),
):
    session.add(referral)
    session.commit()
    session.refresh(referral)
    return referral


@router.patch("/{referral_id}/status", response_model=Referral)
def update_referral_status(
    referral_id: UUID,
    status: str,
    session: Session = Depends(get_session),
):
    referral = session.get(Referral, referral_id)

    if not referral:
        raise HTTPException(status_code=404, detail="Referral not found")

    referral.status = status
    session.add(referral)
    session.commit()
    session.refresh(referral)

    return referral
