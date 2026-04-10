"""
Associate and Organize Service

One-pass-per-artist service that:
1. Walks an artist's directory to discover audio files
2. Reads file metadata (mutagen)
3. Matches files to DB albums and tracks (MBID-first, then fuzzy)
4. Moves/renames files to the naming convention
5. Updates Track.file_path + Track.has_file in the database
6. Creates .mbid.json metadata files per album directory
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models.artist import Artist
from app.models.album import Album
from app.models.track import Track
from app.services.metadata_extractor import MetadataExtractor
from app.services.mbid_file_matcher import MBIDFileMatcher
from app.shared_services.naming_engine import NamingEngine, TrackContext
from app.shared_services.atomic_file_ops import AtomicFileOps, OperationType
from app.shared_services.audit_logger import AuditLogger
from app.shared_services.metadata_file_manager import MetadataFileManager

logger = logging.getLogger(__name__)

# Audio file extensions to discover
AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.m4b', '.ogg', '.opus', '.wav', '.aiff', '.aac'}

# Max directory depth when walking artist folder
MAX_WALK_DEPTH = 3

# Custom template matching CLAUDE.md convention
TRACK_TEMPLATE = "{Artist Name}/{Album Title} ({Release Year})/{Artist Name} - {Album Title} - {track:00} - {Track Title}.{ext}"
MULTI_DISC_TEMPLATE = "{Artist Name}/{Album Title} ({Release Year})/{Medium Format} {medium:00}/{Artist Name} - {Album Title} - {track:00} - {Track Title}.{ext}"


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy comparison."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


@dataclass
class FileMatchResult:
    """Per-file result with metadata, matched album/track, match method, confidence, target path."""
    file_path: str
    metadata: Dict

    # Match results
    matched_album: Optional[Album] = None
    matched_track: Optional[Track] = None
    album_match_method: Optional[str] = None  # mbid_release, mbid_release_group, fuzzy
    track_match_method: Optional[str] = None  # mbid_recording, track_number, fuzzy_title
    confidence: float = 0.0

    # Target path
    target_path: Optional[str] = None

    # Status
    skipped: bool = False
    skip_reason: Optional[str] = None
    error: Optional[str] = None


@dataclass
class OrganizationResult:
    """Result of processing an artist's directory."""
    artist_id: str
    artist_name: str
    files_found: int = 0
    files_matched: int = 0
    files_moved: int = 0
    files_renamed: int = 0
    files_already_organized: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    tracks_linked: int = 0
    albums_with_metadata: int = 0
    dirs_cleaned: int = 0
    match_results: List[FileMatchResult] = field(default_factory=list)


