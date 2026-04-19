"""
Admin API - System Administration and Configuration
Includes logging control, system settings, library management, etc.
"""

import logging
import re
import subprocess
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from slowapi import Limiter
from slowapi.util import get_remote_address
import psutil

from app.database import get_db
from app.services.logging_config import get_logging_config_service
from app.auth import require_director
from app.models.user import User

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# Valid logging levels
VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LoggingLevelRequest(BaseModel):
    """Request model for setting logging level"""
    service: str  # 'root', 'uvicorn', 'uvicorn.access', 'app', etc.
    level: str    # DEBUG, INFO, WARNING, ERROR, CRITICAL


class LoggingLevelResponse(BaseModel):
    """Response model for logging level"""
    service: str
    level: str
    effective_level: int


@router.get("/admin/logging", response_model=List[LoggingLevelResponse])
@limiter.limit("30/minute")
async def get_logging_levels(request: Request, current_user: User = Depends(require_director)):
    """
    Get current logging levels for all loggers.

    Note: Returns levels from this worker's Python logging system.
    All workers should have synchronized levels via Redis.

    Returns:
        List of logging levels for key services
    """
    logging_config = get_logging_config_service()
    levels = logging_config.get_effective_levels()

    return [
        LoggingLevelResponse(
            service=level["service"],
            level=level["level"],
            effective_level=level["effective_level"]
        )
        for level in levels
    ]


@router.post("/admin/logging")
@limiter.limit("10/minute")
async def set_logging_level(request: Request, config: LoggingLevelRequest, current_user: User = Depends(require_director)):
    """
    Set logging level for a specific service.

    This uses Redis to store the level and SIGUSR1 signals to broadcast
    the change to all uvicorn workers, ensuring consistent logging across
    the entire service.

    Args:
        config: Logging configuration (service name and level)

    Returns:
        Updated logging level configuration

    Raises:
        HTTPException: If invalid service or log level
    """
    # Validate log level
    if config.level.upper() not in VALID_LOG_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid log level. Must be one of: {', '.join(VALID_LOG_LEVELS)}"
        )

    # Use the logging config service to set level and broadcast to all workers
    logging_config = get_logging_config_service()
    success = logging_config.set_level(config.service, config.level.upper())

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set logging level"
        )

    service_name = config.service.lower() if config.service.lower() != "root" else "root"

    # Get the effective level after setting
    if service_name == "root":
        effective_level = logging.getLogger().level
    else:
        effective_level = logging.getLogger(service_name).level

    # Log the change
    logging.getLogger("app").info(
        f"Logging level changed for '{service_name}': {config.level.upper()} (broadcast to all workers)"
    )

    return {
        "service": service_name,
        "level": config.level.upper(),
        "effective_level": effective_level,
        "message": f"Logging level for '{service_name}' set to {config.level.upper()} (all workers)"
    }


@router.post("/admin/logging/reset")
@limiter.limit("10/minute")
async def reset_logging_to_defaults(request: Request, current_user: User = Depends(require_director)):
    """
    Reset all logging levels to defaults and broadcast to all workers.

    Defaults:
    - root: WARNING
    - app: INFO
    - uvicorn: INFO
    - uvicorn.access: WARNING (suppress health checks)
    - sqlalchemy: WARNING
    - httpx: WARNING
    - celery: INFO

    Returns:
        List of reset logging configurations
    """
    logging_config = get_logging_config_service()
    logging_config.reset_to_defaults()

    # Get the effective levels after reset
    levels = logging_config.get_effective_levels()

    logging.getLogger("app").info("Logging levels reset to defaults (broadcast to all workers)")

    return {
        "message": "Logging levels reset to defaults (all workers)",
        "levels": levels
    }


# ==================== LIVE SERVICE LOGS ====================

# Logger descriptions for the UI
LOGGER_DESCRIPTIONS = {
    "root": "Base logger — catches anything not handled by a specific logger",
    "app": "Studio54 application code (API, services, models)",
    "uvicorn": "Web server (HTTP request handling)",
    "uvicorn.access": "HTTP access log (request method, path, status code)",
    "uvicorn.error": "Web server errors and startup messages",
    "sqlalchemy": "Database ORM queries and connections",
    "celery": "Background task worker (jobs, downloads, sync)",
    "httpx": "Outbound HTTP calls (MusicBrainz, AcoustID, indexers)",
}


