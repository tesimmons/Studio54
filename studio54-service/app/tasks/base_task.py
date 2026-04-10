"""
Base Task Classes for Job State Tracking

Provides automatic job state management, progress tracking, heartbeat monitoring,
and pause/resume capabilities for all Celery tasks.
"""
from celery import Task
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import traceback
import uuid
from typing import Optional, Dict, Any

import logging

from app.database import SessionLocal
from app.models.job_state import JobState, JobStatus, JobType
from app.tasks.celery_app import celery_app
from app.shared_services.job_logger import JobLogger
from app.utils.db_retry import retry_db_commit

logger = logging.getLogger(__name__)


class JobTrackedTask(Task):
    """
    Base task class that tracks job state in database

    Features:
    - Automatic job state creation and updates
    - Progress tracking with ETA calculations
    - Heartbeat monitoring (last_heartbeat_at)
    - Checkpoint/resume support for long-running tasks
    - Pause/cancel detection
    - Error tracking with stack traces
    - Comprehensive job logging
    """

    def __init__(self):
        super().__init__()
        self.db: Optional[Session] = None
        self.job: Optional[JobState] = None
        self.job_logger: Optional[JobLogger] = None

    def init_job_logger(self, job_type: str, job_name: str) -> JobLogger:
        """
        Initialize job logger for comprehensive activity logging

        Args:
            job_type: Type of job (e.g., 'sync', 'scan', 'import', 'download')
            job_name: Human-readable job name for the log header

        Returns:
            JobLogger instance
        """
        if self.job:
            job_id = str(self.job.id)
        else:
            job_id = str(uuid.uuid4())

        self.job_logger = JobLogger(job_type=job_type, job_id=job_id)
        self.job_logger.log_job_start(job_type, job_name)

        # Save log file path to job state
        if self.job and self.db:
            try:
                if not self.db.object_session(self.job):
                    self.job = self.db.merge(self.job)
                self.job.log_file_path = str(self.job_logger.log_file_path)
                self.db.commit()
                self.db.refresh(self.job)
            except Exception as e:
                logger.error(f"[JobTrackedTask] Error saving log file path: {e}", exc_info=True)
                try:
                    self.db.rollback()
                except Exception:
                    pass

        return self.job_logger

    def complete_job_logger(self, success: bool = True, error: Optional[str] = None):
        """
        Complete the job logger and finalize the log file

        Args:
            success: Whether the job completed successfully
            error: Optional error message if job failed
        """
        if self.job_logger:
            if error:
                self.job_logger.log_error(error)
            self.job_logger.log_job_complete()
            self.job_logger = None

    def before_start(self, task_id, args, kwargs):
        """Initialize job state before task execution"""
        import time
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, DisconnectionError, IntegrityError
        for _attempt in range(3):
            try:
                self.db = SessionLocal()
                self.db.execute(text("SELECT 1"))
                break
            except (OperationalError, DisconnectionError) as e:
                if _attempt < 2:
                    logger.warning(f"[JobTrackedTask] DB connect failed (attempt {_attempt + 1}/3): {e}")
                    time.sleep(2 ** _attempt)
                else:
                    raise

        # Get or create job state
        job_id = kwargs.get('job_id')
        if job_id:
            try:
                self.job = self.db.query(JobState).filter(JobState.id == uuid.UUID(job_id)).first()
            except (ValueError, AttributeError):
                self.job = None

        # Also check for existing job by celery_task_id (handles Celery re-delivery)
        if not self.job:
            self.job = self.db.query(JobState).filter(
                JobState.celery_task_id == task_id
            ).first()

        if not self.job:
            # Create new job if not exists
            self.job = JobState(
                celery_task_id=task_id,
                job_type=kwargs.get('job_type', JobType.ARTIST_SYNC),  # Default, should be overridden
                entity_type=kwargs.get('entity_type'),
                entity_id=kwargs.get('entity_id'),
                status=JobStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
                worker_id=self.request.hostname if hasattr(self, 'request') else None
            )
            self.db.add(self.job)
        else:
            # Update existing job (re-delivery or resume)
            self.job.celery_task_id = task_id
            self.job.status = JobStatus.RUNNING
            self.job.started_at = datetime.now(timezone.utc)
            self.job.worker_id = self.request.hostname if hasattr(self, 'request') else None

        # CRITICAL: Store job ID BEFORE commit to avoid DetachedInstanceError
        job_id_before_commit = None
        try:
            if hasattr(self.job, 'id'):
                job_id_before_commit = self.job.__dict__.get('id') or self.job.id
        except Exception:
            pass

        try:
            retry_db_commit(self.db)
        except IntegrityError:
            # Handle duplicate celery_task_id (Celery re-delivery race condition)
            self.db.rollback()
            self.job = self.db.query(JobState).filter(
                JobState.celery_task_id == task_id
            ).first()
            if self.job:
                self.job.status = JobStatus.RUNNING
                self.job.started_at = datetime.now(timezone.utc)
                self.job.worker_id = self.request.hostname if hasattr(self, 'request') else None
                retry_db_commit(self.db)
                job_id_before_commit = self.job.id
            else:
                logger.error(f"[JobTrackedTask] IntegrityError but no existing job for task {task_id}")
                return

        # Always re-query the job to get a fresh object attached to this worker's session
        if job_id_before_commit:
            self.job = self.db.query(JobState).filter(JobState.id == job_id_before_commit).first()
            if not self.job:
                logger.warning(f"[JobTrackedTask] Job {job_id_before_commit} not found after commit, recreating")
                self.job = JobState(
                    id=job_id_before_commit,
                    celery_task_id=task_id,
                    job_type=kwargs.get('job_type', JobType.ARTIST_SYNC),
                    entity_type=kwargs.get('entity_type'),
                    entity_id=kwargs.get('entity_id'),
                    status=JobStatus.RUNNING,
                    started_at=datetime.now(timezone.utc),
                    worker_id=self.request.hostname if hasattr(self, 'request') else None
                )
                self.db.add(self.job)
                retry_db_commit(self.db)
                self.job = self.db.query(JobState).filter(JobState.id == job_id_before_commit).first()
        else:
            self.job = self.db.query(JobState).filter(
                JobState.celery_task_id == task_id
            ).first()
            if not self.job:
                logger.error(f"[JobTrackedTask] Cannot find job by task_id {task_id}")

    def update_progress(
        self,
        percent: Optional[float] = None,
        step: Optional[str] = None,
        items_processed: Optional[int] = None,
        items_total: Optional[int] = None
    ):
        """
        Update job progress and send heartbeat

        Args:
            percent: Progress percentage (0-100)
            step: Current step description
            items_processed: Number of items processed
            items_total: Total number of items
        """
        if not self.job or not self.db:
            return

        try:
            # Re-attach job to session if detached
            if self.job and not self.db.object_session(self.job):
                self.job = self.db.merge(self.job)

            if percent is not None:
                self.job.progress_percent = max(0.0, min(100.0, percent))
            if step is not None:
                self.job.current_step = step[:500]  # Truncate to field length
            if items_processed is not None:
                self.job.items_processed = items_processed
            if items_total is not None:
                self.job.items_total = items_total

            # Update heartbeat
            self.job.last_heartbeat_at = datetime.now(timezone.utc)
            self.job.updated_at = datetime.now(timezone.utc)

            # Calculate ETA if we have enough data
            if items_processed and items_total and items_processed > 0 and self.job.started_at:
                elapsed = (datetime.now(timezone.utc) - self.job.started_at).total_seconds()
                if elapsed > 0:
                    speed = items_processed / elapsed
                    remaining = items_total - items_processed
                    if speed > 0 and remaining > 0:
                        self.job.eta_seconds = int(remaining / speed)
                        self.job.speed_metric = speed

            self.db.commit()
            self.db.refresh(self.job)
        except Exception as e:
            logger.error(f"[JobTrackedTask] Error updating progress: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass

    def save_checkpoint(self, checkpoint_data: Dict[str, Any]):
        """
        Save checkpoint data for task resumption

        Args:
            checkpoint_data: Dictionary containing state for resuming the task
        """
        if not self.job or not self.db:
            return

        try:
            # Re-attach job to session if detached
            if self.job and not self.db.object_session(self.job):
                self.job = self.db.merge(self.job)

            self.job.checkpoint_data = checkpoint_data
            self.job.updated_at = datetime.now(timezone.utc)

            self.db.commit()
            self.db.refresh(self.job)
        except Exception as e:
            logger.error(f"[JobTrackedTask] Error saving checkpoint: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass

    def get_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Get checkpoint data for resuming task

        Returns:
            Checkpoint dictionary or None
        """
        if not self.job:
            return None

        return self.job.checkpoint_data

    def check_should_pause(self) -> bool:
        """
        Check if job should pause (status changed to PAUSED by external request)

        Returns:
            True if task should pause, False otherwise
        """
        if not self.job or not self.db:
            return False

        try:
            self.db.refresh(self.job)
            return self.job.status == JobStatus.PAUSED
        except Exception:
            return False

    def check_should_cancel(self) -> bool:
        """
        Check if job should cancel (status changed to CANCELLED by external request)

        Returns:
            True if task should cancel, False otherwise
        """
        if not self.job or not self.db:
            return False

        try:
            self.db.refresh(self.job)
            return self.job.status == JobStatus.CANCELLED
        except Exception:
            return False

    def on_success(self, retval, task_id, args, kwargs):
        """Mark job as completed on success"""
        # Complete job logger if initialized
        if self.job_logger:
            self.complete_job_logger(success=True)

        if self.job and self.db:
            try:
                # Re-attach job to session if detached
                if self.job and not self.db.object_session(self.job):
                    self.job = self.db.merge(self.job)

                self.job.status = JobStatus.COMPLETED
                self.job.progress_percent = 100.0
                self.job.completed_at = datetime.now(timezone.utc)
                self.job.updated_at = datetime.now(timezone.utc)

                # Store result if it's a dictionary
                if isinstance(retval, dict):
                    self.job.result_data = retval
                else:
                    self.job.result_data = {"result": str(retval)}

                self.db.commit()
            except Exception as e:
                logger.error(f"[JobTrackedTask] Error marking job as completed: {e}")
                try:
                    self.db.rollback()
                except Exception:
                    pass

        if self.db:
            self.db.close()

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Mark job as failed on exception"""
        # Complete job logger if initialized (with error)
        if self.job_logger:
            self.complete_job_logger(success=False, error=str(exc))

        if self.job and self.db:
            try:
                # Re-attach job to session if detached
                if self.job and not self.db.object_session(self.job):
                    self.job = self.db.merge(self.job)

                self.job.status = JobStatus.FAILED
                self.job.completed_at = datetime.now(timezone.utc)
                self.job.updated_at = datetime.now(timezone.utc)
                self.job.error_message = str(exc)[:2000]  # Truncate to field length
                self.job.error_traceback = traceback.format_exc()[:10000]  # Truncate to field length

                self.db.commit()
            except Exception as e:
                logger.error(f"[JobTrackedTask] Error marking job as failed: {e}")
                self.db.rollback()

        if self.db:
            self.db.close()

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Update retry count on retry"""
        if self.job and self.db:
            try:
                self.job.status = JobStatus.RETRYING
                self.job.retry_count += 1
                self.job.updated_at = datetime.now(timezone.utc)
                self.job.error_message = f"Retry {self.job.retry_count}/{self.job.max_retries}: {str(exc)}"[:2000]

                self.db.commit()
            except Exception as e:
                logger.error(f"[JobTrackedTask] Error updating retry count: {e}")
                self.db.rollback()

        # Don't close DB on retry - task will continue

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        """Cleanup after task completes (success or failure)"""
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass
