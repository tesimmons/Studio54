"""
Artist Import Service
Handles importing and matching artists from library files to Studio54 artists
"""

import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from difflib import SequenceMatcher
import re

from app.models.artist import Artist
from app.models.library import LibraryFile
from app.models.library_import import LibraryArtistMatch
from app.services.musicbrainz_client import get_musicbrainz_client

logger = logging.getLogger(__name__)


class ArtistImportService:
    """
    Service for importing artists from library files

    Responsibilities:
    - Extract unique artists from library files
    - Search MusicBrainz for artist matches
    - Score match confidence
    - Create Studio54 artist records
    """

    def __init__(self, db: Session):
        self.db = db
        self.mb_client = get_musicbrainz_client()

    @staticmethod
    def normalize_artist_name(name: str) -> str:
        """
        Normalize artist name for matching

        Args:
            name: Artist name

        Returns:
            Normalized name
        """
        if not name:
            return ""

        # Convert to lowercase
        normalized = name.lower()

        # Remove common prefixes/articles
        for article in ["the ", "a ", "an "]:
            if normalized.startswith(article):
                normalized = normalized[len(article):]
                break

        # Remove special characters except spaces and letters
        normalized = re.sub(r'[^\w\s]', '', normalized)

        # Collapse multiple spaces
        normalized = ' '.join(normalized.split())

        return normalized.strip()

    @staticmethod
    def calculate_name_similarity(name1: str, name2: str) -> float:
        """
        Calculate similarity between two artist names

        Args:
            name1: First artist name
            name2: Second artist name

        Returns:
            Similarity score (0.0 to 1.0)
        """
        norm1 = ArtistImportService.normalize_artist_name(name1)
        norm2 = ArtistImportService.normalize_artist_name(name2)

        if not norm1 or not norm2:
            return 0.0

        # Exact match after normalization
        if norm1 == norm2:
            return 1.0

        # Sequence matcher for fuzzy similarity
        return SequenceMatcher(None, norm1, norm2).ratio()

    def get_library_artists(
        self,
        library_path_id: str
    ) -> List[Dict]:
        """
        Get unique artists from library files

        Args:
            library_path_id: Library path UUID

        Returns:
            List of artist dictionaries with file counts and sample data
        """
        logger.info(f"Extracting unique artists from library: {library_path_id}")

        # Single query: get artist stats, sample albums, sample files, and MBID all at once
        # Uses array_agg with sub-selects to avoid N+1 per-artist queries
        from sqlalchemy import text
        result = self.db.execute(text("""
            SELECT
                artist_name,
                file_count,
                album_count,
                first_mbid,
                sample_albums,
                sample_files
            FROM (
                SELECT
                    COALESCE(album_artist, artist) AS artist_name,
                    COUNT(*) AS file_count,
                    COUNT(DISTINCT album) AS album_count,
                    (array_agg(musicbrainz_artistid) FILTER (WHERE musicbrainz_artistid IS NOT NULL AND musicbrainz_artistid != ''))[1] AS first_mbid,
                    (array_agg(DISTINCT album) FILTER (WHERE album IS NOT NULL))[1:5] AS sample_albums,
                    (array_agg(file_path))[1:3] AS sample_files
                FROM library_files
                WHERE library_path_id = :lp_id
                  AND COALESCE(album_artist, artist) IS NOT NULL
                GROUP BY COALESCE(album_artist, artist)
            ) sub
            ORDER BY file_count DESC
        """), {"lp_id": library_path_id}).mappings().all()

        artists = []
        for row in result:
            artists.append({
                'name': row['artist_name'],
                'file_count': row['file_count'],
                'album_count': row['album_count'],
                'musicbrainz_id': row['first_mbid'],
                'sample_albums': [a for a in (row['sample_albums'] or []) if a],
                'sample_file_paths': [f for f in (row['sample_files'] or []) if f],
            })

        logger.info(f"Found {len(artists)} unique artists in library")
        return artists

    def search_musicbrainz_artist(
        self,
        artist_name: str,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search MusicBrainz for artist matches

        Args:
            artist_name: Artist name to search
            limit: Maximum results to return

        Returns:
            List of artist matches with confidence scores
        """
        try:
            logger.info(f"Searching MusicBrainz for: {artist_name}")

            # Search MusicBrainz
            results = self.mb_client.search_artist(artist_name, limit=limit)

            if not results:
                logger.warning(f"No MusicBrainz results for: {artist_name}")
                return []

            # Score each result
            scored_results = []
            for result in results:
                mb_name = result.get('name', '')
                mb_sort_name = result.get('sort-name', '')
                disambiguation = result.get('disambiguation', '')

                # Calculate confidence based on name similarity
                name_score = self.calculate_name_similarity(artist_name, mb_name)
                sort_name_score = self.calculate_name_similarity(artist_name, mb_sort_name)

                # Use the better of the two scores
                confidence = max(name_score, sort_name_score) * 100

                # Boost confidence if MusicBrainz score is high
                mb_score = result.get('score', 0)
                if mb_score >= 95:
                    confidence = min(confidence * 1.1, 100)

                scored_results.append({
                    'musicbrainz_id': result.get('id'),
                    'name': mb_name,
                    'sort_name': mb_sort_name,
                    'disambiguation': disambiguation,
                    'confidence': round(confidence, 1),
                    'musicbrainz_score': mb_score,
                    'type': result.get('type', 'Unknown'),
                    'country': result.get('country'),
                    'begin': result.get('life-span', {}).get('begin'),
                    'end': result.get('life-span', {}).get('end')
                })

            # Sort by confidence
            scored_results.sort(key=lambda x: x['confidence'], reverse=True)

            logger.info(
                f"Found {len(scored_results)} MusicBrainz matches for '{artist_name}', "
                f"best confidence: {scored_results[0]['confidence']}%"
            )

            return scored_results

        except Exception as e:
            logger.error(f"MusicBrainz search failed for '{artist_name}': {e}")
            return []

    def check_existing_artist(
        self,
        artist_name: str,
        musicbrainz_id: Optional[str] = None
    ) -> Optional[Artist]:
        """
        Check if artist already exists in Studio54

        Args:
            artist_name: Artist name
            musicbrainz_id: Optional MusicBrainz ID

        Returns:
            Existing Artist if found, None otherwise
        """
        # First check by MusicBrainz ID if available
        if musicbrainz_id:
            existing = self.db.query(Artist).filter(
                Artist.musicbrainz_id == musicbrainz_id
            ).first()
            if existing:
                logger.info(f"Artist already exists by MBID: {existing.name}")
                return existing

        # Check by normalized name
        normalized_name = self.normalize_artist_name(artist_name)
        artists = self.db.query(Artist).all()

        for artist in artists:
            if self.normalize_artist_name(artist.name) == normalized_name:
                logger.info(f"Artist already exists by name: {artist.name}")
                return artist

        return None

    def create_artist_from_musicbrainz(
        self,
        musicbrainz_id: str,
        artist_name: str
    ) -> Optional[Artist]:
        """
        Create new Artist record from MusicBrainz data

        Args:
            musicbrainz_id: MusicBrainz Artist ID
            artist_name: Artist name (fallback if MB fetch fails)

        Returns:
            Created Artist or None on failure
        """
        try:
            logger.info(f"Creating artist from MusicBrainz: {artist_name} ({musicbrainz_id})")

            # Create artist record
            artist = Artist(
                name=artist_name,
                musicbrainz_id=musicbrainz_id,
                is_monitored=False,  # Default to not monitored
            )

            self.db.add(artist)
            self.db.flush()  # Get artist.id without committing

            logger.info(f"Created artist: {artist.name} (ID: {artist.id})")
            return artist

        except Exception as e:
            logger.error(f"Failed to create artist for {artist_name} (MBID: {musicbrainz_id}): {e}")
            self.db.rollback()
            return None

    def match_library_artist(
        self,
        library_artist: Dict,
        confidence_threshold: float = 85.0,
        auto_create: bool = True
    ) -> Tuple[Optional[Artist], LibraryArtistMatch]:
        """
        Match a library artist to Studio54 artist

        Args:
            library_artist: Library artist dict from get_library_artists()
            confidence_threshold: Minimum confidence for auto-match (0-100)
            auto_create: Automatically create artist if high confidence match

        Returns:
            Tuple of (matched_artist, artist_match_record)
        """
        artist_name = library_artist['name']
        file_count = library_artist['file_count']
        musicbrainz_id = library_artist.get('musicbrainz_id')

        logger.info(f"Matching library artist: {artist_name} ({file_count} files)")

        # Check if already exists
        existing_artist = self.check_existing_artist(artist_name, musicbrainz_id)

        if existing_artist:
            # Artist already exists
            match_record = LibraryArtistMatch(
                library_artist_name=artist_name,
                file_count=file_count,
                sample_albums=library_artist.get('sample_albums', []),
                sample_file_paths=library_artist.get('sample_file_paths', []),
                musicbrainz_id=existing_artist.musicbrainz_id,
                confidence_score=100.0,
                status='matched',
                matched_artist_id=existing_artist.id
            )

            return existing_artist, match_record

        # If file tags have a MusicBrainz artist ID, trust it and create directly
        if musicbrainz_id and auto_create:
            logger.info(f"Using embedded MBID {musicbrainz_id} for: {artist_name}")

            # Verify the MBID is valid by fetching artist info from MusicBrainz
            try:
                mb_artist = self.mb_client.get_artist(musicbrainz_id)
                mb_name = mb_artist.get('name', artist_name) if mb_artist else artist_name
            except Exception as e:
                logger.warning(f"Could not verify MBID {musicbrainz_id}: {e}")
                mb_name = artist_name

            artist = self.create_artist_from_musicbrainz(musicbrainz_id, mb_name)

            if artist:
                match_record = LibraryArtistMatch(
                    library_artist_name=artist_name,
                    file_count=file_count,
                    sample_albums=library_artist.get('sample_albums', []),
                    sample_file_paths=library_artist.get('sample_file_paths', []),
                    musicbrainz_id=musicbrainz_id,
                    confidence_score=100.0,
                    status='matched',
                    matched_artist_id=artist.id
                )

                logger.info(f"Created artist from embedded MBID: {artist.name}")
                return artist, match_record

        # Search MusicBrainz by name
        mb_suggestions = self.search_musicbrainz_artist(artist_name, limit=5)

        if not mb_suggestions:
            # No MusicBrainz matches found
            match_record = LibraryArtistMatch(
                library_artist_name=artist_name,
                file_count=file_count,
                sample_albums=library_artist.get('sample_albums', []),
                sample_file_paths=library_artist.get('sample_file_paths', []),
                confidence_score=0.0,
                status='failed',
                musicbrainz_suggestions=[],
                rejection_reason='No MusicBrainz matches found'
            )

            return None, match_record

        # Get best match
        best_match = mb_suggestions[0]
        best_confidence = best_match['confidence']

        # Auto-create if confidence is high enough
        if auto_create and best_confidence >= confidence_threshold:
            artist = self.create_artist_from_musicbrainz(
                best_match['musicbrainz_id'],
                best_match['name']
            )

            if artist:
                match_record = LibraryArtistMatch(
                    library_artist_name=artist_name,
                    file_count=file_count,
                    sample_albums=library_artist.get('sample_albums', []),
                    sample_file_paths=library_artist.get('sample_file_paths', []),
                    musicbrainz_id=artist.musicbrainz_id,
                    confidence_score=best_confidence,
                    status='matched',
                    matched_artist_id=artist.id,
                    musicbrainz_suggestions=mb_suggestions
                )

                logger.info(
                    f"Auto-matched and created artist: {artist.name} "
                    f"(confidence: {best_confidence}%)"
                )

                return artist, match_record
            else:
                # Artist creation failed (e.g., duplicate MBID, DB error)
                rejection = f"Artist creation failed for MBID {best_match['musicbrainz_id']}"
                logger.warning(f"{rejection} - artist: {artist_name}")

                match_record = LibraryArtistMatch(
                    library_artist_name=artist_name,
                    file_count=file_count,
                    sample_albums=library_artist.get('sample_albums', []),
                    sample_file_paths=library_artist.get('sample_file_paths', []),
                    confidence_score=best_confidence,
                    status='failed',
                    musicbrainz_suggestions=mb_suggestions,
                    rejection_reason=rejection
                )
                return None, match_record

        # Below threshold - manual review required
        rejection = f"Confidence {best_confidence:.1f}% below threshold {confidence_threshold}%"
        match_record = LibraryArtistMatch(
            library_artist_name=artist_name,
            file_count=file_count,
            sample_albums=library_artist.get('sample_albums', []),
            sample_file_paths=library_artist.get('sample_file_paths', []),
            confidence_score=best_confidence if mb_suggestions else 0.0,
            status='manual_review',
            musicbrainz_suggestions=mb_suggestions,
            rejection_reason=rejection
        )

        logger.info(
            f"Manual review required for: {artist_name} "
            f"(best confidence: {best_confidence}%)"
        )

        return None, match_record
