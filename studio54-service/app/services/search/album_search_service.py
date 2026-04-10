"""
Album Search Service - Orchestrates searches across all indexers

Coordinates searches across multiple indexers, parses results,
and processes them through the decision engine.

Based on Lidarr's search services from:
- src/NzbDrone.Core/Music/AlbumService.cs
- src/NzbDrone.Core/IndexerSearch/
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Album, Artist, Indexer
from app.models.download_decision import ReleaseInfo, DownloadDecision
from app.services.encryption import get_encryption_service
from app.services.newznab_client import NewznabClient, IndexerAggregator
from app.services.search.release_parser import ReleaseParser
from app.services.decision_engine import DownloadDecisionMaker
from app.services.decision_engine.specifications import get_default_specifications

logger = logging.getLogger(__name__)


class AlbumSearchService:
    """
    Orchestrates album searches across all configured indexers

    Handles:
    - Building indexer clients from database configuration
    - Executing searches across all enabled indexers
    - Parsing results into ReleaseInfo objects
    - Passing results through the decision engine
    - Updating search timestamps
    """

    def __init__(self, db: Session):
        """
        Initialize the album search service

        Args:
            db: Database session
        """
        self.db = db
        self.release_parser = ReleaseParser()
        self._decision_maker = None
        self._encryption_service = None

    @property
    def encryption_service(self):
        """Lazy initialization of encryption service"""
        if self._encryption_service is None:
            self._encryption_service = get_encryption_service()
        return self._encryption_service

    @property
    def decision_maker(self) -> DownloadDecisionMaker:
        """Lazy initialization of decision maker"""
        if self._decision_maker is None:
            specs = get_default_specifications(self.db)
            self._decision_maker = DownloadDecisionMaker(specs)
        return self._decision_maker

    async def search_album(
        self,
        album_id: str,
        auto_grab: bool = False
    ) -> Dict[str, Any]:
        """
        Search all indexers for an album

        Args:
            album_id: UUID of the album to search for
            auto_grab: If True, automatically grab the best result

        Returns:
            Dict with search results and statistics
        """
        album = self.db.query(Album).filter(Album.id == album_id).first()
        if not album:
            raise ValueError(f"Album {album_id} not found")

        artist = album.artist
        if not artist:
            raise ValueError(f"Album {album_id} has no associated artist")

        logger.info(f"Searching for album: {artist.name} - {album.title}")

        # Get all enabled indexers
        indexers = self.db.query(Indexer).filter(Indexer.is_enabled == True).all()
        if not indexers:
            logger.warning("No enabled indexers configured")
            return {
                "album_id": album_id,
                "artist": artist.name,
                "album": album.title,
                "results": [],
                "decisions": [],
                "total_results": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "error": "No enabled indexers configured"
            }

        # Build indexer clients
        clients = self._build_indexer_clients(indexers)

        if not clients:
            logger.warning("No valid indexer clients could be created")
            return {
                "album_id": album_id,
                "artist": artist.name,
                "album": album.title,
                "results": [],
                "decisions": [],
                "total_results": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "error": "No valid indexer clients"
            }

        # Create aggregator and search
        aggregator = IndexerAggregator(clients)
        results = aggregator.search_music(artist=artist.name, album=album.title)

        logger.info(f"Found {len(results)} results from indexers")

        # Parse results into ReleaseInfo
        releases = []
        for result in results:
            indexer = self._find_indexer_by_name(indexers, result.indexer_name)
            indexer_id = str(indexer.id) if indexer else ""

            release_info = self.release_parser.parse(result, indexer_id, result.indexer_name)
            releases.append(release_info)

        # Get decisions from decision engine
        decisions = self.decision_maker.get_decisions(releases, album)

        # Update last search time
        album.last_search_time = datetime.now(timezone.utc)
        self.db.commit()

        # Prepare response
        approved = [d for d in decisions if d.approved]
        rejected = [d for d in decisions if not d.approved]

        logger.info(f"Search complete: {len(approved)} approved, {len(rejected)} rejected")

        return {
            "album_id": str(album_id),
            "artist": artist.name,
            "album": album.title,
            "results": [r.to_dict() for r in releases],
            "decisions": [d.to_dict() for d in decisions],
            "total_results": len(releases),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
        }

    async def search_artist(
        self,
        artist_id: str,
        wanted_only: bool = True
    ) -> Dict[str, Any]:
        """
        Search for all wanted albums by an artist

        Args:
            artist_id: UUID of the artist
            wanted_only: If True, only search for wanted albums

        Returns:
            Dict with search results grouped by album
        """
        artist = self.db.query(Artist).filter(Artist.id == artist_id).first()
        if not artist:
            raise ValueError(f"Artist {artist_id} not found")

        # Get albums to search
        query = self.db.query(Album).filter(Album.artist_id == artist_id)
        if wanted_only:
            from app.models.album import AlbumStatus
            query = query.filter(
                Album.monitored == True,
                Album.status == AlbumStatus.WANTED
            )

        albums = query.all()

        if not albums:
            return {
                "artist_id": str(artist_id),
                "artist": artist.name,
                "albums_searched": 0,
                "results": {}
            }

        logger.info(f"Searching for {len(albums)} albums by {artist.name}")

        # Search each album
        results = {}
        total_approved = 0
        total_rejected = 0

        for album in albums:
            try:
                album_result = await self.search_album(str(album.id))
                results[str(album.id)] = album_result
                total_approved += album_result.get("approved_count", 0)
                total_rejected += album_result.get("rejected_count", 0)
            except Exception as e:
                logger.error(f"Error searching for album {album.title}: {e}")
                results[str(album.id)] = {
                    "error": str(e),
                    "album": album.title
                }

        return {
            "artist_id": str(artist_id),
            "artist": artist.name,
            "albums_searched": len(albums),
            "total_approved": total_approved,
            "total_rejected": total_rejected,
            "results": results
        }

    def search_album_sync(
        self,
        album_id: str
    ) -> Dict[str, Any]:
        """
        Synchronous version of search_album for use in Celery tasks

        Args:
            album_id: UUID of the album to search for

        Returns:
            Dict with search results and statistics
        """
        album = self.db.query(Album).filter(Album.id == album_id).first()
        if not album:
            raise ValueError(f"Album {album_id} not found")

        artist = album.artist
        if not artist:
            raise ValueError(f"Album {album_id} has no associated artist")

        logger.info(f"[Sync] Searching for album: {artist.name} - {album.title}")

        # Get all enabled indexers
        indexers = self.db.query(Indexer).filter(Indexer.is_enabled == True).all()
        if not indexers:
            return {
                "album_id": album_id,
                "results": [],
                "decisions": [],
                "error": "No enabled indexers"
            }

        # Build indexer clients
        clients = self._build_indexer_clients(indexers)
        if not clients:
            return {
                "album_id": album_id,
                "results": [],
                "decisions": [],
                "error": "No valid indexer clients"
            }

        # Search synchronously
        aggregator = IndexerAggregator(clients)
        results = aggregator.search_music(artist=artist.name, album=album.title)

        # Parse and get decisions
        releases = []
        for result in results:
            indexer = self._find_indexer_by_name(indexers, result.indexer_name)
            indexer_id = str(indexer.id) if indexer else ""
            releases.append(self.release_parser.parse(result, indexer_id))

        decisions = self.decision_maker.get_decisions(releases, album)

        # Update last search time
        album.last_search_time = datetime.now(timezone.utc)
        self.db.commit()

        approved = [d for d in decisions if d.approved]
        rejected = [d for d in decisions if not d.approved]

        return {
            "album_id": str(album_id),
            "artist": artist.name,
            "album": album.title,
            "releases": releases,
            "decisions": decisions,
            "total_results": len(releases),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
        }

    def get_approved_decisions(
        self,
        album_id: str
    ) -> List[DownloadDecision]:
        """
        Search and return only approved decisions (sorted by quality)

        Args:
            album_id: UUID of the album

        Returns:
            List of approved DownloadDecision sorted by quality
        """
        result = self.search_album_sync(album_id)
        decisions = result.get("decisions", [])

        # Filter and sort approved decisions
        approved = [d for d in decisions if d.approved]
        return self.decision_maker.prioritize_decisions(approved)

    def _build_indexer_clients(self, indexers: List[Indexer]) -> List[NewznabClient]:
        """
        Build NewznabClient instances from database indexer records

        Args:
            indexers: List of Indexer model instances

        Returns:
            List of configured NewznabClient instances
        """
        clients = []

        for indexer in indexers:
            try:
                # Decrypt API key
                api_key = self.encryption_service.decrypt(indexer.api_key_encrypted)

                # Get categories (default to music categories)
                categories = indexer.categories if indexer.categories else [3010, 3040]

                client = NewznabClient(
                    base_url=indexer.base_url,
                    api_key=api_key,
                    indexer_name=indexer.name,
                    categories=categories
                )
                clients.append(client)

                logger.debug(f"Built client for indexer: {indexer.name}")

            except Exception as e:
                logger.error(f"Failed to build client for indexer {indexer.name}: {e}")
                continue

        return clients

    def _find_indexer_by_name(
        self,
        indexers: List[Indexer],
        name: str
    ) -> Optional[Indexer]:
        """Find indexer by name from list"""
        for indexer in indexers:
            if indexer.name == name:
                return indexer
        return None


class SearchService:
    """
    High-level search service providing convenient methods
    """

    def __init__(self, db: Session):
        self.db = db
        self._album_search = None

    @property
    def album_search(self) -> AlbumSearchService:
        """Lazy initialization of album search service"""
        if self._album_search is None:
            self._album_search = AlbumSearchService(self.db)
        return self._album_search

    async def search_and_grab_best(
        self,
        album_id: str
    ) -> Optional[DownloadDecision]:
        """
        Search for an album and return the best approved result

        Args:
            album_id: UUID of the album

        Returns:
            Best DownloadDecision or None if no approved results
        """
        approved = self.album_search.get_approved_decisions(album_id)
        return approved[0] if approved else None

    def get_wanted_albums(
        self,
        limit: int = 100,
        artist_id: Optional[str] = None
    ) -> List[Album]:
        """
        Get wanted albums for searching

        Args:
            limit: Maximum number of albums to return
            artist_id: Optional filter by artist

        Returns:
            List of wanted Album instances
        """
        from app.models.album import AlbumStatus

        query = self.db.query(Album).join(Artist).filter(
            Album.monitored == True,
            Artist.is_monitored == True,
            Album.status == AlbumStatus.WANTED
        )

        if artist_id:
            query = query.filter(Album.artist_id == artist_id)

        # Order by added date (oldest first) to prioritize older wants
        query = query.order_by(Album.added_at.asc())

        return query.limit(limit).all()
