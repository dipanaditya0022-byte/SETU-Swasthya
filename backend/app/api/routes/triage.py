from uuid import UUID

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.database import get_session
from app.models import TriageEncounter

router = APIRouter(prefix="/triage", tags=["Triage"])


@router.post("/", response_model=TriageEncounter)
def create_triage(
    triage: TriageEncounter,
    session: Session = Depends(get_session),
):
    session.add(triage)
    session.commit()
    session.refresh(triage)
    return triage
