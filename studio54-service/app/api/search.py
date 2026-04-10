"""
Search API Router
Album search and release management endpoints using the decision engine
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
import logging

from app.database import get_db
from app.models import Album, Artist
from app.models.album import AlbumStatus
from app.models.download_decision import PendingRelease, ReleaseInfo
from app.services.search.album_search_service import AlbumSearchService
from app.services.download.process_decisions import ProcessDownloadDecisions, GrabService
from app.security import rate_limit, validate_uuid
from app.auth import require_director, require_any_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models
class ManualSearchRequest(BaseModel):
    auto_grab: bool = False


class GrabReleaseRequest(BaseModel):
    release_guid: str
    release_data: Optional[dict] = None


class SearchWantedRequest(BaseModel):
    limit: int = 10


# ============================================================================
# Album Search Endpoints
# ============================================================================

@router.post("/albums/{album_id}")
@rate_limit("30/minute")
async def search_album(
    request: Request,
    album_id: str,
    search_request: ManualSearchRequest = Body(default=ManualSearchRequest()),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Search indexers for an album

    Uses the decision engine to evaluate releases from all configured
    indexers and returns approved/rejected decisions.

    Args:
        album_id: UUID of the album to search
        request: Search options (auto_grab: bool)

    Returns:
        Search results with decision engine evaluations
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    search_service = AlbumSearchService(db)

    try:
        result = search_service.search_album_sync(album_id)

        # Process decisions if auto_grab is enabled
        if search_request.auto_grab and result.get("decisions"):
            process_service = ProcessDownloadDecisions(db)
            submission_result = process_service.process(
                result["decisions"],
                auto_grab=True
            )

            return {
                "album_id": album_id,
                "artist": result.get("artist"),
                "album": result.get("album"),
                "total_results": result.get("total_results", 0),
                "approved_count": result.get("approved_count", 0),
                "rejected_count": result.get("rejected_count", 0),
                "auto_grab": True,
                "grabbed": submission_result.grabbed,
                "pending": submission_result.pending,
                "rejected": submission_result.rejected,
                "grabbed_items": submission_result.grabbed_items,
                "errors": submission_result.errors,
            }

        return {
            "album_id": album_id,
            "artist": result.get("artist"),
            "album": result.get("album"),
            "total_results": result.get("total_results", 0),
            "approved_count": result.get("approved_count", 0),
            "rejected_count": result.get("rejected_count", 0),
            "results": result.get("results", [])[:20],  # Top 20 results
            "decisions": [d.to_dict() for d in result.get("decisions", [])[:20]] if result.get("decisions") else []
        }

    except Exception as e:
        logger.error(f"Search failed for album {album_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/albums/{album_id}/grab")
@rate_limit("20/minute")
async def grab_album_release(
    request: Request,
    album_id: str,
    grab_request: GrabReleaseRequest,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Manually grab a specific release for an album

    Submits the release to the download client without requiring
    a new search.

    Args:
        album_id: UUID of the album
        request: Release GUID and optional release data

    Returns:
        Grab result with tracked download ID
    """
    validate_uuid(album_id, "Album ID")

    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    grab_service = GrabService(db)

    success, tracked_id, error = grab_service.grab_release(
        release_guid=grab_request.release_guid,
        album_id=album_id,
        release_data=grab_request.release_data
    )

    if not success:
        raise HTTPException(status_code=400, detail=error or "Failed to grab release")

    return {
        "success": True,
        "album_id": album_id,
        "release_guid": grab_request.release_guid,
        "tracked_download_id": tracked_id,
        "message": "Release grabbed successfully"
    }


# ============================================================================
# Artist Search Endpoints
# ============================================================================

