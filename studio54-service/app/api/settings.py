"""
Settings API
Centralized settings endpoints for Studio54 configuration
"""

import json
import os
import logging
from typing import Optional, List

import redis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.config import settings as app_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# --- MusicBrainz Settings ---

class MusicBrainzStats(BaseModel):
    artists: int = 0
    recordings: int = 0
    release_groups: int = 0
    releases: int = 0
    last_replication: Optional[str] = None
    replication_sequence: Optional[int] = None


class MusicBrainzSettingsResponse(BaseModel):
    local_db_enabled: bool
    local_db_url: str = ""
    local_db_status: str  # connected, disconnected, loading, not_configured
    local_db_stats: Optional[MusicBrainzStats] = None
    api_rate_limit: float = 1.0
    api_fallback_enabled: bool = True


class MusicBrainzSettingsUpdate(BaseModel):
    local_db_enabled: Optional[bool] = None
    api_rate_limit: Optional[float] = None


@router.get("/settings/musicbrainz", response_model=MusicBrainzSettingsResponse)
def get_musicbrainz_settings(current_user: User = Depends(require_director), db: Session = Depends(get_db)):
    """Get MusicBrainz configuration and status"""
    local_db_url = os.getenv("MUSICBRAINZ_LOCAL_DB_URL", "")
    local_db_enabled = os.getenv("MUSICBRAINZ_LOCAL_DB_ENABLED", "false").lower() == "true"
    api_rate_limit = float(os.getenv("MUSICBRAINZ_RATE_LIMIT", "1.0"))

    # Determine status
    status = "not_configured"
    stats = None

    if local_db_url and local_db_enabled:
        try:
            from app.services.musicbrainz_local import MusicBrainzLocalDB
            local_db = MusicBrainzLocalDB(local_db_url)

            if local_db.test_connection():
                status = "connected"
                raw_stats = local_db.get_stats()
                stats = MusicBrainzStats(
                    artists=raw_stats.get("artists", 0),
                    recordings=raw_stats.get("recordings", 0),
                    release_groups=raw_stats.get("release_groups", 0),
                    releases=raw_stats.get("releases", 0),
                    last_replication=raw_stats.get("last_replication"),
                    replication_sequence=raw_stats.get("replication_sequence"),
                )
            else:
                status = "loading"
        except Exception as e:
            logger.warning(f"Failed to connect to local MB DB: {e}")
            status = "disconnected"
    elif local_db_url:
        status = "disconnected"

    return MusicBrainzSettingsResponse(
        local_db_enabled=local_db_enabled,
        local_db_url=local_db_url,
        local_db_status=status,
        local_db_stats=stats,
        api_rate_limit=api_rate_limit,
        api_fallback_enabled=True,
    )


