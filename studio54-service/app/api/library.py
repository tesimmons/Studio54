"""
Library Scanner API Router
Manage library paths and file scanning
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import logging
import os

from app.database import get_db
from app.models.library import LibraryPath, LibraryFile, ScanJob
from app.models.library_import import LibraryImportJob, LibraryArtistMatch
from app.security import rate_limit, validate_uuid
from app.auth import require_director, require_any_user
from app.models.user import User
from app.tasks.library_tasks import fetch_missing_images, cleanup_orphaned_files
from app.tasks.scan_coordinator_v2 import scan_library_v2
from app.tasks.import_tasks import orchestrate_library_import
from app.tasks.book_import_task import orchestrate_book_import
from app.services.metadata_extractor import MetadataExtractor
from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic schemas
class LibraryPathCreate(BaseModel):
    path: str = Field(..., description="Absolute path to music/audiobook directory")
    name: str = Field(..., min_length=1, max_length=255)
    is_enabled: bool = Field(default=True)
    library_type: str = Field(default="music", description="Library type: 'music' or 'audiobook'")


class LibraryPathUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_enabled: Optional[bool] = None


class ScanRequest(BaseModel):
    incremental: bool = Field(default=True, description="Skip unchanged files")
    fetch_images: bool = Field(default=True, description="Fetch MusicBrainz images")


class ImportRequest(BaseModel):
    auto_match_artists: bool = Field(default=True, description="Automatically match high-confidence artists")
    auto_assign_folders: bool = Field(default=True, description="Automatically assign folder structures to albums")
    auto_match_tracks: bool = Field(default=True, description="Automatically match tracks to files via MBID")
    confidence_threshold: int = Field(default=85, ge=0, le=100, description="Minimum confidence for auto-matching (0-100)")


class ArtistMatchRequest(BaseModel):
    artist_match_id: str = Field(..., description="LibraryArtistMatch UUID")
    musicbrainz_id: str = Field(..., description="Selected MusicBrainz Artist ID")
    create_new: bool = Field(default=True, description="Create new Studio54 artist if not exists")


@router.get("/library/paths")
@rate_limit("100/minute")
async def list_library_paths(
    request: Request,
    library_type: Optional[str] = None,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List all library paths

    Args:
        library_type: Optional filter by library type ('music' or 'audiobook')

    Returns:
        List of library paths with statistics
    """
    query = db.query(LibraryPath)
    if library_type:
        query = query.filter(LibraryPath.library_type == library_type)
    paths = query.order_by(LibraryPath.created_at).all()

    return {
        "library_paths": [
            {
                "id": str(path.id),
                "path": path.path,
                "name": path.name,
                "is_enabled": path.is_enabled,
                "library_type": getattr(path, 'library_type', 'music'),
                "total_files": path.total_files,
                "total_size_bytes": path.total_size_bytes,
                "last_scan_at": path.last_scan_at.isoformat() if path.last_scan_at else None,
                "created_at": path.created_at.isoformat() if path.created_at else None,
            }
            for path in paths
        ]
    }


@router.post("/library/paths", status_code=status.HTTP_201_CREATED)
@rate_limit("30/minute")
async def create_library_path(
    request: Request,
    path_data: LibraryPathCreate,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Add a new library path

    Args:
        path_data: Library path configuration

    Returns:
        Created library path
    """
    # Validate path exists
    if not os.path.exists(path_data.path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path does not exist: {path_data.path}"
        )

    if not os.path.isdir(path_data.path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {path_data.path}"
        )

    # Check for duplicate path
    existing = db.query(LibraryPath).filter(LibraryPath.path == path_data.path).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Library path already exists: {path_data.path}"
        )

    # Validate library_type
    library_type = getattr(path_data, 'library_type', 'music') or 'music'
    if library_type not in ('music', 'audiobook'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="library_type must be 'music' or 'audiobook'"
        )

    # Create library path
    library_path = LibraryPath(
        path=path_data.path,
        name=path_data.name,
        is_enabled=path_data.is_enabled,
        library_type=library_type,
    )

    db.add(library_path)
    db.commit()
    db.refresh(library_path)

    logger.info(f"Created library path: {library_path.path}")

    return {
        "id": str(library_path.id),
        "path": library_path.path,
        "name": library_path.name,
        "is_enabled": library_path.is_enabled,
        "library_type": library_path.library_type,
        "total_files": 0,
        "created_at": library_path.created_at.isoformat()
    }


@router.patch("/library/paths/{path_id}")
@rate_limit("30/minute")
async def update_library_path(
    request: Request,
    path_id: str,
    path_data: LibraryPathUpdate,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Update library path"""
    validate_uuid(path_id, "Library path ID")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found"
        )

    if path_data.name is not None:
        library_path.name = path_data.name

    if path_data.is_enabled is not None:
        library_path.is_enabled = path_data.is_enabled

    library_path.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Library path updated successfully"}


