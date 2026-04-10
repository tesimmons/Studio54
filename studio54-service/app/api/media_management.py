"""
Media Management API Endpoints
Handles configuration for file naming, organization, and import behavior
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.media_management import MediaManagementConfig
from app.services.naming_template_engine import NamingTemplateEngine, DEFAULT_TEMPLATES
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media-management", tags=["media-management"])


# === Pydantic Models ===

class MediaManagementUpdate(BaseModel):
    """Request model for updating media management settings."""

    # File naming templates
    artist_folder_template: Optional[str] = None
    album_folder_template: Optional[str] = None
    track_file_template: Optional[str] = None
    multi_disc_track_template: Optional[str] = None
    colon_replacement: Optional[str] = Field(None, pattern="^(smart|dash|space_dash|delete)$")

    # File organization
    music_library_path: Optional[str] = None
    rename_tracks: Optional[bool] = None
    replace_existing_files: Optional[bool] = None
    use_hardlinks: Optional[bool] = None

    # Recycle bin
    recycle_bin_path: Optional[str] = None
    recycle_bin_cleanup_days: Optional[int] = Field(None, ge=1, le=365)
    auto_cleanup_recycle_bin: Optional[bool] = None

    # Import behavior
    minimum_file_size_mb: Optional[int] = Field(None, ge=0, le=1000)
    skip_free_space_check: Optional[bool] = None
    minimum_free_space_mb: Optional[int] = Field(None, ge=0, le=100000)
    sabnzbd_download_path: Optional[str] = None
    import_extra_files: Optional[bool] = None
    extra_file_extensions: Optional[str] = None

    # Folder management
    create_empty_artist_folders: Optional[bool] = None
    delete_empty_folders: Optional[bool] = None
    create_folders_on_monitor: Optional[bool] = None

    # Unix permissions
    set_permissions_linux: Optional[bool] = None
    chmod_folder: Optional[str] = Field(None, pattern="^[0-7]{3}$")
    chmod_file: Optional[str] = Field(None, pattern="^[0-7]{3}$")
    chown_group: Optional[str] = None

    # Quality preferences
    upgrade_allowed: Optional[bool] = None
    prefer_lossless: Optional[bool] = None
    minimum_quality_score: Optional[int] = Field(None, ge=0, le=500)


class NamingTemplateValidation(BaseModel):
    """Request model for validating naming templates."""
    template: str


# === Helper Functions ===

def get_or_create_config(db: Session) -> MediaManagementConfig:
    """Get existing config or create default."""
    config = db.query(MediaManagementConfig).first()
    if not config:
        logger.info("Creating default media management configuration")
        config = MediaManagementConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


# === Endpoints ===

@router.get("")
async def get_media_management_settings(
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get current media management settings.

    Returns the current configuration for file naming, organization, and import behavior.
    If no configuration exists, creates default settings.
    """
    config = get_or_create_config(db)
    return config.to_dict()


