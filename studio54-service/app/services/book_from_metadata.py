"""
Book From Metadata Service
Creates Book and Chapter records directly from library file metadata
when MusicBrainz data is unavailable.

For audiobook libraries (e.g. Audible/OpenAudible), files have rich metadata
(album, title, track number, artist, narrator, series) but no MusicBrainz IDs.
This service groups files by album tag, creates a Book for each group,
and creates Chapter records from individual files.
"""

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.models.book import Book, BookStatus
from app.models.chapter import Chapter
from app.models.library import LibraryFile

logger = logging.getLogger(__name__)


def _parse_primary_author(artist_str: str) -> str:
    """Extract the primary (first-listed) author from a multi-author string.

    Splits on common delimiters: ' & ', ' and ', ' with ', ' feat. ', ', '
    and returns the first name, stripped.

    Examples:
        "David Weber & Timothy Zahn" → "David Weber"
        "Brandon Sanderson" → "Brandon Sanderson"
        "Author One, Author Two" → "Author One"
    """
    if not artist_str:
        return artist_str
    for sep in [' & ', ' and ', ' with ', ' feat. ', ', ']:
        if sep in artist_str:
            return artist_str.split(sep, 1)[0].strip()
    return artist_str.strip()


def create_books_from_file_metadata(
    db: Session,
    author_id: UUID,
    library_path_id: UUID,
) -> Dict[str, int]:
    """
    Create Book and Chapter records from library file metadata for an author.

    Called when MusicBrainz sync yields no books for an author but library
    files exist with metadata. Groups files by album tag, creates a Book
    per album, and Chapter records for each file.

    Args:
        db: Database session
        author_id: Author UUID
        library_path_id: Library path UUID

    Returns:
        Stats dict: books_created, chapters_created, files_matched
    """
    from app.models.author import Author

    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        return {"books_created": 0, "chapters_created": 0, "files_matched": 0}

    # Check if author already has books (from MB sync or previous run)
    existing_book_count = db.query(Book).filter(Book.author_id == author_id).count()
    if existing_book_count > 0:
        logger.debug(f"Author {author.name} already has {existing_book_count} books, skipping metadata creation")
        return {"books_created": 0, "chapters_created": 0, "files_matched": 0}

    # Get library files for this author
    query = db.query(LibraryFile).filter(
        LibraryFile.library_path_id == library_path_id,
    )

    # Match by artist MBID or name (including primary-author extraction)
    if author.musicbrainz_id and not author.musicbrainz_id.startswith("local-"):
        query = query.filter(
            or_(
                LibraryFile.musicbrainz_artistid == author.musicbrainz_id,
                LibraryFile.artist.ilike(f"%{author.name}%"),
            )
        )
    else:
        query = query.filter(LibraryFile.artist.ilike(f"%{author.name}%"))

    library_files = query.all()

    # Also match files where primary author (first name before &/and/,) matches
    if not library_files:
        all_files = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id,
        ).all()
        library_files = [
            lf for lf in all_files
            if lf.artist and _parse_primary_author(lf.artist).lower() == author.name.lower()
        ]

    if not library_files:
        logger.info(f"No library files found for author {author.name}")
        return {"books_created": 0, "chapters_created": 0, "files_matched": 0}

    logger.info(f"Creating books from metadata: {len(library_files)} files for {author.name}")

    # Group files by album tag (each album = one book)
    files_by_album: Dict[str, List[LibraryFile]] = defaultdict(list)
    for lf in library_files:
        album_key = (lf.album or "").strip()
        if not album_key:
            # Use filename-derived book name for files without album tag
            album_key = _infer_book_title_from_path(lf.file_path)
        if album_key:
            files_by_album[album_key].append(lf)

    stats = {"books_created": 0, "chapters_created": 0, "files_matched": 0}

    for album_title, files in files_by_album.items():
        try:
            # Check if a book with this exact title already exists for this author
            existing = db.query(Book).filter(
                Book.author_id == author_id,
                Book.title == album_title,
            ).first()

            if existing:
                # Book exists - just match files to chapters
                chapters_matched = _match_files_to_existing_chapters(db, existing, files)
                stats["files_matched"] += chapters_matched
                continue

            # Create Book record with a synthetic musicbrainz_id
            synthetic_mbid = f"local-{uuid.uuid4()}"

            # Extract metadata from the first file for book-level info
            meta_json = files[0].metadata_json or {}

            # Store the full artist credit string if it differs from author name
            raw_artist = (files[0].artist or "").strip()
            credit = raw_artist if raw_artist and raw_artist.lower() != author.name.lower() else None

            book = Book(
                author_id=author_id,
                title=album_title,
                musicbrainz_id=synthetic_mbid,
                album_type="Album",
                secondary_types="Audiobook",
                status=BookStatus.DOWNLOADED,
                monitored=False,
                chapter_count=len(files),
                credit_name=credit,
            )

            # Set release date from file year if available
            for f in files:
                if f.year:
                    from datetime import date
                    try:
                        book.release_date = date(f.year, 1, 1)
                    except ValueError:
                        pass
                    break

            # Check for cover art in the book directory — store the actual file path
            first_file_path = files[0].file_path
            found_cover_path = None
            if first_file_path:
                book_dir = Path(first_file_path).parent
                for cover_name in ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png"):
                    candidate = book_dir / cover_name
                    if candidate.is_file():
                        found_cover_path = candidate
                        break

            db.add(book)
            db.flush()  # Get book.id

            # Copy found cover art into the book-art directory so it's served correctly
            if found_cover_path:
                try:
                    import shutil
                    art_dir = Path("/docker/studio54/book-art")
                    art_dir.mkdir(parents=True, exist_ok=True)
                    dest = art_dir / f"{book.id}{found_cover_path.suffix.lower()}"
                    shutil.copy2(str(found_cover_path), str(dest))
                    book.cover_art_url = str(dest)
                except Exception:
                    pass  # cover art is optional; endpoint will fall back to chapter scan

            # Create Chapter records from files
            # Sort files by disc_number then track_number then filename
            sorted_files = sorted(
                files,
                key=lambda f: (
                    f.disc_number or 1,
                    f.track_number or 9999,
                    f.file_name or "",
                ),
            )

            for idx, lf in enumerate(sorted_files, 1):
                chapter_title = lf.title or f"Chapter {idx}"
                chapter_number = lf.track_number or idx
                disc_number = lf.disc_number or 1
                duration_ms = (lf.duration_seconds * 1000) if lf.duration_seconds else None

                chapter = Chapter(
                    book_id=book.id,
                    title=chapter_title,
                    musicbrainz_id=None,  # No MB recording ID
                    chapter_number=chapter_number,
                    disc_number=disc_number,
                    duration_ms=duration_ms,
                    has_file=True,
                    file_path=lf.file_path,
                )
                db.add(chapter)
                stats["chapters_created"] += 1
                stats["files_matched"] += 1

            stats["books_created"] += 1
            logger.info(
                f"Created book '{album_title}' with {len(sorted_files)} chapters "
                f"for {author.name}"
            )

        except Exception as e:
            logger.error(f"Error creating book '{album_title}': {e}")
            db.rollback()
            continue

    db.commit()

    logger.info(
        f"Metadata book creation for {author.name}: "
        f"{stats['books_created']} books, {stats['chapters_created']} chapters, "
        f"{stats['files_matched']} files matched"
    )

    return stats


