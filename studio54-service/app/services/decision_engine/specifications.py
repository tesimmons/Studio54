"""
Decision Specifications - Modular criteria for evaluating releases

Each specification implements a single responsibility for evaluating releases.
Specifications are evaluated in priority order (lower = first).

Based on Lidarr's specification pattern from:
- src/NzbDrone.Core/DecisionEngine/Specifications/
"""
import re
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.download_decision import (
    RemoteAlbum,
    Rejection,
    RejectionType,
    TrackedDownload,
    TrackedDownloadState,
    Blacklist,
    DownloadHistory,
    DownloadEventType,
)
from app.models import Album, Artist, QualityProfile

logger = logging.getLogger(__name__)


class IDecisionSpecification(ABC):
    """
    Base interface for decision specifications

    Each specification evaluates a single aspect of a release
    and returns a Rejection if the release doesn't meet criteria.
    """

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        Evaluation priority (lower = evaluated first)

        Priority guidelines:
        - 1-10: Critical checks (blacklist, already downloading)
        - 11-30: Quality checks (profile, cutoff)
        - 31-50: Constraints (size, retention)
        - 51-70: History checks
        """
        pass

    @property
    def name(self) -> str:
        """Name of this specification for logging"""
        return self.__class__.__name__

    @abstractmethod
    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        """
        Evaluate whether this specification is satisfied

        Args:
            remote_album: The release linked to an album

        Returns:
            None if satisfied, Rejection if not satisfied
        """
        pass


# =============================================================================
# Quality Specifications
# =============================================================================

class QualityAllowedSpecification(IDecisionSpecification):
    """
    Check if the release quality is in the artist's quality profile

    Rejects if the detected quality is not in the allowed_formats list.
    """
    priority = 11

    def __init__(self, db: Session):
        self.db = db

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        quality = remote_album.release_info.quality
        artist = remote_album.artist

        # Get quality profile
        profile = artist.quality_profile if artist else None

        if not profile:
            # No profile means accept anything
            logger.debug(f"No quality profile for artist, accepting {quality}")
            return None

        allowed = profile.allowed_formats or []

        if not allowed:
            # Empty allowed list means accept anything
            return None

        # Check if quality is allowed
        if quality not in allowed and quality != "Unknown":
            return Rejection(
                reason=f"Quality '{quality}' is not in allowed formats: {allowed}",
                type=RejectionType.PERMANENT
            )

        return None


class QualityCutoffSpecification(IDecisionSpecification):
    """
    Check if we already have this album at cutoff quality or better

    Rejects if the current quality meets the cutoff and upgrade is disabled.
    """
    priority = 12

    def __init__(self, db: Session):
        self.db = db
        self._quality_order = [
            'FLAC-24', 'FLAC', 'MP3-320', 'MP3-V0', 'MP3-256',
            'MP3-192', 'MP3-128', 'AAC-256', 'AAC', 'OGG', 'OPUS', 'Unknown'
        ]

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        album = remote_album.album
        artist = remote_album.artist

        # If album doesn't have quality_meets_cutoff set, allow download
        if not hasattr(album, 'quality_meets_cutoff') or not album.quality_meets_cutoff:
            return None

        # Check if upgrade is enabled
        profile = artist.quality_profile if artist else None
        if profile and profile.upgrade_enabled:
            # Check if this release would be an upgrade
            cutoff_quality = profile.upgrade_until_quality
            release_quality = remote_album.release_info.quality

            if self._is_upgrade(release_quality, cutoff_quality):
                return None  # Allow upgrade

        return Rejection(
            reason="Album already has quality at or above cutoff",
            type=RejectionType.PERMANENT
        )

    def _is_upgrade(self, new_quality: str, cutoff: str) -> bool:
        """Check if new quality is better than cutoff"""
        if not cutoff:
            return True

        try:
            new_idx = self._quality_order.index(new_quality)
            cutoff_idx = self._quality_order.index(cutoff)
            return new_idx < cutoff_idx  # Lower index = better quality
        except ValueError:
            return False


class MinimumBitrateSpecification(IDecisionSpecification):
    """
    Check if the release meets minimum bitrate requirements
    """
    priority = 13

    def __init__(self, db: Session):
        self.db = db

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        artist = remote_album.artist
        profile = artist.quality_profile if artist else None

        if not profile or not profile.min_bitrate:
            return None

        bitrate = remote_album.release_info.bitrate
        if bitrate is None:
            # Can't determine bitrate, allow it
            return None

        if bitrate < profile.min_bitrate:
            return Rejection(
                reason=f"Bitrate {bitrate}kbps below minimum {profile.min_bitrate}kbps",
                type=RejectionType.PERMANENT
            )

        return None


# =============================================================================
# Album/Artist Specifications
# =============================================================================

class MonitoredAlbumSpecification(IDecisionSpecification):
    """
    Check if the album is monitored and wanted

    Rejects if the album is not monitored or not in wanted status.
    """
    priority = 5

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        album = remote_album.album
        artist = remote_album.artist

        # Check artist monitoring
        if artist and not artist.is_monitored:
            return Rejection(
                reason=f"Artist '{artist.name}' is not monitored",
                type=RejectionType.PERMANENT
            )

        # Check album monitoring
        if album and not album.monitored:
            return Rejection(
                reason=f"Album '{album.title}' is not monitored",
                type=RejectionType.PERMANENT
            )

        return None


# =============================================================================
# Constraint Specifications
# =============================================================================

class AcceptableSizeSpecification(IDecisionSpecification):
    """
    Check if the release size is within acceptable range

    Rejects if the release exceeds max_size_mb from quality profile.
    """
    priority = 31

    def __init__(self, db: Session):
        self.db = db

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        artist = remote_album.artist
        profile = artist.quality_profile if artist else None

        if not profile or not profile.max_size_mb:
            return None

        size_mb = remote_album.release_info.size / (1024 * 1024)
        max_size = profile.max_size_mb

        if size_mb > max_size:
            return Rejection(
                reason=f"Release size {size_mb:.0f}MB exceeds maximum {max_size}MB",
                type=RejectionType.PERMANENT
            )

        return None


class RetentionSpecification(IDecisionSpecification):
    """
    Check if the release is within usenet retention period

    Rejects if the release is older than typical retention (e.g., 1500 days).
    """
    priority = 32

    def __init__(self, retention_days: int = 1500):
        self.retention_days = retention_days

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        age_days = remote_album.release_info.age_days

        if age_days > self.retention_days:
            return Rejection(
                reason=f"Release is {age_days} days old, exceeds retention of {self.retention_days} days",
                type=RejectionType.TEMPORARY  # May become available on other indexers
            )

        return None


class ReleaseRestrictionsSpecification(IDecisionSpecification):
    """
    Check release title against must-have / must-not-have patterns

    Can be configured with patterns that must or must not appear in title.
    """
    priority = 33

    def __init__(
        self,
        must_contain: Optional[List[str]] = None,
        must_not_contain: Optional[List[str]] = None
    ):
        self.must_contain = must_contain or []
        self.must_not_contain = must_not_contain or ['BOOTLEG', 'FAKE', 'SAMPLE']

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        title = remote_album.release_info.title.upper()

        # Check must_not_contain patterns
        for pattern in self.must_not_contain:
            if re.search(pattern.upper(), title):
                return Rejection(
                    reason=f"Title contains restricted term: '{pattern}'",
                    type=RejectionType.PERMANENT
                )

        # Check must_contain patterns (all must be present)
        for pattern in self.must_contain:
            if not re.search(pattern.upper(), title):
                return Rejection(
                    reason=f"Title missing required term: '{pattern}'",
                    type=RejectionType.PERMANENT
                )

        return None


# =============================================================================
# History & Blacklist Specifications
# =============================================================================

class BlacklistSpecification(IDecisionSpecification):
    """
    Check if the release is blacklisted

    Rejects if the release GUID or similar title was previously blacklisted.
    """
    priority = 1  # Highest priority - check first

    def __init__(self, db: Session):
        self.db = db

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        release = remote_album.release_info
        album = remote_album.album
        artist = remote_album.artist

        # Check by GUID
        blacklisted = self.db.query(Blacklist).filter(
            Blacklist.release_guid == release.guid
        ).first()

        if blacklisted:
            return Rejection(
                reason=f"Release is blacklisted: {blacklisted.reason or 'Previously failed'}",
                type=RejectionType.PERMANENT
            )

        # Check by title pattern for this album
        if album:
            blacklisted = self.db.query(Blacklist).filter(
                Blacklist.album_id == album.id,
                Blacklist.source_title == release.title
            ).first()

            if blacklisted:
                return Rejection(
                    reason=f"Similar release was blacklisted: {blacklisted.reason or 'Previously failed'}",
                    type=RejectionType.PERMANENT
                )

        return None


class AlreadyImportedSpecification(IDecisionSpecification):
    """
    Check if this exact release was already imported

    Rejects if we have history of importing this GUID successfully.
    """
    priority = 2

    def __init__(self, db: Session):
        self.db = db

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        release = remote_album.release_info

        # Check download history
        imported = self.db.query(DownloadHistory).filter(
            DownloadHistory.release_guid == release.guid,
            DownloadHistory.event_type == DownloadEventType.IMPORTED
        ).first()

        if imported:
            return Rejection(
                reason="Release was already imported previously",
                type=RejectionType.PERMANENT
            )

        return None


class NotInQueueSpecification(IDecisionSpecification):
    """
    Check if the release is already in the download queue

    Rejects if we're already downloading this release.
    """
    priority = 3

    def __init__(self, db: Session):
        self.db = db

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        release = remote_album.release_info
        album = remote_album.album

        # Check if this exact GUID is being downloaded
        in_queue = self.db.query(TrackedDownload).filter(
            TrackedDownload.release_guid == release.guid,
            TrackedDownload.state.in_([
                TrackedDownloadState.QUEUED,
                TrackedDownloadState.DOWNLOADING,
                TrackedDownloadState.PAUSED,
                TrackedDownloadState.IMPORT_PENDING,
                TrackedDownloadState.IMPORTING,
            ])
        ).first()

        if in_queue:
            return Rejection(
                reason="Release is already in download queue",
                type=RejectionType.PERMANENT
            )

        # Check if album is already being downloaded (different release)
        if album:
            album_downloading = self.db.query(TrackedDownload).filter(
                TrackedDownload.album_id == album.id,
                TrackedDownload.state.in_([
                    TrackedDownloadState.QUEUED,
                    TrackedDownloadState.DOWNLOADING,
                    TrackedDownloadState.IMPORTING,
                ])
            ).first()

            if album_downloading:
                return Rejection(
                    reason="Album is already being downloaded (different release)",
                    type=RejectionType.TEMPORARY  # May want this one if current fails
                )

        return None


class RecentlyFailedSpecification(IDecisionSpecification):
    """
    Check if this release recently failed

    Rejects temporarily if the release failed within the last 6 hours.
    """
    priority = 51

    def __init__(self, db: Session, cooldown_hours: int = 6):
        self.db = db
        self.cooldown_hours = cooldown_hours

    def is_satisfied_by(self, remote_album: RemoteAlbum) -> Optional[Rejection]:
        release = remote_album.release_info
        cooldown_time = datetime.now(timezone.utc) - timedelta(hours=self.cooldown_hours)

        # Check for recent failures
        recent_failure = self.db.query(DownloadHistory).filter(
            DownloadHistory.release_guid == release.guid,
            DownloadHistory.event_type.in_([
                DownloadEventType.DOWNLOAD_FAILED,
                DownloadEventType.IMPORT_FAILED,
            ]),
            DownloadHistory.occurred_at > cooldown_time
        ).first()

        if recent_failure:
            return Rejection(
                reason=f"Release failed recently ({recent_failure.message or 'Unknown error'}), waiting for cooldown",
                type=RejectionType.TEMPORARY
            )

        return None


# =============================================================================
# Factory Function
# =============================================================================

def get_default_specifications(db: Session) -> List[IDecisionSpecification]:
    """
    Get the default set of specifications for decision making

    Args:
        db: Database session for specifications that need DB access

    Returns:
        List of specifications in priority order
    """
    return [
        # Priority 1-10: Critical checks
        BlacklistSpecification(db),
        AlreadyImportedSpecification(db),
        NotInQueueSpecification(db),

        # Priority 11-30: Quality checks
        MonitoredAlbumSpecification(),
        QualityAllowedSpecification(db),
        QualityCutoffSpecification(db),
        MinimumBitrateSpecification(db),

        # Priority 31-50: Constraints
        AcceptableSizeSpecification(db),
        RetentionSpecification(),
        ReleaseRestrictionsSpecification(),

        # Priority 51-70: History checks
        RecentlyFailedSpecification(db),
    ]
