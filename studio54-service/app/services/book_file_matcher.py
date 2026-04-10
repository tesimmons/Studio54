"""
Book File Matcher Service
Matches library files to books/chapters using file metadata (no MBID required)

For audiobook imports where files lack MusicBrainz IDs in comments,
this service matches files to Book/Chapter records using:
- Album tag → Book title (fuzzy matching)
- Track number → Chapter number
- Title similarity
- Duration proximity
"""

import logging
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.book import Book
from app.models.chapter import Chapter
from app.models.library import LibraryFile

logger = logging.getLogger(__name__)


class BookFileMatcher:
    """
    Service for matching library files to books/chapters using metadata.

    Called after MBID matching for audiobook libraries to pick up files
    that have no MusicBrainz IDs but do have standard tags (title, album,
    track number, artist).
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalize(s: Optional[str]) -> str:
        if not s:
            return ""
        return s.strip().lower()

    @staticmethod
    def _string_similarity(s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

    def match_author_files(
        self,
        author_id: UUID,
        library_path_id: Optional[UUID] = None,
    ) -> Dict[str, int]:
        """
        Match unmatched library files for an author to books/chapters using metadata.

        Only processes files that were NOT already matched by MBID matching
        (i.e. files where the chapter has no file_path yet, or files with no MBID).

        Args:
            author_id: Author UUID
            library_path_id: Optional library path to limit search

        Returns:
            Statistics dict with matched/unmatched/errors counts
        """
        from app.models.author import Author

        author = self.db.query(Author).filter(Author.id == author_id).first()
        if not author:
            logger.error(f"Author not found: {author_id}")
            return {"matched": 0, "unmatched": 0, "errors": 0}

        # Get all books + chapters for this author
        books = (
            self.db.query(Book)
            .options(joinedload(Book.chapters))
            .filter(Book.author_id == author_id)
            .all()
        )

        if not books:
            logger.info(f"No books found for author {author.name}, skipping metadata match")
            return {"matched": 0, "unmatched": 0, "errors": 0}

        # Get library files for this author that lack MBIDs
        # These are the files that MBID matching couldn't handle
        query = self.db.query(LibraryFile)

        if library_path_id:
            query = query.filter(LibraryFile.library_path_id == library_path_id)

        # Match by artist name (since these files lack artist MBID)
        if author.musicbrainz_id:
            # Include files matched to this author by MBID OR by name
            query = query.filter(
                or_(
                    LibraryFile.musicbrainz_artistid == author.musicbrainz_id,
                    LibraryFile.artist.ilike(f"%{author.name}%"),
                )
            )
        else:
            query = query.filter(LibraryFile.artist.ilike(f"%{author.name}%"))

        # Only files without a recording MBID (already-matched files are handled by MBIDFileMatcher)
        query = query.filter(
            or_(
                LibraryFile.musicbrainz_trackid.is_(None),
                LibraryFile.musicbrainz_trackid == "",
            )
        )

        library_files = query.all()

        if not library_files:
            logger.info(f"No unmatched files found for author {author.name}")
            return {"matched": 0, "unmatched": 0, "errors": 0}

        logger.info(
            f"Metadata matching: {len(library_files)} unmatched files for "
            f"{author.name} across {len(books)} books"
        )

        # Build book title lookup for fuzzy matching
        # Map normalized book title → Book object
        book_title_map: Dict[str, Book] = {}
        for book in books:
            book_title_map[self._normalize(book.title)] = book

        # Group files by album tag (most audiobook files share an album tag per book)
        files_by_album: Dict[str, List[LibraryFile]] = defaultdict(list)
        for lf in library_files:
            album_key = self._normalize(lf.album) or "__no_album__"
            files_by_album[album_key].append(lf)

        matched = 0
        unmatched = 0
        errors = 0

        # Collect chapter IDs already matched (have a file_path set)
        already_matched_chapter_ids = set()
        for book in books:
            for chapter in book.chapters:
                if chapter.has_file and chapter.file_path:
                    already_matched_chapter_ids.add(chapter.id)

        for album_key, files in files_by_album.items():
            try:
                # Find the best matching book for this album group
                book = self._find_matching_book(album_key, book_title_map, books)

                if not book:
                    unmatched += len(files)
                    continue

                # Get unmatched chapters for this book
                unmatched_chapters = [
                    ch for ch in book.chapters
                    if ch.id not in already_matched_chapter_ids
                ]

                if not unmatched_chapters:
                    unmatched += len(files)
                    continue

                # Match files to chapters within this book
                file_matches = self._match_files_to_chapters(
                    files, unmatched_chapters, book
                )

                for chapter, lib_file in file_matches:
                    chapter.file_path = lib_file.file_path
                    chapter.has_file = True
                    already_matched_chapter_ids.add(chapter.id)
                    matched += 1
                    logger.debug(
                        f"Metadata match: '{lib_file.file_name}' → "
                        f"Chapter {chapter.chapter_number}: '{chapter.title}' "
                        f"in book '{book.title}'"
                    )

                unmatched += len(files) - len(file_matches)

            except Exception as e:
                logger.error(f"Error matching album group '{album_key}': {e}")
                errors += len(files)

        self.db.commit()

        logger.info(
            f"Metadata matching complete for {author.name}: "
            f"{matched} matched, {unmatched} unmatched, {errors} errors"
        )

        return {"matched": matched, "unmatched": unmatched, "errors": errors}

    def _find_matching_book(
        self,
        album_key: str,
        book_title_map: Dict[str, "Book"],
        books: List["Book"],
    ) -> Optional["Book"]:
        """
        Find the best matching book for a given album tag.

        Uses exact match first, then fuzzy matching.
        """
        if album_key == "__no_album__":
            # If only one book for this author, assume it's the match
            if len(books) == 1:
                return books[0]
            return None

        # Exact match
        if album_key in book_title_map:
            return book_title_map[album_key]

        # Fuzzy match - find best scoring book
        best_book = None
        best_score = 0.0

        for book in books:
            score = self._string_similarity(album_key, self._normalize(book.title))
            if score > best_score:
                best_score = score
                best_book = book

        # Require at least 60% similarity
        if best_score >= 0.6:
            logger.debug(
                f"Fuzzy matched album '{album_key}' to book "
                f"'{best_book.title}' (score: {best_score:.2f})"
            )
            return best_book

        return None

    def _match_files_to_chapters(
        self,
        files: List[LibraryFile],
        chapters: List[Chapter],
        book: "Book",
    ) -> List[tuple]:
        """
        Match files to chapters within a single book.

        Strategy (in priority order):
        1. Track number match (most reliable for audiobooks)
        2. Title similarity
        3. Duration proximity

        Returns:
            List of (Chapter, LibraryFile) tuples for successful matches
        """
        matches: List[tuple] = []
        used_files = set()
        used_chapters = set()

        # Build chapter lookup by number
        chapter_by_number: Dict[tuple, Chapter] = {}
        for ch in chapters:
            if ch.chapter_number is not None:
                key = (ch.disc_number or 1, ch.chapter_number)
                chapter_by_number[key] = ch

        # Phase 1: Match by track number + disc number (most reliable)
        for lf in files:
            if lf.track_number is None:
                continue

            disc = lf.disc_number or 1
            key = (disc, lf.track_number)
            chapter = chapter_by_number.get(key)

            if chapter and chapter.id not in used_chapters:
                matches.append((chapter, lf))
                used_files.add(lf.id)
                used_chapters.add(chapter.id)

        # Phase 2: Match remaining by title similarity
        remaining_files = [f for f in files if f.id not in used_files]
        remaining_chapters = [c for c in chapters if c.id not in used_chapters]

        if remaining_files and remaining_chapters:
            for lf in remaining_files:
                file_title = self._normalize(lf.title)
                if not file_title:
                    continue

                best_chapter = None
                best_score = 0.0

                for ch in remaining_chapters:
                    if ch.id in used_chapters:
                        continue

                    score = self._string_similarity(file_title, self._normalize(ch.title))

                    # Boost score if duration is close
                    if lf.duration_seconds and ch.duration_ms:
                        file_duration_ms = lf.duration_seconds * 1000
                        duration_diff = abs(file_duration_ms - ch.duration_ms)
                        if duration_diff < 10000:  # Within 10 seconds
                            score += 0.1

                    if score > best_score:
                        best_score = score
                        best_chapter = ch

                # Require at least 55% similarity for title-based matching
                if best_chapter and best_score >= 0.55:
                    matches.append((best_chapter, lf))
                    used_files.add(lf.id)
                    used_chapters.add(best_chapter.id)

        # Phase 3: For single-book authors with sequential files, match by position
        remaining_files = sorted(
            [f for f in files if f.id not in used_files],
            key=lambda f: (f.disc_number or 1, f.file_name or ""),
        )
        remaining_chapters = sorted(
            [c for c in chapters if c.id not in used_chapters],
            key=lambda c: (c.disc_number or 1, c.chapter_number or 0),
        )

        if remaining_files and remaining_chapters and len(remaining_files) == len(remaining_chapters):
            # Same count of unmatched files and chapters - match by position
            for ch, lf in zip(remaining_chapters, remaining_files):
                matches.append((ch, lf))
                used_files.add(lf.id)
                used_chapters.add(ch.id)

        return matches