@router.get("/admin/logging/live")
@limiter.limit("60/minute")
async def get_live_logs(
    request: Request,
    lines: int = 200,
    level: Optional[str] = None,
    logger_name: Optional[str] = None,
    current_user: User = Depends(require_director),
):
    """
    Get recent log output from the in-memory ring buffer.

    This returns the last N log lines from the running service process.
    Optionally filter by log level or logger name.
    """
    from app.services.logging_config import get_ring_handler
    handler = get_ring_handler()
    log_lines = handler.get_lines(
        count=min(lines, 2000),
        level_filter=level,
        logger_filter=logger_name,
    )
    return {
        "lines": log_lines,
        "total": len(log_lines),
        "level_filter": level,
        "logger_filter": logger_name,
    }


@router.get("/admin/logging/descriptions")
@limiter.limit("60/minute")
async def get_logger_descriptions(
    request: Request,
    current_user: User = Depends(require_director),
):
    """Get descriptions for each logger service."""
    return {"loggers": LOGGER_DESCRIPTIONS}


# ==================== LOG FILES ====================

# Human-readable descriptions for each job type
JOB_TYPE_DESCRIPTIONS = {
    # JobState types
    "album_search": "Search indexers for wanted albums",
    "download_monitor": "Monitor SABnzbd download progress",
    "import_download": "Import completed downloads into library",
    "library_scan": "Scan library path for audio files",
    "artist_sync": "Sync artist metadata from MusicBrainz",
    "metadata_refresh": "Refresh metadata for existing records",
    "image_fetch": "Fetch artist/album artwork",
    "cleanup": "Clean up old jobs and data",
    # FileOrganizationJob types
    "organize_library": "Organize and rename library files",
    "organize_artist": "Organize files for a specific artist",
    "organize_album": "Organize files for a specific album",
    "validate_structure": "Validate directory structure",
    "fetch_metadata": "Fetch MBIDs from MusicBrainz",
    "validate_mbid": "Verify MBIDs in file metadata",
    "validate_mbid_metadata": "Validate file metadata matches MusicBrainz",
    "link_files": "Link files to album/track records via MBID",
    "reindex_albums": "Reindex albums from file metadata",
    "verify_audio": "Verify audio match of downloaded files",
    "rollback": "Rollback a previous file operation",
    "library_migration": "Migrate files to new library structure",
    "migration_fingerprint": "Fingerprint files that failed migration",
    "associate_and_organize": "Match filesystem files to DB tracks",
    "validate_file_links": "Verify linked track files exist on disk",
    "resolve_unlinked": "Auto-import albums and resolve unlinked files",
    # LibraryImportJob
    "import": "Full library import pipeline",
}


