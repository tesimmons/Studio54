"""
File Organization Job Model
Tracks file organization, validation, and rollback operations
"""

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum

from app.database import Base


class JobType(str, enum.Enum):
    """Type of file organization job"""
    ORGANIZE_LIBRARY = "organize_library"  # Organize entire library path
    ORGANIZE_ARTIST = "organize_artist"  # Organize specific artist
    ORGANIZE_ALBUM = "organize_album"  # Organize specific album
    VALIDATE_STRUCTURE = "validate_structure"  # Validate directory structure
    FETCH_METADATA = "fetch_metadata"  # Fetch MBIDs from MusicBrainz for files without metadata
    VALIDATE_MBID = "validate_mbid"  # Verify MBID exists in file comments, update DB
    VALIDATE_MBID_METADATA = "validate_mbid_metadata"  # Validate file metadata matches MusicBrainz MBID data
    LINK_FILES = "link_files"  # Link files with MBID to album/track records
    REINDEX_ALBUMS = "reindex_albums"  # Reindex albums/singles from file metadata
    VERIFY_AUDIO = "verify_audio"  # Verify audio match of downloaded files
    ROLLBACK = "rollback"  # Rollback previous operation
    LIBRARY_MIGRATION = "library_migration"  # Migrate files to new library with MBID validation
    MIGRATION_FINGERPRINT = "migration_fingerprint"  # Ponder fingerprint job for migration failures
    ASSOCIATE_AND_ORGANIZE = "associate_and_organize"  # Walk filesystem, match to DB tracks, move/rename/link
    VALIDATE_FILE_LINKS = "validate_file_links"  # Verify linked track files still exist on disk
    RESOLVE_UNLINKED = "resolve_unlinked"  # Bulk resolution of unlinked files via auto-import + fuzzy matching


class JobStatus(str, enum.Enum):
    """Job execution status"""
    PENDING = "pending"  # Queued, not started
    RUNNING = "running"  # Currently executing
    PAUSED = "paused"  # Waiting for user action
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Error occurred
    CANCELLED = "cancelled"  # User cancelled the job
    ROLLED_BACK = "rolled_back"  # Operation was reversed


class FileOrganizationJob(Base):
    """
    File Organization Job Model

    Tracks background tasks for organizing files, validating structures,
    and rolling back operations. Used for progress tracking and job history.
    """
    __tablename__ = "file_organization_jobs"
    __table_args__ = (
        # Composite index for queries filtering by status AND job_type
        Index('idx_file_org_jobs_status_type', 'status', 'job_type'),
        # Composite index for library-specific job queries
        Index('idx_file_org_jobs_library_status', 'library_path_id', 'status'),
        # Note: idx_file_org_jobs_heartbeat is a partial index created in migration 021
    )

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Job Information
    job_type = Column(Enum(JobType), nullable=False, index=True)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, index=True)
    celery_task_id = Column(String(255), nullable=True, index=True)  # Celery task ID

    # References (nullable for different job types)
    library_path_id = Column(
        UUID(as_uuid=True),
        ForeignKey("library_paths.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    artist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    album_id = Column(
        UUID(as_uuid=True),
        ForeignKey("albums.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # Progress Tracking
    progress_percent = Column(Float, default=0.0)  # 0.0-100.0
    current_action = Column(Text, nullable=True)  # Current operation description

    # File Statistics
    files_total = Column(Integer, default=0)
    files_processed = Column(Integer, default=0)
    files_renamed = Column(Integer, default=0)
    files_moved = Column(Integer, default=0)
    files_failed = Column(Integer, default=0)

    # Timestamps
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)  # For stall detection

    # Current Processing State (for debugging and resumability)
    current_file_path = Column(Text, nullable=True)  # Currently processing file
    current_file_index = Column(Integer, default=0)  # Index in file list
    last_processed_file_id = Column(UUID(as_uuid=True), nullable=True)  # Last successfully processed file

    # Error Handling
    error_message = Column(Text, nullable=True)
    last_error_file = Column(Text, nullable=True)  # File that caused the last error
    last_error_details = Column(Text, nullable=True)  # Full error details/traceback

    # Logging
    log_file_path = Column(Text, nullable=True)  # Path to detailed operation log file
    summary_report_path = Column(Text, nullable=True)  # Path to summary report file

    # Files Without MBID Tracking (for validation jobs)
    files_without_mbid = Column(Integer, default=0)  # Count of files missing MBID
    files_without_mbid_json = Column(Text, nullable=True)  # JSON list of file paths without MBID

    # Parent job reference (for fetch_metadata jobs created by validation)
    parent_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("file_organization_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Library Migration Fields
    source_library_path_id = Column(
        UUID(as_uuid=True),
        ForeignKey("library_paths.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    destination_library_path_id = Column(
        UUID(as_uuid=True),
        ForeignKey("library_paths.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    files_with_mbid = Column(Integer, default=0)  # Files that already had MBID
    files_mbid_fetched = Column(Integer, default=0)  # Files where MBID was looked up
    files_metadata_corrected = Column(Integer, default=0)  # Files with metadata corrected
    files_validated = Column(Integer, default=0)  # Files successfully validated
    followup_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("file_organization_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )  # Reference to Ponder fingerprint follow-up job

    def __repr__(self):
        return f"<FileOrganizationJob(id={self.id}, type={self.job_type}, status={self.status})>"
