"""
Playlists API Router
Playlist management with ownership, publishing, and cover art
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from pathlib import Path
import logging
import uuid as uuid_mod

from app.database import get_db
from app.models.playlist import Playlist, PlaylistTrack, PlaylistChapter
from app.models.track import Track
from app.models.chapter import Chapter
from app.models.book import Book
from app.models.author import Author
from app.models.album import Album
from app.models.artist import Artist
from app.security import rate_limit, validate_uuid
from app.auth import require_any_user, require_dj_or_above
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

COVER_ART_DIR = Path("/docker/studio54/playlist-art")


# Pydantic schemas
class PlaylistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class PlaylistUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class TrackAdd(BaseModel):
    track_id: str


class ChapterAdd(BaseModel):
    chapter_id: str


class BulkChapterAdd(BaseModel):
    chapter_ids: List[str] = Field(..., min_length=1, max_length=1000)


class BulkTrackAdd(BaseModel):
    track_ids: List[str] = Field(..., min_length=1, max_length=1000)


class PlaylistReorder(BaseModel):
    track_positions: List[dict] = Field(..., description="List of {track_id: str, position: int}")


def _check_playlist_ownership(playlist: Playlist, current_user: User):
    """Raise 403 if user doesn't own the playlist and isn't a director"""
    if current_user.role != "director" and str(playlist.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own playlists"
        )


def _playlist_response(playlist: Playlist, track_count: Optional[int] = None, chapter_count: Optional[int] = None):
    """Standard playlist response dict"""
    t_count = track_count if track_count is not None else len(playlist.playlist_tracks)
    c_count = chapter_count if chapter_count is not None else (len(playlist.playlist_chapters) if hasattr(playlist, 'playlist_chapters') and playlist.playlist_chapters is not None else 0)
    return {
        "id": str(playlist.id),
        "name": playlist.name,
        "description": playlist.description,
        "user_id": str(playlist.user_id) if playlist.user_id else None,
        "owner_name": playlist.owner.display_name or playlist.owner.username if playlist.owner else None,
        "is_published": playlist.is_published,
        "cover_art_url": f"/api/v1/playlists/{playlist.id}/cover-art" if playlist.cover_art_url else None,
        "track_count": t_count + c_count,
        "created_at": playlist.created_at.isoformat() if playlist.created_at else None,
        "updated_at": playlist.updated_at.isoformat() if playlist.updated_at else None,
    }


@router.get("/playlists")
@rate_limit("100/minute")
async def list_playlists(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """List current user's playlists"""
    query = db.query(Playlist).filter(Playlist.user_id == current_user.id)
    total_count = query.count()
    playlists = query.options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters),
        joinedload(Playlist.owner)
    ).order_by(Playlist.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "playlists": [_playlist_response(p) for p in playlists]
    }


@router.get("/playlists/published")
@rate_limit("100/minute")
async def list_published_playlists(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """List all published playlists (Sound Booth)"""
    query = db.query(Playlist).filter(Playlist.is_published == True)
    total_count = query.count()
    playlists = query.options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters),
        joinedload(Playlist.owner)
    ).order_by(Playlist.updated_at.desc()).limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "playlists": [_playlist_response(p) for p in playlists]
    }


@router.get("/playlists/{playlist_id}")
@rate_limit("100/minute")
async def get_playlist(
    request: Request,
    playlist_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Get playlist details with tracks"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).options(
        selectinload(Playlist.playlist_tracks)
        .joinedload(PlaylistTrack.track)
        .joinedload(Track.album)
        .joinedload(Album.artist),
        selectinload(Playlist.playlist_chapters)
        .joinedload(PlaylistChapter.chapter)
        .joinedload(Chapter.book)
        .joinedload(Book.author),
        joinedload(Playlist.owner)
    ).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    tracks_data = []
    for playlist_track in playlist.playlist_tracks:
        track = playlist_track.track
        if track and track.album:
            tracks_data.append({
                "id": str(track.id),
                "title": track.title,
                "track_number": track.track_number,
                "duration_ms": track.duration_ms,
                "has_file": track.has_file,
                "muse_file_id": str(track.muse_file_id) if track.muse_file_id else None,
                "album_id": str(track.album_id),
                "album_title": track.album.title,
                "artist_name": track.album.artist.name if track.album.artist else "Unknown",
                "cover_art_url": track.album.cover_art_url,
                "position": playlist_track.position,
                "added_at": playlist_track.added_at.isoformat() if playlist_track.added_at else None,
                "is_book_chapter": False,
            })

    for playlist_chapter in playlist.playlist_chapters:
        chapter = playlist_chapter.chapter
        if chapter and chapter.book:
            book = chapter.book
            tracks_data.append({
                "id": str(chapter.id),
                "title": chapter.title,
                "track_number": chapter.chapter_number,
                "duration_ms": chapter.duration_ms,
                "has_file": chapter.has_file,
                "muse_file_id": None,
                "album_id": str(book.id),
                "album_title": book.title,
                "artist_name": book.author.name if book.author else "Unknown",
                "cover_art_url": book.cover_art_url,
                "position": playlist_chapter.position,
                "added_at": playlist_chapter.added_at.isoformat() if playlist_chapter.added_at else None,
                "is_book_chapter": True,
            })

    tracks_data.sort(key=lambda x: x["position"])

    resp = _playlist_response(playlist, track_count=len(playlist.playlist_tracks), chapter_count=len(playlist.playlist_chapters))
    resp["tracks"] = tracks_data
    return resp