def _match_files_to_existing_chapters(
    db: Session, book: Book, files: List[LibraryFile]
) -> int:
    """Match files to existing chapters that don't have files yet."""
    chapters = db.query(Chapter).filter(
        Chapter.book_id == book.id,
        Chapter.has_file == False,
    ).all()

    if not chapters:
        return 0

    matched = 0
    chapter_by_number = {}
    for ch in chapters:
        if ch.chapter_number is not None:
            key = (ch.disc_number or 1, ch.chapter_number)
            chapter_by_number[key] = ch

    for lf in files:
        if lf.track_number is not None:
            key = (lf.disc_number or 1, lf.track_number)
            ch = chapter_by_number.get(key)
            if ch:
                ch.file_path = lf.file_path
                ch.has_file = True
                matched += 1

    return matched


def _infer_book_title_from_path(file_path: str) -> str:
    """Infer book title from file path when album tag is missing."""
    from pathlib import Path

    p = Path(file_path)
    # If file is in a subfolder, use the folder name as book title
    # e.g. /books/A Beautiful Friendship - Star Kingdom, Book 1/03 Chapter One.mp3
    # → "A Beautiful Friendship - Star Kingdom, Book 1"
    parent = p.parent.name
    if parent and parent.lower() not in ("books", "audiobooks", "media", "audible"):
        return parent

    # For standalone files, use the filename without extension and track numbers
    stem = p.stem
    # Remove common prefixes like "01 ", "01. ", "01 - "
    import re
    stem = re.sub(r"^\d+[\s.\-_]+", "", stem)
    return stem or p.stem


