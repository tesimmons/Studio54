# app/models/duplicate_recycle.py
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class DuplicateRecycleStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    PERMANENTLY_DELETED = "permanently_deleted"
    RESTORED = "restored"


class DuplicateRecycle(Base):
    __tablename__ = "duplicate_recycle_bin"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    musicbrainz_trackid = Column(String(36), nullable=False)
    original_file_path = Column(Text, nullable=False)
    staging_file_path = Column(Text, nullable=False)
    kept_file_path = Column(Text, nullable=False)
    removed_bitrate_kbps = Column(Integer, nullable=True)
    removed_format = Column(String(20), nullable=True)
    kept_bitrate_kbps = Column(Integer, nullable=True)
    kept_format = Column(String(20), nullable=True)
    recycled_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), nullable=False, default="pending_review")
    restored_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dup_recycle_status", "status"),
        Index("ix_dup_recycle_expires", "expires_at"),
        Index("ix_dup_recycle_trackid", "musicbrainz_trackid"),
    )