@router.post("/playlists", status_code=status.HTTP_201_CREATED)
@rate_limit("30/minute")
async def create_playlist(
    request: Request,
    playlist_data: PlaylistCreate,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Create a new playlist owned by current user"""
    existing = db.query(Playlist).filter(
        Playlist.name == playlist_data.name,
        Playlist.user_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a playlist named '{playlist_data.name}'"
        )

    playlist = Playlist(
        name=playlist_data.name,
        description=playlist_data.description,
        user_id=current_user.id
    )

    db.add(playlist)
    db.commit()
    db.refresh(playlist)

    logger.info(f"Created playlist: {playlist.name} (ID: {playlist.id}) by user {current_user.username}")

    return _playlist_response(playlist, track_count=0)


@router.put("/playlists/{playlist_id}")
@rate_limit("30/minute")
async def update_playlist(
    request: Request,
    playlist_id: str,
    playlist_data: PlaylistUpdate,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Update playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters),
        joinedload(Playlist.owner)
    ).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    if playlist_data.name and playlist_data.name != playlist.name:
        existing = db.query(Playlist).filter(
            Playlist.name == playlist_data.name,
            Playlist.user_id == playlist.user_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Playlist with name '{playlist_data.name}' already exists"
            )
        playlist.name = playlist_data.name

    if playlist_data.description is not None:
        playlist.description = playlist_data.description

    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(playlist)

    return _playlist_response(playlist)


@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("30/minute")
async def delete_playlist(
    request: Request,
    playlist_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Delete a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    logger.info(f"Deleting playlist: {playlist.name} (ID: {playlist.id})")
    db.delete(playlist)
    db.commit()


@router.post("/playlists/{playlist_id}/tracks", status_code=status.HTTP_201_CREATED)
@rate_limit("60/minute")
async def add_track_to_playlist(
    request: Request,
    playlist_id: str,
    track_data: TrackAdd,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Add a track to a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")
    validate_uuid(track_data.track_id, "Track ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    track = db.query(Track).filter(Track.id == track_data.track_id).first()
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    existing = db.query(PlaylistTrack).filter(
        PlaylistTrack.playlist_id == playlist_id,
        PlaylistTrack.track_id == track_data.track_id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Track already in playlist")

    max_position = (
        db.query(PlaylistTrack).filter(PlaylistTrack.playlist_id == playlist_id).count()
        + db.query(PlaylistChapter).filter(PlaylistChapter.playlist_id == playlist_id).count()
    )

    playlist_track = PlaylistTrack(
        playlist_id=playlist_id,
        track_id=track_data.track_id,
        position=max_position
    )

    db.add(playlist_track)
    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Added track {track.title} to playlist {playlist.name}")

    return {
        "message": "Track added to playlist",
        "track_count": len(playlist.playlist_tracks)
    }


@router.post("/playlists/{playlist_id}/tracks/bulk", status_code=status.HTTP_201_CREATED)
@rate_limit("30/minute")
async def add_tracks_bulk(
    request: Request,
    playlist_id: str,
    track_data: BulkTrackAdd,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Add multiple tracks to a playlist in a single request (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters)
    ).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    # Validate all track IDs
    for tid in track_data.track_ids:
        validate_uuid(tid, "Track ID")

    # Get existing track IDs in this playlist
    existing_track_ids = {
        str(pt.track_id) for pt in playlist.playlist_tracks
    }

    # Get current max position (accounts for both tracks and chapters)
    current_count = len(playlist.playlist_tracks) + len(playlist.playlist_chapters)

    # Verify tracks exist and add non-duplicates
    added_count = 0
    skipped_count = 0
    for tid in track_data.track_ids:
        if tid in existing_track_ids:
            skipped_count += 1
            continue

        track = db.query(Track).filter(Track.id == tid).first()
        if not track:
            skipped_count += 1
            continue

        playlist_track = PlaylistTrack(
            playlist_id=playlist_id,
            track_id=tid,
            position=current_count + added_count
        )
        db.add(playlist_track)
        existing_track_ids.add(tid)
        added_count += 1

    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Bulk added {added_count} tracks to playlist {playlist.name} (skipped {skipped_count})")

    return {
        "message": f"Added {added_count} tracks to playlist",
        "added_count": added_count,
        "skipped_count": skipped_count,
        "track_count": current_count + added_count
    }


@router.post("/playlists/{playlist_id}/chapters", status_code=status.HTTP_201_CREATED)
@rate_limit("60/minute")
async def add_chapter_to_playlist(
    request: Request,
    playlist_id: str,
    chapter_data: ChapterAdd,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Add an audiobook chapter to a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")
    validate_uuid(chapter_data.chapter_id, "Chapter ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    chapter = db.query(Chapter).filter(Chapter.id == chapter_data.chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    existing = db.query(PlaylistChapter).filter(
        PlaylistChapter.playlist_id == playlist_id,
        PlaylistChapter.chapter_id == chapter_data.chapter_id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chapter already in playlist")

    # Position accounts for both tracks and chapters
    max_position = (
        db.query(PlaylistTrack).filter(PlaylistTrack.playlist_id == playlist_id).count()
        + db.query(PlaylistChapter).filter(PlaylistChapter.playlist_id == playlist_id).count()
    )

    playlist_chapter = PlaylistChapter(
        playlist_id=playlist_id,
        chapter_id=chapter_data.chapter_id,
        position=max_position
    )

    db.add(playlist_chapter)
    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Added chapter {chapter.title} to playlist {playlist.name}")

    return {
        "message": "Chapter added to playlist",
        "track_count": len(playlist.playlist_tracks) + len(playlist.playlist_chapters)
    }


@router.post("/playlists/{playlist_id}/chapters/bulk", status_code=status.HTTP_201_CREATED)
@rate_limit("30/minute")
async def add_chapters_bulk(
    request: Request,
    playlist_id: str,
    chapter_data: BulkChapterAdd,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Add multiple audiobook chapters to a playlist in a single request"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters)
    ).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    for cid in chapter_data.chapter_ids:
        validate_uuid(cid, "Chapter ID")

    existing_chapter_ids = {
        str(pc.chapter_id) for pc in playlist.playlist_chapters
    }

    current_count = len(playlist.playlist_tracks) + len(playlist.playlist_chapters)

    added_count = 0
    skipped_count = 0
    for cid in chapter_data.chapter_ids:
        if cid in existing_chapter_ids:
            skipped_count += 1
            continue

        chapter = db.query(Chapter).filter(Chapter.id == cid).first()
        if not chapter:
            skipped_count += 1
            continue

        playlist_chapter = PlaylistChapter(
            playlist_id=playlist_id,
            chapter_id=cid,
            position=current_count + added_count
        )
        db.add(playlist_chapter)
        existing_chapter_ids.add(cid)
        added_count += 1

    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Bulk added {added_count} chapters to playlist {playlist.name} (skipped {skipped_count})")

    return {
        "message": f"Added {added_count} chapters to playlist",
        "added_count": added_count,
        "skipped_count": skipped_count,
        "track_count": current_count + added_count
    }


@router.delete("/playlists/{playlist_id}/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("60/minute")
async def remove_chapter_from_playlist(
    request: Request,
    playlist_id: str,
    chapter_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Remove a chapter from a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")
    validate_uuid(chapter_id, "Chapter ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    playlist_chapter = db.query(PlaylistChapter).filter(
        PlaylistChapter.playlist_id == playlist_id,
        PlaylistChapter.chapter_id == chapter_id
    ).first()
    if not playlist_chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not in playlist")

    removed_position = playlist_chapter.position
    db.delete(playlist_chapter)

    # Reposition remaining chapters after the removed one
    remaining = db.query(PlaylistChapter).filter(
        PlaylistChapter.playlist_id == playlist_id,
        PlaylistChapter.position > removed_position
    ).all()
    for c in remaining:
        c.position -= 1

    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()


@router.delete("/playlists/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("60/minute")
async def remove_track_from_playlist(
    request: Request,
    playlist_id: str,
    track_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Remove a track from a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")
    validate_uuid(track_id, "Track ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    playlist_track = db.query(PlaylistTrack).filter(
        PlaylistTrack.playlist_id == playlist_id,
        PlaylistTrack.track_id == track_id
    ).first()
    if not playlist_track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not in playlist")

    removed_position = playlist_track.position
    db.delete(playlist_track)

    remaining_tracks = db.query(PlaylistTrack).filter(
        PlaylistTrack.playlist_id == playlist_id,
        PlaylistTrack.position > removed_position
    ).all()
    for t in remaining_tracks:
        t.position -= 1

    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()


@router.put("/playlists/{playlist_id}/reorder")
@rate_limit("60/minute")
async def reorder_playlist_tracks(
    request: Request,
    playlist_id: str,
    reorder_data: PlaylistReorder,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Reorder tracks in a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    for item in reorder_data.track_positions:
        validate_uuid(item["track_id"], "Track ID")

        pt = db.query(PlaylistTrack).filter(
            PlaylistTrack.playlist_id == playlist_id,
            PlaylistTrack.track_id == item["track_id"]
        ).first()
        if not pt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Track {item['track_id']} not in playlist"
            )
        pt.position = item["position"]

    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Playlist tracks reordered successfully"}


@router.post("/playlists/{playlist_id}/publish")
@rate_limit("30/minute")
async def publish_playlist(
    request: Request,
    playlist_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """Publish a playlist to the Sound Booth (DJ+ only, owner or director)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters),
        joinedload(Playlist.owner)
    ).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    playlist.is_published = True
    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(playlist)

    logger.info(f"Published playlist: {playlist.name} (ID: {playlist.id})")
    return _playlist_response(playlist)


