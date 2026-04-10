"""
Scheduler API — CRUD for user-configurable scheduled jobs.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime, timezone
import logging

from app.database import get_db
from app.security import rate_limit, validate_uuid
from app.auth import require_director, require_any_user
from app.models.user import User
from app.models.scheduled_job import ScheduledJob
from app.services.task_registry import SCHEDULABLE_TASKS, dispatch_scheduled_task, calculate_next_run

router = APIRouter()
logger = logging.getLogger(__name__)


# ========================================
# Schemas
# ========================================

class SchedulableTaskInfo(BaseModel):
    key: str
    name: str
    description: str
    category: str
    params: List[Dict[str, Any]]


class ScheduledJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    task_key: str = Field(..., min_length=1, max_length=255)
    frequency: str = Field(..., pattern="^(daily|weekly|monthly|quarterly)$")
    enabled: bool = True
    run_at_hour: int = Field(2, ge=0, le=23)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    task_params: Optional[Dict[str, Any]] = None


class ScheduledJobUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    frequency: Optional[str] = Field(None, pattern="^(daily|weekly|monthly|quarterly)$")
    enabled: Optional[bool] = None
    run_at_hour: Optional[int] = Field(None, ge=0, le=23)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    task_params: Optional[Dict[str, Any]] = None


class ScheduledJobResponse(BaseModel):
    id: str
    name: str
    task_key: str
    task_name: str
    frequency: str
    enabled: bool
    run_at_hour: int
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    task_params: Optional[Dict[str, Any]] = None
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_job_id: Optional[str] = None
    last_status: Optional[str] = None
    created_at: Optional[str] = None


def _job_to_response(job: ScheduledJob) -> ScheduledJobResponse:
    task_info = SCHEDULABLE_TASKS.get(job.task_key, {})
    return ScheduledJobResponse(
        id=str(job.id),
        name=job.name,
        task_key=job.task_key,
        task_name=task_info.get("name", job.task_key),
        frequency=job.frequency,
        enabled=job.enabled,
        run_at_hour=job.run_at_hour or 2,
        day_of_week=job.day_of_week,
        day_of_month=job.day_of_month,
        task_params=job.task_params,
        last_run_at=job.last_run_at.isoformat() if job.last_run_at else None,
        next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
        last_job_id=str(job.last_job_id) if job.last_job_id else None,
        last_status=job.last_status,
        created_at=job.created_at.isoformat() if job.created_at else None,
    )


# ========================================
# Endpoints
# ========================================

@router.get("/scheduler/tasks", response_model=List[SchedulableTaskInfo])
@rate_limit("30/minute")
def list_schedulable_tasks(
    request: Request,
    current_user: User = Depends(require_any_user),
):
    """List all available tasks that can be scheduled."""
    return [
        SchedulableTaskInfo(
            key=key,
            name=info["name"],
            description=info["description"],
            category=info["category"],
            params=info["params"],
        )
        for key, info in SCHEDULABLE_TASKS.items()
    ]


@router.get("/scheduler/jobs", response_model=List[ScheduledJobResponse])
@rate_limit("30/minute")
def list_scheduled_jobs(
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """List all scheduled jobs."""
    jobs = db.query(ScheduledJob).order_by(ScheduledJob.created_at).all()
    return [_job_to_response(j) for j in jobs]


@router.post("/scheduler/jobs", response_model=ScheduledJobResponse, status_code=201)
@rate_limit("10/minute")
def create_scheduled_job(
    data: ScheduledJobCreate,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Create a new scheduled job."""
    if data.task_key not in SCHEDULABLE_TASKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown task key: {data.task_key}. Available: {list(SCHEDULABLE_TASKS.keys())}"
        )

    next_run = calculate_next_run(
        frequency=data.frequency,
        run_at_hour=data.run_at_hour,
        day_of_week=data.day_of_week,
        day_of_month=data.day_of_month,
    )

    job = ScheduledJob(
        name=data.name,
        task_key=data.task_key,
        frequency=data.frequency,
        enabled=data.enabled,
        run_at_hour=data.run_at_hour,
        day_of_week=data.day_of_week,
        day_of_month=data.day_of_month,
        task_params=data.task_params,
        next_run_at=next_run if data.enabled else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Created scheduled job: {job.name} ({job.task_key}, {job.frequency}, next={next_run})")
    return _job_to_response(job)


@router.put("/scheduler/jobs/{job_id}", response_model=ScheduledJobResponse)
@rate_limit("10/minute")
def update_scheduled_job(
    job_id: UUID,
    data: ScheduledJobUpdate,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Update a scheduled job."""
    validate_uuid(str(job_id), "job_id")

    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    if data.name is not None:
        job.name = data.name
    if data.frequency is not None:
        job.frequency = data.frequency
    if data.enabled is not None:
        job.enabled = data.enabled
    if data.run_at_hour is not None:
        job.run_at_hour = data.run_at_hour
    if data.day_of_week is not None:
        job.day_of_week = data.day_of_week
    if data.day_of_month is not None:
        job.day_of_month = data.day_of_month
    if data.task_params is not None:
        job.task_params = data.task_params

    # Recalculate next_run_at
    if job.enabled:
        job.next_run_at = calculate_next_run(
            frequency=job.frequency,
            run_at_hour=job.run_at_hour,
            day_of_week=job.day_of_week,
            day_of_month=job.day_of_month,
        )
    else:
        job.next_run_at = None

    db.commit()
    db.refresh(job)

    logger.info(f"Updated scheduled job: {job.name} (enabled={job.enabled}, next={job.next_run_at})")
    return _job_to_response(job)


@router.delete("/scheduler/jobs/{job_id}", status_code=204)
@rate_limit("10/minute")
def delete_scheduled_job(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Delete a scheduled job."""
    validate_uuid(str(job_id), "job_id")

    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    db.delete(job)
    db.commit()

    logger.info(f"Deleted scheduled job: {job.name}")


@router.post("/scheduler/jobs/{job_id}/run-now", response_model=Dict[str, Any])
@rate_limit("10/minute")
def run_scheduled_job_now(
    job_id: UUID,
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Trigger an immediate run of a scheduled job."""
    validate_uuid(str(job_id), "job_id")

    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    task_id = dispatch_scheduled_task(job.task_key, job.task_params)

    if not task_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to dispatch task: {job.task_key}"
        )

    now = datetime.now(timezone.utc)
    job.last_run_at = now
    job.last_status = "dispatched (manual)"

    import uuid as uuid_mod
    try:
        job.last_job_id = uuid_mod.UUID(task_id)
    except (ValueError, AttributeError):
        job.last_job_id = None

    db.commit()

    logger.info(f"Manually triggered scheduled job: {job.name}")
    return {"message": f"Task '{job.name}' dispatched", "task_id": task_id}
