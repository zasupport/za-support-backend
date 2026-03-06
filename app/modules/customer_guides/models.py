from sqlalchemy import Column, Integer, Text, Boolean, ARRAY, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class Guide(Base):
    __tablename__ = "guides"

    id          = Column(Integer, primary_key=True)
    title       = Column(Text, nullable=False)
    content_md  = Column(Text, nullable=False)
    category    = Column(Text)
    tags        = Column(ARRAY(Text), default=[])
    created_by  = Column(Text, default="courtney")
    is_public   = Column(Boolean, default=False)
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())


class GuideClientLink(Base):
    __tablename__ = "guide_client_links"

    id        = Column(Integer, primary_key=True)
    guide_id  = Column(Integer, ForeignKey("guides.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Text, nullable=False)
    sent_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())
    viewed_at = Column(TIMESTAMP(timezone=True))


class GuideFeedback(Base):
    __tablename__ = "guide_feedback"

    id         = Column(Integer, primary_key=True)
    guide_id   = Column(Integer, ForeignKey("guides.id", ondelete="CASCADE"), nullable=False)
    client_id  = Column(Text, nullable=False)
    helpful    = Column(Boolean, nullable=False)
    comment    = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