@router.delete("/library/paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("30/minute")
async def delete_library_path(
    request: Request,
    path_id: str,
    delete_files: bool = False,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Delete library path

    Args:
        path_id: Library path UUID
        delete_files: If true, also delete file records (CASCADE handled by DB)
    """
    validate_uuid(path_id, "Library path ID")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found"
        )

    logger.info(f"Deleting library path: {library_path.path}")
    db.delete(library_path)
    db.commit()


@router.post("/library/paths/{path_id}/scan")
@rate_limit("10/minute")
async def start_scan(
    request: Request,
    path_id: str,
    scan_request: ScanRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start library scan

    Args:
        path_id: Library path UUID
        scan_request: Scan configuration

    Returns:
        Scan job information
    """
    validate_uuid(path_id, "Library path ID")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found"
        )

    if not library_path.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Library path is disabled"
        )

    # Check for active scans
    active_scan = db.query(ScanJob).filter(
        ScanJob.library_path_id == path_id,
        ScanJob.status.in_(['pending', 'running'])
    ).first()

    if active_scan:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scan is already in progress for this library"
        )

    # Create scan job
    scan_job = ScanJob(
        library_path_id=path_id,
        status='pending'
    )

    db.add(scan_job)
    db.commit()
    db.refresh(scan_job)

    # Start V2 Celery task (two-phase scanning)
    task = scan_library_v2.delay(
        library_path_id=str(path_id),
        scan_job_id=str(scan_job.id),
        incremental=scan_request.incremental,
        batch_size=100  # Process 100 files per batch
    )

    scan_job.celery_task_id = task.id
    db.commit()

    logger.info(f"Started scan job {scan_job.id} for library {library_path.path}")

    return {
        "scan_job_id": str(scan_job.id),
        "celery_task_id": task.id,
        "status": "pending",
        "message": "Scan started successfully"
    }


@router.get("/library/scans")
@rate_limit("100/minute")
async def list_scans(
    request: Request,
    library_path_id: Optional[str] = None,
    library_type: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List scan jobs

    Args:
        library_path_id: Optional filter by library path
        library_type: Optional filter by library type ('music' or 'audiobook')
        limit: Max results

    Returns:
        List of scan jobs
    """
    query = db.query(ScanJob)

    if library_path_id:
        validate_uuid(library_path_id, "Library path ID")
        query = query.filter(ScanJob.library_path_id == library_path_id)

    if library_type:
        query = query.join(LibraryPath, ScanJob.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )

    scans = query.order_by(desc(ScanJob.created_at)).limit(limit).all()

    return {
        "scans": [
            {
                "id": str(scan.id),
                "library_path_id": str(scan.library_path_id),
                "status": scan.status,
                "files_scanned": scan.files_scanned,
                "files_added": scan.files_added,
                "files_updated": scan.files_updated,
                "files_skipped": scan.files_skipped,
                "files_failed": scan.files_failed,
                "error_message": scan.error_message,
                "started_at": scan.started_at.isoformat() if scan.started_at else None,
                "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
                "created_at": scan.created_at.isoformat()
            }
            for scan in scans
        ]
    }


@router.get("/library/scans/{scan_id}")
@rate_limit("100/minute")
async def get_scan_status(
    request: Request,
    scan_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Get scan job status"""
    validate_uuid(scan_id, "Scan ID")

    scan = db.query(ScanJob).filter(ScanJob.id == scan_id).first()
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan job not found"
        )

    return {
        "id": str(scan.id),
        "library_path_id": str(scan.library_path_id),
        "status": scan.status,
        "files_scanned": scan.files_scanned,
        "files_added": scan.files_added,
        "files_updated": scan.files_updated,
        "files_skipped": scan.files_skipped,
        "files_failed": scan.files_failed,
        "error_message": scan.error_message,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "duration_seconds": (
            (scan.completed_at - scan.started_at).total_seconds()
            if scan.completed_at and scan.started_at
            else None
        )
    }


