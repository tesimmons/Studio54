"""
Artists API Router
Artist management and monitoring endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_director, require_dj_or_above, require_any_user
from app.models.user import User
from app.models.artist import Artist
from app.models.album import Album
from app.models.track import Track
from app.security import rate_limit, validate_mbid, validate_uuid
from app.services.cover_art_service import save_entity_cover_art, serve_entity_cover_art
from app.utils.search import fuzzy_search_filter
from app.services.musicbrainz_client import get_musicbrainz_client

logger = logging.getLogger(__name__)

router = APIRouter()


class AddArtistRequest(BaseModel):
    """Request model for adding an artist"""
    musicbrainz_id: str
    is_monitored: bool = True
    root_folder_path: Optional[str] = None
    quality_profile_id: Optional[str] = None
    monitor_type: str = "all_albums"
    search_for_missing: bool = False


class ImportArtistsRequest(BaseModel):
    """Request model for importing artists from MUSE or Studio54"""
    library_id: str  # MUSE library_id or Studio54 library_path_id
    artist_names: Optional[List[str]] = None  # Specific artists to import, or None for all
    auto_match_mbid: bool = True  # Auto-search MusicBrainz for missing MBIDs
    is_monitored: bool = False  # Default: unmonitored


class ImportUnlinkedRequest(BaseModel):
    """Request model for importing unlinked artists"""
    library_path_id: Optional[str] = None
    is_monitored: bool = False
    auto_sync: bool = True


class BulkUpdateRequest(BaseModel):
    """Request model for bulk updating artists"""
    artist_ids: List[str]
    is_monitored: Optional[bool] = None
    quality_profile_id: Optional[str] = None


@router.get("/musicbrainz/search/artists")
@rate_limit("100/minute")
async def search_musicbrainz_artists(
    request: Request,
    query: str,
    limit: int = 25,
    current_user: User = Depends(require_any_user),
):
    """
    Search for artists on MusicBrainz (GET endpoint for frontend)

    Args:
        query: Artist name search query
        limit: Maximum results to return (default: 25, max: 100)

    Returns:
        MusicBrainz artist search results with enhanced metadata
    """
    if not query or len(query.strip()) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must be at least 2 characters"
        )

    if limit > 100:
        limit = 100

    try:
        mb_client = get_musicbrainz_client()
        results = mb_client.search_artist(query, limit)

        # Format results for frontend
        artists = []
        for result in results:
            artist_data = {
                "id": result.get("id"),
                "name": result.get("name"),
                "disambiguation": result.get("disambiguation"),
                "country": result.get("country"),
                "type": result.get("type"),
                "score": result.get("score")
            }
            artists.append(artist_data)

        return {
            "artists": artists,
            "query": query,
            "total": len(artists)
        }

    except Exception as e:
        logger.error(f"MusicBrainz artist search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.post("/artists/search")
@rate_limit("100/minute")
async def search_artists(
    request: Request,
    query: str,
    limit: int = 25,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Search for artists on MusicBrainz

    Args:
        query: Artist name search query
        limit: Maximum results to return (default: 25, max: 100)

    Returns:
        List of artist search results from MusicBrainz
    """
    if not query or len(query.strip()) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must be at least 2 characters"
        )

    if limit > 100:
        limit = 100

    try:
        mb_client = get_musicbrainz_client()
        results = mb_client.search_artist(query, limit)

        # Enhance results with monitoring status using bulk query (avoid N+1)
        mbids = [r.get("id") for r in results if r.get("id")]
        existing_artists = db.query(Artist).filter(Artist.musicbrainz_id.in_(mbids)).all() if mbids else []
        artist_map = {a.musicbrainz_id: a for a in existing_artists}

        for result in results:
            mbid = result.get("id")
            if mbid:
                existing = artist_map.get(mbid)
                result["is_monitored"] = existing.is_monitored if existing else False
                result["in_library"] = existing is not None

        return {
            "query": query,
            "total_results": len(results),
            "results": results
        }

    except Exception as e:
        logger.error(f"Artist search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Artist search failed: {str(e)}"
        )


