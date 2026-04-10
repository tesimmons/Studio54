"""
Folder Creator Service
Creates empty artist and album folders based on naming templates
"""
import logging
from pathlib import Path
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.artist import Artist
from app.models.album import Album
from app.models.media_management import MediaManagementConfig
from app.services.naming_template_engine import NamingTemplateEngine

logger = logging.getLogger(__name__)


class FolderCreator:
    """
    Service for creating empty artist and album folders
    based on configured naming templates
    """

    def __init__(self, db: Session):
        """
        Initialize folder creator

        Args:
            db: Database session
        """
        self.db = db
        self.template_engine = NamingTemplateEngine()
        self._config: Optional[MediaManagementConfig] = None

    @property
    def config(self) -> MediaManagementConfig:
        """Get or load media management configuration"""
        if not self._config:
            self._config = self.db.query(MediaManagementConfig).first()
            if not self._config:
                logger.warning("No media management config found, using defaults")
                self._config = MediaManagementConfig()
        return self._config

    def create_artist_folder(self, artist: Artist) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create empty folder for an artist

        Args:
            artist: Artist model instance

        Returns:
            Tuple of (success, folder_path, error_message)
        """
        if not self.config.create_folders_on_monitor:
            logger.debug("Folder creation on monitor is disabled")
            return False, None, "Folder creation disabled"

        try:
            # Build artist folder path using naming template
            metadata = {
                'artist_name': artist.name,
                'artist_mbid': artist.musicbrainz_id,
                'artist_disambiguation': artist.disambiguation,
                'artist_clean_name': self.template_engine.get_clean_name(artist.name),
            }
            artist_folder = self.template_engine.build_path(
                self.config.artist_folder_template,
                metadata,
                is_folder=True
            )

            full_path = Path(self.config.music_library_path) / artist_folder

            # Create directory
            full_path.mkdir(parents=True, exist_ok=True)

            # Set permissions if configured
            if self.config.set_permissions_linux and self.config.chmod_folder:
                try:
                    mode = int(self.config.chmod_folder, 8)
                    full_path.chmod(mode)
                except (ValueError, OSError) as e:
                    logger.warning(f"Failed to set folder permissions: {e}")

            logger.info(f"Created artist folder: {full_path}")
            return True, str(full_path), None

        except Exception as e:
            error_msg = f"Failed to create artist folder for {artist.name}: {e}"
            logger.error(error_msg, exc_info=True)
            return False, None, error_msg

    def create_album_folder(self, album: Album, artist: Artist) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create empty folder for an album

        Args:
            album: Album model instance
            artist: Artist model instance (album's artist)

        Returns:
            Tuple of (success, folder_path, error_message)
        """
        if not self.config.create_folders_on_monitor:
            logger.debug("Folder creation on monitor is disabled")
            return False, None, "Folder creation disabled"

        try:
            # Build artist and album folder paths using naming templates
            metadata = {
                'artist_name': artist.name,
                'artist_mbid': artist.musicbrainz_id,
                'artist_disambiguation': artist.disambiguation,
                'artist_clean_name': self.template_engine.get_clean_name(artist.name),
                'album_title': album.title,
                'album_clean_title': self.template_engine.get_clean_name(album.title),
                'album_type': album.album_type,
                'release_year': album.release_date.year if album.release_date else None,
                'release_date': album.release_date.isoformat() if album.release_date else None,
                'album_mbid': album.musicbrainz_id,
                'album_disambiguation': album.disambiguation,
            }
            artist_folder = self.template_engine.build_path(
                self.config.artist_folder_template,
                metadata,
                is_folder=True
            )
            album_folder = self.template_engine.build_path(
                self.config.album_folder_template,
                metadata,
                is_folder=True
            )

            full_path = Path(self.config.music_library_path) / artist_folder / album_folder

            # Create directory
            full_path.mkdir(parents=True, exist_ok=True)

            # Set permissions if configured
            if self.config.set_permissions_linux and self.config.chmod_folder:
                try:
                    mode = int(self.config.chmod_folder, 8)
                    full_path.chmod(mode)
                    # Also set parent (artist) folder permissions
                    full_path.parent.chmod(mode)
                except (ValueError, OSError) as e:
                    logger.warning(f"Failed to set folder permissions: {e}")

            logger.info(f"Created album folder: {full_path}")
            return True, str(full_path), None

        except Exception as e:
            error_msg = f"Failed to create album folder for {album.title}: {e}"
            logger.error(error_msg, exc_info=True)
            return False, None, error_msg


def get_folder_creator(db: Session) -> FolderCreator:
    """
    Factory function to get a FolderCreator instance

    Args:
        db: Database session

    Returns:
        FolderCreator instance
    """
    return FolderCreator(db)
