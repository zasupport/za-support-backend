from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
import uuid


class ScanIn(BaseModel):
    client_id: str
    total_files: int = 0
    duplicate_sets: int = 0
    recoverable_gb: float = 0.0
    photo_gb: float = 0.0
    document_gb: float = 0.0
    other_gb: float = 0.0
    top_culprits: List[dict] = []
    notes: Optional[str] = None


class ScanOut(ScanIn):
    id: uuid.UUID
    status: str
    scan_date: datetime
    created_at: datetime
    class Config:
        from_attributes = True


class DedupItemIn(BaseModel):
    scan_id: uuid.UUID
    file_hash: str
    file_paths: List[str]
    file_size_mb: float
    file_type: str = "other"
    keep_path: Optional[str] = None
    action: str = "review"


class DedupItemOut(DedupItemIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class ActionUpdate(BaseModel):
    action: str  # keep|delete|review


class ScanSummary(BaseModel):
    client_id: str
    recoverable_gb: float
    duplicate_sets: int
    photo_gb: float
    top_culprit_path: Optional[str]
    client_facing_summary: str  # plain English for reports
