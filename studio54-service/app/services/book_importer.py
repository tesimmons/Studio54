"""
Book Importer Service
Imports individual release groups as Book + Chapter records from MusicBrainz.

Mirrors album_importer.py but creates Book/Chapter records for audiobook content.
"""

import logging
from datetime import date
from typing import Optional, List, Dict, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.book import Book, BookStatus
from app.models.chapter import Chapter
from app.services.musicbrainz_client import MusicBrainzClient

logger = logging.getLogger(__name__)


def _parse_mb_date(date_str: str) -> Optional[date]:
    """Parse a MusicBrainz date string (YYYY, YYYY-MM, or YYYY-MM-DD) into a date object."""
    if not date_str:
        return None
    try:
        parts = date_str.split("-")
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        elif len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        elif len(parts) == 1:
            return date(int(parts[0]), 1, 1)
    except (ValueError, IndexError):
        pass
    return None


def import_release_group_as_book(
    db: Session,
    author_id: UUID,
    release_group_mbid: str,
    mb_client: MusicBrainzClient,
) -> Optional[Book]:
    """
    Import a single release group as a Book + Chapters from MusicBrainz.

    Mirrors album_importer.import_release_group() but creates Book/Chapter records.
    Sets monitored=False by default.

    Args:
        db: Database session
        author_id: Author UUID
        release_group_mbid: MusicBrainz release group MBID
        mb_client: MusicBrainz client instance

    Returns:
        The created Book, or None if it already exists or import fails.
    """
    # Skip if book with this musicbrainz_id already exists
    existing = db.query(Book).filter(Book.musicbrainz_id == release_group_mbid).first()
    if existing:
        # Backfill chapters if book has zero chapters
        existing_chapter_count = db.query(Chapter).filter(Chapter.book_id == existing.id).count()
        if existing_chapter_count == 0:
            chapters_added = _import_chapters_for_book(db, existing, release_group_mbid, mb_client)
            if chapters_added > 0:
                logger.info(f"Backfilled {chapters_added} chapters for existing book: {existing.title}")
        return None

    # Fetch release group metadata
    rg = mb_client.get_release_group(release_group_mbid)
    if not rg:
        logger.warning(f"Could not fetch release group {release_group_mbid}")
        return None

    # Create Book record
    secondary_types_list = rg.get("secondary-types", [])
    book = Book(
        author_id=author_id,
        title=rg.get("title", "Unknown Book"),
        musicbrainz_id=release_group_mbid,
        album_type=rg.get("primary-type", "Album"),
        secondary_types=",".join(secondary_types_list) if secondary_types_list else None,
        status=BookStatus.WANTED,
        monitored=False,  # Audiobooks default to unmonitored
    )

    # Parse release date
    book.release_date = _parse_mb_date(rg.get("first-release-date"))

    db.add(book)
    db.flush()  # Get book.id without committing

    # Import chapters
    chapters_added = _import_chapters_for_book(db, book, release_group_mbid, mb_client)

    logger.info(
        f"Imported audiobook '{book.title}' ({release_group_mbid}) "
        f"with {chapters_added} chapters for author {author_id}"
    )
    return book


def _import_chapters_for_book(
    db: Session,
    book: Book,
    release_group_mbid: str,
    mb_client: MusicBrainzClient,
) -> int:
    """
    Import chapters for a book from MusicBrainz.

    Selects the best release and creates Chapter records.

    Returns:
        Number of chapters added.
    """
    chapters_added = 0
    try:
        release = mb_client.select_best_release(release_group_mbid)
        if not release:
            return 0

        release_mbid = release.get("id")
        if release_mbid and not book.release_mbid:
            book.release_mbid = release_mbid

        media_list = release.get("media", [])
        for media in media_list:
            disc_number = media.get("position", 1)
            for track_data in media.get("tracks", []):
                recording = track_data.get("recording", {})
                recording_mbid = recording.get("id")

                if not recording_mbid:
                    continue

                # Check if chapter already exists for this book
                existing_chapter = db.query(Chapter).filter(
                    Chapter.musicbrainz_id == recording_mbid,
                    Chapter.book_id == book.id,
                ).first()

                if not existing_chapter:
                    chapter = Chapter(
                        book_id=book.id,
                        title=recording.get("title", track_data.get("title", "Unknown Chapter")),
                        musicbrainz_id=recording_mbid,
                        chapter_number=track_data.get("position", 0),
                        disc_number=disc_number,
                        duration_ms=recording.get("length"),
                        has_file=False,
                    )
                    db.add(chapter)
                    chapters_added += 1

        # Update book chapter_count
        total_release_tracks = sum(len(m.get("tracks", [])) for m in media_list)
        if total_release_tracks > 0 and (book.chapter_count or 0) < total_release_tracks:
            book.chapter_count = total_release_tracks

    except Exception as e:
        logger.warning(f"Failed to fetch chapters for release group {release_group_mbid}: {e}")

    return chapters_added


def bulk_import_release_groups_as_books(
    db: Session,
    author_rg_pairs: List[Tuple[UUID, str]],
    mb_client: MusicBrainzClient,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Import multiple release groups as books, batched by author.

    Args:
        db: Database session
        author_rg_pairs: List of (author_id, release_group_mbid) tuples
        mb_client: MusicBrainz client instance
        progress_callback: Optional callable(imported, total, book_title)

    Returns:
        Dict with counts: books_imported, chapters_created, skipped, failed
    """
    stats = {
        "books_imported": 0,
        "chapters_created": 0,
        "skipped": 0,
        "failed": 0,
    }

    total = len(author_rg_pairs)
    for idx, (author_id, rg_mbid) in enumerate(author_rg_pairs):
        try:
            book = import_release_group_as_book(db, author_id, rg_mbid, mb_client)
            if book:
                stats["books_imported"] += 1
                chapter_count = db.query(Chapter).filter(Chapter.book_id == book.id).count()
                stats["chapters_created"] += chapter_count
                db.commit()

                if progress_callback:
                    progress_callback(idx + 1, total, book.title)
            else:
                stats["skipped"] += 1

        except Exception as e:
            logger.error(f"Failed to import release group as book {rg_mbid}: {e}")
            stats["failed"] += 1
            db.rollback()

    return stats