@router.post("/artists/{artist_id}")
@rate_limit("10/minute")
async def search_artist(
    request: Request,
    artist_id: str,
    wanted_only: bool = Query(True, description="Only search for wanted albums"),
    auto_grab: bool = Query(False, description="Auto-grab approved releases"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Search for all albums by an artist

    Searches all indexers for albums by the specified artist.

    Args:
        artist_id: UUID of the artist
        wanted_only: If True, only search for wanted albums
        auto_grab: If True, automatically grab approved releases

    Returns:
        Search results grouped by album
    """
    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    # Get albums to search
    query = db.query(Album).filter(Album.artist_id == artist_id)
    if wanted_only:
        query = query.filter(
            Album.monitored == True,
            Album.status == AlbumStatus.WANTED
        )

    albums = query.all()

    if not albums:
        return {
            "artist_id": artist_id,
            "artist_name": artist.name,
            "albums_searched": 0,
            "message": "No albums to search"
        }

    search_service = AlbumSearchService(db)
    process_service = ProcessDownloadDecisions(db)

    results = {}
    total_approved = 0
    total_grabbed = 0

    for album in albums:
        try:
            result = search_service.search_album_sync(str(album.id))
            decisions = result.get("decisions", [])
            approved = [d for d in decisions if d.approved]

            album_result = {
                "album_id": str(album.id),
                "album_title": album.title,
                "total_results": len(decisions),
                "approved_count": len(approved),
            }

            if auto_grab and approved:
                submission = process_service.process(decisions, auto_grab=True)
                album_result["grabbed"] = submission.grabbed
                total_grabbed += submission.grabbed

            total_approved += len(approved)
            results[str(album.id)] = album_result

        except Exception as e:
            results[str(album.id)] = {
                "album_id": str(album.id),
                "album_title": album.title,
                "error": str(e)
            }

    return {
        "artist_id": artist_id,
        "artist_name": artist.name,
        "albums_searched": len(albums),
        "total_approved": total_approved,
        "total_grabbed": total_grabbed if auto_grab else 0,
        "results": results
    }


# ============================================================================
# Wanted/Bulk Search Endpoints
# ============================================================================

@router.post("/wanted")
@rate_limit("5/minute")
async def search_all_wanted(
    request: Request,
    search_request: SearchWantedRequest = Body(default=SearchWantedRequest()),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Trigger search for all wanted albums

    Queues a background task to search for all wanted albums
    using the decision engine.

    Args:
        search_request: Search options (limit)

    Returns:
        Task ID for monitoring progress
    """
    from app.tasks.search_tasks import search_wanted_albums_v2

    task = search_wanted_albums_v2.delay(search_request.limit)

    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"Searching up to {search_request.limit} wanted albums"
    }


@router.post("/cutoff-unmet")
@rate_limit("5/minute")
async def search_cutoff_unmet(
    request: Request,
    limit: int = Query(5, ge=1, le=50),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Search for quality upgrades

    Searches for albums where the current quality is below
    the cutoff defined in the quality profile.

    Args:
        limit: Maximum albums to search

    Returns:
        Task ID for monitoring progress
    """
    from app.tasks.search_tasks import search_cutoff_unmet

    task = search_cutoff_unmet.delay(limit)

    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"Searching for quality upgrades on up to {limit} albums"
    }


# ============================================================================
# Pending Releases Endpoints
# ============================================================================

@router.get("/pending")
@rate_limit("100/minute")
async def list_pending_releases(
    request: Request,
    album_id: Optional[str] = Query(None, description="Filter by album ID"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List pending releases (temporarily rejected)

    Returns releases that were temporarily rejected and may be
    retried later.
    """
    query = db.query(PendingRelease)

    if album_id:
        validate_uuid(album_id, "Album ID")
        query = query.filter(PendingRelease.album_id == album_id)

    pending = query.order_by(PendingRelease.added_at.desc()).limit(limit).all()

    return {
        "count": len(pending),
        "pending_releases": [
            {
                "id": str(p.id),
                "album_id": str(p.album_id),
                "artist_id": str(p.artist_id),
                "release_guid": p.release_guid,
                "release_title": p.release_title,
                "added_at": p.added_at.isoformat() if p.added_at else None,
                "retry_after": p.retry_after.isoformat() if p.retry_after else None,
                "retry_count": p.retry_count,
                "rejection_reasons": p.rejection_reasons
            }
            for p in pending
        ]
    }


@router.delete("/pending/{pending_id}")
@rate_limit("50/minute")
async def delete_pending_release(
    request: Request,
    pending_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Delete a pending release

    Removes a release from the pending queue.
    """
    validate_uuid(pending_id, "Pending release ID")

    pending = db.query(PendingRelease).filter(PendingRelease.id == pending_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending release not found")

    db.delete(pending)
    db.commit()

    return {"status": "deleted", "pending_id": pending_id}


@router.post("/pending/{pending_id}/retry")
@rate_limit("20/minute")
async def retry_pending_release(
    request: Request,
    pending_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Retry a pending release

    Attempts to grab a previously pending release.
    """
    validate_uuid(pending_id, "Pending release ID")

    pending = db.query(PendingRelease).filter(PendingRelease.id == pending_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending release not found")

    grab_service = GrabService(db)

    success, tracked_id, error = grab_service.grab_release(
        release_guid=pending.release_guid,
        album_id=str(pending.album_id),
        release_data=pending.release_data
    )

    if success:
        return {
            "success": True,
            "tracked_download_id": tracked_id,
            "message": "Pending release grabbed successfully"
        }

    raise HTTPException(status_code=400, detail=error or "Failed to grab pending release")


@router.post("/missing")
@rate_limit("5/minute")
async def search_missing(
    request: Request,
    artist_id: Optional[str] = Query(None, description="Search only this artist's wanted albums"),
    limit: int = Query(50, ge=1, le=200, description="Maximum albums to search"),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Search for missing (wanted) albums

    Triggers a background search for wanted, monitored albums.
    If artist_id is provided, searches only that artist's wanted albums.
    Otherwise searches all wanted albums across the library.

    Args:
        artist_id: Optional artist UUID to scope search
        limit: Maximum albums to search

    Returns:
        Task ID for progress tracking
    """
    if artist_id:
        validate_uuid(artist_id, "Artist ID")
        artist = db.query(Artist).filter(Artist.id == artist_id).first()
        if not artist:
            raise HTTPException(status_code=404, detail="Artist not found")

        from app.tasks.search_tasks import search_wanted_albums_for_artist
        task = search_wanted_albums_for_artist.delay(artist_id)

        return {
            "task_id": task.id,
            "status": "queued",
            "artist_id": artist_id,
            "artist_name": artist.name,
            "message": f"Searching wanted albums for {artist.name}"
        }
    else:
        from app.tasks.search_tasks import search_wanted_albums_v2
        task = search_wanted_albums_v2.delay(limit)

        return {
            "task_id": task.id,
            "status": "queued",
            "message": f"Searching up to {limit} wanted albums across library"
        }