# ---------------------------------------------------------------------------
# Path-based series detection helpers
# ---------------------------------------------------------------------------

# Spelled-out number → int mapping (One–Twenty + common ordinals)
_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    # ordinals
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20,
}

_WORD_PATTERN = "|".join(_WORD_TO_NUM.keys())


def _word_to_int(w: str) -> Optional[int]:
    """Convert a spelled-out number or ordinal to int, or parse digits."""
    if w.isdigit():
        return int(w)
    return _WORD_TO_NUM.get(w.lower())


def _parse_series_from_dirname(dirname: str) -> Optional[Dict[str, any]]:
    """
    Parse series name + position from an audiobook directory name.

    Supported patterns:
      - "Book <N/word> of [the] <Series>"          → series, position
      - "<Title> - <Series>,? Book <N>"             → series, position
      - "(<Series>,? Book <N>)" in any part         → series, position
      - "(<Series> #<N>)" in any part               → series, position
      - "<Series>,? Book <N>"                       → series, position
      - "<Series> #<N>"                             → series, position

    Returns dict {series_name, series_position} or None.
    """
    if not dirname or not dirname.strip():
        return None

    dirname = dirname.strip()
    num = rf"(\d+|{_WORD_PATTERN})"

    # Pattern 1: "Book <N/word> of [the] <Series>"
    # e.g. "The Dragon Reborn - Book Three of The Wheel of Time"
    m = re.search(
        rf"[Bb]ook\s+{num}\s+of\s+(?:the\s+)?(.+)",
        dirname,
        re.IGNORECASE,
    )
    if m:
        pos = _word_to_int(m.group(1))
        series_name = m.group(2).strip().rstrip(")")
        if pos and series_name:
            return {"series_name": series_name, "series_position": pos}

    # Pattern 2: Parenthesised "(<Series>,? Book <N>)" or "(<Series> #<N>)"
    # e.g. "The Eye of the World (The Wheel of Time, Book 1)"
    # e.g. "The Eye of the World (Wheel of Time #1)"
    m = re.search(
        rf"\(([^)]+?),?\s+[Bb]ook\s+{num}\)",
        dirname,
    )
    if m:
        series_name = m.group(1).strip()
        pos = _word_to_int(m.group(2))
        if pos and series_name:
            return {"series_name": series_name, "series_position": pos}

    m = re.search(
        rf"\(([^)]+?)\s+#\s*{num}\)",
        dirname,
    )
    if m:
        series_name = m.group(1).strip()
        pos = _word_to_int(m.group(2))
        if pos and series_name:
            return {"series_name": series_name, "series_position": pos}

    # Pattern 3: "<Title> - <Series>,? Book <N>" (dash-separated)
    # e.g. "A Beautiful Friendship - Star Kingdom, Book 1"
    m = re.search(
        rf"-\s+(.+?),?\s+[Bb]ook\s+{num}\s*$",
        dirname,
    )
    if m:
        series_name = m.group(1).strip()
        pos = _word_to_int(m.group(2))
        if pos and series_name:
            return {"series_name": series_name, "series_position": pos}

    # Pattern 4: "<Series>,? Book <N>" (no dash, whole string)
    # e.g. "Star Kingdom, Book 1"
    m = re.search(
        rf"^(.+?),?\s+[Bb]ook\s+{num}\s*$",
        dirname,
    )
    if m:
        series_name = m.group(1).strip()
        pos = _word_to_int(m.group(2))
        if pos and series_name:
            return {"series_name": series_name, "series_position": pos}

    # Pattern 5: "<Series> #<N>" without parens
    # e.g. "Wheel of Time #1"
    m = re.search(
        rf"^(.+?)\s+#\s*{num}\s*$",
        dirname,
    )
    if m:
        series_name = m.group(1).strip()
        pos = _word_to_int(m.group(2))
        if pos and series_name:
            return {"series_name": series_name, "series_position": pos}

    return None


