"""
Book Playlists API - Series-ordered chapter playlists for audiobooks
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.security import rate_limit, validate_uuid
from app.models.book_playlist import BookPlaylist, BookPlaylistChapter
from app.models.series import Series
from app.models.chapter import Chapter
from app.models.book import Book

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/series/{series_id}/playlist")
@rate_limit("10/minute")
async def create_series_playlist(request: Request, series_id: str, db: Session = Depends(get_db)):
    """Create or refresh a series playlist (dispatches Celery task)."""
    validate_uuid(series_id)

    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    from app.tasks.playlist_tasks import create_series_playlist_task
    result = create_series_playlist_task.delay(series_id)

    return {
        "status": "dispatched",
        "task_id": result.id,
        "message": f"Playlist creation started for series '{series.name}'",
    }


@router.get("/series/{series_id}/playlist")
@rate_limit("60/minute")
async def get_series_playlist(request: Request, series_id: str, db: Session = Depends(get_db)):
    """Get the playlist for a series with all chapter entries."""
    validate_uuid(series_id)

    playlist = (
        db.query(BookPlaylist)
        .filter(BookPlaylist.series_id == series_id)
        .options(
            joinedload(BookPlaylist.series),
            joinedload(BookPlaylist.entries)
            .joinedload(BookPlaylistChapter.chapter)
            .joinedload(Chapter.book)
        )
        .first()
    )

    if not playlist:
        raise HTTPException(status_code=404, detail="No playlist found for this series")

    total_duration_ms = 0
    chapters = []
    for entry in playlist.entries:
        ch = entry.chapter
        book = ch.book if ch else None
        duration = ch.duration_ms or 0
        total_duration_ms += duration
        chapters.append({
            "id": str(entry.id),
            "chapter_id": str(ch.id),
            "chapter_title": ch.title,
            "chapter_number": ch.chapter_number,
            "duration_ms": ch.duration_ms,
            "has_file": ch.has_file,
            "file_path": ch.file_path,
            "position": entry.position,
            "book_position": entry.book_position,
            "book_id": str(book.id) if book else None,
            "book_title": book.title if book else None,
            "book_cover_art_url": book.cover_art_url if book else None,
        })

    return {
        "id": str(playlist.id),
        "series_id": str(playlist.series_id),
        "name": playlist.name,
        "description": playlist.description,
        "chapter_count": len(chapters),
        "total_duration_ms": total_duration_ms,
        "series_name": playlist.series.name if playlist.series else None,
        "created_at": playlist.created_at.isoformat() if playlist.created_at else None,
        "updated_at": playlist.updated_at.isoformat() if playlist.updated_at else None,
        "chapters": chapters,
    }


@router.get("/book-playlists")
@rate_limit("60/minute")
async def list_book_playlists(request: Request, db: Session = Depends(get_db)):
    """List all book playlists."""
    playlists = (
        db.query(BookPlaylist)
        .options(joinedload(BookPlaylist.series))
        .order_by(BookPlaylist.name)
        .all()
    )

    return [
        {
            "id": str(p.id),
            "series_id": str(p.series_id),
            "name": p.name,
            "description": p.description,
            "chapter_count": len(p.entries),
            "series_name": p.series.name if p.series else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in playlists
    ]


@router.delete("/series/{series_id}/playlist")
@rate_limit("10/minute")
async def delete_series_playlist(request: Request, series_id: str, db: Session = Depends(get_db)):
    """Delete a series playlist."""
    validate_uuid(series_id)

    playlist = db.query(BookPlaylist).filter(BookPlaylist.series_id == series_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="No playlist found for this series")

    db.delete(playlist)
    db.commit()

    return {"status": "deleted", "message": f"Playlist '{playlist.name}' deleted"}
