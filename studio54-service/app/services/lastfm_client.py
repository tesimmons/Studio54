"""
Last.fm API Client

Simple HTTP client for the Last.fm API.
Requires LASTFM_API_KEY environment variable.
"""
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"


def get_lastfm_api_key() -> Optional[str]:
    return os.getenv("LASTFM_API_KEY")


async def get_artist_top_tracks(
    artist_name: str,
    limit: int = 10,
) -> list[dict]:
    """
    Fetch top tracks for an artist from Last.fm.

    Returns list of dicts with keys: name, playcount, listeners, mbid
    """
    api_key = get_lastfm_api_key()
    if not api_key:
        return []

    params = {
        "method": "artist.getTopTracks",
        "artist": artist_name,
        "api_key": api_key,
        "format": "json",
        "limit": limit,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(LASTFM_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        top_tracks = data.get("toptracks", {}).get("track", [])

        results = []
        for track in top_tracks:
            results.append({
                "name": track.get("name", ""),
                "playcount": int(track.get("playcount", 0)),
                "listeners": int(track.get("listeners", 0)),
                "mbid": track.get("mbid") or None,
            })

        return results

    except httpx.HTTPStatusError as e:
        logger.warning(f"Last.fm API error for '{artist_name}': {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"Last.fm request failed for '{artist_name}': {e}")
        return []
