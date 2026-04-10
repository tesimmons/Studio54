"""
Wikipedia Biography Service
Fetches artist biographies from Wikipedia API
"""
import logging
import requests
from typing import Optional
from urllib.parse import quote
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class WikipediaService:
    """Service for fetching artist biographies from Wikipedia"""

    BASE_URL = "https://en.wikipedia.org/api/rest_v1"
    SEARCH_URL = "https://en.wikipedia.org/w/api.php"
    MIN_BIO_LENGTH = 50

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Studio54/1.0 (Music Management System; mailto:admin@studio54.local)'
        })

    def _title_similarity(self, artist_name: str, page_title: str) -> float:
        """Check how similar the artist name is to the Wikipedia page title"""
        a = artist_name.lower().strip()
        b = page_title.lower().strip()
        # Exact match
        if a == b:
            return 1.0
        # Page title starts with artist name (e.g. "Pink Floyd (band)")
        if b.startswith(a):
            return 0.95
        # Artist name contained in page title
        if a in b:
            return 0.85
        return SequenceMatcher(None, a, b).ratio()

    def _is_disambiguation_content(self, extract: str) -> bool:
        """Check if content is a surname/disambiguation list rather than a real biography"""
        if not extract:
            return True
        first_sentence = extract.split('.')[0].lower() if extract else ''
        reject_patterns = [
            'is a surname',
            'is a given name',
            'is a name',
            'may refer to',
            'can refer to',
            'commonly refers to',
            'is a list of',
            'notable people with',
        ]
        return any(p in first_sentence for p in reject_patterns)

    def _is_author_related(self, description: str) -> bool:
        """Check if a Wikipedia page description indicates an author/writer"""
        if not description:
            return False
        desc_lower = description.lower()
        author_terms = [
            'author', 'writer', 'novelist', 'poet', 'playwright',
            'essayist', 'biographer', 'fiction', 'non-fiction', 'literary',
            'book', 'novel', 'literature', 'screenwriter', 'journalist',
            'storyteller', 'dramatist', 'short story', 'prose',
        ]
        return any(term in desc_lower for term in author_terms)

    def _is_music_related(self, description: str) -> bool:
        """Check if a Wikipedia page description indicates a music artist/band"""
        if not description:
            return False
        desc_lower = description.lower()
        music_terms = [
            'band', 'singer', 'musician', 'rapper', 'songwriter',
            'musical', 'hip hop', 'rock', 'pop', 'jazz', 'country',
            'artist', 'group', 'duo', 'trio', 'quartet', 'ensemble',
            'vocalist', 'composer', 'dj', 'mc ', 'emcee', 'producer',
            'orchestra', 'choir', 'album', 'record', 'music',
        ]
        return any(term in desc_lower for term in music_terms)

    def _try_direct_page(self, artist_name: str) -> Optional[str]:
        """Try fetching the Wikipedia page directly by title (most reliable)"""
        for title_variant in [artist_name, f"{artist_name} (band)", f"{artist_name} (musician)"]:
            try:
                encoded_title = quote(title_variant.replace(' ', '_'), safe='')
                summary_url = f"{self.BASE_URL}/page/summary/{encoded_title}"
                response = self.session.get(summary_url, timeout=10)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                data = response.json()

                # Check the page is about the right thing
                page_type = data.get('type', '')
                if page_type == 'disambiguation':
                    continue

                description = data.get('description', '')
                extract = data.get('extract', '')

                if not extract or len(extract) < self.MIN_BIO_LENGTH:
                    continue

                # Reject surname/disambiguation list pages
                if self._is_disambiguation_content(extract):
                    logger.debug(f"Skipping surname/disambiguation page for '{artist_name}': {data.get('title')}")
                    continue

                # For direct name match, accept if it's music-related
                if self._is_music_related(description) or self._is_music_related(extract):
                    logger.info(f"Direct page match for '{artist_name}': {data.get('title')} ({len(extract)} chars)")
                    return extract

            except requests.exceptions.RequestException:
                continue

        return None

    def _try_search(self, artist_name: str) -> Optional[str]:
        """Search Wikipedia and validate the top results"""
        search_params = {
            'action': 'query',
            'format': 'json',
            'list': 'search',
            'srsearch': f'"{artist_name}" band OR singer OR musician OR rapper',
            'srlimit': 5
        }

        try:
            search_response = self.session.get(self.SEARCH_URL, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            results = search_data.get('query', {}).get('search', [])
            if not results:
                return None

            for result in results:
                page_title = result.get('title', '')
                similarity = self._title_similarity(artist_name, page_title)

                # Skip results that don't look related to the artist name
                if similarity < 0.5:
                    continue

                # Fetch the page summary
                try:
                    encoded_title = quote(page_title.replace(' ', '_'), safe='')
                    summary_url = f"{self.BASE_URL}/page/summary/{encoded_title}"
                    summary_response = self.session.get(summary_url, timeout=10)
                    if summary_response.status_code == 404:
                        continue
                    summary_response.raise_for_status()
                    summary_data = summary_response.json()

                    if summary_data.get('type') == 'disambiguation':
                        continue

                    description = summary_data.get('description', '')
                    extract = summary_data.get('extract', '')

                    if not extract or len(extract) < self.MIN_BIO_LENGTH:
                        continue

                    # Reject surname/disambiguation list pages
                    if self._is_disambiguation_content(extract):
                        continue

                    # Must be music-related
                    if self._is_music_related(description) or self._is_music_related(extract):
                        logger.info(f"Search match for '{artist_name}': {page_title} (similarity={similarity:.2f}, {len(extract)} chars)")
                        return extract

                except requests.exceptions.RequestException:
                    continue

        except requests.exceptions.RequestException as e:
            logger.warning(f"Wikipedia search failed for {artist_name}: {e}")

        return None

    def _extract_thumbnail(self, data: dict) -> Optional[str]:
        """Extract the best available image URL from a Wikipedia summary response."""
        thumbnail = data.get('thumbnail') or {}
        original = data.get('originalimage') or {}
        return original.get('source') or thumbnail.get('source') or None

    def _is_person_page(self, description: str, extract: str) -> bool:
        """Check if a Wikipedia page describes a real person (any profession)."""
        if not description and not extract:
            return False
        text = (description + ' ' + extract[:300]).lower()
        person_terms = [
            'actor', 'actress', 'director', 'filmmaker', 'musician', 'singer',
            'author', 'writer', 'novelist', 'poet', 'playwright',
            'politician', 'president', 'senator', 'governor',
            'athlete', 'player', 'coach', 'executive', 'entrepreneur',
            'journalist', 'broadcaster', 'host', 'comedian', 'entertainer',
            'born', 'died', 'american', 'british', 'canadian', 'australian',
        ]
        return any(term in text for term in person_terms)

    def _try_direct_page_author(self, author_name: str) -> Optional[tuple]:
        """Try fetching the Wikipedia page directly by title for an author.

        For an exact name match, accepts any person page — audiobook narrators
        can be actors, politicians, athletes, etc., not just literary authors.
        The strict _is_author_related filter is reserved for search results.

        Returns:
            (extract, image_url) tuple or None
        """
        title_variants = [
            author_name,
            f"{author_name} (author)",
            f"{author_name} (writer)",
            f"{author_name} (actor)",
            f"{author_name} (filmmaker)",
        ]
        for title_variant in title_variants:
            try:
                encoded_title = quote(title_variant.replace(' ', '_'), safe='')
                summary_url = f"{self.BASE_URL}/page/summary/{encoded_title}"
                response = self.session.get(summary_url, timeout=10)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                data = response.json()

                page_type = data.get('type', '')
                if page_type == 'disambiguation':
                    continue

                description = data.get('description', '')
                extract = data.get('extract', '')

                if not extract or len(extract) < self.MIN_BIO_LENGTH:
                    continue

                if self._is_disambiguation_content(extract):
                    logger.debug(f"Skipping disambiguation page for '{author_name}': {data.get('title')}")
                    continue

                # For the exact name variant (first in list), accept any person page
                # For disambiguating variants like "(author)", still require relevance
                is_exact = (title_variant == author_name)
                if is_exact:
                    if self._is_person_page(description, extract):
                        logger.info(f"Direct page match for '{author_name}': {data.get('title')} ({len(extract)} chars)")
                        return extract, self._extract_thumbnail(data)
                else:
                    if self._is_author_related(description) or self._is_author_related(extract):
                        logger.info(f"Direct page match for '{author_name}' via variant '{title_variant}': {data.get('title')}")
                        return extract, self._extract_thumbnail(data)

            except requests.exceptions.RequestException:
                continue

        return None

    def _try_search_author(self, author_name: str) -> Optional[tuple]:
        """Search Wikipedia for an author and validate the top results.

        Returns:
            (extract, image_url) tuple or None
        """
        search_params = {
            'action': 'query',
            'format': 'json',
            'list': 'search',
            'srsearch': f'"{author_name}" author OR writer OR novelist OR poet',
            'srlimit': 5
        }

        try:
            search_response = self.session.get(self.SEARCH_URL, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            results = search_data.get('query', {}).get('search', [])
            if not results:
                return None

            for result in results:
                page_title = result.get('title', '')
                similarity = self._title_similarity(author_name, page_title)

                if similarity < 0.5:
                    continue

                try:
                    encoded_title = quote(page_title.replace(' ', '_'), safe='')
                    summary_url = f"{self.BASE_URL}/page/summary/{encoded_title}"
                    summary_response = self.session.get(summary_url, timeout=10)
                    if summary_response.status_code == 404:
                        continue
                    summary_response.raise_for_status()
                    summary_data = summary_response.json()

                    if summary_data.get('type') == 'disambiguation':
                        continue

                    description = summary_data.get('description', '')
                    extract = summary_data.get('extract', '')

                    if not extract or len(extract) < self.MIN_BIO_LENGTH:
                        continue

                    if self._is_disambiguation_content(extract):
                        continue

                    if self._is_author_related(description) or self._is_author_related(extract):
                        logger.info(f"Search match for author '{author_name}': {page_title} (similarity={similarity:.2f}, {len(extract)} chars)")
                        return extract, self._extract_thumbnail(summary_data)

                except requests.exceptions.RequestException:
                    continue

        except requests.exceptions.RequestException as e:
            logger.warning(f"Wikipedia author search failed for {author_name}: {e}")

        return None

    def fetch_author_page(self, author_name: str) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch author biography AND image URL from Wikipedia.

        Returns:
            (biography_text, image_url) — either or both may be None
        """
        try:
            # Phase 1: Direct page lookup with author variants
            result = self._try_direct_page_author(author_name)
            if result:
                return result  # (bio, image_url)

            # Phase 2: Search with author validation
            result = self._try_search_author(author_name)
            if result:
                return result

            # Phase 3: Fall back to music artist search (some authors are also musicians)
            bio = self.fetch_artist_biography(author_name)
            if bio:
                return bio, None

            logger.debug(f"No suitable Wikipedia page found for author '{author_name}'")
            return None, None

        except Exception as e:
            logger.error(f"Error fetching Wikipedia page for author {author_name}: {e}", exc_info=True)
            return None, None

    def fetch_author_biography(self, author_name: str) -> Optional[str]:
        """
        Fetch author biography from Wikipedia.

        Returns:
            Biography text or None if not found
        """
        bio, _ = self.fetch_author_page(author_name)
        return bio

    def fetch_author_image(self, author_name: str) -> Optional[str]:
        """
        Fetch author photo URL from Wikipedia.

        Returns:
            Image URL (originalimage or thumbnail) or None
        """
        _, image_url = self.fetch_author_page(author_name)
        return image_url

    def fetch_artist_biography(self, artist_name: str) -> Optional[str]:
        """
        Fetch artist biography from Wikipedia

        Uses a two-phase approach:
        1. Try direct page lookup by artist name (most reliable)
        2. Fall back to search with relevance validation

        Args:
            artist_name: Name of the artist

        Returns:
            Biography text or None if not found
        """
        try:
            # Phase 1: Direct page lookup
            bio = self._try_direct_page(artist_name)
            if bio:
                return bio

            # Phase 2: Search with validation
            bio = self._try_search(artist_name)
            if bio:
                return bio

            logger.debug(f"No suitable Wikipedia biography found for '{artist_name}'")
            return None

        except Exception as e:
            logger.error(f"Error fetching Wikipedia biography for {artist_name}: {e}", exc_info=True)
            return None


def get_wikipedia_service() -> WikipediaService:
    """Factory function to get WikipediaService instance"""
    return WikipediaService()
