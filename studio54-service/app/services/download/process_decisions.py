"""
Process Download Decisions - Submit approved downloads to clients

Processes approved download decisions by submitting them to download
clients and creating tracking records.

Based on Lidarr's download handling from:
- src/NzbDrone.Core/Download/ProcessDownloadDecisions.cs
"""
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session

from app.models import Album, Artist, DownloadClient
from app.models.download_decision import (
    DownloadDecision,
    TrackedDownload,
    TrackedDownloadState,
    PendingRelease,
    DownloadHistory,
    DownloadEventType,
    ReleaseInfo,
)
from app.services.download.download_client_provider import DownloadClientProvider
from app.services.encryption import get_encryption_service

logger = logging.getLogger(__name__)


@dataclass
class DownloadSubmissionResult:
    """Result of processing download decisions"""
    grabbed: int = 0
    pending: int = 0
    rejected: int = 0
    errors: List[str] = field(default_factory=list)
    grabbed_items: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grabbed": self.grabbed,
            "pending": self.pending,
            "rejected": self.rejected,
            "errors": self.errors,
            "grabbed_items": self.grabbed_items,
        }


class ProcessDownloadDecisions:
    """
    Processes approved download decisions

    Handles:
    - Prioritizing decisions by quality
    - Submitting downloads to appropriate client
    - Creating tracked download records
    - Handling temporary rejections (pending releases)
    - Recording download history
    """

    # Quality ranking for prioritization
    QUALITY_ORDER = [
        'FLAC-24', 'FLAC', 'MP3-320', 'MP3-V0', 'MP3-256',
        'MP3-192', 'MP3-128', 'AAC-256', 'AAC', 'OGG', 'OPUS', 'Unknown'
    ]

    def __init__(self, db: Session):
        """
        Initialize the processor

        Args:
            db: Database session
        """
        self.db = db
        self._client_provider = None

    @property
    def client_provider(self) -> DownloadClientProvider:
        """Lazy initialization of client provider"""
        if self._client_provider is None:
            self._client_provider = DownloadClientProvider(self.db)
        return self._client_provider

    def process(
        self,
        decisions: List[DownloadDecision],
        auto_grab: bool = True
    ) -> DownloadSubmissionResult:
        """
        Process download decisions

        Args:
            decisions: List of DownloadDecision from search
            auto_grab: If True, automatically grab approved decisions

        Returns:
            DownloadSubmissionResult with counts and details
        """
        result = DownloadSubmissionResult()

        # Sort by quality (best first)
        prioritized = self._prioritize(decisions)

        for decision in prioritized:
            if decision.permanently_rejected:
                result.rejected += 1
                logger.debug(
                    f"Rejected: {decision.remote_album.release_info.title} - "
                    f"{decision.rejection_reasons}"
                )
                continue

            if decision.temporarily_rejected:
                # Add to pending releases for later retry
                self._add_to_pending(decision)
                result.pending += 1
                logger.debug(
                    f"Pending: {decision.remote_album.release_info.title} - "
                    f"{decision.rejection_reasons}"
                )
                continue

            if not auto_grab:
                # Just count as approved but don't grab
                continue

            # Approved - try to download
            try:
                tracked = self._grab(decision)
                result.grabbed += 1
                result.grabbed_items.append({
                    "title": decision.remote_album.release_info.title,
                    "quality": decision.remote_album.release_info.quality,
                    "size": decision.remote_album.release_info.size,
                    "tracked_download_id": str(tracked.id),
                })
                logger.info(
                    f"Grabbed: {decision.remote_album.release_info.title} "
                    f"({decision.remote_album.release_info.quality})"
                )

            except Exception as e:
                error_msg = f"Failed to grab {decision.remote_album.release_info.title}: {e}"
                result.errors.append(error_msg)
                logger.error(error_msg)

                # Convert to pending for retry
                self._add_to_pending(decision)
                result.pending += 1

        return result

    def process_single(
        self,
        release_info: ReleaseInfo,
        album: Album,
        artist: Optional[Artist] = None
    ) -> Tuple[bool, Optional[TrackedDownload], Optional[str]]:
        """
        Process a single release directly (manual grab)

        Args:
            release_info: The release to grab
            album: Target album
            artist: Target artist (optional, will be fetched from album)

        Returns:
            (success, tracked_download, error_message) tuple
        """
        if artist is None:
            artist = album.artist

        try:
            # Get download client
            client = self.client_provider.get_client(protocol='usenet')
            if not client:
                return False, None, "No available download client"

            # Get client model for tracking
            client_model = self._get_default_client_model()
            if not client_model:
                return False, None, "No download client configured"

            # Submit to client
            nzo_id = client.add_nzb_url(
                nzb_url=release_info.download_url,
                category=client_model.category or "music",
                nzb_name=release_info.title
            )

            if not nzo_id:
                return False, None, "Failed to submit to download client"

            # Create tracked download
            tracked = TrackedDownload(
                id=uuid.uuid4(),
                download_client_id=client_model.id,
                download_id=nzo_id,
                album_id=album.id,
                artist_id=artist.id if artist else None,
                indexer_id=uuid.UUID(release_info.indexer_id) if release_info.indexer_id else None,
                title=release_info.title,
                size_bytes=release_info.size,
                state=TrackedDownloadState.QUEUED,
                release_guid=release_info.guid,
                release_quality=release_info.quality,
                release_indexer=release_info.indexer_name,
                grabbed_at=datetime.now(timezone.utc)
            )
            self.db.add(tracked)
            self.db.flush()  # Ensure tracked download exists before creating history entry

            # Record in history
            self._record_grabbed(release_info, album, artist, tracked, client_model)

            # Update client stats
            self.client_provider.update_client_stats(str(client_model.id), success=True)

            self.db.commit()

            return True, tracked, None

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to process single release: {e}")
            return False, None, str(e)

    def _grab(self, decision: DownloadDecision) -> TrackedDownload:
        """
        Submit download to client and create tracking record

        Args:
            decision: Approved DownloadDecision

        Returns:
            TrackedDownload instance

        Raises:
            Exception if download submission fails
        """
        release = decision.remote_album.release_info
        album = decision.remote_album.album
        artist = decision.remote_album.artist

        # Get download client
        client = self.client_provider.get_client(protocol='usenet')
        if not client:
            raise Exception("No available download client")

        # Get client model for tracking
        client_model = self._get_default_client_model()
        if not client_model:
            raise Exception("No download client configured")

        # Submit to client
        nzo_id = client.add_nzb_url(
            nzb_url=release.download_url,
            category=client_model.category or "music",
            nzb_name=release.title
        )

        if not nzo_id:
            raise Exception("Failed to submit to download client")

        # Create tracked download
        tracked = TrackedDownload(
            id=uuid.uuid4(),
            download_client_id=client_model.id,
            download_id=nzo_id,
            album_id=album.id if album else None,
            artist_id=artist.id if artist else None,
            indexer_id=uuid.UUID(release.indexer_id) if release.indexer_id else None,
            title=release.title,
            size_bytes=release.size,
            state=TrackedDownloadState.QUEUED,
            release_guid=release.guid,
            release_quality=release.quality,
            release_indexer=release.indexer_name,
            grabbed_at=datetime.now(timezone.utc)
        )
        self.db.add(tracked)
        self.db.flush()  # Ensure tracked download exists before creating history entry

        # Record in history
        self._record_grabbed(release, album, artist, tracked, client_model)

        # Update client stats
        self.client_provider.update_client_stats(str(client_model.id), success=True)

        self.db.commit()

        return tracked

    def _add_to_pending(self, decision: DownloadDecision):
        """
        Add a temporarily rejected release to pending queue

        Args:
            decision: DownloadDecision with temporary rejections
        """
        release = decision.remote_album.release_info
        album = decision.remote_album.album
        artist = decision.remote_album.artist

        # Check if already pending
        existing = self.db.query(PendingRelease).filter(
            PendingRelease.album_id == album.id,
            PendingRelease.release_guid == release.guid
        ).first()

        if existing:
            # Update retry count
            existing.retry_count = (existing.retry_count or 0) + 1
            existing.rejection_reasons = [r.to_dict() for r in decision.rejections]
        else:
            # Create new pending release
            pending = PendingRelease(
                id=uuid.uuid4(),
                album_id=album.id,
                artist_id=artist.id if artist else album.artist_id,
                indexer_id=uuid.UUID(release.indexer_id) if release.indexer_id else None,
                release_guid=release.guid,
                release_title=release.title,
                release_data=release.to_dict(),
                rejection_reasons=[r.to_dict() for r in decision.rejections]
            )
            self.db.add(pending)

        self.db.commit()

    def _record_grabbed(
        self,
        release: ReleaseInfo,
        album: Album,
        artist: Artist,
        tracked: TrackedDownload,
        client: DownloadClient
    ):
        """
        Record grabbed event in download history

        Args:
            release: The grabbed release
            album: Target album
            artist: Target artist
            tracked: TrackedDownload record
            client: DownloadClient used
        """
        history = DownloadHistory(
            id=uuid.uuid4(),
            album_id=album.id if album else None,
            artist_id=artist.id if artist else None,
            indexer_id=uuid.UUID(release.indexer_id) if release.indexer_id else None,
            download_client_id=client.id,
            release_guid=release.guid,
            release_title=release.title,
            event_type=DownloadEventType.GRABBED,
            quality=release.quality,
            source=release.indexer_name,
            message=f"Grabbed from {release.indexer_name}",
            data={
                "size": release.size,
                "download_url": release.download_url,
            }
        )
        self.db.add(history)

    def _get_default_client_model(self) -> Optional[DownloadClient]:
        """Get the default download client model"""
        return self.db.query(DownloadClient).filter(
            DownloadClient.is_enabled == True
        ).order_by(
            DownloadClient.is_default.desc()
        ).first()

    def _prioritize(
        self,
        decisions: List[DownloadDecision]
    ) -> List[DownloadDecision]:
        """
        Sort decisions by quality preference

        Best quality first, with tie-breaker on size.

        Args:
            decisions: List of decisions to sort

        Returns:
            Sorted list (best first)
        """
        def sort_key(d: DownloadDecision):
            quality = d.remote_album.release_info.quality
            size = d.remote_album.release_info.size

            # Quality rank (lower = better)
            try:
                quality_rank = self.QUALITY_ORDER.index(quality)
            except ValueError:
                quality_rank = len(self.QUALITY_ORDER)

            # Approved status (approved first)
            approved_rank = 0 if d.approved else (1 if d.temporarily_rejected else 2)

            # Size (larger = better for quality)
            size_rank = -size

            return (approved_rank, quality_rank, size_rank)

        return sorted(decisions, key=sort_key)


