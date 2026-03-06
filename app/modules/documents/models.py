from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.core.database import Base


class ClientDocument(Base):
    __tablename__ = "client_documents"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id       = Column(String, nullable=False, index=True)
    filename        = Column(String, nullable=False)
    document_type   = Column(String)          # cyberpulse_report|cybershield_report|assessment|guide|invoice|other
    onedrive_id     = Column(String)          # Microsoft Graph item ID
    onedrive_url    = Column(Text)            # sharing URL
    onedrive_path   = Column(Text)            # path within OneDrive
    file_size_bytes = Column(String)
    mime_type       = Column(String)
    shared_with_client = Column(Boolean, default=False)
    share_link      = Column(Text)
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))
