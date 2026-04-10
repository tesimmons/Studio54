"""
File Management API Endpoints
MBID-based file organization and validation for Studio54
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID
import logging
import io
import csv
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_db
from app.models.library import LibraryPath
from app.security import rate_limit, validate_uuid
from app.auth import require_director, require_dj_or_above, require_any_user
from app.models.user import User
from app.tasks.organization_tasks import (
    organize_library_files_task,
    organize_artist_files_task,
    validate_library_structure_task,
    rollback_organization_job_task
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ========================================
# Request/Response Schemas
# ========================================

class FileOrganizationOptions(BaseModel):
    """Options for file organization"""
    dry_run: bool = Field(False, description="Preview changes without executing")
    create_metadata_files: bool = Field(True, description="Create .mbid.json files")
    backup_before_move: bool = Field(True, description="Create backup before moving files")
    only_with_mbid: bool = Field(True, description="Only organize files with MBIDs")
    only_unorganized: bool = Field(True, description="Only organize unorganized files")
    artist_ids: Optional[List[str]] = Field(None, description="Filter to specific artists")


class OrganizationJobResponse(BaseModel):
    """Response for organization job creation"""
    job_id: str
    status: str
    message: str
    estimated_files: Optional[int] = None


class OrganizationJobStatus(BaseModel):
    """Organization job status"""
    id: str
    job_type: str
    status: str
    progress_percent: float
    current_action: Optional[str] = None
    files_total: int
    files_processed: int
    files_renamed: int
    files_moved: int
    files_failed: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class ValidationResponse(BaseModel):
    """Validation result response"""
    is_valid: bool
    total_files: int
    valid_files: int
    issues_summary: Dict[str, int]
    misnamed_files: List[Dict[str, Any]]
    misplaced_files: List[Dict[str, Any]]
    incorrect_directories: List[Dict[str, Any]]


class AuditLogEntry(BaseModel):
    """Audit log entry"""
    id: str
    operation_type: Optional[str] = None
    source_path: Optional[str] = None
    destination_path: Optional[str] = None
    artist_id: Optional[str] = None
    album_id: Optional[str] = None
    recording_mbid: Optional[str] = None
    success: Optional[bool] = None
    error_message: Optional[str] = None
    rollback_possible: Optional[bool] = None
    performed_at: Optional[str] = None


class AuditLogResponse(BaseModel):
    """Audit log query response"""
    entries: List[AuditLogEntry]
    total: int
    limit: int
    offset: int


class RollbackRequest(BaseModel):
    """Request to rollback organization job"""
    confirm: bool = Field(..., description="Must be true to confirm rollback")


# ========================================
# Organization Endpoints
# ========================================

@router.post("/library-paths/{library_path_id}/organize", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def organize_library_files(
    library_path_id: UUID,
    options: FileOrganizationOptions,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Organize all files in a library path based on MBID metadata

    This endpoint creates a background job that:
    - Analyzes all files with MBIDs
    - Generates target paths using naming templates
    - Moves/renames files to correct locations
    - Creates album metadata files
    - Updates database records

    **Returns:**
    - job_id: Background job identifier
    - status: Initial job status
    - estimated_files: Estimated number of files to process
    """
    validate_uuid(str(library_path_id), "library_path_id")

    # Verify library path exists
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library path {library_path_id} not found"
        )

    # Check if there's already a running organization job for this library
    from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus

    running_job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.library_path_id == library_path_id,
        FileOrganizationJob.status.in_(['pending', 'running'])
    ).first()

    if running_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization job {running_job.id} is already running for this library path"
        )

    # Estimate file count
    from sqlalchemy import func, text
    file_count_query = text("""
        SELECT COUNT(DISTINCT lf.id)
        FROM library_files lf
        WHERE lf.library_path_id = :library_path_id
        AND (:only_with_mbid = false OR lf.musicbrainz_trackid IS NOT NULL)
        AND (:only_unorganized = false OR (lf.is_organized = false OR lf.is_organized IS NULL))
    """)

    result = db.execute(file_count_query, {
        'library_path_id': str(library_path_id),
        'only_with_mbid': options.only_with_mbid,
        'only_unorganized': options.only_unorganized
    })
    estimated_files = result.scalar()

    # Create organization job
    job = FileOrganizationJob(
        job_type='organize_library',
        status='pending',
        library_path_id=library_path_id,
        files_total=estimated_files or 0,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created organization job {job.id} for library path {library_path_id}")

    # Queue background task and save the celery task ID
    result = organize_library_files_task.delay(
        job_id=str(job.id),
        library_path_id=str(library_path_id),
        options=options.dict()
    )

    # Update job with celery task ID for tracking
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message='File organization job queued successfully',
        estimated_files=estimated_files
    )


@router.post("/artists/{artist_id}/organize", response_model=OrganizationJobResponse)
@rate_limit("30/minute")
def organize_artist_files(
    artist_id: UUID,
    options: FileOrganizationOptions,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Organize all files for a specific artist

    **Parameters:**
    - artist_id: Artist UUID
    - options: Organization options

    **Returns:**
    - job_id: Background job identifier
    - status: Initial job status
    """
    validate_uuid(str(artist_id), "artist_id")

    # Verify artist exists
    from app.models.artist import Artist
    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artist {artist_id} not found"
        )

    # Get artist's MusicBrainz ID for matching
    from app.models.artist import Artist
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    # Estimate file count for artist using library_files metadata
    from sqlalchemy import text
    file_count_query = text("""
        SELECT COUNT(DISTINCT lf.id)
        FROM library_files lf
        WHERE lf.musicbrainz_artistid = :artist_mbid
        AND (:only_with_mbid = false OR lf.musicbrainz_trackid IS NOT NULL)
        AND (:only_unorganized = false OR (lf.is_organized = false OR lf.is_organized IS NULL))
    """)

    result = db.execute(file_count_query, {
        'artist_mbid': artist.musicbrainz_id,
        'only_with_mbid': options.only_with_mbid,
        'only_unorganized': options.only_unorganized
    })
    estimated_files = result.scalar()

    # Create organization job
    from app.models.file_organization_job import FileOrganizationJob

    job = FileOrganizationJob(
        job_type='organize_artist',
        status='pending',
        artist_id=artist_id,
        files_total=estimated_files or 0,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created artist organization job {job.id} for artist {artist_id}")

    # Queue background task and save the celery task ID
    result = organize_artist_files_task.delay(
        job_id=str(job.id),
        artist_id=str(artist_id),
        options=options.dict()
    )

    # Update job with celery task ID for tracking
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'File organization job queued for artist {artist.name}',
        estimated_files=estimated_files
    )


@router.post("/albums/{album_id}/organize", response_model=OrganizationJobResponse)
@rate_limit("30/minute")
def organize_album_files(
    album_id: UUID,
    options: FileOrganizationOptions,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Organize all files for a specific album

    **Parameters:**
    - album_id: Album UUID
    - options: Organization options

    **Returns:**
    - job_id: Background job identifier
    - status: Initial job status
    """
    validate_uuid(str(album_id), "album_id")

    # Verify album exists
    from app.models.album import Album
    album = db.query(Album).filter(Album.id == album_id).first()

    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Album {album_id} not found"
        )

    # Get album's MusicBrainz ID for matching
    if not album.musicbrainz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Album does not have a MusicBrainz ID"
        )

    # Estimate file count for album using library_files metadata
    from sqlalchemy import text
    file_count_query = text("""
        SELECT COUNT(DISTINCT lf.id)
        FROM library_files lf
        WHERE lf.musicbrainz_releasegroupid = :album_mbid
        AND (:only_with_mbid = false OR lf.musicbrainz_trackid IS NOT NULL)
        AND (:only_unorganized = false OR (lf.is_organized = false OR lf.is_organized IS NULL))
    """)

    result = db.execute(file_count_query, {
        'album_mbid': album.musicbrainz_id,
        'only_with_mbid': options.only_with_mbid,
        'only_unorganized': options.only_unorganized
    })
    estimated_files = result.scalar()

    # Create organization job
    from app.models.file_organization_job import FileOrganizationJob
    from app.tasks.organization_tasks import organize_album_files_task

    job = FileOrganizationJob(
        job_type='organize_album',
        status='pending',
        album_id=album_id,
        artist_id=album.artist_id,
        files_total=estimated_files or 0,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created album organization job {job.id} for album {album_id}")

    # Queue background task and save the celery task ID
    result = organize_album_files_task.delay(
        job_id=str(job.id),
        album_id=str(album_id),
        options=options.dict()
    )

    # Update job with celery task ID for tracking
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'File organization job queued for album {album.title}',
        estimated_files=estimated_files
    )


# ========================================
# Associate and Organize Endpoints
# ========================================