@router.post("/library/scans/{scan_id}/cancel")
@rate_limit("30/minute")
async def cancel_scan(
    request: Request,
    scan_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Cancel a running scan job

    Args:
        scan_id: Scan job UUID

    Returns:
        Cancellation status
    """
    from app.tasks.celery_app import celery_app

    validate_uuid(scan_id, "Scan ID")

    scan = db.query(ScanJob).filter(ScanJob.id == scan_id).first()
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan job not found"
        )

    if scan.status not in ['pending', 'running']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel scan with status: {scan.status}"
        )

    # Revoke Celery task
    if scan.celery_task_id:
        celery_app.control.revoke(scan.celery_task_id, terminate=True)
        logger.info(f"Revoked Celery task: {scan.celery_task_id}")

    # Update scan job status
    scan.status = 'cancelled'
    scan.error_message = 'Scan cancelled by user'
    scan.completed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "message": "Scan cancelled successfully",
        "scan_id": str(scan.id),
        "status": "cancelled"
    }


@router.post("/library/files/{file_id}/rescan")
@rate_limit("50/minute")
async def rescan_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Rescan a single file to refresh metadata

    Args:
        file_id: LibraryFile UUID

    Returns:
        Updated file data
    """
    validate_uuid(file_id, "File ID")

    file_record = db.query(LibraryFile).filter(LibraryFile.id == file_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Check if file still exists
    if not os.path.exists(file_record.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File no longer exists on disk"
        )

    try:
        # Extract fresh metadata
        metadata = MetadataExtractor.extract(file_record.file_path)
        file_stat = os.stat(file_record.file_path)

        # Update file record
        file_record.file_size_bytes = file_stat.st_size
        file_record.file_modified_at = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc)

        # Update metadata fields
        for key, value in metadata.items():
            if hasattr(file_record, key):
                setattr(file_record, key, value)

        file_record.updated_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"Rescanned file: {file_record.file_path}")

        return {
            "message": "File rescanned successfully",
            "file_id": str(file_record.id),
            "file_path": file_record.file_path
        }

    except Exception as e:
        logger.error(f"Failed to rescan file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rescan file: {str(e)}"
        )


@router.post("/library/rescan-by-album")
@rate_limit("20/minute")
async def rescan_by_album(
    request: Request,
    album: str,
    artist: Optional[str] = None,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Rescan all files for a specific album

    Args:
        album: Album name
        artist: Optional artist name for more specific filtering

    Returns:
        Count of files queued for rescan
    """
    from app.tasks.library_tasks import rescan_files

    query = db.query(LibraryFile).filter(LibraryFile.album.ilike(f"%{album}%"))

    if artist:
        query = query.filter(LibraryFile.artist.ilike(f"%{artist}%"))

    files = query.all()

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No files found for the specified album"
        )

    file_ids = [str(f.id) for f in files]

    # Queue background task
    task = rescan_files.delay(file_ids)

    return {
        "message": f"Queued {len(files)} files for rescan",
        "file_count": len(files),
        "task_id": task.id
    }


@router.post("/library/rescan-by-artist")
@rate_limit("20/minute")
async def rescan_by_artist(
    request: Request,
    artist: str,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Rescan all files for a specific artist

    Args:
        artist: Artist name

    Returns:
        Count of files queued for rescan
    """
    from app.tasks.library_tasks import rescan_files

    files = db.query(LibraryFile).filter(
        LibraryFile.artist.ilike(f"%{artist}%")
    ).all()

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No files found for the specified artist"
        )

    file_ids = [str(f.id) for f in files]

    # Queue background task
    task = rescan_files.delay(file_ids)

    return {
        "message": f"Queued {len(files)} files for rescan",
        "file_count": len(files),
        "task_id": task.id
    }


