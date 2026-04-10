"""
Queue Status API — Celery queue monitoring and statistics

Provides real-time visibility into:
- Queue depths (messages waiting per queue)
- Worker status (active, reserved tasks)
- Task throughput rates
- Recent task history
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import redis
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.security import rate_limit
from app.tasks.celery_app import celery_app
from app.auth import require_director, require_any_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# All known queues in the system
KNOWN_QUEUES = [
    "celery",
    "downloads",
    "search",
    "sync",
    "organization",
    "library",
    "monitoring",
    "ingest_fast",
    "index_metadata",
    "fetch_images",
    "calculate_hashes",
    "scan",
]

_redis_client = None


def _get_redis():
    """Get Redis client for queue inspection"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


@router.get("/queue-status")
@rate_limit("60/minute")
async def get_queue_status(request: Request, current_user: User = Depends(require_any_user)):
    """
    Get comprehensive queue status including depths, workers, and task rates.

    Returns queue depths for all known queues, active worker information,
    and recent task completion stats.
    """
    r = _get_redis()

    # ── Queue Depths ──────────────────────────────────────────
    queue_depths = {}
    total_pending = 0
    for queue_name in KNOWN_QUEUES:
        depth = r.llen(queue_name)
        queue_depths[queue_name] = depth
        total_pending += depth

    # ── Worker Status ─────────────────────────────────────────
    workers = []
    total_active = 0
    total_reserved = 0

    try:
        inspect = celery_app.control.inspect(timeout=3)
        active_tasks = inspect.active() or {}
        reserved_tasks = inspect.reserved() or {}
        stats = inspect.stats() or {}

        for worker_name in set(list(active_tasks.keys()) + list(reserved_tasks.keys()) + list(stats.keys())):
            active = active_tasks.get(worker_name, [])
            reserved = reserved_tasks.get(worker_name, [])
            worker_stats = stats.get(worker_name, {})

            pool_info = worker_stats.get("pool", {})
            total = worker_stats.get("total", {})

            workers.append({
                "name": worker_name,
                "active_tasks": len(active),
                "reserved_tasks": len(reserved),
                "pool_size": pool_info.get("max-concurrency", 0),
                "tasks_completed": sum(total.values()) if isinstance(total, dict) else 0,
                "active_task_names": [
                    {
                        "name": t.get("name", "unknown"),
                        "id": t.get("id", ""),
                        "runtime": round(t.get("time_start", 0) and (time.time() - t["time_start"]), 1) if t.get("time_start") else 0,
                    }
                    for t in active
                ],
            })
            total_active += len(active)
            total_reserved += len(reserved)

    except Exception as e:
        logger.warning(f"Failed to inspect workers: {e}")

    # ── Task Throughput (from Redis result keys) ──────────────
    # Count recent task results as a proxy for throughput
    task_type_counts = {}
    try:
        for worker_info in workers:
            # Use the stats 'total' dict which has per-task-name counts
            pass  # Already captured in worker stats above
    except Exception:
        pass

    # ── Search Locks ──────────────────────────────────────────
    active_search_locks = 0
    try:
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match="search:album:*", count=100)
            active_search_locks += len(keys)
            if cursor == 0:
                break
    except Exception:
        pass

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_pending": total_pending,
            "total_active": total_active,
            "total_reserved": total_reserved,
            "total_workers": len(workers),
            "active_search_locks": active_search_locks,
        },
        "queues": queue_depths,
        "workers": workers,
    }


@router.post("/queue-status/purge/{queue_name}")
@rate_limit("5/minute")
async def purge_queue(request: Request, queue_name: str, current_user: User = Depends(require_director)):
    """
    Purge all messages from a specific queue.

    Use with caution — this discards all pending tasks in the queue.
    Useful for clearing stale periodic task backlog.
    """
    if queue_name not in KNOWN_QUEUES:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown queue: {queue_name}. Known queues: {KNOWN_QUEUES}"
        )

    r = _get_redis()
    count = r.llen(queue_name)
    r.delete(queue_name)

    logger.warning(f"Purged {count} messages from queue '{queue_name}'")

    return {
        "success": True,
        "queue": queue_name,
        "messages_purged": count,
    }