def detect_series_from_paths(db: Session, author_id: UUID) -> Dict[str, int]:
    """
    Detect series by parsing audiobook directory names (Phase 3).

    Queries ALL LibraryFile records for the author, extracts unique parent
    directory names, parses each with _parse_series_from_dirname(), groups by
    series name, and creates/links Series and Book records.

    Args:
        db: Database session
        author_id: Author UUID

    Returns:
        Stats dict: series_created, books_linked, new_series_ids
    """
    from app.models.author import Author
    from app.models.series import Series

    stats = {"series_created": 0, "books_linked": 0, "new_series_ids": []}

    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        return stats

    # Get ALL library files for this author (no metadata_json filter)
    query = db.query(LibraryFile)
    if author.musicbrainz_id and not author.musicbrainz_id.startswith("local-"):
        query = query.filter(
            or_(
                LibraryFile.musicbrainz_artistid == author.musicbrainz_id,
                LibraryFile.artist.ilike(f"%{author.name}%"),
            )
        )
    else:
        query = query.filter(LibraryFile.artist.ilike(f"%{author.name}%"))

    library_files = query.all()
    if not library_files:
        return stats

    # Build map: dirname → {parsed series info, list of files}
    # Group files by parent directory
    dir_files: Dict[str, List[LibraryFile]] = defaultdict(list)
    for lf in library_files:
        if lf.file_path:
            parent = Path(lf.file_path).parent.name
            dir_files[parent].append(lf)

    # Parse each unique dirname for series info, group by series name
    series_groups: Dict[str, List[Dict]] = defaultdict(list)  # lower(series_name) → [{dirname, position, files}]
    for dirname, files in dir_files.items():
        parsed = _parse_series_from_dirname(dirname)
        if parsed:
            key = parsed["series_name"].lower()
            series_groups[key].append({
                "series_name": parsed["series_name"],
                "position": parsed["series_position"],
                "files": files,
            })

    if not series_groups:
        logger.debug(f"No series detected from directory names for {author.name}")
        return stats

    logger.info(f"Path-based detection found {len(series_groups)} potential series for {author.name}")

    for series_key, entries in series_groups.items():
        try:
            # Use the canonical name from the first entry
            canonical_name = entries[0]["series_name"]

            # Pre-count linkable books before creating a new series
            linkable_count = 0
            for entry in entries:
                files = entry["files"]
                files_by_album_check: Dict[str, List[LibraryFile]] = defaultdict(list)
                for lf in files:
                    album_key = (lf.album or "").strip()
                    if not album_key:
                        album_key = _infer_book_title_from_path(lf.file_path)
                    if album_key:
                        files_by_album_check[album_key].append(lf)
                for album_title in files_by_album_check:
                    book = db.query(Book).filter(
                        Book.author_id == author_id,
                        Book.title == album_title,
                    ).first()
                    if book and book.series_id is None:
                        linkable_count += 1

            # Find or create Series
            existing_series = db.query(Series).filter(
                Series.author_id == author_id,
                func.lower(Series.name) == series_key,
            ).first()

            if existing_series:
                series = existing_series
            else:
                if linkable_count == 0:
                    logger.info(f"Skipping series '{canonical_name}' (from path) — no linkable books found")
                    continue
                series = Series(
                    author_id=author_id,
                    name=canonical_name,
                    monitored=False,
                )
                db.add(series)
                db.flush()
                stats["series_created"] += 1
                stats["new_series_ids"].append(str(series.id))
                logger.info(f"Created series '{canonical_name}' (from path) for {author.name}")

            # For each directory entry, find the matching Book and link it
            for entry in entries:
                position = entry["position"]
                files = entry["files"]

                # Group files by album to find the Book
                files_by_album: Dict[str, List[LibraryFile]] = defaultdict(list)
                for lf in files:
                    album_key = (lf.album or "").strip()
                    if not album_key:
                        album_key = _infer_book_title_from_path(lf.file_path)
                    if album_key:
                        files_by_album[album_key].append(lf)

                for album_title, _album_files in files_by_album.items():
                    book = db.query(Book).filter(
                        Book.author_id == author_id,
                        Book.title == album_title,
                    ).first()

                    if not book:
                        continue

                    # Skip if already assigned to a series
                    if book.series_id is not None:
                        if book.series_id != series.id:
                            logger.debug(
                                f"Book '{album_title}' already in series {book.series_id}, "
                                f"skipping link to '{canonical_name}' (from path)"
                            )
                        continue

                    book.series_id = series.id
                    book.series_position = position
                    stats["books_linked"] += 1
                    logger.debug(
                        f"Linked book '{album_title}' to series '{canonical_name}' "
                        f"at position {position} (from path)"
                    )

        except Exception as e:
            logger.error(f"Error processing path-based series '{series_key}': {e}")
            db.rollback()
            continue

    db.commit()

    logger.info(
        f"Path-based series detection for {author.name}: "
        f"{stats['series_created']} series created, {stats['books_linked']} books linked"
    )

    return stats


