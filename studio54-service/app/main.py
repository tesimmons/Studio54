"""
Studio54 - Music Acquisition & Library Management System
Main FastAPI Application
"""

import logging
from typing import Optional
from fastapi import FastAPI, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import psutil
import os
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Music acquisition and library management system with MusicBrainz integration, SABnzbd automation, and MUSE library sync",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for web frontend
allowed_origins = [origin.strip() for origin in settings.allowed_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Configure rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Make limiter available to security module
from app.security import set_limiter
set_limiter(limiter)


@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup"""
    # Initialize logging configuration service (for multi-worker sync)
    from app.services.logging_config import get_logging_config_service
    logging_config = get_logging_config_service()
    logging_config.initialize()

    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Database URL: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configured'}")
    logger.info(f"Redis URL: {settings.redis_url.split('@')[1] if '@' in settings.redis_url else 'configured'}")
    logger.info(f"MUSE Service: {settings.muse_service_url}")
    logger.info(f"Music Library Path: {settings.music_library_path}")

    # Log SABnzbd configuration (without exposing API key)
    logger.info(f"SABnzbd: {settings.sabnzbd_host}:{settings.sabnzbd_port}")

    # Auto-configure SABnzbd download client from environment if configured
    try:
        from app.models.download_client import DownloadClient
        from app.services.encryption import get_encryption_service

        db = next(get_db())

        # Check if any download clients exist
        existing_count = db.query(DownloadClient).count()

        if existing_count == 0 and settings.sabnzbd_api_key:
            logger.info("Auto-configuring SABnzbd download client from environment variables")

            encryption_service = get_encryption_service()
            encrypted_api_key = encryption_service.encrypt(settings.sabnzbd_api_key)

            default_client = DownloadClient(
                name="SABnzbd (Auto-configured)",
                client_type="sabnzbd",
                host=settings.sabnzbd_host,
                port=settings.sabnzbd_port,
                use_ssl=False,
                api_key_encrypted=encrypted_api_key,
                category="music",
                priority=0,
                is_enabled=True,
                is_default=True
            )

            db.add(default_client)
            db.commit()

            logger.info(f"✓ Auto-configured SABnzbd client: {settings.sabnzbd_host}:{settings.sabnzbd_port}")
        elif existing_count > 0:
            logger.info(f"Found {existing_count} existing download client(s), skipping auto-configuration")

        db.close()
    except Exception as e:
        logger.error(f"Failed to auto-configure SABnzbd: {e}")

    # Auto-seed admin user if no users exist (safety net beyond migration)
    try:
        from app.models.user import User
        from app.auth import hash_password

        db = next(get_db())
        user_count = db.query(User).count()
        if user_count == 0:
            logger.info("No users found, creating default admin user")
            admin_user = User(
                username="admin",
                password_hash=hash_password("admin"),
                display_name="Club Director",
                role="director",
                must_change_password=True,
            )
            db.add(admin_user)
            db.commit()
            logger.info("Default admin user created (admin/admin)")
        db.close()
    except Exception as e:
        logger.error(f"Failed to seed admin user: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    # Cleanup logging configuration service
    from app.services.logging_config import get_logging_config_service
    logging_config = get_logging_config_service()
    logging_config.cleanup()

    logger.info(f"Shutting down {settings.app_name}")


@app.get("/")
@limiter.limit("100/minute")
async def root(request: Request):
    """Root endpoint"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/v1/health")
