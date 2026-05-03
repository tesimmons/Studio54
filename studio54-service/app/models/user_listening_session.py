"""
UserListeningSession model — per-user audiobook session (book or series).

Owns the chapter queue and current position within it.
BookProgress owns the millisecond position within the current chapter.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from app.database import Base


class UserListeningSession(Base):
    __tablename__ = "user_listening_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_type = Column(String(10), nullable=False)  # "book" | "series"
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=True)
    series_id = Column(UUID(as_uuid=True), ForeignKey("series.id", ondelete="CASCADE"), nullable=True)
    chapter_queue = Column(JSON, nullable=False, default=list)
    current_index = Column(Integer, nullable=False, default=0)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    pending_delete_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "(book_id IS NOT NULL AND series_id IS NULL) OR (book_id IS NULL AND series_id IS NOT NULL)",
            name="ck_uls_exactly_one_fk",
        ),
        Index(
            "uq_uls_user_book", "user_id", "book_id",
            unique=True, postgresql_where=text("series_id IS NULL"),
        ),
        Index(
            "uq_uls_user_series", "user_id", "series_id",
            unique=True, postgresql_where=text("book_id IS NULL"),
        ),
    )
