"""
BookPlaylist models - Series-ordered chapter playlists for audiobooks
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class BookPlaylist(Base):
    """A sequential playlist of all chapters across all books in a series."""
    __tablename__ = "book_playlists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    series_id = Column(UUID(as_uuid=True), ForeignKey("series.id", ondelete="CASCADE"),
                       nullable=False, unique=True)
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    series = relationship("Series", back_populates="playlist")
    entries = relationship("BookPlaylistChapter", back_populates="playlist",
                           order_by="BookPlaylistChapter.position",
                           cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BookPlaylist(id={self.id}, name='{self.name}', series_id={self.series_id})>"


class BookPlaylistChapter(Base):
    """A single chapter entry in a book playlist."""
    __tablename__ = "book_playlist_chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    playlist_id = Column(UUID(as_uuid=True), ForeignKey("book_playlists.id", ondelete="CASCADE"),
                         nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"),
                        nullable=False)
    position = Column(Integer, nullable=False)
    book_position = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("playlist_id", "chapter_id", name="uq_book_playlist_chapter"),
        Index("ix_book_playlist_chapters_playlist_position", "playlist_id", "position"),
    )

    # Relationships
    playlist = relationship("BookPlaylist", back_populates="entries")
    chapter = relationship("Chapter")

    def __repr__(self):
        return f"<BookPlaylistChapter(playlist_id={self.playlist_id}, position={self.position})>"
