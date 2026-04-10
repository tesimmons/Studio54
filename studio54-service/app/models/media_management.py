"""
Media Management Configuration Model
Stores settings for file organization, naming, and import behavior
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Integer, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class MediaManagementConfig(Base):
    """
    Media management configuration settings.

    Stores user preferences for:
    - File naming templates
    - Import behavior
    - Recycle bin settings
    - Permissions
    """
    __tablename__ = "media_management_config"

    # Primary key (single row configuration)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # === File Naming Templates ===
    # Artist folder template (e.g., "{Artist Name}")
    artist_folder_template = Column(
        Text,
        default="{Artist Name}",
        nullable=False
    )

    # Album folder template (e.g., "{Album Title} ({Release Year})")
    album_folder_template = Column(
        Text,
        default="{Album Title} ({Release Year})",
        nullable=False
    )

    # Track file template (e.g., "{track:00} - {Track Title}")
    track_file_template = Column(
        Text,
        default="{Artist Name} - {Album Title} - {track:00} - {Track Title}",
        nullable=False
    )

    # Multi-disc track file template
    multi_disc_track_template = Column(
        Text,
        default="{disc:0}-{track:00} - {Track Title}",
        nullable=False
    )

    # === File Organization Settings ===
    # Root music library path
    music_library_path = Column(
        Text,
        default="/music",
        nullable=False
    )

    # Colon replacement strategy ('smart', 'dash', 'space_dash', 'delete')
    colon_replacement = Column(
        String(20),
        default="smart",
        nullable=False
    )

    # Rename tracks after import
    rename_tracks = Column(Boolean, default=True, nullable=False)

    # Replace existing files (allow upgrades)
    replace_existing_files = Column(Boolean, default=True, nullable=False)

    # Use hardlinks for copying (saves space)
    use_hardlinks = Column(Boolean, default=False, nullable=False)

    # === Recycle Bin Settings ===
    # Recycle bin path (null = permanent delete)
    recycle_bin_path = Column(Text, nullable=True)

    # Days to keep files in recycle bin before cleanup
    recycle_bin_cleanup_days = Column(Integer, default=30, nullable=False)

    # Auto-cleanup recycle bin
    auto_cleanup_recycle_bin = Column(Boolean, default=True, nullable=False)

    # === Import Behavior ===
    # Skip files smaller than this size (MB)
    minimum_file_size_mb = Column(Integer, default=1, nullable=False)

    # Skip free space check when importing
    skip_free_space_check = Column(Boolean, default=False, nullable=False)

    # Minimum free space required (MB)
    minimum_free_space_mb = Column(Integer, default=100, nullable=False)

    # SABnzbd download directory (optional override)
    sabnzbd_download_path = Column(
        Text,
        nullable=True,
        default=None
    )

    # Import extra files (covers, lyrics, etc.)
    import_extra_files = Column(Boolean, default=True, nullable=False)

    # Extra file extensions (comma-separated)
    extra_file_extensions = Column(
        Text,
        default="jpg,png,jpeg,lrc,txt,pdf,log,cue",
        nullable=False
    )

    # === Folder Management ===
    # Create empty artist folders
    create_empty_artist_folders = Column(Boolean, default=False, nullable=False)

    # Delete empty folders after cleanup
    delete_empty_folders = Column(Boolean, default=True, nullable=False)

    # Create folders when artist/album is monitored or searched
    create_folders_on_monitor = Column(Boolean, default=True, nullable=False)

    # === Unix Permissions ===
    # Set permissions on Linux
    set_permissions_linux = Column(Boolean, default=False, nullable=False)

    # Folder permissions (octal, e.g., "755")
    chmod_folder = Column(String(10), default="755", nullable=True)

    # File permissions (octal, e.g., "644")
    chmod_file = Column(String(10), default="644", nullable=True)

    # Group ownership
    chown_group = Column(String(50), nullable=True)

    # === Quality Preferences ===
    # Upgrade allowed
    upgrade_allowed = Column(Boolean, default=True, nullable=False)

    # Prefer lossless formats
    prefer_lossless = Column(Boolean, default=True, nullable=False)

    # Minimum quality score (0-500)
    minimum_quality_score = Column(Integer, default=128, nullable=False)

    # === Timestamps ===
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self):
        return f"<MediaManagementConfig(id={self.id}, library_path='{self.music_library_path}')>"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': str(self.id),

            # File naming
            'artist_folder_template': self.artist_folder_template,
            'album_folder_template': self.album_folder_template,
            'track_file_template': self.track_file_template,
            'multi_disc_track_template': self.multi_disc_track_template,
            'colon_replacement': self.colon_replacement,

            # File organization
            'music_library_path': self.music_library_path,
            'rename_tracks': self.rename_tracks,
            'replace_existing_files': self.replace_existing_files,
            'use_hardlinks': self.use_hardlinks,

            # Recycle bin
            'recycle_bin_path': self.recycle_bin_path,
            'recycle_bin_cleanup_days': self.recycle_bin_cleanup_days,
            'auto_cleanup_recycle_bin': self.auto_cleanup_recycle_bin,

            # Import behavior
            'minimum_file_size_mb': self.minimum_file_size_mb,
            'skip_free_space_check': self.skip_free_space_check,
            'minimum_free_space_mb': self.minimum_free_space_mb,
            'sabnzbd_download_path': self.sabnzbd_download_path,
            'import_extra_files': self.import_extra_files,
            'extra_file_extensions': self.extra_file_extensions,

            # Folder management
            'create_empty_artist_folders': self.create_empty_artist_folders,
            'delete_empty_folders': self.delete_empty_folders,
            'create_folders_on_monitor': self.create_folders_on_monitor,

            # Unix permissions
            'set_permissions_linux': self.set_permissions_linux,
            'chmod_folder': self.chmod_folder,
            'chmod_file': self.chmod_file,
            'chown_group': self.chown_group,

            # Quality preferences
            'upgrade_allowed': self.upgrade_allowed,
            'prefer_lossless': self.prefer_lossless,
            'minimum_quality_score': self.minimum_quality_score,

            # Timestamps
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
