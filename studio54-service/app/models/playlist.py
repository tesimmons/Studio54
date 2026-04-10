"""
Playlist models - User-created playlists
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Playlist(Base):
    """
    Playlist model - User-created collection of tracks

    Allows users to create custom playlists for playback
    """
    __tablename__ = "playlists"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Ownership
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Basic info
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Publishing
    is_published = Column(Boolean, nullable=False, default=False)
    cover_art_url = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    owner = relationship("User", foreign_keys=[user_id])
    playlist_tracks = relationship("PlaylistTrack", back_populates="playlist", cascade="all, delete-orphan", order_by="PlaylistTrack.position")
    playlist_chapters = relationship("PlaylistChapter", back_populates="playlist", cascade="all, delete-orphan", order_by="PlaylistChapter.position")

    def __repr__(self):
        return f"<Playlist(id={self.id}, name='{self.name}', track_count={len(self.playlist_tracks)})>"


class PlaylistTrack(Base):
    """
    PlaylistTrack - Junction table for playlist-track many-to-many relationship

    Includes position field for custom ordering within playlist
    """
    __tablename__ = "playlist_tracks"

    # Composite primary key
    playlist_id = Column(UUID(as_uuid=True), ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
    track_id = Column(UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)

    # Ordering within playlist
    position = Column(Integer, nullable=False)

    # Timestamp
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    playlist = relationship("Playlist", back_populates="playlist_tracks")
    track = relationship("Track")

    def __repr__(self):
        return f"<PlaylistTrack(playlist_id={self.playlist_id}, track_id={self.track_id}, position={self.position})>"


class PlaylistChapter(Base):
    """
    PlaylistChapter - Junction table for playlist-chapter many-to-many relationship

    Allows audiobook chapters to be included in playlists alongside tracks.
    """
    __tablename__ = "playlist_chapters"

    # Composite primary key
    playlist_id = Column(UUID(as_uuid=True), ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), primary_key=True)

    # Ordering within playlist
    position = Column(Integer, nullable=False)

    # Timestamp
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    playlist = relationship("Playlist", back_populates="playlist_chapters")
    chapter = relationship("Chapter")

    def __repr__(self):
        return f"<PlaylistChapter(playlist_id={self.playlist_id}, chapter_id={self.chapter_id}, position={self.position})>"
