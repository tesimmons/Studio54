"""
Albums API Router
Album management and search endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Body, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, literal, or_
from app.utils.search import fuzzy_search_filter
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import logging
from pathlib import Path
import os

import httpx

from app.database import get_db
from app.auth import require_dj_or_above, require_any_user
from app.models.user import User
from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.track import Track
from app.models.track_rating import TrackRating
from app.models.download_queue import DownloadQueue, DownloadStatus
from app.security import rate_limit, validate_uuid, validate_mbid
from app.services.cover_art_service import save_entity_cover_art, serve_entity_cover_art

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request bodies
class AlbumUpdateRequest(BaseModel):
    monitored: Optional[bool] = None
    status: Optional[AlbumStatus] = None
    custom_folder_path: Optional[str] = None


class BulkAlbumUpdateRequest(BaseModel):
    album_ids: List[str]
    monitored: bool


class MonitorByTypeRequest(BaseModel):
    artist_id: str
    album_type: Optional[str] = None  # "Album", "EP", "Single", or None for all
    monitored: bool


@router.get("/albums")
@rate_limit("100/minute")
async def list_albums(
    request: Request,
    search_query: Optional[str] = Query(None, description="Search album title or artist name (fuzzy)"),
    status_filter: Optional[AlbumStatus] = Query(None, description="Filter by album status"),
    artist_id: Optional[str] = Query(None, description="Filter by artist ID"),
    monitored_only: bool = Query(False, description="Only return monitored albums"),
    in_library: Optional[bool] = Query(None, description="Filter by library status (true=downloaded, false=wanted/searching/etc)"),
    sort_by: Optional[str] = Query(None, description="Sort by: title, files_desc, files_asc, release_date, added_at"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List albums with filtering

    Args:
        status_filter: Filter by album status (wanted, downloading, downloaded, etc.)
        artist_id: Filter by artist ID
        monitored_only: Only return monitored albums
        in_library: Filter by library status (true=DOWNLOADED, false=WANTED/etc)
        limit: Results per page (1-1000)
        offset: Pagination offset

    Returns:
        List of albums with artist info
    """
    # Subquery for file stats per album (total tracks + linked files)
    file_stats_sq = (
        db.query(
            Track.album_id,
            func.count(Track.id).label("total_tracks"),
            func.sum(case((Track.has_file == True, 1), else_=0)).label("linked_count")
        )
        .group_by(Track.album_id)
        .subquery()
    )

    query = (
        db.query(Album, file_stats_sq.c.linked_count, file_stats_sq.c.total_tracks)
        .outerjoin(file_stats_sq, Album.id == file_stats_sq.c.album_id)
        .options(joinedload(Album.artist))
    )

    # Fuzzy search on album title and artist name
    _best_similarity = None
    if search_query:
        query = query.join(Artist, Album.artist_id == Artist.id)
        title_filter, title_sim = fuzzy_search_filter(Album.title, search_query)
        artist_filter, artist_sim = fuzzy_search_filter(Artist.name, search_query)

        query = query.filter(or_(title_filter, artist_filter))
        _best_similarity = func.greatest(title_sim, artist_sim)

    if status_filter:
        query = query.filter(Album.status == status_filter)

    if artist_id:
        validate_uuid(artist_id, "Artist ID")
        query = query.filter(Album.artist_id == artist_id)

    if monitored_only:
        query = query.filter(Album.monitored == True)

    # in_library filter: true=DOWNLOADED, false=not DOWNLOADED
    if in_library is not None:
        if in_library:
            query = query.filter(Album.status == AlbumStatus.DOWNLOADED)
        else:
            query = query.filter(Album.status != AlbumStatus.DOWNLOADED)

    total_count = query.with_entities(Album.id).count()

    # Apply sort order
    if sort_by == 'files_desc':
        query = query.order_by(
            (func.coalesce(file_stats_sq.c.linked_count, 0) * 100 /
             func.nullif(file_stats_sq.c.total_tracks, 0)).desc().nullslast(),
            func.coalesce(file_stats_sq.c.linked_count, 0).desc(),
            Album.title
        )
    elif sort_by == 'files_asc':
        query = query.order_by(
            (func.coalesce(file_stats_sq.c.linked_count, 0) * 100 /
             func.nullif(file_stats_sq.c.total_tracks, 0)).asc().nullsfirst(),
            func.coalesce(file_stats_sq.c.linked_count, 0).asc(),
            Album.title
        )
    elif sort_by == 'title':
        query = query.order_by(Album.title)
    elif sort_by == 'added_at':
        query = query.order_by(Album.added_at.desc().nullslast(), Album.title)
    elif _best_similarity is not None and sort_by is None:
        # When searching without explicit sort, order by relevance
        query = query.order_by(_best_similarity.desc(), Album.title)
    else:
        query = query.order_by(Album.release_date.desc().nullslast(), Album.title)

    results = query.limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "albums": [
            {
                "id": str(album.id),
                "title": album.title,
                "artist_id": str(album.artist_id),
                "artist_name": album.artist.name if album.artist else "Unknown",
                "musicbrainz_id": album.musicbrainz_id,
                "release_mbid": album.release_mbid,
                "release_date": album.release_date.isoformat() if album.release_date else None,
                "album_type": album.album_type,
                "status": album.status.value,
                "monitored": album.monitored,
                "track_count": album.track_count,
                "cover_art_url": album.cover_art_url,
                "custom_folder_path": album.custom_folder_path,
                "muse_verified": album.muse_verified,
                "linked_files_count": int(linked_count or 0)
            }
            for album, linked_count, total_tracks in results
        ]
    }


@router.get("/albums/wanted")
@rate_limit("100/minute")
async def get_wanted_albums(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get wanted albums (monitored albums not yet downloaded)

    Args:
        limit: Results per page
        offset: Pagination offset

    Returns:
        List of wanted albums
    """
    query = db.query(Album).options(joinedload(Album.artist)).filter(
        Album.monitored == True,
        Album.status == AlbumStatus.WANTED
    )

    total_count = query.with_entities(Album.id).count()
    albums = query.order_by(Album.release_date.desc().nullslast()).limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "wanted_albums": [
            {
                "id": str(album.id),
                "title": album.title,
                "artist_name": album.artist.name if album.artist else "Unknown",
                "release_date": album.release_date.isoformat() if album.release_date else None,
                "album_type": album.album_type,
                "track_count": album.track_count
            }
            for album in albums
        ]
    }


@router.get("/albums/calendar")
@rate_limit("100/minute")
async def get_calendar(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get upcoming album releases for monitored artists

    Args:
        start_date: Start date (ISO format, default: today)
        end_date: End date (ISO format, default: 30 days from now)

    Returns:
        List of upcoming releases
    """
    # Parse dates
    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date()
    else:
        start = datetime.now(timezone.utc).date()

    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00')).date()
    else:
        end = (datetime.now(timezone.utc) + timedelta(days=30)).date()

    # Query upcoming releases
    query = db.query(Album).join(Artist).options(joinedload(Album.artist)).filter(
        Artist.is_monitored == True,
        Album.release_date.isnot(None),
        Album.release_date >= start,
        Album.release_date <= end
    )

    albums = query.order_by(Album.release_date).all()

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_releases": len(albums),
        "releases": [
            {
                "id": str(album.id),
                "title": album.title,
                "artist_name": album.artist.name if album.artist else "Unknown",
                "release_date": album.release_date.isoformat() if album.release_date else None,
                "album_type": album.album_type,
                "status": album.status.value,
                "monitored": album.monitored
            }
            for album in albums
        ]
    }


