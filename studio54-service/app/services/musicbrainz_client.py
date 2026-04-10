"""
MusicBrainz API Client for Studio54
Extended from MUSE with artist search and album discovery

Uses centralized MusicBrainz API Service for rate-limited queue-based access
API Docs: https://musicbrainz.org/doc/MusicBrainz_API
"""

import os
import time
import requests
from typing import Optional, Dict, List, Any
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


# Retry decorator for transient network errors
def _retry_on_network_error():
    """Create retry decorator for network operations"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(3),  # Wait 3 seconds between retries
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


class MusicBrainzClient:
    """
    MusicBrainz API client with local-first, remote-fallback pattern

    When a local MusicBrainz PostgreSQL mirror is configured, queries go
    directly to the local DB (no rate limits). Falls back to the centralized
    API service for queries that fail locally or for cover art (which requires
    the Cover Art Archive).

    The centralized API Service handles:
    - Global 1 req/sec rate limiting
    - Fair queue management with MUSE
    - Automatic retries with exponential backoff
    """

    COVER_ART_URL = "https://coverartarchive.org"

    # MusicBrainz API Service URL (internal Docker network)
    API_SERVICE_URL = os.getenv(
        "MUSICBRAINZ_API_SERVICE_URL",
        "http://musicbrainz-api-service:8020"
    )

    def __init__(self):
        """Initialize MusicBrainz client with optional local DB"""
        self.local_db = None
        self._init_local_db()

    def _init_local_db(self):
        """Try to initialize local MusicBrainz database connection"""
        try:
            from app.services.musicbrainz_local import get_musicbrainz_local_db
            self.local_db = get_musicbrainz_local_db()
            if self.local_db:
                logger.info("MusicBrainz client using local DB (with remote fallback)")
        except Exception as e:
            logger.debug(f"Local MB DB not available: {e}")
            self.local_db = None

    @property
    def has_local_db(self) -> bool:
        """Check if local database is available"""
        return self.local_db is not None

    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Optional[Dict[str, Any]]:
        """
        Make API request via centralized MusicBrainz API Service

        The API service handles:
        - Global rate limiting (1 req/sec)
        - Fair queue processing with MUSE
        - Retry logic with exponential backoff

        Args:
            endpoint: MusicBrainz API endpoint (e.g., "artist/123", "release-group")
            params: Query parameters
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            JSON response or None on failure
        """
        if params is None:
            params = {}

        # Queue request in Studio54 queue (with retry)
        try:
            task_id = self._queue_request_with_retry(endpoint, params)
            if not task_id:
                return None

            logger.debug(f"[MusicBrainz API Service] Queued task {task_id} for {endpoint}")

        except Exception as e:
            logger.error(f"[MusicBrainz API Service] Failed to queue request after retries: {e}")
            return None

        # Wait for result with timeout (with retry)
        try:
            return self._get_result_with_retry(task_id)

        except Exception as e:
            logger.error(f"[MusicBrainz API Service] Failed to get result after retries: {e}")
            return None

    @_retry_on_network_error()
    def _queue_request_with_retry(
        self,
        endpoint: str,
        params: Dict[str, Any]
    ) -> Optional[str]:
        """Queue request to API service with retry logic"""
        queue_response = requests.post(
            f"{self.API_SERVICE_URL}/api/v1/studio54/request",
            json={
                "endpoint": endpoint,
                "params": params
            },
            timeout=10
        )

        if queue_response.status_code != 200:
            logger.error(f"[MusicBrainz API Service] Failed to queue request: {queue_response.status_code}")
            return None

        return queue_response.json().get("task_id")

    @_retry_on_network_error()
    def _get_result_with_retry(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get result from API service with retry logic"""
        result_response = requests.get(
            f"{self.API_SERVICE_URL}/api/v1/studio54/result/{task_id}",
            params={"wait": True, "timeout": 120},  # 2 minute timeout
            timeout=125  # Slightly longer than task timeout
        )

        if result_response.status_code != 200:
            logger.error(f"[MusicBrainz API Service] Failed to get result: {result_response.status_code}")
            return None

        result_data = result_response.json()

        if result_data.get("status") != "completed":
            logger.error(f"[MusicBrainz API Service] Task not completed: {result_data.get('status')}")
            return None

        return result_data.get("result")

    # === STUDIO54 EXTENSIONS: Artist & Album Discovery ===

    def search_artist(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Search for artists by name (Studio54 extension)

        Args:
            query: Artist name to search
            limit: Maximum results to return (default 25)

        Returns:
            List of artist matches with metadata
        """
        # Try local DB first
        if self.local_db:
            try:
                results = self.local_db.search_artist(query, limit=limit)
                if results:
                    return results
            except Exception as e:
                logger.debug(f"Local DB search_artist failed, falling back to remote: {e}")

        # Remote fallback
        query_clean = query.replace('"', '\\"')
        params = {
            "query": f'artist:"{query_clean}"',
            "limit": limit
        }

        result = self._make_request("artist", params)

        if not result or "artists" not in result:
            return []

        return result["artists"]

    def get_artist(self, mbid: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed artist information by MusicBrainz ID

        Args:
            mbid: MusicBrainz artist ID

        Returns:
            Artist metadata or None
        """
        # Try local DB first
        if self.local_db:
            try:
                result = self.local_db.get_artist(mbid)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Local DB get_artist failed, falling back to remote: {e}")

        # Remote fallback
        params = {
            "inc": "tags+ratings+genres"
        }

        return self._make_request(f"artist/{mbid}", params)

    def get_recording(
        self,
        mbid: str,
        includes: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed recording information by MusicBrainz ID

        Args:
            mbid: MusicBrainz recording ID
            includes: Additional data to include (artists, releases, etc.)

        Returns:
            Recording metadata or None
        """
        # Try local DB first
        if self.local_db:
            try:
                result = self.local_db.get_recording(mbid, includes=includes)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Local DB get_recording failed, falling back to remote: {e}")

        # Remote fallback
        inc_list = includes or ["artists", "releases"]
        params = {
            "inc": "+".join(inc_list)
        }

        return self._make_request(f"recording/{mbid}", params)

    def get_artist_albums(
        self,
        artist_mbid: str,
        types: Optional[List[str]] = None,
        exclude_secondary: bool = True,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get all albums (release groups) for an artist with pagination

        Args:
            artist_mbid: MusicBrainz artist ID
            types: Album types to include (Album, EP, Single, etc.)
            exclude_secondary: Exclude compilations, live, soundtracks, remixes, etc. (default: True)
            limit: Results per page (max 100)

        Returns:
            List of release groups (albums) filtered by type and secondary type
        """
        # Try local DB first
        if self.local_db:
            try:
                results = self.local_db.get_artist_albums(
                    artist_mbid, types=types, exclude_secondary=exclude_secondary
                )
                if results is not None:  # Empty list is valid (artist may have no albums)
                    return results
            except Exception as e:
                logger.debug(f"Local DB get_artist_albums failed, falling back to remote: {e}")

        # Remote fallback
        all_releases = []
        offset = 0

        # Secondary types to exclude (keep Live, Compilation, Soundtrack, Audiobook for filtering)
        excluded_secondary_types = {
            "Remix",
            "Spokenword",
            "Interview",
            "Audio drama",
            "DJ-mix",
            "Mixtape/Street",
            "Demo"
        }

        while True:
            # Build query string with artist MBID and optional types
            query_parts = [f"arid:{artist_mbid}"]
            if types:
                # Add type filter (e.g., "type:album OR type:ep")
                type_query = " OR ".join([f"type:{t.lower()}" for t in types])
                query_parts.append(f"({type_query})")

            params = {
                "query": " AND ".join(query_parts),
                "limit": limit,
                "offset": offset
            }

            result = self._make_request("release-group", params)

            if not result or "release-groups" not in result:
                break

            releases = result["release-groups"]

            # Filter out unwanted secondary types (client-side filtering)
            if exclude_secondary:
                filtered_releases = []
                for release in releases:
                    secondary_types = release.get("secondary-types", [])
                    # Only include if it has no secondary types or none of the excluded ones
                    if not any(st in excluded_secondary_types for st in secondary_types):
                        filtered_releases.append(release)
                releases = filtered_releases

            all_releases.extend(releases)

            # Check if we've got all results
            if len(result["release-groups"]) < limit:
                break

            offset += limit

            # Safety check: don't fetch more than 1000 albums
            if offset >= 1000:
                break

        return all_releases

    def get_artist_audiobooks(
        self,
        artist_mbid: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get audiobook release groups for an artist

        Calls get_artist_albums() with exclude_secondary=False, then filters
        to keep only release groups where secondary-types contains "Audiobook".

        Args:
            artist_mbid: MusicBrainz artist ID
            limit: Results per page (max 100)

        Returns:
            List of audiobook release groups
        """
        all_releases = self.get_artist_albums(
            artist_mbid, exclude_secondary=False, limit=limit
        )

        # Filter to audiobooks only
        audiobooks = []
        for release in all_releases:
            secondary_types = release.get("secondary-types", [])
            if "Audiobook" in secondary_types:
                audiobooks.append(release)

        logger.info(
            f"Found {len(audiobooks)} audiobook release groups for artist {artist_mbid} "
            f"(out of {len(all_releases)} total)"
        )
        return audiobooks

    def get_release_group(self, release_group_mbid: str) -> Optional[Dict[str, Any]]:
        """
        Get release group details including all releases

        Note: No local DB shortcut here because the remote API returns
        releases with full details needed by select_best_release().
        The local DB path for best release selection goes through
        select_best_release() directly.

        Args:
            release_group_mbid: MusicBrainz release group ID

        Returns:
            Release group with releases or None
        """
        params = {
            "inc": "releases+artist-credits+tags"
        }

        return self._make_request(f"release-group/{release_group_mbid}", params)

    def select_best_release(
        self,
        release_group_mbid: str,
        preferred_countries: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Select best release from a release group

        Scoring strategy:
        1. Status: Official (100) > Promotion (50) > Bootleg (10)
        2. Country preference (US, GB, XW=Worldwide)
        3. Track count (more = complete version)
        4. Cover art availability

        Args:
            release_group_mbid: MusicBrainz release group ID
            preferred_countries: List of preferred country codes (default: ["US", "GB", "XW"])

        Returns:
            Best release or None
        """
        if preferred_countries is None:
            preferred_countries = ["US", "GB", "XW"]  # US, UK, Worldwide

        # Try local DB first (handles scoring internally)
        if self.local_db:
            try:
                result = self.local_db.select_best_release(
                    release_group_mbid, preferred_countries=preferred_countries
                )
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Local DB select_best_release failed, falling back to remote: {e}")

        rg = self.get_release_group(release_group_mbid)

        if not rg or "releases" not in rg:
            return None

        releases = rg["releases"]

        if not releases:
            return None

        def score_release(rel):
            score = 0

            # Status preference
            status_scores = {"Official": 100, "Promotion": 50, "Bootleg": 10}
            score += status_scores.get(rel.get("status"), 0)

            # Country preference
            country = rel.get("country")
            if country and preferred_countries:
                try:
                    idx = preferred_countries.index(country)
                    score += (len(preferred_countries) - idx) * 10
                except ValueError:
                    pass

            # Track count (more is better)
            media = rel.get("media", [])
            track_count = sum(m.get("track-count", 0) for m in media)
            score += track_count

            return score

        releases.sort(key=score_release, reverse=True)
        best_release = releases[0]

        # Get full release details
        return self.get_release(best_release["id"])

    def get_release(self, release_mbid: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed release information

        Args:
            release_mbid: MusicBrainz release ID

        Returns:
            Release metadata with recordings or None
        """
        # Try local DB first
        if self.local_db:
            try:
                result = self.local_db.get_release(release_mbid)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Local DB get_release failed, falling back to remote: {e}")

        # Remote fallback
        params = {
            "inc": "recordings+artist-credits+labels+release-groups"
        }

        return self._make_request(f"release/{release_mbid}", params)

    def get_cover_art(self, release_mbid: str) -> Optional[str]:
        """
        Get cover art URL from Cover Art Archive

        Args:
            release_mbid: MusicBrainz release ID

        Returns:
            Cover art URL or None
        """
        url = f"{self.COVER_ART_URL}/release/{release_mbid}"

        try:
            return self._fetch_cover_art_with_retry(url)
        except Exception as e:
            logger.debug(f"[Cover Art Archive] Failed to fetch cover art for release {release_mbid}: {e}")
            return None

    def get_cover_art_for_release_group(self, release_group_mbid: str) -> Optional[str]:
        """
        Get cover art URL from Cover Art Archive using release-group ID

        The Cover Art Archive will automatically redirect to a release that has cover art.
        This is more reliable than selecting a specific release.

        Args:
            release_group_mbid: MusicBrainz release-group ID

        Returns:
            Cover art URL or None
        """
        url = f"{self.COVER_ART_URL}/release-group/{release_group_mbid}"

        try:
            return self._fetch_cover_art_with_retry(url, allow_redirects=True)
        except Exception as e:
            logger.debug(f"[Cover Art Archive] Failed to fetch cover art for release-group {release_group_mbid}: {e}")
            return None

    @_retry_on_network_error()
    def _fetch_cover_art_with_retry(self, url: str, allow_redirects: bool = False) -> Optional[str]:
        """Fetch cover art with retry logic"""
        response = requests.get(url, timeout=10, allow_redirects=allow_redirects)

        if response.status_code == 200:
            data = response.json()
            for img in data.get("images", []):
                if img.get("front"):
                    # Return 500px thumbnail or full image
                    return img.get("thumbnails", {}).get("500") or img.get("image")

        return None

    # === MUSE COMPATIBILITY: Recording Search ===

    def search_recording(
        self,
        artist: Optional[str] = None,
        title: Optional[str] = None,
        release: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for recordings by artist, title, or album (MUSE compatibility)

        Args:
            artist: Artist name
            title: Recording/track title
            release: Album/release name
            limit: Maximum results to return

        Returns:
            List of recording matches with metadata
        """
        query_parts = []

        if artist:
            artist_clean = artist.replace('"', '\\"')
            query_parts.append(f'artist:"{artist_clean}"')

        if title:
            title_clean = title.replace('"', '\\"')
            query_parts.append(f'recording:"{title_clean}"')

        if release:
            release_clean = release.replace('"', '\\"')
            query_parts.append(f'release:"{release_clean}"')

        if not query_parts:
            return []

        query = " AND ".join(query_parts)

        params = {
            "query": query,
            "limit": limit
        }

        result = self._make_request("recording", params)

        if not result or "recordings" not in result:
            return []

        return result["recordings"]

    def get_release_tracks(self, release_group_mbid: str) -> List[Dict[str, Any]]:
        """
        Get all tracks for a release group

        Selects the best release for the release group and returns all tracks
        with track numbers, titles, and durations

        Args:
            release_group_mbid: MusicBrainz release group ID

        Returns:
            List of tracks with metadata (track number, title, duration, mbid)
        """
        # Try local DB first (handles best release selection internally)
        if self.local_db:
            try:
                tracks = self.local_db.get_release_tracks(release_group_mbid)
                if tracks is not None:  # Empty list is valid
                    return tracks
            except Exception as e:
                logger.debug(f"Local DB get_release_tracks failed, falling back to remote: {e}")

        # Get the best release for this release group (remote)
        release = self.select_best_release(release_group_mbid)

        if not release or "media" not in release:
            return []

        tracks = []
        track_offset = 0

        # Process all media (CDs, vinyl sides, etc.)
        for medium in release["media"]:
            if "tracks" not in medium:
                continue

            disc_number = medium.get("position", 1)

            for track_data in medium["tracks"]:
                recording = track_data.get("recording", {})

                # Extract duration (in milliseconds)
                duration_ms = None
                if "length" in track_data and track_data["length"]:
                    duration_ms = int(track_data["length"])
                elif "length" in recording and recording["length"]:
                    duration_ms = int(recording["length"])

                # Track number (position in the medium)
                position = track_data.get("position")
                if position:
                    track_number = int(position)
                else:
                    track_number = track_offset + 1

                track_info = {
                    "track_number": track_number,
                    "disc_number": disc_number,
                    "title": track_data.get("title") or recording.get("title", "Unknown Track"),
                    "duration_ms": duration_ms,
                    "musicbrainz_id": recording.get("id")
                }

                tracks.append(track_info)
                track_offset += 1

        return tracks


# Singleton instance
_musicbrainz_client: Optional[MusicBrainzClient] = None


def get_musicbrainz_client() -> MusicBrainzClient:
    """
    Get singleton MusicBrainz client instance

    Returns:
        Shared MusicBrainzClient instance
    """
    global _musicbrainz_client
    if _musicbrainz_client is None:
        _musicbrainz_client = MusicBrainzClient()
    return _musicbrainz_client


def reset_musicbrainz_client():
    """Reset the singleton to pick up config changes (e.g., local DB enabled/disabled)"""
    global _musicbrainz_client
    _musicbrainz_client = None
