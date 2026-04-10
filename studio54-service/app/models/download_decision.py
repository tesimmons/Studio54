"""
Download Decision models - Lidarr-style decision engine data structures

This module contains the core data structures used by the decision engine
to evaluate and process releases from indexers.
"""
import uuid
import enum
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer, BigInteger, Float, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.artist import Artist
    from app.models.album import Album


# =============================================================================
# Enums
# =============================================================================

class RejectionType(str, enum.Enum):
    """Type of rejection for a release"""
    PERMANENT = "permanent"      # Never retry (wrong album, blacklisted, etc.)
    TEMPORARY = "temporary"      # May retry later (rate limited, temporary error)


class TrackedDownloadState(str, enum.Enum):
    """State machine for tracked downloads"""
    QUEUED = "queued"              # In download client queue
    DOWNLOADING = "downloading"    # Actively downloading
    PAUSED = "paused"              # Paused in client
    IMPORT_PENDING = "import_pending"  # Downloaded, ready to import
    IMPORT_BLOCKED = "import_blocked"  # Error detected, needs attention
    IMPORTING = "importing"        # Currently importing
    IMPORTED = "imported"          # Successfully imported
    FAILED = "failed"              # Permanently failed
    IGNORED = "ignored"            # Ignored by user


class DownloadEventType(str, enum.Enum):
    """Types of events in download history"""
    GRABBED = "grabbed"
    IMPORT_STARTED = "import_started"
    IMPORTED = "imported"
    IMPORT_FAILED = "import_failed"
    DOWNLOAD_FAILED = "download_failed"
    DELETED = "deleted"
    BLACKLISTED = "blacklisted"


# =============================================================================
# Dataclasses (non-persisted)
# =============================================================================

@dataclass
class Rejection:
    """
    Represents a rejection reason from a specification

    Attributes:
        reason: Human-readable explanation of why the release was rejected
        type: Whether this is a permanent or temporary rejection
    """
    reason: str
    type: RejectionType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "type": self.type.value
        }


@dataclass
class ReleaseInfo:
    """
    Parsed release information from an indexer search result

    Contains all relevant metadata extracted from the indexer response
    and parsed from the release title.
    """
    # Identification
    title: str
    guid: str
    indexer_id: str
    indexer_name: str

    # Download info
    download_url: str
    info_url: Optional[str] = None
    size: int = 0
    age_days: int = 0
    publish_date: Optional[datetime] = None

    # Quality info (parsed from title)
    quality: str = "Unknown"
    codec: Optional[str] = None
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None

    # Release metadata (parsed from title)
    artist_name: Optional[str] = None
    album_name: Optional[str] = None
    year: Optional[int] = None
    release_group: Optional[str] = None

    # Additional attributes
    seeders: Optional[int] = None  # For torrents
    leechers: Optional[int] = None  # For torrents
    protocol: str = "usenet"  # usenet or torrent
    categories: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "guid": self.guid,
            "indexer_id": self.indexer_id,
            "indexer_name": self.indexer_name,
            "download_url": self.download_url,
            "info_url": self.info_url,
            "size": self.size,
            "age_days": self.age_days,
            "publish_date": self.publish_date.isoformat() if self.publish_date else None,
            "quality": self.quality,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "artist_name": self.artist_name,
            "album_name": self.album_name,
            "year": self.year,
            "release_group": self.release_group,
            "protocol": self.protocol,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReleaseInfo':
        """Create ReleaseInfo from dictionary (e.g., from JSON storage)"""
        publish_date = data.get('publish_date')
        if publish_date and isinstance(publish_date, str):
            publish_date = datetime.fromisoformat(publish_date)

        return cls(
            title=data.get('title', ''),
            guid=data.get('guid', ''),
            indexer_id=data.get('indexer_id', ''),
            indexer_name=data.get('indexer_name', ''),
            download_url=data.get('download_url', ''),
            info_url=data.get('info_url'),
            size=data.get('size', 0),
            age_days=data.get('age_days', 0),
            publish_date=publish_date,
            quality=data.get('quality', 'Unknown'),
            codec=data.get('codec'),
            bitrate=data.get('bitrate'),
            sample_rate=data.get('sample_rate'),
            bit_depth=data.get('bit_depth'),
            artist_name=data.get('artist_name'),
            album_name=data.get('album_name'),
            year=data.get('year'),
            release_group=data.get('release_group'),
            protocol=data.get('protocol', 'usenet'),
            categories=data.get('categories', []),
        )


