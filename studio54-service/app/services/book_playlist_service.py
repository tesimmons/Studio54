"""
Book Playlist Service - Creates series-ordered chapter playlists for audiobooks.

Queries the local MusicBrainz DB for authoritative series ordering, falls back
to book.series_position for unmatched entries.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models.series import Series
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.book_playlist import BookPlaylist, BookPlaylistChapter

logger = logging.getLogger(__name__)


def create_or_update_series_playlist(db: Session, series_id) -> Optional[BookPlaylist]:
    """
    Create or update a book playlist for a series.

    1. Loads the series with books and chapters
    2. Queries local MB DB for authoritative book ordering (if series has MB ID)
    3. Falls back to series_position for unmatched books
    4. Collects chapters with has_file=True ordered by chapter_number
    5. Upserts the BookPlaylist
    """
    series = db.query(Series).options(
        joinedload(Series.books).joinedload(Book.chapters)
    ).filter(Series.id == series_id).first()

    if not series:
        logger.error(f"Series {series_id} not found")
        return None

    books = list(series.books)
    if not books:
        logger.info(f"Series '{series.name}' has no books, skipping playlist creation")
        return None

    # Determine book ordering
    ordered_books = _get_ordered_books(series, books)

    # Collect chapters with files, ordered by chapter_number
    playlist_entries = []
    position = 1
    for book_pos, book in ordered_books:
        chapters = sorted(
            [ch for ch in book.chapters if ch.has_file],
            key=lambda ch: (ch.disc_number or 1, ch.chapter_number or 0)
        )
        for chapter in chapters:
            playlist_entries.append({
                "chapter_id": chapter.id,
                "position": position,
                "book_position": book_pos,
            })
            position += 1

    if not playlist_entries:
        logger.info(f"Series '{series.name}' has no chapters with files, skipping playlist")
        return None

    # Upsert playlist
    playlist = db.query(BookPlaylist).filter(BookPlaylist.series_id == series_id).first()
    if playlist:
        # Delete old entries and update
        db.query(BookPlaylistChapter).filter(
            BookPlaylistChapter.playlist_id == playlist.id
        ).delete()
        playlist.name = series.name
        playlist.description = f"All chapters from the {series.name} series in order"
        playlist.updated_at = datetime.now(timezone.utc)
    else:
        playlist = BookPlaylist(
            series_id=series.id,
            name=series.name,
            description=f"All chapters from the {series.name} series in order",
        )
        db.add(playlist)
        db.flush()  # Get the ID

    # Insert new entries
    for entry in playlist_entries:
        db.add(BookPlaylistChapter(
            playlist_id=playlist.id,
            chapter_id=entry["chapter_id"],
            position=entry["position"],
            book_position=entry["book_position"],
        ))

    db.flush()
    logger.info(
        f"Series playlist '{series.name}': {len(playlist_entries)} chapters "
        f"from {len(ordered_books)} books"
    )
    return playlist


def _get_ordered_books(series: Series, books: list) -> list:
    """
    Return list of (book_position, book) tuples in correct series order.

    Uses MusicBrainz local DB for authoritative ordering when available,
    falls back to book.series_position.
    """
    # Try MusicBrainz local DB ordering
    if series.musicbrainz_series_id:
        try:
            from app.services.musicbrainz_local import get_musicbrainz_local_db
            local_db = get_musicbrainz_local_db()
            if local_db:
                mb_order = local_db.get_series_release_group_order(series.musicbrainz_series_id)
                if mb_order:
                    return _match_mb_order_to_books(mb_order, books)
        except Exception as e:
            logger.warning(f"MB local DB series lookup failed: {e}")

    # Fallback: use series_position from our DB
    return _order_by_series_position(books)


def _match_mb_order_to_books(mb_order: list, books: list) -> list:
    """Match MB release group order to our books, append unmatched at end."""
    # Build lookup by musicbrainz_id (release_group MBID)
    book_by_mbid = {}
    for book in books:
        if book.musicbrainz_id:
            book_by_mbid[book.musicbrainz_id] = book

    ordered = []
    matched_ids = set()

    for mb_entry in mb_order:
        rg_mbid = mb_entry["release_group_mbid"]
        if rg_mbid in book_by_mbid:
            book = book_by_mbid[rg_mbid]
            ordered.append((mb_entry["series_position"], book))
            matched_ids.add(book.id)

    # Append unmatched books at the end, ordered by series_position
    unmatched = [b for b in books if b.id not in matched_ids]
    unmatched.sort(key=lambda b: (b.series_position or 9999, b.title))
    next_pos = (ordered[-1][0] + 1) if ordered else 1
    for book in unmatched:
        ordered.append((next_pos, book))
        next_pos += 1

    return ordered


def _order_by_series_position(books: list) -> list:
    """Order books by series_position, nulls last."""
    sorted_books = sorted(books, key=lambda b: (b.series_position or 9999, b.title))
    return [(idx + 1, book) for idx, book in enumerate(sorted_books)]
