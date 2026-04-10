"""
Track model - Individual recordings
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Track(Base):
    """
    Track model - Represents an individual recording/track

    Links to MusicBrainz recordings via musicbrainz_id
    """
    __tablename__ = "tracks"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    album_id = Column(UUID(as_uuid=True), ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True)

    # Basic info
    title = Column(Text, nullable=False)
    musicbrainz_id = Column(String(36), nullable=True, index=True)  # Recording MBID

    # Track metadata
    track_number = Column(Integer, nullable=True)
    disc_number = Column(Integer, default=1)
    duration_ms = Column(Integer, nullable=True)  # Duration in milliseconds

    # File tracking
    has_file = Column(Boolean, default=False)
    file_path = Column(Text, nullable=True, index=True)  # Absolute path to the audio file
    muse_file_id = Column(UUID(as_uuid=True), nullable=True)  # External reference to MUSE music_file

    # Lyrics (cached from LRCLIB)
    synced_lyrics = Column(Text, nullable=True)  # LRC format with timestamps
    plain_lyrics = Column(Text, nullable=True)  # Plain text fallback
    lyrics_source = Column(String(50), nullable=True)  # e.g., "lrclib"

    # Play tracking
    play_count = Column(Integer, default=0, server_default="0")
    last_played_at = Column(DateTime(timezone=True), nullable=True)

    # Rating (1-5 stars, null = unrated) — legacy single-user rating
    rating = Column(Integer, nullable=True)

    # Precomputed average of all per-user ratings (from track_ratings table)
    average_rating = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    album = relationship("Album", back_populates="tracks")

    def __repr__(self):
        return f"<Track(id={self.id}, title='{self.title}', track_number={self.track_number})>"
