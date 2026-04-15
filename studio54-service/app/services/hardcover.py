"""
Hardcover API Service
Provides author bios, author images, and book cover art via the Hardcover GraphQL API.
Used as a fallback when MusicBrainz, Fanart.tv, OpenLibrary, and Wikipedia don't have data.

API documentation: https://hardcover.app/account/api
GraphQL endpoint: https://api.hardcover.app/v1/graphql
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

HARDCOVER_GQL_URL = "https://api.hardcover.app/v1/graphql"


class HardcoverService:
    """GraphQL client for the Hardcover book/author database."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Studio54/1.0 (Audiobook Management System)",
        })

    def _gql(self, query: str, variables: dict) -> Optional[dict]:
        """Execute a GraphQL query and return the `data` dict, or None on failure."""
        try:
            resp = self.session.post(
                HARDCOVER_GQL_URL,
                json={"query": query, "variables": variables},
                timeout=15,
            )
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body:
                for err in body["errors"]:
                    logger.warning(f"[Hardcover] GraphQL error: {err.get('message')}")
            return body.get("data")
        except Exception as e:
            logger.warning(f"[Hardcover] Request failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Author lookups
    # ------------------------------------------------------------------

    def _search_author_id(self, name: str) -> Optional[int]:
        """Use the Hardcover search endpoint to find an author ID by name."""
        data = self._gql(
            "query Search($q: String!) { search(query: $q, query_type: \"Author\") { results } }",
            {"q": name},
        )
        if not data:
            return None
        hits = (data.get("search") or {}).get("results", {}).get("hits") or []
        name_lower = name.lower()
        for hit in hits:
            doc = hit.get("document") or {}
            author_id = doc.get("id")
            author_name = (doc.get("name") or "").lower()
            if author_id and author_name == name_lower:
                return int(author_id)
        # Accept first result if name is close enough
        if hits:
            doc = hits[0].get("document") or {}
            if doc.get("id"):
                return int(doc["id"])
        return None

    def find_author(self, name: str) -> Optional[dict]:
        """
        Search for an author by name. Returns the best match dict with
        keys: id, name, bio, image_url — or None.

        Uses the search endpoint (not _ilike which is blocked by Hardcover)
        followed by a pk lookup for full details.
        """
        author_id = self._search_author_id(name)
        if author_id is None:
            return None

        data = self._gql(
            "query ByPk($id: Int!) { authors_by_pk(id: $id) { id name bio image { url } } }",
            {"id": author_id},
        )
        if not data:
            return None
        raw = data.get("authors_by_pk")
        if not raw:
            return None
        return self._normalise_author(raw)

    def _normalise_author(self, raw: dict) -> dict:
        image_url = None
        img = raw.get("image")
        if isinstance(img, dict):
            image_url = img.get("url")
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "bio": raw.get("bio") or None,
            "image_url": image_url,
        }

    def fetch_author_bio(self, name: str) -> Optional[str]:
        """Return a biography string for the given author, or None."""
        author = self.find_author(name)
        if author and author.get("bio"):
            bio = author["bio"].strip()
            if len(bio) >= 50:
                logger.info(f"[Hardcover] Found bio for '{name}' ({len(bio)} chars)")
                return bio
        return None

    def fetch_author_image_url(self, name: str) -> Optional[str]:
        """Return a direct image URL for the given author, or None."""
        author = self.find_author(name)
        if author and author.get("image_url"):
            logger.info(f"[Hardcover] Found author image for '{name}': {author['image_url']}")
            return author["image_url"]
        return None

    # ------------------------------------------------------------------
    # Book lookups
    # ------------------------------------------------------------------

    def _search_book_ids(self, title: str) -> list:
        """Use the Hardcover search endpoint to find book IDs by title."""
        data = self._gql(
            "query Search($q: String!) { search(query: $q, query_type: \"Book\") { results } }",
            {"q": title},
        )
        if not data:
            return []
        hits = (data.get("search") or {}).get("results", {}).get("hits") or []
        ids = []
        for hit in hits:
            doc = hit.get("document") or {}
            book_id = doc.get("id")
            if book_id:
                ids.append({"id": int(book_id), "title": doc.get("title", ""), "author_names": doc.get("author_names") or []})
        return ids

    def find_book(self, title: str, author_name: Optional[str] = None) -> Optional[dict]:
        """
        Search for a book by title (and optionally author). Returns the best
        match dict with keys: id, title, description, image_url — or None.

        Uses the search endpoint (not _ilike which is blocked by Hardcover)
        followed by a pk lookup for full details.
        """
        candidates = self._search_book_ids(title)

        if not candidates:
            # Try shortened title (strip subtitle)
            short_title = title.split(" - ")[0].split(":")[0].strip()
            if short_title != title:
                candidates = self._search_book_ids(short_title)

        if not candidates:
            return None

        # Prefer a match where author_name appears in the book's author list
        chosen_id = None
        if author_name:
            author_lower = author_name.lower()
            for c in candidates:
                if any(author_lower in (an or "").lower() for an in c["author_names"]):
                    chosen_id = c["id"]
                    break

        if chosen_id is None:
            chosen_id = candidates[0]["id"]

        data = self._gql(
            "query ByPk($id: Int!) { books_by_pk(id: $id) { id title description image { url } contributions { author { name } } } }",
            {"id": chosen_id},
        )
        if not data:
            return None
        raw = data.get("books_by_pk")
        if not raw:
            return None
        return self._normalise_book(raw)

    def _normalise_book(self, raw: dict) -> dict:
        image_url = None
        img = raw.get("image")
        if isinstance(img, dict):
            image_url = img.get("url")
        return {
            "id": raw.get("id"),
            "title": raw.get("title"),
            "description": raw.get("description") or None,
            "image_url": image_url,
        }

    def fetch_book_cover_url(self, title: str, author_name: Optional[str] = None) -> Optional[str]:
        """Return a direct cover image URL for the given book, or None."""
        book = self.find_book(title, author_name)
        if book and book.get("image_url"):
            logger.info(f"[Hardcover] Found cover for '{title}': {book['image_url']}")
            return book["image_url"]
        return None


# ---------------------------------------------------------------------------
# Singleton factory — reads key from Redis first, then env var
# ---------------------------------------------------------------------------

_instance: Optional[HardcoverService] = None


def get_hardcover_service() -> Optional[HardcoverService]:
    """
    Return a HardcoverService if an API key is configured, else None.
    Key lookup order: Redis → HARDCOVER_API_KEY env var.
    """
    global _instance

    api_key = _load_api_key()
    if not api_key:
        return None

    # Rebuild if key changed
    if _instance is None or _instance.api_key != api_key:
        _instance = HardcoverService(api_key)

    return _instance


def _load_api_key() -> Optional[str]:
    """Load the Hardcover API key from Redis or environment."""
    import os
    try:
        import redis as redis_lib
        from app.config import settings
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        key = r.get("studio54:settings:hardcover_api_key")
        if key:
            return key
    except Exception:
        pass
    return os.getenv("HARDCOVER_API_KEY") or None


def reset_hardcover_service():
    """Force singleton rebuild on next call (e.g. after key update)."""
    global _instance
    _instance = None