@router.get("/library/files")
@rate_limit("100/minute")
async def search_files(
    request: Request,
    library_path_id: Optional[str] = None,
    library_type: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    title: Optional[str] = None,
    format: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Search library files

    Args:
        library_path_id: Filter by library path
        library_type: Filter by library type ('music' or 'audiobook')
        artist: Search by artist name
        album: Search by album name
        title: Search by title
        format: Filter by audio format
        limit: Max results
        offset: Pagination offset

    Returns:
        List of matching files
    """
    query = db.query(LibraryFile)

    if library_path_id:
        validate_uuid(library_path_id, "Library path ID")
        query = query.filter(LibraryFile.library_path_id == library_path_id)

    if library_type:
        query = query.join(LibraryPath, LibraryFile.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )

    if artist:
        query = query.filter(LibraryFile.artist.ilike(f"%{artist}%"))

    if album:
        query = query.filter(LibraryFile.album.ilike(f"%{album}%"))

    if title:
        query = query.filter(LibraryFile.title.ilike(f"%{title}%"))

    if format:
        query = query.filter(LibraryFile.format == format.upper())

    total_count = query.count()
    files = query.order_by(LibraryFile.artist, LibraryFile.album, LibraryFile.track_number).limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "files": [
            {
                "id": str(f.id),
                "file_path": f.file_path,
                "title": f.title,
                "artist": f.artist,
                "album": f.album,
                "track_number": f.track_number,
                "year": f.year,
                "format": f.format,
                "duration_seconds": f.duration_seconds,
                "musicbrainz_trackid": f.musicbrainz_trackid,
                "musicbrainz_albumid": f.musicbrainz_albumid,
                "musicbrainz_artistid": f.musicbrainz_artistid,
                "album_art_url": f.album_art_url,
                "artist_image_url": f.artist_image_url,
            }
            for f in files
        ]
    }


@router.get("/library/stats")
@rate_limit("60/minute")
async def get_library_stats(
    request: Request,
    library_type: Optional[str] = None,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get library statistics

    Args:
        library_type: Optional filter by library type ('music' or 'audiobook')

    Returns:
        Overall library statistics
    """
    # Base file query, optionally filtered by library_type
    file_query = db.query(LibraryFile)
    if library_type:
        file_query = file_query.join(LibraryPath, LibraryFile.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )

    total_files = file_query.with_entities(func.count(LibraryFile.id)).scalar() or 0
    total_size = file_query.with_entities(func.sum(LibraryFile.file_size_bytes)).scalar() or 0

    path_query = db.query(func.count(LibraryPath.id))
    if library_type:
        path_query = path_query.filter(LibraryPath.library_type == library_type)
    total_paths = path_query.scalar() or 0

    # Count by format
    format_query = db.query(
        LibraryFile.format,
        func.count(LibraryFile.id).label('count')
    )
    if library_type:
        format_query = format_query.join(LibraryPath, LibraryFile.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )
    formats = format_query.group_by(LibraryFile.format).all()

    # Count with MusicBrainz IDs
    mb_base = db.query(func.count(LibraryFile.id))
    if library_type:
        mb_base = mb_base.join(LibraryPath, LibraryFile.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )

    with_mb_track = mb_base.filter(
        LibraryFile.musicbrainz_trackid.isnot(None)
    ).scalar() or 0

    # Re-create base for each count to avoid stacking filters
    mb_base2 = db.query(func.count(LibraryFile.id))
    if library_type:
        mb_base2 = mb_base2.join(LibraryPath, LibraryFile.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )
    with_mb_album = mb_base2.filter(
        LibraryFile.musicbrainz_albumid.isnot(None)
    ).scalar() or 0

    mb_base3 = db.query(func.count(LibraryFile.id))
    if library_type:
        mb_base3 = mb_base3.join(LibraryPath, LibraryFile.library_path_id == LibraryPath.id).filter(
            LibraryPath.library_type == library_type
        )
    with_mb_artist = mb_base3.filter(
        LibraryFile.musicbrainz_artistid.isnot(None)
    ).scalar() or 0

    return {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "total_size_gb": round(total_size / (1024**3), 2),
        "total_library_paths": total_paths,
        "formats": [{"format": f[0], "count": f[1]} for f in formats],
        "musicbrainz_coverage": {
            "tracks_with_mb_id": with_mb_track,
            "albums_with_mb_id": with_mb_album,
            "artists_with_mb_id": with_mb_artist,
            "track_coverage_percent": round((with_mb_track / total_files * 100), 1) if total_files > 0 else 0,
        }
    }


@router.get("/library/filesystem/browse")
@rate_limit("50/minute")
async def browse_filesystem(
    request: Request,
    path: str = "/",
    current_user: User = Depends(require_any_user),
):
    """
    Browse local filesystem directories

    Args:
        path: Directory path to browse (default: "/")

    Returns:
        Directory listing with subdirectories
    """
    # Normalize and validate path
    if not path:
        path = "/"

    # Expand home directory if present
    path = os.path.expanduser(path)

    # Get absolute path
    full_path = os.path.abspath(path)

    # Security: Ensure path exists
    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Path not found"
        )

    if not os.path.isdir(full_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is not a directory"
        )

    # List directories
    try:
        directories = []
        for item in sorted(os.listdir(full_path)):
            item_path = os.path.join(full_path, item)

            # Skip hidden files/directories (starting with .)
            if item.startswith('.'):
                continue

            # Only include directories
            if os.path.isdir(item_path):
                try:
                    # Check if directory is readable
                    is_readable = os.access(item_path, os.R_OK)
                    directories.append({
                        "name": item,
                        "path": item_path,
                        "is_readable": is_readable
                    })
                except (OSError, PermissionError):
                    # Skip directories we can't access
                    continue

        # Get parent directory
        parent_path = os.path.dirname(full_path) if full_path != "/" else None

        return {
            "current_path": full_path,
            "parent_path": parent_path,
            "directories": directories
        }
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )
    except Exception as e:
        logger.error(f"Error browsing filesystem: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/library/paths/{library_path_id}/artists")
