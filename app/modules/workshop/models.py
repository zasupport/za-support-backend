from datetime import date, datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, Numeric, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class WorkshopJob(Base):
    __tablename__ = "workshop_jobs"

    id             = Column(Integer, primary_key=True)
    job_ref        = Column(String, nullable=False, unique=True)
    client_id      = Column(String, nullable=False, index=True)
    serial         = Column(String)
    title          = Column(Text, nullable=False)
    description    = Column(Text)
    status         = Column(String, nullable=False, default="open")
    priority       = Column(String, nullable=False, default="normal")
    source         = Column(String, nullable=False, default="manual")
    snapshot_id    = Column(Integer)
    assigned_to    = Column(String, default="courtney@zasupport.com")
    scheduled_date = Column(Date)
    completed_at   = Column(DateTime(timezone=True))
    labour_minutes = Column(Integer)
    total_incl_vat = Column(Numeric(10, 2))
    notes          = Column(Text)
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at     = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    line_items = relationship("WorkshopLineItem", back_populates="job", cascade="all, delete-orphan")
    history    = relationship("WorkshopJobHistory", back_populates="job", cascade="all, delete-orphan")


class WorkshopLineItem(Base):
    __tablename__ = "workshop_line_items"

    id          = Column(Integer, primary_key=True)
    job_id      = Column(Integer, ForeignKey("workshop_jobs.id", ondelete="CASCADE"), nullable=False)
    description = Column(Text, nullable=False)
    qty         = Column(Integer, nullable=False, default=1)
    unit_price  = Column(Numeric(10, 2))
    line_total  = Column(Numeric(10, 2))
    item_type   = Column(String, default="labour")
    created_at  = Column(DateTime(timezone=True), default=datetime.utcnow)

    job = relationship("WorkshopJob", back_populates="line_items")


class WorkshopJobHistory(Base):
    __tablename__ = "workshop_job_history"

    id          = Column(Integer, primary_key=True)
    job_id      = Column(Integer, ForeignKey("workshop_jobs.id", ondelete="CASCADE"), nullable=False)
    from_status = Column(String)
    to_status   = Column(String, nullable=False)
    note        = Column(Text)
    changed_by  = Column(String, default="system")
    changed_at  = Column(DateTime(timezone=True), default=datetime.utcnow)

    job = relationship("WorkshopJob", back_populates="history")
