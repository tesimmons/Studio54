"""
Scheduled Job Model — User-configurable periodic task scheduling.

Stores job schedules that are checked by a Celery beat task every 5 minutes.
"""
import uuid
import enum
from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class ScheduleFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    task_key = Column(String(255), nullable=False)
    frequency = Column(String(50), nullable=False)  # daily/weekly/monthly/quarterly
    enabled = Column(Boolean, default=True)

    # Scheduling
    run_at_hour = Column(Integer, default=2)          # Hour of day (0-23)
    day_of_week = Column(Integer, nullable=True)      # 0=Mon..6=Sun (weekly only)
    day_of_month = Column(Integer, nullable=True)     # 1-28 (monthly/quarterly)

    # Task config
    task_params = Column(JSON, nullable=True)         # Optional params

    # Tracking
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_job_id = Column(UUID(as_uuid=True), nullable=True)
    last_status = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ScheduledJob(id={self.id}, name='{self.name}', task='{self.task_key}', freq='{self.frequency}')>"