@rate_limit("100/minute")
async def get_library_artists(
    library_path_id: str,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get unique artists from a library path

    Returns list of artists with file counts and album counts for import
    """
    validate_uuid(library_path_id, "Library Path ID")

    # Verify library path exists
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library path not found: {library_path_id}"
        )

    # Get unique artists (prioritize album_artist over artist)
    # Use COALESCE to prefer album_artist, fallback to artist
    from sqlalchemy import case, distinct

    artist_stats = db.query(
        func.coalesce(LibraryFile.album_artist, LibraryFile.artist).label('artist_name'),
        func.count(LibraryFile.id).label('file_count'),
        func.count(distinct(LibraryFile.album)).label('album_count'),
        func.max(LibraryFile.musicbrainz_artistid).label('musicbrainz_id')
    ).filter(
        LibraryFile.library_path_id == library_path_id,
        func.coalesce(LibraryFile.album_artist, LibraryFile.artist).isnot(None)
    ).group_by(
        func.coalesce(LibraryFile.album_artist, LibraryFile.artist)
    ).order_by(
        func.count(LibraryFile.id).desc()
    ).all()

    # Format results
    artists = []
    for stat in artist_stats:
        artists.append({
            "name": stat.artist_name,
            "musicbrainz_id": stat.musicbrainz_id,
            "file_count": stat.file_count,
            "album_count": stat.album_count,
            "has_mbid": bool(stat.musicbrainz_id)
        })

    return {
        "library_name": library_path.name,
        "library_id": str(library_path.id),
        "artists": artists,
        "total_count": len(artists)
    }


# ============================================================================
# Library Import Endpoints
# ============================================================================


@router.post("/library/paths/{path_id}/import")
@rate_limit("10/minute")
async def start_library_import(
    request: Request,
    path_id: str,
    import_request: ImportRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start complete library import workflow

    Orchestrates:
    1. File scanning (metadata extraction)
    2. Artist matching (MusicBrainz search and matching)
    3. Metadata sync (download artist/album/track data)
    4. Folder matching (assign directories to albums)
    5. Track matching (match files to tracks via MBID)
    6. Finalization (calculate statistics)

    Args:
        path_id: Library path UUID
        import_request: Import configuration

    Returns:
        Import job information
    """
    validate_uuid(path_id, "Library path ID")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found"
        )

    if not library_path.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Library path is disabled"
        )

    # Check for active imports
    active_import = db.query(LibraryImportJob).filter(
        LibraryImportJob.library_path_id == path_id,
        LibraryImportJob.status.in_(['pending', 'running'])
    ).first()

    if active_import:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An import is already in progress for this library: {str(active_import.id)}"
        )

    # Create import job
    import_job = LibraryImportJob(
        library_path_id=UUID(path_id),
        status='pending',
        auto_match_artists=import_request.auto_match_artists,
        auto_assign_folders=import_request.auto_assign_folders,
        auto_match_tracks=import_request.auto_match_tracks,
        confidence_threshold=import_request.confidence_threshold
    )

    db.add(import_job)
    db.commit()
    db.refresh(import_job)

    # Start orchestration task
    task = orchestrate_library_import.delay(
        library_path_id=str(path_id),
        import_job_id=str(import_job.id),
        config={
            'auto_match_artists': import_request.auto_match_artists,
            'auto_assign_folders': import_request.auto_assign_folders,
            'auto_match_tracks': import_request.auto_match_tracks,
            'confidence_threshold': import_request.confidence_threshold
        }
    )

    import_job.celery_task_id = task.id
    db.commit()

    logger.info(f"Started library import {import_job.id} for {library_path.path}")

    return {
        "import_job_id": str(import_job.id),
        "celery_task_id": task.id,
        "status": "pending",
        "message": "Library import started successfully"
    }


