from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.agent_auth import verify_agent_token
from app.modules.medical_practice import service
from app.modules.medical_practice.schemas import PracticeIn, PracticeOut, AssessmentIn, AssessmentOut

router = APIRouter(prefix="/api/v1/medical", tags=["Medical Practice"])
auth = [Depends(verify_agent_token)]


@router.post("/practices/", response_model=PracticeOut, dependencies=auth)
def create_practice(payload: PracticeIn, db: Session = Depends(get_db)):
    return service.create_practice(db, payload)


@router.get("/practices/", dependencies=auth)
def list_practices(page: int = 1, per_page: int = 50, db: Session = Depends(get_db)):
    return service.list_practices(db, page, per_page)


@router.get("/practices/{practice_id}", response_model=PracticeOut, dependencies=auth)
def get_practice(practice_id: str, db: Session = Depends(get_db)):
    p = service.get_practice(db, practice_id)
    if not p:
        raise HTTPException(404, "Practice not found")
    return p


@router.get("/practices/by-client/{client_id}", response_model=PracticeOut, dependencies=auth)
def get_practice_by_client(client_id: str, db: Session = Depends(get_db)):
    p = service.get_practice_by_client(db, client_id)
    if not p:
        raise HTTPException(404, "No practice linked to this client_id")
    return p


@router.post("/assessments/", response_model=AssessmentOut, dependencies=auth)
def create_assessment(payload: AssessmentIn, db: Session = Depends(get_db)):
    return service.create_assessment(db, payload)


@router.get("/assessments/{practice_id}", dependencies=auth)
def list_assessments(practice_id: str, page: int = 1, per_page: int = 20,
                     db: Session = Depends(get_db)):
    return service.list_assessments(db, practice_id, page, per_page)


@router.get("/compliance/{practice_id}", dependencies=auth)
def compliance_summary(practice_id: str, db: Session = Depends(get_db)):
    return service.get_compliance_summary(db, practice_id)