def detect_and_create_series(db: Session, author_id: UUID) -> Dict[str, int]:
    """
    Detect series from file metadata and create Series records + link books.

    Reads the 'series' and 'series_part' fields stored in LibraryFile.metadata_json
    by FastMetadataExtractor. Groups files by series name, creates Series records
    for the author, and sets book.series_id / book.series_position.

    Args:
        db: Database session
        author_id: Author UUID

    Returns:
        Stats dict: series_created, books_linked
    """
    from app.models.author import Author
    from app.models.series import Series

    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        return {"series_created": 0, "books_linked": 0}

    # Get library files for this author that have series metadata
    query = db.query(LibraryFile).filter(
        LibraryFile.metadata_json['series'].astext.isnot(None),
        LibraryFile.metadata_json['series'].astext != '',
    )

    # Match by artist MBID or name (same pattern as create_books_from_file_metadata)
    if author.musicbrainz_id and not author.musicbrainz_id.startswith("local-"):
        query = query.filter(
            or_(
                LibraryFile.musicbrainz_artistid == author.musicbrainz_id,
                LibraryFile.artist.ilike(f"%{author.name}%"),
            )
        )
    else:
        query = query.filter(LibraryFile.artist.ilike(f"%{author.name}%"))

    library_files = query.all()

    if not library_files:
        logger.debug(f"No files with series metadata found for author {author.name}")
        return {"series_created": 0, "books_linked": 0}

    logger.info(f"Found {len(library_files)} files with series metadata for {author.name}")

    # Group files by series name (case-insensitive)
    files_by_series: Dict[str, List[LibraryFile]] = defaultdict(list)
    for lf in library_files:
        meta = lf.metadata_json or {}
        series_name = (meta.get('series') or '').strip()
        if series_name:
            files_by_series[series_name.lower()].append(lf)

    stats = {"series_created": 0, "books_linked": 0, "new_series_ids": []}

    for series_key, files in files_by_series.items():
        try:
            # Use the original-case name from the first file
            canonical_name = (files[0].metadata_json or {}).get('series', '').strip()

            # Pre-count linkable books before creating a new series
            linkable_count = 0
            files_by_album_check: Dict[str, List[LibraryFile]] = defaultdict(list)
            for lf in files:
                album_key = (lf.album or "").strip()
                if not album_key:
                    album_key = _infer_book_title_from_path(lf.file_path)
                if album_key:
                    files_by_album_check[album_key].append(lf)
            for album_title in files_by_album_check:
                book = db.query(Book).filter(
                    Book.author_id == author_id,
                    Book.title == album_title,
                ).first()
                if book and book.series_id is None:
                    linkable_count += 1

            # Check if Series already exists for this author (case-insensitive)
            existing_series = db.query(Series).filter(
                Series.author_id == author_id,
                func.lower(Series.name) == series_key,
            ).first()

            if existing_series:
                series = existing_series
            else:
                if linkable_count == 0:
                    logger.info(f"Skipping series '{canonical_name}' — no linkable books found")
                    continue
                series = Series(
                    author_id=author_id,
                    name=canonical_name,
                    monitored=False,
                )
                db.add(series)
                db.flush()
                stats["series_created"] += 1
                stats["new_series_ids"].append(str(series.id))
                logger.info(f"Created series '{canonical_name}' for {author.name}")

            # Group files by album tag to find which Book each belongs to
            files_by_album: Dict[str, List[LibraryFile]] = defaultdict(list)
            for lf in files:
                album_key = (lf.album or "").strip()
                if not album_key:
                    album_key = _infer_book_title_from_path(lf.file_path)
                if album_key:
                    files_by_album[album_key].append(lf)

            # For each album/book group, find the Book and set series info
            for album_title, album_files in files_by_album.items():
                book = db.query(Book).filter(
                    Book.author_id == author_id,
                    Book.title == album_title,
                ).first()

                if not book:
                    continue

                # Skip if already assigned to a series
                if book.series_id is not None:
                    if book.series_id != series.id:
                        logger.debug(
                            f"Book '{album_title}' already in series {book.series_id}, "
                            f"skipping link to '{canonical_name}'"
                        )
                    continue

                # Parse series_part into an integer position
                position = None
                for af in album_files:
                    meta = af.metadata_json or {}
                    part_str = meta.get('series_part', '')
                    if part_str:
                        match = re.search(r'(\d+)', str(part_str))
                        if match:
                            position = int(match.group(1))
                            break

                book.series_id = series.id
                book.series_position = position
                stats["books_linked"] += 1
                logger.debug(f"Linked book '{album_title}' to series '{canonical_name}' at position {position}")

        except Exception as e:
            logger.error(f"Error processing series '{series_key}': {e}")
            db.rollback()
            continue

    db.commit()

    logger.info(
        f"Series detection for {author.name}: "
        f"{stats['series_created']} series created, {stats['books_linked']} books linked"
    )

    return stats