@app.get("/health")
@limiter.limit("30/minute")
async def health_check(request: Request, db: Session = Depends(get_db)):
    """
    Health check endpoint for Docker healthcheck and monitoring

    Checks:
    - API is responding
    - Database connection is working
    - Redis connection is working
    - SABnzbd connectivity (optional)
    - MUSE service connectivity (optional)
    - Disk space availability

    Returns:
        dict: Health status information
    """
    health_status = {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }

    # Check database connection
    try:
        db.execute(text("SELECT 1"))
        health_status["database"] = "connected"
    except Exception as e:
        health_status["database"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"

    # Check Redis connection
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.ping()
        health_status["redis"] = "connected"
    except Exception as e:
        health_status["redis"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"

    # Check SABnzbd availability (optional - doesn't affect health status)
    try:
        import httpx
        sabnzbd_base_url = f"http://{settings.sabnzbd_host}:{settings.sabnzbd_port}"
        response = httpx.get(f"{sabnzbd_base_url}/api?mode=version&output=json&apikey={settings.sabnzbd_api_key}", timeout=5.0)
        if response.status_code == 200:
            health_status["sabnzbd"] = "available"
        else:
            health_status["sabnzbd"] = f"unexpected status: {response.status_code}"
    except Exception as e:
        health_status["sabnzbd"] = f"unavailable: {str(e)}"

    # Check MUSE service availability (optional)
    try:
        import httpx
        response = httpx.get(f"{settings.muse_service_url}/health", timeout=5.0)
        if response.status_code == 200:
            health_status["muse"] = "available"
        else:
            health_status["muse"] = f"unexpected status: {response.status_code}"
    except Exception as e:
        health_status["muse"] = f"unavailable: {str(e)}"

    # Check Ollama availability (for AI features)
    try:
        import httpx
        response = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5.0)
        if response.status_code == 200:
            health_status["ollama"] = "available"
        else:
            health_status["ollama"] = f"unexpected status: {response.status_code}"
    except Exception as e:
        health_status["ollama"] = f"unavailable: {str(e)}"

    # Check disk space
    try:
        disk_usage = psutil.disk_usage('/')
        health_status["disk_space_free_bytes"] = disk_usage.free
        health_status["disk_space_free_gb"] = round(disk_usage.free / (1024**3), 2)

        # Warn if less than 10GB free
        if disk_usage.free < 10 * 1024**3:
            health_status["disk_warning"] = "Low disk space (<10GB free)"
    except Exception as e:
        health_status["disk_space"] = f"error: {str(e)}"

    # Check music library path exists
    try:
        if os.path.exists(settings.music_library_path):
            health_status["music_library_path"] = "exists"
        else:
            health_status["music_library_path"] = "not found"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["music_library_path"] = f"error: {str(e)}"

    return health_status


def format_bytes(bytes_value: int) -> str:
    """
    Format bytes into human-readable string

    Args:
        bytes_value: Number of bytes

    Returns:
        Formatted string like "1.23 GB"
    """
    if bytes_value < 1024:
        return f"{bytes_value} B"
    elif bytes_value < 1024**2:
        return f"{bytes_value / 1024:.2f} KB"
    elif bytes_value < 1024**3:
        return f"{bytes_value / (1024**2):.2f} MB"
    elif bytes_value < 1024**4:
        return f"{bytes_value / (1024**3):.2f} GB"
    else:
        return f"{bytes_value / (1024**4):.2f} TB"


@app.get("/api/v1/stats")
@app.get("/stats")  # Legacy path
@limiter.limit("60/minute")
async def system_stats(request: Request, db: Session = Depends(get_db), library_type: Optional[str] = Query(None)):
    """
    Get system statistics

    Returns:
        dict: System statistics including artist counts, album counts, download stats
    """
    from app.models.artist import Artist
    from app.models.album import Album
    from app.models.download_queue import DownloadQueue, DownloadStatus
    from sqlalchemy import func

    # Get database counts
    if library_type != "audiobook":
        artists_count = db.query(Artist).filter(Artist.is_monitored == True).count()
        total_artists = db.query(Artist).count()
        albums_count = db.query(Album).join(Artist, Album.artist_id == Artist.id).filter(
            Album.monitored == True, Artist.is_monitored == True
        ).count()
        total_albums = db.query(Album).count()

        from app.models.track import Track
        linked_albums = db.query(func.count(func.distinct(Album.id))).join(
            Track, Track.album_id == Album.id
        ).filter(Track.has_file == True).scalar() or 0
        linked_tracks = db.query(func.count(Track.id)).filter(Track.has_file == True).scalar() or 0
        total_tracks = db.query(func.count(Track.id)).scalar() or 0
    else:
        artists_count = total_artists = albums_count = total_albums = 0
        linked_albums = linked_tracks = total_tracks = 0

    # Download statistics (filter by library_type when set)
    dl_base = db.query(DownloadQueue)
    if library_type:
        dl_base = dl_base.filter(DownloadQueue.library_type == library_type)

    active_downloads = dl_base.filter(
        DownloadQueue.status.in_([
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POST_PROCESSING
        ])
    ).count()

    completed_downloads = dl_base.filter(
        DownloadQueue.status == DownloadStatus.COMPLETED
    ).count()

    failed_downloads = dl_base.filter(
        DownloadQueue.status == DownloadStatus.FAILED
    ).count()

    # Album status breakdown
    from app.models.album import AlbumStatus

    if library_type != "audiobook":
        wanted_albums = db.query(Album).filter(
            Album.status == AlbumStatus.WANTED
        ).count()
        downloaded_albums = db.query(Album).filter(
            Album.status == AlbumStatus.DOWNLOADED
        ).count()
    else:
        wanted_albums = downloaded_albums = 0

    # Calculate total download size
    total_download_size = dl_base.filter(
        DownloadQueue.status == DownloadStatus.COMPLETED
    ).with_entities(
        func.sum(DownloadQueue.size_bytes)
    ).scalar() or 0

    # Disk usage
    import psutil
    disk_info = {}
    try:
        root_disk = psutil.disk_usage("/")
        disk_info["root"] = {
            "used_bytes": root_disk.used,
            "total_bytes": root_disk.total,
            "free_bytes": root_disk.free,
            "percent": root_disk.percent,
        }
        # Check /docker partition (mounted as /app/logs inside container)
        for check_path in ["/docker", "/app/logs"]:
            try:
                docker_disk = psutil.disk_usage(check_path)
                # Only include if it's a different device
                if docker_disk.total != root_disk.total:
                    disk_info["docker"] = {
                        "used_bytes": docker_disk.used,
                        "total_bytes": docker_disk.total,
                        "free_bytes": docker_disk.free,
                        "percent": docker_disk.percent,
                    }
                    break
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        pass

    # Audiobook stats
    total_authors = monitored_authors = total_books = wanted_books = downloaded_books = 0
    total_chapters = linked_chapters = 0
    if library_type != "music":
        try:
            from app.models.author import Author
            from app.models.book import Book as BookModel, BookStatus as BookStatusEnum
            from app.models.chapter import Chapter

            total_authors = db.query(Author).count()
            monitored_authors = db.query(Author).filter(Author.is_monitored == True).count()
            total_books = db.query(BookModel).count()
            wanted_books = db.query(BookModel).filter(BookModel.status == BookStatusEnum.WANTED).count()
            downloaded_books = db.query(BookModel).filter(BookModel.status == BookStatusEnum.DOWNLOADED).count()
            total_chapters = db.query(func.count(Chapter.id)).scalar() or 0
            linked_chapters = db.query(func.count(Chapter.id)).filter(Chapter.has_file == True).scalar() or 0
        except Exception:
            pass

    return {
        "monitored_artists": artists_count,
        "total_artists": total_artists,
        "monitored_albums": albums_count,
        "total_albums": total_albums,
        "wanted_albums": wanted_albums,
        "downloaded_albums": downloaded_albums,
        "linked_albums": linked_albums,
        "linked_tracks": linked_tracks,
        "total_tracks": total_tracks,
        "active_downloads": active_downloads,
        "completed_downloads": completed_downloads,
        "failed_downloads": failed_downloads,
        "total_download_size_bytes": total_download_size,
        "total_download_size": format_bytes(total_download_size),
        "disk": disk_info,
        # Audiobook stats
        "total_authors": total_authors,
        "monitored_authors": monitored_authors,
        "total_books": total_books,
        "wanted_books": wanted_books,
        "downloaded_books": downloaded_books,
        "total_chapters": total_chapters,
        "linked_chapters": linked_chapters,
    }


@app.get("/api/v1/statistics")
@limiter.limit("30/minute")
async def statistics_dashboard(request: Request, db: Session = Depends(get_db), library_type: Optional[str] = Query(None)):
    """
    Comprehensive statistics for the Statistics dashboard page.
    Returns album status breakdown, format distribution, download trends,
    quality distribution, and library file counts.
    """
    from app.models.artist import Artist
    from app.models.album import Album, AlbumStatus
    from app.models.track import Track
    from app.models.download_queue import DownloadQueue, DownloadStatus
    from app.models.library import LibraryFile, LibraryPath
    from app.models.job_state import JobState, JobStatus
    from app.models.author import Author
    from app.models.book import Book
    from app.models.chapter import Chapter
    from sqlalchemy import func, cast, Date
    from datetime import datetime, timezone, timedelta

    # --- Music stats (skip when audiobook-only) ---
    if library_type != "audiobook":
        album_statuses = db.query(
            Album.status, func.count(Album.id)
        ).group_by(Album.status).all()
        album_status_counts = {s.value: c for s, c in album_statuses}

        monitored_album_count = db.query(func.count(Album.id)).join(
            Artist, Album.artist_id == Artist.id
        ).filter(Album.monitored == True, Artist.is_monitored == True).scalar() or 0
        album_status_counts["monitored"] = monitored_album_count

        total_artists = db.query(func.count(Artist.id)).scalar() or 0
        monitored_artists = db.query(func.count(Artist.id)).filter(Artist.is_monitored == True).scalar() or 0
        total_albums = db.query(func.count(Album.id)).scalar() or 0
        total_tracks = db.query(func.count(Track.id)).scalar() or 0
        tracks_with_files = db.query(func.count(Track.id)).filter(Track.has_file == True).scalar() or 0
    else:
        album_status_counts = {}
        total_artists = monitored_artists = total_albums = total_tracks = tracks_with_files = 0

    # --- Library file format distribution (filter by library_type) ---
    lib_base = db.query(LibraryFile)
    if library_type:
        lib_base = lib_base.filter(LibraryFile.library_type == library_type)

    format_counts = lib_base.with_entities(
        LibraryFile.format, func.count(LibraryFile.id)
    ).group_by(LibraryFile.format).order_by(func.count(LibraryFile.id).desc()).all()

    # --- Library size ---
    total_library_size = lib_base.with_entities(func.sum(LibraryFile.file_size_bytes)).scalar() or 0
    total_library_files = lib_base.with_entities(func.count(LibraryFile.id)).scalar() or 0

    # --- Download trends (last 30 days, per day) ---
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    dl_trend_base = db.query(
        cast(DownloadQueue.completed_at, Date).label("day"),
        DownloadQueue.status,
        func.count(DownloadQueue.id)
    ).filter(
        DownloadQueue.completed_at >= thirty_days_ago,
        DownloadQueue.status.in_([DownloadStatus.COMPLETED, DownloadStatus.FAILED])
    )
    if library_type:
        dl_trend_base = dl_trend_base.filter(DownloadQueue.library_type == library_type)
    daily_downloads = dl_trend_base.group_by("day", DownloadQueue.status).order_by("day").all()

    # Build daily trend data
    trend_map = {}
    for day, dl_status, count in daily_downloads:
        day_str = str(day)
        if day_str not in trend_map:
            trend_map[day_str] = {"date": day_str, "completed": 0, "failed": 0}
        if dl_status == DownloadStatus.COMPLETED:
            trend_map[day_str]["completed"] = count
        elif dl_status == DownloadStatus.FAILED:
            trend_map[day_str]["failed"] = count

    # --- Recent job stats (last 7 days) ---
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    job_status_counts = db.query(
        JobState.status, func.count(JobState.id)
    ).filter(
        JobState.created_at >= seven_days_ago
    ).group_by(JobState.status).all()

    # --- MusicBrainz coverage (filter by library_type) ---
    mb_track_count = lib_base.filter(
        LibraryFile.musicbrainz_trackid.isnot(None)
    ).with_entities(func.count(LibraryFile.id)).scalar() or 0
    mb_album_count = lib_base.filter(
        LibraryFile.musicbrainz_albumid.isnot(None)
    ).with_entities(func.count(LibraryFile.id)).scalar() or 0
    files_linked = lib_base.filter(
        LibraryFile.mbid_in_file == True
    ).with_entities(func.count(LibraryFile.id)).scalar() or 0

    # --- Audiobook stats (skip when music-only) ---
    if library_type != "music":
        audiobooks_data = {
            "total_authors": db.query(func.count(Author.id)).scalar() or 0,
            "monitored_authors": db.query(func.count(Author.id)).filter(Author.is_monitored == True).scalar() or 0,
            "total_books": db.query(func.count(Book.id)).scalar() or 0,
            "total_chapters": db.query(func.count(Chapter.id)).scalar() or 0,
            "chapters_with_files": db.query(func.count(Chapter.id)).filter(Chapter.has_file == True).scalar() or 0,
        }
    else:
        audiobooks_data = {
            "total_authors": 0, "monitored_authors": 0,
            "total_books": 0, "total_chapters": 0, "chapters_with_files": 0,
        }

    return {
        "artists": {
            "total": total_artists,
            "monitored": monitored_artists,
        },
        "albums": {
            "total": total_albums,
            "status_breakdown": album_status_counts,
        },
        "tracks": {
            "total": total_tracks,
            "with_files": tracks_with_files,
            "file_percent": round(tracks_with_files / total_tracks * 100, 1) if total_tracks else 0,
        },
        "library": {
            "total_files": total_library_files,
            "total_size_bytes": total_library_size,
            "total_size": format_bytes(total_library_size),
            "format_distribution": [{"format": f or "unknown", "count": c} for f, c in format_counts],
            "musicbrainz_coverage": {
                "tracks_tagged": mb_track_count,
                "albums_tagged": mb_album_count,
                "files_linked": files_linked,
                "coverage_percent": round(mb_track_count / total_library_files * 100, 1) if total_library_files else 0,
            },
        },
        "downloads": {
            "daily_trend": sorted(trend_map.values(), key=lambda x: x["date"]),
        },
        "jobs_last_7d": {s.value: c for s, c in job_status_counts},
        "audiobooks": audiobooks_data,
    }


# Import and include API routers
from app.api import auth as auth_api
from app.api import artists, albums, indexers, muse, download_clients, playlists, library, admin, jobs, filesystem, media_management, file_management
from app.api import search, queue, root_folders, quality_profiles, notifications, queue_status, dj_requests
from app.api import settings as settings_api
from app.api import scheduler as scheduler_api
from app.api import now_playing
from app.api import authors, series as series_api, books
from app.api import storage_mounts as storage_mounts_api
from app.api import listen as listen_api
from app.api import book_progress as book_progress_api
from app.api import book_playlists as book_playlists_api

# Auth endpoints (login, user management)
app.include_router(auth_api.router, prefix="/api/v1", tags=["auth"])

# Admin endpoints (logging control, etc.)
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])

