"""
Download Queue model - Active download tracking
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer, BigInteger, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class DownloadStatus(str, enum.Enum):
    """Download status enum"""
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    POST_PROCESSING = "post_processing"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadQueue(Base):
    """
    Download Queue model - Tracks active and completed downloads

    Links albums to SABnzbd downloads for monitoring and import
    """
    __tablename__ = "download_queue"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys (music)
    album_id = Column(UUID(as_uuid=True), ForeignKey("albums.id", ondelete="CASCADE"), nullable=True, index=True)
    artist_id = Column(UUID(as_uuid=True), ForeignKey("artists.id", ondelete="CASCADE"), nullable=True, index=True)

    # Foreign keys (audiobook)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=True, index=True)
    author_id = Column(UUID(as_uuid=True), ForeignKey("authors.id", ondelete="CASCADE"), nullable=True, index=True)

    # Library type
    library_type = Column(String(20), default="music", nullable=False)

    indexer_id = Column(UUID(as_uuid=True), ForeignKey("indexers.id", ondelete="SET NULL"), nullable=True)
    download_client_id = Column(UUID(as_uuid=True), ForeignKey("download_clients.id", ondelete="SET NULL"), nullable=True)

    # NZB information
    nzb_title = Column(Text, nullable=False)
    nzb_guid = Column(Text, unique=True, index=True)
    nzb_url = Column(Text, nullable=True)

    # SABnzbd tracking
    sabnzbd_id = Column(String(255), nullable=True, index=True)  # NZO ID from SABnzbd

    # Status tracking
    status = Column(Enum(DownloadStatus), default=DownloadStatus.QUEUED, nullable=False, index=True)
    progress_percent = Column(Integer, default=0)

    # File information
    size_bytes = Column(BigInteger, nullable=True)
    download_path = Column(Text, nullable=True)

    # Error handling
    error_message = Column(Text, nullable=True)
    sab_fail_message = Column(Text, nullable=True)  # Raw SABnzbd fail_message
    retry_count = Column(Integer, default=0)

    # NZB attempt tracking - stores GUIDs of all NZBs tried for this album's download
    # Used to avoid re-trying the same NZBs when searching for alternates
    attempted_nzb_guids = Column(JSONB, default=list, server_default='[]', nullable=False)

    # Timestamps
    queued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    album = relationship("Album", back_populates="downloads")
    artist = relationship("Artist", backref="download_queue_entries")
    book = relationship("Book", back_populates="downloads", foreign_keys=[book_id])
    author = relationship("Author", backref="download_queue_entries", foreign_keys=[author_id])

    def __repr__(self):
        return f"<DownloadQueue(id={self.id}, album='{self.album.title if self.album else 'Unknown'}', status='{self.status}')>"
