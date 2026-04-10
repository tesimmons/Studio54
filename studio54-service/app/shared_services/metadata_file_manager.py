"""
Metadata File Manager Service

Creates and manages .mbid.json files in album directories:
- Create .mbid.json files with album MBIDs and track lists
- Validate files against expected tracks
- Detect missing or extra files
- Track file organization status
"""

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from uuid import UUID
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


@dataclass
class TrackMetadata:
    """Track metadata for .mbid.json file"""
    track_number: int
    disc_number: int
    title: str
    duration: Optional[int] = None
    recording_mbid: Optional[str] = None
    expected_filename: Optional[str] = None
    file_present: bool = False
    file_path: Optional[str] = None


@dataclass
class AlbumMetadata:
    """Album metadata structure for .mbid.json file"""
    version: str = "1.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    album: Optional[Dict[str, Any]] = None
    mbids: Optional[Dict[str, Any]] = None
    tracks: Optional[List[Dict[str, Any]]] = None
    validation: Optional[Dict[str, Any]] = None
    organization: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'version': self.version,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'album': self.album or {},
            'mbids': self.mbids or {},
            'tracks': self.tracks or [],
            'validation': self.validation or {},
            'organization': self.organization or {}
        }


@dataclass
class ValidationResult:
    """Result of album directory validation"""
    status: str  # 'valid', 'missing_files', 'extra_files', 'invalid'
    metadata_exists: bool = False
    expected_tracks: int = 0
    found_tracks: int = 0
    missing_tracks: List[Dict[str, Any]] = None
    extra_files: List[Dict[str, Any]] = None
    metadata_file_path: Optional[str] = None

    def __post_init__(self):
        if self.missing_tracks is None:
            self.missing_tracks = []
        if self.extra_files is None:
            self.extra_files = []