@router.post("/playlists/{playlist_id}/unpublish")
@rate_limit("30/minute")
async def unpublish_playlist(
    request: Request,
    playlist_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """Unpublish a playlist from the Sound Booth (DJ+ only, owner or director)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).options(
        selectinload(Playlist.playlist_tracks),
        selectinload(Playlist.playlist_chapters),
        joinedload(Playlist.owner)
    ).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    playlist.is_published = False
    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(playlist)

    logger.info(f"Unpublished playlist: {playlist.name} (ID: {playlist.id})")
    return _playlist_response(playlist)


@router.post("/playlists/{playlist_id}/cover-art")
@rate_limit("10/minute")
async def upload_cover_art(
    request: Request,
    playlist_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """Upload cover art for a playlist (owner or director only)"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    _check_playlist_ownership(playlist, current_user)

    # Validate file type
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, and WebP images are accepted")

    # Read file (max 5MB)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 5MB")

    # Save to disk
    COVER_ART_DIR.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if file.content_type == "image/jpeg" else "png" if file.content_type == "image/png" else "webp"
    filename = f"{playlist_id}.{ext}"
    filepath = COVER_ART_DIR / filename

    # Remove any existing cover art with different extension
    for old in COVER_ART_DIR.glob(f"{playlist_id}.*"):
        old.unlink()

    filepath.write_bytes(content)

    playlist.cover_art_url = str(filepath)
    playlist.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Uploaded cover art for playlist {playlist.name}: {filepath}")

    return {"message": "Cover art uploaded", "cover_art_url": f"/api/v1/playlists/{playlist_id}/cover-art"}


@router.get("/playlists/{playlist_id}/cover-art")
async def get_cover_art(
    playlist_id: str,
    db: Session = Depends(get_db)
):
    """Serve playlist cover art image"""
    validate_uuid(playlist_id, "Playlist ID")

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist or not playlist.cover_art_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cover art found")

    filepath = Path(playlist.cover_art_url)
    if not filepath.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cover art file not found")

    media_type = "image/jpeg" if filepath.suffix == ".jpg" else "image/png" if filepath.suffix == ".png" else "image/webp"
    return FileResponse(filepath, media_type=media_type)
