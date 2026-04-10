"""
Celery Application Configuration for Studio54
Manages background tasks for music acquisition, downloads, and library management

Queue Architecture:
  - celery:        Import tasks, default fallback
  - downloads:     SABnzbd monitoring, download management
  - search:        Album search with decision engine (separated from downloads to prevent starvation)
  - sync:          Artist/album sync with MusicBrainz
  - organization:  File organization, linking, renaming (long-running)
  - library:       Library scanning tasks
  - monitoring:    Fast periodic health checks (stalled jobs, queue stats)
  - ingest_fast, index_metadata, fetch_images, calculate_hashes, scan: V2 scanner queues

Key design decisions:
  - All periodic tasks have `expires` set to < schedule interval to prevent queue backlog
  - Fast monitoring tasks are on a dedicated queue so they're never blocked by slow work
  - Search tasks separated from downloads to prevent mutual starvation
  - worker_prefetch_multiplier=1 ensures fair task distribution across workers
"""

from celery import Celery, signals
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Create Celery application
celery_app = Celery(
    "studio54",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.download_tasks",
        "app.tasks.sync_tasks",
        "app.tasks.library_tasks",
        "app.tasks.fast_ingest_tasks",
        "app.tasks.background_tasks",
        "app.tasks.scan_coordinator_v2",
        "app.tasks.monitoring_tasks",  # Job monitoring and stall detection
        "app.tasks.import_tasks",  # Library import orchestration
        "app.tasks.book_import_task",  # Audiobook import orchestration
        "app.tasks.organization_tasks",  # File organization tasks
        "app.tasks.resolve_unlinked_task",  # Bulk unlinked file resolution
        "app.tasks.search_tasks",  # Decision engine search tasks
        "app.tasks.playlist_tasks",  # Book playlist creation
    ]
)

