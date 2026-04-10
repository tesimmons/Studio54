"""
Artist model - Monitored artists
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class MonitorType(str, enum.Enum):
    """Album monitoring strategy"""
    ALL_ALBUMS = "all_albums"
    FUTURE_ONLY = "future_only"
    EXISTING_ONLY = "existing_only"
    FIRST_ALBUM = "first_album"
    LATEST_ALBUM = "latest_album"
    NONE = "none"


class Artist(Base):
    """
    Artist model - Represents a monitored music artist

    Links to MusicBrainz via musicbrainz_id for metadata synchronization
    """
    __tablename__ = "artists"

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
    root_folder_path = Column(Text, nullable=True)  # e.g., /music/Artist Name/

    # Metadata
    overview = Column(Text, nullable=True)  # Artist biography
    genre = Column(String(255), nullable=True)
    country = Column(String(100), nullable=True)
    image_url = Column(Text, nullable=True)  # Artist image from MusicBrainz

    # Import source tracking
    import_source = Column(String(100), nullable=True)  # 'muse', 'studio54', 'manual'
    muse_library_id = Column(UUID(as_uuid=True), nullable=True)  # External reference to MUSE library
    studio54_library_path_id = Column(UUID(as_uuid=True), ForeignKey("library_paths.id"), nullable=True)

    # Rating (1-5 stars manual override, null = use computed average)
    rating_override = Column(Integer, nullable=True)

    # Statistics
    album_count = Column(Integer, default=0)  # Only albums, not singles
    single_count = Column(Integer, default=0)  # Number of singles
    track_count = Column(Integer, default=0)  # Total tracks (albums + singles)

    # Timestamps
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    quality_profile = relationship("QualityProfile", back_populates="artists")
    albums = relationship("Album", back_populates="artist", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Artist(id={self.id}, name='{self.name}', musicbrainz_id='{self.musicbrainz_id}')>"
