from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.database import get_session
from app.models import Patient

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("/", response_model=Patient)
def create_patient(
    patient: Patient,
    session: Session = Depends(get_session),
):
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=Patient)
def get_patient(
    patient_id: UUID,
    session: Session = Depends(get_session),
):
    patient = session.get(Patient, patient_id)

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return patient