# Celery configuration
celery_app.conf.update(
    # Broker settings
    broker_connection_retry_on_startup=True,  # Retry broker connection on startup

    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,  # Acknowledge task after completion
    task_reject_on_worker_lost=True,  # Reject tasks if worker dies
    task_track_started=True,  # Track when tasks start

    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,  # Store additional task metadata

    # Worker settings
    worker_prefetch_multiplier=1,  # Fetch one task at a time (fair distribution for mixed workloads)
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory leak prevention)

    # Events (needed for monitoring/inspection)
    worker_send_task_events=True,
    task_send_sent_event=True,

    # Task routes — order matters: more specific routes must come first
    task_routes={
        # Monitoring: fast periodic checks, never blocked by slow work
        "app.tasks.monitoring_tasks.*": {"queue": "monitoring"},
        # Downloads: SABnzbd interaction only
        "app.tasks.download_tasks.*": {"queue": "downloads"},
        # Search: separated from downloads to prevent mutual starvation
        "app.tasks.search_tasks.*": {"queue": "search"},
        # Sync: MusicBrainz API interaction
        "app.tasks.sync_tasks.*": {"queue": "sync"},
        # Organization: long-running file I/O
        "app.tasks.organization_tasks.*": {"queue": "organization"},
        "app.tasks.resolve_unlinked_task.*": {"queue": "organization"},
        # Library
        "app.tasks.library_tasks.*": {"queue": "library"},
        # Import: library import orchestration
        "app.tasks.import_tasks.orchestrate_library_import": {"queue": "celery"},
        "app.tasks.import_tasks.sync_import_batch": {"queue": "sync"},
        "app.tasks.import_tasks.finalize_import_sync": {"queue": "celery"},
        "app.tasks.import_tasks.*": {"queue": "celery"},
        # V2 Scanner queues
        "app.tasks.fast_ingest_tasks.*": {"queue": "ingest_fast"},
        "app.tasks.background_tasks.index_metadata_batch": {"queue": "index_metadata"},
        "app.tasks.background_tasks.fetch_images_batch": {"queue": "fetch_images"},
        "app.tasks.background_tasks.calculate_hash_batch": {"queue": "calculate_hashes"},
        "app.tasks.scan_coordinator_v2.*": {"queue": "scan"},
    },

    # Task time limits
    task_soft_time_limit=3600,  # Soft limit: 1 hour
    task_time_limit=3900,  # Hard limit: 1 hour 5 minutes

    # Beat schedule (for periodic tasks)
    # IMPORTANT: every periodic task MUST have 'expires' set to less than its schedule
    # interval to prevent queue backlog when workers are busy.
    beat_schedule={
        # ── Fast monitoring (monitoring queue) ──────────────────
        # Monitor active downloads every 30 seconds
        "monitor-downloads": {
            "task": "app.tasks.download_tasks.monitor_active_downloads",
            "schedule": 30.0,
            "options": {"expires": 25, "queue": "monitoring"},  # Expire before next run
        },
        # Detect stalled jobs every 2 minutes
        "detect-stalled-jobs": {
            "task": "app.tasks.monitoring_tasks.detect_stalled_jobs",
            "schedule": 120.0,
            "options": {"expires": 110, "queue": "monitoring"},
        },
        # Monitor tracked downloads every 2 minutes (decision engine)
        "monitor-tracked-downloads": {
            "task": "app.tasks.search_tasks.monitor_tracked_downloads",
            "schedule": 120.0,
            "options": {"expires": 110, "queue": "monitoring"},
        },

        # ── Search tasks (search queue) ─────────────────────────
        # Search wanted albums with decision engine every 15 minutes
        "search-wanted-v2": {
            "task": "app.tasks.search_tasks.search_wanted_albums_v2",
            "schedule": 900.0,  # 15 minutes
            "args": [10],  # limit
            "options": {"expires": 840},  # 14 minutes
        },
        # Check for wanted albums every 6 hours (legacy)
        "search-wanted-albums": {
            "task": "app.tasks.download_tasks.search_wanted_albums",
            "schedule": 21600.0,  # 6 hours
            "options": {"expires": 21000},
        },
        # Search for quality upgrades every 6 hours
        "search-cutoff-unmet": {
            "task": "app.tasks.search_tasks.search_cutoff_unmet",
            "schedule": 21600.0,  # 6 hours
            "args": [5],  # limit
            "options": {"expires": 21000},
        },

        # ── Sync tasks (sync queue) ─────────────────────────────
        # Sync new releases for monitored artists daily
        "sync-new-releases": {
            "task": "app.tasks.sync_tasks.sync_all_artists",
            "schedule": 86400.0,  # 24 hours
            "options": {"expires": 82800},  # 23 hours
        },

        # ── Cleanup tasks (daily, can run on their natural queues) ──
        # Clean up old jobs daily
        "cleanup-old-jobs": {
            "task": "app.tasks.monitoring_tasks.cleanup_old_jobs",
            "schedule": 86400.0,
            "options": {"expires": 82800},
        },
        # Clean up old download records daily
        "cleanup-old-downloads": {
            "task": "app.tasks.monitoring_tasks.cleanup_old_downloads",
            "schedule": 86400.0,
            "args": [30],  # days_to_keep
            "options": {"expires": 82800},
        },
        # Clean up old log files daily (files older than 120 days)
        "cleanup-old-logs": {
            "task": "app.tasks.organization_tasks.cleanup_old_logs_task",
            "schedule": 86400.0,
            "args": [120],  # retention_days
            "options": {"expires": 82800},
        },
        # Worker autoscale check every 60 seconds
        "check-worker-autoscale": {
            "task": "app.tasks.monitoring_tasks.check_worker_autoscale",
            "schedule": 60.0,
            "options": {"expires": 55, "queue": "monitoring"},
        },
        # Check scheduled jobs every 5 minutes
        "check-scheduled-jobs": {
            "task": "app.tasks.monitoring_tasks.check_scheduled_jobs",
            "schedule": 300.0,
            "options": {"expires": 280, "queue": "monitoring"},
        },
    },
)