@dataclass
class RemoteAlbum:
    """
    Links a release from an indexer to a library album/artist

    This is the core data structure passed to specifications for evaluation.
    """
    artist: 'Artist'
    album: 'Album'
    release_info: ReleaseInfo

    @property
    def artist_name(self) -> str:
        return self.artist.name if self.artist else ""

    @property
    def album_title(self) -> str:
        return self.album.title if self.album else ""


@dataclass
class DownloadDecision:
    """
    Result of decision engine evaluation for a release

    Contains the remote album info and any rejections that occurred
    during specification evaluation.
    """
    remote_album: RemoteAlbum
    rejections: List[Rejection] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        """Returns True if no rejections"""
        return len(self.rejections) == 0

    @property
    def temporarily_rejected(self) -> bool:
        """Returns True if all rejections are temporary"""
        return (
            len(self.rejections) > 0 and
            all(r.type == RejectionType.TEMPORARY for r in self.rejections)
        )

    @property
    def permanently_rejected(self) -> bool:
        """Returns True if any rejection is permanent"""
        return any(r.type == RejectionType.PERMANENT for r in self.rejections)

    @property
    def rejection_reasons(self) -> List[str]:
        """Returns list of rejection reason strings"""
        return [r.reason for r in self.rejections]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.remote_album.release_info.title,
            "guid": self.remote_album.release_info.guid,
            "quality": self.remote_album.release_info.quality,
            "size": self.remote_album.release_info.size,
            "indexer": self.remote_album.release_info.indexer_name,
            "approved": self.approved,
            "temporarily_rejected": self.temporarily_rejected,
            "permanently_rejected": self.permanently_rejected,
            "rejections": [r.to_dict() for r in self.rejections],
        }


# =============================================================================
# SQLAlchemy Models (persisted)
# =============================================================================

class TrackedDownload(Base):
    """
    Tracks a download through its lifecycle from grab to import

    State machine:
        QUEUED -> DOWNLOADING -> IMPORT_PENDING -> IMPORTING -> IMPORTED
                            |
                            v
                         FAILED/IGNORED

        IMPORT_PENDING can go to IMPORT_BLOCKED if there's an issue
    """
    __tablename__ = 'tracked_downloads'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    download_client_id = Column(UUID(as_uuid=True), ForeignKey('download_clients.id', ondelete='CASCADE'), nullable=False)
    download_id = Column(String(255), nullable=False, index=True)  # ID in download client

    album_id = Column(UUID(as_uuid=True), ForeignKey('albums.id', ondelete='CASCADE'), nullable=True, index=True)
    artist_id = Column(UUID(as_uuid=True), ForeignKey('artists.id', ondelete='CASCADE'), nullable=True, index=True)
    indexer_id = Column(UUID(as_uuid=True), ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True)

    title = Column(String(500), nullable=False)
    output_path = Column(String(1000), nullable=True)
    state = Column(
        Enum(TrackedDownloadState, values_callable=lambda x: [e.value for e in x]),
        default=TrackedDownloadState.QUEUED,
        nullable=False,
        index=True
    )

    # Release info (cached)
    release_guid = Column(String(255), nullable=True)
    release_quality = Column(String(50), nullable=True)
    release_indexer = Column(String(100), nullable=True)

    # Progress tracking
    size_bytes = Column(BigInteger, nullable=True)
    downloaded_bytes = Column(BigInteger, default=0)
    progress_percent = Column(Float, default=0)
    eta_seconds = Column(Integer, nullable=True)

    # Timestamps
    grabbed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    imported_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Error handling
    error_message = Column(String(1000), nullable=True)
    status_messages = Column(JSONB, nullable=True)

    # Relationships
    album = relationship("Album", backref="tracked_downloads")
    artist = relationship("Artist", backref="tracked_downloads")
    download_client = relationship("DownloadClient", backref="tracked_downloads")
    indexer = relationship("Indexer", backref="tracked_downloads")

    def __repr__(self):
        return f"<TrackedDownload(id={self.id}, title='{self.title[:50]}...', state='{self.state}')>"


