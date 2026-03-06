"""
Customer Guides router — HTTP layer only. All logic in service.py.
Prefix: /api/v1/guides
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.customer_guides import service
from app.modules.customer_guides.schemas import GuideCreate, GuideUpdate, GuideOut, SendGuideIn, FeedbackIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/guides", tags=["Customer Guides"])


@router.get("", response_model=dict, dependencies=[Depends(verify_agent_token)])
def list_guides(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_guides(db, category=category, search=search, page=page, per_page=per_page)
    return {
        "data": [GuideOut.model_validate(g) for g in result["data"]],
        "meta": result["meta"],
    }


@router.post("", response_model=GuideOut, dependencies=[Depends(verify_agent_token)])
def create_guide(data: GuideCreate, db: Session = Depends(get_db)):
    return service.create_guide(db, data)


@router.get("/{guide_id}", response_model=GuideOut, dependencies=[Depends(verify_agent_token)])
def get_guide(guide_id: int, db: Session = Depends(get_db)):
    g = service.get_guide(db, guide_id)
    if not g:
        raise HTTPException(status_code=404, detail="Guide not found")
    return g


@router.patch("/{guide_id}", response_model=GuideOut, dependencies=[Depends(verify_agent_token)])
def update_guide(guide_id: int, data: GuideUpdate, db: Session = Depends(get_db)):
    g = service.update_guide(db, guide_id, data)
    if not g:
        raise HTTPException(status_code=404, detail="Guide not found")
    return g


@router.delete("/{guide_id}", status_code=204, dependencies=[Depends(verify_agent_token)])
def delete_guide(guide_id: int, db: Session = Depends(get_db)):
    if not service.delete_guide(db, guide_id):
        raise HTTPException(status_code=404, detail="Guide not found")


@router.post("/{guide_id}/send", dependencies=[Depends(verify_agent_token)])
def send_guide(guide_id: int, data: SendGuideIn, db: Session = Depends(get_db)):
    """Send a guide to a client via email and record the send."""
    g = service.get_guide(db, guide_id)
    if not g:
        raise HTTPException(status_code=404, detail="Guide not found")
    ok = service.send_guide_to_client(db, guide_id, data.client_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not send guide — check client email")
    return {"sent": True}


@router.post("/{guide_id}/feedback", dependencies=[Depends(verify_agent_token)])
def submit_feedback(guide_id: int, data: FeedbackIn, db: Session = Depends(get_db)):
    """Record client feedback on a guide."""
    g = service.get_guide(db, guide_id)
    if not g:
        raise HTTPException(status_code=404, detail="Guide not found")
    fb = service.submit_feedback(db, guide_id, data.client_id, data.helpful, data.comment)
    return {"id": fb.id, "helpful": fb.helpful}


@router.get("/client/{client_id}", dependencies=[Depends(verify_agent_token)])
def client_guides(client_id: str, db: Session = Depends(get_db)):
    """All guides sent to a specific client with viewed/feedback status."""
    return service.get_client_guides(db, client_id)


@router.post("/{guide_id}/viewed", dependencies=[Depends(verify_agent_token)])
def mark_viewed(guide_id: int, client_id: str = Query(...), db: Session = Depends(get_db)):
    service.mark_viewed(db, guide_id, client_id)
    return {"ok": True}
