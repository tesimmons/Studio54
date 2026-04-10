"""
Author model - Audiobook authors (mirrors Artist for audiobooks)
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.artist import MonitorType


class Author(Base):
    """
    Author model - Represents a monitored audiobook author

    Links to MusicBrainz via musicbrainz_id for metadata synchronization.
    Mirrors Artist but for audiobook content.
    """
    __tablename__ = "authors"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic info
    name = Column(Text, nullable=False, index=True)
    musicbrainz_id = Column(String(100), unique=True, nullable=False, index=True)

    # Monitoring settings (defaults to unmonitored)
    is_monitored = Column(Boolean, default=False, nullable=False)
    quality_profile_id = Column(UUID(as_uuid=True), ForeignKey("quality_profiles.id"), nullable=True)
    monitor_type = Column(String(30), default=MonitorType.NONE.value, nullable=False)

    # File organization
    root_folder_path = Column(Text, nullable=True)

    # Metadata
    overview = Column(Text, nullable=True)
    genre = Column(String(255), nullable=True)
    country = Column(String(100), nullable=True)
    image_url = Column(Text, nullable=True)

    # Import source tracking
    import_source = Column(String(100), nullable=True)  # 'studio54', 'manual'
    studio54_library_path_id = Column(UUID(as_uuid=True), ForeignKey("library_paths.id"), nullable=True)

    # Statistics
    book_count = Column(Integer, default=0)
    series_count = Column(Integer, default=0)
    chapter_count = Column(Integer, default=0)

    # Timestamps
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    quality_profile = relationship("QualityProfile", backref="authors")
    books = relationship("Book", back_populates="author", cascade="all, delete-orphan")
    series = relationship("Series", back_populates="author", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Author(id={self.id}, name='{self.name}', musicbrainz_id='{self.musicbrainz_id}')>"
