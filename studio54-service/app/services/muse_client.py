"""
MUSE API Client for Studio54
Bidirectional integration with MUSE music library system
"""

import httpx
from typing import Optional, Dict, List, Any
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
from app.config import settings

logger = logging.getLogger(__name__)


# Retry decorator for transient network errors
def _retry_on_network_error():
    """Create retry decorator for network operations"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


class MuseClient:
    """
    MUSE API client for library integration

    Provides methods to:
    - Check if albums exist in MUSE library
    - Trigger library scans after downloads
    - Get library statistics
    - Find missing albums
    """

    def __init__(self, base_url: str = None):
        """
        Initialize MUSE client

        Args:
            base_url: MUSE service URL (defaults to settings.muse_service_url)
        """
        self.base_url = (base_url or settings.muse_service_url).rstrip('/')
        self.timeout = 30.0

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Make HTTP request to MUSE API with automatic retry on transient errors

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON request body

        Returns:
            JSON response or None on failure
        """
        url = f"{self.base_url}{endpoint}"

        try:
            return self._execute_request_with_retry(method, url, params, json_data)

        except httpx.TimeoutException:
            logger.error(f"[MUSE] Request timeout after retries: {endpoint}")
            return None

        except httpx.HTTPStatusError as e:
            logger.error(f"[MUSE] HTTP error {e.response.status_code}: {endpoint}")
            return None

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logger.error(f"[MUSE] Request failed after retries: {endpoint} - {e}")
            return None

        except Exception as e:
            logger.error(f"[MUSE] Request failed: {e}")
            return None

    @_retry_on_network_error()
    def _execute_request_with_retry(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute HTTP request with retry logic"""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(
                method=method,
                url=url,
                params=params,
                json=json_data
            )
            response.raise_for_status()
            return response.json()

    def test_connection(self) -> bool:
        """
        Test connection to MUSE service

        Returns:
            True if MUSE is available, False otherwise
        """
        try:
            result = self._make_request("GET", "/health")
            if result and result.get("status") in ["healthy", "running"]:
                logger.info("[MUSE] Connection successful")
                return True
            return False
        except Exception as e:
            logger.error(f"[MUSE] Connection test failed: {e}")
            return False

    def get_libraries(self) -> List[Dict[str, Any]]:
        """
        Get all MUSE libraries

        Returns:
            List of library objects
        """
        result = self._make_request("GET", "/api/v1/libraries")
        if result and isinstance(result, list):
            return result
        return []

    def get_library_artists(
        self,
        library_id: str,
        limit: int = 1000,
        offset: int = 0,
        missing_mbid_only: bool = False
    ) -> Dict[str, Any]:
        """
        Get artists from MUSE library

        Args:
            library_id: MUSE library UUID
            limit: Maximum number of artists to return
            offset: Number of artists to skip
            missing_mbid_only: Only return artists without MusicBrainz IDs

        Returns:
            Dictionary with library info and artist list
        """
        params = {
            "limit": limit,
            "offset": offset,
            "missing_mbid_only": missing_mbid_only
        }

        result = self._make_request("GET", f"/api/v1/libraries/{library_id}/artists", params=params)
        if result:
            return result
        return {"artists": [], "total_artists": 0}

    def search_by_musicbrainz_id(
        self,
        musicbrainz_id: str,
        library_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search MUSE library for files with specific MusicBrainz ID

        Args:
            musicbrainz_id: MusicBrainz release or recording ID
            library_id: Specific library to search (optional)

        Returns:
            List of matching files
        """
        params = {"musicbrainz_id": musicbrainz_id}

        if library_id:
            endpoint = f"/api/v1/libraries/{library_id}/files"
        else:
            # Search all libraries
            endpoint = "/api/v1/files/search"

        result = self._make_request("GET", endpoint, params=params)
        if result:
            return result.get("files", [])
        return []

    def album_exists(
        self,
        musicbrainz_id: str,
        min_track_count: int = 1
    ) -> tuple[bool, Optional[int]]:
        """
        Check if album exists in MUSE library

        Args:
            musicbrainz_id: MusicBrainz release or release group ID
            min_track_count: Minimum number of tracks to consider album complete

        Returns:
            (exists, file_count) tuple
        """
        files = self.search_by_musicbrainz_id(musicbrainz_id)

        if not files:
            return (False, 0)

        file_count = len(files)

        # Consider album exists if we have at least min_track_count files
        exists = file_count >= min_track_count

        logger.info(f"[MUSE] Album {musicbrainz_id}: {file_count} files (exists: {exists})")

        return (exists, file_count)

    def trigger_scan(
        self,
        library_id: str,
        path_hint: Optional[str] = None
    ) -> bool:
        """
        Trigger MUSE library scan

        Args:
            library_id: Library UUID to scan
            path_hint: Optional path to scan (for faster targeted scans)

        Returns:
            True if scan started successfully
        """
        endpoint = f"/api/v1/libraries/{library_id}/scan"

        json_data = {}
        if path_hint:
            json_data["path"] = path_hint

        result = self._make_request("POST", endpoint, json_data=json_data)

        if result and result.get("success"):
            logger.info(f"[MUSE] Scan triggered for library {library_id}")
            return True

        logger.error(f"[MUSE] Failed to trigger scan for library {library_id}")
        return False

    def get_library_stats(self, library_id: str) -> Optional[Dict[str, Any]]:
        """
        Get MUSE library statistics

        Args:
            library_id: Library UUID

        Returns:
            Library stats dict or None
        """
        endpoint = f"/api/v1/libraries/{library_id}"
        result = self._make_request("GET", endpoint)

        if result:
            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "path": result.get("path"),
                "total_files": result.get("total_files", 0),
                "total_size_bytes": result.get("total_size_bytes", 0),
                "last_scan_at": result.get("last_scan_at")
            }

        return None

    def get_artists(self, library_id: str) -> List[Dict[str, Any]]:
        """
        Get all unique artists from MUSE library

        Args:
            library_id: Library UUID

        Returns:
            List of artist names with file counts
        """
        # This would need to be implemented on MUSE side
        # For now, return empty list
        logger.warning("[MUSE] get_artists not yet implemented on MUSE API")
        return []

    def find_missing_albums(
        self,
        library_id: str,
        artist_musicbrainz_id: str
    ) -> List[str]:
        """
        Find albums by artist that are missing from MUSE library

        Args:
            library_id: MUSE library ID
            artist_musicbrainz_id: MusicBrainz artist ID

        Returns:
            List of missing release group MBIDs
        """
        # This is a placeholder - actual implementation would:
        # 1. Get all albums from MusicBrainz for artist
        # 2. Check which ones exist in MUSE
        # 3. Return list of missing MBIDs

        logger.warning("[MUSE] find_missing_albums requires MusicBrainz integration")
        return []

    def verify_album_quality(
        self,
        musicbrainz_id: str,
        min_quality_score: int = 70
    ) -> tuple[bool, Optional[int]]:
        """
        Verify if existing album in MUSE meets quality standards

        Args:
            musicbrainz_id: MusicBrainz release ID
            min_quality_score: Minimum quality score (0-100)

        Returns:
            (meets_quality, average_quality) tuple
        """
        files = self.search_by_musicbrainz_id(musicbrainz_id)

        if not files:
            return (False, None)

        # Get quality scores from files (if MUSE provides them)
        quality_scores = []
        for file in files:
            score = file.get("quality_score", 0)
            if score > 0:
                quality_scores.append(score)

        if not quality_scores:
            # No quality scores available, assume acceptable
            return (True, None)

        avg_quality = sum(quality_scores) // len(quality_scores)
        meets_quality = avg_quality >= min_quality_score

        logger.info(f"[MUSE] Album {musicbrainz_id} avg quality: {avg_quality} (min: {min_quality_score})")

        return (meets_quality, avg_quality)


# Singleton instance
_muse_client: Optional[MuseClient] = None


def get_muse_client() -> MuseClient:
    """
    Get singleton MUSE client instance

    Returns:
        MuseClient instance
    """
    global _muse_client
    if _muse_client is None:
        _muse_client = MuseClient()
    return _muse_client
