"""
Jobs API - Task status and management endpoints

Provides real-time visibility into background job execution with:
- Job listing and filtering
- Progress tracking
- Cancellation support
- Retry functionality
- Statistics and monitoring
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
import uuid

from app.database import get_db
from app.models.job_state import JobState, JobType, JobStatus
from app.models.file_organization_job import FileOrganizationJob, JobStatus as FileOrgJobStatus, JobType as FileOrgJobType
from app.models.library import ScanJob
from app.models.library_import import LibraryImportJob
from app.tasks.celery_app import celery_app
from app.auth import require_director, require_any_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


# Pydantic schemas
class JobStateResponse(BaseModel):
    """Job state response schema"""
    id: str
    job_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    celery_task_id: Optional[str] = None
    worker_id: Optional[str] = None
    status: str
    current_step: Optional[str] = None
    progress_percent: float
    items_processed: int
    items_total: Optional[int] = None
    speed_metric: Optional[float] = None
    eta_seconds: Optional[int] = None
    retry_count: int
    max_retries: int
    error_message: Optional[str] = None
    log_file_path: Optional[str] = None
    result_data: Optional[dict] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    updated_at: datetime
    completed_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_job_state(cls, job: JobState) -> "JobStateResponse":
        """Convert JobState model to response schema"""
        return cls(
            id=str(job.id),
            job_type=job.job_type.value if isinstance(job.job_type, JobType) else job.job_type,
            entity_type=job.entity_type,
            entity_id=str(job.entity_id) if job.entity_id else None,
            celery_task_id=job.celery_task_id,
            worker_id=job.worker_id,
            status=job.status.value if isinstance(job.status, JobStatus) else job.status,
            current_step=job.current_step,
            progress_percent=job.progress_percent or 0.0,
            items_processed=job.items_processed or 0,
            items_total=job.items_total,
            speed_metric=job.speed_metric,
            eta_seconds=job.eta_seconds,
            retry_count=job.retry_count or 0,
            max_retries=job.max_retries or 3,
            error_message=job.error_message,
            log_file_path=job.log_file_path,
            result_data=job.result_data,
            created_at=job.created_at,
            started_at=job.started_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
            last_heartbeat_at=job.last_heartbeat_at
        )


class JobListResponse(BaseModel):
    """Job list response with pagination"""
    jobs: List[JobStateResponse]
    total_count: int
    limit: int
    offset: int


class JobStatsResponse(BaseModel):
    """Job statistics response"""
    total_jobs: int = Field(description="Total number of jobs")
    pending: int = Field(description="Jobs waiting to start")
    running: int = Field(description="Currently executing jobs")
    paused: int = Field(description="Paused jobs")
    completed: int = Field(description="Successfully completed jobs")
    failed: int = Field(description="Failed jobs")
    cancelled: int = Field(description="Cancelled jobs")
    stalled: int = Field(description="Stalled jobs (no heartbeat)")
    retrying: int = Field(description="Jobs being retried")


class JobCancelResponse(BaseModel):
    """Job cancellation response"""
    success: bool
    message: str
    job_id: str


class JobRetryResponse(BaseModel):
    """Job retry response"""
    success: bool
    message: str
    new_job_id: str


# API Endpoints

@router.get("", response_model=JobListResponse)
def list_jobs(
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    limit: int = Query(50, le=200, description="Number of jobs to return"),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List jobs with optional filters and pagination

    Returns recent jobs sorted by creation date (newest first).
    """
    query = db.query(JobState)

    # Check if job_type is a FileOrganizationJob type
    is_file_org_type = False
    if job_type:
        try:
            FileOrgJobType(job_type)
            is_file_org_type = True
        except ValueError:
            pass

    # Apply filters to JobState query (skip if filtering by a file org type)
    if job_type and not is_file_org_type:
        try:
            job_type_enum = JobType(job_type)
            query = query.filter(JobState.job_type == job_type_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid job_type: {job_type}")

    if status:
        try:
            status_enum = JobStatus(status)
            query = query.filter(JobState.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if entity_id:
        try:
            entity_uuid = uuid.UUID(entity_id)
            query = query.filter(JobState.entity_id == entity_uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid entity_id: {entity_id}")

    # Get total count before pagination
    total_count = query.count()

    # Apply pagination and ordering
    # Skip JobState results if filtering by a file org type
    if is_file_org_type:
        jobs = []
    else:
        jobs = query.order_by(desc(JobState.created_at)).offset(offset).limit(limit).all()

    # Convert JobState jobs to response format
    job_responses = [JobStateResponse.from_job_state(job) for job in jobs]

    # Also fetch file organization jobs
    file_org_query = db.query(FileOrganizationJob)

    # Include file org jobs when: no type filter, generic "file_organization" filter, or specific file org type
    if not job_type or job_type == "file_organization" or is_file_org_type:
        # Filter by specific file org job type
        if is_file_org_type:
            file_org_query = file_org_query.filter(
                FileOrganizationJob.job_type == FileOrgJobType(job_type)
            )

        if status:
            try:
                status_map = {
                    "pending": FileOrgJobStatus.PENDING,
                    "running": FileOrgJobStatus.RUNNING,
                    "completed": FileOrgJobStatus.COMPLETED,
                    "failed": FileOrgJobStatus.FAILED,
                    "paused": FileOrgJobStatus.PAUSED,
                    "cancelled": FileOrgJobStatus.CANCELLED
                }
                if status in status_map:
                    file_org_query = file_org_query.filter(FileOrganizationJob.status == status_map[status])
            except:
                pass

        if entity_id:
            # Filter by library_path_id, artist_id, or album_id
            try:
                entity_uuid = uuid.UUID(entity_id)
                file_org_query = file_org_query.filter(
                    (FileOrganizationJob.library_path_id == entity_uuid) |
                    (FileOrganizationJob.artist_id == entity_uuid) |
                    (FileOrganizationJob.album_id == entity_uuid)
                )
            except:
                pass

        file_org_jobs = file_org_query.order_by(desc(FileOrganizationJob.created_at)).limit(limit).all()

        # Convert file organization jobs to JobStateResponse format
        for job in file_org_jobs:
            # Get the actual job type value
            actual_job_type = job.job_type.value if isinstance(job.job_type, FileOrgJobType) else str(job.job_type)
            job_responses.append(JobStateResponse(
                id=str(job.id),
                job_type=actual_job_type,  # validate_structure, fetch_metadata, organize_library, etc.
                entity_type="file_organization",  # Source type indicator
                entity_id=str(job.library_path_id) if job.library_path_id else (str(job.artist_id) if job.artist_id else None),
                celery_task_id=job.celery_task_id,
                worker_id=None,
                status=job.status.value,
                current_step=job.current_action,
                progress_percent=float(job.progress_percent or 0),
                items_processed=job.files_processed or 0,
                items_total=job.files_total or 0,
                speed_metric=None,
                eta_seconds=None,
                retry_count=0,
                max_retries=0,
                error_message=job.error_message,
                log_file_path=job.log_file_path,
                created_at=job.created_at,
                started_at=job.started_at,
                updated_at=job.created_at,  # FileOrganizationJob doesn't have updated_at
                completed_at=job.completed_at,
                last_heartbeat_at=None
            ))

        total_count += len(file_org_jobs)

    # Also fetch scan jobs
    if not job_type or job_type == "scan":
        scan_query = db.query(ScanJob)

        if status:
            status_map = {
                "pending": "pending",
                "running": "running",
                "completed": "completed",
                "failed": "failed"
            }
            if status in status_map:
                scan_query = scan_query.filter(ScanJob.status == status_map[status])

        if entity_id:
            try:
                entity_uuid = uuid.UUID(entity_id)
                scan_query = scan_query.filter(ScanJob.library_path_id == entity_uuid)
            except:
                pass

        scan_jobs = scan_query.order_by(desc(ScanJob.created_at)).limit(limit).all()

        for job in scan_jobs:
            # Calculate progress from files_scanned if available
            progress = 0.0
            if job.files_scanned and job.files_scanned > 0:
                # Estimate progress based on elapsed vs estimated remaining
                if job.estimated_remaining_seconds and job.elapsed_seconds:
                    total_time = job.elapsed_seconds + job.estimated_remaining_seconds
                    progress = (job.elapsed_seconds / total_time) * 100 if total_time > 0 else 0
                elif job.status == 'completed':
                    progress = 100.0

            # Use current_action if available, otherwise default message
            current_step = job.current_action or (f"Scanned {job.files_scanned or 0} files" if job.files_scanned else None)

            job_responses.append(JobStateResponse(
                id=str(job.id),
                job_type="scan",
                entity_type="library_path",
                entity_id=str(job.library_path_id) if job.library_path_id else None,
                celery_task_id=job.celery_task_id,
                worker_id=None,
                status=job.status or "pending",
                current_step=current_step,
                progress_percent=progress,
                items_processed=job.files_scanned or 0,
                items_total=job.files_scanned or 0,  # ScanJob doesn't track total upfront
                speed_metric=None,
                eta_seconds=job.estimated_remaining_seconds,
                retry_count=0,
                max_retries=0,
                error_message=job.error_message,
                log_file_path=job.log_file_path,
                created_at=job.created_at,
                started_at=job.started_at,
                updated_at=job.created_at,
                completed_at=job.completed_at,
                last_heartbeat_at=None
            ))

        total_count += len(scan_jobs)

    # Also fetch library import jobs
    if not job_type or job_type == "import":
        import_query = db.query(LibraryImportJob)

        if status:
            status_map = {
                "pending": "pending",
                "running": "running",
                "completed": "completed",
                "failed": "failed"
            }
            if status in status_map:
                import_query = import_query.filter(LibraryImportJob.status == status_map[status])

        if entity_id:
            try:
                entity_uuid = uuid.UUID(entity_id)
                import_query = import_query.filter(LibraryImportJob.library_path_id == entity_uuid)
            except:
                pass

        import_jobs = import_query.order_by(desc(LibraryImportJob.created_at)).limit(limit).all()

        for job in import_jobs:
            # Build current step from current_phase and current_action
            current_step = job.current_phase
            if job.current_action:
                current_step = f"{job.current_phase}: {job.current_action}" if job.current_phase else job.current_action

            job_responses.append(JobStateResponse(
                id=str(job.id),
                job_type="import",
                entity_type="library_path",
                entity_id=str(job.library_path_id) if job.library_path_id else None,
                celery_task_id=job.celery_task_id,
                worker_id=None,
                status=job.status or "pending",
                current_step=current_step,
                progress_percent=float(job.progress_percent or 0),
                items_processed=job.files_scanned or 0,
                items_total=job.files_scanned or 0,  # LibraryImportJob doesn't track total upfront
                speed_metric=None,
                eta_seconds=None,
                retry_count=0,
                max_retries=0,
                error_message=job.error_message,
                log_file_path=job.log_file_path,
                created_at=job.created_at,
                started_at=job.started_at,
                updated_at=job.created_at,
                completed_at=job.completed_at,
                last_heartbeat_at=None
            ))

        total_count += len(import_jobs)

    # Sort all jobs by created_at
    job_responses.sort(key=lambda x: x.created_at, reverse=True)

    # Apply limit after merging
    job_responses = job_responses[:limit]

    return JobListResponse(
        jobs=job_responses,
        total_count=total_count,
        limit=limit,
        offset=offset
    )


@router.get("/stats", response_model=JobStatsResponse)
def get_job_stats(
    job_type: Optional[str] = Query(None, description="Filter stats by job type"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get job statistics aggregated by status

    Queries all job tables (JobState, FileOrganizationJob, ScanJob, LibraryImportJob)
    and combines their statistics.

    Optionally filter by job type to see stats for specific operation types.
    """
    # Initialize combined status counts
    status_counts = {
        "pending": 0,
        "running": 0,
        "paused": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "stalled": 0,
        "retrying": 0,
    }
    total = 0

    # === Query JobState table ===
    if not job_type or job_type not in ["file_organization", "scan", "import",
                                        "validate_structure", "fetch_metadata", "organize_library",
                                        "organize_artist", "organize_album", "validate_mbid",
                                        "link_files", "reindex_albums", "verify_audio"]:
        query = db.query(JobState)
        if job_type:
            try:
                job_type_enum = JobType(job_type)
                query = query.filter(JobState.job_type == job_type_enum)
            except ValueError:
                pass  # Invalid job type for JobState, skip

        job_state_total = query.count()
        total += job_state_total

        stats = db.query(
            JobState.status,
            func.count(JobState.id)
        )
        if job_type:
            try:
                job_type_enum = JobType(job_type)
                stats = stats.filter(JobState.job_type == job_type_enum)
            except ValueError:
                pass

        for status, count in stats.group_by(JobState.status).all():
            status_value = status.value if isinstance(status, JobStatus) else status
            if status_value in status_counts:
                status_counts[status_value] += count

    # === Query FileOrganizationJob table ===
    file_org_job_types = ["file_organization", "validate_structure", "fetch_metadata",
                         "organize_library", "organize_artist", "organize_album",
                         "validate_mbid", "validate_mbid_metadata", "link_files",
                         "reindex_albums", "verify_audio", "associate_and_organize",
                         "rollback", "library_migration", "migration_fingerprint"]
    if not job_type or job_type in file_org_job_types:
        file_org_query = db.query(FileOrganizationJob)

        if job_type and job_type != "file_organization":
            try:
                file_org_type_enum = FileOrgJobType(job_type)
                file_org_query = file_org_query.filter(FileOrganizationJob.job_type == file_org_type_enum)
            except ValueError:
                pass

        file_org_total = file_org_query.count()
        total += file_org_total

        file_org_stats = db.query(
            FileOrganizationJob.status,
            func.count(FileOrganizationJob.id)
        )
        if job_type and job_type != "file_organization":
            try:
                file_org_type_enum = FileOrgJobType(job_type)
                file_org_stats = file_org_stats.filter(FileOrganizationJob.job_type == file_org_type_enum)
            except ValueError:
                pass

        for status, count in file_org_stats.group_by(FileOrganizationJob.status).all():
            status_value = status.value if isinstance(status, FileOrgJobStatus) else status
            # Map FileOrganizationJob statuses to our status counts
            if status_value in status_counts:
                status_counts[status_value] += count

    # === Query ScanJob table ===
    if not job_type or job_type == "scan":
        scan_query = db.query(ScanJob)
        scan_total = scan_query.count()
        total += scan_total

        scan_stats = db.query(
            ScanJob.status,
            func.count(ScanJob.id)
        ).group_by(ScanJob.status).all()

        for status, count in scan_stats:
            if status in status_counts:
                status_counts[status] += count

    # === Query LibraryImportJob table ===
    if not job_type or job_type == "import":
        import_query = db.query(LibraryImportJob)
        import_total = import_query.count()
        total += import_total

        import_stats = db.query(
            LibraryImportJob.status,
            func.count(LibraryImportJob.id)
        ).group_by(LibraryImportJob.status).all()

        for status, count in import_stats:
            if status in status_counts:
                status_counts[status] += count

    return JobStatsResponse(
        total_jobs=total,
        pending=status_counts["pending"],
        running=status_counts["running"],
        paused=status_counts["paused"],
        completed=status_counts["completed"],
        failed=status_counts["failed"],
        cancelled=status_counts["cancelled"],
        stalled=status_counts["stalled"],
        retrying=status_counts["retrying"],
    )


@router.get("/{job_id}", response_model=JobStateResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific job

    Returns full job state including progress, errors, and timing information.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    job = db.query(JobState).filter(JobState.id == job_uuid).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStateResponse.from_job_state(job)


@router.post("/{job_id}/cancel", response_model=JobCancelResponse)
def cancel_job(
    job_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Cancel a running or pending job

    Attempts to gracefully cancel the job by:
    1. Revoking the Celery task (if running)
    2. Marking the job as cancelled in the database

    Jobs in terminal states (completed, failed, cancelled) cannot be cancelled.
    Searches across all job types (JobState, FileOrganizationJob, ScanJob, LibraryImportJob).
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # Search JobState first
    job = db.query(JobState).filter(JobState.id == job_uuid).first()

    if job:
        # Check if job can be cancelled
        if job.is_terminal():
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in {job.status.value} state"
            )

        # Revoke Celery task if it exists
        if job.celery_task_id:
            try:
                celery_app.control.revoke(
                    job.celery_task_id,
                    terminate=True,
                    signal='SIGTERM'
                )
            except Exception as e:
                print(f"Error revoking Celery task {job.celery_task_id}: {e}")

        # Update job status
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)

        if not job.error_message:
            job.error_message = "Job cancelled by user"

        db.commit()

        return JobCancelResponse(
            success=True,
            message="Job cancelled successfully",
            job_id=job_id
        )

    # Search FileOrganizationJob
    file_org_job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()

    if file_org_job:
        # Check if job can be cancelled
        terminal_statuses = [FileOrgJobStatus.COMPLETED, FileOrgJobStatus.FAILED, FileOrgJobStatus.CANCELLED, FileOrgJobStatus.ROLLED_BACK]
        if file_org_job.status in terminal_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in {file_org_job.status.value} state"
            )

        # Revoke Celery task if it exists
        if file_org_job.celery_task_id:
            try:
                celery_app.control.revoke(
                    file_org_job.celery_task_id,
                    terminate=True,
                    signal='SIGTERM'
                )
            except Exception as e:
                print(f"Error revoking Celery task {file_org_job.celery_task_id}: {e}")

        # Update job status
        file_org_job.status = FileOrgJobStatus.CANCELLED
        file_org_job.completed_at = datetime.now(timezone.utc)

        if not file_org_job.error_message:
            file_org_job.error_message = "Job cancelled by user"

        db.commit()

        return JobCancelResponse(
            success=True,
            message="Job cancelled successfully",
            job_id=job_id
        )

    # Search ScanJob
    scan_job = db.query(ScanJob).filter(ScanJob.id == job_uuid).first()

    if scan_job:
        # Check if job can be cancelled
        if scan_job.status in ['completed', 'failed', 'cancelled']:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in {scan_job.status} state"
            )

        # Revoke Celery task if it exists
        if scan_job.celery_task_id:
            try:
                celery_app.control.revoke(
                    scan_job.celery_task_id,
                    terminate=True,
                    signal='SIGTERM'
                )
            except Exception as e:
                print(f"Error revoking Celery task {scan_job.celery_task_id}: {e}")

        # Update job status
        scan_job.status = 'cancelled'
        scan_job.completed_at = datetime.now(timezone.utc)

        if not scan_job.error_message:
            scan_job.error_message = "Job cancelled by user"

        db.commit()

        return JobCancelResponse(
            success=True,
            message="Job cancelled successfully",
            job_id=job_id
        )

    # Search LibraryImportJob
    import_job = db.query(LibraryImportJob).filter(LibraryImportJob.id == job_uuid).first()

    if import_job:
        # Check if job can be cancelled
        if import_job.status in ['completed', 'failed', 'cancelled']:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in {import_job.status} state"
            )

        # Revoke Celery task if it exists
        if import_job.celery_task_id:
            try:
                celery_app.control.revoke(
                    import_job.celery_task_id,
                    terminate=True,
                    signal='SIGTERM'
                )
            except Exception as e:
                print(f"Error revoking Celery task {import_job.celery_task_id}: {e}")

        # Update job status
        import_job.status = 'cancelled'
        import_job.cancel_requested = True
        import_job.completed_at = datetime.now(timezone.utc)

        if not import_job.error_message:
            import_job.error_message = "Job cancelled by user"

        db.commit()

        return JobCancelResponse(
            success=True,
            message="Job cancelled successfully",
            job_id=job_id
        )

    raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")


class JobResumeResponse(BaseModel):
    """Job resume response"""
    success: bool
    message: str
    job_id: str
    celery_task_id: Optional[str] = None


@router.post("/{job_id}/resume", response_model=JobResumeResponse)
def resume_job(
    job_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Resume a paused job

    Currently supports resuming FileOrganizationJob jobs in PAUSED status.
    For FETCH_METADATA jobs, this dispatches the task to fetch metadata from MusicBrainz.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # First check JobState
    job = db.query(JobState).filter(JobState.id == job_uuid).first()

    if job:
        # Handle JobState resume
        if job.status != JobStatus.PAUSED:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume job in {job.status.value} state. Only paused jobs can be resumed."
            )

        # Resume JobState job
        job.status = JobStatus.PENDING
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        return JobResumeResponse(
            success=True,
            message="Job resumed successfully",
            job_id=job_id
        )

    # Check FileOrganizationJob
    file_org_job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()

    if file_org_job:
        if file_org_job.status != FileOrgJobStatus.PAUSED:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume job in {file_org_job.status.value} state. Only paused jobs can be resumed."
            )

        # Import the task here to avoid circular imports
        from app.tasks.organization_tasks import fetch_metadata_task

        # Handle FETCH_METADATA job
        if file_org_job.job_type == FileOrgJobType.FETCH_METADATA:
            result = fetch_metadata_task.delay(str(file_org_job.id))
            file_org_job.celery_task_id = result.id
            file_org_job.status = FileOrgJobStatus.PENDING
            file_org_job.current_action = "Queued to fetch metadata from MusicBrainz"
            db.commit()

            return JobResumeResponse(
                success=True,
                message=f"Fetch metadata job resumed, processing {file_org_job.files_total} files",
                job_id=job_id,
                celery_task_id=result.id
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Resume not supported for job type: {file_org_job.job_type.value}"
            )

    raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")


class JobPauseResponse(BaseModel):
    """Job pause response"""
    success: bool
    message: str
    job_id: str


class CheckpointInfoResponse(BaseModel):
    """Checkpoint information response"""
    job_id: str
    has_checkpoint: bool
    checkpoint_data: Optional[dict] = None
    checkpoint_age_seconds: Optional[float] = None
    pause_requested: bool


class BulkPauseResumeResponse(BaseModel):
    """Bulk pause/resume operation response"""
    success: bool
    message: str
    jobs_affected: int
    job_ids: List[str]
    errors: List[str] = []


@router.post("/{job_id}/pause", response_model=JobPauseResponse)
def pause_job(
    job_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Request a running job to pause at the next safe checkpoint.

    The job will continue until it reaches a safe stopping point (checkpoint),
    then save its state and pause. This allows safe system updates without
    losing work in progress.

    Supports FileOrganizationJob jobs.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # Check FileOrganizationJob
    file_org_job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()

    if file_org_job:
        if file_org_job.status != FileOrgJobStatus.RUNNING:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot pause job in {file_org_job.status.value} state. Only running jobs can be paused."
            )

        # Request pause via checkpoint manager
        from app.services.job_checkpoint_manager import JobCheckpointManager
        checkpoint_manager = JobCheckpointManager(job_id)

        if checkpoint_manager.request_pause():
            return JobPauseResponse(
                success=True,
                message="Pause requested. Job will pause at next checkpoint.",
                job_id=job_id
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to request pause. Redis may be unavailable."
            )

    # Check JobState (generic jobs)
    job = db.query(JobState).filter(JobState.id == job_uuid).first()

    if job:
        if job.status != JobStatus.RUNNING:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot pause job in {job.status.value} state. Only running jobs can be paused."
            )

        from app.services.job_checkpoint_manager import JobCheckpointManager
        checkpoint_manager = JobCheckpointManager(job_id)

        if checkpoint_manager.request_pause():
            return JobPauseResponse(
                success=True,
                message="Pause requested. Job will pause at next checkpoint.",
                job_id=job_id
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to request pause. Redis may be unavailable."
            )

    raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")


@router.get("/{job_id}/checkpoint", response_model=CheckpointInfoResponse)
def get_job_checkpoint(
    job_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get checkpoint information for a job.

    Returns checkpoint data, age, and whether a pause has been requested.
    Useful for monitoring job state and resume capabilities.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # Verify job exists in any table
    job_exists = (
        db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first() or
        db.query(JobState).filter(JobState.id == job_uuid).first() or
        db.query(ScanJob).filter(ScanJob.id == job_uuid).first() or
        db.query(LibraryImportJob).filter(LibraryImportJob.id == job_uuid).first()
    )

    if not job_exists:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    from app.services.job_checkpoint_manager import JobCheckpointManager
    checkpoint_manager = JobCheckpointManager(job_id)

    has_checkpoint = checkpoint_manager.has_checkpoint()
    checkpoint_data = checkpoint_manager.load_checkpoint() if has_checkpoint else None
    checkpoint_age = checkpoint_manager.get_checkpoint_age_seconds() if has_checkpoint else None
    pause_requested = checkpoint_manager.is_pause_requested()

    return CheckpointInfoResponse(
        job_id=job_id,
        has_checkpoint=has_checkpoint,
        checkpoint_data=checkpoint_data,
        checkpoint_age_seconds=checkpoint_age,
        pause_requested=pause_requested
    )


@router.post("/pause-all", response_model=BulkPauseResumeResponse)
def pause_all_jobs(
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Request all running jobs to pause at their next checkpoint.

    This is useful before system updates to safely stop all processing.
    Jobs will save their state before pausing, allowing resume after update.
    """
    from app.services.job_checkpoint_manager import JobCheckpointManager

    paused_job_ids = []
    errors = []

    # Pause all running FileOrganizationJobs
    running_file_org_jobs = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.status == FileOrgJobStatus.RUNNING
    ).all()

    for job in running_file_org_jobs:
        try:
            checkpoint_manager = JobCheckpointManager(str(job.id))
            if checkpoint_manager.request_pause():
                paused_job_ids.append(str(job.id))
            else:
                errors.append(f"Failed to request pause for job {job.id}")
        except Exception as e:
            errors.append(f"Error pausing job {job.id}: {str(e)}")

    # Pause all running JobState jobs
    running_jobs = db.query(JobState).filter(
        JobState.status == JobStatus.RUNNING
    ).all()

    for job in running_jobs:
        try:
            checkpoint_manager = JobCheckpointManager(str(job.id))
            if checkpoint_manager.request_pause():
                paused_job_ids.append(str(job.id))
            else:
                errors.append(f"Failed to request pause for job {job.id}")
        except Exception as e:
            errors.append(f"Error pausing job {job.id}: {str(e)}")

    success = len(errors) == 0
    message = f"Requested pause for {len(paused_job_ids)} job(s)"
    if errors:
        message += f" with {len(errors)} error(s)"

    return BulkPauseResumeResponse(
        success=success,
        message=message,
        jobs_affected=len(paused_job_ids),
        job_ids=paused_job_ids,
        errors=errors
    )


@router.post("/resume-all", response_model=BulkPauseResumeResponse)
def resume_all_jobs(
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Resume all paused jobs after a system update.

    Jobs will continue from their last checkpoint, preserving progress.
    This is useful after completing maintenance or updates.
    """
    from app.services.job_checkpoint_manager import JobCheckpointManager
    from app.tasks.organization_tasks import (
        fetch_metadata_task,
        validate_library_structure_task,
        organize_library_files_task,
        validate_mbid_task,
        validate_mbid_metadata_task,
        link_files_task,
        reindex_albums_task,
        verify_audio_task
    )

    resumed_job_ids = []
    errors = []

    # Resume all paused FileOrganizationJobs
    paused_file_org_jobs = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.status == FileOrgJobStatus.PAUSED
    ).all()

    for job in paused_file_org_jobs:
        try:
            # Clear any pause request
            checkpoint_manager = JobCheckpointManager(str(job.id))
            checkpoint_manager.clear_pause_request()

            # Dispatch appropriate task based on job type
            task_map = {
                FileOrgJobType.FETCH_METADATA: fetch_metadata_task,
                FileOrgJobType.VALIDATE_STRUCTURE: validate_library_structure_task,
                FileOrgJobType.ORGANIZE_LIBRARY: organize_library_files_task,
                FileOrgJobType.VALIDATE_MBID: validate_mbid_task,
                FileOrgJobType.VALIDATE_MBID_METADATA: validate_mbid_metadata_task,
                FileOrgJobType.LINK_FILES: link_files_task,
                FileOrgJobType.REINDEX_ALBUMS: reindex_albums_task,
                FileOrgJobType.VERIFY_AUDIO: verify_audio_task,
            }

            task = task_map.get(job.job_type)
            if task:
                result = task.delay(str(job.id))
                job.celery_task_id = result.id
                job.status = FileOrgJobStatus.PENDING
                job.current_action = f"Resuming {job.job_type.value} from checkpoint"
                db.commit()
                resumed_job_ids.append(str(job.id))
            else:
                errors.append(f"No task handler for job type {job.job_type.value} (job {job.id})")
        except Exception as e:
            errors.append(f"Error resuming job {job.id}: {str(e)}")

    # Resume all paused JobState jobs
    paused_jobs = db.query(JobState).filter(
        JobState.status == JobStatus.PAUSED
    ).all()

    for job in paused_jobs:
        try:
            checkpoint_manager = JobCheckpointManager(str(job.id))
            checkpoint_manager.clear_pause_request()

            job.status = JobStatus.PENDING
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            resumed_job_ids.append(str(job.id))
            # Note: Generic JobState jobs need specific task dispatching
            # This just changes status; caller may need to dispatch task
        except Exception as e:
            errors.append(f"Error resuming job {job.id}: {str(e)}")

    success = len(errors) == 0
    message = f"Resumed {len(resumed_job_ids)} job(s)"
    if errors:
        message += f" with {len(errors)} error(s)"

    return BulkPauseResumeResponse(
        success=success,
        message=message,
        jobs_affected=len(resumed_job_ids),
        job_ids=resumed_job_ids,
        errors=errors
    )


@router.post("/{job_id}/retry", response_model=JobRetryResponse)
def retry_job(
    job_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Retry a failed, cancelled, or stalled job

    Resets the job state and dispatches the appropriate Celery task.
    Works with both JobState and FileOrganizationJob entries.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # First try FileOrganizationJob (most common for retry)
    from app.models.file_organization_job import FileOrganizationJob, JobStatus as FOJobStatus, JobType as FOJobType
    from app.tasks.organization_tasks import (
        organize_library_files_task,
        organize_artist_files_task,
        organize_album_files_task,
        fetch_metadata_task,
        validate_mbid_task,
        validate_mbid_metadata_task,
        link_files_task,
        reindex_albums_task,
        verify_audio_task
    )
    from datetime import datetime, timezone

    fo_job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()

    if fo_job:
        # Check if job can be retried
        retryable_statuses = [FOJobStatus.FAILED, FOJobStatus.CANCELLED]
        if fo_job.status not in retryable_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry job in {fo_job.status} state. Only failed or cancelled jobs can be retried."
            )

        # Reset job state for retry
        fo_job.status = FOJobStatus.PENDING
        fo_job.error_message = None
        fo_job.started_at = None
        fo_job.completed_at = None
        fo_job.progress_percent = 0.0
        fo_job.files_processed = 0
        fo_job.files_renamed = 0
        fo_job.files_moved = 0
        fo_job.files_failed = 0
        fo_job.current_action = "Queued for retry"

        # Get options
        options = {
            'dry_run': fo_job.dry_run if hasattr(fo_job, 'dry_run') else False,
            'only_with_mbid': True,
            'only_unorganized': False,
            'create_metadata_files': True
        }

        # Dispatch appropriate task
        celery_result = None
        message = ""

        if fo_job.job_type == FOJobType.ORGANIZE_LIBRARY:
            celery_result = organize_library_files_task.delay(
                str(fo_job.id), str(fo_job.library_path_id), options
            )
            message = f'Organize library job retrying'

        elif fo_job.job_type == FOJobType.ORGANIZE_ARTIST:
            celery_result = organize_artist_files_task.delay(
                str(fo_job.id), str(fo_job.artist_id), options
            )
            message = f'Organize artist job retrying'

        elif fo_job.job_type == FOJobType.ORGANIZE_ALBUM:
            celery_result = organize_album_files_task.delay(
                str(fo_job.id), str(fo_job.album_id), options
            )
            message = f'Organize album job retrying'

        elif fo_job.job_type == FOJobType.FETCH_METADATA:
            celery_result = fetch_metadata_task.delay(str(fo_job.id))
            message = f'Fetch metadata job retrying'

        elif fo_job.job_type == FOJobType.VALIDATE_MBID:
            celery_result = validate_mbid_task.delay(
                str(fo_job.id), str(fo_job.library_path_id)
            )
            message = f'Validate MBID job retrying'

        elif fo_job.job_type == FOJobType.VALIDATE_MBID_METADATA:
            celery_result = validate_mbid_metadata_task.delay(
                str(fo_job.id)
            )
            message = f'Validate MBID metadata job retrying'

        elif fo_job.job_type == FOJobType.LINK_FILES:
            celery_result = link_files_task.delay(
                str(fo_job.id), str(fo_job.library_path_id)
            )
            message = f'Link files job retrying'

        elif fo_job.job_type == FOJobType.REINDEX_ALBUMS:
            celery_result = reindex_albums_task.delay(
                str(fo_job.id), str(fo_job.library_path_id)
            )
            message = f'Reindex albums job retrying'

        elif fo_job.job_type == FOJobType.VERIFY_AUDIO:
            celery_result = verify_audio_task.delay(
                str(fo_job.id), 7
            )
            message = f'Verify audio job retrying'

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Retry not supported for job type: {fo_job.job_type}"
            )

        if celery_result:
            fo_job.celery_task_id = celery_result.id
            db.commit()

            return JobRetryResponse(
                success=True,
                message=message,
                new_job_id=str(fo_job.id)
            )

    # Try JobState if not found in FileOrganizationJob
    job = db.query(JobState).filter(JobState.id == job_uuid).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Check if job can be retried
    if job.status not in [JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.STALLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry job in {job.status.value} state. Only failed, cancelled, or stalled jobs can be retried."
        )

    # Create new job with same parameters
    new_job = JobState(
        job_type=job.job_type,
        entity_type=job.entity_type,
        entity_id=job.entity_id,
        max_retries=job.max_retries,
        status=JobStatus.PENDING
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    # TODO: Dispatch task based on job_type for JobState jobs

    return JobRetryResponse(
        success=True,
        message=f"Job queued for retry",
        new_job_id=str(new_job.id)
    )


@router.delete("/{job_id}")
def delete_job(
    job_id: str,
    force: bool = Query(False, description="Force delete even if job is pending/running (for stale jobs)"),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Delete a completed, failed, or cancelled job from history

    Active jobs (pending, running, paused) must be cancelled before deletion,
    unless force=true is specified (for cleaning up stale/orphaned jobs).
    This permanently removes the job record from the database.
    Searches across all job types (JobState, FileOrganizationJob, ScanJob, LibraryImportJob).
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # Search JobState first
    job = db.query(JobState).filter(JobState.id == job_uuid).first()

    if job:
        # Prevent deletion of active jobs unless forced
        if job.is_active() and not force:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete active job in {job.status.value} state. Cancel the job first or use force=true for stale jobs."
            )

        # If forcing deletion of active job, try to revoke task first
        if job.is_active() and force and job.celery_task_id:
            try:
                celery_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
            except Exception as e:
                print(f"Error revoking Celery task during force delete: {e}")

        db.delete(job)
        db.commit()

        return {"success": True, "message": "Job deleted successfully", "forced": force}

    # Search FileOrganizationJob
    file_org_job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()

    if file_org_job:
        # Prevent deletion of active jobs unless forced
        active_statuses = [FileOrgJobStatus.PENDING, FileOrgJobStatus.RUNNING, FileOrgJobStatus.PAUSED]
        if file_org_job.status in active_statuses and not force:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete active job in {file_org_job.status.value} state. Cancel the job first or use force=true for stale jobs."
            )

        # If forcing deletion of active job, try to revoke task first
        if file_org_job.status in active_statuses and force and file_org_job.celery_task_id:
            try:
                celery_app.control.revoke(file_org_job.celery_task_id, terminate=True, signal='SIGTERM')
            except Exception as e:
                print(f"Error revoking Celery task during force delete: {e}")

        # Delete log file if it exists
        if file_org_job.log_file_path:
            from pathlib import Path
            log_path = Path(file_org_job.log_file_path)
            if log_path.exists():
                try:
                    log_path.unlink()
                except Exception as e:
                    print(f"Failed to delete log file: {e}")

        db.delete(file_org_job)
        db.commit()

        return {"success": True, "message": "Job deleted successfully", "forced": force}

    # Search ScanJob
    scan_job = db.query(ScanJob).filter(ScanJob.id == job_uuid).first()

    if scan_job:
        # Prevent deletion of active jobs unless forced
        if scan_job.status in ['pending', 'running', 'paused'] and not force:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete active job in {scan_job.status} state. Cancel the job first or use force=true for stale jobs."
            )

        # If forcing deletion of active job, try to revoke task first
        if scan_job.status in ['pending', 'running', 'paused'] and force and scan_job.celery_task_id:
            try:
                celery_app.control.revoke(scan_job.celery_task_id, terminate=True, signal='SIGTERM')
            except Exception as e:
                print(f"Error revoking Celery task during force delete: {e}")

        # Delete log file if it exists
        if scan_job.log_file_path:
            from pathlib import Path
            log_path = Path(scan_job.log_file_path)
            if log_path.exists():
                try:
                    log_path.unlink()
                except Exception as e:
                    print(f"Failed to delete log file: {e}")

        db.delete(scan_job)
        db.commit()

        return {"success": True, "message": "Job deleted successfully", "forced": force}

    # Search LibraryImportJob
    import_job = db.query(LibraryImportJob).filter(LibraryImportJob.id == job_uuid).first()

    if import_job:
        # Prevent deletion of active jobs unless forced
        if import_job.status in ['pending', 'running', 'paused'] and not force:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete active job in {import_job.status} state. Cancel the job first or use force=true for stale jobs."
            )

        # If forcing deletion of active job, try to revoke task first
        if import_job.status in ['pending', 'running', 'paused'] and force and import_job.celery_task_id:
            try:
                celery_app.control.revoke(import_job.celery_task_id, terminate=True, signal='SIGTERM')
            except Exception as e:
                print(f"Error revoking Celery task during force delete: {e}")

        # Delete log file if it exists
        if import_job.log_file_path:
            from pathlib import Path
            log_path = Path(import_job.log_file_path)
            if log_path.exists():
                try:
                    log_path.unlink()
                except Exception as e:
                    print(f"Failed to delete log file: {e}")

        db.delete(import_job)
        db.commit()

        return {"success": True, "message": "Job deleted successfully", "forced": force}

    raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")


@router.delete("")
def clear_job_history(
    include_active: bool = Query(False, description="Include active jobs (pending, running, paused)"),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Clear all job history from the database

    By default, only clears completed, failed, cancelled, and stalled jobs.
    Set include_active=true to also clear active jobs (will cancel them first).

    WARNING: This permanently deletes all job records from the database.
    """
    total_deleted = 0

    # Clear JobState jobs
    query = db.query(JobState)

    if include_active:
        # Cancel all active jobs first
        active_jobs = query.filter(
            JobState.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED])
        ).all()

        for job in active_jobs:
            # Revoke Celery task if it exists
            if job.celery_task_id:
                try:
                    celery_app.control.revoke(
                        job.celery_task_id,
                        terminate=True,
                        signal='SIGTERM'
                    )
                except Exception as e:
                    print(f"Error revoking Celery task {job.celery_task_id}: {e}")

            # Mark as cancelled
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = "Job cancelled during history clear"

        db.commit()

        # Delete all JobState jobs
        deleted_count = db.query(JobState).delete()
        total_deleted += deleted_count
    else:
        # Delete only terminal JobState jobs
        deleted_count = db.query(JobState).filter(
            JobState.status.in_([
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.STALLED
            ])
        ).delete()
        total_deleted += deleted_count

    # Clear FileOrganizationJob jobs
    file_org_query = db.query(FileOrganizationJob)

    if include_active:
        # Cancel active file organization jobs
        active_file_jobs = file_org_query.filter(
            FileOrganizationJob.status.in_([FileOrgJobStatus.PENDING, FileOrgJobStatus.RUNNING])
        ).all()

        for job in active_file_jobs:
            # Revoke Celery task if it exists
            if job.celery_task_id:
                try:
                    celery_app.control.revoke(
                        job.celery_task_id,
                        terminate=True,
                        signal='SIGTERM'
                    )
                except Exception as e:
                    print(f"Error revoking Celery task {job.celery_task_id}: {e}")

            # Delete log file if it exists
            if job.log_file_path:
                from pathlib import Path
                log_path = Path(job.log_file_path)
                if log_path.exists():
                    try:
                        log_path.unlink()
                    except Exception as e:
                        print(f"Failed to delete log file: {e}")

        # Delete all file organization jobs
        file_org_deleted = db.query(FileOrganizationJob).delete()
        total_deleted += file_org_deleted
    else:
        # Delete only completed/failed file organization jobs and cleanup log files
        terminal_file_jobs = file_org_query.filter(
            FileOrganizationJob.status.in_([FileOrgJobStatus.COMPLETED, FileOrgJobStatus.FAILED])
        ).all()

        for job in terminal_file_jobs:
            # Delete log file if it exists
            if job.log_file_path:
                from pathlib import Path
                log_path = Path(job.log_file_path)
                if log_path.exists():
                    try:
                        log_path.unlink()
                    except Exception as e:
                        print(f"Failed to delete log file: {e}")

            db.delete(job)

        file_org_deleted = len(terminal_file_jobs)
        total_deleted += file_org_deleted

    # Clear ScanJob jobs
    if include_active:
        # Cancel active scan jobs
        active_scans = db.query(ScanJob).filter(
            ScanJob.status.in_(['pending', 'running'])
        ).all()
        for job in active_scans:
            if job.celery_task_id:
                try:
                    celery_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
                except Exception as e:
                    print(f"Error revoking scan task {job.celery_task_id}: {e}")
            job.status = 'cancelled'
            job.completed_at = datetime.now(timezone.utc)
        db.commit()

        scan_deleted = db.query(ScanJob).delete()
        total_deleted += scan_deleted
    else:
        scan_deleted = db.query(ScanJob).filter(
            ScanJob.status.in_(['completed', 'failed', 'cancelled'])
        ).delete()
        total_deleted += scan_deleted

    # Clear LibraryImportJob jobs
    if include_active:
        active_imports = db.query(LibraryImportJob).filter(
            LibraryImportJob.status.in_(['pending', 'running', 'paused'])
        ).all()
        for job in active_imports:
            if job.celery_task_id:
                try:
                    celery_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
                except Exception as e:
                    print(f"Error revoking import task {job.celery_task_id}: {e}")
            job.status = 'cancelled'
            job.completed_at = datetime.now(timezone.utc)
        db.commit()

        import_deleted = db.query(LibraryImportJob).delete()
        total_deleted += import_deleted
    else:
        # LibraryImportJob has artist_matches FK — delete matches first
        terminal_imports = db.query(LibraryImportJob).filter(
            LibraryImportJob.status.in_(['completed', 'failed', 'cancelled'])
        ).all()
        for job in terminal_imports:
            # Delete log file if it exists
            if job.log_file_path:
                log_path = Path(job.log_file_path)
                if log_path.exists():
                    try:
                        log_path.unlink()
                    except Exception:
                        pass
            db.delete(job)  # cascade deletes artist_matches
        total_deleted += len(terminal_imports)

    db.commit()

    return {
        "success": True,
        "message": f"Cleared {total_deleted} job(s) from history",
        "deleted_count": total_deleted
    }


def _find_job_log_path(job_id: str, db: Session) -> tuple[Optional[str], str]:
    """
    Find log file path for a job by searching across all job types.

    Returns tuple of (log_file_path, job_type) or raises HTTPException if not found.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    # Search JobState first (most common)
    job = db.query(JobState).filter(JobState.id == job_uuid).first()
    if job:
        return job.log_file_path, job.job_type.value if isinstance(job.job_type, JobType) else job.job_type

    # Search FileOrganizationJob
    job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()
    if job:
        return job.log_file_path, "file_organization"

    # Search ScanJob
    job = db.query(ScanJob).filter(ScanJob.id == job_uuid).first()
    if job:
        return job.log_file_path, "scan"

    # Search LibraryImportJob
    job = db.query(LibraryImportJob).filter(LibraryImportJob.id == job_uuid).first()
    if job:
        return job.log_file_path, "import"

    raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")


@router.get("/{job_id}/log")
async def get_job_log(
    job_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Download the log file for any job type.

    Searches across all job types (JobState, FileOrganizationJob, ScanJob, LibraryImportJob)
    and returns the log file as a downloadable text file.
    """
    log_file_path, job_type = _find_job_log_path(job_id, db)

    if not log_file_path:
        raise HTTPException(
            status_code=404,
            detail=f"No log file available for job {job_id}"
        )

    log_path = Path(log_file_path)
    if not log_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Log file not found at {log_file_path}"
        )

    return FileResponse(
        path=str(log_path),
        filename=f"{job_type}_job_{job_id}.log",
        media_type="text/plain"
    )


@router.get("/{job_id}/log/content")
async def get_job_log_content(
    job_id: str,
    lines: int = Query(default=100, ge=1, le=10000, description="Number of lines to return"),
    offset: int = Query(default=0, ge=0, description="Line offset from start"),
    tail: bool = Query(default=False, description="Return lines from end of file instead of beginning"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get the log file content for any job type.

    Returns the log content as JSON for display in the UI.
    Supports pagination via offset and lines parameters.
    Use tail=true to get the most recent lines.
    """
    log_file_path, job_type = _find_job_log_path(job_id, db)

    if not log_file_path:
        return {
            "job_id": job_id,
            "job_type": job_type,
            "log_available": False,
            "content": "",
            "total_lines": 0
        }

    log_path = Path(log_file_path)
    if not log_path.exists():
        return {
            "job_id": job_id,
            "job_type": job_type,
            "log_available": False,
            "content": "",
            "total_lines": 0
        }

    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)

        if tail:
            # Return last N lines
            start_idx = max(0, total_lines - offset - lines)
            end_idx = max(0, total_lines - offset)
            selected_lines = all_lines[start_idx:end_idx]
        else:
            # Return from offset
            selected_lines = all_lines[offset:offset + lines]

        content = ''.join(selected_lines)

        return {
            "job_id": job_id,
            "job_type": job_type,
            "log_available": True,
            "content": content,
            "total_lines": total_lines,
            "lines_returned": len(selected_lines),
            "offset": offset,
            "tail": tail,
            "log_file_path": log_file_path
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading log file: {str(e)}"
        )


class LogCleanupRequest(BaseModel):
    """Request schema for log cleanup"""
    retention_days: int = Field(default=120, ge=1, le=365, description="Number of days to retain log files")


class LogCleanupResponse(BaseModel):
    """Response schema for log cleanup"""
    success: bool
    message: str
    task_id: Optional[str] = None
    retention_days: int


@router.post("/cleanup-logs", response_model=LogCleanupResponse)
async def cleanup_old_logs(
    request: LogCleanupRequest = LogCleanupRequest(),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Trigger manual cleanup of old job log files
    
    Deletes log files older than the specified retention period (default: 120 days).
    This task runs asynchronously and returns immediately.
    
    The cleanup process:
    1. Finds all completed/failed jobs older than retention period
    2. Deletes their log files from disk
    3. Clears log_file_path references in database
    4. Cleans up orphan log files not in database
    """
    from app.tasks.organization_tasks import cleanup_old_logs_task
    
    # Queue the cleanup task
    result = cleanup_old_logs_task.delay(request.retention_days)
    
    return LogCleanupResponse(
        success=True,
        message=f"Log cleanup task queued. Files older than {request.retention_days} days will be deleted.",
        task_id=result.id,
        retention_days=request.retention_days
    )


@router.get("/cleanup-logs/preview")
async def preview_log_cleanup(
    retention_days: int = Query(default=120, ge=1, le=365, description="Number of days to retain log files"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Preview what would be cleaned up by the log cleanup task
    
    Returns a summary of files that would be deleted without actually deleting them.
    """
    from datetime import timedelta
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    # Count jobs with log files that would be cleaned
    file_org_jobs_count = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.completed_at < cutoff_date,
        FileOrganizationJob.log_file_path.isnot(None),
        FileOrganizationJob.status.in_([FileOrgJobStatus.COMPLETED, FileOrgJobStatus.FAILED, FileOrgJobStatus.CANCELLED, FileOrgJobStatus.ROLLED_BACK])
    ).count()
    
    scan_jobs_count = db.query(ScanJob).filter(
        ScanJob.completed_at < cutoff_date,
        ScanJob.log_file_path.isnot(None),
        ScanJob.status.in_(['completed', 'failed', 'cancelled'])
    ).count()
    
    import_jobs_count = db.query(LibraryImportJob).filter(
        LibraryImportJob.completed_at < cutoff_date,
        LibraryImportJob.log_file_path.isnot(None),
        LibraryImportJob.status.in_(['completed', 'failed', 'cancelled'])
    ).count()
    
    # Count orphan log files
    log_dir = Path("/app/logs/jobs")
    orphan_count = 0
    estimated_size = 0
    
    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            try:
                file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
                if file_mtime < cutoff_date:
                    # Check if this is an orphan (not in database)
                    job_id_str = log_file.stem
                    try:
                        job_uuid = uuid.UUID(job_id_str)
                        
                        # Check if job exists in any table
                        exists = (
                            db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first() or
                            db.query(ScanJob).filter(ScanJob.id == job_uuid).first() or
                            db.query(LibraryImportJob).filter(LibraryImportJob.id == job_uuid).first() or
                            db.query(JobState).filter(JobState.id == job_uuid).first()
                        )
                        
                        if not exists:
                            orphan_count += 1
                            estimated_size += log_file.stat().st_size
                    except (ValueError, Exception):
                        pass
            except Exception:
                pass
    
    total_jobs = file_org_jobs_count + scan_jobs_count + import_jobs_count
    
    # Convert size to human-readable
    if estimated_size >= 1024 * 1024 * 1024:
        size_str = f"{estimated_size / (1024 * 1024 * 1024):.2f} GB"
    elif estimated_size >= 1024 * 1024:
        size_str = f"{estimated_size / (1024 * 1024):.2f} MB"
    elif estimated_size >= 1024:
        size_str = f"{estimated_size / 1024:.2f} KB"
    else:
        size_str = f"{estimated_size} bytes"
    
    return {
        "retention_days": retention_days,
        "cutoff_date": cutoff_date.isoformat(),
        "jobs_with_logs_to_clean": {
            "file_organization_jobs": file_org_jobs_count,
            "scan_jobs": scan_jobs_count,
            "import_jobs": import_jobs_count,
            "total": total_jobs
        },
        "orphan_log_files": orphan_count,
        "estimated_orphan_size": size_str,
        "estimated_orphan_size_bytes": estimated_size
    }
