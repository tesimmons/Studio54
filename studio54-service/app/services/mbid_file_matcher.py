"""
MBID File Matcher Service
Rapidly matches library files to tracks using MusicBrainz Recording IDs from file metadata
"""

import logging
import re
from typing import List, Dict, Tuple, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from uuid import UUID

from app.models.library import LibraryFile
from app.models.track import Track
from app.models.album import Album
from app.models.artist import Artist

logger = logging.getLogger(__name__)


class MBIDFileMatcher:
    """
    Service for matching library files to tracks using MBID from comment fields

    MUSE Ponder stores MBIDs in comment field format:
    RecordingMBID:<uuid> | ArtistMBID:<uuid> | ReleaseMBID:<uuid> | ReleaseGroupMBID:<uuid>

    This service parses those MBIDs and matches files to tracks instantly.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def parse_mbids_from_comment(comment: str) -> Dict[str, Optional[str]]:
        """
        Parse MBIDs from MUSE Ponder comment field

        Args:
            comment: Comment field from file metadata

        Returns:
            Dict with recording_mbid, artist_mbid, release_mbid, release_group_mbid
        """
        if not comment:
            return {
                'recording_mbid': None,
                'artist_mbid': None,
                'release_mbid': None,
                'release_group_mbid': None
            }

        result = {
            'recording_mbid': None,
            'artist_mbid': None,
            'release_mbid': None,
            'release_group_mbid': None
        }

        # Pattern: RecordingMBID:<uuid>
        recording_match = re.search(r'RecordingMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if recording_match:
            result['recording_mbid'] = recording_match.group(1)

        # Pattern: ArtistMBID:<uuid>
        artist_match = re.search(r'ArtistMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if artist_match:
            result['artist_mbid'] = artist_match.group(1)

        # Pattern: ReleaseMBID:<uuid>
        release_match = re.search(r'ReleaseMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if release_match:
            result['release_mbid'] = release_match.group(1)

        # Pattern: ReleaseGroupMBID:<uuid>
        release_group_match = re.search(r'ReleaseGroupMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if release_group_match:
            result['release_group_mbid'] = release_group_match.group(1)

        return result

    def match_file_by_recording_mbid(
        self,
        library_file: LibraryFile,
        artist_id: Optional[UUID] = None
    ) -> Optional[Track]:
        """
        Match a library file to a track using Recording MBID

        Args:
            library_file: LibraryFile with comment field
            artist_id: Optional artist ID to narrow search

        Returns:
            Matched Track or None
        """
        # Try direct MBID field first (populated by Phase 1 fast extractor)
        recording_mbid = library_file.musicbrainz_trackid

        # Fallback: parse from comment in metadata_json
        if not recording_mbid:
            comment = None
            if library_file.metadata_json and 'comment' in library_file.metadata_json:
                comment = library_file.metadata_json['comment']
            if comment:
                mbids = self.parse_mbids_from_comment(comment)
                recording_mbid = mbids.get('recording_mbid')

        if not recording_mbid:
            return None

        # Find all tracks with matching recording MBID (eager load album for scoring)
        query = self.db.query(Track).options(
            joinedload(Track.album)
        ).filter(
            Track.musicbrainz_id == recording_mbid
        )

        # Optionally filter by artist
        if artist_id:
            query = query.join(Album).filter(Album.artist_id == artist_id)

        candidates = query.all()

        if not candidates:
            return None

        if len(candidates) == 1:
            track = candidates[0]
        else:
            # Multiple candidates - score using release-group match and album type
            file_rg_mbid = library_file.musicbrainz_releasegroupid

            def _score(t):
                score = 0
                # Release Group MBID match (+1000)
                if file_rg_mbid and t.album and t.album.musicbrainz_id == file_rg_mbid:
                    score += 1000
                # Non-compilation preference (+50)
                if t.album and not (t.album.secondary_types and 'compilation' in t.album.secondary_types.lower()):
                    score += 50
                return score

            track = max(candidates, key=_score)

        logger.info(
            f"Matched file '{library_file.file_path}' to track '{track.title}' "
            f"(Album: {track.album.title}) via Recording MBID: {recording_mbid}"
            + (f" (selected from {len(candidates)} candidates)" if len(candidates) > 1 else "")
        )

        return track

    def match_artist_files(
        self,
        artist_id: UUID,
        library_path_id: Optional[UUID] = None
    ) -> Dict[str, int]:
        """
        Match all library files for an artist using Recording MBIDs

        This is called immediately after syncing artist metadata to rapidly
        match files while the data is hot in cache.

        Args:
            artist_id: Artist UUID
            library_path_id: Optional library path to limit search

        Returns:
            Statistics dict with matched/unmatched counts
        """
        logger.info(f"Starting rapid MBID file matching for artist: {artist_id}")

        # Get artist
        artist = self.db.query(Artist).filter(Artist.id == artist_id).first()
        if not artist:
            logger.error(f"Artist not found: {artist_id}")
            return {'matched': 0, 'unmatched': 0, 'errors': 0}

        # Get all tracks for this artist (eager load album for later access)
        tracks = self.db.query(Track).options(
            joinedload(Track.album)
        ).join(Album).filter(
            Album.artist_id == artist_id,
            Track.musicbrainz_id.isnot(None)
        ).all()

        if not tracks:
            logger.warning(f"No tracks with MBIDs found for artist: {artist.name}")
            return {'matched': 0, 'unmatched': 0, 'errors': 0}

        # Create MBID -> Track mapping (keep all candidates per MBID)
        from collections import defaultdict
        mbid_to_tracks = defaultdict(list)
        for track in tracks:
            mbid_to_tracks[track.musicbrainz_id].append(track)
        recording_mbids = list(mbid_to_tracks.keys())

        logger.info(f"Found {len(recording_mbids)} tracks with MBIDs for {artist.name}")

        # Get library files that might match
        # Filter by artist MBID or name, and require either direct MBID fields or metadata_json
        from sqlalchemy import or_
        query = self.db.query(LibraryFile)

        if library_path_id:
            query = query.filter(LibraryFile.library_path_id == library_path_id)

        # Filter by artist MBID or name
        if artist.musicbrainz_id:
            query = query.filter(
                LibraryFile.musicbrainz_artistid == artist.musicbrainz_id
            )
        else:
            query = query.filter(
                LibraryFile.artist.ilike(f"%{artist.name}%")
            )

        # Only include files that have MBID data (either direct field or in metadata_json)
        query = query.filter(
            or_(
                LibraryFile.musicbrainz_trackid.isnot(None),
                LibraryFile.metadata_json.isnot(None)
            )
        )

        library_files = query.all()
        logger.info(f"Found {len(library_files)} library files for {artist.name}")

        matched = 0
        unmatched = 0
        errors = 0

        # Track album match counts for cohort-aware scoring
        album_match_counts = defaultdict(int)

        def _is_compilation(album):
            return album and album.secondary_types and 'compilation' in album.secondary_types.lower()

        def _score_track(track, file_rg_mbid, use_cohort=True):
            score = 0
            if file_rg_mbid and track.album and track.album.musicbrainz_id == file_rg_mbid:
                score += 1000
            if not _is_compilation(track.album):
                score += 50
            if use_cohort and track.album:
                score += album_match_counts.get(str(track.album_id), 0)
            return score

        def _pick_best_track(candidates, file_rg_mbid):
            if len(candidates) == 1:
                return candidates[0]
            return max(candidates, key=lambda t: _score_track(t, file_rg_mbid))

        for lib_file in library_files:
            try:
                # Try direct MBID field first
                recording_mbid = lib_file.musicbrainz_trackid

                # Fallback: parse from comment in metadata_json
                if not recording_mbid:
                    if lib_file.metadata_json and 'comment' in lib_file.metadata_json:
                        mbids = self.parse_mbids_from_comment(lib_file.metadata_json['comment'])
                        recording_mbid = mbids.get('recording_mbid')

                if not recording_mbid:
                    unmatched += 1
                    continue

                # Check if we have tracks with this MBID
                candidates = mbid_to_tracks.get(recording_mbid)
                if not candidates:
                    unmatched += 1
                    continue

                # Pick best track using album-aware scoring
                file_rg_mbid = lib_file.musicbrainz_releasegroupid
                track = _pick_best_track(candidates, file_rg_mbid)

                if track.file_path == lib_file.file_path and track.has_file:
                    continue  # Already matched to this exact file
                track.file_path = lib_file.file_path
                track.has_file = True
                matched += 1

                # Update cohort counts
                album_match_counts[str(track.album_id)] += 1

                logger.debug(
                    f"Matched '{lib_file.file_name}' to '{track.title}' "
                    f"on album '{track.album.title}'"
                    + (f" (selected from {len(candidates)} candidates)" if len(candidates) > 1 else "")
                )

            except Exception as e:
                logger.error(f"Error matching file {lib_file.file_path}: {e}")
                errors += 1

        # Commit all matches
        self.db.commit()

        logger.info(
            f"Rapid MBID matching complete for {artist.name}: "
            f"{matched} matched, {unmatched} unmatched, {errors} errors"
        )

        return {
            'matched': matched,
            'unmatched': unmatched,
            'errors': errors
        }

    def match_all_artists(
        self,
        artist_ids: List[UUID],
        library_path_id: Optional[UUID] = None
    ) -> Dict[str, int]:
        """
        Match files for multiple artists

        Args:
            artist_ids: List of artist UUIDs
            library_path_id: Optional library path to limit search

        Returns:
            Aggregated statistics
        """
        total_stats = {'matched': 0, 'unmatched': 0, 'errors': 0}

        for artist_id in artist_ids:
            stats = self.match_artist_files(artist_id, library_path_id)
            total_stats['matched'] += stats['matched']
            total_stats['unmatched'] += stats['unmatched']
            total_stats['errors'] += stats['errors']

        logger.info(
            f"Rapid MBID matching complete for {len(artist_ids)} artists: "
            f"{total_stats['matched']} matched, "
            f"{total_stats['unmatched']} unmatched, "
            f"{total_stats['errors']} errors"
        )

        return total_stats
