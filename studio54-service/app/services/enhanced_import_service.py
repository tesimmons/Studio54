"""
Enhanced Import Service for Studio54
Integrates Lidarr-style file organization with quality detection and naming templates
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.media_management import MediaManagementConfig
from app.models.album import Album
from app.models.track import Track
from app.services.naming_template_engine import NamingTemplateEngine
from app.services.quality_detector import QualityDetector
from app.services.file_organizer import FileOrganizer, TransferMode, FileOperation
from app.services.muse_client import get_muse_client

logger = logging.getLogger(__name__)


class EnhancedImportService:
    """
    Enhanced import service using Lidarr-style file organization.

    Features:
    - Configurable naming templates
    - Quality detection and scoring
    - Atomic file operations with rollback
    - Upgrade detection
    - Recycle bin support
    """

    def __init__(self, db: Session):
        """
        Initialize enhanced import service.

        Args:
            db: Database session for accessing configuration
        """
        self.db = db
        self.config = self._get_config()
        self.naming_engine = NamingTemplateEngine(
            colon_strategy=self.config.colon_replacement
        )
        self.quality_detector = QualityDetector()
        self.file_organizer = FileOrganizer(
            music_library_path=self.config.music_library_path,
            recycle_bin_path=self.config.recycle_bin_path,
            use_hardlinks=self.config.use_hardlinks,
            recycle_bin_days=self.config.recycle_bin_cleanup_days,
        )
        self.muse_client = get_muse_client()

    def _get_config(self) -> MediaManagementConfig:
        """Get or create media management configuration."""
        config = self.db.query(MediaManagementConfig).first()
        if not config:
            logger.warning("No media management config found, creating default")
            config = MediaManagementConfig()
            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)
        return config

    def _reload_config(self):
        """Reload configuration from database."""
        self.config = self._get_config()

    def build_album_path(
        self,
        album: Album,
        track: Optional[Track] = None,
        is_multi_disc: bool = False
    ) -> Path:
        """
        Build complete file path using naming templates.

        Args:
            album: Album model
            track: Track model (optional, for track file names)
            is_multi_disc: Whether album has multiple discs

        Returns:
            Complete path (relative to music library root)
        """
        # Build metadata dict for template engine
        metadata = {
            'artist_name': album.artist.name if album.artist else 'Unknown Artist',
            'artist_clean_name': self.naming_engine.get_clean_name(
                album.artist.name if album.artist else 'Unknown Artist'
            ),
            'album_title': album.title,
            'album_clean_title': self.naming_engine.get_clean_name(album.title),
            'album_type': album.album_type or 'Album',
            'release_year': album.release_date.year if album.release_date else None,
        }

        # Build artist folder
        artist_folder = self.naming_engine.build_path(
            self.config.artist_folder_template,
            metadata,
            is_folder=True
        )

        # Build album folder
        album_folder = self.naming_engine.build_path(
            self.config.album_folder_template,
            metadata,
            is_folder=True
        )

        # Build full path
        full_path = Path(artist_folder) / album_folder

        # Add track filename if provided
        if track:
            track_metadata = {
                **metadata,
                'track_title': track.title,
                'track_clean_title': self.naming_engine.get_clean_name(track.title),
                'track_number': track.track_number or 0,
                'disc_number': track.disc_number or 1,
                'track_mbid': track.musicbrainz_id,
            }

            # Choose template based on multi-disc status
            if is_multi_disc:
                track_template = self.config.multi_disc_track_template
            else:
                track_template = self.config.track_file_template

            # Build track filename (without extension - will be added from source)
            track_file = self.naming_engine.build_path(
                track_template,
                track_metadata,
                is_folder=False
            )

            full_path = full_path / track_file

        return full_path

    def analyze_file_quality(self, file_path: Path) -> Dict[str, Any]:
        """
        Analyze audio file quality.

        Args:
            file_path: Path to audio file

        Returns:
            Quality information dict
        """
        try:
            # Detect from path (quick)
            quality_profile = self.quality_detector.detect_from_path(file_path)

            # TODO: Optionally read metadata using mutagen for more accurate detection
            # This would require adding mutagen as a dependency

            return quality_profile.to_dict()

        except Exception as e:
            logger.error(f"Failed to analyze quality for {file_path}: {e}")
            return {
                'quality': 'UNKNOWN',
                'quality_score': 0,
                'quality_title': 'Unknown',
                'codec': 'Unknown',
            }

    def should_upgrade(
        self,
        current_file: Path,
        new_file: Path
    ) -> bool:
        """
        Determine if new file is an upgrade over current file.

        Args:
            current_file: Path to current file
            new_file: Path to new file

        Returns:
            True if new file is better quality
        """
        if not self.config.upgrade_allowed:
            return False

        try:
            current_quality = self.quality_detector.detect_from_path(current_file)
            new_quality = self.quality_detector.detect_from_path(new_file)

            return self.quality_detector.is_upgrade(current_quality, new_quality)

        except Exception as e:
            logger.error(f"Failed to compare quality: {e}")
            return False

    def import_album(
        self,
        album: Album,
        source_directory: str,
        file_list: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Import album files using enhanced organization.

        Args:
            album: Album model
            source_directory: Directory containing downloaded files
            file_list: Optional list of specific files to import

        Returns:
            Import results dictionary
        """
        source_path = Path(source_directory)

        if not source_path.exists():
            raise FileNotFoundError(f"Source directory not found: {source_directory}")

        results = {
            'success': False,
            'imported_files': [],
            'skipped_files': [],
            'upgraded_files': [],
            'errors': [],
        }

        try:
            # Determine if multi-disc
            is_multi_disc = any(t.disc_number and t.disc_number > 1 for t in album.tracks)

            # Find all audio files in source
            audio_extensions = ['.flac', '.mp3', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.alac']
            source_files = []

            if file_list:
                # Use specified files
                source_files = [source_path / f for f in file_list if Path(f).suffix.lower() in audio_extensions]
            else:
                # Find all audio files
                source_files = [f for f in source_path.rglob('*') if f.is_file() and f.suffix.lower() in audio_extensions]

            logger.info(f"[Enhanced Import] Found {len(source_files)} audio files in {source_directory}")

            # Process each file
            for source_file in source_files:
                try:
                    # Analyze quality
                    quality_info = self.analyze_file_quality(source_file)

                    # Check minimum quality
                    if quality_info['quality_score'] < self.config.minimum_quality_score:
                        logger.info(
                            f"[Enhanced Import] Skipping {source_file.name}: "
                            f"Quality {quality_info['quality_score']} below minimum {self.config.minimum_quality_score}"
                        )
                        results['skipped_files'].append({
                            'file': source_file.name,
                            'reason': 'Below minimum quality',
                            'quality': quality_info,
                        })
                        continue

                    # Check minimum file size
                    file_size_mb = source_file.stat().st_size / (1024 * 1024)
                    if file_size_mb < self.config.minimum_file_size_mb:
                        logger.info(
                            f"[Enhanced Import] Skipping {source_file.name}: "
                            f"Size {file_size_mb:.2f}MB below minimum {self.config.minimum_file_size_mb}MB"
                        )
                        results['skipped_files'].append({
                            'file': source_file.name,
                            'reason': 'Below minimum size',
                            'size_mb': file_size_mb,
                        })
                        continue

                    # Try to match file to track (simplified - could be enhanced with metadata matching)
                    # For now, just use first available track or create generic path
                    if album.tracks:
                        track = album.tracks[0]  # Simplified - should match by metadata
                    else:
                        track = None

                    # Build destination path
                    if track and self.config.rename_tracks:
                        # Use naming template
                        dest_relative = self.build_album_path(album, track, is_multi_disc)
                        # Add extension from source file
                        dest_relative = Path(str(dest_relative) + source_file.suffix)
                    else:
                        # Keep original filename
                        dest_relative = self.build_album_path(album) / source_file.name

                    # Check if file already exists
                    dest_absolute = Path(self.config.music_library_path) / dest_relative
                    if dest_absolute.exists():
                        # Check if upgrade
                        if self.should_upgrade(dest_absolute, source_file):
                            logger.info(
                                f"[Enhanced Import] Upgrading: {source_file.name} -> {dest_relative}"
                            )
                            operation = FileOperation.UPGRADE
                            results['upgraded_files'].append(str(dest_relative))
                        elif self.config.replace_existing_files:
                            logger.info(
                                f"[Enhanced Import] Replacing: {source_file.name} -> {dest_relative}"
                            )
                            operation = FileOperation.IMPORT
                        else:
                            logger.info(
                                f"[Enhanced Import] Skipping {source_file.name}: File exists and replace disabled"
                            )
                            results['skipped_files'].append({
                                'file': source_file.name,
                                'reason': 'File exists',
                            })
                            continue
                    else:
                        operation = FileOperation.IMPORT

                    # Determine transfer mode
                    transfer_mode = TransferMode.HARDLINK if self.config.use_hardlinks else TransferMode.MOVE

                    # Import file using file organizer (with atomic operations)
                    # No backup - use checksum validation instead
                    import_result = self.file_organizer.import_file(
                        source_path=source_file,
                        dest_relative_path=str(dest_relative),
                        transfer_mode=transfer_mode,
                        create_backup=False,
                    )

                    if import_result.success:
                        logger.info(
                            f"[Enhanced Import] Successfully imported: {source_file.name} -> {dest_relative}"
                        )
                        results['imported_files'].append({
                            'source': source_file.name,
                            'destination': str(dest_relative),
                            'quality': quality_info,
                            'operation': operation.value,
                        })
                    else:
                        logger.error(
                            f"[Enhanced Import] Failed to import {source_file.name}: {import_result.error}"
                        )
                        results['errors'].append({
                            'file': source_file.name,
                            'error': import_result.error,
                        })

                except Exception as e:
                    logger.error(f"[Enhanced Import] Error processing {source_file.name}: {e}", exc_info=True)
                    results['errors'].append({
                        'file': source_file.name,
                        'error': str(e),
                    })

            # Clean up empty folders if configured
            if self.config.delete_empty_folders:
                try:
                    deleted_count = self.file_organizer.delete_empty_folders()
                    logger.info(f"[Enhanced Import] Deleted {deleted_count} empty folders")
                except Exception as e:
                    logger.error(f"[Enhanced Import] Failed to delete empty folders: {e}")

            # Trigger MUSE library scan if files were imported
            if results['imported_files']:
                try:
                    logger.info("[Enhanced Import] Triggering MUSE library scan")
                    # TODO: Trigger MUSE scan via API
                except Exception as e:
                    logger.error(f"[Enhanced Import] Failed to trigger MUSE scan: {e}")

            results['success'] = len(results['imported_files']) > 0
            return results

        except Exception as e:
            logger.error(f"[Enhanced Import] Album import failed: {e}", exc_info=True)
            results['errors'].append({'error': str(e)})
            return results

    def get_import_preview(
        self,
        album: Album,
        source_directory: str
    ) -> List[Dict[str, Any]]:
        """
        Preview what file paths will be created for an album import.

        Args:
            album: Album model
            source_directory: Directory containing files

        Returns:
            List of preview entries with source and destination paths
        """
        source_path = Path(source_directory)
        preview = []

        if not source_path.exists():
            return preview

        # Find audio files
        audio_extensions = ['.flac', '.mp3', '.m4a', '.aac', '.ogg', '.opus', '.wav']
        source_files = [f for f in source_path.rglob('*') if f.is_file() and f.suffix.lower() in audio_extensions]

        is_multi_disc = any(t.disc_number and t.disc_number > 1 for t in album.tracks)

        for source_file in source_files:
            # Analyze quality
            quality_info = self.analyze_file_quality(source_file)

            # Build destination path
            if album.tracks:
                track = album.tracks[0]  # Simplified
            else:
                track = None

            if track and self.config.rename_tracks:
                dest_relative = self.build_album_path(album, track, is_multi_disc)
                dest_relative = Path(str(dest_relative) + source_file.suffix)
            else:
                dest_relative = self.build_album_path(album) / source_file.name

            preview.append({
                'source': source_file.name,
                'destination': str(dest_relative),
                'quality': quality_info,
                'size_mb': round(source_file.stat().st_size / (1024 * 1024), 2),
            })

        return preview