@router.get("/admin/logs")
@limiter.limit("30/minute")
async def list_log_files(
    request: Request,
    job_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    List available job log files with metadata.

    Returns log files from all job types (JobState, FileOrganizationJob, LibraryImportJob)
    sorted by most recent first.
    """
    from app.models.job_state import JobState, JobType as JSJobType
    from app.models.file_organization_job import FileOrganizationJob, JobType as FOJobType
    from app.models.library_import import LibraryImportJob

    logs = []

    # Gather from JobState
    js_query = db.query(JobState).filter(JobState.log_file_path.isnot(None))
    if job_type:
        try:
            js_query = js_query.filter(JobState.job_type == job_type)
        except Exception:
            pass
    for job in js_query.order_by(JobState.created_at.desc()).all():
        jt = job.job_type.value if isinstance(job.job_type, JSJobType) else str(job.job_type)
        logs.append({
            "job_id": str(job.id),
            "job_type": jt,
            "description": JOB_TYPE_DESCRIPTIONS.get(jt, jt),
            "status": job.status.value if hasattr(job.status, 'value') else str(job.status),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "log_file_path": job.log_file_path,
            "source": "job_state",
        })

    # Gather from FileOrganizationJob
    fo_query = db.query(FileOrganizationJob).filter(FileOrganizationJob.log_file_path.isnot(None))
    if job_type:
        try:
            fo_query = fo_query.filter(FileOrganizationJob.job_type == job_type)
        except Exception:
            pass
    for job in fo_query.order_by(FileOrganizationJob.created_at.desc()).all():
        jt = job.job_type.value if isinstance(job.job_type, FOJobType) else str(job.job_type)
        logs.append({
            "job_id": str(job.id),
            "job_type": jt,
            "description": JOB_TYPE_DESCRIPTIONS.get(jt, jt),
            "status": job.status.value if hasattr(job.status, 'value') else str(job.status),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "log_file_path": job.log_file_path,
            "current_action": getattr(job, 'current_action', None),
            "source": "file_organization",
        })

    # Gather from LibraryImportJob
    li_query = db.query(LibraryImportJob).filter(LibraryImportJob.log_file_path.isnot(None))
    for job in li_query.order_by(LibraryImportJob.created_at.desc()).all():
        logs.append({
            "job_id": str(job.id),
            "job_type": "import",
            "description": JOB_TYPE_DESCRIPTIONS.get("import", "Library import"),
            "status": str(job.status),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "log_file_path": job.log_file_path,
            "source": "library_import",
        })

    # Sort all by created_at desc
    logs.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    # Get unique job types for filter dropdown
    all_types = sorted(set(l["job_type"] for l in logs))
    type_options = [{"value": t, "label": JOB_TYPE_DESCRIPTIONS.get(t, t)} for t in all_types]

    total = len(logs)
    paginated = logs[offset:offset + limit]

    return {
        "logs": paginated,
        "total": total,
        "offset": offset,
        "limit": limit,
        "job_types": type_options,
    }


@router.get("/admin/logs/{job_id}/content")
@limiter.limit("60/minute")
async def get_log_content(
    request: Request,
    job_id: str,
    lines: int = 500,
    tail: bool = False,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Get log file content for a specific job.
    """
    from app.models.job_state import JobState
    from app.models.file_organization_job import FileOrganizationJob
    from app.models.library_import import LibraryImportJob
    from pathlib import Path
    import uuid as uuid_mod

    try:
        job_uuid = uuid_mod.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    log_file_path = None
    job_type = "unknown"

    job = db.query(JobState).filter(JobState.id == job_uuid).first()
    if job:
        log_file_path = job.log_file_path
        job_type = job.job_type.value if hasattr(job.job_type, 'value') else str(job.job_type)
    else:
        job = db.query(FileOrganizationJob).filter(FileOrganizationJob.id == job_uuid).first()
        if job:
            log_file_path = job.log_file_path
            job_type = job.job_type.value if hasattr(job.job_type, 'value') else str(job.job_type)
        else:
            job = db.query(LibraryImportJob).filter(LibraryImportJob.id == job_uuid).first()
            if job:
                log_file_path = job.log_file_path
                job_type = "import"

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not log_file_path or not Path(log_file_path).exists():
        return {
            "job_id": job_id,
            "job_type": job_type,
            "log_available": False,
            "content": "Log file not available.",
            "total_lines": 0,
        }

    all_lines = Path(log_file_path).read_text(errors="replace").splitlines()
    total = len(all_lines)

    if tail:
        selected = all_lines[-lines:]
    else:
        selected = all_lines[:lines]

    return {
        "job_id": job_id,
        "job_type": job_type,
        "log_available": True,
        "content": "\n".join(selected),
        "total_lines": total,
        "lines_returned": len(selected),
    }


# ==================== LIBRARY MANAGEMENT ====================


class ClearLibraryRequest(BaseModel):
    """Request model for clearing library database"""
    keep_playlists: bool = False
    keep_watched_artists: bool = False


@router.delete("/admin/library/clear")
@limiter.limit("5/minute")
async def clear_library(request: Request, body: ClearLibraryRequest, current_user: User = Depends(require_director), db: Session = Depends(get_db)):
    """
    Clear all library data from the database.
    No files on disk are deleted.

    Options:
    - keep_playlists: Preserve playlists and their track associations
    - keep_watched_artists: Preserve monitored artists (but clear their albums/tracks)
    """
    logger = logging.getLogger("app")
    logger.warning(
        f"Clear library requested: keep_playlists={body.keep_playlists}, "
        f"keep_watched_artists={body.keep_watched_artists}"
    )

    summary = {}

    try:
        # Delete in order respecting foreign keys
        # 1. Audit and job history
        r = db.execute(text("DELETE FROM file_operation_audit"))
        summary["file_operation_audit"] = r.rowcount
        r = db.execute(text("DELETE FROM file_organization_jobs"))
        summary["file_organization_jobs"] = r.rowcount
        r = db.execute(text("DELETE FROM scan_jobs"))
        summary["scan_jobs"] = r.rowcount
        r = db.execute(text("DELETE FROM job_states"))
        summary["job_states"] = r.rowcount
        r = db.execute(text("DELETE FROM library_import_jobs"))
        summary["library_import_jobs"] = r.rowcount

        # 2. Library files and matches
        r = db.execute(text("DELETE FROM library_files"))
        summary["library_files"] = r.rowcount
        r = db.execute(text("DELETE FROM library_artist_matches"))
        summary["library_artist_matches"] = r.rowcount

        # 3. Downloads
        r = db.execute(text("DELETE FROM tracked_downloads"))
        summary["tracked_downloads"] = r.rowcount
        r = db.execute(text("DELETE FROM download_history"))
        summary["download_history"] = r.rowcount
        r = db.execute(text("DELETE FROM download_queue"))
        summary["download_queue"] = r.rowcount

        # 4. Releases and blacklist
        r = db.execute(text("DELETE FROM pending_releases"))
        summary["pending_releases"] = r.rowcount
        r = db.execute(text("DELETE FROM blacklist"))
        summary["blacklist"] = r.rowcount

        # 5. Album metadata files
        r = db.execute(text("DELETE FROM album_metadata_files"))
        summary["album_metadata_files"] = r.rowcount

        # 6. Playlists (conditional)
        if not body.keep_playlists:
            r = db.execute(text("DELETE FROM playlist_tracks"))
            summary["playlist_tracks"] = r.rowcount
            r = db.execute(text("DELETE FROM playlists"))
            summary["playlists"] = r.rowcount
        else:
            # Even when keeping playlists, clear playlist_tracks since tracks are being deleted
            r = db.execute(text("DELETE FROM playlist_tracks"))
            summary["playlist_tracks"] = r.rowcount
            summary["playlists"] = 0
            summary["playlists_kept"] = True

        # 7. Tracks
        r = db.execute(text("DELETE FROM tracks"))
        summary["tracks"] = r.rowcount

        # 8. Albums
        r = db.execute(text("DELETE FROM albums"))
        summary["albums"] = r.rowcount

        # 9. Artists (conditional)
        if body.keep_watched_artists:
            r = db.execute(text("DELETE FROM artists WHERE is_monitored = false"))
            summary["artists_deleted"] = r.rowcount
            # Reset counts on kept artists since their albums/tracks are gone
            r = db.execute(text(
                "UPDATE artists SET album_count = 0, single_count = 0, track_count = 0"
            ))
            summary["artists_kept"] = r.rowcount
        else:
            r = db.execute(text("DELETE FROM artists"))
            summary["artists"] = r.rowcount

        db.commit()

        total_deleted = sum(v for k, v in summary.items() if isinstance(v, int) and k not in ("artists_kept",))
        logger.warning(f"Library cleared: {total_deleted} total rows deleted")

        return {
            "success": True,
            "message": f"Library cleared successfully. {total_deleted} rows deleted.",
            "summary": summary,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to clear library: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear library: {str(e)}"
        )


# ==================== SYSTEM STATS ====================


@router.get("/admin/system/stats")
@limiter.limit("30/minute")
async def get_system_stats(request: Request, current_user: User = Depends(require_director)):
    """
    Get system resource utilization (CPU, memory, disk, GPU).
    Uses psutil for CPU/memory/disk. Optionally uses pynvml for GPU stats.
    """
    cpu_percent = psutil.cpu_percent(interval=0.1)

    mem = psutil.virtual_memory()
    memory = {
        "used_bytes": mem.used,
        "total_bytes": mem.total,
        "percent": mem.percent,
    }

    disk = psutil.disk_usage("/")
    disk_info = {
        "used_bytes": disk.used,
        "total_bytes": disk.total,
        "percent": disk.percent,
    }

    # Top processes by CPU usage
    top_cpu = []
    top_mem = []
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
            try:
                info = p.info
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        # Top 10 by CPU
        by_cpu = sorted(procs, key=lambda x: x.get('cpu_percent') or 0, reverse=True)[:10]
        top_cpu = [
            {
                "pid": p['pid'],
                "name": p['name'],
                "cpu_percent": round(p.get('cpu_percent') or 0, 1),
            }
            for p in by_cpu
        ]
        # Top 10 by memory
        by_mem = sorted(procs, key=lambda x: x.get('memory_percent') or 0, reverse=True)[:10]
        top_mem = [
            {
                "pid": p['pid'],
                "name": p['name'],
                "memory_percent": round(p.get('memory_percent') or 0, 1),
                "memory_mb": round((p.get('memory_info') and p['memory_info'].rss or 0) / (1024 * 1024), 1),
            }
            for p in by_mem
        ]
    except Exception:
        pass

    # Network I/O
    network = {}
    try:
        net = psutil.net_io_counters()
        network = {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
        }
    except Exception:
        pass

    gpu = None
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        gpu = {
            "name": name,
            "utilization_percent": util.gpu,
            "memory_used_mb": round(mem_info.used / (1024 * 1024)),
            "memory_total_mb": round(mem_info.total / (1024 * 1024)),
        }
        pynvml.nvmlShutdown()
    except Exception:
        pass

    return {
        "cpu_percent": cpu_percent,
        "memory": memory,
        "network": network,
        "disk": disk_info,
        "gpu": gpu,
        "top_cpu_processes": top_cpu,
        "top_memory_processes": top_mem,
    }


@router.post("/admin/recalculate-artist-stats")
@limiter.limit("2/hour")
async def recalculate_artist_stats(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Recalculate album_count, single_count, and track_count for ALL artists
    from the actual albums/tracks in the database. Fixes stale stored counts.
    """
    from sqlalchemy import func, case
    from app.models.artist import Artist
    from app.models.album import Album
    from app.models.track import Track

    artists = db.query(Artist).all()
    updated = 0
    for artist in artists:
        old_album = artist.album_count or 0
        old_single = artist.single_count or 0
        old_track = artist.track_count or 0

        artist.album_count = db.query(Album).filter(
            Album.artist_id == artist.id,
            Album.album_type != 'Single'
        ).count()
        artist.single_count = db.query(Album).filter(
            Album.artist_id == artist.id,
            Album.album_type == 'Single'
        ).count()
        artist.track_count = db.query(Track).join(Album).filter(
            Album.artist_id == artist.id
        ).count()

        if (artist.album_count != old_album or
            artist.single_count != old_single or
            artist.track_count != old_track):
            updated += 1

    db.commit()
    return {
        "success": True,
        "total_artists": len(artists),
        "updated": updated,
        "message": f"Recalculated stats for {len(artists)} artists ({updated} had stale counts)"
    }


# ---------------------------------------------------------------------------
# Network ping check
# ---------------------------------------------------------------------------

# Validate host: allow hostnames, IPv4, IPv6 — reject anything shell-dangerous
_SAFE_HOST_RE = re.compile(
    r'^(?:'
    r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'  # hostname
    r'|(?:\d{1,3}\.){3}\d{1,3}'  # IPv4
    r'|(?:[0-9a-fA-F:]{2,39})'   # IPv6
    r')$'
)


@router.get("/admin/network/ping")
@limiter.limit("30/minute")
async def network_ping(
    request: Request,
    host: str = Query(..., description="Hostname or IP address to ping"),
    count: int = Query(default=4, ge=1, le=10),
    current_user: User = Depends(require_director),
):
    """
    Perform an ICMP ping to the given host and return latency statistics.
    Uses the system ping binary; director role required.
    """
    # Strip port if provided (e.g. "8.8.8.8:53" → "8.8.8.8")
    host = host.split(":")[0].strip()
    # Strip protocol prefix if present
    for prefix in ("http://", "https://", "ftp://"):
        if host.startswith(prefix):
            host = host[len(prefix):]

    if not _SAFE_HOST_RE.match(host):
        raise HTTPException(status_code=400, detail="Invalid host format")

    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", "2", host],
            capture_output=True,
            text=True,
            timeout=count * 3 + 5,
        )
    except subprocess.TimeoutExpired:
        return {
            "host": host,
            "reachable": False,
            "packet_loss_percent": 100.0,
            "rtt_min_ms": None,
            "rtt_avg_ms": None,
            "rtt_max_ms": None,
            "packets_sent": count,
            "packets_received": 0,
            "error": "timeout",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    output = result.stdout + result.stderr
    reachable = result.returncode == 0

    # Parse "X packets transmitted, Y received, Z% packet loss"
    loss_match = re.search(r'(\d+)% packet loss', output)
    packet_loss = float(loss_match.group(1)) if loss_match else (0.0 if reachable else 100.0)

    tx_match = re.search(r'(\d+) packets? transmitted', output)
    rx_match = re.search(r'(\d+) received', output)
    packets_sent = int(tx_match.group(1)) if tx_match else count
    packets_received = int(rx_match.group(1)) if rx_match else (count if reachable else 0)

    # Parse RTT line: "rtt min/avg/max/mdev = 1.234/2.345/3.456/0.123 ms"
    rtt_min = rtt_avg = rtt_max = None
    rtt_match = re.search(r'min/avg/max(?:/mdev)? = ([\d.]+)/([\d.]+)/([\d.]+)', output)
    if rtt_match:
        rtt_min = float(rtt_match.group(1))
        rtt_avg = float(rtt_match.group(2))
        rtt_max = float(rtt_match.group(3))

    return {
        "host": host,
        "reachable": reachable,
        "packet_loss_percent": packet_loss,
        "rtt_min_ms": rtt_min,
        "rtt_avg_ms": rtt_avg,
        "rtt_max_ms": rtt_max,
        "packets_sent": packets_sent,
        "packets_received": packets_received,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Disk usage for a given mount point
# ---------------------------------------------------------------------------

# Allow only safe filesystem paths: absolute paths, no shell metacharacters
_SAFE_PATH_RE = re.compile(r'^/[a-zA-Z0-9._/\-]*$')


@router.get("/admin/disk/usage")
@limiter.limit("60/minute")
async def disk_usage(
    request: Request,
    path: str = Query(..., description="Absolute mount point path to check (e.g. /, /mnt/data)"),
    current_user: User = Depends(require_director),
):
    """
    Return disk usage statistics for the given mount point using psutil.
    Director role required.
    """
    path = path.strip()
    if not _SAFE_PATH_RE.match(path):
        raise HTTPException(status_code=400, detail="Invalid path format")

    try:
        usage = psutil.disk_usage(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    def fmt(b: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b //= 1024
        return f"{b:.1f} PB"

    return {
        "path": path,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent": usage.percent,
        "total_human": fmt(usage.total),
        "used_human": fmt(usage.used),
        "free_human": fmt(usage.free),
    }


# ---------------------------------------------------------------------------
# Job activity summary (last N days)
# ---------------------------------------------------------------------------

@router.get("/admin/jobs/activity-summary")
@limiter.limit("60/minute")
async def jobs_activity_summary(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Return aggregate job counts for the last N days across all job tables.
    Director role required.
    """
    from datetime import timedelta
    from app.models.job_state import JobState, JobStatus as JSStatus
    from app.models.file_organization_job import FileOrganizationJob, JobStatus as FOStatus
    from app.models.library_import import LibraryImportJob

    cutoff = __import__('datetime').datetime.now(__import__('datetime').timezone.utc) - timedelta(days=days)

    def _counts(query, completed_val, failed_val):
        total = query.count()
        completed = query.filter_by(status=completed_val).count()
        failed = query.filter_by(status=failed_val).count()
        return total, completed, failed

    # JobState
    js_base = db.query(JobState).filter(JobState.created_at >= cutoff)
    js_total, js_completed, js_failed = _counts(js_base, JSStatus.COMPLETED, JSStatus.FAILED)

    # FileOrganizationJob
    fo_base = db.query(FileOrganizationJob).filter(FileOrganizationJob.created_at >= cutoff)
    fo_total, fo_completed, fo_failed = _counts(fo_base, FOStatus.COMPLETED, FOStatus.FAILED)

    # LibraryImportJob — status stored as plain string
    li_base = db.query(LibraryImportJob).filter(LibraryImportJob.created_at >= cutoff)
    li_total = li_base.count()
    li_completed = li_base.filter(LibraryImportJob.status == "completed").count()
    li_failed = li_base.filter(LibraryImportJob.status == "failed").count()

    total = js_total + fo_total + li_total
    completed = js_completed + fo_completed + li_completed
    failed = js_failed + fo_failed + li_failed

    return {
        "days": days,
        "total": total,
        "completed": completed,
        "failed": failed,
        "running": total - completed - failed,
    }
