from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from typing import List

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.vault import service
from app.modules.vault.schemas import (
    VaultEntryCreate, VaultEntryUpdate,
    VaultEntryMeta, VaultEntryFull, VaultAuditLogEntry,
)

router = APIRouter(prefix="/api/v1/vault", tags=["vault"])


def _performer(request: Request) -> str:
    # Use the Authorization header token's last 8 chars as a stable identifier,
    # falling back to client IP so audit logs reflect who made the request.
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    return f"token:{token[-8:]}" if token else _ip(request)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/entries", response_model=VaultEntryMeta, dependencies=[Depends(verify_agent_token)])
def create_entry(payload: VaultEntryCreate, request: Request, db: Session = Depends(get_db)):
    return service.create_entry(db, payload.model_dump(), _performer(request), _ip(request))


@router.get("/entries", response_model=List[VaultEntryMeta], dependencies=[Depends(verify_agent_token)])
def list_entries(client_id: str = Query(...), db: Session = Depends(get_db)):
    return service.list_entries(db, client_id)


@router.get("/entries/expiring", response_model=List[VaultEntryMeta], dependencies=[Depends(verify_agent_token)])
def get_expiring(days: int = Query(30), db: Session = Depends(get_db)):
    return service.get_expiring(db, days)


@router.get("/entries/{entry_id}", response_model=VaultEntryFull, dependencies=[Depends(verify_agent_token)])
def get_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = service.get_entry(db, entry_id, _performer(request), _ip(request))
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.put("/entries/{entry_id}", response_model=VaultEntryMeta, dependencies=[Depends(verify_agent_token)])
def update_entry(entry_id: int, payload: VaultEntryUpdate, request: Request, db: Session = Depends(get_db)):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    row = service.update_entry(db, entry_id, data, _performer(request), _ip(request))
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    return row


@router.delete("/entries/{entry_id}", dependencies=[Depends(verify_agent_token)])
def delete_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    ok = service.delete_entry(db, entry_id, _performer(request), _ip(request))
    if not ok:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"deleted": True}


@router.post("/entries/{entry_id}/rotate", response_model=VaultEntryMeta, dependencies=[Depends(verify_agent_token)])
def rotate_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    row = service.rotate_entry(db, entry_id, _performer(request), _ip(request))
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    return row


@router.get("/audit", response_model=List[VaultAuditLogEntry], dependencies=[Depends(verify_agent_token)])
def get_audit_log(entry_id: int = Query(...), db: Session = Depends(get_db)):
    return service.get_audit_log(db, entry_id)