class PendingRelease(Base):
    """
    Temporarily rejected releases that may be retried later

    Used when a release fails temporarily (rate limited, transient error)
    and should be retried after a delay.
    """
    __tablename__ = 'pending_releases'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    album_id = Column(UUID(as_uuid=True), ForeignKey('albums.id', ondelete='CASCADE'), nullable=False, index=True)
    artist_id = Column(UUID(as_uuid=True), ForeignKey('artists.id', ondelete='CASCADE'), nullable=False)
    indexer_id = Column(UUID(as_uuid=True), ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True)

    release_guid = Column(String(255), nullable=False)
    release_title = Column(String(500), nullable=False)
    release_data = Column(JSONB, nullable=False)  # Full ReleaseInfo as JSON

    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    retry_after = Column(DateTime(timezone=True), nullable=True)
    rejection_reasons = Column(JSONB, nullable=True)
    retry_count = Column(Integer, default=0)

    # Relationships
    album = relationship("Album", backref="pending_releases")
    artist = relationship("Artist", backref="pending_releases")

    def get_release_info(self) -> ReleaseInfo:
        """Reconstruct ReleaseInfo from stored JSON"""
        return ReleaseInfo.from_dict(self.release_data)

    def __repr__(self):
        return f"<PendingRelease(id={self.id}, album_id={self.album_id}, title='{self.release_title[:30]}...')>"


class DownloadHistory(Base):
    """
    History of download events for auditing and tracking

    Records grabbed, imported, failed events for albums.
    """
    __tablename__ = 'download_history'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    album_id = Column(UUID(as_uuid=True), ForeignKey('albums.id', ondelete='SET NULL'), nullable=True, index=True)
    artist_id = Column(UUID(as_uuid=True), ForeignKey('artists.id', ondelete='SET NULL'), nullable=True, index=True)
    indexer_id = Column(UUID(as_uuid=True), ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True)
    download_client_id = Column(UUID(as_uuid=True), ForeignKey('download_clients.id', ondelete='SET NULL'), nullable=True)

    release_guid = Column(String(255), nullable=True)
    release_title = Column(String(500), nullable=True)

    event_type = Column(Enum(DownloadEventType, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    quality = Column(String(50), nullable=True)
    source = Column(String(100), nullable=True)

    message = Column(String(1000), nullable=True)
    data = Column(JSONB, nullable=True)

    occurred_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    album = relationship("Album", backref="download_history")
    artist = relationship("Artist", backref="download_history")

    def __repr__(self):
        return f"<DownloadHistory(id={self.id}, event='{self.event_type}', album_id={self.album_id})>"


class Blacklist(Base):
    """
    Permanently rejected releases that should never be grabbed again

    Used when a release is known bad (corrupt, wrong content, etc.)
    """
    __tablename__ = 'blacklist'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    album_id = Column(UUID(as_uuid=True), ForeignKey('albums.id', ondelete='CASCADE'), nullable=True, index=True)
    artist_id = Column(UUID(as_uuid=True), ForeignKey('artists.id', ondelete='CASCADE'), nullable=True, index=True)
    indexer_id = Column(UUID(as_uuid=True), ForeignKey('indexers.id', ondelete='SET NULL'), nullable=True)

    release_guid = Column(String(255), nullable=False, index=True)
    release_title = Column(String(500), nullable=True)

    reason = Column(String(500), nullable=True)
    source_title = Column(String(500), nullable=True)

    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    album = relationship("Album", backref="blacklisted_releases")
    artist = relationship("Artist", backref="blacklisted_releases")

    def __repr__(self):
        return f"<Blacklist(id={self.id}, guid='{self.release_guid}', reason='{self.reason}')>"
