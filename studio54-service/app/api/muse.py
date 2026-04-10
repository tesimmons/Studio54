"""
MUSE Integration API Router
Endpoints for bidirectional MUSE library integration
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.artist import Artist
from app.models.album import Album, AlbumStatus
from app.services.muse_client import get_muse_client
from app.services.musicbrainz_client import get_musicbrainz_client
from pydantic import BaseModel

router = APIRouter(prefix="/muse", tags=["MUSE Integration"])
logger = logging.getLogger(__name__)


# Request/Response Models

class VerifyAlbumRequest(BaseModel):
    """Request to verify if album exists in MUSE"""
    musicbrainz_id: str
    min_track_count: int = 1


class VerifyAlbumResponse(BaseModel):
    """Album verification result"""
    musicbrainz_id: str
    exists: bool
    file_count: int
    recommendation: str  # "skip_download" or "proceed_download"


class FindMissingRequest(BaseModel):
    """Request to find missing albums"""
    artist_id: Optional[str] = None  # If None, check all monitored artists
    muse_library_id: Optional[str] = None  # If None, use first available


class FindMissingResponse(BaseModel):
    """Missing albums detection result"""
    total_artists_checked: int
    total_albums_checked: int
    missing_albums_found: int
    missing_albums: List[Dict[str, Any]]


class TriggerScanRequest(BaseModel):
    """Request to trigger MUSE scan"""
    library_id: str
    path_hint: Optional[str] = None  # For faster targeted scans


class TriggerScanResponse(BaseModel):
    """Scan trigger result"""
    success: bool
    library_id: str
    message: str


# Endpoints

@router.get("/libraries")
async def get_muse_libraries(current_user: User = Depends(require_director)):
    """
    Get all MUSE libraries

    Returns:
        List of MUSE libraries with metadata
    """
    try:
        muse_client = get_muse_client()
        libraries = muse_client.get_libraries()

        return {
            "success": True,
            "total_libraries": len(libraries),
            "libraries": libraries
        }

    except Exception as e:
        logger.error(f"Failed to get MUSE libraries: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get MUSE libraries: {str(e)}")


@router.get("/libraries/{library_id}/stats")
async def get_library_stats(library_id: str, current_user: User = Depends(require_director)):
    """
    Get MUSE library statistics

    Args:
        library_id: MUSE library UUID

    Returns:
        Library statistics including file counts and size
    """
    try:
        muse_client = get_muse_client()
        stats = muse_client.get_library_stats(library_id)

        if not stats:
            raise HTTPException(status_code=404, detail="Library not found")

        return {
            "success": True,
            "library": stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get library stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get library stats: {str(e)}")


@router.get("/libraries/{library_id}/artists")
async def get_library_artists(
    library_id: str,
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    missing_mbid_only: bool = Query(False),
    current_user: User = Depends(require_director)
):
    """
    Get artists from MUSE library

    Args:
        library_id: MUSE library UUID
        limit: Maximum number of artists to return (default 1000)
        offset: Number of artists to skip (default 0)
        missing_mbid_only: Only return artists without MusicBrainz IDs (default False)

    Returns:
        List of artists with file counts and MusicBrainz IDs
    """
    try:
        muse_client = get_muse_client()
        artists = muse_client.get_library_artists(
            library_id=library_id,
            limit=limit,
            offset=offset,
            missing_mbid_only=missing_mbid_only
        )

        return artists

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get library artists: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get library artists: {str(e)}")


@router.post("/verify-album", response_model=VerifyAlbumResponse)
async def verify_album_exists(request: VerifyAlbumRequest, current_user: User = Depends(require_director)):
    """
    Verify if album exists in MUSE library

    Used to prevent downloading duplicates. Checks if album with
    given MusicBrainz ID already exists in MUSE with sufficient tracks.

    Args:
        request: VerifyAlbumRequest with musicbrainz_id and min_track_count

    Returns:
        VerifyAlbumResponse with existence status and recommendation
    """
    try:
        muse_client = get_muse_client()
        exists, file_count = muse_client.album_exists(
            musicbrainz_id=request.musicbrainz_id,
            min_track_count=request.min_track_count
        )

        recommendation = "skip_download" if exists else "proceed_download"

        logger.info(
            f"Album verification: MBID={request.musicbrainz_id}, "
            f"exists={exists}, files={file_count}, recommendation={recommendation}"
        )

        return VerifyAlbumResponse(
            musicbrainz_id=request.musicbrainz_id,
            exists=exists,
            file_count=file_count or 0,
            recommendation=recommendation
        )

    except Exception as e:
        logger.error(f"Album verification failed: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


@router.post("/trigger-scan", response_model=TriggerScanResponse)
async def trigger_library_scan(request: TriggerScanRequest, current_user: User = Depends(require_director)):
    """
    Trigger MUSE library scan

    Initiates a library scan on MUSE. Use path_hint for faster
    targeted scans of specific directories.

    Args:
        request: TriggerScanRequest with library_id and optional path_hint

    Returns:
        TriggerScanResponse with success status
    """
    try:
        muse_client = get_muse_client()
        success = muse_client.trigger_scan(
            library_id=request.library_id,
            path_hint=request.path_hint
        )

        if success:
            message = f"Scan triggered successfully for library {request.library_id}"
            if request.path_hint:
                message += f" (path: {request.path_hint})"
        else:
            message = "Failed to trigger scan"

        logger.info(message)

        return TriggerScanResponse(
            success=success,
            library_id=request.library_id,
            message=message
        )

    except Exception as e:
        logger.error(f"Scan trigger failed: {e}")
        raise HTTPException(status_code=500, detail=f"Scan trigger failed: {str(e)}")


@router.post("/find-missing", response_model=FindMissingResponse)
async def find_missing_albums(
    request: FindMissingRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Find missing albums for monitored artists

    Compares MUSE library against MusicBrainz catalog to identify
    albums that should be downloaded. Creates new Album entries
    with status=WANTED for missing albums.

    Process:
    1. Get monitored artists (or specific artist if artist_id provided)
    2. For each artist, get all albums from MusicBrainz
    3. Check which albums exist in MUSE library
    4. Add missing albums to Studio54 wanted list

    Args:
        request: FindMissingRequest with optional artist_id and library_id
        db: Database session

    Returns:
        FindMissingResponse with counts and list of missing albums
    """
    try:
        muse_client = get_muse_client()
        mb_client = get_musicbrainz_client()

        # Get MUSE library
        libraries = muse_client.get_libraries()
        if not libraries:
            raise HTTPException(status_code=400, detail="No MUSE libraries found")

        muse_library_id = request.muse_library_id or libraries[0].get("id")

        # Get artists to check
        if request.artist_id:
            artists = db.query(Artist).filter(Artist.id == request.artist_id).all()
            if not artists:
                raise HTTPException(status_code=404, detail="Artist not found")
        else:
            artists = db.query(Artist).filter(Artist.is_monitored == True).all()

        if not artists:
            return FindMissingResponse(
                total_artists_checked=0,
                total_albums_checked=0,
                missing_albums_found=0,
                missing_albums=[]
            )

        logger.info(f"Checking {len(artists)} artists for missing albums")

        total_albums_checked = 0
        missing_albums = []

        for artist in artists:
            try:
                if not artist.musicbrainz_id:
                    logger.warning(f"Artist {artist.name} has no MusicBrainz ID, skipping")
                    continue

                # Get all albums from MusicBrainz
                release_groups = mb_client.get_artist_albums(
                    artist.musicbrainz_id,
                    types=["Album", "EP"]
                )

                total_albums_checked += len(release_groups)

                for rg in release_groups:
                    try:
                        mbid = rg.get("id")
                        if not mbid:
                            continue

                        # Check if already in Studio54 database
                        existing_album = db.query(Album).filter(
                            Album.musicbrainz_id == mbid
                        ).first()

                        if existing_album:
                            # Already tracked, skip
                            continue

                        # Check if exists in MUSE library
                        exists, file_count = muse_client.album_exists(mbid, min_track_count=1)

                        if not exists:
                            # Album missing - add to wanted list
                            release_date = None
                            first_release_date = rg.get("first-release-date")

                            if first_release_date:
                                try:
                                    from datetime import date
                                    date_parts = first_release_date.split("-")
                                    if len(date_parts) == 3:
                                        release_date = date(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                                    elif len(date_parts) == 2:
                                        release_date = date(int(date_parts[0]), int(date_parts[1]), 1)
                                    elif len(date_parts) == 1:
                                        release_date = date(int(date_parts[0]), 1, 1)
                                except (ValueError, IndexError):
                                    pass

                            # Create new album entry
                            new_album = Album(
                                artist_id=artist.id,
                                title=rg.get("title", "Unknown Album"),
                                musicbrainz_id=mbid,
                                release_date=release_date,
                                album_type=rg.get("primary-type"),
                                status=AlbumStatus.WANTED,
                                monitored=True,
                                muse_library_id=muse_library_id
                            )

                            db.add(new_album)

                            missing_albums.append({
                                "artist_name": artist.name,
                                "album_title": rg.get("title"),
                                "musicbrainz_id": mbid,
                                "release_date": first_release_date,
                                "album_type": rg.get("primary-type"),
                                "album_id": str(new_album.id)
                            })

                            logger.info(f"Missing album found: {artist.name} - {rg.get('title')}")

                    except Exception as e:
                        logger.error(f"Failed to process album {rg.get('id')}: {e}")
                        continue

            except Exception as e:
                logger.error(f"Failed to check artist {artist.name}: {e}")
                continue

        # Commit all new albums
        db.commit()

        logger.info(
            f"Missing albums scan complete: {len(artists)} artists, "
            f"{total_albums_checked} albums checked, {len(missing_albums)} missing"
        )

        return FindMissingResponse(
            total_artists_checked=len(artists),
            total_albums_checked=total_albums_checked,
            missing_albums_found=len(missing_albums),
            missing_albums=missing_albums
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Find missing albums failed: {e}")
        raise HTTPException(status_code=500, detail=f"Find missing albums failed: {str(e)}")


@router.get("/connection-test")
async def test_muse_connection(current_user: User = Depends(require_director)):
    """
    Test connection to MUSE service

    Returns:
        Connection status and MUSE availability
    """
    try:
        muse_client = get_muse_client()
        is_available = muse_client.test_connection()

        return {
            "success": True,
            "muse_available": is_available,
            "message": "MUSE is available" if is_available else "MUSE is not available"
        }

    except Exception as e:
        logger.error(f"MUSE connection test failed: {e}")
        return {
            "success": False,
            "muse_available": False,
            "message": str(e)
        }


@router.get("/quality-check/{musicbrainz_id}")
async def check_album_quality(
    musicbrainz_id: str,
    min_quality_score: int = Query(70, ge=0, le=100),
    current_user: User = Depends(require_director)
):
    """
    Check quality of existing album in MUSE

    Verifies if existing album meets quality standards. Used to
    determine if upgrade download is needed.

    Args:
        musicbrainz_id: MusicBrainz release ID
        min_quality_score: Minimum acceptable quality score (0-100)

    Returns:
        Quality check result with recommendation
    """
    try:
        muse_client = get_muse_client()
        meets_quality, avg_quality = muse_client.verify_album_quality(
            musicbrainz_id=musicbrainz_id,
            min_quality_score=min_quality_score
        )

        if avg_quality is None:
            recommendation = "no_quality_data"
            message = "No quality data available"
        elif meets_quality:
            recommendation = "quality_acceptable"
            message = f"Album quality acceptable (score: {avg_quality})"
        else:
            recommendation = "upgrade_recommended"
            message = f"Album quality below threshold (score: {avg_quality}, min: {min_quality_score})"

        return {
            "success": True,
            "musicbrainz_id": musicbrainz_id,
            "meets_quality": meets_quality,
            "average_quality_score": avg_quality,
            "minimum_quality_score": min_quality_score,
            "recommendation": recommendation,
            "message": message
        }

    except Exception as e:
        logger.error(f"Quality check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Quality check failed: {str(e)}")
