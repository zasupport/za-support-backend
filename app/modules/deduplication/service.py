import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from app.modules.deduplication.models import DedupScan, DedupItem
from app.modules.deduplication.schemas import ScanIn, DedupItemIn, ActionUpdate, ScanSummary

logger = logging.getLogger(__name__)


def create_scan(db: Session, payload: ScanIn) -> DedupScan:
    scan = DedupScan(**payload.model_dump())
    db.add(scan)
    db.commit()
    db.refresh(scan)
    logger.info(f"Dedup scan created for {payload.client_id}: {payload.recoverable_gb:.2f} GB recoverable")
    return scan


def list_scans(db: Session, client_id: str, page: int = 1, per_page: int = 20) -> dict:
    q = db.query(DedupScan).filter(DedupScan.client_id == client_id)
    total = q.count()
    items = q.order_by(DedupScan.scan_date.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": items, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_scan(db: Session, scan_id: str) -> Optional[DedupScan]:
    return db.query(DedupScan).filter(DedupScan.id == scan_id).first()


def add_items(db: Session, items: List[DedupItemIn]) -> List[DedupItem]:
    created = []
    for item in items:
        obj = DedupItem(**item.model_dump())
        db.add(obj)
        created.append(obj)
    db.commit()
    return created


def list_items(db: Session, scan_id: str, action_filter: Optional[str] = None) -> List[DedupItem]:
    q = db.query(DedupItem).filter(DedupItem.scan_id == scan_id)
    if action_filter:
        q = q.filter(DedupItem.action == action_filter)
    return q.order_by(DedupItem.file_size_mb.desc()).all()


def update_item_action(db: Session, item_id: str, payload: ActionUpdate) -> Optional[DedupItem]:
    item = db.query(DedupItem).filter(DedupItem.id == item_id).first()
    if not item:
        return None
    item.action = payload.action
    db.commit()
    db.refresh(item)
    return item


def mark_scan_complete(db: Session, scan_id: str) -> Optional[DedupScan]:
    scan = get_scan(db, scan_id)
    if scan:
        scan.status = "complete"
        db.commit()
        db.refresh(scan)
    return scan


def get_client_summary(db: Session, client_id: str) -> ScanSummary:
    """Latest scan summary — plain English for client report."""
    latest = db.query(DedupScan).filter(
        DedupScan.client_id == client_id
    ).order_by(DedupScan.scan_date.desc()).first()

    if not latest:
        return ScanSummary(
            client_id=client_id,
            recoverable_gb=0,
            duplicate_sets=0,
            photo_gb=0,
            top_culprit_path=None,
            client_facing_summary="No duplicate scan has been run yet.",
        )

    top = (latest.top_culprits or [{}])[0]
    top_path = top.get("path") if top else None

    if latest.recoverable_gb >= 1:
        summary = (
            f"Your Mac has {latest.recoverable_gb:.1f} GB of duplicate files that can be safely removed, "
            f"freeing up valuable storage space. The biggest contributor is duplicate photos "
            f"({latest.photo_gb:.1f} GB). We recommend a cleanup session."
        )
    else:
        summary = f"Duplicate file scan found {latest.recoverable_gb * 1024:.0f} MB of recoverable space — minimal impact."

    return ScanSummary(
        client_id=client_id,
        recoverable_gb=float(latest.recoverable_gb),
        duplicate_sets=latest.duplicate_sets,
        photo_gb=float(latest.photo_gb),
        top_culprit_path=top_path,
        client_facing_summary=summary,
    )
