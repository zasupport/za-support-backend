from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, JSON, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class DedupScan(Base):
    __tablename__ = "dedup_scans"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id       = Column(String, nullable=False, index=True)
    scan_date       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    total_files     = Column(Integer, default=0)
    duplicate_sets  = Column(Integer, default=0)
    recoverable_gb  = Column(Numeric(10, 3), default=0)
    photo_gb        = Column(Numeric(10, 3), default=0)      # photos are primary culprit
    document_gb     = Column(Numeric(10, 3), default=0)
    other_gb        = Column(Numeric(10, 3), default=0)
    top_culprits    = Column(JSON, default=list)             # [{path, size_gb, count}]
    status          = Column(String, default="pending")      # pending|complete|reviewed|actioned
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    items = relationship("DedupItem", back_populates="scan", cascade="all, delete-orphan")


class DedupItem(Base):
    __tablename__ = "dedup_items"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id      = Column(UUID(as_uuid=True), ForeignKey("dedup_scans.id", ondelete="CASCADE"), nullable=False)
    file_hash    = Column(String, nullable=False)
    file_paths   = Column(JSON, default=list)   # all paths sharing this hash
    file_size_mb = Column(Numeric(10, 3))
    file_type    = Column(String)               # photo|document|video|archive|other
    keep_path    = Column(Text)                 # path recommended to keep
    action       = Column(String, default="review")  # keep|delete|review
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    scan = relationship("DedupScan", back_populates="items")
