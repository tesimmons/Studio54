"""
UnlinkedFile model - Tracks library files that couldn't be linked to album tracks
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class UnlinkedFile(Base):
    """
    UnlinkedFile - Records why a library file couldn't be linked to a track

    Populated by link_files_task after each run. Uses UPSERT so re-runs
    update existing entries rather than duplicating. Files that get linked
    are marked resolved_at so progress is visible over time.
    """
    __tablename__ = "unlinked_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    library_file_id = Column(UUID(as_uuid=True), ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, unique=True)
    file_path = Column(Text, nullable=False)
    artist = Column(Text, nullable=True)
    album = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    musicbrainz_trackid = Column(String(36), nullable=True)
    reason = Column(String(100), nullable=False)
    reason_detail = Column(Text, nullable=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("file_organization_jobs.id", ondelete="SET NULL"), nullable=True)
    detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('idx_unlinked_files_reason', 'reason'),
        Index('idx_unlinked_files_library_file', 'library_file_id'),
        Index('idx_unlinked_files_resolved', 'resolved_at'),
    )

    def __repr__(self):
        return f"<UnlinkedFile(id={self.id}, reason='{self.reason}', file='{self.file_path}')>"