@router.put("/settings/musicbrainz", response_model=MusicBrainzSettingsResponse)
def update_musicbrainz_settings(
    settings_update: MusicBrainzSettingsUpdate,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Update MusicBrainz settings.

    Note: Changes to local_db_enabled and api_rate_limit are applied via
    environment variables. This endpoint updates the .env file and resets
    the singleton client to pick up changes immediately.
    """
    env_file = os.getenv("ENV_FILE_PATH", "/app/.env")

    if settings_update.local_db_enabled is not None:
        os.environ["MUSICBRAINZ_LOCAL_DB_ENABLED"] = str(settings_update.local_db_enabled).lower()

    if settings_update.api_rate_limit is not None:
        rate = max(0.1, min(10.0, settings_update.api_rate_limit))
        os.environ["MUSICBRAINZ_RATE_LIMIT"] = str(rate)

    # Reset the singleton client to pick up changes
    try:
        from app.services.musicbrainz_client import reset_musicbrainz_client
        reset_musicbrainz_client()
    except Exception as e:
        logger.warning(f"Failed to reset MB client: {e}")

    # Return current state
    return get_musicbrainz_settings(current_user=current_user, db=db)


@router.get("/settings/musicbrainz/search")
def search_musicbrainz_local(
    query: str,
    search_type: str = "artist",
    artist_filter: Optional[str] = None,
    limit: int = 10,
    current_user: User = Depends(require_director),
):
    """Search the local MusicBrainz database for artists, albums, or tracks"""
    if search_type not in ("artist", "album", "track"):
        raise HTTPException(status_code=400, detail="search_type must be artist, album, or track")

    if limit < 1 or limit > 50:
        limit = 10

    local_db_url = os.getenv("MUSICBRAINZ_LOCAL_DB_URL", "")
    local_db_enabled = os.getenv("MUSICBRAINZ_LOCAL_DB_ENABLED", "false").lower() == "true"

    if not local_db_url or not local_db_enabled:
        raise HTTPException(status_code=400, detail="Local MusicBrainz database is not configured or enabled")

    try:
        from app.services.musicbrainz_local import get_musicbrainz_local_db
        local_db = get_musicbrainz_local_db()
        if not local_db:
            raise HTTPException(status_code=503, detail="Local MusicBrainz database is not available")

        if search_type == "artist":
            results = local_db.search_artist(query, limit=limit)
        elif search_type == "album":
            results = local_db.search_release_group(query, artist_name=artist_filter, limit=limit)
        elif search_type == "track":
            results = local_db.search_recording(query, artist_name=artist_filter, limit=limit)
        else:
            results = []

        return {"results": results, "search_type": search_type, "query": query}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MusicBrainz local search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/settings/musicbrainz/test-connection")
def test_musicbrainz_connection(current_user: User = Depends(require_director)):
    """Test connection to local MusicBrainz database"""
    local_db_url = os.getenv("MUSICBRAINZ_LOCAL_DB_URL", "")

    if not local_db_url:
        return {
            "success": False,
            "message": "Local MusicBrainz database URL not configured",
        }

    try:
        from app.services.musicbrainz_local import MusicBrainzLocalDB
        local_db = MusicBrainzLocalDB(local_db_url)

        if local_db.test_connection():
            stats = local_db.get_stats()
            return {
                "success": True,
                "message": f"Connected. {stats.get('artists', 0):,} artists, {stats.get('recordings', 0):,} recordings.",
            }
        else:
            return {
                "success": False,
                "message": "Connected to database but no data found. Initial data load may still be in progress.",
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection failed: {str(e)}",
        }


# --- Worker Autoscale Settings ---

class WorkerInfoResponse(BaseModel):
    name: str
    active_tasks: int


class WorkerSettingsResponse(BaseModel):
    enabled: bool
    max_workers: int
    current_workers: int
    total_active_tasks: int
    workers: List[WorkerInfoResponse]
    at_capacity_since: Optional[float] = None
    idle_since: Optional[float] = None


class WorkerSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    max_workers: Optional[int] = Field(None, ge=1, le=10)


class WorkerScaleRequest(BaseModel):
    target: int = Field(..., ge=1, le=10)


@router.get("/settings/workers", response_model=WorkerSettingsResponse)
def get_worker_settings():
    """Get worker autoscale configuration and live status."""
    try:
        from app.services.worker_autoscaler import get_status
        status = get_status()
        return WorkerSettingsResponse(
            enabled=status.enabled,
            max_workers=status.max_workers,
            current_workers=status.current_workers,
            total_active_tasks=status.total_active_tasks,
            workers=[WorkerInfoResponse(**w) for w in status.workers],
            at_capacity_since=status.at_capacity_since,
            idle_since=status.idle_since,
        )
    except Exception as e:
        logger.error(f"Failed to get worker settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/settings/workers", response_model=WorkerSettingsResponse)
def update_worker_settings(update: WorkerSettingsUpdate):
    """Update worker autoscale configuration."""
    try:
        from app.services.worker_autoscaler import set_config, get_status
        set_config(enabled=update.enabled, max_workers=update.max_workers)
        status = get_status()
        return WorkerSettingsResponse(
            enabled=status.enabled,
            max_workers=status.max_workers,
            current_workers=status.current_workers,
            total_active_tasks=status.total_active_tasks,
            workers=[WorkerInfoResponse(**w) for w in status.workers],
            at_capacity_since=status.at_capacity_since,
            idle_since=status.idle_since,
        )
    except Exception as e:
        logger.error(f"Failed to update worker settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/workers/scale", response_model=WorkerSettingsResponse)
def manual_scale_workers(request: WorkerScaleRequest):
    """Manually scale workers to a target count."""
    try:
        from app.services.worker_autoscaler import scale_workers, get_status, get_worker_container_count, scale_down_one

        current = get_worker_container_count()
        target = request.target

        if target > current:
            success = scale_workers(target)
            if not success:
                raise HTTPException(status_code=500, detail="Failed to scale up workers")
        elif target < current:
            # Scale down one at a time
            for _ in range(current - target):
                scale_down_one()

        status = get_status()
        return WorkerSettingsResponse(
            enabled=status.enabled,
            max_workers=status.max_workers,
            current_workers=status.current_workers,
            total_active_tasks=status.total_active_tasks,
            workers=[WorkerInfoResponse(**w) for w in status.workers],
            at_capacity_since=status.at_capacity_since,
            idle_since=status.idle_since,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scale workers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Album Type Filter Settings ---

ALBUM_TYPE_FILTERS_KEY = "studio54:settings:album_type_filters"
DEFAULT_ALBUM_TYPE_FILTERS = ["Album", "EP", "Single", "Compilation", "Live", "Soundtrack", "Audiobook"]


def _get_redis():
    return redis.from_url(app_settings.redis_url, decode_responses=True)


class AlbumTypeFiltersResponse(BaseModel):
    enabled_types: List[str]


class AlbumTypeFiltersUpdate(BaseModel):
    enabled_types: List[str]


@router.get("/settings/album-type-filters", response_model=AlbumTypeFiltersResponse)
def get_album_type_filters():
    """Get default album type filters for artist pages"""
    try:
        r = _get_redis()
        stored = r.get(ALBUM_TYPE_FILTERS_KEY)
        if stored:
            return AlbumTypeFiltersResponse(enabled_types=json.loads(stored))
    except Exception as e:
        logger.warning(f"Failed to read album type filters from Redis: {e}")

    return AlbumTypeFiltersResponse(enabled_types=DEFAULT_ALBUM_TYPE_FILTERS)


@router.put("/settings/album-type-filters", response_model=AlbumTypeFiltersResponse)
def update_album_type_filters(update: AlbumTypeFiltersUpdate):
    """Update default album type filters for artist pages"""
    try:
        r = _get_redis()
        r.set(ALBUM_TYPE_FILTERS_KEY, json.dumps(update.enabled_types))
        return AlbumTypeFiltersResponse(enabled_types=update.enabled_types)
    except Exception as e:
        logger.error(f"Failed to save album type filters: {e}")
        raise HTTPException(status_code=500, detail=str(e))