# Core routers with /api/v1 prefix
app.include_router(artists.router, prefix="/api/v1", tags=["artists"])
app.include_router(albums.router, prefix="/api/v1", tags=["albums"])
app.include_router(indexers.router, prefix="/api/v1", tags=["indexers"])
app.include_router(download_clients.router, prefix="/api/v1", tags=["download-clients"])
app.include_router(playlists.router, prefix="/api/v1", tags=["playlists"])
app.include_router(dj_requests.router, prefix="/api/v1", tags=["dj-requests"])
app.include_router(library.router, prefix="/api/v1", tags=["library"])
app.include_router(filesystem.router, prefix="/api/v1", tags=["filesystem"])
app.include_router(media_management.router, prefix="/api/v1", tags=["media-management"])

# Jobs API (Resilient job tracking system)
app.include_router(jobs.router)

# MUSE Integration (Phase 3)
app.include_router(muse.router, prefix="/api/v1", tags=["muse"])

# File Organization (MBID-based)
app.include_router(file_management.router, prefix="/api/v1/file-organization", tags=["file-management"])

# Root Folders and Quality Profiles (Lidarr-style workflow)
app.include_router(root_folders.router, prefix="/api/v1", tags=["root-folders"])
app.include_router(quality_profiles.router, prefix="/api/v1", tags=["quality-profiles"])