def detect_series_from_musicbrainz(db: Session, author_id: UUID) -> Dict:
    """
    Detect series by querying the local MusicBrainz database mirror.

    Finds all series containing release groups by this author, creates Series
    records, and links matching Book records with correct series positions.

    Args:
        db: Database session
        author_id: Author UUID

    Returns:
        Stats dict: series_created, books_linked, new_series_ids
    """
    from app.models.author import Author
    from app.models.series import Series
    from app.services.musicbrainz_local import get_musicbrainz_local_db

    stats = {"series_created": 0, "books_linked": 0, "new_series_ids": []}

    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        return stats

    local_db = get_musicbrainz_local_db()
    if not local_db:
        logger.debug("MusicBrainz local DB not available, skipping MB series detection")
        return stats

    # --- Approach A: Artist MBID → series (original logic) ---
    if author.musicbrainz_id and not author.musicbrainz_id.startswith("local-"):
        logger.info(f"Checking MusicBrainz for series by {author.name} ({author.musicbrainz_id})")

        mb_series_list = local_db.get_series_for_artist(author.musicbrainz_id)

        if mb_series_list:
            logger.info(f"Found {len(mb_series_list)} series in MusicBrainz for {author.name}")

            for mb_series in mb_series_list:
                series_mbid = mb_series["series_mbid"]
                series_name = mb_series["series_name"]

                try:
                    # Get ordered release groups for this series
                    ordered_books = local_db.get_series_release_group_order(series_mbid)

                    # Pre-count linkable books
                    linkable_count = 0
                    for entry in ordered_books:
                        book = db.query(Book).filter(
                            Book.author_id == author_id,
                            Book.musicbrainz_id == entry["release_group_mbid"],
                        ).first()
                        if book and book.series_id is None:
                            linkable_count += 1

                    series = _find_or_create_mb_series(
                        db, author_id, series_mbid, series_name, stats,
                        linkable_count=linkable_count,
                    )
                    if series is None:
                        continue

                    for entry in ordered_books:
                        rg_mbid = entry["release_group_mbid"]
                        position = entry["series_position"]

                        book = db.query(Book).filter(
                            Book.author_id == author_id,
                            Book.musicbrainz_id == rg_mbid,
                        ).first()

                        if not book:
                            continue
                        if book.series_id is not None:
                            if book.series_id != series.id:
                                logger.debug(
                                    f"Book '{book.title}' already in series {book.series_id}, "
                                    f"skipping link to '{series_name}'"
                                )
                            continue

                        book.series_id = series.id
                        book.series_position = position
                        stats["books_linked"] += 1
                        logger.debug(
                            f"Linked book '{book.title}' to series '{series_name}' at position {position}"
                        )

                except Exception as e:
                    logger.error(f"Error processing MB series '{series_name}' ({series_mbid}): {e}")
                    db.rollback()
                    continue

    # --- Approach B: Title-based lookup (works for local authors too) ---
    # For each unlinked book, search MB by title+author to find series relationships
    unlinked_books = db.query(Book).filter(
        Book.author_id == author_id,
        Book.series_id.is_(None),
    ).all()

    if unlinked_books:
        logger.info(f"Title-based MB lookup for {len(unlinked_books)} unlinked books by {author.name}")

        for book in unlinked_books:
            try:
                # Search for matching release groups by title + author name
                rg_results = local_db.search_release_group(book.title, author.name, limit=3)

                for rg in rg_results:
                    # Require a reasonable match score
                    if rg.get("score", 0) < 60:
                        continue

                    rg_mbid = rg["id"]

                    # Check if this release group belongs to any series
                    series_info = local_db.get_series_for_release_group(rg_mbid)
                    if not series_info:
                        continue

                    series = _find_or_create_mb_series(
                        db, author_id,
                        series_info["series_mbid"],
                        series_info["series_name"],
                        stats,
                        linkable_count=1,  # This book is the linkable one
                    )
                    if series is None:
                        continue

                    book.series_id = series.id
                    book.series_position = series_info.get("series_position")
                    stats["books_linked"] += 1
                    logger.debug(
                        f"Linked book '{book.title}' to series '{series_info['series_name']}' "
                        f"at position {series_info.get('series_position')} (title lookup)"
                    )
                    break  # Found a match, stop searching

            except Exception as e:
                logger.error(f"Error in title-based MB lookup for '{book.title}': {e}")
                continue

    db.commit()

    logger.info(
        f"MB series detection for {author.name}: "
        f"{stats['series_created']} series created, {stats['books_linked']} books linked"
    )

    return stats


