import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from app.modules.medical_practice.models import MedicalPractice, MedicalAssessment
from app.modules.medical_practice.schemas import PracticeIn, AssessmentIn

logger = logging.getLogger(__name__)

GRADE_MAP = [(90, "A"), (75, "B"), (60, "C"), (45, "D"), (0, "F")]


def _compute_grade(score: int) -> str:
    for threshold, grade in GRADE_MAP:
        if score >= threshold:
            return grade
    return "F"


def create_practice(db: Session, payload: PracticeIn) -> MedicalPractice:
    existing = db.query(MedicalPractice).filter(MedicalPractice.client_id == payload.client_id).first()
    if existing:
        return existing
    practice = MedicalPractice(**payload.model_dump())
    db.add(practice)
    db.commit()
    db.refresh(practice)
    logger.info(f"Medical practice created: {practice.practice_name}")
    return practice


def list_practices(db: Session, page: int = 1, per_page: int = 50) -> dict:
    q = db.query(MedicalPractice)
    total = q.count()
    items = q.order_by(MedicalPractice.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": items, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_practice(db: Session, practice_id: str) -> Optional[MedicalPractice]:
    return db.query(MedicalPractice).filter(MedicalPractice.id == practice_id).first()


def get_practice_by_client(db: Session, client_id: str) -> Optional[MedicalPractice]:
    return db.query(MedicalPractice).filter(MedicalPractice.client_id == client_id).first()


def create_assessment(db: Session, payload: AssessmentIn) -> MedicalAssessment:
    scores = [s for s in [
        payload.network_score, payload.device_score, payload.software_score,
        payload.backup_score, payload.compliance_score
    ] if s is not None]

    overall = int(sum(scores) / len(scores)) if scores else None
    grade = _compute_grade(overall) if overall is not None else None

    assessment = MedicalAssessment(
        **payload.model_dump(),
        overall_score=overall,
        overall_grade=grade,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    logger.info(f"Medical assessment created for practice {payload.practice_id}: grade {grade}")
    return assessment


def list_assessments(db: Session, practice_id: str, page: int = 1, per_page: int = 20) -> dict:
    q = db.query(MedicalAssessment).filter(MedicalAssessment.practice_id == practice_id)
    total = q.count()
    items = q.order_by(MedicalAssessment.assessment_date.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": items, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_compliance_summary(db: Session, practice_id: str) -> dict:
    """Return latest assessment compliance flags for dashboard."""
    latest = db.query(MedicalAssessment).filter(
        MedicalAssessment.practice_id == practice_id
    ).order_by(MedicalAssessment.assessment_date.desc()).first()

    if not latest:
        return {"status": "no_assessment"}

    return {
        "overall_grade": latest.overall_grade,
        "overall_score": latest.overall_score,
        "popia_compliant": latest.popia_compliant,
        "hpcsa_compliant": latest.hpcsa_compliant,
        "backup_offsite": latest.backup_offsite,
        "encryption_status": latest.encryption_status,
        "assessed_at": latest.assessment_date.isoformat(),
        "recommendations_count": len(latest.recommendations or []),
        "upsell_flags": latest.upsell_flags or [],
    }
