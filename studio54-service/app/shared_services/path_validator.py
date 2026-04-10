"""
Path Validator Service

Validates existing directory structures and identifies issues:
- Scan existing directory structures
- Compare against database records
- Identify misnamed files/folders
- Queue correction jobs
- Validate artist directory names
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.orm import Session

from .naming_engine import NamingEngine, TrackContext, AlbumContext, ArtistContext


logger = logging.getLogger(__name__)


@dataclass
class MisnamedFile:
    """File with incorrect name"""
    file_id: Optional[UUID]
    current_path: str
    expected_path: str
    current_filename: str
    expected_filename: str
    issue_type: str  # 'incorrect_format', 'wrong_track_number', 'wrong_title', etc.
    track_id: Optional[UUID] = None
    album_id: Optional[UUID] = None
    artist_id: Optional[UUID] = None


@dataclass
class MisplacedFile:
    """File in wrong directory"""
    file_id: Optional[UUID]
    current_path: str
    expected_path: str
    current_directory: str
    expected_directory: str
    reason: str  # 'wrong_album', 'wrong_artist', 'mbid_mismatch', etc.
    track_id: Optional[UUID] = None
    album_id: Optional[UUID] = None
    artist_id: Optional[UUID] = None


@dataclass
class IncorrectDirectory:
    """Incorrectly named directory"""
    current_path: str
    expected_path: str
    current_name: str
    expected_name: str
    directory_type: str  # 'artist', 'album'
    affected_files: int = 0
    artist_id: Optional[UUID] = None
    album_id: Optional[UUID] = None


@dataclass
class ValidationResult:
    """Result of path validation"""
    is_valid: bool
    total_files: int = 0
    valid_files: int = 0
    misnamed_files: List[MisnamedFile] = None
    misplaced_files: List[MisplacedFile] = None
    incorrect_directories: List[IncorrectDirectory] = None
    issues_summary: Dict[str, int] = None

    def __post_init__(self):
        if self.misnamed_files is None:
            self.misnamed_files = []
        if self.misplaced_files is None:
            self.misplaced_files = []
        if self.incorrect_directories is None:
            self.incorrect_directories = []
        if self.issues_summary is None:
            self.issues_summary = {}


class PathValidator:
    """
    Service for validating directory structures

    Features:
    - Validate all files for an artist
    - Check artist directory names
    - Check album directory names
    - Identify misnamed files
    - Identify misplaced files
    - Generate correction recommendations
    """

    def __init__(
        self,
        db: Session,
        naming_engine: Optional[NamingEngine] = None
    ):
        """
        Initialize PathValidator service

        Args:
            db: Database session
            naming_engine: NamingEngine instance (creates default if None)
        """
        self.db = db
        self.naming_engine = naming_engine or NamingEngine()
        logger.info("PathValidator initialized")

    def validate_artist_structure(
        self,
        artist_id: UUID,
        library_root: str
    ) -> ValidationResult:
        """
        Validate all files for an artist

        Checks:
        - Artist directory name matches database
        - Album directories correctly named
        - Files in correct albums
        - All files following naming convention

        Args:
            artist_id: Artist UUID
            library_root: Root directory of library

        Returns:
            ValidationResult with all issues found
        """
        result = ValidationResult(is_valid=True)

        try:
            logger.info(f"Validating structure for artist {artist_id}")

            # Get artist info
            artist_info = self._get_artist_info(artist_id)

            if not artist_info:
                logger.error(f"Artist not found: {artist_id}")
                result.is_valid = False
                return result

            artist_name = artist_info.get('name', 'Unknown Artist')

            # Check artist directory
            artist_dir_issues = self._validate_artist_directory(
                artist_id=artist_id,
                artist_name=artist_name,
                library_root=library_root
            )

            if artist_dir_issues:
                result.incorrect_directories.extend(artist_dir_issues)

            # Get all tracks for artist
            tracks = self._get_artist_tracks(artist_id)
            result.total_files = len(tracks)

            logger.info(f"Validating {result.total_files} tracks for {artist_name}")

            # Validate each track
            for track in tracks:
                # Build track context
                track_context = self._build_track_context(track)

                # Calculate expected path
                expected_filename = self.naming_engine.generate_track_filename(track_context)
                expected_full_path = str(Path(library_root) / expected_filename)

                current_path = track.get('file_path', '')

                # Check if file is correctly named and placed
                if current_path == expected_full_path:
                    result.valid_files += 1
                    continue

                # Determine issue type
                current_filename = Path(current_path).name
                expected_filename_only = Path(expected_full_path).name

                current_directory = str(Path(current_path).parent)
                expected_directory = str(Path(expected_full_path).parent)

                # Check if it's a filename issue or directory issue
                if current_directory == expected_directory:
                    # Same directory, different filename - misnamed
                    result.misnamed_files.append(MisnamedFile(
                        file_id=track.get('file_id'),
                        current_path=current_path,
                        expected_path=expected_full_path,
                        current_filename=current_filename,
                        expected_filename=expected_filename_only,
                        issue_type=self._determine_filename_issue(current_filename, expected_filename_only),
                        track_id=track.get('track_id'),
                        album_id=track.get('album_id'),
                        artist_id=artist_id
                    ))
                else:
                    # Different directory - misplaced
                    result.misplaced_files.append(MisplacedFile(
                        file_id=track.get('file_id'),
                        current_path=current_path,
                        expected_path=expected_full_path,
                        current_directory=current_directory,
                        expected_directory=expected_directory,
                        reason=self._determine_misplacement_reason(current_directory, expected_directory),
                        track_id=track.get('track_id'),
                        album_id=track.get('album_id'),
                        artist_id=artist_id
                    ))

            # Generate summary
            result.issues_summary = {
                'misnamed_files': len(result.misnamed_files),
                'misplaced_files': len(result.misplaced_files),
                'incorrect_directories': len(result.incorrect_directories),
                'valid_files': result.valid_files,
                'total_issues': len(result.misnamed_files) + len(result.misplaced_files) + len(result.incorrect_directories)
            }

            result.is_valid = result.issues_summary['total_issues'] == 0

            logger.info(
                f"Validation complete for {artist_name}: "
                f"{result.valid_files}/{result.total_files} valid, "
                f"{result.issues_summary['total_issues']} issues found"
            )

            return result

        except Exception as e:
            logger.error(f"Error validating artist structure: {e}")
            result.is_valid = False
            return result

    def validate_library_structure(
        self,
        library_path_id: UUID,
        library_root: str
    ) -> ValidationResult:
        """
        Validate entire library structure

        Args:
            library_path_id: Library path UUID
            library_root: Root directory of library

        Returns:
            ValidationResult with all issues found
        """
        result = ValidationResult(is_valid=True)

        try:
            logger.info(f"Validating library structure: {library_root}")

            # Get all artists in library
            artists = self._get_library_artists(library_path_id)

            logger.info(f"Found {len(artists)} artists in library")

            # Validate each artist
            for artist in artists:
                artist_result = self.validate_artist_structure(
                    artist_id=artist['artist_id'],
                    library_root=library_root
                )

                # Aggregate results
                result.total_files += artist_result.total_files
                result.valid_files += artist_result.valid_files
                result.misnamed_files.extend(artist_result.misnamed_files)
                result.misplaced_files.extend(artist_result.misplaced_files)
                result.incorrect_directories.extend(artist_result.incorrect_directories)

            # Generate summary
            result.issues_summary = {
                'misnamed_files': len(result.misnamed_files),
                'misplaced_files': len(result.misplaced_files),
                'incorrect_directories': len(result.incorrect_directories),
                'valid_files': result.valid_files,
                'total_issues': len(result.misnamed_files) + len(result.misplaced_files) + len(result.incorrect_directories)
            }

            result.is_valid = result.issues_summary['total_issues'] == 0

            logger.info(
                f"Library validation complete: {result.valid_files}/{result.total_files} valid, "
                f"{result.issues_summary['total_issues']} issues found"
            )

            return result

        except Exception as e:
            logger.error(f"Error validating library structure: {e}")
            result.is_valid = False
            return result

    def identify_misnamed_files(
        self,
        artist_id: UUID,
        library_root: str
    ) -> List[MisnamedFile]:
        """
        Find files not following naming convention

        Args:
            artist_id: Artist UUID
            library_root: Root directory of library

        Returns:
            List of misnamed files
        """
        validation_result = self.validate_artist_structure(artist_id, library_root)
        return validation_result.misnamed_files

    def identify_misplaced_files(
        self,
        artist_id: UUID,
        library_root: str
    ) -> List[MisplacedFile]:
        """
        Find files in wrong album directories

        Args:
            artist_id: Artist UUID
            library_root: Root directory of library

        Returns:
            List of misplaced files
        """
        validation_result = self.validate_artist_structure(artist_id, library_root)
        return validation_result.misplaced_files

    def identify_incorrect_directories(
        self,
        artist_id: UUID,
        library_root: str
    ) -> List[IncorrectDirectory]:
        """
        Find incorrectly named directories

        Args:
            artist_id: Artist UUID
            library_root: Root directory of library

        Returns:
            List of incorrect directories
        """
        validation_result = self.validate_artist_structure(artist_id, library_root)
        return validation_result.incorrect_directories

    def generate_correction_plan(
        self,
        validation_result: ValidationResult
    ) -> List[Dict[str, Any]]:
        """
        Generate plan for correcting issues

        Args:
            validation_result: Validation result with issues

        Returns:
            List of correction operations
        """
        corrections = []

        # Directory renames (do these first)
        for incorrect_dir in validation_result.incorrect_directories:
            corrections.append({
                'operation': 'rename_directory',
                'priority': 1,  # High priority
                'current_path': incorrect_dir.current_path,
                'new_path': incorrect_dir.expected_path,
                'directory_type': incorrect_dir.directory_type,
                'affected_files': incorrect_dir.affected_files
            })

        # File moves (misplaced files)
        for misplaced_file in validation_result.misplaced_files:
            corrections.append({
                'operation': 'move_file',
                'priority': 2,  # Medium priority
                'current_path': misplaced_file.current_path,
                'new_path': misplaced_file.expected_path,
                'reason': misplaced_file.reason,
                'file_id': misplaced_file.file_id,
                'track_id': misplaced_file.track_id
            })

        # File renames (misnamed files)
        for misnamed_file in validation_result.misnamed_files:
            corrections.append({
                'operation': 'rename_file',
                'priority': 3,  # Lower priority
                'current_path': misnamed_file.current_path,
                'new_path': misnamed_file.expected_path,
                'issue_type': misnamed_file.issue_type,
                'file_id': misnamed_file.file_id,
                'track_id': misnamed_file.track_id
            })

        # Sort by priority
        corrections.sort(key=lambda x: x['priority'])

        logger.info(f"Generated correction plan with {len(corrections)} operations")

        return corrections

    # ========================================
    # Private helper methods
    # ========================================

    def _get_artist_info(self, artist_id: UUID) -> Optional[Dict[str, Any]]:
        """Get artist information from database"""
        from sqlalchemy import text
        try:
            query = text("SELECT id, name, musicbrainz_id FROM artists WHERE id = :artist_id")
            result = self.db.execute(query, {'artist_id': str(artist_id)}).first()

            if result:
                return {
                    'id': result[0],
                    'name': result[1],
                    'musicbrainz_id': result[2]
                }
            return None
        except:
            return None

    def _get_artist_tracks(self, artist_id: UUID) -> List[Dict[str, Any]]:
        """Get all tracks/files for an artist from library_files"""
        from app.models.artist import Artist
        from app.models.library import LibraryFile

        try:
            # Get artist to find their musicbrainz_id
            artist = self.db.query(Artist).filter(Artist.id == artist_id).first()
            if not artist or not artist.musicbrainz_id:
                logger.warning(f"Artist {artist_id} not found or has no MusicBrainz ID")
                return []

            # Get all files for this artist via musicbrainz_artistid
            files = self.db.query(LibraryFile).filter(
                LibraryFile.musicbrainz_artistid == artist.musicbrainz_id
            ).all()

            tracks = []
            for f in files:
                tracks.append({
                    'file_id': str(f.id),
                    'file_path': f.file_path,
                    'artist_name': f.artist or artist.name,
                    'album_title': f.album or 'Unknown Album',
                    'track_title': f.title or f.file_name,
                    'track_number': f.track_number or 1,
                    'disc_number': f.disc_number or 1,
                    'total_discs': 1,  # Would need to be calculated from album
                    'release_year': f.year,
                    'file_extension': f.format or 'flac',
                    'medium_format': 'CD',  # Default
                    'album_type': 'Album',  # Default
                    'is_compilation': False,  # Would need to check album
                    'track_id': f.musicbrainz_trackid,
                    'album_id': f.musicbrainz_albumid,
                })

            logger.info(f"Found {len(tracks)} tracks for artist {artist.name}")
            return tracks

        except Exception as e:
            logger.error(f"Error getting artist tracks: {e}")
            return []

    def _get_library_artists(self, library_path_id: UUID) -> List[Dict[str, Any]]:
        """Get all artists in a library by finding artists with files in this library path"""
        from app.models.artist import Artist
        from app.models.library import LibraryFile
        from sqlalchemy import distinct

        try:
            # Get all unique musicbrainz_artistid values from library files
            artist_mbids = self.db.query(distinct(LibraryFile.musicbrainz_artistid)).filter(
                LibraryFile.library_path_id == library_path_id,
                LibraryFile.musicbrainz_artistid.isnot(None)
            ).all()

            # Flatten the result
            mbid_list = [mbid[0] for mbid in artist_mbids if mbid[0]]

            if not mbid_list:
                logger.warning(f"No artists with MusicBrainz IDs found in library path {library_path_id}")
                return []

            # Get artist records matching these MBIDs
            artists = self.db.query(Artist).filter(
                Artist.musicbrainz_id.in_(mbid_list)
            ).all()

            logger.info(f"Found {len(artists)} artists in library path {library_path_id}")

            return [{'artist_id': artist.id, 'name': artist.name} for artist in artists]

        except Exception as e:
            logger.error(f"Error getting library artists: {e}")
            return []

    def _build_track_context(self, track: Dict[str, Any]) -> TrackContext:
        """Build TrackContext from database track record"""
        from .naming_engine import TrackContext
        return TrackContext(
            artist_name=track.get('artist_name', 'Unknown Artist'),
            album_title=track.get('album_title', 'Unknown Album'),
            track_title=track.get('track_title', 'Unknown Track'),
            track_number=track.get('track_number', 1),
            release_year=track.get('release_year'),
            disc_number=track.get('disc_number', 1),
            total_discs=track.get('total_discs', 1),
            medium_format=track.get('medium_format', 'CD'),
            album_type=track.get('album_type', 'Album'),
            file_extension=track.get('file_extension', 'flac'),
            is_compilation=track.get('is_compilation', False)
        )

    def _validate_artist_directory(
        self,
        artist_id: UUID,
        artist_name: str,
        library_root: str
    ) -> List[IncorrectDirectory]:
        """Validate artist directory name"""
        issues = []

        try:
            # Generate expected artist directory name
            artist_context = ArtistContext(artist_name=artist_name)
            expected_artist_dir = self.naming_engine.generate_artist_directory(artist_context)

            # Check if artist has files
            tracks = self._get_artist_tracks(artist_id)

            if not tracks:
                return issues

            # Get actual artist directory from first file
            first_file_path = tracks[0].get('file_path', '')

            if not first_file_path:
                return issues

            # Extract artist directory from path
            file_path = Path(first_file_path)
            library_path = Path(library_root)

            try:
                relative_path = file_path.relative_to(library_path)
                actual_artist_dir = relative_path.parts[0] if relative_path.parts else None
            except ValueError:
                # File not in library
                return issues

            # Compare
            if actual_artist_dir and actual_artist_dir != expected_artist_dir:
                # Count affected files
                affected_files = len(tracks)

                issues.append(IncorrectDirectory(
                    current_path=str(library_path / actual_artist_dir),
                    expected_path=str(library_path / expected_artist_dir),
                    current_name=actual_artist_dir,
                    expected_name=expected_artist_dir,
                    directory_type='artist',
                    affected_files=affected_files,
                    artist_id=artist_id
                ))

        except Exception as e:
            logger.error(f"Error validating artist directory: {e}")

        return issues

    def _determine_filename_issue(self, current: str, expected: str) -> str:
        """Determine what type of filename issue exists"""
        # Extract components for comparison
        import re

        # Check for track number mismatch
        current_track = re.search(r'(\d{2,3})', current)
        expected_track = re.search(r'(\d{2,3})', expected)

        if current_track and expected_track and current_track.group() != expected_track.group():
            return 'wrong_track_number'

        # Check for title mismatch
        if current.lower().replace(' ', '') != expected.lower().replace(' ', ''):
            return 'wrong_title'

        # Check for format/template mismatch
        return 'incorrect_format'

    def _determine_misplacement_reason(self, current_dir: str, expected_dir: str) -> str:
        """Determine why file is in wrong directory"""
        current_parts = Path(current_dir).parts
        expected_parts = Path(expected_dir).parts

        # Compare directory structures
        if len(current_parts) != len(expected_parts):
            return 'wrong_structure'

        # Check artist directory
        if len(current_parts) >= 1 and current_parts[-2] != expected_parts[-2]:
            return 'wrong_artist'

        # Check album directory
        if len(current_parts) >= 2 and current_parts[-1] != expected_parts[-1]:
            return 'wrong_album'

        return 'unknown_reason'
