"""
Library scanning models - File system indexing
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer, BigInteger, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class LibraryType(str, enum.Enum):
    """Library content type"""
    MUSIC = "music"
    AUDIOBOOK = "audiobook"


class LibraryPath(Base):
    """
    LibraryPath - Root directories to scan for music files

    Tracks scan paths and their status
    """
    __tablename__ = "library_paths"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Path info
    path = Column(Text, nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Library type
    library_type = Column(String(20), default="music", nullable=False, index=True)

    # Root folder support (Lidarr-style)
    is_root_folder = Column(Boolean, default=False, nullable=False)
    free_space_bytes = Column(BigInteger, nullable=True)

    # Scan statistics
    total_files = Column(Integer, default=0)
    total_size_bytes = Column(BigInteger, default=0)
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    last_scan_duration_seconds = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    files = relationship("LibraryFile", back_populates="library_path", cascade="all, delete-orphan")
    import_jobs = relationship("LibraryImportJob", back_populates="library_path", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<LibraryPath(id={self.id}, path='{self.path}', files={self.total_files})>"


class LibraryFile(Base):
    """
    LibraryFile - Indexed audio files with metadata

    Stores file information and extracted metadata for fast searching
    """
    __tablename__ = "library_files"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    library_path_id = Column(UUID(as_uuid=True), ForeignKey("library_paths.id", ondelete="CASCADE"), nullable=False, index=True)

    # Library type
    library_type = Column(String(20), default="music", nullable=False, index=True)

    # File information
    file_path = Column(Text, nullable=False, unique=True, index=True)  # Full path
    file_name = Column(Text, nullable=False, index=True)
    file_size_bytes = Column(BigInteger, nullable=False)
    file_modified_at = Column(DateTime(timezone=True), nullable=False)

    # Audio format
    format = Column(String(20), nullable=True, index=True)  # MP3, FLAC, WAV, etc.
    bitrate_kbps = Column(Integer, nullable=True)
    sample_rate_hz = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Metadata (searchable)
    title = Column(Text, nullable=True, index=True)
    artist = Column(Text, nullable=True, index=True)
    album = Column(Text, nullable=True, index=True)
    album_artist = Column(Text, nullable=True, index=True)
    track_number = Column(Integer, nullable=True)
    disc_number = Column(Integer, nullable=True)
    year = Column(Integer, nullable=True, index=True)
    genre = Column(Text, nullable=True, index=True)

    # MusicBrainz IDs (priority matching)
    musicbrainz_trackid = Column(String(36), nullable=True, index=True)
    musicbrainz_albumid = Column(String(36), nullable=True, index=True)
    musicbrainz_artistid = Column(String(36), nullable=True, index=True)
    musicbrainz_releasegroupid = Column(String(36), nullable=True, index=True)

    # Full metadata (JSON)
    metadata_json = Column(JSONB, nullable=True)  # Store all tags for reference

    # Artwork status
    has_embedded_artwork = Column(Boolean, default=False)
    album_art_fetched = Column(Boolean, default=False)
    album_art_url = Column(Text, nullable=True)
    artist_image_fetched = Column(Boolean, default=False)
    artist_image_url = Column(Text, nullable=True)

    # MBID tracking (whether MBID is stored in file comments)
    mbid_in_file = Column(Boolean, default=False, comment='True if Recording MBID is written to file Comment tag')
    is_organized = Column(Boolean, default=False, comment='True if file has been organized to correct location')
    mbid_verified_at = Column(DateTime(timezone=True), nullable=True, comment='Last time MBID was verified in file comment')
    organization_status = Column(String(50), default='unprocessed', comment='Status: unprocessed, validated, needs_rename, needs_move, organized')
    target_path = Column(Text, nullable=True, comment='Calculated ideal path based on MBID metadata')
    last_organization_check = Column(DateTime(timezone=True), nullable=True, comment='Last time organization was checked')

    # Timestamps
    indexed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    library_path = relationship("LibraryPath", back_populates="files")

    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_library_artist_album', 'artist', 'album'),
        Index('idx_library_musicbrainz_album', 'musicbrainz_albumid'),
        Index('idx_library_musicbrainz_artist', 'musicbrainz_artistid'),
        Index('idx_library_files_mbid_in_file', 'mbid_in_file'),
        Index('idx_library_files_is_organized', 'is_organized'),
        Index('idx_library_files_org_status', 'organization_status'),
        # Composite index for library-specific queries by organization status
        Index('idx_library_files_path_org_status', 'library_path_id', 'organization_status'),
    )

    def __repr__(self):
        return f"<LibraryFile(id={self.id}, artist='{self.artist}', album='{self.album}', title='{self.title}')>"


class ScanJob(Base):
    """
    ScanJob - Track library scan operations

    Monitors scan progress and status
    """
    __tablename__ = "scan_jobs"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    library_path_id = Column(UUID(as_uuid=True), ForeignKey("library_paths.id", ondelete="CASCADE"), nullable=False, index=True)

    # Job info
    celery_task_id = Column(String(255), nullable=True, unique=True, index=True)
    status = Column(String(50), nullable=False, default="pending", index=True)  # pending, running, completed, failed

    # Progress tracking
    files_scanned = Column(Integer, default=0)
    files_added = Column(Integer, default=0)
    files_updated = Column(Integer, default=0)
    files_skipped = Column(Integer, default=0)
    files_failed = Column(Integer, default=0)
    files_removed = Column(Integer, default=0)  # Files removed (no longer on disk)

    # V2 Scanner: Pause/Resume control
    pause_requested = Column(Boolean, default=False, nullable=False)

    # V2 Scanner: Checkpoint/Resume data
    checkpoint_data = Column(JSONB, nullable=True)  # Stores: phase, last_batch, files_processed, start_time

    # V2 Scanner: Skip statistics
    skip_statistics = Column(JSONB, nullable=True)  # Stores: {resource_fork: N, hidden: N, system: N, etc.}

    # V2 Scanner: Time estimates
    elapsed_seconds = Column(Integer, default=0)
    estimated_remaining_seconds = Column(Integer, default=0)

    # V2 Scanner: Current action for progress display
    current_action = Column(Text, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Logging
    log_file_path = Column(Text, nullable=True)  # Path to job log file

    # Timestamps
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ScanJob(id={self.id}, status='{self.status}', files_scanned={self.files_scanned})>"
