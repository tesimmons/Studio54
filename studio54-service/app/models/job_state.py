"""
Job State model - Resilient job tracking system

Provides persistent job state for all background tasks with:
- Progress tracking
- Pause/resume support
- Checkpoint/recovery after crashes
- Heartbeat monitoring for stall detection
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class JobType(str, enum.Enum):
    """Types of background jobs"""
    ALBUM_SEARCH = "album_search"
    DOWNLOAD_MONITOR = "download_monitor"
    IMPORT_DOWNLOAD = "import_download"
    LIBRARY_SCAN = "library_scan"
    ARTIST_SYNC = "artist_sync"
    METADATA_REFRESH = "metadata_refresh"
    IMAGE_FETCH = "image_fetch"
    CLEANUP = "cleanup"


class JobStatus(str, enum.Enum):
    """Job execution status"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALLED = "stalled"
    RETRYING = "retrying"


class JobState(Base):
    """
    JobState - Universal job tracking for all background tasks

    Tracks execution state, progress, checkpoints, and errors for all
    long-running operations. Enables pause/resume, recovery after crashes,
    and real-time progress monitoring.

    Based on proven MUSE architecture for resilient job processing.
    """
    __tablename__ = "job_states"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Job identification
    job_type = Column(SQLEnum(JobType), nullable=False, index=True)
    entity_type = Column(String(50), nullable=True)  # "album", "library", "artist"
    entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Foreign key to entity

    # Celery task tracking
    celery_task_id = Column(String(255), nullable=True, index=True, unique=True)
    worker_id = Column(String(255), nullable=True, index=True)  # Which worker is processing

    # Status
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    current_step = Column(String(500), nullable=True)  # Human-readable current action

    # Progress tracking
    progress_percent = Column(Float, default=0.0)  # 0-100
    items_processed = Column(Integer, default=0)
    items_total = Column(Integer, nullable=True)

    # Performance metrics
    speed_metric = Column(Float, nullable=True)  # files/sec, mb/sec, etc.
    eta_seconds = Column(Integer, nullable=True)  # Estimated time remaining

    # Resilience features
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True, index=True)  # For stall detection
    checkpoint_data = Column(JSONB, nullable=True)  # Resume state (last_file, counters, etc.)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    # Results and errors
    result_data = Column(JSONB, nullable=True)  # Success results (JSON)
    error_message = Column(Text, nullable=True)  # Short error message
    error_traceback = Column(Text, nullable=True)  # Full traceback for debugging

    # Logging
    log_file_path = Column(Text, nullable=True)  # Path to job log file

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships to existing models
    album_id = Column(UUID(as_uuid=True), ForeignKey("albums.id", ondelete="SET NULL"), nullable=True)
    album = relationship("Album", foreign_keys=[album_id], backref="job_history")

    scan_job_id = Column(UUID(as_uuid=True), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=True)
    scan_job = relationship("ScanJob", foreign_keys=[scan_job_id], backref="job_state")

    download_queue_id = Column(UUID(as_uuid=True), ForeignKey("download_queue.id", ondelete="CASCADE"), nullable=True)
    download_queue = relationship("DownloadQueue", foreign_keys=[download_queue_id], backref="job_state")

    def __repr__(self):
        return f"<JobState(id={self.id}, type='{self.job_type}', status='{self.status}', progress={self.progress_percent}%)>"

    def is_active(self) -> bool:
        """Check if job is currently active"""
        return self.status in [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.RETRYING]

    def is_terminal(self) -> bool:
        """Check if job has reached a terminal state"""
        return self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]

    def calculate_eta(self) -> int:
        """Calculate estimated time remaining in seconds"""
        if not self.items_total or not self.items_processed or self.items_processed == 0:
            return None

        if not self.started_at:
            return None

        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        if elapsed == 0:
            return None

        speed = self.items_processed / elapsed
        if speed == 0:
            return None

        remaining = self.items_total - self.items_processed
        return int(remaining / speed)

    def update_progress(self, percent=None, items_processed=None, items_total=None, step=None):
        """Update job progress and calculate ETA"""
        if percent is not None:
            self.progress_percent = min(100.0, max(0.0, percent))

        if items_processed is not None:
            self.items_processed = items_processed

        if items_total is not None:
            self.items_total = items_total

        if step is not None:
            self.current_step = step

        # Calculate ETA
        if self.items_total and self.items_processed and self.started_at:
            self.eta_seconds = self.calculate_eta()

        # Update heartbeat
        self.last_heartbeat_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
