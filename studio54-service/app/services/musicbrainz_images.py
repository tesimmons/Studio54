"""
MusicBrainz Image Fetcher Service
Fetch artist images and album art from MusicBrainz Cover Art Archive
"""
import logging
import httpx
from typing import Optional, Dict, Any
from urllib.parse import quote
import asyncio

logger = logging.getLogger(__name__)


class MusicBrainzImageFetcher:
    """
    Fetch images from MusicBrainz Cover Art Archive and Fanart.tv

    Uses MusicBrainz IDs for accurate matching
    """

    # API endpoints
    COVER_ART_ARCHIVE_URL = "https://coverartarchive.org"
    MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2"
    FANART_TV_URL = "https://webservice.fanart.tv/v3"

    # Rate limiting
    REQUEST_TIMEOUT = 10.0
    MAX_RETRIES = 3

    def __init__(self, fanart_api_key: Optional[str] = None):
        """
        Initialize image fetcher

        Args:
            fanart_api_key: Optional Fanart.tv API key for artist images
        """
        self.fanart_api_key = fanart_api_key
        self.headers = {
            "User-Agent": "Studio54/1.0 (https://github.com/tesimmons/MasterControl)"
        }

    async def fetch_album_art(self, musicbrainz_album_id: str) -> Optional[str]:
        """
        Fetch album art URL from Cover Art Archive

        Args:
            musicbrainz_album_id: MusicBrainz Release ID (UUID)

        Returns:
            URL to album art image or None
        """
        if not musicbrainz_album_id:
            return None

        try:
            url = f"{self.COVER_ART_ARCHIVE_URL}/release/{musicbrainz_album_id}"

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                response = await client.get(url, headers=self.headers)

                if response.status_code == 200:
                    data = response.json()

                    # Get front cover
                    for image in data.get('images', []):
                        if image.get('front', False):
                            # Prefer large size
                            thumbnails = image.get('thumbnails', {})
                            if 'large' in thumbnails:
                                logger.info(f"Found album art for {musicbrainz_album_id}")
                                return thumbnails['large']
                            elif 'small' in thumbnails:
                                return thumbnails['small']
                            else:
                                return image.get('image')

                    # Fallback to first image
                    if len(data.get('images', [])) > 0:
                        first_image = data['images'][0]
                        thumbnails = first_image.get('thumbnails', {})
                        return thumbnails.get('large') or thumbnails.get('small') or first_image.get('image')

                elif response.status_code == 404:
                    logger.debug(f"No album art found for {musicbrainz_album_id}")
                else:
                    logger.warning(f"Cover Art Archive returned {response.status_code} for {musicbrainz_album_id}")

        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching album art for {musicbrainz_album_id}")
        except Exception as e:
            logger.error(f"Error fetching album art for {musicbrainz_album_id}: {e}")

        return None

    async def fetch_artist_image(self, musicbrainz_artist_id: str) -> Optional[str]:
        """
        Fetch artist image from Fanart.tv or fallback to MusicBrainz

        Args:
            musicbrainz_artist_id: MusicBrainz Artist ID (UUID)

        Returns:
            URL to artist image or None
        """
        if not musicbrainz_artist_id:
            return None

        # Try Fanart.tv first (higher quality images)
        if self.fanart_api_key:
            fanart_url = await self._fetch_from_fanart_tv(musicbrainz_artist_id)
            if fanart_url:
                return fanart_url

        # Fallback to MusicBrainz artist image
        return await self._fetch_from_musicbrainz(musicbrainz_artist_id)

    async def _fetch_from_fanart_tv(self, artist_id: str) -> Optional[str]:
        """Fetch artist image from Fanart.tv"""
        try:
            url = f"{self.FANART_TV_URL}/music/{artist_id}"
            headers = {**self.headers, "api-key": self.fanart_api_key}

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()

                    # Priority: artistthumb > hdmusiclogo > artistbackground
                    for key in ['artistthumb', 'hdmusiclogo', 'artistbackground']:
                        if key in data and len(data[key]) > 0:
                            logger.info(f"Found artist image on Fanart.tv for {artist_id}")
                            return data[key][0].get('url')

        except Exception as e:
            logger.debug(f"Fanart.tv fetch failed for {artist_id}: {e}")

        return None

    async def _fetch_from_musicbrainz(self, artist_id: str) -> Optional[str]:
        """
        Fetch artist image from MusicBrainz artist relations

        Note: MusicBrainz doesn't host images directly, but has links to images
        Uses the MusicBrainz client to respect rate limiting and queue management
        """
        try:
            # Use the MusicBrainz client instead of direct HTTP call
            from app.services.musicbrainz_client import get_musicbrainz_client

            client = get_musicbrainz_client()

            # The client's _make_request is synchronous, so we need to run it in a thread pool
            # to avoid blocking the async event loop
            import asyncio
            import functools

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                functools.partial(
                    client._make_request,
                    f"artist/{artist_id}",
                    {"inc": "url-rels"}
                )
            )

            if data:
                # Look for image URLs in relations
                for relation in data.get('relations', []):
                    if relation.get('type') in ['image', 'logo', 'picture']:
                        url = relation.get('url', {}).get('resource')
                        if url:
                            logger.info(f"Found artist image on MusicBrainz for {artist_id}")
                            return url

                # Check for Wikidata/Wikipedia links (could fetch image from there)
                # This is a future enhancement

        except Exception as e:
            logger.debug(f"MusicBrainz image fetch failed for {artist_id}: {e}")

        return None

    def fetch_album_art_sync(self, musicbrainz_album_id: str) -> Optional[str]:
        """Synchronous wrapper for fetch_album_art"""
        try:
            return asyncio.run(self.fetch_album_art(musicbrainz_album_id))
        except Exception as e:
            logger.error(f"Error in sync fetch_album_art: {e}")
            return None

    def fetch_artist_image_sync(self, musicbrainz_artist_id: str) -> Optional[str]:
        """Synchronous wrapper for fetch_artist_image"""
        try:
            return asyncio.run(self.fetch_artist_image(musicbrainz_artist_id))
        except Exception as e:
            logger.error(f"Error in sync fetch_artist_image: {e}")
            return None

    async def fetch_batch_album_art(self, album_ids: list) -> Dict[str, Optional[str]]:
        """
        Fetch album art for multiple albums in parallel

        Args:
            album_ids: List of MusicBrainz album IDs

        Returns:
            Dict mapping album_id -> image_url
        """
        tasks = [self.fetch_album_art(album_id) for album_id in album_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            album_id: (url if not isinstance(url, Exception) else None)
            for album_id, url in zip(album_ids, results)
        }

    async def fetch_batch_artist_images(self, artist_ids: list) -> Dict[str, Optional[str]]:
        """
        Fetch artist images for multiple artists in parallel

        Args:
            artist_ids: List of MusicBrainz artist IDs

        Returns:
            Dict mapping artist_id -> image_url
        """
        tasks = [self.fetch_artist_image(artist_id) for artist_id in artist_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            artist_id: (url if not isinstance(url, Exception) else None)
            for artist_id, url in zip(artist_ids, results)
        }


# Convenience functions
def fetch_album_art(musicbrainz_album_id: str, fanart_api_key: Optional[str] = None) -> Optional[str]:
    """
    Fetch album art URL (synchronous)

    Args:
        musicbrainz_album_id: MusicBrainz Release ID
        fanart_api_key: Optional Fanart.tv API key

    Returns:
        Image URL or None
    """
    fetcher = MusicBrainzImageFetcher(fanart_api_key=fanart_api_key)
    return fetcher.fetch_album_art_sync(musicbrainz_album_id)


def fetch_artist_image(musicbrainz_artist_id: str, fanart_api_key: Optional[str] = None) -> Optional[str]:
    """
    Fetch artist image URL (synchronous)

    Args:
        musicbrainz_artist_id: MusicBrainz Artist ID
        fanart_api_key: Optional Fanart.tv API key

    Returns:
        Image URL or None
    """
    fetcher = MusicBrainzImageFetcher(fanart_api_key=fanart_api_key)
    return fetcher.fetch_artist_image_sync(musicbrainz_artist_id)
