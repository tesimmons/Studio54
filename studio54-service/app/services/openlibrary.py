"""
OpenLibrary cover art service.
Used as a fallback for audiobooks that don't have MusicBrainz IDs.
"""
import logging
import requests
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class OpenLibraryService:
    SEARCH_URL = "https://openlibrary.org/search.json"
    COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Studio54/1.0 (Audiobook Management System; mailto:admin@studio54.local)'
        })

    def _search(self, title: str, author_name: Optional[str]) -> Optional[str]:
        """Run a single OpenLibrary search and return cover URL or None."""
        params: dict = {
            'title': title,
            'fields': 'title,author_name,cover_i',
            'limit': 5,
        }
        if author_name:
            params['author'] = author_name

        resp = self.session.get(self.SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        docs = resp.json().get('docs', [])

        for doc in docs:
            cover_id = doc.get('cover_i')
            if cover_id:
                url = self.COVER_URL.format(cover_id=cover_id)
                logger.info(f"[OpenLibrary] Found cover for '{title}': {url}")
                return url
        return None

    def fetch_book_cover_url(self, title: str, author_name: Optional[str] = None) -> Optional[str]:
        """
        Search OpenLibrary for a book and return the cover image URL if found.

        Tries the full title first, then strips common subtitle patterns
        (everything after ' - ' or ':') and retries if the first attempt
        returns no results. This handles cases where audiobook titles have
        appended subtitles that OpenLibrary doesn't index.

        Args:
            title: Book title to search for
            author_name: Optional author name to narrow results

        Returns:
            Direct cover image URL (large size) or None
        """
        try:
            # First try: full title as stored
            url = self._search(title, author_name)
            if url:
                return url

            # Second try: strip subtitle after ' - '
            if ' - ' in title:
                short_title = title.split(' - ')[0].strip()
                logger.debug(f"[OpenLibrary] Retrying with short title: '{short_title}'")
                url = self._search(short_title, author_name)
                if url:
                    return url

            # Third try: strip after ':'
            if ':' in title:
                short_title = title.split(':')[0].strip()
                logger.debug(f"[OpenLibrary] Retrying with colon-stripped title: '{short_title}'")
                url = self._search(short_title, author_name)
                if url:
                    return url

            logger.debug(f"[OpenLibrary] No cover found for '{title}' by '{author_name}'")
            return None

        except Exception as e:
            logger.warning(f"[OpenLibrary] Failed to fetch cover for '{title}': {e}")
            return None


_service: Optional[OpenLibraryService] = None


def get_openlibrary_service() -> OpenLibraryService:
    global _service
    if _service is None:
        _service = OpenLibraryService()
    return _service
