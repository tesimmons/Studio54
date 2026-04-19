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

    # Subjects to skip — too generic to be useful as a genre label
    _SKIP_SUBJECTS = {
        'fiction', 'nonfiction', 'non-fiction', 'audiobook', 'audiobooks',
        'large type books', 'large print', 'accessible book', 'open library',
        'protected daisy', 'in library', 'readable', 'borrowable', 'overlay',
        'overdrive', 'open syllabus project', 'internet archive',
    }

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


    def fetch_book_genre(self, title: str, author_name: Optional[str] = None) -> Optional[str]:
        """
        Search OpenLibrary for a book and return its most specific subject as a genre string.

        Uses the `subject` field from the search index (a list of subject strings
        already cleaned and sorted by OpenLibrary). Returns the first meaningful
        subject after filtering out generic/meta subjects.

        Args:
            title: Book title
            author_name: Optional author name to narrow results

        Returns:
            Genre string (e.g. "Science Fiction", "Fantasy") or None
        """
        try:
            params: dict = {
                'title': title,
                'fields': 'title,author_name,subject',
                'limit': 5,
            }
            if author_name:
                params['author'] = author_name

            resp = self.session.get(self.SEARCH_URL, params=params, timeout=10)
            resp.raise_for_status()
            docs = resp.json().get('docs', [])

            for doc in docs:
                subjects = doc.get('subject') or []
                for subj in subjects:
                    normalized = subj.lower().strip()
                    if normalized in self._SKIP_SUBJECTS:
                        continue
                    # Skip overly long / meta subjects
                    if len(subj) > 60:
                        continue
                    logger.info(f"[OpenLibrary] Genre for '{title}': {subj}")
                    return subj

            # Retry with short title if no results
            for sep in (' - ', ':'):
                if sep in title:
                    short = title.split(sep)[0].strip()
                    result = self.fetch_book_genre(short, author_name)
                    if result:
                        return result
                    break

            return None

        except Exception as e:
            logger.warning(f"[OpenLibrary] Failed to fetch genre for '{title}': {e}")
            return None


    def fetch_book_description(self, title: str, author_name: Optional[str] = None) -> Optional[str]:
        """
        Search OpenLibrary for a book and return its description/synopsis.

        Two-step: search.json to find the work key, then /works/{key}.json
        to retrieve the description field (which may be a plain string or a
        {"type": "/type/text", "value": "..."} dict).

        Args:
            title: Book title
            author_name: Optional author name to narrow results

        Returns:
            Description string (up to ~2000 chars) or None
        """
        try:
            params: dict = {
                'title': title,
                'fields': 'title,author_name,key',
                'limit': 5,
            }
            if author_name:
                params['author'] = author_name

            resp = self.session.get(self.SEARCH_URL, params=params, timeout=10)
            resp.raise_for_status()
            docs = resp.json().get('docs', [])

            work_key = None
            for doc in docs:
                work_key = doc.get('key')
                if work_key:
                    break

            if not work_key:
                # Retry with subtitle stripped
                for sep in (' - ', ':'):
                    if sep in title:
                        short = title.split(sep)[0].strip()
                        result = self.fetch_book_description(short, author_name)
                        if result:
                            return result
                        break
                return None

            works_url = f"https://openlibrary.org{work_key}.json"
            wresp = self.session.get(works_url, timeout=10)
            wresp.raise_for_status()
            works_data = wresp.json()

            raw_desc = works_data.get('description')
            if not raw_desc:
                return None

            # Description can be a plain string or {"type": ..., "value": "..."}
            if isinstance(raw_desc, dict):
                text = raw_desc.get('value') or ''
            else:
                text = str(raw_desc)

            text = text.strip()
            if not text:
                return None

            # Trim to a reasonable dust-jacket length
            if len(text) > 2000:
                text = text[:1997] + '...'

            logger.info(f"[OpenLibrary] Description for '{title}': {len(text)} chars")
            return text

        except Exception as e:
            logger.warning(f"[OpenLibrary] Failed to fetch description for '{title}': {e}")
            return None


_service: Optional[OpenLibraryService] = None


def get_openlibrary_service() -> OpenLibraryService:
    global _service
    if _service is None:
        _service = OpenLibraryService()
    return _service
