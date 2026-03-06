from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.agent_auth import verify_agent_token
from app.modules.deduplication import service
from app.modules.deduplication.schemas import (
    ScanIn, ScanOut, DedupItemIn, DedupItemOut, ActionUpdate, ScanSummary
)

router = APIRouter(prefix="/api/v1/dedup", tags=["Deduplication"])
auth = [Depends(verify_agent_token)]


@router.post("/scans/", response_model=ScanOut, dependencies=auth)
def create_scan(payload: ScanIn, db: Session = Depends(get_db)):
    return service.create_scan(db, payload)


@router.get("/scans/{client_id}", dependencies=auth)
def list_scans(client_id: str, page: int = 1, per_page: int = 20, db: Session = Depends(get_db)):
    return service.list_scans(db, client_id, page, per_page)


@router.get("/scans/{scan_id}/items", dependencies=auth)
def list_items(scan_id: str, action: Optional[str] = None, db: Session = Depends(get_db)):
    return service.list_items(db, scan_id, action)


@router.post("/scans/{scan_id}/items", dependencies=auth)
def add_items(scan_id: str, items: List[DedupItemIn], db: Session = Depends(get_db)):
    created = service.add_items(db, items)
    return {"added": len(created)}


@router.post("/scans/{scan_id}/complete", dependencies=auth)
def complete_scan(scan_id: str, db: Session = Depends(get_db)):
    scan = service.mark_scan_complete(db, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    return {"status": "complete", "recoverable_gb": float(scan.recoverable_gb)}


@router.patch("/items/{item_id}/action", dependencies=auth)
def update_action(item_id: str, payload: ActionUpdate, db: Session = Depends(get_db)):
    item = service.update_item_action(db, item_id, payload)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.get("/summary/{client_id}", response_model=ScanSummary, dependencies=auth)
def client_summary(client_id: str, db: Session = Depends(get_db)):
    return service.get_client_summary(db, client_id)
