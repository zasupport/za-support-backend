from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, JSON, Numeric, Boolean
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.core.database import Base


class ResearchItem(Base):
    __tablename__ = "research_items"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title        = Column(String, nullable=False)
    summary      = Column(Text)
    source       = Column(String)             # hn|arxiv|producthunt|github|crunchbase
    url          = Column(Text)
    category     = Column(String)             # voice_ai|autonomous_agents|ai_tools|investment|other
    relevance    = Column(String, default="medium")  # high|medium|low
    investment_usd = Column(Numeric(15, 0))   # funding amount if applicable
    tags         = Column(JSON, default=list)
    published_at = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    included_in_digest = Column(Boolean, default=False)


class ResearchDigest(Base):
    __tablename__ = "research_digests"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    week_of      = Column(DateTime(timezone=True), nullable=False)
    summary_md   = Column(Text)               # Claude-generated weekly summary
    item_ids     = Column(JSON, default=list) # list of ResearchItem UUIDs
    sent_at      = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