def _find_or_create_mb_series(
    db: Session, author_id: UUID, series_mbid: str, series_name: str, stats: Dict,
    linkable_count: int = -1,
):
    """Find or create a Series record for a MusicBrainz series. Updates stats in-place.

    Args:
        linkable_count: Number of books that will be linked. If 0 and no existing
            series, creation is skipped. Pass -1 (default) to skip the check.
    """
    from app.models.series import Series

    existing_series = db.query(Series).filter(
        Series.author_id == author_id,
        or_(
            Series.musicbrainz_series_id == series_mbid,
            func.lower(Series.name) == series_name.lower(),
        ),
    ).first()

    if existing_series:
        # Backfill MB series ID if missing
        if not existing_series.musicbrainz_series_id:
            existing_series.musicbrainz_series_id = series_mbid
        return existing_series

    if linkable_count == 0:
        logger.info(f"Skipping series '{series_name}' (MB: {series_mbid}) — no linkable books found")
        return None

    series = Series(
        author_id=author_id,
        name=series_name,
        musicbrainz_series_id=series_mbid,
        monitored=False,
    )
    db.add(series)
    db.flush()
    stats["series_created"] += 1
    stats["new_series_ids"].append(str(series.id))
    logger.info(f"Created series '{series_name}' (MB: {series_mbid}) for author {author_id}")
    return series
