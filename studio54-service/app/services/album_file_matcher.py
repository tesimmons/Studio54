"""
Album File Matcher Service
Scans custom folder paths and matches audio files to album tracks
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from difflib import SequenceMatcher

from app.models.album import Album
from app.models.track import Track
from app.services.metadata_extractor import MetadataExtractor

logger = logging.getLogger(__name__)


class AlbumFileMatcher:
    """
    Service for scanning directories and matching audio files to album tracks
    """

    AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.m4b', '.aac', '.ogg', '.opus', '.wma', '.wav', '.aiff'}

    def __init__(self, db: Session):
        self.db = db
        self.metadata_extractor = MetadataExtractor()

    def scan_and_match_album(self, album_id: str) -> Dict[str, any]:
        """
        Scan an album's custom folder path and match files to tracks

        Args:
            album_id: Album UUID

        Returns:
            Dictionary with match results
        """
        # Eager load artist to avoid N+1 in match scoring
        album = self.db.query(Album).options(
            joinedload(Album.artist)
        ).filter(Album.id == album_id).first()
        if not album:
            raise ValueError(f"Album {album_id} not found")

        if not album.custom_folder_path:
            raise ValueError(f"Album {album_id} has no custom_folder_path set")

        folder_path = Path(album.custom_folder_path)
        if not folder_path.exists():
            raise ValueError(f"Folder path {album.custom_folder_path} does not exist")

        if not folder_path.is_dir():
            raise ValueError(f"Path {album.custom_folder_path} is not a directory")

        logger.info(f"Scanning {folder_path} for album: {album.title}")

        # Find all audio files in the directory
        audio_files = self._find_audio_files(folder_path)
        logger.info(f"Found {len(audio_files)} audio files in {folder_path}")

        if not audio_files:
            return {
                "album_id": str(album_id),
                "folder_path": str(folder_path),
                "files_found": 0,
                "matches": 0,
                "unmatched_files": [],
                "unmatched_tracks": [str(t.id) for t in album.tracks]
            }

        # Extract metadata from all files
        file_metadata = {}
        for file_path in audio_files:
            try:
                metadata = self.metadata_extractor.extract_metadata(str(file_path))
                file_metadata[file_path] = metadata
            except Exception as e:
                logger.warning(f"Failed to extract metadata from {file_path}: {e}")
                file_metadata[file_path] = {}

        # Match files to tracks
        matches = self._match_files_to_tracks(album, file_metadata)

        # Get potential matches for unmatched items (50%+ confidence)
        potential_matches = self._get_potential_matches(album, file_metadata, matches)

        # Update track records with file paths (only auto-matched ones)
        matched_count = 0
        matched_track_ids = set()
        for track_id, file_path in matches.items():
            track = self.db.query(Track).filter(Track.id == track_id).first()
            if track:
                track.file_path = str(file_path)
                track.has_file = True
                matched_count += 1
                matched_track_ids.add(track_id)
                logger.info(f"Matched track '{track.title}' (#{track.track_number}) to {file_path.name}")

        self.db.commit()

        # Identify unmatched items
        unmatched_files = [
            {
                "path": str(f),
                "name": f.name,
                "metadata": file_metadata.get(f, {})
            }
            for f in audio_files if f not in matches.values()
        ]
        unmatched_tracks = [
            {"id": str(t.id), "title": t.title, "track_number": t.track_number}
            for t in album.tracks if t.id not in matched_track_ids
        ]

        return {
            "album_id": str(album_id),
            "album_title": album.title,
            "folder_path": str(folder_path),
            "files_found": len(audio_files),
            "matches": matched_count,
            "unmatched_files": unmatched_files,
            "unmatched_tracks": unmatched_tracks,
            "potential_matches": potential_matches  # NEW: suggestions for manual review
        }

    def _find_audio_files(self, directory: Path) -> List[Path]:
        """
        Find all audio files in a directory (non-recursive)

        Args:
            directory: Path to search

        Returns:
            List of audio file paths
        """
        audio_files = []
        try:
            for item in directory.iterdir():
                if item.is_file() and item.suffix.lower() in self.AUDIO_EXTENSIONS:
                    audio_files.append(item)
        except PermissionError as e:
            logger.error(f"Permission denied reading directory {directory}: {e}")

        return sorted(audio_files)

    def _match_files_to_tracks(
        self,
        album: Album,
        file_metadata: Dict[Path, Dict]
    ) -> Dict[str, Path]:
        """
        Match audio files to album tracks using metadata

        Matching strategy:
        0. MusicBrainz Recording ID (100% accurate if present)
        1. Track number (most reliable)
        2. Title similarity
        3. Duration proximity

        Args:
            album: Album object with tracks
            file_metadata: Dict mapping file paths to extracted metadata

        Returns:
            Dict mapping track IDs to file paths
        """
        matches = {}
        used_files = set()

        # Phase 0: Match by MusicBrainz Recording ID (MBID) - 100% accurate
        for track in album.tracks:
            if not track.musicbrainz_id:
                continue

            for file_path, metadata in file_metadata.items():
                if file_path in used_files:
                    continue

                # Check if file has Recording MBID that matches track
                file_mbid = metadata.get('musicbrainz_trackid')
                if file_mbid and file_mbid.lower() == track.musicbrainz_id.lower():
                    matches[track.id] = file_path
                    used_files.add(file_path)
                    logger.info(f"MBID match: Track '{track.title}' matched to {file_path.name} via Recording MBID")
                    break

        # Phase 1: Match by track number (most reliable)
        for track in album.tracks:
            if track.id in matches:  # Skip if already matched by MBID
                continue

            if not track.track_number:
                continue

            for file_path, metadata in file_metadata.items():
                if file_path in used_files:
                    continue

                file_track_num = metadata.get('track_number')
                if file_track_num and int(file_track_num) == track.track_number:
                    # Verify it's reasonable (check title similarity or album match)
                    if self._is_reasonable_match(track, album, metadata):
                        matches[track.id] = file_path
                        used_files.add(file_path)
                        break

        # Phase 2: Match by title similarity for unmatched tracks
        unmatched_tracks = [t for t in album.tracks if t.id not in matches]
        unmatched_files = {fp: meta for fp, meta in file_metadata.items() if fp not in used_files}

        for track in unmatched_tracks:
            best_match = None
            best_score = 0.0

            for file_path, metadata in unmatched_files.items():
                score = self._calculate_match_score(track, album, metadata)
                if score > best_score and score >= 0.6:  # Minimum 60% confidence
                    best_score = score
                    best_match = file_path

            if best_match:
                matches[track.id] = best_match
                used_files.add(best_match)
                unmatched_files.pop(best_match)

        return matches

    def _is_reasonable_match(self, track: Track, album: Album, metadata: Dict) -> bool:
        """
        Verify that a track number match is reasonable by checking other fields

        Args:
            track: Track object
            album: Album object
            metadata: File metadata dict

        Returns:
            True if match seems reasonable
        """
        # Check album title
        file_album = metadata.get('album', '').lower()
        if file_album and album.title.lower() in file_album or file_album in album.title.lower():
            return True

        # Check title similarity
        file_title = metadata.get('title', '').lower()
        track_title = track.title.lower()
        if file_title and self._string_similarity(file_title, track_title) > 0.5:
            return True

        # If track number matches and we have some metadata, accept it
        if file_album or file_title:
            return True

        return False

    def _calculate_match_score(self, track: Track, album: Album, metadata: Dict) -> float:
        """
        Calculate match score between a track and file metadata

        Args:
            track: Track object
            album: Album object
            metadata: File metadata dict

        Returns:
            Match score between 0.0 and 1.0
        """
        score = 0.0
        weights = []

        # Title similarity (40% weight)
        file_title = metadata.get('title', '').lower()
        if file_title:
            title_sim = self._string_similarity(track.title.lower(), file_title)
            score += title_sim * 0.4
            weights.append(0.4)

        # Album similarity (30% weight)
        file_album = metadata.get('album', '').lower()
        if file_album:
            album_sim = self._string_similarity(album.title.lower(), file_album)
            score += album_sim * 0.3
            weights.append(0.3)

        # Duration proximity (20% weight)
        file_duration = metadata.get('duration_ms')
        if file_duration and track.duration_ms:
            duration_diff = abs(file_duration - track.duration_ms)
            # Allow 5 second variance
            if duration_diff < 5000:
                duration_score = 1.0 - (duration_diff / 5000.0)
                score += duration_score * 0.2
                weights.append(0.2)

        # Artist similarity (10% weight)
        file_artist = metadata.get('artist', '').lower()
        album_artist = album.artist.name.lower() if album.artist else ''
        if file_artist and album_artist:
            artist_sim = self._string_similarity(album_artist, file_artist)
            score += artist_sim * 0.1
            weights.append(0.1)

        # Normalize score by actual weights used
        if weights:
            return score / sum(weights)
        return 0.0

    def _string_similarity(self, s1: str, s2: str) -> float:
        """
        Calculate string similarity ratio

        Args:
            s1: First string
            s2: Second string

        Returns:
            Similarity ratio between 0.0 and 1.0
        """
        return SequenceMatcher(None, s1, s2).ratio()

    def _get_potential_matches(
        self,
        album: Album,
        file_metadata: Dict[Path, Dict],
        confirmed_matches: Dict[str, Path]
    ) -> List[Dict]:
        """
        Get potential matches for unmatched tracks (50%+ confidence)

        Args:
            album: Album object
            file_metadata: Dict mapping file paths to metadata
            confirmed_matches: Already confirmed matches (to exclude)

        Returns:
            List of potential matches with scores
        """
        potential_matches = []
        used_files = set(confirmed_matches.values())
        matched_track_ids = set(confirmed_matches.keys())

        # Get unmatched tracks and ALL files (don't filter by used_files)
        unmatched_tracks = [t for t in album.tracks if t.id not in matched_track_ids]
        # Show ALL files in directory, even if already matched to other tracks
        # This allows manual linking of the same file to multiple tracks
        all_files = file_metadata

        # Calculate scores for all combinations
        for track in unmatched_tracks:
            track_suggestions = []

            for file_path, metadata in all_files.items():
                score = self._calculate_match_score(track, album, metadata)

                # ALWAYS show all files, regardless of score
                # This allows manual linking of any file to any track
                track_suggestions.append({
                    "file_path": str(file_path),
                    "file_name": file_path.name,
                    "confidence": round(score * 100, 1),  # Convert to percentage
                    "metadata": {
                        "title": metadata.get('title', 'No metadata'),
                        "artist": metadata.get('artist', 'No metadata'),
                        "album": metadata.get('album', 'No metadata'),
                        "track_number": metadata.get('track_number'),
                        "duration_ms": metadata.get('duration_ms')
                    }
                })

            # Sort by confidence (highest first)
            track_suggestions.sort(key=lambda x: x['confidence'], reverse=True)

            # ALWAYS include the track in results, even if no files
            # Show ALL files (removed [:10] limit)
            potential_matches.append({
                "track_id": str(track.id),
                "track_title": track.title,
                "track_number": track.track_number,
                "suggestions": track_suggestions  # Show ALL files
            })

        return potential_matches

    def manually_link_track(self, track_id: str, file_path: str) -> bool:
        """
        Manually link a track to a file

        Args:
            track_id: Track UUID
            file_path: Absolute path to audio file

        Returns:
            True if successful
        """
        track = self.db.query(Track).filter(Track.id == track_id).first()
        if not track:
            raise ValueError(f"Track {track_id} not found")

        file = Path(file_path)
        if not file.exists():
            raise ValueError(f"File {file_path} does not exist")

        track.file_path = str(file_path)
        track.has_file = True
        self.db.commit()

        logger.info(f"Manually linked track '{track.title}' to {file.name}")
        return True
