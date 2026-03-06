"""Customer Guides service — CRUD + client delivery."""
import logging
from typing import Optional, List
from sqlalchemy.orm import Session

from app.modules.customer_guides.models import Guide, GuideClientLink, GuideFeedback
from app.modules.customer_guides.schemas import GuideCreate, GuideUpdate, FeedbackIn

logger = logging.getLogger(__name__)


def list_guides(db: Session, category: Optional[str] = None, page: int = 1, per_page: int = 50) -> dict:
    q = db.query(Guide)
    if category:
        q = q.filter(Guide.category == category)
    total = q.count()
    rows  = q.order_by(Guide.updated_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": rows, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_guide(db: Session, guide_id: int) -> Optional[Guide]:
    return db.query(Guide).filter(Guide.id == guide_id).first()


def create_guide(db: Session, data: GuideCreate) -> Guide:
    row = Guide(
        title=data.title,
        content_md=data.content_md,
        category=data.category,
        tags=data.tags,
        is_public=data.is_public,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(f"Guide created: {row.id} — {row.title}")
    return row


def update_guide(db: Session, guide_id: int, data: GuideUpdate) -> Optional[Guide]:
    row = get_guide(db, guide_id)
    if not row:
        return None
    for field, val in data.model_dump(exclude_none=True).items():
        setattr(row, field, val)
    db.commit()
    db.refresh(row)
    return row


def delete_guide(db: Session, guide_id: int) -> bool:
    row = get_guide(db, guide_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def send_to_client(db: Session, guide_id: int, client_id: str) -> GuideClientLink:
    existing = db.query(GuideClientLink).filter(
        GuideClientLink.guide_id == guide_id,
        GuideClientLink.client_id == client_id,
    ).first()
    if existing:
        return existing
    link = GuideClientLink(guide_id=guide_id, client_id=client_id)
    db.add(link)
    db.commit()
    db.refresh(link)
    logger.info(f"Guide {guide_id} sent to client {client_id}")
    return link


def list_client_guides(db: Session, client_id: str) -> List[Guide]:
    links = db.query(GuideClientLink).filter(GuideClientLink.client_id == client_id).all()
    guide_ids = [l.guide_id for l in links]
    return db.query(Guide).filter(Guide.id.in_(guide_ids)).all()


def submit_feedback(db: Session, guide_id: int, data: FeedbackIn) -> GuideFeedback:
    fb = GuideFeedback(guide_id=guide_id, client_id=data.client_id, helpful=data.helpful, comment=data.comment)
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb
