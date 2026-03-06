"""Customer Guides router — HTTP layer only. Prefix: /api/v1/guides"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.customer_guides import service
from app.modules.customer_guides.schemas import GuideCreate, GuideUpdate, GuideOut, FeedbackIn, SendGuideIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/guides", tags=["Customer Guides"])


@router.get("", response_model=dict, dependencies=[Depends(verify_agent_token)])
def list_guides(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_guides(db, category=category, page=page, per_page=per_page)
    return {
        "data": [GuideOut.model_validate(g) for g in result["data"]],
        "meta": result["meta"],
    }


@router.post("", response_model=GuideOut, dependencies=[Depends(verify_agent_token)])
def create_guide(data: GuideCreate, db: Session = Depends(get_db)):
    return service.create_guide(db, data)


@router.get("/{guide_id}", response_model=GuideOut, dependencies=[Depends(verify_agent_token)])
def get_guide(guide_id: int, db: Session = Depends(get_db)):
    row = service.get_guide(db, guide_id)
    if not row:
        raise HTTPException(status_code=404, detail="Guide not found")
    return row


@router.patch("/{guide_id}", response_model=GuideOut, dependencies=[Depends(verify_agent_token)])
def update_guide(guide_id: int, data: GuideUpdate, db: Session = Depends(get_db)):
    row = service.update_guide(db, guide_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Guide not found")
    return row


@router.delete("/{guide_id}", status_code=204, dependencies=[Depends(verify_agent_token)])
def delete_guide(guide_id: int, db: Session = Depends(get_db)):
    if not service.delete_guide(db, guide_id):
        raise HTTPException(status_code=404, detail="Guide not found")


@router.post("/{guide_id}/send", dependencies=[Depends(verify_agent_token)])
def send_guide(guide_id: int, body: SendGuideIn, db: Session = Depends(get_db)):
    if not service.get_guide(db, guide_id):
        raise HTTPException(status_code=404, detail="Guide not found")
    link = service.send_to_client(db, guide_id, body.client_id)
    return {"guide_id": guide_id, "client_id": body.client_id, "sent_at": str(link.sent_at)}


@router.get("/client/{client_id}", response_model=List[GuideOut], dependencies=[Depends(verify_agent_token)])
def client_guides(client_id: str, db: Session = Depends(get_db)):
    return service.list_client_guides(db, client_id)


@router.post("/{guide_id}/feedback", dependencies=[Depends(verify_agent_token)])
def submit_feedback(guide_id: int, data: FeedbackIn, db: Session = Depends(get_db)):
    if not service.get_guide(db, guide_id):
        raise HTTPException(status_code=404, detail="Guide not found")
    return service.submit_feedback(db, guide_id, data)
