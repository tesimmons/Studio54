"""
Album model - Release tracking
"""
import uuid
import enum
from datetime import datetime, timezone, date
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer, Date, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class AlbumStatus(str, enum.Enum):
    """Album download status"""
    WANTED = "wanted"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


class Album(Base):
    """
    Album model - Represents a music album/release

    Links to MusicBrainz release groups and specific releases
    """
    __tablename__ = "albums"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    artist_id = Column(UUID(as_uuid=True), ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)

    # Basic info
    title = Column(Text, nullable=False, index=True)
    musicbrainz_id = Column(String(36), unique=True, nullable=False, index=True)  # Release group MBID
    release_mbid = Column(String(36), nullable=True, index=True)  # Specific release MBID

    # Release metadata
    release_date = Column(Date, nullable=True)
    album_type = Column(String(50), nullable=True)  # Album, EP, Single, etc.
    secondary_types = Column(Text, nullable=True)  # Comma-separated: "Compilation,Live"
    track_count = Column(Integer, default=0)

    # Status tracking
    status = Column(Enum(AlbumStatus), default=AlbumStatus.WANTED, nullable=False, index=True)
    monitored = Column(Boolean, default=False, nullable=False)

    # Media
    cover_art_url = Column(Text, nullable=True)

    # Custom folder path (overrides default Artist/Album structure)
    custom_folder_path = Column(Text, nullable=True)  # Custom directory path for this album's files

    # Search and quality tracking
    last_search_time = Column(DateTime(timezone=True), nullable=True)
    quality_meets_cutoff = Column(Boolean, default=True, nullable=False)

    # MUSE integration
    muse_library_id = Column(UUID(as_uuid=True), nullable=True)  # External reference to MUSE library
    muse_verified = Column(Boolean, default=False)  # Has this been verified in MUSE?

    # Timestamps
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    searched_at = Column(DateTime(timezone=True), nullable=True)
    downloaded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    artist = relationship("Artist", back_populates="albums")
    tracks = relationship("Track", back_populates="album", cascade="all, delete-orphan")
    downloads = relationship("DownloadQueue", back_populates="album", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Album(id={self.id}, title='{self.title}', artist='{self.artist.name if self.artist else 'Unknown'}', status='{self.status}')>"