class AssociateAndOrganizeService:
    """
    Main class for one-pass-per-artist file association and organization.
    """

    def __init__(
        self,
        db: Session,
        naming_engine: NamingEngine = None,
        atomic_ops: AtomicFileOps = None,
        audit_logger: AuditLogger = None,
        dry_run: bool = False
    ):
        self.db = db
        self.naming_engine = naming_engine or NamingEngine(
            track_template=TRACK_TEMPLATE,
            multi_disc_template=MULTI_DISC_TEMPLATE
        )
        self.atomic_ops = atomic_ops or AtomicFileOps()
        self.audit_logger = audit_logger or AuditLogger(db=db)
        self.dry_run = dry_run

    def process_artist(
        self,
        artist_id: str,
        library_root: str,
        job_logger=None,
        progress_callback=None
    ) -> OrganizationResult:
        """
        Process all files for a single artist.

        Args:
            artist_id: Artist UUID string
            library_root: Root library path (e.g., /music/)
            job_logger: Optional JobLogger for detailed logging
            progress_callback: Optional callable(current_idx, total, file_path) for progress

        Returns:
            OrganizationResult with statistics and per-file details
        """
        # Load artist
        artist = self.db.query(Artist).filter(Artist.id == UUID(artist_id)).first()
        if not artist:
            raise ValueError(f"Artist {artist_id} not found")

        result = OrganizationResult(artist_id=artist_id, artist_name=artist.name)

        if job_logger:
            job_logger.log_info(f"Processing artist: {artist.name} (ID: {artist_id})")

        # Step 1: Discover artist directory
        artist_dir = self._discover_artist_directory(artist, library_root, job_logger)
        if not artist_dir:
            if job_logger:
                job_logger.log_info(f"No directory found for {artist.name}, skipping")
            return result

        # Update artist.root_folder_path if not set
        if not artist.root_folder_path or artist.root_folder_path != str(artist_dir):
            artist.root_folder_path = str(artist_dir)
            self.db.commit()
            if job_logger:
                job_logger.log_info(f"Set root_folder_path: {artist_dir}")

        # Step 2: Walk files
        audio_files = self._walk_audio_files(artist_dir, job_logger)
        result.files_found = len(audio_files)

        if not audio_files:
            if job_logger:
                job_logger.log_info(f"No audio files found in {artist_dir}")
            return result

        if job_logger:
            job_logger.log_info(f"Found {len(audio_files)} audio files in {artist_dir}")

        # Step 3: Pre-load DB data with indexes
        album_indexes, track_indexes = self._build_lookup_indexes(artist)

        if job_logger:
            job_logger.log_info(
                f"Loaded {len(artist.albums)} albums, "
                f"{sum(len(a.tracks) for a in artist.albums)} tracks from DB"
            )

        # Track which tracks already have files (first file wins)
        tracks_with_files = set()
        for album in artist.albums:
            for track in album.tracks:
                if track.has_file and track.file_path:
                    tracks_with_files.add(track.id)

        # Track album directories that got files (for .mbid.json creation)
        album_dirs_to_update = set()
        # Track source paths of moved files (for empty directory cleanup)
        moved_source_paths = []

        # Step 4: Process each file
        for idx, file_path in enumerate(audio_files):
            if progress_callback:
                progress_callback(idx, len(audio_files), file_path)

            match_result = self._process_file(
                file_path=file_path,
                artist=artist,
                library_root=library_root,
                album_indexes=album_indexes,
                track_indexes=track_indexes,
                tracks_with_files=tracks_with_files,
                job_logger=job_logger
            )

            result.match_results.append(match_result)

            if match_result.error:
                result.files_failed += 1
                continue

            if match_result.skipped:
                result.files_skipped += 1
                continue

            if match_result.matched_track:
                result.files_matched += 1

                # Mark track as claimed
                tracks_with_files.add(match_result.matched_track.id)

                # Move/rename file
                if match_result.target_path:
                    move_result = self._move_file(
                        source_path=file_path,
                        target_path=match_result.target_path,
                        match_result=match_result,
                        job_logger=job_logger
                    )

                    if move_result == 'moved':
                        result.files_moved += 1
                        moved_source_paths.append(file_path)
                        final_path = match_result.target_path
                    elif move_result == 'renamed':
                        result.files_renamed += 1
                        final_path = match_result.target_path
                    elif move_result == 'already_organized':
                        result.files_already_organized += 1
                        final_path = file_path
                    else:
                        result.files_failed += 1
                        continue

                    # Update DB: Track.file_path + Track.has_file
                    if not self.dry_run:
                        match_result.matched_track.file_path = final_path
                        match_result.matched_track.has_file = True
                        self.db.commit()
                        result.tracks_linked += 1

                        # Track album dir for metadata
                        album_dir = str(Path(final_path).parent)
                        album_dirs_to_update.add(
                            (album_dir, match_result.matched_album.id if match_result.matched_album else None)
                        )

                    if job_logger:
                        job_logger.log_file_operation(
                            operation="associate",
                            source_path=file_path,
                            destination_path=final_path,
                            success=True
                        )
            else:
                result.files_skipped += 1

        # Step 5: Create .mbid.json files
        if not self.dry_run and album_dirs_to_update:
            metadata_count = self._create_metadata_files(
                album_dirs_to_update, artist, job_logger
            )
            result.albums_with_metadata = metadata_count

        # Step 6: Clean up empty directories left behind by moved files
        if not self.dry_run and moved_source_paths:
            if job_logger:
                job_logger.log_info(f"Cleaning up empty directories from {len(moved_source_paths)} moved files")
            dirs_removed = self._cleanup_empty_directories(moved_source_paths, library_root, job_logger)
            result.dirs_cleaned = dirs_removed

        if job_logger:
            job_logger.log_info(
                f"Artist {artist.name} complete: "
                f"found={result.files_found}, matched={result.files_matched}, "
                f"moved={result.files_moved}, renamed={result.files_renamed}, "
                f"already_organized={result.files_already_organized}, "
                f"skipped={result.files_skipped}, failed={result.files_failed}, "
                f"tracks_linked={result.tracks_linked}"
            )

        return result

    def _discover_artist_directory(
        self, artist: Artist, library_root: str, job_logger=None
    ) -> Optional[Path]:
        """
        Discover the artist's directory.

        Priority:
        1. Use artist.root_folder_path if set and exists
        2. Scan library_root for matching directory (case-insensitive)
        3. Return None (don't create directories in discovery phase)
        """
        # Check existing root_folder_path
        if artist.root_folder_path:
            rfp = Path(artist.root_folder_path)
            if rfp.exists() and rfp.is_dir():
                return rfp

        # Scan library_root for matching directory
        root = Path(library_root)
        if not root.exists():
            return None

        artist_name_norm = _normalize(artist.name)

        try:
            for entry in root.iterdir():
                if entry.is_dir() and _normalize(entry.name) == artist_name_norm:
                    if job_logger:
                        job_logger.log_info(f"Discovered artist directory: {entry}")
                    return entry
        except PermissionError:
            if job_logger:
                job_logger.log_warning(f"Permission denied scanning {library_root}")

        return None

    def _walk_audio_files(self, artist_dir: Path, job_logger=None) -> List[str]:
        """
        Recursively find all audio files up to MAX_WALK_DEPTH levels deep.
        """
        audio_files = []
        base_depth = len(artist_dir.parts)

        for dirpath, dirnames, filenames in os.walk(str(artist_dir)):
            current_depth = len(Path(dirpath).parts) - base_depth
            if current_depth >= MAX_WALK_DEPTH:
                dirnames.clear()
                continue

            for filename in sorted(filenames):
                ext = Path(filename).suffix.lower()
                if ext in AUDIO_EXTENSIONS:
                    audio_files.append(os.path.join(dirpath, filename))

        return audio_files

    def _build_lookup_indexes(self, artist: Artist) -> Tuple[Dict, Dict]:
        """
        Pre-load all albums + tracks for artist with joinedload into lookup indexes.

        Returns:
            (album_indexes, track_indexes)
        """
        # Reload artist with eagerly loaded albums and tracks
        artist = self.db.query(Artist).options(
            joinedload(Artist.albums).joinedload(Album.tracks)
        ).filter(Artist.id == artist.id).first()

        album_indexes = {
            'by_release_mbid': {},      # release_mbid -> Album
            'by_release_group_mbid': {},  # musicbrainz_id -> Album
            'by_normalized_title': {},   # normalized_title -> [Album]
        }

        track_indexes = {
            'by_recording_mbid': {},  # musicbrainz_id -> Track (across all albums)
        }

        for album in artist.albums:
            if album.release_mbid:
                album_indexes['by_release_mbid'][album.release_mbid.lower()] = album
            if album.musicbrainz_id:
                album_indexes['by_release_group_mbid'][album.musicbrainz_id.lower()] = album

            norm_title = _normalize(album.title)
            if norm_title not in album_indexes['by_normalized_title']:
                album_indexes['by_normalized_title'][norm_title] = []
            album_indexes['by_normalized_title'][norm_title].append(album)

            for track in album.tracks:
                if track.musicbrainz_id:
                    track_indexes['by_recording_mbid'][track.musicbrainz_id.lower()] = track

        return album_indexes, track_indexes

    def _process_file(
        self,
        file_path: str,
        artist: Artist,
        library_root: str,
        album_indexes: Dict,
        track_indexes: Dict,
        tracks_with_files: set,
        job_logger=None
    ) -> FileMatchResult:
        """
        Process a single file: extract metadata, match album, match track, calculate target path.
        """
        # Extract metadata
        try:
            metadata = MetadataExtractor.extract(file_path)
        except Exception as e:
            return FileMatchResult(
                file_path=file_path,
                metadata={},
                error=f"Metadata extraction failed: {e}"
            )

        result = FileMatchResult(file_path=file_path, metadata=metadata)

        # Get MBIDs from file (standard tags + comment field)
        release_mbid = metadata.get('musicbrainz_albumid')
        release_group_mbid = metadata.get('musicbrainz_releasegroupid')
        recording_mbid = metadata.get('musicbrainz_trackid')

        # Match Album
        matched_album, album_method, album_confidence = self._match_album(
            metadata, album_indexes, release_mbid, release_group_mbid
        )

        # If recording MBID matches a track on a different album, follow the MBID
        if recording_mbid and recording_mbid.lower() in track_indexes['by_recording_mbid']:
            mbid_track = track_indexes['by_recording_mbid'][recording_mbid.lower()]
            if matched_album and mbid_track.album_id != matched_album.id:
                # MBID says this track belongs to a different album - follow the MBID
                for album in self.db.query(Album).filter(Album.id == mbid_track.album_id).all():
                    matched_album = album
                    album_method = "mbid_recording_redirect"
                    album_confidence = 1.0
                    break

        if not matched_album:
            result.skipped = True
            result.skip_reason = f"No album match for: {metadata.get('album', 'Unknown')}"
            if job_logger:
                job_logger.log_info(
                    f"  SKIP (no album match): {Path(file_path).name} "
                    f"album='{metadata.get('album')}'"
                )
            return result

        result.matched_album = matched_album
        result.album_match_method = album_method
        result.confidence = album_confidence

        # Match Track within album
        matched_track, track_method = self._match_track(
            metadata, matched_album, recording_mbid, track_indexes
        )

        if not matched_track:
            result.skipped = True
            result.skip_reason = (
                f"No track match in album '{matched_album.title}' for: "
                f"{metadata.get('title', 'Unknown')}"
            )
            if job_logger:
                job_logger.log_info(
                    f"  SKIP (no track match): {Path(file_path).name} "
                    f"title='{metadata.get('title')}' in album='{matched_album.title}'"
                )
            return result

        # Check if track already has a file (first file wins)
        if matched_track.id in tracks_with_files:
            result.skipped = True
            result.skip_reason = f"Track already has file: {matched_track.title}"
            if job_logger:
                job_logger.log_info(
                    f"  SKIP (track has file): {Path(file_path).name} -> {matched_track.title}"
                )
            return result

        result.matched_track = matched_track
        result.track_match_method = track_method

        # Calculate target path
        target_path = self._calculate_target_path(
            artist=artist,
            album=matched_album,
            track=matched_track,
            file_path=file_path,
            library_root=library_root
        )
        result.target_path = target_path

        if job_logger:
            job_logger.log_info(
                f"  MATCH: {Path(file_path).name} -> "
                f"[{album_method}] {matched_album.title} / "
                f"[{track_method}] #{matched_track.track_number} {matched_track.title}"
            )

        return result

    def _match_album(
        self,
        metadata: Dict,
        album_indexes: Dict,
        release_mbid: Optional[str],
        release_group_mbid: Optional[str]
    ) -> Tuple[Optional[Album], Optional[str], float]:
        """
        Match file to album using priority order:
        1. Release MBID -> Album.release_mbid (exact, 1.0 confidence)
        2. Release Group MBID -> Album.musicbrainz_id (exact, 0.95)
        3. Fuzzy title+year (>= 0.75)
        """
        # 1. Release MBID
        if release_mbid:
            album = album_indexes['by_release_mbid'].get(release_mbid.lower())
            if album:
                return album, "mbid_release", 1.0

        # 2. Release Group MBID
        if release_group_mbid:
            album = album_indexes['by_release_group_mbid'].get(release_group_mbid.lower())
            if album:
                return album, "mbid_release_group", 0.95

        # 3. Fuzzy title match
        file_album = metadata.get('album')
        if not file_album:
            return None, None, 0.0

        file_album_norm = _normalize(file_album)
        file_year = metadata.get('year')

        best_album = None
        best_score = 0.0
        best_track_count = 0
        best_method = None

        file_track_num = metadata.get('track_number')

        for norm_title, albums in album_indexes['by_normalized_title'].items():
            ratio = SequenceMatcher(None, file_album_norm, norm_title).ratio()

            for album in albums:
                score = ratio
                # Boost if year matches
                if file_year and album.release_date:
                    try:
                        album_year = album.release_date.year
                        if int(file_year) == album_year:
                            score = min(score + 0.1, 1.0)
                    except (ValueError, AttributeError):
                        pass

                if score >= 0.75:
                    album_track_count = len(album.tracks) if album.tracks else 0
                    # When scores are equal, prefer album with more tracks
                    # (full album over single) and that contains the file's track number
                    if score > best_score or (
                        score == best_score and album_track_count > best_track_count
                    ):
                        best_score = score
                        best_album = album
                        best_track_count = album_track_count
                        best_method = "fuzzy_title"

        return best_album, best_method, best_score

    def _match_track(
        self,
        metadata: Dict,
        album: Album,
        recording_mbid: Optional[str],
        track_indexes: Dict
    ) -> Tuple[Optional[Track], Optional[str]]:
        """
        Match file to track within the matched album.

        Priority:
        1. Recording MBID -> Track.musicbrainz_id (exact, 1.0)
        2. Exact track_number + disc_number
        3. Fuzzy title (>= 0.6, tie-break by duration proximity)
        """
        album_tracks = album.tracks

        # 1. Recording MBID
        if recording_mbid:
            for track in album_tracks:
                if track.musicbrainz_id and track.musicbrainz_id.lower() == recording_mbid.lower():
                    return track, "mbid_recording"

            # Also check global recording MBID index (might be on a different album)
            global_track = track_indexes['by_recording_mbid'].get(recording_mbid.lower())
            if global_track:
                return global_track, "mbid_recording_cross_album"

        # 2. Exact track number + disc number
        file_track_num = metadata.get('track_number')
        file_disc_num = metadata.get('disc_number') or 1

        if file_track_num:
            for track in album_tracks:
                track_disc = track.disc_number or 1
                if track.track_number == file_track_num and track_disc == file_disc_num:
                    return track, "track_number"

        # 3. Fuzzy title matching
        file_title = metadata.get('title')
        if not file_title:
            # Try to parse title from filename
            file_title = self._parse_title_from_filename(metadata.get('file_name', ''))

        if not file_title:
            return None, None

        file_title_norm = _normalize(file_title)
        file_duration_ms = metadata.get('duration_ms')

        best_track = None
        best_score = 0.0

        for track in album_tracks:
            track_title_norm = _normalize(track.title)
            ratio = SequenceMatcher(None, file_title_norm, track_title_norm).ratio()

            if ratio >= 0.6:
                # Tie-break by duration proximity
                if file_duration_ms and track.duration_ms:
                    duration_diff = abs(file_duration_ms - track.duration_ms)
                    if duration_diff <= 5000:  # within 5 seconds
                        ratio += 0.05  # Small boost for duration match

                if ratio > best_score:
                    best_score = ratio
                    best_track = track

        if best_track:
            return best_track, "fuzzy_title"

        return None, None

    def _parse_title_from_filename(self, filename: str) -> Optional[str]:
        """Parse track title from filename as fallback."""
        if not filename:
            return None

        # Remove extension
        name = Path(filename).stem

        # Try common patterns:
        # "01 - Track Title"
        # "Artist - Album - 01 - Track Title"
        # "01. Track Title"
        # "01-track_title"

        # Pattern: number separator title
        match = re.match(r'^\d+[\s._-]+(.+)$', name)
        if match:
            title = match.group(1)
            # Remove artist/album prefix if present (e.g., "Artist - Album - Title")
            parts = re.split(r'\s*-\s*', title)
            if len(parts) > 1:
                return parts[-1].strip()
            return title.strip()

        return name

    def _calculate_target_path(
        self,
        artist: Artist,
        album: Album,
        track: Track,
        file_path: str,
        library_root: str
    ) -> str:
        """
        Calculate the target path for a file using NamingEngine.
        """
        # Determine total discs for this album
        max_disc = max(
            (t.disc_number or 1 for t in album.tracks),
            default=1
        )

        # Get release year
        release_year = None
        if album.release_date:
            try:
                release_year = album.release_date.year
            except AttributeError:
                pass

        # Get file extension
        file_ext = Path(file_path).suffix.lstrip('.').lower()
        if not file_ext:
            file_ext = 'flac'

        track_context = TrackContext(
            artist_name=artist.name,
            album_title=album.title,
            track_title=track.title,
            track_number=track.track_number or 1,
            release_year=release_year,
            disc_number=track.disc_number or 1,
            total_discs=max_disc,
            medium_format='CD',
            album_type=album.album_type or 'Album',
            file_extension=file_ext,
            is_compilation=False
        )

        # Generate relative path
        relative_path = self.naming_engine.generate_track_filename(track_context)

        # Full target path
        target_path = os.path.join(library_root, relative_path)

        return target_path

    def _move_file(
        self,
        source_path: str,
        target_path: str,
        match_result: FileMatchResult,
        job_logger=None
    ) -> str:
        """
        Move/rename file to target path.

        Returns:
            'moved', 'renamed', 'already_organized', or 'failed'
        """
        source = Path(source_path)
        target = Path(target_path)

        # Normalize for comparison
        try:
            source_resolved = source.resolve()
            target_resolved = target.resolve()
        except OSError:
            source_resolved = source
            target_resolved = target

        # Already at target path
        if source_resolved == target_resolved:
            return 'already_organized'

        if self.dry_run:
            if job_logger:
                job_logger.log_info(f"  DRY RUN: {source_path} -> {target_path}")
            # Determine what operation would be performed
            if source.parent == target.parent:
                return 'renamed'
            return 'moved'

        # Perform the move
        op_result = self.atomic_ops.move_file(
            source_path=source_path,
            destination_path=target_path,
            backup=False,
            overwrite=False
        )

        if op_result.success:
            # Log audit
            self.audit_logger.log_operation(
                operation_result=op_result,
                artist_id=match_result.matched_album.artist_id if match_result.matched_album else None,
                album_id=match_result.matched_album.id if match_result.matched_album else None,
                recording_mbid=match_result.matched_track.musicbrainz_id if match_result.matched_track else None,
            )

            if source.parent == target.parent:
                return 'renamed'
            return 'moved'
        else:
            if job_logger:
                job_logger.log_info(
                    f"  FAIL move: {source_path} -> {target_path}: {op_result.error_message}"
                )
            match_result.error = op_result.error_message
            return 'failed'

    def _create_metadata_files(
        self,
        album_dirs: set,
        artist: Artist,
        job_logger=None
    ) -> int:
        """Create .mbid.json files in album directories."""
        count = 0
        try:
            metadata_mgr = MetadataFileManager(self.db)
            for album_dir, album_id in album_dirs:
                if album_id:
                    try:
                        album = self.db.query(Album).filter(Album.id == album_id).first()
                        if not album:
                            continue

                        release_year = None
                        if album.release_date:
                            try:
                                release_year = album.release_date.year
                            except AttributeError:
                                pass

                        metadata_mgr.create_album_metadata_file(
                            album_id=album_id,
                            album_directory=album_dir,
                            album_title=album.title,
                            artist_name=artist.name,
                            artist_mbid=artist.musicbrainz_id,
                            release_year=release_year,
                            album_type=album.album_type or "Album",
                            release_mbid=album.release_mbid,
                            release_group_mbid=album.musicbrainz_id,
                        )
                        count += 1
                    except Exception as e:
                        if job_logger:
                            job_logger.log_warning(
                                f"Failed to create .mbid.json in {album_dir}: {e}"
                            )
        except Exception as e:
            if job_logger:
                job_logger.log_warning(f"Error creating metadata files: {e}")

        return count

    def _cleanup_empty_directories(
        self,
        source_paths: list,
        library_root: str,
        job_logger=None
    ) -> int:
        """
        Remove empty directories left behind after files are moved.

        Walks up from each source file's parent directory, removing empty dirs
        until reaching the library root or a non-empty directory.

        Args:
            source_paths: List of original file paths that were moved
            library_root: Root library path (will NOT be removed)
            job_logger: Optional JobLogger for logging

        Returns:
            Number of directories removed
        """
        deleted_count = 0
        root = Path(library_root).resolve()
        already_checked = set()

        # Collect unique parent directories from source paths
        parent_dirs = set()
        for file_path in source_paths:
            parent_dirs.add(Path(file_path).parent)

        # Sort deepest first so we clean children before parents
        sorted_dirs = sorted(parent_dirs, key=lambda p: len(p.parts), reverse=True)

        for dir_path in sorted_dirs:
            current = dir_path
            while True:
                try:
                    resolved = current.resolve()
                except OSError:
                    break

                # Don't remove the library root or go above it
                if resolved == root or not str(resolved).startswith(str(root)):
                    break

                if resolved in already_checked:
                    break
                already_checked.add(resolved)

                if not current.exists() or not current.is_dir():
                    break
                if any(current.iterdir()):
                    break

                try:
                    current.rmdir()
                    deleted_count += 1
                    if job_logger:
                        job_logger.log_info(f"Removed empty directory: {current}")
                    logger.info(f"Removed empty directory: {current}")
                except OSError as e:
                    logger.warning(f"Could not remove directory {current}: {e}")
                    break

                current = current.parent

        if deleted_count > 0 and job_logger:
            job_logger.log_info(f"Cleaned up {deleted_count} empty directories")

        return deleted_count
