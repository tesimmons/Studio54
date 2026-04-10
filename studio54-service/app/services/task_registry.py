"""
Task Registry — Maps schedulable task keys to metadata and dispatch functions.

Used by the scheduler to discover available tasks and dispatch them.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


SCHEDULABLE_TASKS = {
    "sync_all_albums": {
        "name": "Sync All Albums",
        "description": "Sync albums and tracks for all artists from MusicBrainz",
        "category": "sync",
        "params": [],
    },
    "sync_all_artists": {
        "name": "Sync All Artists",
        "description": "Sync new releases for all monitored artists",
        "category": "sync",
        "params": [],
    },
    "search_wanted_albums": {
        "name": "Search Wanted Albums",
        "description": "Search indexers for wanted albums",
        "category": "search",
        "params": [{"key": "limit", "type": "int", "default": 10, "label": "Max albums to search"}],
    },
    "search_cutoff_unmet": {
        "name": "Search Quality Upgrades",
        "description": "Search for quality upgrades on existing albums",
        "category": "search",
        "params": [{"key": "limit", "type": "int", "default": 5, "label": "Max albums"}],
    },
    "validate_file_links": {
        "name": "Validate File Links",
        "description": "Check that all linked track files still exist on disk",
        "category": "organization",
        "params": [],
    },
    "cleanup_old_jobs": {
        "name": "Cleanup Old Jobs",
        "description": "Delete completed/failed jobs older than N days",
        "category": "maintenance",
        "params": [{"key": "days_to_keep", "type": "int", "default": 30, "label": "Days to keep"}],
    },
    "cleanup_old_downloads": {
        "name": "Cleanup Old Downloads",
        "description": "Delete old download records",
        "category": "maintenance",
        "params": [{"key": "days_to_keep", "type": "int", "default": 30, "label": "Days to keep"}],
    },
    "cleanup_old_logs": {
        "name": "Cleanup Old Logs",
        "description": "Delete log files older than N days",
        "category": "maintenance",
        "params": [{"key": "retention_days", "type": "int", "default": 120, "label": "Retention days"}],
    },
    "fetch_missing_images": {
        "name": "Fetch Missing Images",
        "description": "Fetch missing album art and artist images",
        "category": "organization",
        "params": [],
    },
}


def dispatch_scheduled_task(task_key: str, task_params: Optional[dict] = None) -> Optional[str]:
    """
    Dispatch a scheduled task by key.

    Returns the Celery task ID or job ID if dispatched, None if task_key is unknown.
    """
    params = task_params or {}

    if task_key == "sync_all_albums":
        from app.tasks.sync_tasks import sync_all_albums
        result = sync_all_albums.delay()
        return result.id

    elif task_key == "sync_all_artists":
        from app.tasks.sync_tasks import sync_all_artists
        result = sync_all_artists.delay()
        return result.id

    elif task_key == "search_wanted_albums":
        from app.tasks.search_tasks import search_wanted_albums_v2
        limit = params.get("limit", 10)
        result = search_wanted_albums_v2.delay(limit)
        return result.id

    elif task_key == "search_cutoff_unmet":
        from app.tasks.search_tasks import search_cutoff_unmet
        limit = params.get("limit", 5)
        result = search_cutoff_unmet.delay(limit)
        return result.id

    elif task_key == "validate_file_links":
        from app.database import SessionLocal
        from app.models.file_organization_job import FileOrganizationJob, JobType, JobStatus
        from app.tasks.organization_tasks import validate_file_links_task

        db = SessionLocal()
        try:
            job = FileOrganizationJob(
                job_type=JobType.VALIDATE_FILE_LINKS,
                status=JobStatus.PENDING,
                progress_percent=0.0
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            result = validate_file_links_task.delay(str(job.id))
            job.celery_task_id = result.id
            db.commit()
            return str(job.id)
        finally:
            db.close()

    elif task_key == "cleanup_old_jobs":
        from app.tasks.monitoring_tasks import cleanup_old_jobs
        days = params.get("days_to_keep", 30)
        result = cleanup_old_jobs.delay(days)
        return result.id

    elif task_key == "cleanup_old_downloads":
        from app.tasks.monitoring_tasks import cleanup_old_downloads
        days = params.get("days_to_keep", 30)
        result = cleanup_old_downloads.delay(days)
        return result.id

    elif task_key == "cleanup_old_logs":
        from app.tasks.organization_tasks import cleanup_old_logs_task
        days = params.get("retention_days", 120)
        result = cleanup_old_logs_task.delay(days)
        return result.id

    elif task_key == "fetch_missing_images":
        from app.tasks.library_tasks import fetch_missing_images
        result = fetch_missing_images.delay()
        return result.id

    else:
        logger.warning(f"Unknown scheduled task key: {task_key}")
        return None


def calculate_next_run(frequency: str, run_at_hour: int = 2,
                       day_of_week: Optional[int] = None,
                       day_of_month: Optional[int] = None,
                       from_time: Optional[datetime] = None) -> datetime:
    """
    Calculate next run time for a scheduled job.

    Args:
        frequency: daily/weekly/monthly/quarterly
        run_at_hour: Hour of day (0-23)
        day_of_week: 0=Mon..6=Sun (for weekly)
        day_of_month: 1-28 (for monthly/quarterly)
        from_time: Calculate from this time (default: now)
    """
    from datetime import timedelta
    import calendar

    now = from_time or datetime.now(timezone.utc)
    today = now.replace(hour=run_at_hour, minute=0, second=0, microsecond=0)

    if frequency == "daily":
        next_run = today
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    elif frequency == "weekly":
        dow = day_of_week if day_of_week is not None else 0  # Default Monday
        days_ahead = dow - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and today <= now):
            days_ahead += 7
        next_run = today + timedelta(days=days_ahead)
        return next_run

    elif frequency == "monthly":
        dom = day_of_month if day_of_month is not None else 1
        dom = min(dom, 28)  # Cap at 28 to avoid month-length issues
        next_run = today.replace(day=dom)
        if next_run <= now:
            # Move to next month
            if now.month == 12:
                next_run = next_run.replace(year=now.year + 1, month=1)
            else:
                next_run = next_run.replace(month=now.month + 1)
        return next_run

    elif frequency == "quarterly":
        dom = day_of_month if day_of_month is not None else 1
        dom = min(dom, 28)
        # Quarterly months: Jan, Apr, Jul, Oct
        quarter_months = [1, 4, 7, 10]
        next_run = today.replace(day=dom)

        for qm in quarter_months:
            candidate = next_run.replace(month=qm)
            if candidate.month < now.month:
                candidate = candidate.replace(year=now.year + 1)
            if candidate > now:
                return candidate

        # Wrap to next year
        return next_run.replace(year=now.year + 1, month=1)

    # Fallback: daily
    return today + timedelta(days=1)