@signals.worker_ready.connect
def on_worker_ready(**kwargs):
    """
    Auto-recover orphaned jobs when worker starts.

    Checks for jobs stuck in RUNNING/STALLED status (left behind by a crashed
    or restarted worker) and re-dispatches them so they resume from their
    last checkpoint.
    """
    # Delay import to avoid circular imports at module load time
    import time
    import redis as redis_lib
    time.sleep(5)  # Let worker fully initialize before querying DB

    # Use a distributed lock so only ONE worker runs recovery
    try:
        r = redis_lib.from_url(settings.redis_url)
        lock = r.lock("worker_recovery_lock", timeout=60, blocking_timeout=1)
        if not lock.acquire(blocking=False):
            logger.info("Worker startup: another worker is handling recovery, skipping")
            return
    except Exception as e:
        logger.warning(f"Failed to acquire recovery lock, proceeding anyway: {e}")

    try:
        from app.database import SessionLocal
        from app.models.library_import import LibraryImportJob
        from app.models.library import LibraryPath
        from app.models.job_state import JobState, JobStatus
        from app.models.file_organization_job import FileOrganizationJob, JobStatus as FileOrgJobStatus

        db = SessionLocal()
        recovered = 0

        try:
            # ── 1. Recover orphaned LibraryImportJobs ──
            # These are the big multi-phase imports that take hours.
            # Include 'pending' — if a task was dispatched but the worker wasn't
            # running (or Redis was flushed during a deploy), the Celery message
            # is lost and the job stays pending forever.
            orphaned_imports = db.query(LibraryImportJob).filter(
                LibraryImportJob.status.in_(['pending', 'running', 'stalled'])
            ).all()

            for job in orphaned_imports:
                library_path = db.query(LibraryPath).filter(
                    LibraryPath.id == job.library_path_id
                ).first()
                if not library_path:
                    logger.warning(f"Skipping orphaned import {job.id}: library path not found")
                    job.status = 'failed'
                    job.error_message = "Library path not found during recovery"
                    db.commit()
                    continue

                lib_type = library_path.library_type

                logger.warning(
                    f"Recovering orphaned {lib_type} import job {job.id} "
                    f"(status={job.status}, phase={job.current_phase})"
                )

                # For running/stalled jobs, mark as failed so resume logic
                # skips already-completed work. For pending jobs, reset to
                # pending so the task starts fresh.
                if job.status in ('running', 'stalled'):
                    job.status = 'failed'
                    job.error_message = (
                        f"Worker restarted during {job.current_phase or 'unknown'} phase. "
                        f"Auto-resuming from checkpoint."
                    )
                    db.commit()

                # Re-dispatch the correct task based on library type
                if lib_type == "audiobook":
                    from app.tasks.book_import_task import orchestrate_book_import
                    task = orchestrate_book_import.delay(
                        library_path_id=str(job.library_path_id),
                        import_job_id=str(job.id),
                    )
                else:
                    from app.tasks.import_tasks import orchestrate_library_import
                    task = orchestrate_library_import.delay(
                        library_path_id=str(job.library_path_id),
                        import_job_id=str(job.id),
                    )
                job.celery_task_id = task.id
                db.commit()
                recovered += 1
                logger.info(f"Re-dispatched {lib_type} import job {job.id} as task {task.id}")

            # ── 2. Recover orphaned JobState jobs ──
            # Generic tracked tasks (sync, download monitor, etc.)
            orphaned_jobs = db.query(JobState).filter(
                JobState.status.in_([JobStatus.RUNNING, JobStatus.STALLED, JobStatus.RETRYING])
            ).all()

            for job in orphaned_jobs:
                logger.warning(
                    f"Marking orphaned JobState {job.id} ({job.job_type.value}) as FAILED "
                    f"for retry (was {job.status.value})"
                )
                job.status = JobStatus.FAILED
                job.error_message = (
                    f"Worker restarted while job was {job.status.value}. "
                    f"Marked as failed for cleanup."
                )
                job.completed_at = None  # Allow retry
                db.commit()
                recovered += 1

            # ── 3. Recover orphaned FileOrganizationJobs ──
            orphaned_file_jobs = db.query(FileOrganizationJob).filter(
                FileOrganizationJob.status == FileOrgJobStatus.RUNNING
            ).all()

            for job in orphaned_file_jobs:
                logger.warning(
                    f"Marking orphaned FileOrganizationJob {job.id} ({job.job_type.value}) "
                    f"as FAILED for resume"
                )
                job.status = FileOrgJobStatus.FAILED
                job.error_message = (
                    f"Worker restarted during {job.current_action or 'processing'}. "
                    f"Progress: {job.files_processed}/{job.files_total} files. "
                    f"Job is resumable."
                )
                db.commit()
                recovered += 1

            if recovered > 0:
                logger.info(f"Worker startup: recovered {recovered} orphaned job(s)")
            else:
                logger.info("Worker startup: no orphaned jobs found")

        except Exception as e:
            logger.error(f"Error during worker startup job recovery: {e}")
            db.rollback()
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Failed to initialize DB for worker startup recovery: {e}")


# Explicitly import all task modules to ensure they're registered
from app.tasks import book_import_task  # noqa: F401

if __name__ == "__main__":
    celery_app.start()