class MetadataFileManager:
    """
    Service for creating and managing .mbid.json files

    Features:
    - Create metadata files in album directories
    - Store album MBIDs and track lists
    - Validate files against track list
    - Detect missing or extra files
    - Update validation status
    """

    METADATA_FILENAME = ".mbid.json"
    SUPPORTED_AUDIO_EXTENSIONS = {'.flac', '.mp3', '.m4a', '.m4b', '.aac', '.ogg', '.opus', '.wav', '.wma'}

    def __init__(self, db: Session):
        """
        Initialize MetadataFileManager service

        Args:
            db: Database session
        """
        self.db = db
        logger.info("MetadataFileManager initialized")

    def create_album_metadata_file(
        self,
        album_id: UUID,
        album_directory: str,
        album_title: str,
        artist_name: str,
        artist_mbid: Optional[UUID] = None,
        release_year: Optional[int] = None,
        album_type: str = "Album",
        total_discs: int = 1,
        total_tracks: int = 0,
        recording_mbids: Optional[List[UUID]] = None,
        release_mbid: Optional[UUID] = None,
        release_group_mbid: Optional[UUID] = None,
        tracks: Optional[List[TrackMetadata]] = None,
        organization_job_id: Optional[UUID] = None,
        organized_by: str = "system"
    ) -> Optional[str]:
        """
        Create .mbid.json file in album directory

        Args:
            album_id: Album UUID
            album_directory: Album directory path
            album_title: Album title
            artist_name: Artist name
            artist_mbid: Artist MusicBrainz ID
            release_year: Album release year
            album_type: Album type (Album, EP, Single, etc.)
            total_discs: Total number of discs
            total_tracks: Total number of tracks
            recording_mbids: List of recording MBIDs
            release_mbid: Release MBID
            release_group_mbid: Release Group MBID
            tracks: List of track metadata
            organization_job_id: Organization job ID
            organized_by: Who organized the files

        Returns:
            Path to created metadata file or None if failed
        """
        try:
            album_dir_path = Path(album_directory)

            if not album_dir_path.exists():
                logger.error(f"Album directory does not exist: {album_directory}")
                return None

            # Build metadata structure
            now = datetime.now().isoformat()

            metadata = AlbumMetadata(
                version="1.0",
                created_at=now,
                updated_at=now,
                album={
                    'title': album_title,
                    'artist': artist_name,
                    'artist_mbid': str(artist_mbid) if artist_mbid else None,
                    'release_year': release_year,
                    'album_type': album_type,
                    'total_discs': total_discs,
                    'total_tracks': total_tracks
                },
                mbids={
                    'recording_mbids': [str(mbid) for mbid in (recording_mbids or [])],
                    'release_mbid': str(release_mbid) if release_mbid else None,
                    'release_group_mbid': str(release_group_mbid) if release_group_mbid else None
                },
                tracks=[asdict(track) for track in (tracks or [])],
                validation={
                    'status': 'pending',
                    'missing_tracks': [],
                    'extra_files': [],
                    'last_validated': None
                },
                organization={
                    'organized': True,
                    'organized_at': now,
                    'organized_by': organized_by,
                    'organization_job_id': str(organization_job_id) if organization_job_id else None
                }
            )

            # Write to file
            metadata_path = album_dir_path / self.METADATA_FILENAME

            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info(f"Created metadata file: {metadata_path}")

            # Store in database
            self._store_metadata_in_db(
                album_id=album_id,
                file_path=str(metadata_path),
                album_directory=album_directory,
                metadata=metadata
            )

            return str(metadata_path)

        except Exception as e:
            logger.error(f"Error creating metadata file: {e}")
            return None

    def read_metadata_file(self, metadata_file_path: str) -> Optional[AlbumMetadata]:
        """
        Read .mbid.json metadata file

        Args:
            metadata_file_path: Path to metadata file

        Returns:
            AlbumMetadata object or None if failed
        """
        try:
            metadata_path = Path(metadata_file_path)

            if not metadata_path.exists():
                logger.error(f"Metadata file does not exist: {metadata_file_path}")
                return None

            with open(metadata_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            metadata = AlbumMetadata(
                version=data.get('version', '1.0'),
                created_at=data.get('created_at'),
                updated_at=data.get('updated_at'),
                album=data.get('album', {}),
                mbids=data.get('mbids', {}),
                tracks=data.get('tracks', []),
                validation=data.get('validation', {}),
                organization=data.get('organization', {})
            )

            return metadata

        except Exception as e:
            logger.error(f"Error reading metadata file: {e}")
            return None

    def update_metadata_file(
        self,
        metadata_file_path: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update existing metadata file

        Args:
            metadata_file_path: Path to metadata file
            updates: Dictionary of updates to apply

        Returns:
            True if successful
        """
        try:
            # Read existing metadata
            metadata = self.read_metadata_file(metadata_file_path)

            if not metadata:
                return False

            # Apply updates
            metadata.updated_at = datetime.now().isoformat()

            for key, value in updates.items():
                if hasattr(metadata, key):
                    setattr(metadata, key, value)

            # Write back
            with open(metadata_file_path, 'w', encoding='utf-8') as f:
                json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info(f"Updated metadata file: {metadata_file_path}")

            return True

        except Exception as e:
            logger.error(f"Error updating metadata file: {e}")
            return False

    def validate_album_directory(
        self,
        album_directory: str,
        album_id: Optional[UUID] = None
    ) -> ValidationResult:
        """
        Validate album directory against metadata file

        Checks:
        - All expected tracks present
        - No unexpected audio files
        - Filenames match expected format

        Args:
            album_directory: Album directory path
            album_id: Optional album ID for database lookup

        Returns:
            ValidationResult with status and issues
        """
        result = ValidationResult(status='valid')

        try:
            album_dir_path = Path(album_directory)

            if not album_dir_path.exists():
                result.status = 'invalid'
                return result

            # Check for metadata file
            metadata_path = album_dir_path / self.METADATA_FILENAME
            result.metadata_file_path = str(metadata_path)

            if not metadata_path.exists():
                result.metadata_exists = False
                result.status = 'no_metadata'
                return result

            result.metadata_exists = True

            # Read metadata
            metadata = self.read_metadata_file(str(metadata_path))

            if not metadata:
                result.status = 'invalid_metadata'
                return result

            # Get expected tracks
            expected_tracks = metadata.tracks or []
            result.expected_tracks = len(expected_tracks)

            # Get actual audio files in directory
            actual_files = self._get_audio_files(album_dir_path)

            # Check for expected tracks
            for track in expected_tracks:
                expected_filename = track.get('expected_filename')

                if not expected_filename:
                    continue

                file_found = any(
                    f.name == expected_filename or f.name == Path(track.get('file_path', '')).name
                    for f in actual_files
                )

                if not file_found:
                    result.missing_tracks.append({
                        'track_number': track.get('track_number'),
                        'title': track.get('title'),
                        'expected_filename': expected_filename
                    })

            # Check for extra files
            expected_filenames = {
                track.get('expected_filename') or Path(track.get('file_path', '')).name
                for track in expected_tracks
            }

            for actual_file in actual_files:
                if actual_file.name not in expected_filenames:
                    result.extra_files.append({
                        'filename': actual_file.name,
                        'should_ignore': self._should_ignore_file(actual_file)
                    })

            result.found_tracks = len(actual_files)

            # Determine final status
            if result.missing_tracks and result.extra_files:
                result.status = 'mixed_issues'
            elif result.missing_tracks:
                result.status = 'missing_files'
            elif result.extra_files:
                # Filter out files that should be ignored (cover art, etc.)
                extra_audio = [f for f in result.extra_files if not f.get('should_ignore', False)]
                if extra_audio:
                    result.status = 'extra_files'
                else:
                    result.status = 'valid'
            else:
                result.status = 'valid'

            # Update metadata file with validation result
            self.update_metadata_file(str(metadata_path), {
                'validation': {
                    'status': result.status,
                    'missing_tracks': result.missing_tracks,
                    'extra_files': result.extra_files,
                    'last_validated': datetime.now().isoformat()
                }
            })

            logger.info(f"Validated album directory: {album_directory} - Status: {result.status}")

            return result

        except Exception as e:
            logger.error(f"Error validating album directory: {e}")
            result.status = 'validation_error'
            return result

    def find_misplaced_files(
        self,
        album_directory: str
    ) -> List[Dict[str, Any]]:
        """
        Find files that don't belong in this album

        Uses MBID in file metadata to determine correct album

        Args:
            album_directory: Album directory path

        Returns:
            List of misplaced files with details
        """
        misplaced = []

        try:
            album_dir_path = Path(album_directory)

            # Read metadata
            metadata_path = album_dir_path / self.METADATA_FILENAME

            if not metadata_path.exists():
                return misplaced

            metadata = self.read_metadata_file(str(metadata_path))

            if not metadata:
                return misplaced

            # Get expected recording MBIDs
            expected_mbids = set(metadata.mbids.get('recording_mbids', []))

            # Check each audio file
            audio_files = self._get_audio_files(album_dir_path)

            for audio_file in audio_files:
                # This would require reading file metadata with mutagen
                # Placeholder for now
                file_mbid = self._get_file_recording_mbid(audio_file)

                if file_mbid and file_mbid not in expected_mbids:
                    misplaced.append({
                        'filename': audio_file.name,
                        'file_path': str(audio_file),
                        'recording_mbid': file_mbid,
                        'reason': 'mbid_mismatch'
                    })

            logger.info(f"Found {len(misplaced)} misplaced files in {album_directory}")

            return misplaced

        except Exception as e:
            logger.error(f"Error finding misplaced files: {e}")
            return []

    # ========================================
    # Private helper methods
    # ========================================

    def _get_audio_files(self, directory: Path) -> List[Path]:
        """Get all audio files in directory"""
        audio_files = []

        for file_path in directory.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_AUDIO_EXTENSIONS:
                audio_files.append(file_path)

        return audio_files

    def _should_ignore_file(self, file_path: Path) -> bool:
        """Check if file should be ignored (cover art, logs, etc.)"""
        ignore_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.txt', '.log', '.m3u', '.cue', '.nfo'}
        ignore_names = {'cover.jpg', 'folder.jpg', 'albumart.jpg', 'thumb.jpg'}

        return (
            file_path.suffix.lower() in ignore_extensions or
            file_path.name.lower() in ignore_names or
            file_path.name.startswith('.')
        )

    def _get_file_recording_mbid(self, file_path: Path) -> Optional[str]:
        """
        Get recording MBID from file metadata

        This would use mutagen to read file tags
        Placeholder for now

        Args:
            file_path: Path to audio file

        Returns:
            Recording MBID or None
        """
        # TODO: Implement with mutagen
        # from mutagen import File
        # audio = File(file_path)
        # return audio.get('musicbrainz_trackid')
        return None

    def _store_metadata_in_db(
        self,
        album_id: UUID,
        file_path: str,
        album_directory: str,
        metadata: AlbumMetadata
    ):
        """Store metadata file info in database"""
        try:
            from sqlalchemy import text

            # Extract MBIDs from metadata
            release_mbid = metadata.mbids.get('release_mbid')
            release_group_mbid = metadata.mbids.get('release_group_mbid')
            artist_mbid = metadata.album.get('artist_mbid')

            query = text("""
                INSERT INTO album_metadata_files (
                    album_id,
                    album_directory,
                    file_path,
                    album_mbid,
                    release_mbid,
                    release_group_mbid,
                    artist_mbid,
                    artist_name,
                    album_title,
                    release_year,
                    track_count,
                    tracks_json,
                    validation_status,
                    created_at,
                    updated_at
                ) VALUES (
                    :album_id,
                    :album_directory,
                    :file_path,
                    :album_mbid,
                    :release_mbid,
                    :release_group_mbid,
                    :artist_mbid,
                    :artist_name,
                    :album_title,
                    :release_year,
                    :track_count,
                    :tracks_json,
                    :validation_status,
                    NOW(),
                    NOW()
                )
                ON CONFLICT (album_directory) DO UPDATE SET
                    updated_at = NOW(),
                    file_path = EXCLUDED.file_path,
                    tracks_json = EXCLUDED.tracks_json,
                    validation_status = EXCLUDED.validation_status
            """)

            self.db.execute(query, {
                'album_id': str(album_id) if album_id else None,
                'album_directory': album_directory,
                'file_path': file_path,
                'album_mbid': release_group_mbid,  # Use release_group_mbid as album_mbid
                'release_mbid': release_mbid,
                'release_group_mbid': release_group_mbid,
                'artist_mbid': artist_mbid,
                'artist_name': metadata.album.get('artist'),
                'album_title': metadata.album.get('title'),
                'release_year': metadata.album.get('release_year'),
                'track_count': len(metadata.tracks or []),
                'tracks_json': json.dumps(metadata.tracks or []),
                'validation_status': 'pending'
            })

            self.db.commit()

            logger.debug(f"Stored metadata file info in database: {file_path}")

        except Exception as e:
            logger.error(f"Error storing metadata in database: {e}")
            self.db.rollback()

    def regenerate_metadata_file(
        self,
        album_id: UUID,
        album_directory: str
    ) -> Optional[str]:
        """
        Regenerate metadata file from database

        Useful for repairing corrupted or deleted metadata files

        Args:
            album_id: Album UUID
            album_directory: Album directory path

        Returns:
            Path to regenerated file or None
        """
        # This would query the database for album/track info
        # and recreate the metadata file
        # Placeholder for now
        logger.info(f"Regenerating metadata file for album {album_id}")
        return None
