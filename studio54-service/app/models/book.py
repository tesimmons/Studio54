"""
Book model - Audiobook release tracking (mirrors Album for audiobooks)
"""
import uuid
import enum
from datetime import datetime, timezone, date
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer, Date, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class BookStatus(str, enum.Enum):
    """Book download status"""
    WANTED = "wanted"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


class Book(Base):
    """
    Book model - Represents an audiobook release

    Links to MusicBrainz release groups.
    Mirrors Album but for audiobook content.
    """
    __tablename__ = "books"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    author_id = Column(UUID(as_uuid=True), ForeignKey("authors.id", ondelete="CASCADE"), nullable=False, index=True)
    series_id = Column(UUID(as_uuid=True), ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True)

    # Series info
    series_position = Column(Integer, nullable=True)  # Book's order within its series (1, 2, 3)
    related_series = Column(Text, nullable=True)  # User-editable free-form cross-series references

    # Basic info
    title = Column(Text, nullable=False, index=True)
    musicbrainz_id = Column(String(100), unique=True, nullable=False, index=True)  # Release group MBID
    release_mbid = Column(String(36), nullable=True, index=True)  # Specific release MBID

    # Release metadata
    release_date = Column(Date, nullable=True)
    album_type = Column(String(100), nullable=True)  # "Album" typically for audiobooks
    secondary_types = Column(Text, nullable=True)  # Comma-separated, should include "Audiobook"
    chapter_count = Column(Integer, default=0)

    # Status tracking (defaults to unmonitored)
    status = Column(Enum(BookStatus), default=BookStatus.WANTED, nullable=False, index=True)
    monitored = Column(Boolean, default=False, nullable=False)

    # Display metadata
    credit_name = Column(Text, nullable=True)  # Full artist credit string (e.g. "David Weber & Timothy Zahn")

    # Media
    cover_art_url = Column(Text, nullable=True)

    # Custom folder path
    custom_folder_path = Column(Text, nullable=True)

    # Search and quality tracking
    last_search_time = Column(DateTime(timezone=True), nullable=True)
    quality_meets_cutoff = Column(Boolean, default=True, nullable=False)

    # Timestamps
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    searched_at = Column(DateTime(timezone=True), nullable=True)
    downloaded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    author = relationship("Author", back_populates="books")
    series = relationship("Series", back_populates="books")
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    downloads = relationship("DownloadQueue", back_populates="book", foreign_keys="DownloadQueue.book_id")

    def __repr__(self):
        return f"<Book(id={self.id}, title='{self.title}', author_id='{self.author_id}', status='{self.status}')>"
