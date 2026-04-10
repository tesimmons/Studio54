"""
Chapter model - Individual audiobook chapters (mirrors Track for audiobooks)
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Chapter(Base):
    """
    Chapter model - Represents an individual audiobook chapter/recording

    Links to MusicBrainz recordings via musicbrainz_id.
    Mirrors Track but for audiobook content (no lyrics fields).
    """
    __tablename__ = "chapters"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)

    # Basic info
    title = Column(Text, nullable=False)
    musicbrainz_id = Column(String(100), nullable=True, index=True)  # Recording MBID

    # Chapter metadata
    chapter_number = Column(Integer, nullable=True)
    disc_number = Column(Integer, default=1)
    duration_ms = Column(Integer, nullable=True)

    # File tracking
    has_file = Column(Boolean, default=False)
    file_path = Column(Text, nullable=True, index=True)

    # Play tracking
    play_count = Column(Integer, default=0, server_default="0")
    last_played_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    book = relationship("Book", back_populates="chapters")

    def __repr__(self):
        return f"<Chapter(id={self.id}, title='{self.title}', chapter_number={self.chapter_number})>"
