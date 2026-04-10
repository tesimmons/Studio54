"""
Monitoring Tasks for Studio54

Periodic tasks for monitoring job health, detecting stalls, and cleaning up old jobs.
"""
from celery import shared_task
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, timedelta
import logging

from app.database import SessionLocal
from app.models.job_state import JobState, JobStatus
from app.models.file_organization_job import FileOrganizationJob, JobStatus as FileOrgJobStatus
from app.utils.db_retry import retry_db_commit

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.monitoring_tasks.detect_stalled_jobs")
def detect_stalled_jobs():
    """
    Detect and mark stalled jobs (no heartbeat for > 5 minutes)

    Runs every 2 minutes to check for jobs that:
    - Are in RUNNING status
    - Haven't sent heartbeat for > 5 minutes
    - Haven't completed

    Marks them as STALLED/FAILED for manual review/retry.
    Checks both JobState and FileOrganizationJob tables.
    """
    db: Session = SessionLocal()
    try:
        # Calculate stall thresholds
        # JobState jobs (sync, download): 15 minutes
        stall_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
        # FileOrganizationJob jobs (file I/O + MusicBrainz API per file): 10 minutes
        file_org_stall_threshold = datetime.now(timezone.utc) - timedelta(minutes=10)
        stalled_count = 0
        stalled_job_ids = []

        # === Check JobState table ===
        stalled_jobs = db.query(JobState).filter(
            and_(
                JobState.status == JobStatus.RUNNING,
                JobState.last_heartbeat_at < stall_threshold,
                JobState.last_heartbeat_at.isnot(None)  # Only jobs that ever sent a heartbeat
            )
        ).all()

        for job in stalled_jobs:
            # Mark as stalled
            job.status = JobStatus.STALLED
            job.updated_at = datetime.now(timezone.utc)

            # Add error message
            if job.last_heartbeat_at:
                stalled_duration = (datetime.now(timezone.utc) - job.last_heartbeat_at).total_seconds()
                job.error_message = f"Job stalled - no heartbeat for {stalled_duration:.0f} seconds (threshold: 900s)"
            else:
                job.error_message = "Job stalled - no heartbeat received"

            logger.warning(
                f"Marked JobState {job.id} ({job.job_type.value}) as STALLED - "
                f"last heartbeat: {job.last_heartbeat_at}"
            )
            stalled_job_ids.append(str(job.id))

        stalled_count += len(stalled_jobs)

        # === Check FileOrganizationJob table (longer threshold for file I/O + API calls) ===
        stalled_file_org_jobs = db.query(FileOrganizationJob).filter(
            and_(
                FileOrganizationJob.status == FileOrgJobStatus.RUNNING,
                FileOrganizationJob.last_heartbeat_at < file_org_stall_threshold,
                FileOrganizationJob.last_heartbeat_at.isnot(None)
            )
        ).all()

        for job in stalled_file_org_jobs:
            # Mark as failed (FileOrganizationJob doesn't have STALLED status)
            job.status = FileOrgJobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)

            # Add detailed error message
            stalled_duration = (datetime.now(timezone.utc) - job.last_heartbeat_at).total_seconds()
            current_file_info = f" while processing: {job.current_file_path}" if job.current_file_path else ""
            job.error_message = (
                f"Job stalled - no heartbeat for {stalled_duration:.0f} seconds{current_file_info}. "
                f"Progress: {job.files_processed}/{job.files_total} files ({job.progress_percent:.1f}%). "
                f"Job is resumable - restart to continue from where it left off."
            )

            logger.warning(
                f"Marked FileOrganizationJob {job.id} ({job.job_type.value}) as FAILED (stalled) - "
                f"last heartbeat: {job.last_heartbeat_at}, "
                f"current file: {job.current_file_path}, "
                f"progress: {job.files_processed}/{job.files_total}"
            )
            stalled_job_ids.append(str(job.id))

        stalled_count += len(stalled_file_org_jobs)

        # === Check for JobState running jobs with NO heartbeat (crashed before first heartbeat) ===
        old_running_jobstate_jobs = db.query(JobState).filter(
            and_(
                JobState.status == JobStatus.RUNNING,
                JobState.last_heartbeat_at.is_(None),
                JobState.started_at < stall_threshold  # Started > 15 min ago with no heartbeat
            )
        ).all()

        for job in old_running_jobstate_jobs:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            job.error_message = (
                "Job failed - no heartbeat received since start. "
                "The task likely crashed during initialization."
            )
            logger.warning(
                f"Marked JobState {job.id} ({job.job_type.value}) as FAILED (no heartbeat since start)"
            )
            stalled_job_ids.append(str(job.id))

        stalled_count += len(old_running_jobstate_jobs)

        # === Also check for running FileOrganizationJob with NO heartbeat ===
        old_running_jobs = db.query(FileOrganizationJob).filter(
            and_(
                FileOrganizationJob.status == FileOrgJobStatus.RUNNING,
                FileOrganizationJob.last_heartbeat_at.is_(None),
                FileOrganizationJob.started_at < file_org_stall_threshold  # Started > 10 min ago with no heartbeat
            )
        ).all()

        for job in old_running_jobs:
            job.status = FileOrgJobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = (
                f"Job stalled - no heartbeat received since start. "
                f"Progress: {job.files_processed}/{job.files_total} files. "
                f"Job is resumable - restart to continue."
            )
            logger.warning(f"Marked FileOrganizationJob {job.id} as FAILED (no heartbeat since start)")
            stalled_job_ids.append(str(job.id))

        stalled_count += len(old_running_jobs)

        if stalled_count > 0:
            logger.warning(f"Total stalled jobs detected: {stalled_count}")

            # Send notification for stalled jobs
            try:
                from app.services.notification_service import send_notification
                send_notification("job_failed", {
                    "message": f"{stalled_count} job(s) detected as stalled/failed",
                    "stalled_count": stalled_count,
                    "stalled_job_ids": stalled_job_ids[:10],  # Limit payload size
                })
            except Exception as e:
                logger.debug(f"Notification send failed: {e}")

        retry_db_commit(db)

        return {
            "stalled_jobs_detected": stalled_count,
            "stalled_job_ids": stalled_job_ids
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error detecting stalled jobs: {e}")
        raise
    finally:
        db.close()


@shared_task(name="app.tasks.monitoring_tasks.cleanup_old_jobs")
def cleanup_old_jobs(days_to_keep: int = 30):
    """
    Clean up completed/failed jobs older than specified days

    Args:
        days_to_keep: Number of days to retain job history (default: 30)

    Returns:
        dict: Cleanup summary
    """
    db: Session = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        # Find old completed/failed/cancelled jobs
        old_jobs = db.query(JobState).filter(
            and_(
                JobState.completed_at < cutoff_date,
                JobState.status.in_([
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED
                ])
            )
        ).all()

        deleted_count = len(old_jobs)

        if deleted_count > 0:
            logger.info(f"Cleaning up {deleted_count} old jobs (older than {days_to_keep} days)")

        for job in old_jobs:
            db.delete(job)

        retry_db_commit(db)

        return {
            "jobs_deleted": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "days_kept": days_to_keep
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error cleaning up old jobs: {e}")
        raise
    finally:
        db.close()


@shared_task(name="app.tasks.monitoring_tasks.cleanup_old_downloads")
def cleanup_old_downloads(days_to_keep: int = 30):
    """
    Clean up completed/failed download queue records older than specified days.

    - COMPLETED downloads: always deleted after cutoff
    - FAILED downloads: only deleted if the album is NOT in WANTED status
      (preserves attempted_nzb_guids dedup history for albums still being searched)
    - Never touches QUEUED, DOWNLOADING, POST_PROCESSING, or IMPORTING rows

    Args:
        days_to_keep: Number of days to retain download history (default: 30)

    Returns:
        dict: Cleanup summary
    """
    from app.models.download_queue import DownloadQueue, DownloadStatus
    from app.models.album import Album, AlbumStatus

    db: Session = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        # Delete old COMPLETED downloads
        completed_query = db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.status == DownloadStatus.COMPLETED,
                DownloadQueue.completed_at < cutoff_date
            )
        )
        completed_count = completed_query.count()
        if completed_count > 0:
            completed_query.delete(synchronize_session='fetch')

        # Delete old FAILED downloads only if album is no longer WANTED
        # This preserves attempted_nzb_guids for albums still being searched
        failed_downloads = db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.status == DownloadStatus.FAILED,
                DownloadQueue.completed_at < cutoff_date
            )
        ).all()

        failed_count = 0
        for download in failed_downloads:
            album = db.query(Album).filter(Album.id == download.album_id).first()
            if not album or album.status != AlbumStatus.WANTED:
                db.delete(download)
                failed_count += 1

        total_deleted = completed_count + failed_count
        if total_deleted > 0:
            logger.info(
                f"Cleaned up {total_deleted} old downloads "
                f"({completed_count} completed, {failed_count} failed, "
                f"older than {days_to_keep} days)"
            )

        retry_db_commit(db)

        return {
            "downloads_deleted": total_deleted,
            "completed_deleted": completed_count,
            "failed_deleted": failed_count,
            "cutoff_date": cutoff_date.isoformat(),
            "days_kept": days_to_keep
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error cleaning up old downloads: {e}")
        raise
    finally:
        db.close()


@shared_task(name="app.tasks.monitoring_tasks.check_worker_autoscale")
def check_worker_autoscale():
    """
    Check worker load and auto-scale up/down if enabled.

    Runs every 60 seconds via beat.
    - Scale up: all workers at 8 tasks for 5+ minutes
    - Scale down: any worker idle for 10+ minutes and count > 1
    """
    try:
        from app.services.worker_autoscaler import check_and_scale
        result = check_and_scale()
        if result.get("action") not in ("disabled", "no_change", "no_workers"):
            logger.info(f"Worker autoscale: {result}")
        return result
    except Exception as e:
        logger.error(f"Worker autoscale check failed: {e}")
        return {"action": "error", "error": str(e)}


@shared_task(name="app.tasks.monitoring_tasks.get_job_stats")
def get_job_stats():
    """
    Calculate and log job statistics

    Returns:
        dict: Job statistics by status and type
    """
    db: Session = SessionLocal()
    try:
        from sqlalchemy import func

        # Count by status
        status_counts = {}
        for status in JobStatus:
            count = db.query(JobState).filter(JobState.status == status).count()
            status_counts[status.value] = count

        # Count by type
        type_counts = {}
        from app.models.job_state import JobType
        for job_type in JobType:
            count = db.query(JobState).filter(JobState.job_type == job_type).count()
            type_counts[job_type.value] = count

        # Active jobs (running/pending/retrying)
        active_count = db.query(JobState).filter(
            JobState.status.in_([JobStatus.RUNNING, JobStatus.PENDING, JobStatus.RETRYING])
        ).count()

        # Average completion time for completed jobs (last 24 hours)
        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        completed_jobs = db.query(JobState).filter(
            and_(
                JobState.status == JobStatus.COMPLETED,
                JobState.completed_at >= yesterday,
                JobState.started_at.isnot(None),
                JobState.completed_at.isnot(None)
            )
        ).all()

        avg_duration = None
        if completed_jobs:
            durations = [
                (job.completed_at - job.started_at).total_seconds()
                for job in completed_jobs
                if job.completed_at and job.started_at
            ]
            if durations:
                avg_duration = sum(durations) / len(durations)

        stats = {
            "status_counts": status_counts,
            "type_counts": type_counts,
            "active_jobs": active_count,
            "completed_last_24h": len(completed_jobs),
            "avg_completion_time_seconds": avg_duration
        }

        logger.info(f"Job stats: {active_count} active, {len(completed_jobs)} completed in last 24h")

        return stats

    except Exception as e:
        logger.error(f"Error getting job stats: {e}")
        raise
    finally:
        db.close()


@shared_task(name="app.tasks.monitoring_tasks.check_scheduled_jobs")
def check_scheduled_jobs():
    """
    Check for scheduled jobs that are due and dispatch them.

    Runs every 5 minutes via beat schedule. Queries scheduled_jobs where
    enabled=True and next_run_at <= now(), dispatches the task, and
    updates last_run_at / next_run_at.
    """
    from app.models.scheduled_job import ScheduledJob
    from app.services.task_registry import dispatch_scheduled_task, calculate_next_run

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        due_jobs = db.query(ScheduledJob).filter(
            ScheduledJob.enabled == True,
            ScheduledJob.next_run_at <= now
        ).all()

        if not due_jobs:
            return {"dispatched": 0}

        dispatched_count = 0
        for scheduled_job in due_jobs:
            try:
                logger.info(f"Dispatching scheduled job: {scheduled_job.name} (task={scheduled_job.task_key})")

                task_id = dispatch_scheduled_task(
                    scheduled_job.task_key,
                    scheduled_job.task_params
                )

                if task_id:
                    import uuid as uuid_mod
                    try:
                        scheduled_job.last_job_id = uuid_mod.UUID(task_id)
                    except (ValueError, AttributeError):
                        scheduled_job.last_job_id = None

                    scheduled_job.last_run_at = now
                    scheduled_job.last_status = "dispatched"
                    scheduled_job.next_run_at = calculate_next_run(
                        frequency=scheduled_job.frequency,
                        run_at_hour=scheduled_job.run_at_hour,
                        day_of_week=scheduled_job.day_of_week,
                        day_of_month=scheduled_job.day_of_month,
                        from_time=now
                    )
                    dispatched_count += 1
                    logger.info(
                        f"Dispatched {scheduled_job.name}, next run: {scheduled_job.next_run_at}"
                    )
                else:
                    scheduled_job.last_status = "dispatch_failed"
                    logger.error(f"Failed to dispatch scheduled job: {scheduled_job.name}")

            except Exception as e:
                scheduled_job.last_status = f"error: {str(e)[:200]}"
                logger.error(f"Error dispatching scheduled job {scheduled_job.name}: {e}")

        retry_db_commit(db)
        logger.info(f"Scheduled job check complete: {dispatched_count}/{len(due_jobs)} dispatched")

        return {"dispatched": dispatched_count, "due": len(due_jobs)}

    except Exception as e:
        db.rollback()
        logger.error(f"Error checking scheduled jobs: {e}")
        raise
    finally:
        db.close()