@router.post("/artists")
@rate_limit("50/minute")
async def add_artist(
    request: Request,
    artist_data: AddArtistRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Add artist to monitoring

    Args:
        artist_data: Artist information (musicbrainz_id, is_monitored, etc.)

    Returns:
        Created artist object
    """
    validate_mbid(artist_data.musicbrainz_id)

    musicbrainz_id = artist_data.musicbrainz_id
    is_monitored = artist_data.is_monitored
    root_folder_path = artist_data.root_folder_path
    quality_profile_id = artist_data.quality_profile_id
    monitor_type = artist_data.monitor_type
    search_for_missing = artist_data.search_for_missing

    # Check if artist already exists
    existing = db.query(Artist).filter(Artist.musicbrainz_id == musicbrainz_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Artist already exists with ID {existing.id}"
        )

    try:
        # Get artist details from MusicBrainz
        mb_client = get_musicbrainz_client()
        artist_data = mb_client.get_artist(musicbrainz_id)

        if not artist_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artist not found on MusicBrainz"
            )

        # Extract top genre from MusicBrainz genres list
        genre = None
        mb_genres = artist_data.get("genres") or []
        if mb_genres:
            top_genre = sorted(mb_genres, key=lambda g: g.get("count", 0), reverse=True)[0]
            genre = top_genre.get("name")

        # Create artist
        artist = Artist(
            name=artist_data.get("name", "Unknown Artist"),
            musicbrainz_id=musicbrainz_id,
            is_monitored=is_monitored,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            monitor_type=monitor_type,
            genre=genre,
            added_at=datetime.now(timezone.utc)
        )

        db.add(artist)
        db.commit()
        db.refresh(artist)

        logger.info(f"Added artist: {artist.name} (MBID: {musicbrainz_id})")

        # Send notification
        try:
            from app.services.notification_service import send_notification
            send_notification("artist_added", {
                "message": f"Artist added: {artist.name}",
                "artist_name": artist.name,
                "musicbrainz_id": musicbrainz_id,
                "is_monitored": is_monitored,
            })
        except Exception as e:
            logger.debug(f"Notification send failed: {e}")

        # Create folder if artist is monitored
        if is_monitored:
            try:
                from app.services.folder_creator import get_folder_creator
                folder_creator = get_folder_creator(db)
                success, folder_path, error = folder_creator.create_artist_folder(artist)
                if success:
                    logger.info(f"Created folder for monitored artist {artist.name}: {folder_path}")
                elif error:
                    logger.warning(f"Failed to create folder for artist {artist.name}: {error}")
            except Exception as e:
                logger.error(f"Error creating folder for artist {artist.name}: {e}", exc_info=True)

        # Trigger background task to fetch albums
        from app.tasks.sync_tasks import sync_artist_albums
        try:
            task = sync_artist_albums.delay(str(artist.id))
            logger.info(f"Triggered album sync task {task.id} for artist {artist.name}")
        except Exception as e:
            logger.warning(f"Failed to trigger album sync task: {e}")
            # Don't fail the request if background task fails to start

        # Chain search for missing albums if requested
        search_task_id = None
        if search_for_missing and is_monitored:
            try:
                from app.tasks.search_tasks import search_wanted_albums_for_artist
                search_task = search_wanted_albums_for_artist.apply_async(
                    args=[str(artist.id)],
                    countdown=30,  # Wait 30s for sync to complete
                )
                search_task_id = search_task.id
                logger.info(f"Queued search-for-missing task {search_task.id} for artist {artist.name}")
            except Exception as e:
                logger.warning(f"Failed to queue search-for-missing task: {e}")

        return {
            "id": str(artist.id),
            "name": artist.name,
            "musicbrainz_id": artist.musicbrainz_id,
            "is_monitored": artist.is_monitored,
            "monitor_type": artist.monitor_type,
            "search_task_id": search_task_id,
            "added_at": artist.added_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add artist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add artist: {str(e)}"
        )


@router.get("/artists/genres")
@rate_limit("100/minute")
async def list_genres(
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get distinct genre values from all artists

    Returns:
        List of unique genre strings
    """
    genres = (
        db.query(Artist.genre)
        .filter(Artist.genre.isnot(None), Artist.genre != '')
        .distinct()
        .order_by(Artist.genre)
        .all()
    )
    return {"genres": [g[0] for g in genres]}


@router.get("/artists")
@rate_limit("100/minute")
async def list_artists(
    request: Request,
    search_query: Optional[str] = Query(None, description="Search artist name"),
    monitored_only: bool = Query(False, description="Only return monitored artists"),
    unmonitored_only: bool = Query(False, description="Only return unmonitored artists"),
    import_source: Optional[str] = Query(None, description="Filter by import source (muse, studio54, manual)"),
    has_image: Optional[bool] = Query(None, description="Filter by whether artist has image"),
    genre: Optional[str] = Query(None, description="Filter by genre (case-insensitive partial match)"),
    sort_by: Optional[str] = Query(None, description="Sort by: name, files_desc, files_asc, added_at"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List artists in library with search and filtering

    Args:
        search_query: Search artist name (case-insensitive partial match)
        monitored_only: Only return monitored artists
        unmonitored_only: Only return unmonitored artists
        import_source: Filter by import source (muse, studio54, manual)
        has_image: Filter by whether artist has image_url
        sort_by: Sort order - name (default), files_desc (most files first), files_asc (least files first), added_at
        limit: Results per page (1-1000)
        offset: Pagination offset

    Returns:
        List of artists with pagination metadata including file linking stats
    """
    # Build file stats subquery (needed for both sorting and response)
    file_stats_sq = (
        db.query(
            Album.artist_id,
            func.count(Track.id).label('total_tracks'),
            func.sum(case((Track.has_file == True, 1), else_=0)).label('linked_files')
        )
        .join(Track, Track.album_id == Album.id)
        .group_by(Album.artist_id)
        .subquery()
    )

    # Build album count subquery (live from DB, not stored column)
    album_counts_sq = (
        db.query(
            Album.artist_id,
            func.count(Album.id).label('total_albums'),
            func.sum(case((Album.monitored == True, 1), else_=0)).label('monitored_albums')
        )
        .group_by(Album.artist_id)
        .subquery()
    )

    query = (
        db.query(
            Artist,
            file_stats_sq.c.total_tracks,
            file_stats_sq.c.linked_files,
            album_counts_sq.c.total_albums,
            album_counts_sq.c.monitored_albums
        )
        .outerjoin(file_stats_sq, Artist.id == file_stats_sq.c.artist_id)
        .outerjoin(album_counts_sq, Artist.id == album_counts_sq.c.artist_id)
    )

    # Search by artist name (fuzzy trigram + ILIKE fallback)
    _artist_similarity = None
    if search_query:
        name_filter, _artist_similarity = fuzzy_search_filter(Artist.name, search_query)
        query = query.filter(name_filter)

    # Monitored status filters (mutually exclusive)
    if monitored_only:
        query = query.filter(Artist.is_monitored == True)
    elif unmonitored_only:
        query = query.filter(Artist.is_monitored == False)

    # Import source filter
    if import_source:
        query = query.filter(Artist.import_source == import_source)

    # Genre filter
    if genre:
        query = query.filter(Artist.genre.ilike(f"%{genre}%"))

    # Image presence filter
    if has_image is not None:
        if has_image:
            query = query.filter(Artist.image_url.isnot(None))
        else:
            query = query.filter(Artist.image_url.is_(None))

    total_count = query.with_entities(Artist.id).count()

    # Apply sort order
    if sort_by == 'files_desc':
        # Most files first (by percentage, then by count)
        query = query.order_by(
            (func.coalesce(file_stats_sq.c.linked_files, 0) * 100 /
             func.nullif(file_stats_sq.c.total_tracks, 0)).desc().nullslast(),
            func.coalesce(file_stats_sq.c.linked_files, 0).desc(),
            Artist.name
        )
    elif sort_by == 'files_asc':
        # Least files first (by percentage, then by count)
        query = query.order_by(
            (func.coalesce(file_stats_sq.c.linked_files, 0) * 100 /
             func.nullif(file_stats_sq.c.total_tracks, 0)).asc().nullsfirst(),
            func.coalesce(file_stats_sq.c.linked_files, 0).asc(),
            Artist.name
        )
    elif sort_by == 'added_at':
        query = query.order_by(Artist.added_at.desc().nullslast(), Artist.name)
    elif _artist_similarity is not None and sort_by is None:
        # When searching without explicit sort, order by relevance
        query = query.order_by(_artist_similarity.desc(), Artist.name)
    else:
        query = query.order_by(Artist.name)

    results = query.limit(limit).offset(offset).all()

    # Build file_stats and album_stats dicts from joined results
    artists = []
    file_stats = {}
    album_stats = {}
    for row in results:
        artist = row[0]
        total_tracks = row[1] or 0
        linked_files = int(row[2] or 0)
        total_albums = int(row[3] or 0)
        monitored_albums = int(row[4] or 0)
        artists.append(artist)
        file_stats[artist.id] = {
            'total_tracks': total_tracks,
            'linked_files': linked_files
        }
        album_stats[artist.id] = {
            'total_albums': total_albums,
            'monitored_albums': monitored_albums,
        }

    # Fallback: for artists without image_url, get an album cover_art_url
    artists_without_image = [a.id for a in artists if not a.image_url]
    fallback_covers = {}
    if artists_without_image:
        from sqlalchemy import text as sa_text
        # Get the first album with a cover for each artist (prefer albums over singles)
        cover_query = db.execute(sa_text("""
            SELECT DISTINCT ON (artist_id) artist_id, cover_art_url
            FROM albums
            WHERE artist_id = ANY(:artist_ids)
              AND cover_art_url IS NOT NULL
            ORDER BY artist_id,
                     CASE WHEN album_type = 'Album' THEN 0 ELSE 1 END,
                     release_date DESC NULLS LAST
        """), {"artist_ids": artists_without_image})
        for row in cover_query:
            fallback_covers[row[0]] = row[1]

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "artists": [
            {
                "id": str(artist.id),
                "name": artist.name,
                "musicbrainz_id": artist.musicbrainz_id,
                "is_monitored": artist.is_monitored,
                "album_count": album_stats.get(artist.id, {}).get('total_albums', 0),
                "monitored_album_count": album_stats.get(artist.id, {}).get('monitored_albums', 0),
                "track_count": file_stats.get(artist.id, {}).get('total_tracks', 0),
                "linked_files_count": file_stats.get(artist.id, {}).get('linked_files', 0),
                "total_track_files": file_stats.get(artist.id, {}).get('total_tracks', 0),
                "genre": artist.genre,
                "image_url": artist.image_url or fallback_covers.get(artist.id),
                "import_source": artist.import_source,
                "muse_library_id": str(artist.muse_library_id) if artist.muse_library_id else None,
                "studio54_library_path_id": str(artist.studio54_library_path_id) if artist.studio54_library_path_id else None,
                "rating_override": artist.rating_override,
                "added_at": artist.added_at.isoformat() if artist.added_at else None,
                "last_sync_at": artist.last_sync_at.isoformat() if artist.last_sync_at else None
            }
            for artist in artists
        ]
    }


@router.get("/artists/orphaned")
@rate_limit("30/minute")
async def get_orphaned_artists(
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Preview orphaned artists - unmonitored artists with no linked files.
    """
    from sqlalchemy import text

    try:
        orphaned_query = text("""
            SELECT a.id, a.name, a.musicbrainz_id, a.added_at,
                   COUNT(DISTINCT al.id) as album_count,
                   COUNT(DISTINCT t.id) as track_count
            FROM artists a
            LEFT JOIN albums al ON al.artist_id = a.id
            LEFT JOIN tracks t ON t.album_id = al.id
            WHERE a.is_monitored = false
              AND NOT EXISTS (
                  SELECT 1 FROM tracks t2
                  JOIN albums a2 ON t2.album_id = a2.id
                  WHERE a2.artist_id = a.id AND t2.has_file = true
              )
            GROUP BY a.id, a.name, a.musicbrainz_id, a.added_at
            ORDER BY a.name
        """)

        results = db.execute(orphaned_query).fetchall()

        orphaned = []
        for row in results:
            orphaned.append({
                "id": str(row.id),
                "name": row.name,
                "musicbrainz_id": row.musicbrainz_id,
                "added_at": row.added_at.isoformat() if row.added_at else None,
                "album_count": row.album_count,
                "track_count": row.track_count
            })

        return {
            "success": True,
            "count": len(orphaned),
            "orphaned_artists": orphaned
        }

    except Exception as e:
        logger.error(f"Failed to get orphaned artists: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get orphaned artists: {str(e)}"
        )


@router.delete("/artists/cleanup-orphaned")
@rate_limit("5/minute")
async def cleanup_orphaned_artists(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Delete orphaned artists - unmonitored artists with no linked files.
    Uses bulk SQL deletes for performance (cascade via foreign keys).
    """
    from sqlalchemy import text

    try:
        # Get orphaned artist info for response
        orphaned_query = text("""
            SELECT a.id, a.name, a.musicbrainz_id
            FROM artists a
            WHERE a.is_monitored = false
              AND NOT EXISTS (
                  SELECT 1 FROM tracks t
                  JOIN albums al ON t.album_id = al.id
                  WHERE al.artist_id = a.id AND t.has_file = true
              )
        """)

        results = db.execute(orphaned_query).fetchall()

        if not results:
            return {
                "success": True,
                "deleted_count": 0,
                "message": "No orphaned artists found",
                "deleted_artists": []
            }

        orphaned_ids = [str(row.id) for row in results]
        deleted_artists = [
            {"id": str(row.id), "name": row.name, "musicbrainz_id": row.musicbrainz_id}
            for row in results
        ]

        # Batch delete to avoid long-running transactions and lock contention
        BATCH_SIZE = 50
        deleted_count = 0
        for i in range(0, len(orphaned_ids), BATCH_SIZE):
            batch = orphaned_ids[i:i + BATCH_SIZE]
            count = db.query(Artist).filter(
                Artist.id.in_(batch)
            ).delete(synchronize_session=False)
            db.commit()
            deleted_count += count

        logger.info(f"Cleaned up {deleted_count} orphaned artists")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Removed {deleted_count} orphaned artists",
            "deleted_artists": deleted_artists
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cleanup orphaned artists: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup orphaned artists: {str(e)}"
        )


@router.get("/artists/{artist_id}")
@rate_limit("100/minute")
async def get_artist(
    request: Request,
    artist_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get artist details

    Args:
        artist_id: Artist UUID

    Returns:
        Artist object with albums
    """
    from app.security import validate_uuid
    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    # Get albums
    albums = db.query(Album).filter(Album.artist_id == artist_id).all()

    # Get linked files count (artist-level total)
    linked_files_count = (
        db.query(func.count(Track.id))
        .join(Album, Track.album_id == Album.id)
        .filter(Album.artist_id == artist_id, Track.has_file == True)
        .scalar()
    ) or 0

    # Compute average rating from rated tracks
    rating_stats = (
        db.query(
            func.avg(Track.rating).label("avg_rating"),
            func.count(Track.rating).label("rated_count")
        )
        .join(Album, Track.album_id == Album.id)
        .filter(Album.artist_id == artist_id, Track.rating.isnot(None))
        .first()
    )
    average_rating = round(float(rating_stats.avg_rating), 1) if rating_stats.avg_rating else None
    rated_track_count = int(rating_stats.rated_count) if rating_stats.rated_count else 0

    # Get per-album track counts and linked files counts from actual Track rows
    album_ids = [a.id for a in albums]
    if album_ids:
        track_stats_query = (
            db.query(
                Track.album_id,
                func.count(Track.id),
                func.sum(case((Track.has_file == True, 1), else_=0))
            )
            .filter(Track.album_id.in_(album_ids))
            .group_by(Track.album_id)
            .all()
        )
        real_track_counts = {album_id: int(total or 0) for album_id, total, _ in track_stats_query}
        linked_counts = {album_id: int(linked or 0) for album_id, _, linked in track_stats_query}
    else:
        real_track_counts = {}
        linked_counts = {}

    # Fallback image: use album cover if artist has no image_url
    effective_image_url = artist.image_url
    if not effective_image_url and albums:
        for a in albums:
            if a.cover_art_url:
                effective_image_url = a.cover_art_url
                break

    return {
        "id": str(artist.id),
        "name": artist.name,
        "musicbrainz_id": artist.musicbrainz_id,
        "is_monitored": artist.is_monitored,
        "quality_profile_id": str(artist.quality_profile_id) if artist.quality_profile_id else None,
        "root_folder_path": artist.root_folder_path,
        "monitor_type": artist.monitor_type,
        "image_url": effective_image_url,
        "overview": artist.overview,
        "genre": artist.genre,
        "country": artist.country,
        "album_count": artist.album_count,  # Use stored count (excludes singles)
        "single_count": artist.single_count,  # Add single count
        "track_count": artist.track_count,
        "linked_files_count": linked_files_count,
        "rating_override": artist.rating_override,
        "average_rating": average_rating,
        "rated_track_count": rated_track_count,
        "added_at": artist.added_at.isoformat() if artist.added_at else None,
        "last_sync_at": artist.last_sync_at.isoformat() if artist.last_sync_at else None,
        "albums": [
            {
                "id": str(album.id),
                "title": album.title,
                "musicbrainz_id": album.musicbrainz_id,
                "release_date": album.release_date.isoformat() if album.release_date else None,
                "album_type": album.album_type,
                "secondary_types": album.secondary_types,
                "status": album.status.value,
                "monitored": album.monitored,
                "track_count": real_track_counts.get(album.id, album.track_count or 0),
                "linked_files_count": linked_counts.get(album.id, 0),
                "cover_art_url": album.cover_art_url
            }
            for album in albums
        ]
    }


@router.patch("/artists/{artist_id}/rating")
@rate_limit("100/minute")
async def set_artist_rating(
    request: Request,
    artist_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """Set or clear an artist's rating override (1-5, or null to clear)"""
    from app.security import validate_uuid
    validate_uuid(artist_id, "Artist ID")

    rating = body.get("rating")
    if rating is not None:
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rating must be an integer between 1 and 5, or null to clear"
            )

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")

    artist.rating_override = rating
    db.commit()

    return {
        "id": str(artist.id),
        "name": artist.name,
        "rating_override": artist.rating_override
    }


@router.get("/artists/{artist_id}/top-tracks-external")
@rate_limit("30/minute")
async def get_top_tracks_external(
    request: Request,
    artist_id: str,
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get popular tracks for an artist from Last.fm, cross-referenced with local library.

    Returns Last.fm top tracks with local track matches (by recording MBID or fuzzy title).
    If LASTFM_API_KEY is not configured, returns an error indicator with empty tracks.
    """
    from app.security import validate_uuid
    from app.services.lastfm_client import get_lastfm_api_key, get_artist_top_tracks
    from app.models.track import Track
    from app.models.album import Album
    from difflib import SequenceMatcher

    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    if not get_lastfm_api_key():
        return {"error": "not_configured", "tracks": []}

    # Fetch from Last.fm
    lastfm_tracks = await get_artist_top_tracks(artist.name, limit=limit)

    if not lastfm_tracks:
        return {"error": None, "tracks": []}

    # Get all local tracks for this artist (with files)
    local_tracks = (
        db.query(Track)
        .join(Album, Track.album_id == Album.id)
        .options(joinedload(Track.album))
        .filter(Album.artist_id == artist_id)
        .all()
    )

    # Build lookup structures
    mbid_map = {}
    title_list = []
    for lt in local_tracks:
        if lt.musicbrainz_id:
            mbid_map[lt.musicbrainz_id] = lt
        title_list.append(lt)

    def find_local_match(lastfm_name: str, lastfm_mbid: str | None):
        # Try MBID match first
        if lastfm_mbid and lastfm_mbid in mbid_map:
            return mbid_map[lastfm_mbid]
        # Fuzzy title match
        best_match = None
        best_score = 0.0
        for lt in title_list:
            score = SequenceMatcher(None, lastfm_name.lower(), lt.title.lower()).ratio()
            if score > best_score:
                best_score = score
                best_match = lt
        if best_match and best_score >= 0.75:
            return best_match
        return None

    results = []
    for lfm in lastfm_tracks:
        match = find_local_match(lfm["name"], lfm.get("mbid"))
        results.append({
            "track_name": lfm["name"],
            "listeners": lfm["listeners"],
            "playcount": lfm["playcount"],
            "local_track_id": str(match.id) if match else None,
            "has_file": match.has_file if match else False,
            "file_path": match.file_path if match else None,
            "album_title": match.album.title if match and match.album else None,
            "album_cover_art_url": match.album.cover_art_url if match and match.album else None,
            "album_id": str(match.album_id) if match else None,
            "duration_ms": match.duration_ms if match else None,
            "artist_name": artist.name,
            "artist_id": str(artist.id),
        })

    return {"error": None, "tracks": results}


@router.patch("/artists/{artist_id}")
@rate_limit("50/minute")
async def update_artist(
    request: Request,
    artist_id: str,
    is_monitored: Optional[bool] = None,
    quality_profile_id: Optional[str] = None,
    root_folder_path: Optional[str] = None,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Update artist settings

    Args:
        artist_id: Artist UUID
        is_monitored: Monitor status
        quality_profile_id: Quality profile ID
        root_folder_path: Root folder path

    Returns:
        Updated artist object
    """
    from app.security import validate_uuid
    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    try:
        if is_monitored is not None:
            artist.is_monitored = is_monitored

        if quality_profile_id is not None:
            if quality_profile_id:
                validate_uuid(quality_profile_id, "Quality Profile ID")
            artist.quality_profile_id = quality_profile_id

        if root_folder_path is not None:
            artist.root_folder_path = root_folder_path

        db.commit()
        db.refresh(artist)

        # Create folder if artist is now monitored
        if is_monitored is True:
            try:
                from app.services.folder_creator import get_folder_creator
                folder_creator = get_folder_creator(db)
                success, folder_path, error = folder_creator.create_artist_folder(artist)
                if success:
                    logger.info(f"Created folder for monitored artist {artist.name}: {folder_path}")
                elif error:
                    logger.warning(f"Failed to create folder for artist {artist.name}: {error}")
            except Exception as e:
                logger.error(f"Error creating folder for artist {artist.name}: {e}", exc_info=True)

        logger.info(f"Updated artist: {artist.name} (ID: {artist_id})")

        return {
            "id": str(artist.id),
            "name": artist.name,
            "is_monitored": artist.is_monitored,
            "quality_profile_id": str(artist.quality_profile_id) if artist.quality_profile_id else None,
            "root_folder_path": artist.root_folder_path
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update artist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update artist: {str(e)}"
        )


@router.delete("/artists/{artist_id}")
@rate_limit("50/minute")
async def delete_artist(
    request: Request,
    artist_id: str,
    delete_files: bool = False,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Remove artist from monitoring

    Args:
        artist_id: Artist UUID
        delete_files: Delete music files from disk

    Returns:
        Success message
    """
    from app.security import validate_uuid
    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    try:
        artist_name = artist.name
        files_deleted_count = 0

        # Delete linked files from disk if requested
        if delete_files:
            import os
            tracks_with_files = (
                db.query(Track)
                .join(Album, Track.album_id == Album.id)
                .filter(Album.artist_id == artist_id, Track.has_file == True, Track.file_path.isnot(None))
                .all()
            )
            for track in tracks_with_files:
                try:
                    if os.path.exists(track.file_path):
                        os.remove(track.file_path)
                        files_deleted_count += 1
                        logger.info(f"Deleted file: {track.file_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete file {track.file_path}: {e}")

            # Clean up empty directories left behind
            dirs_to_check = set()
            for track in tracks_with_files:
                if track.file_path:
                    parent = os.path.dirname(track.file_path)
                    if parent:
                        dirs_to_check.add(parent)
            for dir_path in sorted(dirs_to_check, key=len, reverse=True):
                try:
                    if os.path.isdir(dir_path) and not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.info(f"Removed empty directory: {dir_path}")
                        # Also check parent
                        parent = os.path.dirname(dir_path)
                        if parent and os.path.isdir(parent) and not os.listdir(parent):
                            os.rmdir(parent)
                            logger.info(f"Removed empty parent directory: {parent}")
                except OSError as e:
                    logger.debug(f"Could not remove directory {dir_path}: {e}")

        # Delete artist (cascade deletes albums, tracks, downloads)
        db.delete(artist)
        db.commit()

        logger.info(f"Deleted artist: {artist_name} (ID: {artist_id}, delete_files: {delete_files}, files_deleted: {files_deleted_count})")

        return {
            "success": True,
            "message": f"Artist '{artist_name}' removed" + (f" ({files_deleted_count} files deleted)" if delete_files else ""),
            "files_deleted": delete_files,
            "files_deleted_count": files_deleted_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete artist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete artist: {str(e)}"
        )


@router.post("/artists/{artist_id}/sync")
@rate_limit("20/minute")
async def sync_artist_albums(
    request: Request,
    artist_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Trigger album sync for artist

    Args:
        artist_id: Artist UUID

    Returns:
        Sync job status
    """
    from app.security import validate_uuid
    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    try:
        # Trigger Celery background task with job tracking parameters
        from app.tasks.sync_tasks import sync_artist_albums as sync_task
        from app.models.job_state import JobType

        task = sync_task.apply_async(
            args=[str(artist.id)],
            kwargs={
                'job_type': JobType.ARTIST_SYNC,
                'entity_type': 'artist',
                'entity_id': str(artist.id)
            }
        )

        logger.info(f"Triggered album sync for artist: {artist.name} (ID: {artist_id}, Task: {task.id})")

        return {
            "success": True,
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            "message": "Album sync started",
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger album sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger album sync: {str(e)}"
        )


@router.post("/artists/{artist_id}/refresh-metadata")
@rate_limit("20/minute")
async def refresh_artist_metadata_endpoint(
    request: Request,
    artist_id: str,
    force: bool = False,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Refresh metadata (images) for a single artist

    Fetches missing artist images and album cover art without doing a full
    album sync from MusicBrainz. This is faster than a full sync.

    Args:
        artist_id: Artist UUID
        force: If true, re-fetch metadata even if fields already have values

    Returns:
        Refresh job status
    """
    from app.security import validate_uuid
    validate_uuid(artist_id, "Artist ID")
    
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )
    
    try:
        from app.tasks.sync_tasks import refresh_artist_metadata
        from app.models.job_state import JobType
        
        task = refresh_artist_metadata.apply_async(
            args=[str(artist.id)],
            kwargs={
                'force': force,
                'job_type': JobType.METADATA_REFRESH,
                'entity_type': 'artist',
                'entity_id': str(artist.id)
            }
        )
        
        logger.info(f"Triggered metadata refresh for artist: {artist.name} (ID: {artist_id}, Task: {task.id})")
        
        return {
            "success": True,
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            "message": "Metadata refresh started",
            "task_id": task.id
        }
        
    except Exception as e:
        logger.error(f"Failed to trigger metadata refresh: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger metadata refresh: {str(e)}"
        )


@router.post("/artists/{artist_id}/scan-folder")
@rate_limit("20/minute")
async def scan_artist_folder(
    request: Request,
    artist_id: str,
    folder_path: str = Body(..., embed=True),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Scan artist folder and automatically assign album folder paths

    Scans the specified artist folder for album subdirectories and
    automatically assigns custom_folder_path to matching albums.

    Args:
        artist_id: Artist UUID
        folder_path: Path to artist's folder (e.g., /music/Pink Floyd/)

    Returns:
        Scan results with matched albums
    """
    from app.security import validate_uuid
    from pathlib import Path
    from difflib import SequenceMatcher

    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()

    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    # Validate folder path
    folder = Path(folder_path)
    if not folder.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Folder path does not exist: {folder_path}"
        )

    if not folder.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {folder_path}"
        )

    try:
        # Update artist's root_folder_path
        artist.root_folder_path = str(folder_path)

        # Find all subdirectories (potential album folders)
        subdirs = [d for d in folder.iterdir() if d.is_dir()]
        logger.info(f"Found {len(subdirs)} subdirectories in {folder_path}")

        # Get all albums for this artist
        albums = db.query(Album).filter(Album.artist_id == artist_id).all()

        if not albums:
            db.commit()
            return {
                "artist_id": str(artist_id),
                "artist_name": artist.name,
                "folder_path": folder_path,
                "subdirectories_found": len(subdirs),
                "albums_matched": 0,
                "matches": [],
                "message": "No albums found for this artist"
            }

        # Match subdirectories to albums
        matches = []
        matched_count = 0

        def normalize_string(s: str) -> str:
            """Normalize string for comparison"""
            import re
            # Remove special characters, convert to lowercase
            s = re.sub(r'[^\w\s]', '', s.lower())
            # Remove common words
            for word in ['the', 'a', 'an']:
                s = s.replace(f' {word} ', ' ')
            return s.strip()

        def string_similarity(s1: str, s2: str) -> float:
            """Calculate string similarity"""
            return SequenceMatcher(None, normalize_string(s1), normalize_string(s2)).ratio()

        for subdir in subdirs:
            subdir_name = subdir.name
            best_match = None
            best_score = 0.0

            for album in albums:
                score = string_similarity(subdir_name, album.title)

                # Also check if album title is contained in folder name
                if normalize_string(album.title) in normalize_string(subdir_name):
                    score = max(score, 0.9)

                if score > best_score:
                    best_score = score
                    best_match = album

            # Only auto-assign if confidence is high (70%+)
            if best_match and best_score >= 0.7:
                best_match.custom_folder_path = str(subdir)
                matched_count += 1
                matches.append({
                    "album_id": str(best_match.id),
                    "album_title": best_match.title,
                    "folder_name": subdir_name,
                    "folder_path": str(subdir),
                    "confidence": round(best_score * 100, 1),
                    "auto_assigned": True
                })
                logger.info(f"Auto-assigned: '{best_match.title}' -> {subdir_name} (confidence: {best_score*100:.1f}%)")
            else:
                # Include low-confidence matches for manual review
                if best_match and best_score >= 0.5:
                    matches.append({
                        "album_id": str(best_match.id),
                        "album_title": best_match.title,
                        "folder_name": subdir_name,
                        "folder_path": str(subdir),
                        "confidence": round(best_score * 100, 1),
                        "auto_assigned": False
                    })

        db.commit()

        return {
            "artist_id": str(artist_id),
            "artist_name": artist.name,
            "folder_path": folder_path,
            "subdirectories_found": len(subdirs),
            "albums_matched": matched_count,
            "matches": sorted(matches, key=lambda x: x['confidence'], reverse=True),
            "message": f"Successfully assigned {matched_count} album folder paths"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to scan artist folder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scan folder: {str(e)}"
        )


@router.post("/artists/refresh-all-metadata")
@rate_limit("5/hour")
async def refresh_all_metadata_endpoint(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Refresh metadata for ALL artists in the library
    
    This queues individual metadata refresh tasks for every artist.
    Can take a long time for large libraries.
    
    Returns:
        Bulk refresh job status
    """
    try:
        from app.tasks.sync_tasks import refresh_all_metadata
        from app.models.job_state import JobType
        
        # Count total artists
        total_artists = db.query(Artist).count()
        
        if total_artists == 0:
            return {
                "success": False,
                "message": "No artists in library",
                "total_artists": 0
            }
        
        task = refresh_all_metadata.apply_async(
            kwargs={
                'job_type': JobType.METADATA_REFRESH,
                'entity_type': 'library',
                'entity_id': None  # NULL for bulk operations
            }
        )
        
        logger.info(f"Triggered metadata refresh for all {total_artists} artists (Task: {task.id})")
        
        return {
            "success": True,
            "message": f"Queuing metadata refresh for {total_artists} artists",
            "total_artists": total_artists,
            "task_id": task.id
        }
        
    except Exception as e:
        logger.error(f"Failed to trigger bulk metadata refresh: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger bulk metadata refresh: {str(e)}"
        )


@router.post("/artists/sync-all-albums")
@rate_limit("2/hour")
async def sync_all_albums_endpoint(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Sync albums and tracks for ALL artists in the library.

    Fetches album/track data from MusicBrainz for every artist,
    creating missing albums and backfilling tracks for albums with zero tracks.
    Uses the local MusicBrainz DB when available (no rate limiting).
    """
    try:
        from app.tasks.sync_tasks import sync_all_albums
        from app.models.job_state import JobType

        total_artists = db.query(Artist).filter(
            Artist.musicbrainz_id.isnot(None),
            Artist.musicbrainz_id != ''
        ).count()

        if total_artists == 0:
            return {
                "success": False,
                "message": "No artists with MusicBrainz IDs in library",
                "total_artists": 0
            }

        task = sync_all_albums.apply_async(
            kwargs={
                'job_type': JobType.ARTIST_SYNC,
                'entity_type': 'library',
                'entity_id': None
            }
        )

        logger.info(f"Triggered full album sync for {total_artists} artists (Task: {task.id})")

        return {
            "success": True,
            "message": f"Syncing albums for {total_artists} artists",
            "total_artists": total_artists,
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger full album sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger full album sync: {str(e)}"
        )


@router.post("/artists/import/muse")
@rate_limit("20/minute")
async def import_artists_from_muse(
    request: Request,
    import_request: ImportArtistsRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Import artists from MUSE library

    Process:
    1. Query MUSE /libraries/{id}/artists endpoint
    2. For each artist:
       - Check if already exists (by name or MBID)
       - If no MBID and auto_match=True, search MusicBrainz
       - Create Artist record (unmonitored by default)
       - Queue background album sync

    Returns:
        Summary: imported_count, skipped_count, failed_count
    """
    import httpx
    import os

    muse_library_id = import_request.library_id
    artist_names = import_request.artist_names
    auto_match_mbid = import_request.auto_match_mbid
    is_monitored = import_request.is_monitored

    # Get MUSE service URL from environment
    muse_url = os.getenv("MUSE_SERVICE_URL", "http://muse-service:8007")

    imported_count = 0
    skipped_count = 0
    failed_count = 0
    imported_artists = []
    skipped_artists = []

    try:
        # Query MUSE for artists
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{muse_url}/api/v1/libraries/{muse_library_id}/artists",
                params={"limit": 1000, "offset": 0},
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

        artists_data = data.get("artists", [])

        # Filter to specific artists if requested
        if artist_names:
            artists_data = [a for a in artists_data if a.get("name") in artist_names]

        mb_client = get_musicbrainz_client()

        for artist_data in artists_data:
            artist_name = artist_data.get("name")
            mbid = artist_data.get("musicbrainz_id")

            if not artist_name:
                failed_count += 1
                continue

            try:
                # Check if artist already exists
                existing = None
                if mbid:
                    existing = db.query(Artist).filter(Artist.musicbrainz_id == mbid).first()

                if not existing:
                    # Check by name (case-insensitive)
                    existing = db.query(Artist).filter(
                        Artist.name.ilike(artist_name)
                    ).first()

                if existing:
                    logger.info(f"Artist '{artist_name}' already exists, skipping")
                    skipped_count += 1
                    skipped_artists.append(artist_name)
                    continue

                # Auto-match MBID if needed
                if not mbid and auto_match_mbid:
                    logger.info(f"Searching MusicBrainz for '{artist_name}'...")
                    search_results = mb_client.search_artist(artist_name, limit=1)
                    if search_results and len(search_results) > 0:
                        top_result = search_results[0]
                        score = top_result.get("score", 0)
                        if score >= 95:  # High confidence match
                            mbid = top_result.get("id")
                            logger.info(f"Auto-matched '{artist_name}' to MBID {mbid} (score: {score})")

                # Create artist
                if mbid:
                    artist = Artist(
                        name=artist_name,
                        musicbrainz_id=mbid,
                        is_monitored=is_monitored,
                        import_source="muse",
                        muse_library_id=muse_library_id,
                        added_at=datetime.now(timezone.utc)
                    )

                    db.add(artist)
                    db.commit()
                    db.refresh(artist)

                    # Queue album sync task
                    from app.tasks.sync_tasks import sync_artist_albums as sync_task
                    try:
                        sync_task.delay(str(artist.id))
                    except Exception as e:
                        logger.warning(f"Failed to queue album sync for {artist_name}: {e}")

                    imported_count += 1
                    imported_artists.append({"name": artist_name, "musicbrainz_id": mbid})
                    logger.info(f"Imported artist '{artist_name}' from MUSE")
                else:
                    logger.warning(f"Skipping '{artist_name}' - no MBID and auto-match failed")
                    skipped_count += 1
                    skipped_artists.append(artist_name)

            except Exception as e:
                logger.error(f"Failed to import artist '{artist_name}': {e}")
                failed_count += 1
                db.rollback()

        return {
            "success": True,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "total_processed": len(artists_data),
            "imported_artists": imported_artists,
            "skipped_artists": skipped_artists
        }

    except Exception as e:
        logger.error(f"MUSE import failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import from MUSE: {str(e)}"
        )


@router.post("/artists/import/studio54")
@rate_limit("20/minute")
async def import_artists_from_studio54(
    request: Request,
    import_request: ImportArtistsRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Import artists from Studio54 local library

    Process:
    1. Query library_files table for distinct artists
    2. Group by artist/album_artist
    3. Extract MBIDs from library_files
    4. Create Artist records with Studio54 source tracking
    """
    from app.models.library import LibraryFile
    from sqlalchemy import func, distinct, case, or_

    library_path_id = import_request.library_id
    artist_names = import_request.artist_names
    auto_match_mbid = import_request.auto_match_mbid
    is_monitored = import_request.is_monitored

    imported_count = 0
    skipped_count = 0
    failed_count = 0
    imported_artists = []
    skipped_artists = []

    try:
        # Query unique artists from library_files
        artist_name = case(
            (LibraryFile.album_artist.isnot(None), LibraryFile.album_artist),
            else_=LibraryFile.artist
        ).label('artist_name')

        query = db.query(
            artist_name,
            LibraryFile.musicbrainz_artistid,
            func.count(distinct(LibraryFile.id)).label('file_count')
        ).filter(
            LibraryFile.library_path_id == library_path_id,
            or_(LibraryFile.artist.isnot(None), LibraryFile.album_artist.isnot(None))
        ).group_by(
            artist_name,
            LibraryFile.musicbrainz_artistid
        )

        # Filter to specific artists if requested
        if artist_names:
            query = query.filter(artist_name.in_(artist_names))

        results = query.all()

        mb_client = get_musicbrainz_client()

        for result in results:
            name = result.artist_name
            mbid = result.musicbrainz_artistid

            if not name:
                failed_count += 1
                continue

            try:
                # Check if artist already exists
                existing = None
                if mbid:
                    existing = db.query(Artist).filter(Artist.musicbrainz_id == mbid).first()

                if not existing:
                    existing = db.query(Artist).filter(Artist.name.ilike(name)).first()

                if existing:
                    logger.info(f"Artist '{name}' already exists, skipping")
                    skipped_count += 1
                    skipped_artists.append(name)
                    continue

                # Auto-match MBID if needed
                if not mbid and auto_match_mbid:
                    logger.info(f"Searching MusicBrainz for '{name}'...")
                    search_results = mb_client.search_artist(name, limit=1)
                    if search_results and len(search_results) > 0:
                        top_result = search_results[0]
                        score = top_result.get("score", 0)
                        if score >= 95:
                            mbid = top_result.get("id")
                            logger.info(f"Auto-matched '{name}' to MBID {mbid} (score: {score})")

                # Create artist
                if mbid:
                    try:
                        artist = Artist(
                            name=name,
                            musicbrainz_id=mbid,
                            is_monitored=is_monitored,
                            import_source="studio54",
                            studio54_library_path_id=library_path_id,
                            added_at=datetime.now(timezone.utc)
                        )

                        db.add(artist)
                        db.commit()
                        db.refresh(artist)

                        # Queue album sync task
                        from app.tasks.sync_tasks import sync_artist_albums as sync_task
                        try:
                            sync_task.delay(str(artist.id))
                        except Exception as e:
                            logger.warning(f"Failed to queue album sync for {name}: {e}")

                        imported_count += 1
                        imported_artists.append({"name": name, "musicbrainz_id": mbid})
                        logger.info(f"Imported artist '{name}' from Studio54 library")
                    except Exception as db_error:
                        db.rollback()
                        # If it's a duplicate key error, just skip it
                        error_str = str(db_error).lower()
                        if "duplicate key" in error_str or "unique constraint" in error_str:
                            logger.info(f"Artist '{name}' already exists (duplicate key), skipping")
                            skipped_count += 1
                            skipped_artists.append(name)
                        else:
                            # Some other error - log and count as failed
                            raise
                else:
                    logger.warning(f"Skipping '{name}' - no MBID and auto-match failed")
                    skipped_count += 1
                    skipped_artists.append(name)

            except Exception as e:
                logger.error(f"Failed to import artist '{name}': {e}")
                failed_count += 1
                db.rollback()

        return {
            "success": True,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "total_processed": len(results),
            "imported_artists": imported_artists,
            "skipped_artists": skipped_artists
        }

    except Exception as e:
        logger.error(f"Studio54 import failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import from Studio54: {str(e)}"
        )


@router.patch("/artists/bulk-update")
@rate_limit("30/minute")
async def bulk_update_artists(
    request: Request,
    update_request: BulkUpdateRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Bulk update artist settings

    Use case: Select multiple artists -> Monitor all
    """
    from app.security import validate_uuid

    artist_ids = update_request.artist_ids
    is_monitored = update_request.is_monitored
    quality_profile_id = update_request.quality_profile_id

    if not artist_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No artist IDs provided"
        )

    # Validate all IDs
    for artist_id in artist_ids:
        validate_uuid(artist_id, "Artist ID")

    updated_count = 0

    try:
        for artist_id in artist_ids:
            artist = db.query(Artist).filter(Artist.id == artist_id).first()

            if not artist:
                logger.warning(f"Artist {artist_id} not found, skipping")
                continue

            if is_monitored is not None:
                artist.is_monitored = is_monitored

            if quality_profile_id is not None:
                if quality_profile_id:
                    validate_uuid(quality_profile_id, "Quality Profile ID")
                artist.quality_profile_id = quality_profile_id

            updated_count += 1

        db.commit()

        logger.info(f"Bulk updated {updated_count} artists")

        return {
            "success": True,
            "updated_count": updated_count,
            "total_requested": len(artist_ids)
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Bulk update failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk update failed: {str(e)}"
        )


@router.post("/artists/{artist_id}/resolve-mbid")
@rate_limit("50/minute")
async def resolve_artist_mbid(
    request: Request,
    artist_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Search local MusicBrainz database for an artist's MBID.

    Uses local DB only (no remote API fallback) to find matching artists
    by name similarity. Returns top matches for user selection.
    """
    from app.security import validate_uuid
    from app.services.musicbrainz_local import get_musicbrainz_local_db

    validate_uuid(artist_id, "Artist ID")

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    local_db = get_musicbrainz_local_db()
    if not local_db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local MusicBrainz database is not available"
        )

    try:
        results = local_db.search_artist(artist.name, limit=10)

        matches = []
        for r in results:
            matches.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "disambiguation": r.get("disambiguation", ""),
                "type": r.get("type"),
                "score": r.get("score", 0),
            })

        return {
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            "current_mbid": artist.musicbrainz_id,
            "matches": matches,
            "total": len(matches),
        }

    except Exception as e:
        logger.error(f"Failed to resolve MBID for artist {artist.name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MBID resolution failed: {str(e)}"
        )


class SetMusicbrainzIdRequest(BaseModel):
    """Request model for setting an artist's MusicBrainz ID"""
    musicbrainz_id: str
    trigger_sync: bool = True


@router.patch("/artists/{artist_id}/musicbrainz-id")
@rate_limit("50/minute")
async def set_artist_musicbrainz_id(
    request: Request,
    artist_id: str,
    body: SetMusicbrainzIdRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Set or update an artist's MusicBrainz ID.

    Optionally triggers album sync after updating the MBID.
    """
    from app.security import validate_uuid

    validate_uuid(artist_id, "Artist ID")
    validate_mbid(body.musicbrainz_id)

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )

    # Check if MBID is already used by another artist
    existing = db.query(Artist).filter(
        Artist.musicbrainz_id == body.musicbrainz_id,
        Artist.id != artist_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"MBID already assigned to artist '{existing.name}'"
        )

    try:
        old_mbid = artist.musicbrainz_id
        artist.musicbrainz_id = body.musicbrainz_id
        db.commit()
        db.refresh(artist)

        logger.info(f"Updated MBID for artist '{artist.name}': {old_mbid} -> {body.musicbrainz_id}")

        # Optionally trigger album sync
        sync_task_id = None
        if body.trigger_sync:
            from app.tasks.sync_tasks import sync_artist_albums as sync_task
            try:
                task = sync_task.delay(str(artist.id))
                sync_task_id = task.id
                logger.info(f"Triggered album sync for artist {artist.name} after MBID update")
            except Exception as e:
                logger.warning(f"Failed to trigger album sync: {e}")

        return {
            "success": True,
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            "musicbrainz_id": artist.musicbrainz_id,
            "old_musicbrainz_id": old_mbid,
            "sync_task_id": sync_task_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to set MBID for artist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set MBID: {str(e)}"
        )


@router.post("/artists/bulk-resolve-mbid")
@rate_limit("10/minute")
async def bulk_resolve_mbid(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Batch resolve MBIDs for all artists missing them using local MusicBrainz DB.

    Auto-updates artists where confidence is high (score >= 95 and single top match).
    Returns resolved and unresolved lists.
    """
    from app.services.musicbrainz_local import get_musicbrainz_local_db

    local_db = get_musicbrainz_local_db()
    if not local_db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local MusicBrainz database is not available"
        )

    try:
        # Get all artists without MBIDs
        artists_without_mbid = db.query(Artist).filter(
            Artist.musicbrainz_id.is_(None)
        ).all()

        if not artists_without_mbid:
            return {
                "resolved": [],
                "unresolved": [],
                "stats": {"total": 0, "resolved": 0, "unresolved": 0},
            }

        resolved = []
        unresolved = []

        for artist in artists_without_mbid:
            try:
                results = local_db.search_artist(artist.name, limit=3)

                if results and len(results) > 0:
                    top = results[0]
                    score = top.get("score", 0)

                    # Auto-resolve if score >= 95
                    if score >= 95:
                        mbid = top.get("id")

                        # Check MBID not already in use
                        existing = db.query(Artist).filter(
                            Artist.musicbrainz_id == mbid
                        ).first()

                        if not existing:
                            artist.musicbrainz_id = mbid
                            resolved.append({
                                "id": str(artist.id),
                                "name": artist.name,
                                "mbid": mbid,
                                "score": score,
                                "matched_name": top.get("name"),
                            })
                            continue

                    # Not auto-resolved
                    unresolved.append({
                        "id": str(artist.id),
                        "name": artist.name,
                        "top_match": {
                            "name": top.get("name"),
                            "mbid": top.get("id"),
                            "score": score,
                        } if results else None,
                    })
                else:
                    unresolved.append({
                        "id": str(artist.id),
                        "name": artist.name,
                        "top_match": None,
                    })

            except Exception as e:
                logger.warning(f"Failed to resolve MBID for '{artist.name}': {e}")
                unresolved.append({
                    "id": str(artist.id),
                    "name": artist.name,
                    "top_match": None,
                })

        db.commit()
        logger.info(f"Bulk MBID resolution: {len(resolved)} resolved, {len(unresolved)} unresolved out of {len(artists_without_mbid)} total")

        return {
            "resolved": resolved,
            "unresolved": unresolved,
            "stats": {
                "total": len(artists_without_mbid),
                "resolved": len(resolved),
                "unresolved": len(unresolved),
            },
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Bulk MBID resolution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk resolution failed: {str(e)}"
        )


class BulkResolveRemoteRequest(BaseModel):
    """Request model for remote bulk MBID resolution"""
    artist_ids: List[str]


@router.post("/artists/bulk-resolve-mbid/remote")
@rate_limit("5/minute")
async def bulk_resolve_mbid_remote(
    request: Request,
    body: BulkResolveRemoteRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Batch resolve MBIDs via remote MusicBrainz API for unresolved artists.

    Creates a Celery task that queries the remote API (respecting rate limits).
    Returns task ID for progress tracking.
    """
    if not body.artist_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No artist IDs provided"
        )

    from app.security import validate_uuid
    for aid in body.artist_ids:
        validate_uuid(aid, "Artist ID")

    try:
        from app.tasks.sync_tasks import bulk_resolve_mbid_remote_task

        task = bulk_resolve_mbid_remote_task.delay(body.artist_ids)
        logger.info(f"Started remote MBID resolution for {len(body.artist_ids)} artists (task: {task.id})")

        return {
            "success": True,
            "task_id": task.id,
            "artist_count": len(body.artist_ids),
            "message": f"Queued remote MBID resolution for {len(body.artist_ids)} artists",
        }

    except Exception as e:
        logger.error(f"Failed to start remote MBID resolution: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start remote resolution: {str(e)}"
        )


@router.post("/artists/import-unlinked")
@rate_limit("10/minute")
async def import_unlinked_artists(
    request: Request,
    import_request: ImportUnlinkedRequest = Body(default=ImportUnlinkedRequest()),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Import artists from library files that have MBIDs but no matching track in the DB.

    Dispatches a Celery task that finds files with Recording MBIDs that couldn't be linked,
    extracts unique Artist MBIDs, creates Artist records, and queues album sync.
    Returns a task_id for progress tracking.
    """
    try:
        if import_request.library_path_id:
            from app.security import validate_uuid
            validate_uuid(import_request.library_path_id, "Library Path ID")

        from app.tasks.sync_tasks import import_unlinked_artists_task

        task = import_unlinked_artists_task.delay(
            library_path_id=import_request.library_path_id,
            is_monitored=import_request.is_monitored,
            auto_sync=import_request.auto_sync,
        )
        logger.info(f"Started import unlinked artists task (task: {task.id})")

        return {
            "success": True,
            "task_id": task.id,
            "message": "Import unlinked artists task queued",
        }

    except Exception as e:
        logger.error(f"Import unlinked artists failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start import unlinked artists: {str(e)}"
        )


# ── Cover Art ────────────────────────────────────────────────────────


@router.post("/{artist_id}/cover-art", dependencies=[Depends(require_dj_or_above)])
async def upload_artist_cover_art(
    request: Request,
    artist_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload cover art for an artist."""
    validate_uuid(artist_id)

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    filepath = await save_entity_cover_art("artist", artist_id, file)
    artist.image_url = filepath
    db.commit()

    return {"success": True, "image_url": filepath}


@router.post("/{artist_id}/cover-art-from-url", dependencies=[Depends(require_dj_or_above)])
async def upload_artist_cover_art_from_url(
    request: Request,
    artist_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Fetch cover art for an artist from a remote URL."""
    from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url

    validate_uuid(artist_id)

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    filepath = await fetch_and_save_entity_cover_art_from_url("artist", artist_id, url)
    artist.image_url = filepath
    db.commit()

    return {"success": True, "image_url": filepath}


@router.get("/{artist_id}/cover-art")
async def get_artist_cover_art(
    request: Request,
    artist_id: str,
    db: Session = Depends(get_db),
):
    """Serve cover art for an artist.

    Falls back to an album cover if the artist has no dedicated image.
    """
    from fastapi.responses import RedirectResponse
    validate_uuid(artist_id)

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    # Use artist's own image_url if present
    cover_url = artist.image_url

    # Fallback: use first album cover (same logic as the detail endpoint)
    if not cover_url:
        album = (
            db.query(Album)
            .filter(Album.artist_id == artist_id, Album.cover_art_url.isnot(None))
            .first()
        )
        if album:
            cover_url = album.cover_art_url

    # If cover_url is an external URL, redirect directly (avoids serve_entity_cover_art
    # trying to open it as a local file path)
    if cover_url and cover_url.startswith(("http://", "https://")):
        return RedirectResponse(url=cover_url, status_code=302)

    return serve_entity_cover_art("artist", artist_id, cover_url)

