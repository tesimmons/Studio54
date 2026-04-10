"""
Import Service for Studio54
Handles post-download file organization, tagging, and library integration
"""

import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime

from app.config import settings
from app.services.muse_client import get_muse_client

logger = logging.getLogger(__name__)


class ImportService:
    """
    Import service for organizing and tagging downloaded music

    Responsibilities:
    - Create artist/album directory structure
    - Move files from download directory
    - Apply MusicBrainz tags (future enhancement)
    - Trigger MUSE library scan
    """

    def __init__(self, music_library_path: str = None):
        """
        Initialize import service

        Args:
            music_library_path: Root music library path (default from settings)
        """
        self.music_library_path = Path(music_library_path or settings.music_library_path)
        self.muse_client = get_muse_client()

    def sanitize_filename(self, name: str) -> str:
        """
        Sanitize filename/directory name

        Args:
            name: Original name

        Returns:
            Sanitized name safe for filesystem
        """
        # Remove invalid characters
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\x00']
        sanitized = name

        for char in invalid_chars:
            sanitized = sanitized.replace(char, '_')

        # Remove leading/trailing dots and spaces
        sanitized = sanitized.strip('. ')

        # Limit length
        if len(sanitized) > 255:
            sanitized = sanitized[:255]

        return sanitized or "Unknown"

    def create_album_directory(
        self,
        artist_name: str,
        album_title: str,
        release_year: Optional[int] = None,
        album_type: Optional[str] = None,
        custom_folder_path: Optional[str] = None
    ) -> Path:
        """
        Create artist/album directory structure

        Directory format:
        - Custom: {custom_folder_path} (if provided)
        - Albums: /music/Artist Name/Album Title (Year)/
        - Singles: /music/Artist Name/Singles/

        Args:
            artist_name: Artist name
            album_title: Album title
            release_year: Release year (optional)
            album_type: Album type (Album, Single, EP, etc.) (optional)
            custom_folder_path: Custom folder path (overrides default structure) (optional)

        Returns:
            Path to album directory
        """
        # Use custom path if provided
        if custom_folder_path:
            album_path = Path(custom_folder_path)
        else:
            # Sanitize names
            artist_dir = self.sanitize_filename(artist_name)

            # Use "Singles" directory for singles instead of album title
            if album_type and album_type.lower() == "single":
                album_dir = "Singles"
            else:
                album_dir = self.sanitize_filename(album_title)
                # Add year if provided (not for Singles directory)
                if release_year:
                    album_dir = f"{album_dir} ({release_year})"

            # Create full path
            album_path = self.music_library_path / artist_dir / album_dir

        # Create directories
        try:
            album_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Import] Created directory: {album_path}")
            return album_path

        except Exception as e:
            logger.error(f"[Import] Failed to create directory {album_path}: {e}")
            raise

    def move_files(
        self,
        source_dir: str,
        dest_dir: Path,
        file_extensions: List[str] = None
    ) -> List[Path]:
        """
        Move music files from source to destination

        Args:
            source_dir: Source directory path
            dest_dir: Destination directory path
            file_extensions: List of file extensions to move (default: audio files)

        Returns:
            List of moved file paths
        """
        if file_extensions is None:
            file_extensions = ['.flac', '.mp3', '.m4a', '.aac', '.ogg', '.opus', '.wav']

        source_path = Path(source_dir)

        if not source_path.exists():
            logger.error(f"[Import] Source directory not found: {source_dir}")
            return []

        moved_files = []

        try:
            # Find all music files
            for item in source_path.rglob('*'):
                if item.is_file() and item.suffix.lower() in file_extensions:
                    # Move file to destination
                    dest_file = dest_dir / item.name

                    # Handle duplicate filenames
                    counter = 1
                    while dest_file.exists():
                        stem = item.stem
                        dest_file = dest_dir / f"{stem}_{counter}{item.suffix}"
                        counter += 1

                    try:
                        shutil.move(str(item), str(dest_file))
                    except (OSError, PermissionError) as e:
                        # If move fails (e.g., NFS permission issues), try copy without metadata
                        logger.warning(f"[Import] Move failed, trying copy: {e}")
                        try:
                            shutil.copy(str(item), str(dest_file))
                            # Try to delete source, but don't fail if we can't
                            try:
                                item.unlink()
                            except (OSError, PermissionError):
                                logger.warning(f"[Import] Could not delete source file: {item}")
                        except (OSError, PermissionError) as copy_error:
                            logger.error(f"[Import] Copy also failed: {copy_error}")
                            raise

                    moved_files.append(dest_file)
                    logger.info(f"[Import] Moved: {item.name} -> {dest_file}")

            logger.info(f"[Import] Moved {len(moved_files)} files from {source_dir}")
            return moved_files

        except Exception as e:
            logger.error(f"[Import] Failed to move files: {e}")
            raise

    def apply_musicbrainz_tags(
        self,
        file_path: Path,
        track_metadata: Dict[str, Any]
    ) -> bool:
        """
        Apply MusicBrainz tags to audio file

        Args:
            file_path: Path to audio file
            track_metadata: Track metadata dict with MusicBrainz IDs

        Returns:
            True if successful, False otherwise
        """
        # TODO: Implement actual tagging using mutagen
        # This would apply:
        # - musicbrainz_trackid
        # - musicbrainz_albumid
        # - musicbrainz_artistid
        # - musicbrainz_releasegroupid
        # - Plus standard tags (title, artist, album, etc.)

        logger.warning(f"[Import] Tagging not yet implemented for: {file_path.name}")
        return False

    def import_album(
        self,
        source_dir: str,
        artist_name: str,
        album_title: str,
        release_year: Optional[int] = None,
        album_type: Optional[str] = None,
        musicbrainz_release_id: Optional[str] = None,
        track_metadata: Optional[List[Dict[str, Any]]] = None,
        custom_folder_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete album import workflow

        Args:
            source_dir: SABnzbd download directory
            artist_name: Artist name
            album_title: Album title
            release_year: Release year
            album_type: Album type (Album, Single, EP, etc.)
            musicbrainz_release_id: MusicBrainz release ID
            track_metadata: List of track metadata dicts
            custom_folder_path: Custom folder path (overrides default structure) (optional)

        Returns:
            Import result dict with file paths and MUSE scan status
        """
        try:
            # Step 1: Create album directory
            album_dir = self.create_album_directory(
                artist_name=artist_name,
                album_title=album_title,
                release_year=release_year,
                album_type=album_type,
                custom_folder_path=custom_folder_path
            )

            # Step 2: Check if files already exist (SABnzbd post-processing may have moved them)
            audio_extensions = ['.flac', '.mp3', '.m4a', '.aac', '.ogg', '.opus', '.wav']
            logger.info(f"[Import] Checking for existing files in: {album_dir}")
            logger.info(f"[Import] Directory exists: {album_dir.exists()}, is_dir: {album_dir.is_dir()}")

            existing_files = []
            if album_dir.exists():
                existing_files = [
                    f for f in album_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in audio_extensions
                ]
                logger.info(f"[Import] Found {len(existing_files)} existing audio files")

            if existing_files:
                # Files already in destination (SABnzbd post-processing)
                logger.info(f"[Import] Found {len(existing_files)} files already in destination: {album_dir}")
                moved_files = existing_files
            else:
                # Move files from source
                moved_files = self.move_files(source_dir, album_dir)

                if not moved_files:
                    logger.warning(f"[Import] No files moved from: {source_dir}")
                    return {
                        "success": False,
                        "error": "No files found",
                        "files_moved": 0
                    }

            # Step 3: Apply tags (future enhancement)
            # if track_metadata:
            #     for file_path in moved_files:
            #         self.apply_musicbrainz_tags(file_path, track_metadata)

            # Step 4: Trigger MUSE scan
            muse_scan_triggered = False
            if musicbrainz_release_id:
                # Get first available MUSE library
                libraries = self.muse_client.get_libraries()
                if libraries:
                    library_id = libraries[0].get("id")
                    # Trigger scan with path hint for faster scanning
                    muse_scan_triggered = self.muse_client.trigger_scan(
                        library_id=library_id,
                        path_hint=str(album_dir)
                    )

            # Step 5: Clean up source directory
            self._cleanup_source_directory(source_dir)

            logger.info(f"[Import] Successfully imported album: {artist_name} - {album_title}")

            return {
                "success": True,
                "album_directory": str(album_dir),
                "files_moved": len(moved_files),
                "files": [str(f) for f in moved_files],
                "muse_scan_triggered": muse_scan_triggered
            }

        except Exception as e:
            logger.error(f"[Import] Album import failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "files_moved": 0
            }

    def _cleanup_source_directory(self, source_dir: str):
        """
        Clean up source directory after import

        Removes empty directories and leftover files

        Args:
            source_dir: Source directory path
        """
        try:
            source_path = Path(source_dir)

            if not source_path.exists():
                return

            # Remove empty subdirectories
            for item in source_path.rglob('*'):
                if item.is_dir() and not any(item.iterdir()):
                    item.rmdir()
                    logger.debug(f"[Import] Removed empty dir: {item}")

            # Remove the source directory if empty
            if source_path.exists() and not any(source_path.iterdir()):
                source_path.rmdir()
                logger.info(f"[Import] Cleaned up source directory: {source_dir}")

        except Exception as e:
            logger.warning(f"[Import] Cleanup failed for {source_dir}: {e}")

    def verify_import(
        self,
        album_directory: str,
        expected_track_count: int
    ) -> Dict[str, Any]:
        """
        Verify album import was successful

        Args:
            album_directory: Path to imported album
            expected_track_count: Expected number of tracks

        Returns:
            Verification result dict
        """
        album_path = Path(album_directory)

        if not album_path.exists():
            return {
                "verified": False,
                "error": "Album directory not found",
                "actual_files": 0,
                "expected_files": expected_track_count
            }

        # Count music files
        audio_extensions = ['.flac', '.mp3', '.m4a', '.aac', '.ogg', '.opus', '.wav']
        music_files = [
            f for f in album_path.iterdir()
            if f.is_file() and f.suffix.lower() in audio_extensions
        ]

        actual_count = len(music_files)
        verified = actual_count >= expected_track_count

        return {
            "verified": verified,
            "actual_files": actual_count,
            "expected_files": expected_track_count,
            "files": [f.name for f in music_files]
        }


# Singleton instance
_import_service: Optional[ImportService] = None


def get_import_service() -> ImportService:
    """
    Get singleton import service instance

    Returns:
        ImportService instance
    """
    global _import_service
    if _import_service is None:
        _import_service = ImportService()
    return _import_service
