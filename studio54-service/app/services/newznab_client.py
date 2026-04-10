"""
Newznab Indexer Client for Studio54
Multi-indexer NZB search with quality-based ranking and deduplication
"""
import time
import requests
import xml.etree.ElementTree as ET
from typing import Optional, Dict, List, Any
from datetime import datetime
import logging
import re
from urllib.parse import urlencode
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


# Retry decorator for transient network errors
def _retry_on_network_error():
    """Create retry decorator for network operations"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


class NewznabResult:
    """
    Represents a single NZB search result

    Attributes:
        title: NZB title
        guid: Unique identifier (for deduplication)
        size_bytes: File size in bytes
        publish_date: Publication timestamp
        indexer_name: Source indexer name
        category: Newznab category ID
        download_url: NZB download URL
        info_url: Web page URL
        grabs: Number of times grabbed (community validation)
        quality_score: Calculated quality score (0-100)
        format: Audio format (FLAC, MP3, AAC, etc.)
        bitrate: Bitrate in kbps
    """

    def __init__(self, data: Dict[str, Any], indexer_name: str):
        self.title = data.get("title", "")
        self.guid = data.get("guid", "")
        self.size_bytes = int(data.get("size", 0))
        self.publish_date = data.get("pubDate")
        self.indexer_name = indexer_name
        self.category = data.get("category")
        self.download_url = data.get("link", "")
        self.info_url = data.get("comments", "")
        self.grabs = int(data.get("grabs", 0))

        # Extract quality info from title
        self.format, self.bitrate = self._parse_quality()
        self.quality_score = self._calculate_quality_score()

    def _parse_quality(self) -> tuple[str, Optional[int]]:
        """
        Parse audio format and bitrate from title

        Returns:
            (format, bitrate) tuple
        """
        title_upper = self.title.upper()

        # Format detection
        if "FLAC" in title_upper:
            format_type = "FLAC"
        elif "ALAC" in title_upper or "APPLE LOSSLESS" in title_upper:
            format_type = "ALAC"
        elif "WAV" in title_upper:
            format_type = "WAV"
        elif "AAC" in title_upper or "M4A" in title_upper:
            format_type = "AAC"
        elif "MP3" in title_upper:
            format_type = "MP3"
        elif "OGG" in title_upper or "VORBIS" in title_upper:
            format_type = "OGG"
        elif "OPUS" in title_upper:
            format_type = "OPUS"
        else:
            format_type = "UNKNOWN"

        # Bitrate detection (for lossy formats)
        bitrate = None
        if format_type in ["MP3", "AAC", "OGG", "OPUS"]:
            # Match patterns like: 320, 320kbps, V0, V2, CBR320, etc.
            bitrate_match = re.search(r'(\d{3})\s*k?bps?|V([0-2])|CBR(\d{3})|VBR(\d{3})', title_upper)
            if bitrate_match:
                if bitrate_match.group(1):
                    bitrate = int(bitrate_match.group(1))
                elif bitrate_match.group(2):  # VBR quality (V0, V1, V2)
                    v_quality = int(bitrate_match.group(2))
                    bitrate = 250 if v_quality == 0 else (225 if v_quality == 1 else 190)
                elif bitrate_match.group(3):
                    bitrate = int(bitrate_match.group(3))
                elif bitrate_match.group(4):
                    bitrate = int(bitrate_match.group(4))

        return format_type, bitrate

    def _calculate_quality_score(self) -> int:
        """
        Calculate quality score (0-100) based on format and bitrate

        Scoring:
        - Lossless (FLAC, ALAC, WAV): 90-100
        - High bitrate AAC/MP3 (320kbps, V0): 70-85
        - Medium bitrate (256kbps, V1): 50-65
        - Lower bitrate (192kbps, V2): 30-45
        - Unknown/Low: 0-25
        """
        score = 0

        # Format base score
        format_scores = {
            "FLAC": 100,
            "ALAC": 98,
            "WAV": 95,
            "AAC": 60,
            "MP3": 55,
            "OPUS": 50,
            "OGG": 45,
            "UNKNOWN": 10
        }
        score = format_scores.get(self.format, 0)

        # Adjust for bitrate (lossy formats only)
        if self.bitrate and self.format not in ["FLAC", "ALAC", "WAV"]:
            if self.bitrate >= 320:
                score += 25
            elif self.bitrate >= 256:
                score += 20
            elif self.bitrate >= 192:
                score += 15
            elif self.bitrate >= 128:
                score += 10
            else:
                score += 5

        # Cap at 100
        return min(score, 100)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "title": self.title,
            "guid": self.guid,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / (1024 * 1024), 2),
            "publish_date": self.publish_date,
            "indexer": self.indexer_name,
            "download_url": self.download_url,
            "info_url": self.info_url,
            "grabs": self.grabs,
            "quality_score": self.quality_score,
            "format": self.format,
            "bitrate": self.bitrate
        }


class NewznabClient:
    """
    Newznab API client for NZB indexer integration

    Supports standard Newznab API protocol used by most indexers.
    Handles multi-indexer search, result aggregation, and deduplication.
    """

    # Newznab audio categories
    CATEGORY_AUDIO = 3000
    CATEGORY_AUDIO_MP3 = 3010
    CATEGORY_AUDIO_LOSSLESS = 3040
    CATEGORY_AUDIO_AUDIOBOOK = 3030

    def __init__(self, base_url: str, api_key: str, indexer_name: str, categories: Optional[List[int]] = None):
        """
        Initialize Newznab client

        Args:
            base_url: Indexer API base URL (e.g., https://api.nzbgeek.info/api)
            api_key: Indexer API key (decrypted)
            indexer_name: Display name for this indexer
            categories: List of Newznab category codes to search (default: [3010, 3040] for MP3 and lossless)
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.indexer_name = indexer_name
        self.last_request_time = 0.0
        self.rate_limit_interval = 1.0  # 1 request per second (default)

        # Default to MP3 (3010) and lossless (3040) audio categories if not specified
        self.categories = categories if categories else [self.CATEGORY_AUDIO_MP3, self.CATEGORY_AUDIO_LOSSLESS]

    def _wait_for_rate_limit(self):
        """Enforce rate limiting before making request"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.rate_limit_interval:
            wait_time = self.rate_limit_interval - time_since_last
            time.sleep(wait_time)

        self.last_request_time = time.time()

    def _make_request(
        self,
        params: Dict[str, Any],
        timeout: int = 30
    ) -> Optional[ET.Element]:
        """
        Make API request to Newznab indexer with automatic retry on transient errors

        Args:
            params: Query parameters
            timeout: Request timeout in seconds

        Returns:
            XML root element or None on failure
        """
        self._wait_for_rate_limit()

        # Build request parameters
        request_params = {
            "apikey": self.api_key,
            "t": params.get("t", "search"),
            "o": "xml"
        }
        request_params.update({k: v for k, v in params.items() if k != "t"})

        try:
            content = self._execute_request_with_retry(request_params, timeout)

            # Parse XML response
            root = ET.fromstring(content)

            # Check for error
            error = root.find(".//error")
            if error is not None:
                error_code = error.get("code", "unknown")
                error_desc = error.get("description", "Unknown error")
                logger.error(f"[{self.indexer_name}] API error {error_code}: {error_desc}")
                return None

            return root

        except requests.exceptions.Timeout:
            logger.error(f"[{self.indexer_name}] Request timeout after {timeout}s (after retries)")
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"[{self.indexer_name}] Request failed after retries: {e}")
            return None

        except ET.ParseError as e:
            logger.error(f"[{self.indexer_name}] XML parse error: {e}")
            return None

    @_retry_on_network_error()
    def _execute_request_with_retry(
        self,
        params: Dict[str, Any],
        timeout: int
    ) -> bytes:
        """Execute HTTP request with retry logic"""
        response = requests.get(self.base_url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.content

    def search(
        self,
        query: str,
        categories: Optional[List[int]] = None,
        limit: int = 100
    ) -> List[NewznabResult]:
        """
        Search indexer for NZBs

        Args:
            query: Search query string
            categories: Category IDs to search (default: all audio categories)
            limit: Maximum results to return

        Returns:
            List of search results
        """
        if categories is None:
            categories = [self.CATEGORY_AUDIO]

        params = {
            "t": "search",
            "q": query,
            "cat": ",".join(map(str, categories)),
            "limit": limit,
            "extended": 1  # Extended attributes
        }

        root = self._make_request(params)

        if root is None:
            return []

        return self._parse_results(root)

    def search_music(
        self,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        limit: int = 100
    ) -> List[NewznabResult]:
        """
        Search for music by artist and/or album

        Args:
            artist: Artist name
            album: Album title
            limit: Maximum results to return

        Returns:
            List of search results
        """
        # Build query string
        query_parts = []
        if artist:
            query_parts.append(artist)
        if album:
            query_parts.append(album)

        if not query_parts:
            return []

        query = " ".join(query_parts)

        # Use configured categories (default: MP3 and lossless)
        return self.search(query, self.categories, limit)

    def _parse_results(self, root: ET.Element) -> List[NewznabResult]:
        """
        Parse XML response into NewznabResult objects

        Args:
            root: XML root element

        Returns:
            List of parsed results
        """
        results = []

        for item in root.findall(".//item"):
            try:
                # Extract basic fields
                data = {
                    "title": item.findtext("title", ""),
                    "guid": item.findtext("guid", ""),
                    "link": item.findtext("link", ""),
                    "comments": item.findtext("comments", ""),
                    "pubDate": item.findtext("pubDate", ""),
                    "category": item.findtext("category", ""),
                    "size": 0,
                    "grabs": 0
                }

                # Extract newznab attributes
                for attr in item.findall(".//{http://www.newznab.com/DTD/2010/feeds/attributes/}attr"):
                    name = attr.get("name")
                    value = attr.get("value")

                    if name == "size":
                        data["size"] = int(value)
                    elif name == "grabs":
                        data["grabs"] = int(value)

                # Also check enclosure for size
                enclosure = item.find("enclosure")
                if enclosure is not None and not data["size"]:
                    length = enclosure.get("length")
                    if length:
                        data["size"] = int(length)

                result = NewznabResult(data, self.indexer_name)
                results.append(result)

            except Exception as e:
                logger.warning(f"[{self.indexer_name}] Failed to parse result: {e}")
                continue

        logger.info(f"[{self.indexer_name}] Found {len(results)} results")
        return results

    def test_connection(self) -> bool:
        """
        Test connection to indexer

        Returns:
            True if connection successful, False otherwise
        """
        params = {"t": "caps"}
        root = self._make_request(params)

        if root is not None:
            logger.info(f"[{self.indexer_name}] Connection test successful")
            return True

        logger.error(f"[{self.indexer_name}] Connection test failed")
        return False


class IndexerAggregator:
    """
    Aggregates results from multiple Newznab indexers

    Handles multi-indexer search, deduplication, and quality-based ranking.
    """

    def __init__(self, clients: List[NewznabClient]):
        """
        Initialize aggregator

        Args:
            clients: List of configured NewznabClient instances
        """
        self.clients = clients

    def search(
        self,
        query: str,
        categories: Optional[List[int]] = None,
        limit_per_indexer: int = 50
    ) -> List[NewznabResult]:
        """
        Search all indexers and aggregate results

        Args:
            query: Search query
            categories: Category IDs
            limit_per_indexer: Max results per indexer

        Returns:
            Deduplicated and ranked results
        """
        all_results = []

        # Search each indexer
        for client in self.clients:
            try:
                results = client.search(query, categories, limit_per_indexer)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"[{client.indexer_name}] Search failed: {e}")
                continue

        # Deduplicate by GUID
        deduplicated = self._deduplicate(all_results)

        # Sort by quality score (descending) and grabs (descending)
        ranked = sorted(
            deduplicated,
            key=lambda r: (r.quality_score, r.grabs),
            reverse=True
        )

        logger.info(f"[Aggregator] Total results: {len(all_results)}, after deduplication: {len(deduplicated)}")
        return ranked

    def search_music(
        self,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        limit_per_indexer: int = 50
    ) -> List[NewznabResult]:
        """
        Search for music across all indexers

        Args:
            artist: Artist name
            album: Album title
            limit_per_indexer: Max results per indexer

        Returns:
            Deduplicated and ranked results
        """
        all_results = []

        for client in self.clients:
            try:
                results = client.search_music(artist, album, limit_per_indexer)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"[{client.indexer_name}] Music search failed: {e}")
                continue

        deduplicated = self._deduplicate(all_results)
        ranked = sorted(
            deduplicated,
            key=lambda r: (r.quality_score, r.grabs),
            reverse=True
        )

        return ranked

    def _deduplicate(self, results: List[NewznabResult]) -> List[NewznabResult]:
        """
        Deduplicate results by GUID, keeping highest quality

        Args:
            results: List of results from all indexers

        Returns:
            Deduplicated list
        """
        seen_guids = {}

        for result in results:
            if not result.guid:
                continue

            if result.guid not in seen_guids:
                seen_guids[result.guid] = result
            else:
                # Keep result with higher quality score
                existing = seen_guids[result.guid]
                if result.quality_score > existing.quality_score:
                    seen_guids[result.guid] = result

        return list(seen_guids.values())


# Factory functions
def create_newznab_client(base_url: str, api_key: str, indexer_name: str, categories: Optional[List[int]] = None) -> NewznabClient:
    """
    Create Newznab client instance

    Args:
        base_url: Indexer API URL
        api_key: Decrypted API key
        indexer_name: Display name
        categories: List of Newznab category codes (default: [3010, 3040])

    Returns:
        NewznabClient instance
    """
    return NewznabClient(base_url, api_key, indexer_name, categories)


def create_aggregator(clients: List[NewznabClient]) -> IndexerAggregator:
    """
    Create indexer aggregator

    Args:
        clients: List of Newznab clients

    Returns:
        IndexerAggregator instance
    """
    return IndexerAggregator(clients)