# Notifications (Webhook/Discord/Slack)
app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])

# Decision Engine - Search and Queue Management (Lidarr-style)
app.include_router(search.router, prefix="/api/v1/search", tags=["search"])
app.include_router(queue.router, prefix="/api/v1/queue", tags=["queue"])

# Queue Status Monitoring
app.include_router(queue_status.router, prefix="/api/v1", tags=["queue-status"])

# Settings (MusicBrainz, etc.)
app.include_router(settings_api.router, prefix="/api/v1", tags=["settings"])

# Job Scheduler
app.include_router(scheduler_api.router, prefix="/api/v1", tags=["scheduler"])

# Now Playing (Sound Booth live listeners)
app.include_router(now_playing.router, prefix="/api/v1", tags=["now-playing"])

# Storage Mounts (Dynamic volume management)
app.include_router(storage_mounts_api.router, prefix="/api/v1", tags=["storage-mounts"])

# Audiobook Library (Reading Room)
app.include_router(authors.router, prefix="/api/v1", tags=["authors"])
app.include_router(series_api.router, prefix="/api/v1", tags=["series"])
app.include_router(books.router, prefix="/api/v1", tags=["books"])

# Audiobook Progress (Resume Playback)
app.include_router(book_progress_api.router, prefix="/api/v1", tags=["book-progress"])

# Book Playlists (Series-ordered chapter playlists)
app.include_router(book_playlists_api.router, prefix="/api/v1", tags=["book-playlists"])

# Listen & Add (Audio Recognition)
app.include_router(listen_api.router, prefix="/api/v1", tags=["listen"])