@router.post("/library/paths/{path_id}/book-import")
@rate_limit("10/minute")
async def start_book_import(
    request: Request,
    path_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start simplified book import workflow (no MusicBrainz dependency).

    Scans audiobook library files, creates Author records from metadata,
    then creates Book and Chapter records grouped by album tag.

    Args:
        path_id: Library path UUID (must be audiobook type)

    Returns:
        Import job information
    """
    validate_uuid(path_id, "Library path ID")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found"
        )

    if not library_path.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Library path is disabled"
        )

    library_type = getattr(library_path, 'library_type', 'music')
    if library_type != 'audiobook':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book import is only available for audiobook libraries"
        )

    # Check for active imports
    active_import = db.query(LibraryImportJob).filter(
        LibraryImportJob.library_path_id == path_id,
        LibraryImportJob.status.in_(['pending', 'running'])
    ).first()

    if active_import:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An import is already in progress for this library: {str(active_import.id)}"
        )

    # Create import job
    import_job = LibraryImportJob(
        library_path_id=UUID(path_id),
        status='pending',
        auto_match_artists=True,
        auto_assign_folders=False,
        auto_match_tracks=False,
        confidence_threshold=0,
    )

    db.add(import_job)
    db.commit()
    db.refresh(import_job)

    # Start book import task
    task = orchestrate_book_import.delay(
        library_path_id=str(path_id),
        import_job_id=str(import_job.id),
    )

    import_job.celery_task_id = task.id
    db.commit()

    logger.info(f"Started book import {import_job.id} for {library_path.path}")

    return {
        "import_job_id": str(import_job.id),
        "celery_task_id": task.id,
        "status": "pending",
        "message": "Book import started successfully"
    }


@router.get("/library/imports")
@rate_limit("100/minute")
async def list_import_jobs(
    request: Request,
    library_path_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List library import jobs

    Args:
        library_path_id: Optional filter by library path
        status_filter: Optional filter by status (pending, running, completed, failed, cancelled)
        limit: Max results

    Returns:
        List of import jobs with statistics
    """
    query = db.query(LibraryImportJob)

    if library_path_id:
        validate_uuid(library_path_id, "Library path ID")
        query = query.filter(LibraryImportJob.library_path_id == library_path_id)

    if status_filter:
        query = query.filter(LibraryImportJob.status == status_filter)

    imports = query.order_by(desc(LibraryImportJob.created_at)).limit(limit).all()

    return {
        "imports": [
            {
                "id": str(imp.id),
                "library_path_id": str(imp.library_path_id),
                "status": imp.status,
                "current_phase": imp.current_phase,
                "progress_percent": float(imp.progress_percent) if imp.progress_percent else 0.0,
                "current_action": imp.current_action,
                "artists_found": imp.artists_found,
                "artists_matched": imp.artists_matched,
                "artists_created": imp.artists_created,
                "artists_pending": imp.artists_pending,
                "albums_synced": imp.albums_synced,
                "tracks_matched": imp.tracks_matched,
                "tracks_unmatched": imp.tracks_unmatched,
                "files_scanned": imp.files_scanned,
                "error_message": imp.error_message,
                "started_at": imp.started_at.isoformat() if imp.started_at else None,
                "completed_at": imp.completed_at.isoformat() if imp.completed_at else None,
                "created_at": imp.created_at.isoformat()
            }
            for imp in imports
        ]
    }


@router.get("/library/imports/{import_job_id}")
@rate_limit("100/minute")
async def get_import_status(
    request: Request,
    import_job_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed import job status

    Args:
        import_job_id: Import job UUID

    Returns:
        Detailed import job information with phase status
    """
    validate_uuid(import_job_id, "Import job ID")

    import_job = db.query(LibraryImportJob).filter(
        LibraryImportJob.id == UUID(import_job_id)
    ).first()

    if not import_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found"
        )

    return {
        "id": str(import_job.id),
        "library_path_id": str(import_job.library_path_id),
        "status": import_job.status,
        "current_phase": import_job.current_phase,
        "progress_percent": float(import_job.progress_percent) if import_job.progress_percent else 0.0,
        "current_action": import_job.current_action,
        "phases": {
            "scanning": import_job.phase_scanning,
            "artist_matching": import_job.phase_artist_matching,
            "metadata_sync": import_job.phase_metadata_sync,
            "folder_matching": import_job.phase_folder_matching,
            "track_matching": import_job.phase_track_matching,
            "enrichment": import_job.phase_enrichment,
            "finalization": import_job.phase_finalization
        },
        "statistics": {
            "files_scanned": import_job.files_scanned,
            "artists_found": import_job.artists_found,
            "artists_matched": import_job.artists_matched,
            "artists_created": import_job.artists_created,
            "artists_pending": import_job.artists_pending,
            "albums_synced": import_job.albums_synced,
            "tracks_matched": import_job.tracks_matched,
            "tracks_unmatched": import_job.tracks_unmatched
        },
        "configuration": {
            "auto_match_artists": import_job.auto_match_artists,
            "auto_assign_folders": import_job.auto_assign_folders,
            "auto_match_tracks": import_job.auto_match_tracks,
            "confidence_threshold": import_job.confidence_threshold
        },
        "error_message": import_job.error_message,
        "warnings": import_job.warnings,
        "celery_task_id": import_job.celery_task_id,
        "started_at": import_job.started_at.isoformat() if import_job.started_at else None,
        "completed_at": import_job.completed_at.isoformat() if import_job.completed_at else None,
        "duration_seconds": (
            (import_job.completed_at - import_job.started_at).total_seconds()
            if import_job.completed_at and import_job.started_at
            else None
        )
    }


@router.get("/library/imports/{import_job_id}/unmatched-artists")
@rate_limit("100/minute")
async def get_unmatched_artists(
    request: Request,
    import_job_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get artists requiring manual review for an import job

    Returns artists that couldn't be auto-matched with their
    MusicBrainz suggestions for manual selection

    Args:
        import_job_id: Import job UUID

    Returns:
        List of unmatched artists with MusicBrainz suggestions
    """
    validate_uuid(import_job_id, "Import job ID")

    # Verify import job exists
    import_job = db.query(LibraryImportJob).filter(
        LibraryImportJob.id == UUID(import_job_id)
    ).first()

    if not import_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found"
        )

    # Get artists requiring manual review
    unmatched_artists = db.query(LibraryArtistMatch).filter(
        LibraryArtistMatch.import_job_id == UUID(import_job_id),
        LibraryArtistMatch.status.in_(['pending', 'manual_review', 'failed'])
    ).all()

    return {
        "import_job_id": str(import_job_id),
        "unmatched_count": len(unmatched_artists),
        "artists": [
            {
                "id": str(match.id),
                "library_artist_name": match.library_artist_name,
                "file_count": match.file_count,
                "sample_albums": match.sample_albums,
                "confidence_score": float(match.confidence_score) if match.confidence_score else 0.0,
                "status": match.status,
                "musicbrainz_suggestions": match.musicbrainz_suggestions,
                "rejection_reason": match.rejection_reason
            }
            for match in unmatched_artists
        ]
    }


@router.post("/library/imports/{import_job_id}/match-artist")
@rate_limit("30/minute")
async def manually_match_artist(
    request: Request,
    import_job_id: str,
    match_request: ArtistMatchRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Manually match an artist from import job

    Allows user to select a MusicBrainz match for artists
    that couldn't be auto-matched

    Args:
        import_job_id: Import job UUID
        match_request: Artist match selection

    Returns:
        Updated artist match status
    """
    from app.services.artist_import_service import ArtistImportService

    validate_uuid(import_job_id, "Import job ID")
    validate_uuid(match_request.artist_match_id, "Artist match ID")

    # Get artist match record
    artist_match = db.query(LibraryArtistMatch).filter(
        LibraryArtistMatch.id == UUID(match_request.artist_match_id),
        LibraryArtistMatch.import_job_id == UUID(import_job_id)
    ).first()

    if not artist_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist match record not found"
        )

    if artist_match.status == 'matched':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Artist is already matched"
        )

    # Create or find artist
    artist_service = ArtistImportService(db)

    if match_request.create_new:
        # Get MusicBrainz name from suggestions
        mb_match = next(
            (s for s in artist_match.musicbrainz_suggestions if s['musicbrainz_id'] == match_request.musicbrainz_id),
            None
        )

        if not mb_match:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected MusicBrainz ID not found in suggestions"
            )

        # Check if artist already exists
        existing_artist = artist_service.check_existing_artist(
            mb_match['name'],
            match_request.musicbrainz_id
        )

        if existing_artist:
            artist = existing_artist
        else:
            # Create new artist
            artist = artist_service.create_artist_from_musicbrainz(
                match_request.musicbrainz_id,
                mb_match['name']
            )

            if not artist:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create artist"
                )
    else:
        # Find existing artist by MBID
        from app.models.artist import Artist
        artist = db.query(Artist).filter(
            Artist.musicbrainz_id == match_request.musicbrainz_id
        ).first()

        if not artist:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artist not found with MusicBrainz ID: {match_request.musicbrainz_id}"
            )

    # Update artist match record
    artist_match.matched_artist_id = artist.id
    artist_match.musicbrainz_id = artist.musicbrainz_id
    artist_match.status = 'matched'
    artist_match.confidence_score = 100.0  # Manual match = 100% confidence
    db.commit()

    logger.info(
        f"Manually matched artist '{artist_match.library_artist_name}' to "
        f"'{artist.name}' (MBID: {artist.musicbrainz_id})"
    )

    return {
        "message": "Artist matched successfully",
        "artist_match_id": str(artist_match.id),
        "matched_artist_id": str(artist.id),
        "artist_name": artist.name,
        "musicbrainz_id": artist.musicbrainz_id
    }


@router.post("/library/imports/{import_job_id}/cancel")
@rate_limit("30/minute")
async def cancel_import(
    request: Request,
    import_job_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Cancel a running import job

    Args:
        import_job_id: Import job UUID

    Returns:
        Cancellation status
    """
    from app.tasks.celery_app import celery_app

    validate_uuid(import_job_id, "Import job ID")

    import_job = db.query(LibraryImportJob).filter(
        LibraryImportJob.id == UUID(import_job_id)
    ).first()

    if not import_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found"
        )

    if import_job.status not in ['pending', 'running']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel import with status: {import_job.status}"
        )

    # Set cancel flag (task will check this periodically)
    import_job.cancel_requested = True
    db.commit()

    # Attempt to revoke Celery task (may not work if already started)
    if import_job.celery_task_id:
        celery_app.control.revoke(import_job.celery_task_id, terminate=True)
        logger.info(f"Revoked Celery task: {import_job.celery_task_id}")

    logger.info(f"Cancel requested for import job: {import_job_id}")

    return {
        "message": "Import cancellation requested",
        "import_job_id": str(import_job.id),
        "status": "cancelling"
    }
