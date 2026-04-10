"""
Library Import Models
Models for tracking library import jobs and artist matching
"""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Numeric, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.database import Base


class LibraryImportJob(Base):
    """
    Tracks library import job progress and statistics

    Coordinates multi-phase import:
    1. File scanning
    2. Artist matching/import
    3. Metadata syncing
    4. Folder matching
    5. Track matching
    6. Finalization
    """
    __tablename__ = "library_import_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    library_path_id = Column(UUID(as_uuid=True), ForeignKey("library_paths.id", ondelete="CASCADE"), nullable=False)

    # Status tracking
    status = Column(String(20), nullable=False, default="pending")  # pending, running, paused, completed, failed, cancelled
    current_phase = Column(String(50))  # scanning, artist_matching, metadata_sync, folder_matching, track_matching, enrichment, finalization
    progress_percent = Column(Numeric(5, 2), default=0.0)
    current_action = Column(String(500))  # Current action description

    # Phase completion tracking
    phase_scanning = Column(String(20), default="pending")  # pending, running, completed, failed
    phase_artist_matching = Column(String(20), default="pending")
    phase_metadata_sync = Column(String(20), default="pending")
    phase_folder_matching = Column(String(20), default="pending")
    phase_track_matching = Column(String(20), default="pending")
    phase_enrichment = Column(String(20), default="pending")
    phase_finalization = Column(String(20), default="pending")

    # Statistics
    artists_found = Column(Integer, default=0)
    artists_matched = Column(Integer, default=0)
    artists_created = Column(Integer, default=0)
    artists_pending = Column(Integer, default=0)
    albums_synced = Column(Integer, default=0)
    albums_pending = Column(Integer, default=0)
    tracks_matched = Column(Integer, default=0)
    tracks_unmatched = Column(Integer, default=0)
    files_scanned = Column(Integer, default=0)

    # Configuration
    auto_match_artists = Column(Boolean, default=True)
    auto_assign_folders = Column(Boolean, default=True)
    auto_match_tracks = Column(Boolean, default=True)
    confidence_threshold = Column(Integer, default=70)  # 0-100

    # Results and errors
    error_message = Column(Text)
    warnings = Column(JSON)  # List of warning messages

    # Logging
    log_file_path = Column(Text, nullable=True)  # Path to job log file

    # Timing
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    estimated_completion = Column(DateTime(timezone=True))

    # Celery task tracking
    celery_task_id = Column(String(255))

    # Pause/cancel support
    pause_requested = Column(Boolean, default=False)
    cancel_requested = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    library_path = relationship("LibraryPath", back_populates="import_jobs")
    artist_matches = relationship("LibraryArtistMatch", back_populates="import_job", cascade="all, delete-orphan")


class LibraryArtistMatch(Base):
    """
    Tracks artist matching from library files to Studio54 artists

    Used to:
    - Store MusicBrainz search results for manual review
    - Track which library files belong to which artist
    - Handle unmatched artists requiring manual intervention
    """
    __tablename__ = "library_artist_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_job_id = Column(UUID(as_uuid=True), ForeignKey("library_import_jobs.id", ondelete="CASCADE"), nullable=False)

    # Library artist info (from file tags)
    library_artist_name = Column(String(500), nullable=False)
    file_count = Column(Integer, default=0)
    sample_albums = Column(JSON)  # List of album names for this artist
    sample_file_paths = Column(JSON)  # List of sample file paths

    # MusicBrainz matching
    musicbrainz_id = Column(String(36))  # NULL if unmatched
    confidence_score = Column(Numeric(5, 2))  # 0-100
    status = Column(String(20), default="pending")  # pending, matched, rejected, manual_review, failed

    # MusicBrainz suggestions for manual review
    musicbrainz_suggestions = Column(JSON)  # List of potential matches with scores

    # Matched Studio54 artist
    matched_artist_id = Column(UUID(as_uuid=True), ForeignKey("artists.id", ondelete="SET NULL"))

    # Rejection/skip reason
    rejection_reason = Column(Text)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    import_job = relationship("LibraryImportJob", back_populates="artist_matches")
    matched_artist = relationship("Artist")