@router.put("")
async def update_media_management_settings(
    updates: MediaManagementUpdate,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update media management settings.

    Partial updates are supported - only provided fields will be updated.

    Request Body:
    - artist_folder_template: Template for artist folders
    - album_folder_template: Template for album folders
    - track_file_template: Template for track files
    - multi_disc_track_template: Template for multi-disc tracks
    - colon_replacement: How to handle colons in filenames (smart/dash/space_dash/delete)
    - music_library_path: Root path for music library
    - rename_tracks: Rename tracks after import
    - replace_existing_files: Allow file upgrades
    - use_hardlinks: Use hardlinks for copying
    - recycle_bin_path: Path for deleted files (null = permanent delete)
    - recycle_bin_cleanup_days: Days to keep files in recycle bin
    - auto_cleanup_recycle_bin: Auto-cleanup old files
    - minimum_file_size_mb: Skip files smaller than this
    - skip_free_space_check: Skip free space validation
    - minimum_free_space_mb: Minimum free space required
    - import_extra_files: Import non-audio files (covers, lyrics)
    - extra_file_extensions: Comma-separated list of extra file extensions
    - create_empty_artist_folders: Create folders even if empty
    - delete_empty_folders: Delete empty folders after cleanup
    - set_permissions_linux: Set permissions on Linux
    - chmod_folder: Folder permissions (octal, e.g., "755")
    - chmod_file: File permissions (octal, e.g., "644")
    - chown_group: Group ownership
    - upgrade_allowed: Allow quality upgrades
    - prefer_lossless: Prefer lossless formats
    - minimum_quality_score: Minimum quality score (0-500)
    """
    config = get_or_create_config(db)

    # Validate naming templates if provided
    engine = NamingTemplateEngine()

    if updates.artist_folder_template:
        is_valid, error = engine.validate_template(updates.artist_folder_template)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid artist folder template: {error}")
        config.artist_folder_template = updates.artist_folder_template

    if updates.album_folder_template:
        is_valid, error = engine.validate_template(updates.album_folder_template)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid album folder template: {error}")
        config.album_folder_template = updates.album_folder_template

    if updates.track_file_template:
        is_valid, error = engine.validate_template(updates.track_file_template)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid track file template: {error}")
        config.track_file_template = updates.track_file_template

    if updates.multi_disc_track_template:
        is_valid, error = engine.validate_template(updates.multi_disc_track_template)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid multi-disc track template: {error}")
        config.multi_disc_track_template = updates.multi_disc_track_template

    # Update other fields
    update_dict = updates.dict(exclude_unset=True, exclude={
        'artist_folder_template',
        'album_folder_template',
        'track_file_template',
        'multi_disc_track_template',
    })

    for field, value in update_dict.items():
        if hasattr(config, field):
            setattr(config, field, value)

    db.commit()
    db.refresh(config)

    logger.info("Media management settings updated")
    return config.to_dict()


@router.post("/validate-template")
async def validate_naming_template(
    validation: NamingTemplateValidation
) -> Dict[str, Any]:
    """
    Validate a naming template.

    Checks template syntax and provides example output.

    Request Body:
    - template: Template string to validate

    Returns:
    - is_valid: Whether template is valid
    - error: Error message if invalid
    - example: Example output using sample metadata
    """
    engine = NamingTemplateEngine()

    is_valid, error = engine.validate_template(validation.template)

    result = {
        'is_valid': is_valid,
        'error': error,
    }

    if is_valid:
        # Generate example output
        example = engine.get_example_output(validation.template)
        result['example'] = example

    return result


@router.get("/naming-templates")
async def get_naming_templates() -> Dict[str, Any]:
    """
    Get predefined naming templates.

    Returns a dictionary of template presets that users can choose from.

    Templates:
    - standard: Artist/Album (Year)/Artist - Album - 01 - Title
    - multi_disc: Artist/Album (Year)/1-01 - Title
    - simple: Artist/Album/01 - Title
    - quality: Artist/Album (Year) [FLAC]/01 - Title
    """
    return {'templates': DEFAULT_TEMPLATES}


@router.get("/naming-tokens")
async def get_naming_tokens() -> Dict[str, Any]:
    """
    Get available naming template tokens.

    Returns a list of all supported tokens with descriptions.
    """
    tokens = {
        'artist': {
            'artist_name': 'Artist name',
            'artist_clean_name': 'Artist name (cleaned)',
            'artist_first_char': 'First character of artist name',
            'artist_mbid': 'Artist MusicBrainz ID',
            'artist_disambiguation': 'Artist disambiguation',
        },
        'album': {
            'album_title': 'Album title',
            'album_clean_title': 'Album title (cleaned)',
            'album_type': 'Album type (Album, EP, Single, etc.)',
            'album_mbid': 'Album MusicBrainz ID',
            'album_disambiguation': 'Album disambiguation',
            'release_year': 'Release year',
            'release_date': 'Release date',
            'album_genre': 'Album genre',
        },
        'track': {
            'track_title': 'Track title',
            'track_clean_title': 'Track title (cleaned)',
            'track_number': 'Track number',
            'disc_number': 'Disc number',
            'track_mbid': 'Track MusicBrainz ID',
            'track_artist': 'Track artist (if different from album artist)',
        },
        'quality': {
            'quality_title': 'Quality (e.g., FLAC, MP3 320kbps)',
            'quality_full': 'Full quality description',
        },
        'mediainfo': {
            'mediainfo_audiocodec': 'Audio codec (FLAC, MP3, AAC, etc.)',
            'mediainfo_audiobitrate': 'Audio bitrate',
            'mediainfo_audiochannels': 'Audio channels',
            'mediainfo_audiosamplerate': 'Audio sample rate',
        },
        'file': {
            'original_filename': 'Original filename',
            'file_extension': 'File extension',
        },
        'special': {
            'track:00': 'Track number with zero-padding (e.g., 01, 02)',
            'disc:0': 'Disc number with zero-padding (e.g., 1, 2)',
            '{ARTIST NAME}': 'UPPERCASE transformation',
            '{artist name}': 'lowercase transformation',
            '{Artist-Name}': 'Space replacement (e.g., Pink-Floyd)',
            '{Title:20}': 'Truncate to 20 characters',
        },
    }

    return {'tokens': tokens}


@router.get("/library-stats")
async def get_library_stats(
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get statistics about the music library.

    Returns:
    - total_files: Number of files in library
    - total_size: Total size in bytes
    - total_size_mb: Total size in MB
    - total_size_gb: Total size in GB
    - total_directories: Number of directories
    - library_path: Music library path
    """
    from pathlib import Path
    from app.services.file_organizer import get_file_organizer

    config = get_or_create_config(db)

    try:
        organizer = get_file_organizer(
            music_library_path=config.music_library_path,
            recycle_bin_path=config.recycle_bin_path,
        )

        stats = organizer.get_library_stats()
        return stats

    except Exception as e:
        logger.error(f"Failed to get library stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get library stats: {str(e)}")


@router.post("/cleanup-recycle-bin")
async def cleanup_recycle_bin(
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Clean up old files from recycle bin.

    Removes files older than recycle_bin_cleanup_days.

    Returns:
    - deleted_files: Number of files deleted
    - deleted_size: Total size freed (bytes)
    """
    from app.services.file_organizer import get_file_organizer

    config = get_or_create_config(db)

    if not config.recycle_bin_path:
        raise HTTPException(status_code=400, detail="Recycle bin is not configured")

    try:
        organizer = get_file_organizer(
            music_library_path=config.music_library_path,
            recycle_bin_path=config.recycle_bin_path,
            recycle_bin_days=config.recycle_bin_cleanup_days,
        )

        result = organizer.cleanup_recycle_bin()
        return result

    except Exception as e:
        logger.error(f"Failed to cleanup recycle bin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cleanup recycle bin: {str(e)}")


@router.post("/delete-empty-folders")
async def delete_empty_folders(
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Delete empty folders in music library.

    Returns:
    - deleted_count: Number of folders deleted
    """
    from app.services.file_organizer import get_file_organizer

    config = get_or_create_config(db)

    try:
        organizer = get_file_organizer(
            music_library_path=config.music_library_path,
            recycle_bin_path=config.recycle_bin_path,
        )

        deleted_count = organizer.delete_empty_folders()
        return {'deleted_count': deleted_count}

    except Exception as e:
        logger.error(f"Failed to delete empty folders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete empty folders: {str(e)}")