class GrabService:
    """
    High-level service for grabbing releases
    """

    def __init__(self, db: Session):
        self.db = db
        self._processor = None

    @property
    def processor(self) -> ProcessDownloadDecisions:
        """Lazy initialization of processor"""
        if self._processor is None:
            self._processor = ProcessDownloadDecisions(self.db)
        return self._processor

    def grab_release(
        self,
        release_guid: str,
        album_id: str,
        release_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Grab a specific release by GUID

        Args:
            release_guid: GUID of the release to grab
            album_id: UUID of the target album
            release_data: Optional pre-parsed release data

        Returns:
            (success, tracked_download_id, error_message) tuple
        """
        album = self.db.query(Album).filter(Album.id == album_id).first()
        if not album:
            return False, None, f"Album {album_id} not found"

        # Check pending releases first
        pending = self.db.query(PendingRelease).filter(
            PendingRelease.album_id == album_id,
            PendingRelease.release_guid == release_guid
        ).first()

        if pending:
            # Use pending release data
            release_info = pending.get_release_info()
        elif release_data:
            # Use provided data
            release_info = ReleaseInfo.from_dict(release_data)
        else:
            return False, None, "Release data not found"

        # Process the single release
        success, tracked, error = self.processor.process_single(
            release_info=release_info,
            album=album,
            artist=album.artist
        )

        if success and tracked:
            # Remove from pending if it was there
            if pending:
                self.db.delete(pending)
                self.db.commit()

            return True, str(tracked.id), None

        return False, None, error or "Unknown error"