@router.post("/library-paths/{library_path_id}/associate-and-organize", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def associate_and_organize_library(
    library_path_id: UUID,
    options: FileOrganizationOptions,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Associate and organize all files in a library path.

    Walks artist directories, reads file metadata, matches to DB tracks,
    moves/renames to naming convention, and updates Track.file_path + has_file.

    **Returns:**
    - job_id: Background job identifier
    - status: Initial job status
    """
    validate_uuid(str(library_path_id), "library_path_id")

    # Verify library path exists
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library path {library_path_id} not found"
        )

    # Check if there's already a running job for this library
    from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

    running_job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.library_path_id == library_path_id,
        FileOrganizationJob.status.in_(['pending', 'running']),
        FileOrganizationJob.job_type == JobType.ASSOCIATE_AND_ORGANIZE
    ).first()

    if running_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Associate & organize job {running_job.id} is already running for this library path"
        )

    # Create job
    job = FileOrganizationJob(
        job_type=JobType.ASSOCIATE_AND_ORGANIZE,
        status=OrgJobStatus.PENDING,
        library_path_id=library_path_id,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created associate & organize job {job.id} for library path {library_path_id}")

    # Queue background task
    from app.tasks.organization_tasks import associate_and_organize_library_task
    result = associate_and_organize_library_task.delay(
        job_id=str(job.id),
        library_path_id=str(library_path_id),
        options=options.dict()
    )

    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message='Associate & organize job queued successfully'
    )


@router.post("/artists/{artist_id}/associate-and-organize", response_model=OrganizationJobResponse)
@rate_limit("30/minute")
def associate_and_organize_artist(
    artist_id: UUID,
    options: FileOrganizationOptions,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Associate and organize files for a specific artist.

    Walks artist's directory, reads file metadata, matches to DB tracks,
    moves/renames to naming convention, and updates Track.file_path + has_file.

    **Parameters:**
    - artist_id: Artist UUID
    - options: Organization options

    **Returns:**
    - job_id: Background job identifier
    - status: Initial job status
    """
    validate_uuid(str(artist_id), "artist_id")

    # Verify artist exists
    from app.models.artist import Artist
    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artist {artist_id} not found"
        )

    # Create job
    from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

    job = FileOrganizationJob(
        job_type=JobType.ASSOCIATE_AND_ORGANIZE,
        status=OrgJobStatus.PENDING,
        artist_id=artist_id,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created associate & organize job {job.id} for artist {artist_id}")

    # Queue background task
    from app.tasks.organization_tasks import associate_and_organize_artist_task
    result = associate_and_organize_artist_task.delay(
        job_id=str(job.id),
        artist_id=str(artist_id),
        options=options.dict()
    )

    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Associate & organize job queued for artist {artist.name}'
    )


# ========================================
# Validation Endpoints
# ========================================

@router.post("/library-paths/{library_path_id}/validate", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def validate_library_structure(
    library_path_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Validate library structure and identify issues

    Checks for:
    - Misnamed files (incorrect naming format)
    - Misplaced files (wrong directory)
    - Incorrect directory names

    **Returns:**
    - job_id: Background validation job identifier
    """
    validate_uuid(str(library_path_id), "library_path_id")

    # Verify library path exists
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library path {library_path_id} not found"
        )

    # Create validation job
    from app.models.file_organization_job import FileOrganizationJob

    job = FileOrganizationJob(
        job_type='validate_structure',
        status='pending',
        library_path_id=library_path_id,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created validation job {job.id} for library path {library_path_id}")

    # Queue background task and save the celery task ID
    result = validate_library_structure_task.delay(
        job_id=str(job.id),
        library_path_id=str(library_path_id)
    )

    # Update job with celery task ID for tracking
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message='Structure validation job queued successfully'
    )


# ========================================
# Job Status Endpoints
# ========================================

@router.get("/jobs/{job_id}", response_model=OrganizationJobStatus)
@rate_limit("60/minute")
def get_organization_job_status(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get organization job status and statistics

    **Returns:**
    - Complete job details including progress, statistics, and errors
    """
    validate_uuid(str(job_id), "job_id")

    from app.models.file_organization_job import FileOrganizationJob

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization job {job_id} not found"
        )

    return OrganizationJobStatus(
        id=str(job.id),
        job_type=job.job_type,
        status=job.status,
        progress_percent=float(job.progress_percent or 0.0),
        current_action=job.current_action,
        files_total=job.files_total or 0,
        files_processed=job.files_processed or 0,
        files_renamed=job.files_renamed or 0,
        files_moved=job.files_moved or 0,
        files_failed=job.files_failed or 0,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        error_message=job.error_message
    )


@router.get("/jobs/{job_id}/log")
@rate_limit("30/minute")
def download_job_log(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Download the log file for an organization job

    **Requirements:**
    - Job must exist and have a log file

    **Returns:**
    - Log file as downloadable text file
    """
    validate_uuid(str(job_id), "job_id")

    from app.models.file_organization_job import FileOrganizationJob

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization job {job_id} not found"
        )

    if not job.log_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No log file available for job {job_id}"
        )

    log_path = Path(job.log_file_path)

    if not log_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log file not found at {job.log_file_path}"
        )

    logger.info(f"Serving log file for job {job_id}: {job.log_file_path}")

    return FileResponse(
        path=str(log_path),
        media_type="text/plain",
        filename=f"file_organization_job_{job_id}.log"
    )


@router.get("/jobs", response_model=List[OrganizationJobStatus])
@rate_limit("60/minute")
def list_organization_jobs(
    request: Request,
    library_path_id: Optional[UUID] = Query(None, description="Filter by library path"),
    artist_id: Optional[UUID] = Query(None, description="Filter by artist"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List organization jobs with optional filters

    **Query Parameters:**
    - library_path_id: Filter by library path
    - artist_id: Filter by artist
    - status_filter: Filter by status (pending, running, completed, failed)
    - limit: Max results (1-500)
    - offset: Pagination offset
    """
    from app.models.file_organization_job import FileOrganizationJob

    query = db.query(FileOrganizationJob)

    if library_path_id:
        validate_uuid(library_path_id, "library_path_id")
        query = query.filter(FileOrganizationJob.library_path_id == library_path_id)

    if artist_id:
        validate_uuid(str(artist_id), "artist_id")
        query = query.filter(FileOrganizationJob.artist_id == artist_id)

    if status_filter:
        query = query.filter(FileOrganizationJob.status == status_filter)

    # Order by creation time descending
    query = query.order_by(FileOrganizationJob.created_at.desc())

    # Apply pagination
    jobs = query.limit(limit).offset(offset).all()

    return [
        OrganizationJobStatus(
            id=str(job.id),
            job_type=job.job_type,
            status=job.status,
            progress_percent=float(job.progress_percent or 0.0),
            current_action=job.current_action,
            files_total=job.files_total or 0,
            files_processed=job.files_processed or 0,
            files_renamed=job.files_renamed or 0,
            files_moved=job.files_moved or 0,
            files_failed=job.files_failed or 0,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            error_message=job.error_message
        )
        for job in jobs
    ]


# ========================================
# Rollback Endpoints
# ========================================

@router.post("/jobs/{job_id}/rollback", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def rollback_organization_job(
    job_id: UUID,
    rollback_request: RollbackRequest,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Rollback a completed organization job

    Reverses all file operations performed by the job using audit trail.

    **Requirements:**
    - Job must be completed
    - Job must not already be rolled back
    - confirm field must be true

    **Returns:**
    - Rollback job status
    """
    validate_uuid(str(job_id), "job_id")

    if not rollback_request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to rollback job"
        )

    from app.models.file_organization_job import FileOrganizationJob

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization job {job_id} not found"
        )

    if job.status != 'completed':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only rollback completed jobs. Job status: {job.status}"
        )

    if job.status == 'rolled_back':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has already been rolled back"
        )

    logger.info(f"Initiating rollback for organization job {job_id}")

    # Queue rollback task and save the celery task ID
    result = rollback_organization_job_task.delay(job_id=str(job_id))

    # Update job with new celery task ID for tracking the rollback
    job.celery_task_id = result.id
    job.status = 'rollback_queued'
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job_id),
        status='rollback_queued',
        message='Rollback job queued successfully'
    )


@router.delete("/jobs/{job_id}")
@rate_limit("10/minute")
def cancel_organization_job(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a pending or running organization job

    **Requirements:**
    - Job must be in pending or running status

    **Returns:**
    - Success message
    """
    validate_uuid(str(job_id), "job_id")

    from app.models.file_organization_job import FileOrganizationJob, JobStatus
    from celery.result import AsyncResult

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}"
        )

    # Check if job can be cancelled
    if job.status not in [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job with status: {job.status}. Only pending, running, or paused jobs can be cancelled."
        )

    # Revoke Celery task if it exists
    if job.celery_task_id:
        AsyncResult(job.celery_task_id).revoke(terminate=True)
        logger.info(f"Revoked Celery task {job.celery_task_id} for job {job_id}")

    # Update job status
    job.status = JobStatus.CANCELLED
    job.error_message = "Cancelled by user"
    job.completed_at = datetime.now(timezone.utc)

    # Cleanup log file if it exists
    if job.log_file_path:
        log_path = Path(job.log_file_path)
        if log_path.exists():
            try:
                log_path.unlink()
                logger.info(f"Deleted log file for cancelled job {job_id}: {job.log_file_path}")
            except Exception as e:
                logger.error(f"Failed to delete log file {job.log_file_path}: {e}")

    db.commit()

    logger.info(f"Cancelled organization job {job_id}")

    return {"message": f"Job {job_id} cancelled successfully", "job_id": str(job_id)}


@router.post("/jobs/{job_id}/resume", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def resume_organization_job(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Resume a paused organization job (typically FETCH_METADATA jobs)

    **Requirements:**
    - Job must be in PAUSED status

    **Returns:**
    - Success message with job details
    """
    validate_uuid(str(job_id), "job_id")

    from app.models.file_organization_job import FileOrganizationJob, JobStatus, JobType
    from app.tasks.organization_tasks import fetch_metadata_task

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}"
        )

    # Check if job is paused
    if job.status != JobStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume job with status: {job.status}. Only paused jobs can be resumed."
        )

    # Dispatch the appropriate task based on job type
    if job.job_type == JobType.FETCH_METADATA:
        result = fetch_metadata_task.delay(str(job.id))
        job.celery_task_id = result.id
        job.status = JobStatus.PENDING
        job.current_action = "Queued to fetch metadata from MusicBrainz"
        db.commit()

        logger.info(f"Resumed FETCH_METADATA job {job_id}, Celery task: {result.id}")

        return OrganizationJobResponse(
            job_id=str(job_id),
            status='resumed',
            message=f'Fetch metadata job resumed, processing {job.files_total} files'
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Resume not supported for job type: {job.job_type}"
        )


@router.post("/jobs/{job_id}/restart", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def restart_organization_job(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Restart a failed, cancelled, or completed organization job

    **Requirements:**
    - Job must be in FAILED, CANCELLED, or COMPLETED status

    **Behavior:**
    - Resets job progress counters
    - Creates new Celery task
    - Job continues from where it left off (files already processed are skipped)

    **Returns:**
    - Success message with job details
    """
    validate_uuid(str(job_id), "job_id")

    from app.models.file_organization_job import FileOrganizationJob, JobStatus, JobType
    from app.tasks.organization_tasks import (
        organize_library_files_task,
        organize_artist_files_task,
        organize_album_files_task,
        validate_library_structure_task,
        fetch_metadata_task,
        validate_mbid_task,
        validate_mbid_metadata_task,
        link_files_task,
        reindex_albums_task,
        verify_audio_task
    )
    from datetime import datetime, timezone

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}"
        )

    # Check if job can be restarted
    restartable_statuses = [JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.COMPLETED]
    if job.status not in restartable_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot restart job with status: {job.status}. Only failed, cancelled, or completed jobs can be restarted."
        )

    # Reset job state for restart
    job.status = JobStatus.PENDING
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.progress_percent = 0.0
    job.files_processed = 0
    job.files_renamed = 0
    job.files_moved = 0
    job.files_failed = 0
    job.current_action = "Queued for restart"

    # Get options from job (preserve original options)
    options = {
        'dry_run': job.dry_run if hasattr(job, 'dry_run') else False,
        'only_with_mbid': True,
        'only_unorganized': False,  # Re-process all files on restart
        'create_metadata_files': True
    }

    # Dispatch the appropriate task based on job type
    task_dispatched = False
    celery_result = None

    if job.job_type == JobType.ORGANIZE_LIBRARY:
        celery_result = organize_library_files_task.delay(
            str(job.id),
            str(job.library_path_id),
            options
        )
        task_dispatched = True
        message = f'Organize library job restarted for library path {job.library_path_id}'

    elif job.job_type == JobType.ORGANIZE_ARTIST:
        celery_result = organize_artist_files_task.delay(
            str(job.id),
            str(job.artist_id),
            options
        )
        task_dispatched = True
        message = f'Organize artist job restarted'

    elif job.job_type == JobType.ORGANIZE_ALBUM:
        celery_result = organize_album_files_task.delay(
            str(job.id),
            str(job.album_id),
            options
        )
        task_dispatched = True
        message = f'Organize album job restarted'

    elif job.job_type == JobType.VALIDATE_STRUCTURE:
        celery_result = validate_library_structure_task.delay(
            str(job.id),
            str(job.library_path_id)
        )
        task_dispatched = True
        message = f'Validate structure job restarted'

    elif job.job_type == JobType.FETCH_METADATA:
        celery_result = fetch_metadata_task.delay(str(job.id))
        task_dispatched = True
        message = f'Fetch metadata job restarted'

    elif job.job_type == JobType.VALIDATE_MBID:
        celery_result = validate_mbid_task.delay(
            str(job.id),
            str(job.library_path_id)
        )
        task_dispatched = True
        message = f'Validate MBID job restarted'

    elif job.job_type == JobType.LINK_FILES:
        celery_result = link_files_task.delay(
            str(job.id)
        )
        task_dispatched = True
        message = f'Link files job restarted'

    elif job.job_type == JobType.REINDEX_ALBUMS:
        celery_result = reindex_albums_task.delay(
            str(job.id)
        )
        task_dispatched = True
        message = f'Reindex albums job restarted'

    elif job.job_type == JobType.VERIFY_AUDIO:
        celery_result = verify_audio_task.delay(
            str(job.id),
            7  # Default to 7 days
        )
        task_dispatched = True
        message = f'Verify audio job restarted'

    elif job.job_type == JobType.VALIDATE_MBID_METADATA:
        celery_result = validate_mbid_metadata_task.delay(
            str(job.id)
        )
        task_dispatched = True
        message = f'Validate MBID metadata job restarted'

    elif job.job_type == JobType.VALIDATE_FILE_LINKS:
        from app.tasks.organization_tasks import validate_file_links_task
        celery_result = validate_file_links_task.delay(
            str(job.id),
            str(job.library_path_id) if job.library_path_id else None
        )
        task_dispatched = True
        message = f'Validate file links job restarted'

    if not task_dispatched:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Restart not supported for job type: {job.job_type}"
        )

    # Update job with new Celery task ID
    job.celery_task_id = celery_result.id
    db.commit()

    logger.info(f"Restarted {job.job_type} job {job_id}, Celery task: {celery_result.id}")

    return OrganizationJobResponse(
        job_id=str(job_id),
        status='restarted',
        message=message
    )


# ========================================
# Audit Log Endpoints
# ========================================

@router.get("/audit/operations", response_model=AuditLogResponse)
@rate_limit("60/minute")
def get_audit_log(
    request: Request,
    operation_type: Optional[str] = Query(None, description="Filter by operation type"),
    artist_id: Optional[UUID] = Query(None, description="Filter by artist"),
    album_id: Optional[UUID] = Query(None, description="Filter by album"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Query audit log with filters

    **Query Parameters:**
    - operation_type: Filter by operation (rename, move, delete)
    - artist_id: Filter by artist UUID
    - album_id: Filter by album UUID
    - start_date: Filter operations after this date
    - end_date: Filter operations before this date
    - limit: Max results (1-1000)
    - offset: Pagination offset

    **Returns:**
    - List of audit log entries with pagination info
    """
    from sqlalchemy import text

    # Build query with filters
    where_clauses = []
    params = {}

    if operation_type:
        where_clauses.append("operation_type = :operation_type")
        params['operation_type'] = operation_type

    if artist_id:
        validate_uuid(str(artist_id), "artist_id")
        where_clauses.append("artist_id = :artist_id")
        params['artist_id'] = str(artist_id)

    if album_id:
        validate_uuid(str(album_id), "album_id")
        where_clauses.append("album_id = :album_id")
        params['album_id'] = str(album_id)

    if start_date:
        where_clauses.append("performed_at >= :start_date")
        params['start_date'] = start_date

    if end_date:
        where_clauses.append("performed_at <= :end_date")
        params['end_date'] = end_date

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Count total
    count_query = text(f"""
        SELECT COUNT(*)
        FROM file_operation_audit
        WHERE {where_sql}
    """)
    total = db.execute(count_query, params).scalar()

    # Get entries
    entries_query = text(f"""
        SELECT
            id, operation_type, source_path, destination_path,
            artist_id, album_id, track_id, recording_mbid, release_mbid,
            success, error_message, rollback_possible, performed_at
        FROM file_operation_audit
        WHERE {where_sql}
        ORDER BY performed_at DESC
        LIMIT :limit OFFSET :offset
    """)

    params['limit'] = limit
    params['offset'] = offset

    result = db.execute(entries_query, params)
    rows = result.fetchall()

    entries = [
        AuditLogEntry(
            id=str(row[0]),
            operation_type=row[1],
            source_path=row[2],
            destination_path=row[3],
            artist_id=str(row[4]) if row[4] else None,
            album_id=str(row[5]) if row[5] else None,
            recording_mbid=str(row[6]) if row[6] else None,
            success=row[7],
            error_message=row[8],
            rollback_possible=row[9],
            performed_at=row[10].isoformat() if row[10] else None
        )
        for row in rows
    ]

    return AuditLogResponse(
        entries=entries,
        total=total or 0,
        limit=limit,
        offset=offset
    )


# ========================================
# Job Log Endpoints
# ========================================

@router.get("/jobs/{job_id}/log")
async def get_job_log(
    job_id: UUID,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get the log file for a file organization job.
    Returns the log file as a downloadable text file.
    """
    from app.models.file_organization_job import FileOrganizationJob

    job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    if not job.log_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No log file available for job {job_id}"
        )

    log_path = Path(job.log_file_path)
    if not log_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log file not found at {job.log_file_path}"
        )

    return FileResponse(
        path=str(log_path),
        filename=f"organization_job_{job_id}.log",
        media_type="text/plain"
    )


@router.get("/jobs/{job_id}/unmatched-csv")
@rate_limit("30/minute")
def download_unmatched_csv(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Download the CSV report of unmatched files for a FETCH_METADATA job.

    Returns a CSV with columns: file_path, file_name, artist, title, album, reason
    """
    validate_uuid(str(job_id), "job_id")

    from app.models.file_organization_job import FileOrganizationJob

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    if not job.summary_report_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No unmatched files report available for job {job_id}"
        )

    csv_path = Path(job.summary_report_path)
    if not csv_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report file not found at {job.summary_report_path}"
        )

    return FileResponse(
        path=str(csv_path),
        media_type="text/csv",
        filename=f"unmatched_files_{job_id}.csv"
    )


@router.get("/jobs/{job_id}/log/content")
async def get_job_log_content(
    job_id: UUID,
    lines: int = Query(default=100, ge=1, le=10000, description="Number of lines to return"),
    offset: int = Query(default=0, ge=0, description="Line offset from start"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get the log file content for a file organization job.
    Returns the log content as JSON for display in the UI.
    """
    from app.models.file_organization_job import FileOrganizationJob

    job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    if not job.log_file_path:
        return {
            "job_id": str(job_id),
            "log_available": False,
            "content": "",
            "total_lines": 0
        }

    log_path = Path(job.log_file_path)
    if not log_path.exists():
        return {
            "job_id": str(job_id),
            "log_available": False,
            "content": "",
            "total_lines": 0
        }

    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        selected_lines = all_lines[offset:offset + lines]
        content = ''.join(selected_lines)

        return {
            "job_id": str(job_id),
            "log_available": True,
            "content": content,
            "total_lines": total_lines,
            "lines_returned": len(selected_lines),
            "offset": offset,
            "log_file_path": job.log_file_path
        }
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading log file: {str(e)}"
        )


# ========================================
# Additional Job Endpoints (MBID Jobs)
# ========================================

@router.post("/library-paths/{library_path_id}/fetch-metadata", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_fetch_metadata_job(
    library_path_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to fetch MBIDs from MusicBrainz for files without metadata
    
    This job:
    - Finds files without MBIDs in the database
    - Searches MusicBrainz for matches based on artist/title
    - Writes MBIDs to the file Comment tags
    - Updates the database with found MBIDs
    """
    validate_uuid(str(library_path_id), "library_path_id")
    
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")
    
    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import fetch_metadata_task
    
    # Count files without MBID
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(*) FROM library_files
        WHERE library_path_id = :library_path_id
        AND (musicbrainz_trackid IS NULL OR musicbrainz_trackid = '')
    """)
    result = db.execute(count_query, {'library_path_id': str(library_path_id)})
    file_count = result.scalar() or 0
    
    job = FileOrganizationJob(
        job_type=JobType.FETCH_METADATA,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    result = fetch_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()
    
    logger.info(f"Created fetch_metadata job {job.id} for library path {library_path_id}")
    
    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Fetch metadata job queued. {file_count} files to process.',
        estimated_files=file_count
    )


@router.post("/library-paths/{library_path_id}/validate-mbid", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_validate_mbid_job(
    library_path_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to validate MBIDs in file comments
    
    This job:
    - Reads the Comment tag from each audio file
    - Checks if Recording MBID is present
    - Updates the database mbid_in_file flag
    - Tracks verification time
    """
    validate_uuid(str(library_path_id), "library_path_id")
    
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")
    
    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import validate_mbid_task
    
    # Count files with MBID in database
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(*) FROM library_files
        WHERE library_path_id = :library_path_id
        AND musicbrainz_trackid IS NOT NULL
    """)
    result = db.execute(count_query, {'library_path_id': str(library_path_id)})
    file_count = result.scalar() or 0
    
    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    result = validate_mbid_task.delay(str(job.id), str(library_path_id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created validate_mbid job {job.id} for library path {library_path_id}")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'MBID validation job queued. {file_count} files to verify.',
        estimated_files=file_count
    )


@router.post("/library-paths/{library_path_id}/validate-mbid-metadata", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_validate_mbid_metadata_job(
    library_path_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to validate file metadata against MusicBrainz

    This job validates that file metadata (title, artist, album) matches
    the authoritative data from MusicBrainz for files with MBIDs:
    - Reads MBID from file comments
    - Looks up recording on MusicBrainz
    - Compares file metadata with MusicBrainz metadata
    - Calculates confidence score
    - Reports files with low confidence for review
    """
    validate_uuid(str(library_path_id), "library_path_id")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")

    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import validate_mbid_metadata_task

    # Count files with MBID in file
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(*) FROM library_files
        WHERE library_path_id = :library_path_id
        AND mbid_in_file = TRUE
    """)
    result = db.execute(count_query, {'library_path_id': str(library_path_id)})
    file_count = result.scalar() or 0

    if file_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No files with MBID found. Run 'Validate MBID' first to identify files with MBIDs."
        )

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID_METADATA,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = validate_mbid_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created validate_mbid_metadata job {job.id} for library path {library_path_id}")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'MBID metadata validation job queued. {file_count} files to validate against MusicBrainz.',
        estimated_files=file_count
    )


@router.post("/artists/{artist_id}/validate-mbid-metadata", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_artist_validate_mbid_metadata_job(
    artist_id: UUID,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Validate MBID metadata for a specific artist's files

    Validates all files belonging to an artist against MusicBrainz.
    """
    validate_uuid(str(artist_id), "artist_id")

    from app.models.artist import Artist
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist {artist_id} not found")

    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import validate_mbid_metadata_task

    # Count files with MBID for this artist
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(*) FROM library_files lf
        JOIN albums a ON a.id = lf.album_id
        WHERE a.artist_id = :artist_id
        AND lf.mbid_in_file = TRUE
    """)
    result = db.execute(count_query, {'artist_id': str(artist_id)})
    file_count = result.scalar() or 0

    if file_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No files with MBID found for artist '{artist.name}'."
        )

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID_METADATA,
        status=JobStatus.PENDING,
        artist_id=artist_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = validate_mbid_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created artist validate_mbid_metadata job {job.id} for artist {artist.name}")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f"MBID metadata validation job queued for artist '{artist.name}'. {file_count} files to validate.",
        estimated_files=file_count
    )


@router.post("/albums/{album_id}/validate-mbid-metadata", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_album_validate_mbid_metadata_job(
    album_id: UUID,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Validate MBID metadata for a specific album's files

    Validates all files in an album against MusicBrainz.
    """
    validate_uuid(str(album_id), "album_id")

    from app.models.album import Album
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail=f"Album {album_id} not found")

    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import validate_mbid_metadata_task

    # Count files with MBID for this album
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(*) FROM library_files
        WHERE album_id = :album_id
        AND mbid_in_file = TRUE
    """)
    result = db.execute(count_query, {'album_id': str(album_id)})
    file_count = result.scalar() or 0

    if file_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No files with MBID found for album '{album.title}'."
        )

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID_METADATA,
        status=JobStatus.PENDING,
        album_id=album_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = validate_mbid_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created album validate_mbid_metadata job {job.id} for album {album.title}")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f"MBID metadata validation job queued for album '{album.title}'. {file_count} files to validate.",
        estimated_files=file_count
    )


class SingleFileValidationResponse(BaseModel):
    """Response for single file MBID metadata validation"""
    file_path: str
    has_mbid: bool
    recording_mbid: Optional[str] = None
    confidence_score: Optional[int] = None
    confidence_level: Optional[str] = None
    file_metadata: Optional[dict] = None
    mb_metadata: Optional[dict] = None
    recommendation: Optional[str] = None
    validated_at: str


@router.post("/files/validate-mbid-metadata")
@rate_limit("30/minute")
def validate_single_file_mbid_metadata(
    file_path: str = Query(..., description="Full path to the audio file"),
    request: Request = None,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Validate MBID metadata for a single file (synchronous)

    Immediately validates a single file's metadata against MusicBrainz
    and returns the result. Does not create a background job.
    """
    import time
    from app.services.metadata_extractor import MetadataExtractor
    from app.services.metadata_writer import MetadataWriter
    from app.services.musicbrainz_client import MusicBrainzClient
    from app.services.mbid_confidence_scorer import MBIDConfidenceScorer

    # Verify file exists
    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Read MBID from file
    mbid_data = MetadataWriter.verify_mbid_in_file(file_path)

    if not mbid_data.get('has_mbid'):
        return SingleFileValidationResponse(
            file_path=file_path,
            has_mbid=False,
            recommendation="File has no MBID. Run 'Fetch Metadata' to search MusicBrainz.",
            validated_at=datetime.now(timezone.utc).isoformat()
        )

    recording_mbid = mbid_data.get('recording_mbid')
    if not recording_mbid:
        return SingleFileValidationResponse(
            file_path=file_path,
            has_mbid=True,
            recommendation="File has MBID data but no Recording MBID.",
            validated_at=datetime.now(timezone.utc).isoformat()
        )

    # Look up on MusicBrainz
    mb_client = MusicBrainzClient()
    try:
        mb_recording = mb_client.get_recording(recording_mbid, includes=['artists', 'releases'])
        time.sleep(1.0)  # Rate limit
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MusicBrainz lookup failed: {e}")

    if not mb_recording:
        return SingleFileValidationResponse(
            file_path=file_path,
            has_mbid=True,
            recording_mbid=recording_mbid,
            recommendation=f"Recording {recording_mbid} not found on MusicBrainz. MBID may be invalid.",
            validated_at=datetime.now(timezone.utc).isoformat()
        )

    # Extract file metadata
    file_metadata = MetadataExtractor.extract(file_path)
    if not file_metadata:
        return SingleFileValidationResponse(
            file_path=file_path,
            has_mbid=True,
            recording_mbid=recording_mbid,
            recommendation="Could not extract metadata from file.",
            validated_at=datetime.now(timezone.utc).isoformat()
        )

    # Calculate confidence
    score_result = MBIDConfidenceScorer.score_match(
        file_metadata={
            'title': file_metadata.get('title'),
            'artist': file_metadata.get('artist'),
            'album': file_metadata.get('album'),
            'duration': file_metadata.get('duration') or file_metadata.get('length')
        },
        mb_recording=mb_recording
    )

    breakdown = score_result['breakdown']

    return SingleFileValidationResponse(
        file_path=file_path,
        has_mbid=True,
        recording_mbid=recording_mbid,
        confidence_score=score_result['total_score'],
        confidence_level=score_result['confidence_level'],
        file_metadata={
            'title': file_metadata.get('title'),
            'artist': file_metadata.get('artist'),
            'album': file_metadata.get('album'),
            'duration': file_metadata.get('duration')
        },
        mb_metadata={
            'title': breakdown['title']['mb'],
            'artist': breakdown['artist']['mb'],
            'album': breakdown['album']['mb'],
            'duration': breakdown['duration']['mb']
        },
        recommendation=score_result['recommendation'],
        validated_at=datetime.now(timezone.utc).isoformat()
    )


@router.post("/library-paths/{library_path_id}/link-files", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_link_files_job(
    library_path_id: UUID,
    request: Request,
    auto_import_artists: bool = False,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to link files with MBIDs to album tracks

    This job:
    - Finds files with Recording MBIDs
    - Matches to existing album tracks by MBID
    - Links files to tracks in the database
    - Updates track has_file status
    - Optionally auto-imports artists for unlinked files
    """
    validate_uuid(str(library_path_id), "library_path_id")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")

    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import link_files_task

    # Count files with MBID
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(*) FROM library_files
        WHERE library_path_id = :library_path_id
        AND musicbrainz_trackid IS NOT NULL
    """)
    result = db.execute(count_query, {'library_path_id': str(library_path_id)})
    file_count = result.scalar() or 0

    job = FileOrganizationJob(
        job_type=JobType.LINK_FILES,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = link_files_task.delay(
        str(job.id),
        library_path_id=str(library_path_id),
        auto_import_artists=auto_import_artists
    )
    job.celery_task_id = result.id
    db.commit()

    msg = f'Link files job queued. {file_count} files to link.'
    if auto_import_artists:
        msg += ' Auto-import artists enabled.'

    logger.info(f"Created link_files job {job.id} for library path {library_path_id} (auto_import={auto_import_artists})")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=msg,
        estimated_files=file_count
    )


@router.post("/files/resolve-unlinked", response_model=OrganizationJobResponse, status_code=202)
@rate_limit("5/minute")
def trigger_resolve_unlinked(
    request: Request,
    library_path_id: Optional[UUID] = None,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Trigger bulk resolution of unlinked files.

    This job runs multiple phases:
    1. Auto-import missing albums from MusicBrainz (album_not_in_db files)
    2. Re-run MBID matching (fast path + ambiguous)
    3. Release group fallback matching
    4. Fuzzy matching for files without MBIDs (by title + artist + duration)
    5. Re-categorize remaining unlinked files
    """
    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.resolve_unlinked_task import resolve_unlinked_files_task

    if library_path_id:
        validate_uuid(str(library_path_id), "library_path_id")
        library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
        if not library_path:
            raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")

    # Check for existing running resolve job
    running_job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.job_type == JobType.RESOLVE_UNLINKED,
        FileOrganizationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
    ).first()

    if running_job:
        raise HTTPException(
            status_code=409,
            detail=f"A resolve job is already running (job {running_job.id})"
        )

    # Count unlinked files
    count_sql = text("""
        SELECT
            (SELECT COUNT(*) FROM library_files lf
             LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
             WHERE lf.musicbrainz_trackid IS NOT NULL AND t.id IS NULL) +
            (SELECT COUNT(*) FROM library_files WHERE musicbrainz_trackid IS NULL)
        AS total_unlinked
    """)
    total_unlinked = db.execute(count_sql).scalar() or 0

    job = FileOrganizationJob(
        job_type=JobType.RESOLVE_UNLINKED,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=total_unlinked,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = resolve_unlinked_files_task.delay(
        str(job.id),
        library_path_id=str(library_path_id) if library_path_id else None
    )
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created resolve_unlinked job {job.id} ({total_unlinked} unlinked files)")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Resolve unlinked files job queued. {total_unlinked} files to process.',
        estimated_files=total_unlinked
    )


@router.post("/library-paths/{library_path_id}/reindex-albums", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_reindex_albums_job(
    library_path_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to reindex albums/singles from file metadata
    
    This job:
    - Reads Release MBIDs from file comments
    - Groups files by album
    - Detects albums vs singles based on track count
    - Updates album information in database
    """
    validate_uuid(str(library_path_id), "library_path_id")
    
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")
    
    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import reindex_albums_task
    
    # Count distinct albums in library
    from sqlalchemy import text
    count_query = text("""
        SELECT COUNT(DISTINCT musicbrainz_releasegroupid) FROM library_files
        WHERE library_path_id = :library_path_id
        AND musicbrainz_releasegroupid IS NOT NULL
    """)
    result = db.execute(count_query, {'library_path_id': str(library_path_id)})
    album_count = result.scalar() or 0
    
    job = FileOrganizationJob(
        job_type=JobType.REINDEX_ALBUMS,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=album_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    result = reindex_albums_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()
    
    logger.info(f"Created reindex_albums job {job.id} for library path {library_path_id}")
    
    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Reindex albums job queued. {album_count} albums to process.',
        estimated_files=album_count
    )


class VerifyAudioRequest(BaseModel):
    """Request for audio verification job"""
    days_back: int = Field(default=90, ge=1, le=365, description="Verify files downloaded within this many days")


@router.post("/library-paths/{library_path_id}/verify-audio", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_verify_audio_job(
    library_path_id: UUID,
    request_data: VerifyAudioRequest,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to verify audio files from recent downloads
    
    This job:
    - Finds files that were downloaded within the specified time period
    - Verifies that MBIDs are correctly written to file Comment tags
    - Reports any mismatches or missing MBIDs
    """
    validate_uuid(str(library_path_id), "library_path_id")
    
    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")
    
    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import verify_audio_task
    
    # Count files downloaded in the time period
    from datetime import timedelta
    from sqlalchemy import text
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=request_data.days_back)
    count_query = text("""
        SELECT COUNT(*) FROM library_files
        WHERE library_path_id = :library_path_id
        AND musicbrainz_trackid IS NOT NULL
        AND indexed_at >= :cutoff_date
    """)
    result = db.execute(count_query, {
        'library_path_id': str(library_path_id),
        'cutoff_date': cutoff_date
    })
    file_count = result.scalar() or 0
    
    job = FileOrganizationJob(
        job_type=JobType.VERIFY_AUDIO,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    result = verify_audio_task.delay(str(job.id), request_data.days_back)
    job.celery_task_id = result.id
    db.commit()
    
    logger.info(f"Created verify_audio job {job.id} for library path {library_path_id}, days_back={request_data.days_back}")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Audio verification job queued. Checking {file_count} files downloaded in last {request_data.days_back} days.',
        estimated_files=file_count
    )


# ========================================
# Library Migration Endpoints
# ========================================

class LibraryMigrationRequest(BaseModel):
    """Request to start library migration"""
    source_library_id: str = Field(..., description="Source library path UUID")
    destination_library_id: Optional[str] = Field(None, description="Existing destination library UUID")
    new_library_name: Optional[str] = Field(None, description="Name for new destination library")
    new_library_path: Optional[str] = Field(None, description="Path for new destination library")
    min_confidence: int = Field(80, ge=50, le=100, description="Minimum confidence threshold for auto-acceptance")
    correct_metadata: bool = Field(True, description="Correct metadata to match MusicBrainz")
    create_metadata_files: bool = Field(True, description="Create .mbid.json files in album directories")


class MigrationJobResponse(BaseModel):
    """Response for migration job creation"""
    job_id: str
    status: str
    source_library: Dict[str, Any]
    destination_library: Dict[str, Any]
    estimated_files: int
    message: str


class MigrationStatusResponse(BaseModel):
    """Migration job status"""
    id: str
    job_type: str
    status: str
    progress_percent: float
    current_action: Optional[str] = None
    files_total: int
    files_processed: int
    files_with_mbid: int
    files_mbid_fetched: int
    files_metadata_corrected: int
    files_validated: int
    files_moved: int
    files_failed: int
    followup_job_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class MigrationLogEntry(BaseModel):
    """Entry in migration log"""
    source_path: str
    destination_path: Optional[str] = None
    recording_mbid: Optional[str] = None
    confidence_score: Optional[int] = None
    validation_tag: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    timestamp: str


class MigrationLogsResponse(BaseModel):
    """Response for migration logs"""
    count: int
    files: List[Dict[str, Any]]


class MigrationSummaryResponse(BaseModel):
    """Summary of migration job"""
    job_id: str
    status: str
    total_files: int
    success_count: int
    failed_count: int
    skipped_count: int
    ponder_count: int
    duration_seconds: Optional[int] = None


@router.post("/library-migration", response_model=MigrationJobResponse)
@rate_limit("5/minute")
def start_library_migration(
    request_data: LibraryMigrationRequest,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start library migration job

    Migrates all files from source library to destination library with:
    - MBID validation and lookup
    - Metadata correction against MusicBrainz
    - File renaming using NamingEngine templates
    - Directory creation based on artist/album metadata
    - Validation tag writing to "Encoded By" field
    - Auto-dispatch Ponder job for files with <80% confidence

    **Fully automated - no user intervention required.**
    """
    from app.models.file_organization_job import FileOrganizationJob, JobStatus, JobType
    from app.models.library import LibraryFile
    from app.tasks.migration_tasks import library_migration_task

    validate_uuid(request_data.source_library_id, "source_library_id")

    # Verify source library exists
    source_library = db.query(LibraryPath).filter(
        LibraryPath.id == UUID(request_data.source_library_id)
    ).first()
    if not source_library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source library {request_data.source_library_id} not found"
        )

    # Determine destination library
    destination_library = None
    if request_data.destination_library_id:
        validate_uuid(request_data.destination_library_id, "destination_library_id")
        destination_library = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(request_data.destination_library_id)
        ).first()
        if not destination_library:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Destination library {request_data.destination_library_id} not found"
            )
    elif request_data.new_library_name and request_data.new_library_path:
        # Create new library
        import os
        if not os.path.exists(request_data.new_library_path):
            os.makedirs(request_data.new_library_path, exist_ok=True)

        destination_library = LibraryPath(
            name=request_data.new_library_name,
            path=request_data.new_library_path
        )
        db.add(destination_library)
        db.commit()
        db.refresh(destination_library)
        logger.info(f"Created new destination library: {destination_library.name} at {destination_library.path}")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either destination_library_id or both new_library_name and new_library_path"
        )

    # Check for running migration jobs
    running_job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.source_library_path_id == source_library.id,
        FileOrganizationJob.status.in_(['pending', 'running'])
    ).first()
    if running_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Migration job already in progress for source library: {running_job.id}"
        )

    # Count files to migrate
    file_count = db.query(LibraryFile).filter(
        LibraryFile.library_path_id == source_library.id
    ).count()

    # Create migration job
    job = FileOrganizationJob(
        job_type=JobType.LIBRARY_MIGRATION,
        status=JobStatus.PENDING,
        source_library_path_id=source_library.id,
        destination_library_path_id=destination_library.id,
        files_total=file_count,
        progress_percent=0.0,
        files_with_mbid=0,
        files_mbid_fetched=0,
        files_metadata_corrected=0,
        files_validated=0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch Celery task
    options = {
        'min_confidence': request_data.min_confidence,
        'correct_metadata': request_data.correct_metadata,
        'create_metadata_files': request_data.create_metadata_files
    }

    result = library_migration_task.delay(
        str(job.id),
        str(source_library.id),
        str(destination_library.id),
        options
    )
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created library migration job {job.id}: {source_library.path} -> {destination_library.path}")

    return MigrationJobResponse(
        job_id=str(job.id),
        status='queued',
        source_library={
            'id': str(source_library.id),
            'name': source_library.name,
            'path': source_library.path
        },
        destination_library={
            'id': str(destination_library.id),
            'name': destination_library.name,
            'path': destination_library.path
        },
        estimated_files=file_count,
        message=f"Library migration job queued. Migrating {file_count} files from '{source_library.name}' to '{destination_library.name}'."
    )


@router.get("/library-migration/{job_id}", response_model=MigrationStatusResponse)
def get_migration_status(
    job_id: UUID,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get detailed status of a library migration job"""
    from app.models.file_organization_job import FileOrganizationJob, JobType

    validate_uuid(str(job_id), "job_id")

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id,
        FileOrganizationJob.job_type.in_([JobType.LIBRARY_MIGRATION, JobType.MIGRATION_FINGERPRINT])
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration job {job_id} not found"
        )

    return MigrationStatusResponse(
        id=str(job.id),
        job_type=job.job_type.value,
        status=job.status.value,
        progress_percent=job.progress_percent or 0,
        current_action=job.current_action,
        files_total=job.files_total or 0,
        files_processed=job.files_processed or 0,
        files_with_mbid=job.files_with_mbid or 0,
        files_mbid_fetched=job.files_mbid_fetched or 0,
        files_metadata_corrected=job.files_metadata_corrected or 0,
        files_validated=job.files_validated or 0,
        files_moved=job.files_moved or 0,
        files_failed=job.files_failed or 0,
        followup_job_id=str(job.followup_job_id) if job.followup_job_id else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        error_message=job.error_message
    )


@router.get("/library-migration/{job_id}/logs/success", response_model=MigrationLogsResponse)
def get_migration_success_log(
    job_id: UUID,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get success log for migration job"""
    import json
    import os

    validate_uuid(str(job_id), "job_id")

    log_file = f"/app/logs/migration_{job_id}_success.json"
    if not os.path.exists(log_file):
        return MigrationLogsResponse(count=0, files=[])

    with open(log_file, 'r') as f:
        data = json.load(f)
        return MigrationLogsResponse(
            count=data.get('count', 0),
            files=data.get('files', [])
        )


@router.get("/library-migration/{job_id}/logs/failed", response_model=MigrationLogsResponse)
def get_migration_failed_log(
    job_id: UUID,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get failed log for migration job"""
    import json
    import os

    validate_uuid(str(job_id), "job_id")

    log_file = f"/app/logs/migration_{job_id}_failed.json"
    if not os.path.exists(log_file):
        return MigrationLogsResponse(count=0, files=[])

    with open(log_file, 'r') as f:
        data = json.load(f)
        return MigrationLogsResponse(
            count=data.get('count', 0),
            files=data.get('files', [])
        )


@router.get("/library-migration/{job_id}/logs/skipped", response_model=MigrationLogsResponse)
def get_migration_skipped_log(
    job_id: UUID,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get skipped log for migration job"""
    import json
    import os

    validate_uuid(str(job_id), "job_id")

    log_file = f"/app/logs/migration_{job_id}_skipped.json"
    if not os.path.exists(log_file):
        return MigrationLogsResponse(count=0, files=[])

    with open(log_file, 'r') as f:
        data = json.load(f)
        return MigrationLogsResponse(
            count=data.get('count', 0),
            files=data.get('files', [])
        )


@router.get("/library-migration/{job_id}/summary", response_model=MigrationSummaryResponse)
def get_migration_summary(
    job_id: UUID,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get summary of migration job results"""
    import json
    import os

    from app.models.file_organization_job import FileOrganizationJob

    validate_uuid(str(job_id), "job_id")

    job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration job {job_id} not found"
        )

    # Read log files for counts
    success_count = 0
    failed_count = 0
    skipped_count = 0
    ponder_count = 0

    success_file = f"/app/logs/migration_{job_id}_success.json"
    failed_file = f"/app/logs/migration_{job_id}_failed.json"
    skipped_file = f"/app/logs/migration_{job_id}_skipped.json"
    ponder_file = f"/app/logs/migration_{job_id}_ponder_queue.json"

    if os.path.exists(success_file):
        with open(success_file, 'r') as f:
            success_count = json.load(f).get('count', 0)

    if os.path.exists(failed_file):
        with open(failed_file, 'r') as f:
            failed_count = json.load(f).get('count', 0)

    if os.path.exists(skipped_file):
        with open(skipped_file, 'r') as f:
            skipped_count = json.load(f).get('count', 0)

    if os.path.exists(ponder_file):
        with open(ponder_file, 'r') as f:
            ponder_count = json.load(f).get('count', 0)

    # Calculate duration
    duration_seconds = None
    if job.started_at and job.completed_at:
        duration_seconds = int((job.completed_at - job.started_at).total_seconds())

    return MigrationSummaryResponse(
        job_id=str(job.id),
        status=job.status.value,
        total_files=job.files_total or 0,
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        ponder_count=ponder_count,
        duration_seconds=duration_seconds
    )


@router.post("/library-migration/{job_id}/retry-failed", response_model=MigrationJobResponse)
@rate_limit("5/minute")
def retry_failed_migration(
    job_id: UUID,
    request: Request,
    include_skipped: bool = Query(True, description="Include skipped files in retry"),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Retry failed and optionally skipped files from a completed migration job.

    Creates a new migration job with only the files that failed or were skipped.
    """
    import json
    import os

    from app.models.file_organization_job import FileOrganizationJob, JobStatus, JobType
    from app.tasks.migration_tasks import library_migration_task

    validate_uuid(str(job_id), "job_id")

    # Get original job
    original_job = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.id == job_id,
        FileOrganizationJob.job_type == JobType.LIBRARY_MIGRATION
    ).first()

    if not original_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration job {job_id} not found"
        )

    if original_job.status not in [JobStatus.COMPLETED, JobStatus.FAILED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only retry completed or failed jobs. Current status: {original_job.status.value}"
        )

    # Collect files to retry
    files_to_retry = []

    failed_file = f"/app/logs/migration_{job_id}_failed.json"
    if os.path.exists(failed_file):
        with open(failed_file, 'r') as f:
            data = json.load(f)
            for item in data.get('files', []):
                files_to_retry.append(item.get('file_path'))

    if include_skipped:
        skipped_file = f"/app/logs/migration_{job_id}_skipped.json"
        if os.path.exists(skipped_file):
            with open(skipped_file, 'r') as f:
                data = json.load(f)
                for item in data.get('files', []):
                    files_to_retry.append(item.get('file_path'))

    if not files_to_retry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files to retry"
        )

    # Get source and destination libraries
    source_library = db.query(LibraryPath).filter(
        LibraryPath.id == original_job.source_library_path_id
    ).first()

    destination_library = db.query(LibraryPath).filter(
        LibraryPath.id == original_job.destination_library_path_id
    ).first()

    if not source_library or not destination_library:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source or destination library no longer exists"
        )

    # Create new job
    job = FileOrganizationJob(
        job_type=JobType.LIBRARY_MIGRATION,
        status=JobStatus.PENDING,
        source_library_path_id=source_library.id,
        destination_library_path_id=destination_library.id,
        parent_job_id=original_job.id,
        files_total=len(files_to_retry),
        progress_percent=0.0,
        files_with_mbid=0,
        files_mbid_fetched=0,
        files_metadata_corrected=0,
        files_validated=0,
        files_without_mbid_json=json.dumps([{'file_path': f} for f in files_to_retry])
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch Celery task
    options = {
        'min_confidence': 80,
        'correct_metadata': True,
        'create_metadata_files': True,
        'retry_file_list': files_to_retry
    }

    result = library_migration_task.delay(
        str(job.id),
        str(source_library.id),
        str(destination_library.id),
        options
    )
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created retry migration job {job.id} for {len(files_to_retry)} files from job {job_id}")

    return MigrationJobResponse(
        job_id=str(job.id),
        status='queued',
        source_library={
            'id': str(source_library.id),
            'name': source_library.name,
            'path': source_library.path
        },
        destination_library={
            'id': str(destination_library.id),
            'name': destination_library.name,
            'path': destination_library.path
        },
        estimated_files=len(files_to_retry),
        message=f"Retry migration job queued for {len(files_to_retry)} files."
    )


# ========================================
# Unlinked Files Endpoints
# ========================================

class UnlinkedFileResponse(BaseModel):
    id: str
    library_file_id: str
    file_path: str
    filesystem_path: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    musicbrainz_trackid: Optional[str] = None
    reason: str
    reason_detail: Optional[str] = None
    detected_at: Optional[str] = None
    resolved_at: Optional[str] = None
    format: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    duration_seconds: Optional[int] = None


class UnlinkedFilesSummaryResponse(BaseModel):
    total: int
    by_reason: Dict[str, int]
    last_scan: Optional[str] = None


class UnlinkedFilesListResponse(BaseModel):
    items: List[UnlinkedFileResponse]
    total: int
    page: int
    per_page: int
    reason_summary: Dict[str, int]


@router.get("/unlinked-files/summary", response_model=UnlinkedFilesSummaryResponse)
@rate_limit("30/minute")
def get_unlinked_files_summary(
    request: Request,
    library_type: Optional[str] = Query(None, description="Filter by library type (music, audiobook)"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Get summary statistics for unlinked files"""
    from app.models.unlinked_file import UnlinkedFile

    try:
        # Count by reason (unresolved only)
        type_join = ""
        type_condition = ""
        type_params: Dict[str, Any] = {}
        if library_type:
            type_join = "JOIN library_files lf ON lf.id = uf.library_file_id"
            type_condition = "AND lf.library_type = :library_type"
            type_params['library_type'] = library_type

        reason_counts = db.execute(text(f"""
            SELECT uf.reason, COUNT(*) as cnt
            FROM unlinked_files uf
            {type_join}
            WHERE uf.resolved_at IS NULL {type_condition}
            GROUP BY uf.reason
            ORDER BY cnt DESC
        """), type_params).fetchall()

        by_reason = {row[0]: row[1] for row in reason_counts}
        total = sum(by_reason.values())

        # Last scan date
        last_scan = db.execute(text(f"""
            SELECT MAX(uf.detected_at) FROM unlinked_files uf
            {type_join}
            {"WHERE lf.library_type = :library_type" if library_type else ""}
        """), type_params).scalar()

        return UnlinkedFilesSummaryResponse(
            total=total,
            by_reason=by_reason,
            last_scan=last_scan.isoformat() if last_scan else None
        )
    except Exception as e:
        logger.error(f"Failed to get unlinked files summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unlinked-files", response_model=UnlinkedFilesListResponse)
@rate_limit("30/minute")
def get_unlinked_files(
    request: Request,
    reason: Optional[str] = Query(None, description="Filter by reason"),
    artist: Optional[str] = Query(None, description="Search by artist name"),
    search: Optional[str] = Query(None, description="Search file path, artist, album, or title"),
    library_path_id: Optional[str] = Query(None, description="Filter by library path"),
    library_type: Optional[str] = Query(None, description="Filter by library type (music, audiobook)"),
    sort_by: Optional[str] = Query(None, description="Sort column"),
    sort_dir: Optional[str] = Query("asc", description="Sort direction: asc or desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Get paginated list of unlinked files with filters"""
    try:
        # Build WHERE clauses
        conditions = ["uf.resolved_at IS NULL"]
        params: Dict[str, Any] = {}

        if library_type:
            conditions.append("lf.library_type = :library_type")
            params['library_type'] = library_type

        if reason:
            conditions.append("uf.reason = :reason")
            params['reason'] = reason

        if artist:
            conditions.append("uf.artist ILIKE :artist")
            params['artist'] = f"%{artist}%"

        if search:
            conditions.append("(uf.file_path ILIKE :search OR uf.artist ILIKE :search OR uf.album ILIKE :search OR uf.title ILIKE :search)")
            params['search'] = f"%{search}%"

        if library_path_id:
            conditions.append("lf.library_path_id = CAST(:library_path_id AS uuid)")
            params['library_path_id'] = library_path_id

        where_clause = " AND ".join(conditions)

        # Always join library_files to get filesystem path
        join_clause = "LEFT JOIN library_files lf ON lf.id = uf.library_file_id"

        # Get total count
        count_sql = text(f"SELECT COUNT(*) FROM unlinked_files uf {join_clause} WHERE {where_clause}")
        total = db.execute(count_sql, params).scalar() or 0

        # Get reason summary (for the current filter minus reason filter)
        summary_conditions = [c for c in conditions if "uf.reason" not in c]
        summary_where = " AND ".join(summary_conditions) if summary_conditions else "1=1"
        summary_sql = text(f"""
            SELECT uf.reason, COUNT(*) as cnt
            FROM unlinked_files uf {join_clause}
            WHERE {summary_where}
            GROUP BY uf.reason
            ORDER BY cnt DESC
        """)
        summary_params = {k: v for k, v in params.items() if k != 'reason'}
        reason_rows = db.execute(summary_sql, summary_params).fetchall()
        reason_summary = {row[0]: row[1] for row in reason_rows}

        # Get paginated items
        offset = (page - 1) * per_page
        params['limit'] = per_page
        params['offset'] = offset

        # Build ORDER BY
        unlinked_sort_columns = {
            'file': 'uf.file_path',
            'file_path': 'lf.file_path',
            'artist': 'uf.artist',
            'album': 'uf.album',
            'title': 'uf.title',
            'reason': 'uf.reason',
            'detected_at': 'uf.detected_at',
        }
        order_col = unlinked_sort_columns.get(sort_by or '', 'uf.reason')
        order_dir = 'DESC' if sort_dir == 'desc' else 'ASC'
        order_clause = f"{order_col} {order_dir} NULLS LAST"
        if sort_by and sort_by != 'reason':
            order_clause += ", uf.artist, uf.album, uf.title"

        items_sql = text(f"""
            SELECT uf.id, uf.library_file_id, uf.file_path, uf.artist, uf.album, uf.title,
                   uf.musicbrainz_trackid, uf.reason, uf.reason_detail, uf.detected_at, uf.resolved_at,
                   lf.file_path as filesystem_path,
                   lf.format, lf.bitrate_kbps, lf.sample_rate_hz, lf.duration_seconds
            FROM unlinked_files uf {join_clause}
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
        """)
        rows = db.execute(items_sql, params).fetchall()

        items = [
            UnlinkedFileResponse(
                id=str(row[0]),
                library_file_id=str(row[1]),
                file_path=row[2],
                filesystem_path=row[11],
                artist=row[3],
                album=row[4],
                title=row[5],
                musicbrainz_trackid=row[6],
                reason=row[7],
                reason_detail=row[8],
                detected_at=row[9].isoformat() if row[9] else None,
                resolved_at=row[10].isoformat() if row[10] else None,
                format=row[12],
                bitrate_kbps=row[13],
                sample_rate_hz=row[14],
                duration_seconds=row[15],
            )
            for row in rows
        ]

        return UnlinkedFilesListResponse(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            reason_summary=reason_summary
        )
    except Exception as e:
        logger.error(f"Failed to get unlinked files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unlinked-files/export")
@rate_limit("30/minute")
def export_unlinked_files_csv(
    request: Request,
    reason: Optional[str] = Query(None),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Export unlinked files as CSV download"""
    try:
        conditions = ["resolved_at IS NULL"]
        params: Dict[str, Any] = {}

        if reason:
            conditions.append("reason = :reason")
            params['reason'] = reason

        where_clause = " AND ".join(conditions)

        rows = db.execute(text(f"""
            SELECT file_path, artist, album, title, musicbrainz_trackid, reason, reason_detail, detected_at
            FROM unlinked_files
            WHERE {where_clause}
            ORDER BY reason, artist, album, title
        """), params).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['file_path', 'artist', 'album', 'title', 'musicbrainz_trackid', 'reason', 'reason_detail', 'detected_at'])
        for row in rows:
            writer.writerow([
                row[0], row[1], row[2], row[3], row[4], row[5], row[6],
                row[7].isoformat() if row[7] else ''
            ])

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename=unlinked_files.csv'}
        )
    except Exception as e:
        logger.error(f"Failed to export unlinked files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/unlinked-files/resolved")
@rate_limit("30/minute")
def cleanup_resolved_unlinked_files(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Delete resolved entries from unlinked_files table"""
    try:
        result = db.execute(text("DELETE FROM unlinked_files WHERE resolved_at IS NOT NULL"))
        deleted = result.rowcount
        db.commit()
        return {"deleted": deleted, "message": f"Cleaned up {deleted} resolved entries"}
    except Exception as e:
        logger.error(f"Failed to cleanup resolved unlinked files: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# Unlinked Files - Delete from Disk
# ========================================

@router.delete("/unlinked-files/{unlinked_id}")
@rate_limit("30/minute")
def delete_unlinked_file(
    unlinked_id: UUID,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """Delete an unlinked file from disk and remove its DB records."""
    validate_uuid(str(unlinked_id), "unlinked_id")

    from app.models.unlinked_file import UnlinkedFile

    uf = db.query(UnlinkedFile).filter(UnlinkedFile.id == unlinked_id).first()
    if not uf:
        raise HTTPException(status_code=404, detail="Unlinked file not found")

    file_path = uf.file_path

    # Delete physical file from disk
    import os
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")
    else:
        logger.warning(f"File already missing from disk: {file_path}")

    # Delete the unlinked_files record (library_files cascades via FK)
    try:
        # Also delete the parent library_file record if it exists
        if uf.library_file_id:
            db.execute(text("DELETE FROM library_files WHERE id = :id"), {"id": uf.library_file_id})
        db.delete(uf)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete unlinked file record: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "deleted_path": file_path}


# ========================================
# Unlinked Files - Edit & Link Endpoints
# ========================================

class UpdateUnlinkedMetadataRequest(BaseModel):
    """Request to update metadata on an unlinked file"""
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None


class LinkUnlinkedFileRequest(BaseModel):
    """Request to link an unlinked file to a specific track"""
    track_id: str = Field(..., description="UUID of the track to link to")
    acoustid_score: Optional[float] = Field(None, description="AcoustID match score (0.0-1.0). Required for DJ role (must be >= 0.80)")


@router.patch("/unlinked-files/{unlinked_id}/metadata")
@rate_limit("30/minute")
def update_unlinked_metadata(
    unlinked_id: UUID,
    body: UpdateUnlinkedMetadataRequest,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Edit metadata (artist/album/title) on an unlinked file.
    Writes tags to the audio file and updates DB records.
    """
    validate_uuid(str(unlinked_id), "unlinked_id")

    from app.models.unlinked_file import UnlinkedFile
    from app.models.library import LibraryFile
    from app.services.metadata_writer import MetadataWriter

    uf = db.query(UnlinkedFile).filter(UnlinkedFile.id == unlinked_id).first()
    if not uf:
        raise HTTPException(status_code=404, detail="Unlinked file not found")
    if uf.resolved_at is not None:
        raise HTTPException(status_code=400, detail="File is already resolved")

    file_path = uf.file_path
    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found on disk: {file_path}")

    # Build kwargs for metadata write
    write_kwargs = {}
    if body.artist is not None:
        write_kwargs['artist'] = body.artist
    if body.album is not None:
        write_kwargs['album'] = body.album
    if body.title is not None:
        write_kwargs['title'] = body.title

    if not write_kwargs:
        raise HTTPException(status_code=400, detail="At least one field (artist, album, title) must be provided")

    # Write to audio file
    result = MetadataWriter.write_metadata(file_path, **write_kwargs)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Failed to write metadata: {result.error}")

    # Update unlinked_files record
    if body.artist is not None:
        uf.artist = body.artist
    if body.album is not None:
        uf.album = body.album
    if body.title is not None:
        uf.title = body.title

    # Update library_files record
    lf = db.query(LibraryFile).filter(LibraryFile.id == uf.library_file_id).first()
    if lf:
        if body.artist is not None:
            lf.artist = body.artist
        if body.album is not None:
            lf.album = body.album
        if body.title is not None:
            lf.title = body.title

    db.commit()

    return {
        "success": True,
        "id": str(uf.id),
        "artist": uf.artist,
        "album": uf.album,
        "title": uf.title,
        "tags_written": result.tags_written,
    }


@router.post("/unlinked-files/{unlinked_id}/link")
@rate_limit("30/minute")
def link_unlinked_file(
    unlinked_id: UUID,
    body: LinkUnlinkedFileRequest,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Link an unlinked file to a specific track.
    Writes metadata + MBIDs to audio file, moves file to correct location,
    updates Track.file_path + has_file, marks unlinked file as resolved.
    """
    validate_uuid(str(unlinked_id), "unlinked_id")
    validate_uuid(body.track_id, "track_id")

    from app.models.unlinked_file import UnlinkedFile
    from app.models.library import LibraryFile
    from app.models.track import Track
    from app.models.album import Album
    from app.models.artist import Artist
    from app.services.metadata_writer import MetadataWriter
    from app.shared_services.naming_engine import NamingEngine, TrackContext
    from app.shared_services.atomic_file_ops import AtomicFileOps

    # 1. Look up unlinked file
    uf = db.query(UnlinkedFile).filter(UnlinkedFile.id == unlinked_id).first()
    if not uf:
        raise HTTPException(status_code=404, detail="Unlinked file not found")
    if uf.resolved_at is not None:
        raise HTTPException(status_code=400, detail="File is already resolved")

    file_path = uf.file_path
    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found on disk: {file_path}")

    # DJ role AcoustID restriction: must have >= 80% match score
    if current_user.role == "dj":
        if body.acoustid_score is None or body.acoustid_score < 0.80:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"DJs can only link files with AcoustID match score >= 80%. Score: {body.acoustid_score or 'not provided'}"
            )

    # 2. Look up Track + Album + Artist
    track = db.query(Track).filter(Track.id == body.track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    album = db.query(Album).filter(Album.id == track.album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found for track")

    artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found for album")

    # 3. Determine the library root (from library_files → library_path)
    lf = db.query(LibraryFile).filter(LibraryFile.id == uf.library_file_id).first()
    library_root = None
    if lf:
        from app.models.library import LibraryPath
        lp = db.query(LibraryPath).filter(LibraryPath.id == lf.library_path_id).first()
        if lp:
            library_root = lp.path

    if not library_root:
        # Fall back to artist's root folder or first library path
        lp = db.query(LibraryPath).filter(LibraryPath.is_enabled == True).first()
        if lp:
            library_root = lp.path
        else:
            raise HTTPException(status_code=400, detail="No library path found for file organization")

    # 4. Write metadata + MBIDs to audio file
    release_year = album.release_date.year if album.release_date else None
    file_ext = Path(file_path).suffix.lstrip('.')

    write_result = MetadataWriter.write_all(
        file_path,
        recording_mbid=track.musicbrainz_id,
        artist_mbid=artist.musicbrainz_id,
        release_mbid=album.release_mbid,
        release_group_mbid=album.musicbrainz_id,
        title=track.title,
        artist=artist.name,
        album=album.title,
        track_number=track.track_number,
        disc_number=track.disc_number,
        year=release_year,
        overwrite_mbid=True,
        overwrite_metadata=True,
    )
    if not write_result.success:
        logger.error(f"Failed to write metadata for link: {write_result.error}")
        # Continue anyway — moving the file is more important

    # 5. Calculate target path via NamingEngine
    naming_engine = NamingEngine()
    track_context = TrackContext(
        artist_name=artist.name,
        album_title=album.title,
        track_title=track.title,
        track_number=track.track_number or 1,
        release_year=release_year,
        disc_number=track.disc_number or 1,
        file_extension=file_ext,
        album_type=album.album_type or "Album",
    )

    track_filename = naming_engine.generate_track_filename(track_context)
    target_path = str(Path(library_root) / track_filename)

    # 6. Move file via AtomicFileOps
    new_path = file_path  # Default if move not needed
    if str(Path(file_path).resolve()) != str(Path(target_path).resolve()):
        atomic_ops = AtomicFileOps()
        move_result = atomic_ops.move_file(file_path, target_path)
        if not move_result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to move file: {move_result.error_message}"
            )
        new_path = target_path
        logger.info(f"Moved file from {file_path} to {new_path}")

    # 7. Update Track record
    track.file_path = new_path
    track.has_file = True

    # 8. Update library_files record
    if lf:
        lf.file_path = new_path
        lf.file_name = Path(new_path).name
        lf.musicbrainz_trackid = track.musicbrainz_id
        lf.musicbrainz_artistid = artist.musicbrainz_id
        lf.musicbrainz_albumid = album.release_mbid
        lf.is_organized = True
        lf.artist = artist.name
        lf.album = album.title
        lf.title = track.title

    # 9. Mark unlinked file as resolved
    uf.resolved_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "success": True,
        "new_path": new_path,
        "track_title": track.title,
        "album_title": album.title,
        "artist_name": artist.name,
    }


@router.get("/unlinked-files/{unlinked_id}/link-search")
@rate_limit("60/minute")
def search_link_targets(
    unlinked_id: UUID,
    request: Request,
    query: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("artist", description="Search type: artist, album, or track"),
    artist_id: Optional[UUID] = Query(None, description="Filter albums/tracks to this artist"),
    album_id: Optional[UUID] = Query(None, description="Filter tracks to this album"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Search for link targets (artists, albums, or tracks) from the DB.
    Used by the LinkFileModal for step-by-step linking.
    """
    from app.models.artist import Artist
    from app.models.album import Album
    from app.models.track import Track

    search_pattern = f"%{query}%"

    if type == "artist":
        artists = db.query(Artist).filter(
            Artist.name.ilike(search_pattern)
        ).order_by(Artist.name).limit(limit).all()
        return {
            "type": "artist",
            "results": [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "musicbrainz_id": a.musicbrainz_id,
                }
                for a in artists
            ]
        }

    elif type == "album":
        q = db.query(Album).filter(Album.title.ilike(search_pattern))
        if artist_id:
            q = q.filter(Album.artist_id == artist_id)
        albums = q.order_by(Album.title).limit(limit).all()
        return {
            "type": "album",
            "results": [
                {
                    "id": str(a.id),
                    "title": a.title,
                    "artist_id": str(a.artist_id),
                    "release_date": a.release_date.isoformat() if a.release_date else None,
                    "album_type": a.album_type,
                    "track_count": a.track_count,
                    "cover_art_url": a.cover_art_url,
                }
                for a in albums
            ]
        }

    elif type == "track":
        q = db.query(Track).filter(Track.title.ilike(search_pattern))
        if album_id:
            q = q.filter(Track.album_id == album_id)
        tracks = q.order_by(Track.disc_number, Track.track_number).limit(limit).all()
        return {
            "type": "track",
            "results": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "track_number": t.track_number,
                    "disc_number": t.disc_number,
                    "has_file": t.has_file,
                    "album_id": str(t.album_id),
                    "musicbrainz_id": t.musicbrainz_id,
                    "duration_ms": t.duration_ms,
                }
                for t in tracks
            ]
        }

    else:
        raise HTTPException(status_code=400, detail="type must be 'artist', 'album', or 'track'")


@router.get("/unlinked-files/{unlinked_id}/stream")
@rate_limit("100/minute")
async def stream_unlinked_file(
    unlinked_id: UUID,
    request: Request,
    token: str = Query(None, description="JWT token for audio element auth"),
    db: Session = Depends(get_db)
):
    """Stream an unlinked audio file for playback. Accepts Bearer header or ?token= query param."""
    from app.auth import get_current_user, bearer_scheme
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = await bearer_scheme(request)
    if credentials:
        await get_current_user(credentials, db)
    elif token:
        fake_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        await get_current_user(fake_creds, db)
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    validate_uuid(str(unlinked_id), "unlinked_id")

    from app.models.unlinked_file import UnlinkedFile

    uf = db.query(UnlinkedFile).filter(UnlinkedFile.id == unlinked_id).first()
    if not uf:
        raise HTTPException(status_code=404, detail="Unlinked file not found")

    file_path = Path(uf.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {uf.file_path}")

    ext = file_path.suffix.lower()
    media_type_map = {
        '.mp3': 'audio/mpeg',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4',
        '.aac': 'audio/aac',
        '.ogg': 'audio/ogg',
        '.opus': 'audio/opus',
        '.wav': 'audio/wav',
        '.wma': 'audio/x-ms-wma',
    }
    media_type = media_type_map.get(ext, 'audio/mpeg')

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{file_path.name.encode("ascii", "replace").decode("ascii")}"',
            "Accept-Ranges": "bytes",
        }
    )


@router.post("/unlinked-files/{unlinked_id}/acoustid-lookup")
@rate_limit("10/minute")
def acoustid_lookup(
    unlinked_id: UUID,
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Fingerprint an unlinked file with fpcalc and look it up on AcoustID.
    Returns matched recordings with artist, title, album, and MusicBrainz IDs.
    """
    import subprocess
    import os
    import requests as http_requests

    validate_uuid(str(unlinked_id), "unlinked_id")

    from app.models.unlinked_file import UnlinkedFile

    uf = db.query(UnlinkedFile).filter(UnlinkedFile.id == unlinked_id).first()
    if not uf:
        raise HTTPException(status_code=404, detail="Unlinked file not found")

    file_path = uf.file_path
    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {file_path}")

    api_key = os.getenv("ACOUSTID_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ACOUSTID_API_KEY not configured")

    # Run fpcalc to get fingerprint + duration
    try:
        result = subprocess.run(
            ["fpcalc", "-json", file_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"fpcalc failed: {result.stderr.strip()}")

        import json
        fpcalc_data = json.loads(result.stdout)
        fingerprint = fpcalc_data["fingerprint"]
        duration = int(fpcalc_data["duration"])
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="fpcalc timed out")
    except (json.JSONDecodeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=f"fpcalc output parse error: {e}")

    # Call AcoustID API
    try:
        resp = http_requests.post(
            "https://api.acoustid.org/v2/lookup",
            data={
                "client": api_key,
                "duration": duration,
                "fingerprint": fingerprint,
                "meta": "recordings releasegroups",
            },
            headers={
                "User-Agent": "Studio54/1.0 ( https://github.com/tesimmons/MasterControl )",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except http_requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"AcoustID API error: {e}")

    if data.get("status") != "ok":
        error_msg = data.get("error", {}).get("message", "Unknown error")
        raise HTTPException(status_code=502, detail=f"AcoustID error: {error_msg}")

    # Parse results into a clean format
    matches = []
    for result in data.get("results", []):
        score = result.get("score", 0)
        if score < 0.5:
            continue

        for recording in result.get("recordings", []):
            artists = recording.get("artists", [])
            artist_name = ", ".join(a.get("name", "") for a in artists) if artists else None
            artist_mbid = artists[0].get("id") if artists else None

            # Extract release group info
            release_groups = recording.get("releasegroups", [])
            album_title = None
            album_type = None
            release_group_mbid = None
            if release_groups:
                rg = release_groups[0]
                album_title = rg.get("title")
                album_type = rg.get("type")
                release_group_mbid = rg.get("id")

            matches.append({
                "score": round(score, 3),
                "recording_mbid": recording.get("id"),
                "title": recording.get("title"),
                "artist": artist_name,
                "artist_mbid": artist_mbid,
                "album": album_title,
                "album_type": album_type,
                "release_group_mbid": release_group_mbid,
            })

    # Deduplicate by recording_mbid, keep highest score
    seen = {}
    for m in matches:
        key = m["recording_mbid"]
        if key and (key not in seen or m["score"] > seen[key]["score"]):
            seen[key] = m
    matches = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

    return {
        "file_path": file_path,
        "duration": duration,
        "matches": matches[:10],
    }


# Also add endpoints to list albums/tracks for a specific artist/album (no search needed)

@router.get("/unlinked-files/artists/{artist_id}/albums")
@rate_limit("60/minute")
def get_artist_albums_for_linking(
    artist_id: UUID,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """Get all albums for an artist (used by LinkFileModal step 2)"""
    validate_uuid(str(artist_id), "artist_id")
    from app.models.album import Album

    albums = db.query(Album).filter(
        Album.artist_id == artist_id
    ).order_by(Album.release_date.desc().nullslast()).all()

    return {
        "results": [
            {
                "id": str(a.id),
                "title": a.title,
                "release_date": a.release_date.isoformat() if a.release_date else None,
                "album_type": a.album_type,
                "track_count": a.track_count,
                "cover_art_url": a.cover_art_url,
            }
            for a in albums
        ]
    }


@router.get("/unlinked-files/albums/{album_id}/tracks")
@rate_limit("60/minute")
def get_album_tracks_for_linking(
    album_id: UUID,
    request: Request,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """Get all tracks for an album (used by LinkFileModal step 3)"""
    validate_uuid(str(album_id), "album_id")
    from app.models.track import Track

    tracks = db.query(Track).filter(
        Track.album_id == album_id
    ).order_by(Track.disc_number, Track.track_number).all()

    return {
        "results": [
            {
                "id": str(t.id),
                "title": t.title,
                "track_number": t.track_number,
                "disc_number": t.disc_number,
                "has_file": t.has_file,
                "musicbrainz_id": t.musicbrainz_id,
                "duration_ms": t.duration_ms,
            }
            for t in tracks
        ]
    }


# ========================================
# Unorganized Files Endpoints
# ========================================

class UnorganizedFileResponse(BaseModel):
    id: str
    file_path: str
    file_name: str
    artist: Optional[str] = None
    album_artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    format: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    duration_seconds: Optional[int] = None
    file_size_bytes: Optional[int] = None
    musicbrainz_trackid: Optional[str] = None
    musicbrainz_artistid: Optional[str] = None
    musicbrainz_albumid: Optional[str] = None
    indexed_at: Optional[str] = None


class UnorganizedFilesListResponse(BaseModel):
    items: List[UnorganizedFileResponse]
    total: int
    page: int
    per_page: int


@router.get("/unorganized-files/summary")
@rate_limit("30/minute")
def get_unorganized_files_summary(
    request: Request,
    library_type: Optional[str] = Query(None, description="Filter by library type (music, audiobook)"),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get summary statistics for unorganized files"""
    try:
        type_condition = ""
        type_params: Dict[str, Any] = {}
        if library_type:
            type_condition = "AND library_type = :library_type"
            type_params['library_type'] = library_type

        total = db.execute(text(
            f"SELECT COUNT(*) FROM library_files WHERE (is_organized = false OR is_organized IS NULL) {type_condition}"
        ), type_params).scalar() or 0

        organized = db.execute(text(
            f"SELECT COUNT(*) FROM library_files WHERE is_organized = true {type_condition}"
        ), type_params).scalar() or 0

        # Group by format
        format_rows = db.execute(text(f"""
            SELECT COALESCE(UPPER(format), 'UNKNOWN') as fmt, COUNT(*) as cnt
            FROM library_files
            WHERE (is_organized = false OR is_organized IS NULL) {type_condition}
            GROUP BY fmt
            ORDER BY cnt DESC
        """), type_params).fetchall()
        by_format = {row[0]: row[1] for row in format_rows}

        return {
            "total_unorganized": total,
            "total_organized": organized,
            "by_format": by_format,
        }
    except Exception as e:
        logger.error(f"Failed to get unorganized files summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unorganized-files", response_model=UnorganizedFilesListResponse)
@rate_limit("30/minute")
def get_unorganized_files(
    request: Request,
    search: Optional[str] = Query(None, description="Search file path, artist, album, or title"),
    format_filter: Optional[str] = Query(None, alias="format", description="Filter by audio format"),
    library_type: Optional[str] = Query(None, description="Filter by library type (music, audiobook)"),
    sort_by: Optional[str] = Query(None, description="Sort column"),
    sort_dir: Optional[str] = Query("asc", description="Sort direction: asc or desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Get paginated list of unorganized library files"""
    try:
        conditions = ["(lf.is_organized = false OR lf.is_organized IS NULL)"]
        params: Dict[str, Any] = {}

        if library_type:
            conditions.append("lf.library_type = :library_type")
            params['library_type'] = library_type

        if search:
            conditions.append(
                "(lf.file_path ILIKE :search OR lf.artist ILIKE :search "
                "OR lf.album ILIKE :search OR lf.title ILIKE :search "
                "OR lf.album_artist ILIKE :search)"
            )
            params['search'] = f"%{search}%"

        if format_filter:
            conditions.append("UPPER(lf.format) = UPPER(:format_filter)")
            params['format_filter'] = format_filter

        where_clause = " AND ".join(conditions)

        # Total count
        total = db.execute(
            text(f"SELECT COUNT(*) FROM library_files lf WHERE {where_clause}"),
            params
        ).scalar() or 0

        # Paginated items
        offset = (page - 1) * per_page
        params['limit'] = per_page
        params['offset'] = offset

        # Build ORDER BY
        unorg_sort_columns = {
            'file': 'lf.file_name',
            'file_path': 'lf.file_path',
            'artist': "COALESCE(lf.album_artist, lf.artist, '')",
            'album': 'lf.album',
            'title': 'lf.title',
            'track_number': 'lf.track_number',
            'year': 'lf.year',
            'format': 'lf.format',
            'mbid': 'lf.musicbrainz_trackid',
        }
        order_col = unorg_sort_columns.get(sort_by or '', "COALESCE(lf.album_artist, lf.artist, '')")
        order_dir_str = 'DESC' if sort_dir == 'desc' else 'ASC'
        order_clause = f"{order_col} {order_dir_str} NULLS LAST"
        if sort_by not in ('artist', None):
            order_clause += ", COALESCE(lf.album_artist, lf.artist, ''), lf.album, lf.disc_number, lf.track_number"

        rows = db.execute(text(f"""
            SELECT lf.id, lf.file_path, lf.file_name,
                   lf.artist, lf.album_artist, lf.album, lf.title,
                   lf.track_number, lf.disc_number, lf.year, lf.genre,
                   lf.format, lf.bitrate_kbps, lf.duration_seconds, lf.file_size_bytes,
                   lf.musicbrainz_trackid, lf.musicbrainz_artistid, lf.musicbrainz_albumid,
                   lf.indexed_at
            FROM library_files lf
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        items = [
            UnorganizedFileResponse(
                id=str(row[0]),
                file_path=row[1],
                file_name=row[2],
                artist=row[3],
                album_artist=row[4],
                album=row[5],
                title=row[6],
                track_number=row[7],
                disc_number=row[8],
                year=row[9],
                genre=row[10],
                format=row[11],
                bitrate_kbps=row[12],
                duration_seconds=row[13],
                file_size_bytes=row[14],
                musicbrainz_trackid=row[15],
                musicbrainz_artistid=row[16],
                musicbrainz_albumid=row[17],
                indexed_at=row[18].isoformat() if row[18] else None,
            )
            for row in rows
        ]

        return UnorganizedFilesListResponse(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
        )
    except Exception as e:
        logger.error(f"Failed to get unorganized files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# Validate File Links Endpoints
# ========================================

@router.post("/library-paths/{library_path_id}/validate-file-links", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_validate_file_links_job(
    library_path_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to validate that all linked track files still exist on disk
    for a specific library path.
    """
    validate_uuid(str(library_path_id), "library_path_id")

    library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
    if not library_path:
        raise HTTPException(status_code=404, detail=f"Library path {library_path_id} not found")

    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import validate_file_links_task
    from app.models.track import Track

    file_count = db.query(Track).filter(
        Track.has_file == True,
        Track.file_path.isnot(None),
        Track.file_path.like(f"{library_path.path}%")
    ).count()

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_FILE_LINKS,
        status=JobStatus.PENDING,
        library_path_id=library_path_id,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = validate_file_links_task.delay(str(job.id), str(library_path_id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created validate_file_links job {job.id} for library path {library_path_id}")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'File link validation job queued. Checking {file_count} linked tracks.',
        estimated_files=file_count
    )


@router.post("/validate-file-links", response_model=OrganizationJobResponse)
@rate_limit("10/minute")
def start_validate_all_file_links_job(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Start a job to validate all linked track files across all library paths.
    """
    from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
    from app.tasks.organization_tasks import validate_file_links_task
    from app.models.track import Track

    file_count = db.query(Track).filter(
        Track.has_file == True,
        Track.file_path.isnot(None)
    ).count()

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_FILE_LINKS,
        status=JobStatus.PENDING,
        files_total=file_count,
        progress_percent=0.0
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = validate_file_links_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Created validate_file_links job {job.id} for all library paths")

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'File link validation job queued. Checking {file_count} linked tracks across all libraries.',
        estimated_files=file_count
    )