@router.patch("/albums/bulk-update")
@rate_limit("20/minute")
async def bulk_update_albums(
    request: Request,
    bulk_request: BulkAlbumUpdateRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Bulk update monitoring status for multiple albums

    Args:
        bulk_request: Album IDs and monitored flag

    Returns:
        Count of updated albums
    """
    if not bulk_request.album_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="album_ids list cannot be empty"
        )

    for aid in bulk_request.album_ids:
        validate_uuid(aid, "Album ID")

    updated = db.query(Album).filter(
        Album.id.in_(bulk_request.album_ids)
    ).update(
        {"monitored": bulk_request.monitored, "updated_at": datetime.now(timezone.utc)},
        synchronize_session="fetch"
    )

    db.commit()

    logger.info(f"Bulk updated {updated} albums: monitored={bulk_request.monitored}")

    return {
        "success": True,
        "updated_count": updated,
        "monitored": bulk_request.monitored
    }


@router.post("/albums/monitor-by-type")
@rate_limit("20/minute")
async def monitor_by_type(
    request: Request,
    monitor_request: MonitorByTypeRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Monitor or unmonitor albums by type for a specific artist

    Args:
        monitor_request: Artist ID, album type filter, and monitored flag

    Returns:
        Count of updated albums
    """
    validate_uuid(monitor_request.artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == monitor_request.artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    query = db.query(Album).filter(Album.artist_id == monitor_request.artist_id)

    if monitor_request.album_type:
        query = query.filter(Album.album_type == monitor_request.album_type)

    updated = query.update(
        {"monitored": monitor_request.monitored, "updated_at": datetime.now(timezone.utc)},
        synchronize_session="fetch"
    )

    db.commit()

    type_label = monitor_request.album_type or "all"
    logger.info(
        f"Updated {updated} {type_label} albums for {artist.name}: "
        f"monitored={monitor_request.monitored}"
    )

    return {
        "success": True,
        "artist_id": monitor_request.artist_id,
        "artist_name": artist.name,
        "album_type": monitor_request.album_type,
        "updated_count": updated,
        "monitored": monitor_request.monitored
    }


@router.get("/downloads/cleanup/preview")
@rate_limit("20/minute")
async def preview_download_cleanup(
    request: Request,
    retention_days: int = Query(30, ge=1, le=365, description="Days of history to retain"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Preview download queue cleanup — shows counts of records that would be deleted.

    - COMPLETED downloads older than retention_days are always eligible.
    - FAILED downloads are only eligible if the album is NOT in WANTED status
      (preserves attempted_nzb_guids search history for albums still being searched).
    """
    from sqlalchemy import and_

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

    completed_count = db.query(DownloadQueue).filter(
        and_(
            DownloadQueue.status == DownloadStatus.COMPLETED,
            DownloadQueue.completed_at < cutoff_date
        )
    ).count()

    failed_downloads = db.query(DownloadQueue).filter(
        and_(
            DownloadQueue.status == DownloadStatus.FAILED,
            DownloadQueue.completed_at < cutoff_date
        )
    ).all()

    failed_eligible = 0
    for dl in failed_downloads:
        album = db.query(Album).filter(Album.id == dl.album_id).first()
        if not album or album.status != AlbumStatus.WANTED:
            failed_eligible += 1

    return {
        "retention_days": retention_days,
        "cutoff_date": cutoff_date.isoformat(),
        "completed_eligible": completed_count,
        "failed_eligible": failed_eligible,
        "total_eligible": completed_count + failed_eligible,
        "failed_preserved": len(failed_downloads) - failed_eligible,
    }


@router.post("/downloads/cleanup")
@rate_limit("10/minute")
async def execute_download_cleanup(
    request: Request,
    retention_days: int = Query(30, ge=1, le=365, description="Days of history to retain"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Execute download queue cleanup — deletes old completed/failed download records.

    Same logic as the daily automatic cleanup but triggered manually.
    """
    from sqlalchemy import and_

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

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
    failed_downloads = db.query(DownloadQueue).filter(
        and_(
            DownloadQueue.status == DownloadStatus.FAILED,
            DownloadQueue.completed_at < cutoff_date
        )
    ).all()

    failed_count = 0
    for dl in failed_downloads:
        album = db.query(Album).filter(Album.id == dl.album_id).first()
        if not album or album.status != AlbumStatus.WANTED:
            db.delete(dl)
            failed_count += 1

    db.commit()

    total_deleted = completed_count + failed_count
    logger.info(
        f"Manual download cleanup: {total_deleted} deleted "
        f"({completed_count} completed, {failed_count} failed, "
        f"retention={retention_days} days)"
    )

    return {
        "success": True,
        "retention_days": retention_days,
        "cutoff_date": cutoff_date.isoformat(),
        "completed_deleted": completed_count,
        "failed_deleted": failed_count,
        "total_deleted": total_deleted,
    }


@router.get("/albums/{album_id}")
@rate_limit("100/minute")
async def get_album(
    request: Request,
    album_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get album details

    Args:
        album_id: Album UUID

    Returns:
        Album object with tracks and download history
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()

    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    # Get tracks
    from app.models.track import Track
    tracks = db.query(Track).filter(Track.album_id == album_id).order_by(Track.disc_number, Track.track_number).all()

    # Get download history
    downloads = db.query(DownloadQueue).filter(DownloadQueue.album_id == album_id).all()

    # Batch-fetch current user's ratings and rating counts for all tracks in this album
    track_ids = [t.id for t in tracks]
    user_ratings_map = {}
    rating_counts_map = {}
    if track_ids:
        user_ratings = db.query(TrackRating.track_id, TrackRating.rating).filter(
            TrackRating.track_id.in_(track_ids),
            TrackRating.user_id == current_user.id,
        ).all()
        user_ratings_map = {str(tr.track_id): tr.rating for tr in user_ratings}

        rating_counts = db.query(
            TrackRating.track_id, func.count(TrackRating.id)
        ).filter(
            TrackRating.track_id.in_(track_ids)
        ).group_by(TrackRating.track_id).all()
        rating_counts_map = {str(tc[0]): tc[1] for tc in rating_counts}

    return {
        "id": str(album.id),
        "title": album.title,
        "artist_id": str(album.artist_id),
        "artist_name": album.artist.name if album.artist else "Unknown",
        "musicbrainz_id": album.musicbrainz_id,
        "release_mbid": album.release_mbid,
        "release_date": album.release_date.isoformat() if album.release_date else None,
        "album_type": album.album_type,
        "status": album.status.value,
        "monitored": album.monitored,
        "cover_art_url": album.cover_art_url,
        "custom_folder_path": album.custom_folder_path,
        "track_count": len(tracks),
        "muse_library_id": str(album.muse_library_id) if album.muse_library_id else None,
        "muse_verified": album.muse_verified,
        "added_at": album.added_at.isoformat() if album.added_at else None,
        "updated_at": album.updated_at.isoformat() if album.updated_at else None,
        "tracks": [
            {
                "id": str(track.id),
                "title": track.title,
                "track_number": track.track_number,
                "disc_number": track.disc_number,
                "duration_ms": track.duration_ms,
                "has_file": track.has_file,
                "file_path": track.file_path,
                "muse_file_id": str(track.muse_file_id) if track.muse_file_id else None,
                "musicbrainz_id": track.musicbrainz_id,
                "rating": track.rating,
                "average_rating": track.average_rating,
                "user_rating": user_ratings_map.get(str(track.id)),
                "rating_count": rating_counts_map.get(str(track.id), 0),
            }
            for track in tracks
        ],
        "downloads": [
            {
                "id": str(download.id),
                "nzb_title": download.nzb_title,
                "status": download.status.value,
                "progress_percent": download.progress_percent,
                "size_bytes": download.size_bytes,
                "error_message": download.error_message,
                "queued_at": download.queued_at.isoformat() if download.queued_at else None,
                "completed_at": download.completed_at.isoformat() if download.completed_at else None
            }
            for download in downloads
        ]
    }


@router.patch("/albums/{album_id}")
@rate_limit("50/minute")
async def update_album(
    request: Request,
    album_id: str,
    updates: AlbumUpdateRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Update album settings

    Args:
        album_id: Album UUID
        updates: Album update fields (monitored, status, custom_folder_path)

    Returns:
        Updated album object
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()

    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    try:
        if updates.monitored is not None:
            album.monitored = updates.monitored

        if updates.status is not None:
            album.status = updates.status

        if updates.custom_folder_path is not None:
            album.custom_folder_path = updates.custom_folder_path

        album.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(album)

        # Create folder if album is now monitored
        if updates.monitored is True:
            try:
                from app.services.folder_creator import get_folder_creator
                artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
                if artist:
                    folder_creator = get_folder_creator(db)
                    success, folder_path, error = folder_creator.create_album_folder(album, artist)
                    if success:
                        logger.info(f"Created folder for monitored album {album.title}: {folder_path}")
                    elif error:
                        logger.warning(f"Failed to create folder for album {album.title}: {error}")
            except Exception as e:
                logger.error(f"Error creating folder for album {album.title}: {e}", exc_info=True)

        logger.info(f"Updated album: {album.title} (ID: {album_id})")

        return {
            "id": str(album.id),
            "title": album.title,
            "monitored": album.monitored,
            "status": album.status.value,
            "custom_folder_path": album.custom_folder_path,
            "updated_at": album.updated_at.isoformat()
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update album: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update album: {str(e)}"
        )


@router.post("/albums/{album_id}/search")
@rate_limit("20/minute")
async def search_album(
    request: Request,
    album_id: str,
    skip_muse_check: bool = Query(False, description="Skip MUSE verification before searching"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Trigger manual album search

    Before searching indexers, optionally checks if album already exists
    in MUSE library to prevent duplicate downloads.

    Args:
        album_id: Album UUID
        skip_muse_check: Skip MUSE existence check (force search)

    Returns:
        Search task info or MUSE skip notification
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()

    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    try:
        # Check MUSE library first (unless skipped)
        if not skip_muse_check and album.musicbrainz_id:
            from app.services.muse_client import get_muse_client
            muse_client = get_muse_client()

            exists, file_count = muse_client.album_exists(
                musicbrainz_id=album.musicbrainz_id,
                min_track_count=album.track_count or 1
            )

            if exists:
                # Album already in MUSE - mark as downloaded and skip search
                album.status = AlbumStatus.DOWNLOADED
                album.muse_verified = True
                db.commit()

                logger.info(
                    f"Album already in MUSE: {album.title} "
                    f"({file_count} files) - skipping search"
                )

                return {
                    "success": True,
                    "album_id": str(album.id),
                    "album_title": album.title,
                    "already_exists": True,
                    "file_count": file_count,
                    "message": f"Album already exists in MUSE library ({file_count} files)"
                }

        # Album not in MUSE - trigger search
        from app.tasks.download_tasks import search_album as search_album_task
        from app.models.job_state import JobType

        # Create folder before searching
        try:
            from app.services.folder_creator import get_folder_creator
            artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
            if artist:
                folder_creator = get_folder_creator(db)
                success, folder_path, error = folder_creator.create_album_folder(album, artist)
                if success:
                    logger.info(f"Created folder for album search {album.title}: {folder_path}")
                elif error:
                    logger.warning(f"Failed to create folder for album {album.title}: {error}")
        except Exception as e:
            logger.error(f"Error creating folder for album {album.title}: {e}", exc_info=True)

        task = search_album_task.apply_async(
            args=[str(album.id)],
            kwargs={
                'job_type': JobType.ALBUM_SEARCH,
                'entity_type': 'album',
                'entity_id': str(album.id)
            }
        )

        logger.info(f"Triggered manual search for album: {album.title} (ID: {album_id})")

        return {
            "success": True,
            "album_id": str(album.id),
            "album_title": album.title,
            "artist_name": album.artist.name if album.artist else "Unknown",
            "message": "Album search started",
            "task_id": task.id,
            "already_exists": False
        }

    except Exception as e:
        logger.error(f"Failed to trigger album search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger album search: {str(e)}"
        )


@router.post("/albums/{album_id}/verify-muse")
@rate_limit("20/minute")
async def verify_muse(
    request: Request,
    album_id: str,
    update_status: bool = Query(True, description="Update album status if found in MUSE"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Verify if album exists in MUSE library

    Checks MUSE library for album by MusicBrainz ID. Optionally updates
    album status to DOWNLOADED if found.

    Args:
        album_id: Album UUID
        update_status: Update album status to DOWNLOADED if found in MUSE

    Returns:
        MUSE verification status with file count
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()

    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    if not album.musicbrainz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Album has no MusicBrainz ID"
        )

    try:
        from app.services.muse_client import get_muse_client
        muse_client = get_muse_client()

        # Check if album exists in MUSE
        exists, file_count = muse_client.album_exists(
            musicbrainz_id=album.musicbrainz_id,
            min_track_count=album.track_count or 1
        )

        # Update album status if requested
        if update_status and exists:
            album.status = AlbumStatus.DOWNLOADED
            album.muse_verified = True
            db.commit()

        logger.info(
            f"MUSE verification for {album.title}: "
            f"exists={exists}, files={file_count}"
        )

        return {
            "success": True,
            "album_id": str(album.id),
            "album_title": album.title,
            "musicbrainz_id": album.musicbrainz_id,
            "exists_in_muse": exists,
            "file_count": file_count or 0,
            "muse_verified": album.muse_verified,
            "status": album.status.value,
            "message": (
                f"Album found in MUSE ({file_count} files)" if exists
                else "Album not found in MUSE library"
            )
        }

    except Exception as e:
        logger.error(f"Failed to verify MUSE status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to verify MUSE status: {str(e)}"
        )


@router.post("/albums/{album_id}/scan-files")
@rate_limit("10/minute")
async def scan_album_files(
    request: Request,
    album_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Scan an album's custom folder path and match audio files to tracks

    This endpoint:
    1. Scans the custom_folder_path for audio files
    2. Extracts metadata from each file
    3. Matches files to tracks based on track number, title, duration
    4. Updates track records with file paths and sets has_file=True

    Args:
        album_id: Album UUID

    Returns:
        Match results including:
        - files_found: Total audio files discovered
        - matches: Number of successful track-to-file matches
        - unmatched_files: List of files that couldn't be matched
        - unmatched_tracks: List of tracks without files
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    if not album.custom_folder_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Album does not have a custom_folder_path set. Please set one first."
        )

    try:
        from app.services.album_file_matcher import AlbumFileMatcher

        matcher = AlbumFileMatcher(db)
        results = matcher.scan_and_match_album(album_id)

        # Update album status if files were matched
        if results['matches'] > 0:
            # Check if all tracks have files
            total_tracks = len(album.tracks)
            matched_tracks = results['matches']

            if matched_tracks == total_tracks:
                album.status = AlbumStatus.DOWNLOADED
                logger.info(f"All {total_tracks} tracks matched - marking album as DOWNLOADED")
            elif matched_tracks > 0:
                # Partial match - keep current status but log it
                logger.info(f"Partial match: {matched_tracks}/{total_tracks} tracks found")

            album.updated_at = datetime.now(timezone.utc)
            db.commit()

        return {
            "success": True,
            **results
        }

    except ValueError as e:
        logger.error(f"Validation error scanning album files: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to scan album files: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scan album files: {str(e)}"
        )


@router.post("/albums/{album_id}/link-track")
@rate_limit("50/minute")
async def manually_link_track(
    request: Request,
    album_id: str,
    track_id: str = Query(..., description="Track UUID to link"),
    file_path: str = Query(..., description="Absolute path to audio file"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Manually link a track to an audio file

    This endpoint allows manual selection when automatic matching fails
    or when you want to override the automatic match.

    Args:
        album_id: Album UUID (for validation)
        track_id: Track UUID to link
        file_path: Absolute path to the audio file

    Returns:
        Success confirmation with updated track info
    """
    validate_uuid(album_id, "Album ID")
    validate_uuid(track_id, "Track ID")

    # Verify album exists
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    try:
        from app.services.album_file_matcher import AlbumFileMatcher

        matcher = AlbumFileMatcher(db)
        success = matcher.manually_link_track(track_id, file_path)

        return {
            "success": success,
            "track_id": track_id,
            "file_path": file_path,
            "message": "Track successfully linked to file"
        }

    except ValueError as e:
        logger.error(f"Validation error linking track: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to link track to file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to link track: {str(e)}"
        )


@router.post("/albums/{album_id}/unlink-track")
@rate_limit("50/minute")
async def unlink_track(
    request: Request,
    album_id: str,
    track_id: str = Query(..., description="Track UUID to unlink"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Unlink a track from its audio file

    This removes the file_path association, allowing you to relink
    the track to a different file.

    Args:
        album_id: Album UUID (for validation)
        track_id: Track UUID to unlink

    Returns:
        Success confirmation
    """
    validate_uuid(album_id, "Album ID")
    validate_uuid(track_id, "Track ID")

    # Verify album exists
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    # Get track
    track = db.query(Track).filter(Track.id == track_id, Track.album_id == album_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    # Unlink the file
    old_file_path = track.file_path
    track.file_path = None
    track.has_file = False
    db.commit()

    logger.info(f"Unlinked track '{track.title}' from file {old_file_path}")

    return {
        "success": True,
        "track_id": track_id,
        "message": "Track successfully unlinked from file",
        "previous_file_path": old_file_path
    }


@router.get("/albums/{album_id}/import-preview")
@rate_limit("20/minute")
async def preview_album_import(
    request: Request,
    album_id: str,
    source_directory: str = Query(..., description="Directory containing downloaded files"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Preview how files will be organized when imported

    Shows what file paths will be created based on naming templates
    and media management settings. Does not modify any files.

    Args:
        album_id: Album UUID
        source_directory: Directory containing audio files to import

    Returns:
        Preview of file operations including:
        - source: Original filename
        - destination: New file path (relative to music library)
        - quality: Detected quality information
        - size_mb: File size in megabytes
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    # Validate source directory
    source_path = Path(source_directory)
    if not source_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source directory does not exist: {source_directory}"
        )

    try:
        from app.services.enhanced_import_service import EnhancedImportService

        service = EnhancedImportService(db)
        preview = service.get_import_preview(album, source_directory)

        logger.info(f"Generated import preview for album: {album.title} ({len(preview)} files)")

        return {
            "success": True,
            "album_id": str(album.id),
            "album_title": album.title,
            "source_directory": source_directory,
            "file_count": len(preview),
            "preview": preview
        }

    except Exception as e:
        logger.error(f"Failed to generate import preview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate import preview: {str(e)}"
        )


@router.post("/albums/{album_id}/import")
@rate_limit("10/minute")
async def import_album_files(
    request: Request,
    album_id: str,
    source_directory: str = Query(..., description="Directory containing downloaded files"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Import and organize album files using Lidarr-style file handling

    This endpoint:
    1. Analyzes audio quality of all files
    2. Applies minimum quality and size filters
    3. Builds organized paths using naming templates
    4. Checks for upgrades to existing files
    5. Imports files with atomic operations (rollback on failure)
    6. Updates track records with new file paths
    7. Cleans up empty folders
    8. Triggers MUSE library scan

    Args:
        album_id: Album UUID
        source_directory: Directory containing downloaded audio files

    Returns:
        Import results including:
        - imported_files: Successfully imported files
        - upgraded_files: Files that replaced lower quality versions
        - skipped_files: Files that didn't meet quality/size requirements
        - errors: Any errors encountered during import
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    # Validate source directory
    source_path = Path(source_directory)
    if not source_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source directory does not exist: {source_directory}"
        )

    try:
        from app.services.enhanced_import_service import EnhancedImportService

        service = EnhancedImportService(db)
        results = service.import_album(album, source_directory)

        # Update album status if files were imported
        if results['success'] and results['imported_files']:
            album.status = AlbumStatus.DOWNLOADED
            album.updated_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(
                f"Successfully imported album: {album.title} "
                f"({len(results['imported_files'])} files)"
            )

        return {
            **results,
            "album_id": str(album.id),
            "album_title": album.title
        }

    except FileNotFoundError as e:
        logger.error(f"Import failed - file not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to import album: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import album: {str(e)}"
        )


@router.post("/tracks/{track_id}/search")
@rate_limit("20/minute")
async def search_track(
    request: Request,
    track_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Search Usenet for a single track by artist + track title.

    Uses the same search pipeline as album search but queries with
    the track title instead of the album title.
    """
    validate_uuid(track_id, "Track ID")

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    album = db.query(Album).filter(Album.id == track.album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found for track"
        )

    artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found for album"
        )

    try:
        from app.tasks.download_tasks import search_album as search_album_task
        from app.models.job_state import JobType

        task = search_album_task.apply_async(
            args=[str(album.id)],
            kwargs={
                'job_type': JobType.ALBUM_SEARCH,
                'entity_type': 'album',
                'entity_id': str(album.id),
                'track_title': track.title,
            }
        )

        logger.info(f"Triggered track search: {artist.name} - {track.title} (album: {album.title})")

        return {
            "success": True,
            "album_id": str(album.id),
            "album_title": album.title,
            "track_id": str(track.id),
            "track_title": track.title,
            "artist_name": artist.name,
            "message": f"Track search started: {track.title}",
            "task_id": task.id,
        }

    except Exception as e:
        logger.error(f"Failed to trigger track search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger track search: {str(e)}"
        )


@router.delete("/tracks/{track_id}/file")
@rate_limit("30/minute")
async def delete_track_file(
    request: Request,
    track_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Delete the physical audio file for a track and unlink it.

    Removes the file from disk, sets has_file=False and file_path=None,
    and cleans up empty parent directories up to the artist root.
    """
    validate_uuid(track_id, "Track ID")

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    if not track.has_file or not track.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Track does not have a file linked"
        )

    file_path = Path(track.file_path)
    deleted_path = str(track.file_path)

    # Delete the physical file
    if file_path.exists():
        try:
            os.remove(str(file_path))
            logger.info(f"Deleted file: {file_path}")
        except OSError as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete file: {str(e)}"
            )
    else:
        logger.warning(f"File not found on disk (already missing): {file_path}")

    # Unlink the track
    track.has_file = False
    track.file_path = None
    db.commit()

    # Clean up empty parent directories (up to 3 levels)
    parent = file_path.parent
    for _ in range(3):
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                logger.info(f"Removed empty directory: {parent}")
                parent = parent.parent
            else:
                break
        except OSError:
            break

    logger.info(f"Deleted file and unlinked track '{track.title}' (was: {deleted_path})")

    return {
        "success": True,
        "message": "File deleted",
        "track_id": track_id,
        "deleted_path": deleted_path
    }


@router.get("/tracks/{track_id}/stream")
@rate_limit("100/minute")
async def stream_track(
    request: Request,
    track_id: str,
    token: str = Query(None, description="JWT token for audio element auth"),
    db: Session = Depends(get_db)
):
    """
    Stream audio file for a track

    Serves the audio file associated with the track for playback.
    Returns 404 if track doesn't have a file linked.
    Accepts auth via Bearer header OR ?token= query parameter (for HTML audio elements).
    """
    from app.auth import get_current_user, bearer_scheme
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = await bearer_scheme(request)
    if credentials:
        await get_current_user(credentials, db)
    elif token:
        fake_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        await get_current_user(fake_creds, db)
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    validate_uuid(track_id, "Track ID")

    # Get track with file path (check tracks first, then chapters for audiobooks)
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        from app.models.chapter import Chapter
        chapter = db.query(Chapter).filter(Chapter.id == track_id).first()
        if not chapter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Track not found"
            )
        # Use chapter as a duck-typed track
        track = chapter

    if not track.file_path or not track.has_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track does not have a file linked"
        )

    # Verify file exists
    file_path = Path(track.file_path)
    if not file_path.exists():
        logger.error(f"Track {track_id} references non-existent file: {track.file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio file not found: {track.file_path}"
        )

    # Determine media type based on extension
    ext = file_path.suffix.lower()
    media_type_map = {
        '.mp3': 'audio/mpeg',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4',
        '.aac': 'audio/aac',
        '.ogg': 'audio/ogg',
        '.opus': 'audio/opus',
        '.wav': 'audio/wav',
        '.wma': 'audio/x-ms-wma',
    }
    media_type = media_type_map.get(ext, 'audio/mpeg')

    # Return streaming response with inline disposition for browser playback
    # Sanitize filename for Content-Disposition header (must be latin-1 safe)
    safe_name = file_path.name.encode('ascii', 'replace').decode('ascii')
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Accept-Ranges": "bytes",
        }
    )


@router.get("/tracks/{track_id}/download")
@rate_limit("60/minute")
async def download_track(
    request: Request,
    track_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Download audio file for a track (browser save).

    Same file lookup as stream_track, but with Content-Disposition: attachment
    to trigger browser save dialog. Requires DJ or above role.

    Args:
        track_id: Track UUID

    Returns:
        Audio file as attachment download
    """
    validate_uuid(track_id, "Track ID")

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    if not track.file_path or not track.has_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track does not have a file linked"
        )

    file_path = Path(track.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio file not found: {track.file_path}"
        )

    ext = file_path.suffix.lower()
    media_type_map = {
        '.mp3': 'audio/mpeg',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4',
        '.aac': 'audio/aac',
        '.ogg': 'audio/ogg',
        '.opus': 'audio/opus',
        '.wav': 'audio/wav',
        '.wma': 'audio/x-ms-wma',
    }
    media_type = media_type_map.get(ext, 'audio/mpeg')

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_path.name.encode("ascii", "replace").decode("ascii")}"',
        }
    )


@router.delete("/albums/{album_id}/downloads")
@rate_limit("30/minute")
async def clear_album_downloads(
    request: Request,
    album_id: str,
    status_filter: Optional[str] = Query(None, description="Only clear downloads with this status (e.g., 'failed')"),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Clear download history for an album and reset album status

    Args:
        album_id: Album UUID
        status_filter: Optional - only clear downloads with this status ('failed', 'completed', etc.)

    Returns:
        Summary of cleared downloads
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    query = db.query(DownloadQueue).filter(DownloadQueue.album_id == album_id)

    if status_filter:
        try:
            filter_status = DownloadStatus(status_filter.lower())
            query = query.filter(DownloadQueue.status == filter_status)
        except (ValueError, KeyError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status filter: {status_filter}"
            )

    downloads = query.all()
    cleared_count = len(downloads)

    for download in downloads:
        db.delete(download)

    # Reset album status to WANTED if it was FAILED and we cleared the failed downloads
    if album.status in (AlbumStatus.FAILED,) and (not status_filter or status_filter.lower() == "failed"):
        album.status = AlbumStatus.WANTED
        album.updated_at = datetime.now(timezone.utc)

    db.commit()

    logger.info(f"Cleared {cleared_count} downloads for album {album.title} (filter: {status_filter})")

    return {
        "cleared": cleared_count,
        "album_id": str(album.id),
        "album_status": album.status.value
    }


@router.post("/albums/{album_id}/prefetch-lyrics")
@rate_limit("10/minute")
async def prefetch_album_lyrics(
    request: Request,
    album_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Prefetch lyrics for all tracks in an album from LRCLIB.

    Skips tracks that already have cached lyrics. Results are cached in DB
    for subsequent requests via the /tracks/{id}/lyrics endpoint.

    Args:
        album_id: Album UUID

    Returns:
        Summary of fetched/cached/failed counts
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found"
        )

    tracks = (
        db.query(Track)
        .filter(Track.album_id == album_id)
        .order_by(Track.track_number)
        .all()
    )

    artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
    artist_name = artist.name if artist else None
    album_title = album.title

    total = len(tracks)
    already_cached = 0
    fetched = 0
    failed = 0

    try:
        import httpx

        headers = {"User-Agent": "Studio54/1.0"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            for track in tracks:
                # Skip if already cached (non-empty lyrics or empty string meaning "looked up, not found")
                if track.synced_lyrics is not None or track.plain_lyrics is not None:
                    already_cached += 1
                    continue

                if not artist_name or not track.title:
                    failed += 1
                    continue

                synced_lyrics = None
                plain_lyrics = None
                source = None

                try:
                    params = {
                        "artist_name": artist_name,
                        "track_name": track.title,
                    }
                    if album_title:
                        params["album_name"] = album_title
                    duration_sec = round(track.duration_ms / 1000) if track.duration_ms else None
                    if duration_sec:
                        params["duration"] = str(duration_sec)

                    resp = await client.get(
                        "https://lrclib.net/api/get",
                        params=params,
                        headers=headers,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        synced_lyrics = data.get("syncedLyrics") or None
                        plain_lyrics = data.get("plainLyrics") or None
                        if synced_lyrics or plain_lyrics:
                            source = "lrclib"

                    # Fallback: search
                    if not synced_lyrics and not plain_lyrics:
                        search_resp = await client.get(
                            "https://lrclib.net/api/search",
                            params={"q": f"{artist_name} {track.title}"},
                            headers=headers,
                        )
                        if search_resp.status_code == 200:
                            results = search_resp.json()
                            if results and len(results) > 0:
                                best = results[0]
                                synced_lyrics = best.get("syncedLyrics") or None
                                plain_lyrics = best.get("plainLyrics") or None
                                if synced_lyrics or plain_lyrics:
                                    source = "lrclib"

                    # Cache in DB
                    track.synced_lyrics = synced_lyrics or ""
                    track.plain_lyrics = plain_lyrics or ""
                    track.lyrics_source = source

                    if synced_lyrics or plain_lyrics:
                        fetched += 1
                    else:
                        failed += 1

                except Exception as e:
                    logger.warning(f"Failed to fetch lyrics for track {track.id} ({track.title}): {e}")
                    # Cache empty to avoid re-fetching
                    track.synced_lyrics = ""
                    track.plain_lyrics = ""
                    track.lyrics_source = None
                    failed += 1

        db.commit()

    except Exception as e:
        logger.error(f"Failed to prefetch lyrics for album {album_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prefetch lyrics: {str(e)}"
        )

    logger.info(
        f"Prefetched lyrics for album {album.title}: "
        f"{fetched} fetched, {already_cached} cached, {failed} failed"
    )

    return {
        "total": total,
        "fetched": fetched,
        "already_cached": already_cached,
        "failed": failed,
    }


@router.post("/tracks/{track_id}/record-play")
@rate_limit("200/minute")
async def record_play(
    request: Request,
    track_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Record a play for a track. Increments play_count and sets last_played_at.
    Called by the frontend when a track finishes playing naturally.
    """
    validate_uuid(track_id, "Track ID")

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    track.play_count = (track.play_count or 0) + 1
    track.last_played_at = datetime.now(timezone.utc)
    db.commit()

    return {"play_count": track.play_count}


@router.get("/tracks/top")
@rate_limit("100/minute")
async def get_top_tracks(
    request: Request,
    artist_id: str = Query(..., description="Artist ID (required)"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get top tracks for an artist based on local play counts.

    If 5+ tracks for this artist have play_count > 0, returns top N by play_count.
    Otherwise returns tracks with files ordered by album release date (newest first).

    Returns:
        source: "play_count" or "newest"
        tracks: list of track objects
    """
    validate_uuid(artist_id, "Artist ID")

    # Check how many tracks have plays
    played_count = (
        db.query(func.count(Track.id))
        .join(Album, Track.album_id == Album.id)
        .filter(Album.artist_id == artist_id, Track.has_file == True, Track.play_count > 0)
        .scalar()
    ) or 0

    if played_count > 0:
        # Return by play count
        tracks = (
            db.query(Track)
            .join(Album, Track.album_id == Album.id)
            .join(Artist, Album.artist_id == Artist.id)
            .options(joinedload(Track.album).joinedload(Album.artist))
            .filter(Album.artist_id == artist_id, Track.has_file == True, Track.play_count > 0)
            .order_by(Track.play_count.desc())
            .limit(limit)
            .all()
        )
        source = "play_count"
    else:
        # Return newest tracks with files
        tracks = (
            db.query(Track)
            .join(Album, Track.album_id == Album.id)
            .join(Artist, Album.artist_id == Artist.id)
            .options(joinedload(Track.album).joinedload(Album.artist))
            .filter(Album.artist_id == artist_id, Track.has_file == True)
            .order_by(Album.release_date.desc().nullslast(), Track.track_number.asc())
            .limit(limit)
            .all()
        )
        source = "newest"

    return {
        "source": source,
        "tracks": [
            {
                "id": str(t.id),
                "title": t.title,
                "track_number": t.track_number,
                "disc_number": t.disc_number,
                "duration_ms": t.duration_ms,
                "has_file": t.has_file,
                "file_path": t.file_path,
                "musicbrainz_id": t.musicbrainz_id,
                "play_count": t.play_count or 0,
                "rating": t.rating,
                "average_rating": t.average_rating,
                "album_id": str(t.album_id),
                "album_title": t.album.title if t.album else "Unknown",
                "album_cover_art_url": t.album.cover_art_url if t.album else None,
                "artist_id": str(t.album.artist_id) if t.album else None,
                "artist_name": t.album.artist.name if t.album and t.album.artist else "Unknown",
            }
            for t in tracks
        ]
    }


@router.get("/tracks")
@rate_limit("100/minute")
async def list_tracks(
    request: Request,
    search_query: Optional[str] = Query(None, description="Search tracks by title"),
    has_file: Optional[bool] = Query(None, description="Filter by file availability"),
    artist_id: Optional[str] = Query(None, description="Filter by artist ID"),
    album_id: Optional[str] = Query(None, description="Filter by album ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List tracks with album and artist info

    Args:
        search_query: Filter by track title (case-insensitive)
        has_file: Filter by file availability (true=has file, false=missing)
        artist_id: Filter by artist ID
        album_id: Filter by album ID
        limit: Results per page (1-500)
        offset: Pagination offset

    Returns:
        List of tracks with album and artist details
    """
    query = (
        db.query(Track)
        .join(Album, Track.album_id == Album.id)
        .join(Artist, Album.artist_id == Artist.id)
        .options(
            joinedload(Track.album).joinedload(Album.artist)
        )
    )

    _best_track_similarity = None
    if search_query:

        title_filter, title_sim = fuzzy_search_filter(Track.title, search_query)
        artist_filter, artist_sim = fuzzy_search_filter(Artist.name, search_query)
        album_filter, album_sim = fuzzy_search_filter(Album.title, search_query)
        query = query.filter(or_(title_filter, artist_filter, album_filter))
        _best_track_similarity = func.greatest(title_sim, artist_sim, album_sim)

    if has_file is not None:
        query = query.filter(Track.has_file == has_file)

    if artist_id:
        validate_uuid(artist_id, "Artist ID")
        query = query.filter(Album.artist_id == artist_id)

    if album_id:
        validate_uuid(album_id, "Album ID")
        query = query.filter(Track.album_id == album_id)

    total_count = query.with_entities(Track.id).count()

    if _best_track_similarity is not None:
        order_clause = (_best_track_similarity.desc(), Artist.name, Album.title, Track.disc_number, Track.track_number)
    else:
        order_clause = (Artist.name, Album.title, Track.disc_number, Track.track_number)

    tracks = (
        query.order_by(*order_clause)
        .limit(limit)
        .offset(offset)
        .all()
    )

    def get_file_format(file_path: str) -> str | None:
        if not file_path:
            return None
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else None
        return ext

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "tracks": [
            {
                "id": str(track.id),
                "title": track.title,
                "track_number": track.track_number,
                "disc_number": track.disc_number,
                "duration_ms": track.duration_ms,
                "has_file": track.has_file,
                "file_path": track.file_path,
                "file_format": get_file_format(track.file_path),
                "musicbrainz_id": track.musicbrainz_id,
                "album_id": str(track.album_id),
                "album_title": track.album.title if track.album else "Unknown",
                "album_cover_art_url": track.album.cover_art_url if track.album else None,
                "artist_id": str(track.album.artist_id) if track.album else None,
                "artist_name": track.album.artist.name if track.album and track.album.artist else "Unknown",
                "monitored": track.album.monitored if track.album else False,
                "rating": track.rating,
                "average_rating": track.average_rating,
            }
            for track in tracks
        ]
    }


@router.get("/tracks/{track_id}/lyrics")
@rate_limit("60/minute")
async def get_track_lyrics(
    request: Request,
    track_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get lyrics for a track, fetching from LRCLIB if not cached.

    Returns synced (LRC format) and/or plain text lyrics.
    Caches results in the database for subsequent requests.
    """
    validate_uuid(track_id, "Track ID")

    track = (
        db.query(Track)
        .join(Album, Track.album_id == Album.id)
        .join(Artist, Album.artist_id == Artist.id)
        .options(joinedload(Track.album).joinedload(Album.artist))
        .filter(Track.id == track_id)
        .first()
    )
    if not track:
        # Check if this is a chapter (audiobook) — chapters don't have lyrics
        from app.models.chapter import Chapter
        chapter = db.query(Chapter).filter(Chapter.id == track_id).first()
        if chapter:
            return {"synced_lyrics": None, "plain_lyrics": None, "source": None}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    # Return cached lyrics if available
    if track.synced_lyrics is not None or track.plain_lyrics is not None:
        return {
            "synced_lyrics": track.synced_lyrics,
            "plain_lyrics": track.plain_lyrics,
            "source": track.lyrics_source,
            "has_synced": bool(track.synced_lyrics),
        }

    # Fetch from LRCLIB
    artist_name = track.album.artist.name if track.album and track.album.artist else None
    album_title = track.album.title if track.album else None
    duration_sec = round(track.duration_ms / 1000) if track.duration_ms else None

    synced_lyrics = None
    plain_lyrics = None
    source = None

    if artist_name and track.title:
        try:
            import httpx

            headers = {"User-Agent": "Studio54/1.0"}

            # Try exact match first
            params = {
                "artist_name": artist_name,
                "track_name": track.title,
            }
            if album_title:
                params["album_name"] = album_title
            if duration_sec:
                params["duration"] = str(duration_sec)

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://lrclib.net/api/get",
                    params=params,
                    headers=headers,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    synced_lyrics = data.get("syncedLyrics") or None
                    plain_lyrics = data.get("plainLyrics") or None
                    if synced_lyrics or plain_lyrics:
                        source = "lrclib"

                # Fallback: search if exact match failed
                if not synced_lyrics and not plain_lyrics:
                    search_resp = await client.get(
                        "https://lrclib.net/api/search",
                        params={"q": f"{artist_name} {track.title}"},
                        headers=headers,
                    )
                    if search_resp.status_code == 200:
                        results = search_resp.json()
                        if results and len(results) > 0:
                            best = results[0]
                            synced_lyrics = best.get("syncedLyrics") or None
                            plain_lyrics = best.get("plainLyrics") or None
                            if synced_lyrics or plain_lyrics:
                                source = "lrclib"

        except Exception as e:
            logger.warning(f"Failed to fetch lyrics from LRCLIB for track {track_id}: {e}")

    # Cache in DB (even empty strings to avoid re-fetching)
    track.synced_lyrics = synced_lyrics or ""
    track.plain_lyrics = plain_lyrics or ""
    track.lyrics_source = source
    db.commit()

    return {
        "synced_lyrics": synced_lyrics,
        "plain_lyrics": plain_lyrics,
        "source": source,
        "has_synced": bool(synced_lyrics),
    }


@router.get("/tracks/{track_id}/rating")
@rate_limit("100/minute")
async def get_track_rating(
    request: Request,
    track_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Get the current user's rating and the average rating for a track"""
    validate_uuid(track_id, "Track ID")

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        # Check if this is a chapter (audiobook) — return empty rating
        from app.models.chapter import Chapter
        chapter = db.query(Chapter).filter(Chapter.id == track_id).first()
        if chapter:
            return {
                "track_id": str(chapter.id),
                "average_rating": None,
                "user_rating": None,
                "rating_count": 0,
            }
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    user_rating_row = db.query(TrackRating).filter(
        TrackRating.track_id == track_id,
        TrackRating.user_id == current_user.id,
    ).first()

    rating_count = db.query(func.count(TrackRating.id)).filter(
        TrackRating.track_id == track_id
    ).scalar() or 0

    return {
        "track_id": str(track.id),
        "average_rating": track.average_rating,
        "user_rating": user_rating_row.rating if user_rating_row else None,
        "rating_count": rating_count,
    }


@router.patch("/tracks/{track_id}/rating")
@rate_limit("100/minute")
async def set_track_rating(
    request: Request,
    track_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Set or clear a per-user track rating (1-5, or null to clear)"""
    validate_uuid(track_id, "Track ID")

    rating = body.get("rating")
    if rating is not None:
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rating must be an integer between 1 and 5, or null to clear"
            )

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        # Check if this is a book chapter — chapters don't support ratings but shouldn't hard-fail
        from app.models.chapter import Chapter as ChapterModel
        chapter = db.query(ChapterModel).filter(ChapterModel.id == track_id).first()
        if chapter:
            return {
                "id": str(chapter.id),
                "title": chapter.title,
                "average_rating": None,
                "user_rating": rating,
                "rating_count": 0,
            }
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    if rating is None:
        # Clear this user's rating
        db.query(TrackRating).filter(
            TrackRating.track_id == track_id,
            TrackRating.user_id == current_user.id,
        ).delete()
    else:
        # Upsert: update existing or insert new
        existing = db.query(TrackRating).filter(
            TrackRating.track_id == track_id,
            TrackRating.user_id == current_user.id,
        ).first()
        if existing:
            existing.rating = rating
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(TrackRating(
                user_id=current_user.id,
                track_id=track.id,
                rating=rating,
            ))

    db.flush()

    # Recompute average_rating
    avg = db.query(func.avg(TrackRating.rating)).filter(
        TrackRating.track_id == track_id
    ).scalar()
    track.average_rating = round(float(avg), 2) if avg else None

    rating_count = db.query(func.count(TrackRating.id)).filter(
        TrackRating.track_id == track_id
    ).scalar() or 0

    db.commit()

    return {
        "id": str(track.id),
        "title": track.title,
        "average_rating": track.average_rating,
        "user_rating": rating,
        "rating_count": rating_count,
    }


# ── Cover Art Proxy ──
# Archive.org blocks direct browser requests (hotlinking). This endpoint
# fetches cover art server-side and streams it back to the browser.

_cover_art_client = None

def _get_cover_art_client():
    global _cover_art_client
    if _cover_art_client is None:
        _cover_art_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": "Studio54/1.0 (Music Library Manager)"},
        )
    return _cover_art_client


@router.get("/cover-art-proxy/{release_mbid}/{image_file}")
async def proxy_cover_art(release_mbid: str, image_file: str):
    """Proxy cover art from coverartarchive.org (follows redirects server-side)."""
    url = f"https://coverartarchive.org/release/{release_mbid}/{image_file}"
    client = _get_cover_art_client()
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Cover art not found")
        content_type = resp.headers.get("content-type", "image/jpeg")
        return StreamingResponse(
            iter([resp.content]),
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=604800",
                "X-Cover-Art-Proxy": "hit",
            },
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Failed to fetch cover art")


# ── Cover Art Upload ─────────────────────────────────────────────────


@router.post("/{album_id}/cover-art", dependencies=[Depends(require_dj_or_above)])
async def upload_album_cover_art(
    request: Request,
    album_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload cover art for an album."""
    validate_uuid(album_id)

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    filepath = await save_entity_cover_art("album", album_id, file)
    album.cover_art_url = filepath
    db.commit()

    return {"success": True, "cover_art_url": filepath}


@router.post("/{album_id}/cover-art-from-url", dependencies=[Depends(require_dj_or_above)])
async def upload_album_cover_art_from_url(
    request: Request,
    album_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Fetch cover art for an album from a remote URL."""
    from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url

    validate_uuid(album_id)

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    filepath = await fetch_and_save_entity_cover_art_from_url("album", album_id, url)
    album.cover_art_url = filepath
    db.commit()

    return {"success": True, "cover_art_url": filepath}


@router.get("/{album_id}/cover-art")
async def get_album_cover_art(
    request: Request,
    album_id: str,
    db: Session = Depends(get_db),
):
    """Serve cover art for an album."""
    validate_uuid(album_id)

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    return serve_entity_cover_art("album", album_id, album.cover_art_url)
