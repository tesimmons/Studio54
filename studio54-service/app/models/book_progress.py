"""
BookProgress model - Per-user audiobook playback progress tracking
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class BookProgress(Base):
    __tablename__ = "book_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    position_ms = Column(Integer, nullable=False, default=0)
    completed = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    book = relationship("Book", lazy="joined")
    chapter = relationship("Chapter", lazy="joined")

    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_book_progress_user_book"),
    )
