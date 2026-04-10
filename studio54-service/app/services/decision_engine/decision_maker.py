"""
Download Decision Maker - Orchestrates release evaluation

The DownloadDecisionMaker evaluates releases from indexers against
all configured specifications and returns approved/rejected decisions.

Based on Lidarr's DownloadDecisionMaker from:
- src/NzbDrone.Core/DecisionEngine/DownloadDecisionMaker.cs
"""
import logging
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from app.models import Album, Artist
from app.models.download_decision import (
    ReleaseInfo,
    RemoteAlbum,
    DownloadDecision,
    Rejection,
    RejectionType,
)
from app.services.decision_engine.specifications import IDecisionSpecification

logger = logging.getLogger(__name__)


class DownloadDecisionMaker:
    """
    Evaluates releases against all specifications to make download decisions

    Usage:
        specs = get_default_specifications(db)
        decision_maker = DownloadDecisionMaker(specs)
        decisions = decision_maker.get_decisions(releases, album)

        approved = [d for d in decisions if d.approved]
        best = decision_maker.prioritize_decisions(approved)[0]
    """

    # Quality ranking for prioritization (lower index = better)
    QUALITY_ORDER = [
        'FLAC-24', 'FLAC', 'MP3-320', 'MP3-V0', 'MP3-256',
        'MP3-192', 'MP3-128', 'AAC-256', 'AAC', 'OGG', 'OPUS', 'Unknown'
    ]

    def __init__(self, specifications: List[IDecisionSpecification]):
        """
        Initialize with list of specifications

        Args:
            specifications: List of IDecisionSpecification implementations
        """
        # Sort specifications by priority (lower = evaluated first)
        self.specifications = sorted(specifications, key=lambda s: s.priority)
        logger.info(f"Decision maker initialized with {len(self.specifications)} specifications")

    def get_decisions(
        self,
        releases: List[ReleaseInfo],
        album: Album
    ) -> List[DownloadDecision]:
        """
        Evaluate all releases for an album

        Args:
            releases: List of ReleaseInfo from indexer search
            album: The album we're searching for

        Returns:
            List of DownloadDecision for each release
        """
        decisions = []
        artist = album.artist if album else None

        logger.info(f"Evaluating {len(releases)} releases for album '{album.title if album else 'Unknown'}'")

        for release in releases:
            decision = self._evaluate_release(release, album, artist)
            decisions.append(decision)

            if decision.approved:
                logger.debug(f"Release APPROVED: {release.title}")
            else:
                reasons = ", ".join(decision.rejection_reasons)
                logger.debug(f"Release REJECTED: {release.title} - {reasons}")

        # Log summary
        approved_count = sum(1 for d in decisions if d.approved)
        temp_rejected = sum(1 for d in decisions if d.temporarily_rejected)
        perm_rejected = sum(1 for d in decisions if d.permanently_rejected)

        logger.info(
            f"Decision results: {approved_count} approved, "
            f"{temp_rejected} temporarily rejected, {perm_rejected} permanently rejected"
        )

        return decisions

    def get_decisions_for_artist(
        self,
        releases: List[ReleaseInfo],
        albums: List[Album]
    ) -> Dict[str, List[DownloadDecision]]:
        """
        Evaluate releases across multiple albums (artist search)

        Args:
            releases: List of ReleaseInfo from indexer search
            albums: List of albums to match against

        Returns:
            Dict mapping album_id to list of decisions
        """
        results = {str(a.id): [] for a in albums}

        for release in releases:
            # Try to match release to an album
            matched_album = self._match_release_to_album(release, albums)

            if matched_album:
                decision = self._evaluate_release(
                    release,
                    matched_album,
                    matched_album.artist
                )
                results[str(matched_album.id)].append(decision)
            else:
                logger.debug(f"Could not match release to any album: {release.title}")

        return results

    def prioritize_decisions(
        self,
        decisions: List[DownloadDecision],
        prefer_larger: bool = True
    ) -> List[DownloadDecision]:
        """
        Sort decisions by quality preference

        Best quality first, with tie-breaker on size.

        Args:
            decisions: List of decisions to sort
            prefer_larger: If True, prefer larger files as tie-breaker

        Returns:
            Sorted list of decisions (best first)
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
            approved_rank = 0 if d.approved else 1

            # Size (larger = better for quality, unless prefer_larger is False)
            size_rank = -size if prefer_larger else size

            return (approved_rank, quality_rank, size_rank)

        return sorted(decisions, key=sort_key)

    def get_best_decision(
        self,
        releases: List[ReleaseInfo],
        album: Album
    ) -> Optional[DownloadDecision]:
        """
        Get the best approved decision for an album

        Convenience method that evaluates and returns only the best result.

        Args:
            releases: List of ReleaseInfo from indexer search
            album: The album we're searching for

        Returns:
            Best approved DownloadDecision, or None if none approved
        """
        decisions = self.get_decisions(releases, album)
        approved = [d for d in decisions if d.approved]

        if not approved:
            return None

        prioritized = self.prioritize_decisions(approved)
        return prioritized[0] if prioritized else None

    def _evaluate_release(
        self,
        release: ReleaseInfo,
        album: Album,
        artist: Artist
    ) -> DownloadDecision:
        """
        Evaluate a single release against all specifications

        Args:
            release: The release to evaluate
            album: The target album
            artist: The artist

        Returns:
            DownloadDecision with rejections if any
        """
        remote_album = RemoteAlbum(
            artist=artist,
            album=album,
            release_info=release
        )

        rejections = []

        for spec in self.specifications:
            try:
                rejection = spec.is_satisfied_by(remote_album)

                if rejection:
                    rejections.append(rejection)
                    logger.debug(
                        f"Spec '{spec.name}' rejected release: {rejection.reason}"
                    )

                    # Stop on permanent rejection (no point checking more)
                    if rejection.type == RejectionType.PERMANENT:
                        break

            except Exception as e:
                logger.error(f"Error in specification '{spec.name}': {e}")
                # Don't let a broken spec stop evaluation
                continue

        return DownloadDecision(
            remote_album=remote_album,
            rejections=rejections
        )

    def _match_release_to_album(
        self,
        release: ReleaseInfo,
        albums: List[Album]
    ) -> Optional[Album]:
        """
        Try to match a release to an album by title

        Simple matching by album name in release title.
        Could be enhanced with fuzzy matching.

        Args:
            release: The release to match
            albums: List of candidate albums

        Returns:
            Matched Album or None
        """
        release_title_lower = release.title.lower()
        release_album = (release.album_name or "").lower()

        for album in albums:
            album_title_lower = album.title.lower()

            # Check if album title appears in release title or parsed album name
            if album_title_lower in release_title_lower:
                return album

            if release_album and album_title_lower in release_album:
                return album

        return None


class DecisionService:
    """
    High-level service for making download decisions

    Provides a simpler interface for common operations and
    handles specification initialization.
    """

    def __init__(self, db: Session):
        """
        Initialize the decision service

        Args:
            db: Database session
        """
        self.db = db
        self._decision_maker = None

    @property
    def decision_maker(self) -> DownloadDecisionMaker:
        """Lazy initialization of decision maker"""
        if self._decision_maker is None:
            from app.services.decision_engine.specifications import get_default_specifications
            specs = get_default_specifications(self.db)
            self._decision_maker = DownloadDecisionMaker(specs)
        return self._decision_maker

    def evaluate_releases(
        self,
        releases: List[ReleaseInfo],
        album_id: str
    ) -> List[DownloadDecision]:
        """
        Evaluate releases for an album by ID

        Args:
            releases: List of ReleaseInfo from indexer
            album_id: Album ID to evaluate for

        Returns:
            List of DownloadDecision
        """
        from app.models import Album
        album = self.db.query(Album).filter(Album.id == album_id).first()

        if not album:
            raise ValueError(f"Album {album_id} not found")

        return self.decision_maker.get_decisions(releases, album)

    def get_approved_releases(
        self,
        releases: List[ReleaseInfo],
        album_id: str
    ) -> List[DownloadDecision]:
        """
        Get only approved releases for an album

        Args:
            releases: List of ReleaseInfo from indexer
            album_id: Album ID to evaluate for

        Returns:
            List of approved DownloadDecision (sorted by quality)
        """
        decisions = self.evaluate_releases(releases, album_id)
        approved = [d for d in decisions if d.approved]
        return self.decision_maker.prioritize_decisions(approved)

    def get_best_release(
        self,
        releases: List[ReleaseInfo],
        album_id: str
    ) -> Optional[DownloadDecision]:
        """
        Get the best approved release for an album

        Args:
            releases: List of ReleaseInfo from indexer
            album_id: Album ID to evaluate for

        Returns:
            Best DownloadDecision or None
        """
        approved = self.get_approved_releases(releases, album_id)
        return approved[0] if approved else None
