"""
Series API Router
Series management endpoints for audiobook library
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_dj_or_above, require_any_user
from app.models.user import User
from app.models.author import Author
from app.models.book import Book, BookStatus
from app.models.chapter import Chapter
from app.models.series import Series
from app.security import rate_limit, validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request bodies
class CreateSeriesRequest(BaseModel):
    """Request model for creating a series"""
    author_id: str
    name: str
    description: Optional[str] = None
    musicbrainz_series_id: Optional[str] = None
    monitored: bool = False


class UpdateSeriesRequest(BaseModel):
    """Request model for updating a series"""
    name: Optional[str] = None
    description: Optional[str] = None
    monitored: Optional[bool] = None
    cover_art_url: Optional[str] = None


class BulkDeleteSeriesRequest(BaseModel):
    """Request model for bulk deleting series"""
    series_ids: List[str]


class AddBookToSeriesRequest(BaseModel):
    """Request model for adding a book to a series"""
    book_id: str
    position: Optional[int] = None


class ReorderRequest(BaseModel):
    """Request model for reordering books in a series"""
    book_ids: List[str]


@router.get("/series")
@rate_limit("100/minute")
async def list_series(
    request: Request,
    author_id: Optional[str] = Query(None, description="Filter by author ID"),
    monitored_only: bool = Query(False, description="Only return monitored series"),
    search_query: Optional[str] = Query(None, description="Search series name"),
    sort_by: Optional[str] = Query(None, description="Sort by: name, added_at"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List all series with filtering and pagination

    Args:
        author_id: Filter by author ID
        monitored_only: Only return monitored series
        search_query: Search series name (case-insensitive partial match)
        sort_by: Sort order - name (default), added_at
        limit: Results per page (1-1000)
        offset: Pagination offset

    Returns:
        List of series with book counts and author info
    """
    # Subquery for book count per series
    book_counts_sq = (
        db.query(
            Book.series_id,
            func.count(Book.id).label('total_books')
        )
        .filter(Book.series_id.isnot(None))
        .group_by(Book.series_id)
        .subquery()
    )

    query = (
        db.query(Series, book_counts_sq.c.total_books)
        .outerjoin(book_counts_sq, Series.id == book_counts_sq.c.series_id)
        .options(joinedload(Series.author))
    )

    # Filter by author
    if author_id:
        validate_uuid(author_id, "Author ID")
        query = query.filter(Series.author_id == author_id)

    # Filter by monitored status
    if monitored_only:
        query = query.filter(Series.monitored == True)

    # Search by series name
    if search_query:
        query = query.filter(Series.name.ilike(f"%{search_query}%"))

    total_count = query.with_entities(Series.id).count()

    # Apply sort order
    if sort_by == 'added_at':
        query = query.order_by(Series.added_at.desc().nullslast(), Series.name)
    else:
        query = query.order_by(Series.name)

    results = query.limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "series": [
            {
                "id": str(series.id),
                "name": series.name,
                "author_id": str(series.author_id),
                "author_name": series.author.name if series.author else "Unknown",
                "musicbrainz_series_id": series.musicbrainz_series_id,
                "description": series.description,
                "monitored": series.monitored,
                "book_count": int(book_count or 0),
                "cover_art_url": series.cover_art_url,
                "added_at": series.added_at.isoformat() if series.added_at else None,
            }
            for series, book_count in results
        ]
    }


@router.get("/series/{series_id}")
@rate_limit("100/minute")
async def get_series(
    request: Request,
    series_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get series details with books in order

    Args:
        series_id: Series UUID

    Returns:
        Series object with books sorted by series_position and chapter stats
    """
    validate_uuid(series_id, "Series ID")

    series = db.query(Series).filter(Series.id == series_id).first()

    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Series not found"
        )

    # Get books in series order
    books = (
        db.query(Book)
        .filter(Book.series_id == series_id)
        .order_by(Book.series_position.asc().nullslast(), Book.title)
        .all()
    )

    # Get chapter stats per book
    book_ids = [b.id for b in books]
    chapter_stats = {}
    if book_ids:
        chapter_query = (
            db.query(
                Chapter.book_id,
                func.count(Chapter.id).label('total_chapters'),
                func.sum(case((Chapter.has_file == True, 1), else_=0)).label('linked_files')
            )
            .filter(Chapter.book_id.in_(book_ids))
            .group_by(Chapter.book_id)
            .all()
        )
        for book_id, total, linked in chapter_query:
            chapter_stats[book_id] = {
                'total_chapters': int(total or 0),
                'linked_files': int(linked or 0)
            }

    return {
        "id": str(series.id),
        "name": series.name,
        "author_id": str(series.author_id),
        "author_name": series.author.name if series.author else "Unknown",
        "musicbrainz_series_id": series.musicbrainz_series_id,
        "description": series.description,
        "monitored": series.monitored,
        "cover_art_url": series.cover_art_url,
        "total_expected_books": series.total_expected_books,
        "added_at": series.added_at.isoformat() if series.added_at else None,
        "updated_at": series.updated_at.isoformat() if series.updated_at else None,
        "books": [
            {
                "id": str(book.id),
                "title": book.title,
                "musicbrainz_id": book.musicbrainz_id,
                "release_mbid": book.release_mbid,
                "release_date": book.release_date.isoformat() if book.release_date else None,
                "album_type": book.album_type,
                "status": book.status.value,
                "monitored": book.monitored,
                "series_position": book.series_position,
                "chapter_count": chapter_stats.get(book.id, {}).get('total_chapters', book.chapter_count or 0),
                "linked_files_count": chapter_stats.get(book.id, {}).get('linked_files', 0),
                "cover_art_url": book.cover_art_url
            }
            for book in books
        ]
    }


@router.post("/series")
@rate_limit("50/minute")
async def create_series(
    request: Request,
    series_data: CreateSeriesRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Create a new series

    Args:
        series_data: Series information (author_id, name, description, etc.)

    Returns:
        Created series object
    """
    validate_uuid(series_data.author_id, "Author ID")

    # Validate author exists
    author = db.query(Author).filter(Author.id == series_data.author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    # Check if series already exists for this author with same name
    existing = db.query(Series).filter(
        Series.author_id == series_data.author_id,
        Series.name.ilike(series_data.name)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Series '{series_data.name}' already exists for this author"
        )

    try:
        # Create series
        series = Series(
            author_id=series_data.author_id,
            name=series_data.name,
            description=series_data.description,
            musicbrainz_series_id=series_data.musicbrainz_series_id,
            monitored=series_data.monitored,
            added_at=datetime.now(timezone.utc)
        )

        db.add(series)
        db.commit()
        db.refresh(series)

        logger.info(f"Created series: {series.name} for author {author.name} (ID: {series.id})")

        return {
            "id": str(series.id),
            "name": series.name,
            "author_id": str(series.author_id),
            "author_name": author.name,
            "musicbrainz_series_id": series.musicbrainz_series_id,
            "description": series.description,
            "monitored": series.monitored,
            "added_at": series.added_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create series: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create series: {str(e)}"
        )


@router.patch("/series/{series_id}")
@rate_limit("50/minute")
async def update_series(
    request: Request,
    series_id: str,
    updates: UpdateSeriesRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Update series settings

    When monitored status changes, cascades to all books in the series.

    Args:
        series_id: Series UUID
        updates: Series update fields (name, description, monitored, cover_art_url)

    Returns:
        Updated series object
    """
    validate_uuid(series_id, "Series ID")

    series = db.query(Series).filter(Series.id == series_id).first()

    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Series not found"
        )

    try:
        monitored_changed = False

        if updates.name is not None:
            series.name = updates.name

        if updates.description is not None:
            series.description = updates.description

        if updates.monitored is not None:
            if updates.monitored != series.monitored:
                monitored_changed = True
                series.monitored = updates.monitored

        if updates.cover_art_url is not None:
            series.cover_art_url = updates.cover_art_url

        series.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(series)

        # Cascade monitored status to all books in the series
        if monitored_changed:
            updated_count = db.query(Book).filter(Book.series_id == series_id).update(
                {"monitored": series.monitored},
                synchronize_session="fetch"
            )
            db.commit()
            logger.info(
                f"Updated series {series.name}: monitored={series.monitored}, "
                f"cascaded to {updated_count} books"
            )

        logger.info(f"Updated series: {series.name} (ID: {series_id})")

        return {
            "id": str(series.id),
            "name": series.name,
            "description": series.description,
            "monitored": series.monitored,
            "cover_art_url": series.cover_art_url,
            "updated_at": series.updated_at.isoformat()
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update series: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update series: {str(e)}"
        )


@router.delete("/series/bulk-delete")
@rate_limit("20/minute")
async def bulk_delete_series(
    request: Request,
    bulk_request: BulkDeleteSeriesRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Bulk delete multiple series

    Books remain in the library but their series_id is set to NULL
    (handled by DB ON DELETE SET NULL constraint).

    Args:
        bulk_request: List of series UUIDs to delete

    Returns:
        Success status with deleted count
    """
    if not bulk_request.series_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="series_ids list cannot be empty"
        )

    # Validate all UUIDs
    for sid in bulk_request.series_ids:
        validate_uuid(sid, "Series ID")

    try:
        # Find all matching series
        series_list = db.query(Series).filter(Series.id.in_(bulk_request.series_ids)).all()

        if not series_list:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No matching series found"
            )

        deleted_count = 0
        deleted_names = []
        for series in series_list:
            deleted_names.append(series.name)
            db.delete(series)
            deleted_count += 1

        db.commit()

        logger.info(f"Bulk deleted {deleted_count} series: {', '.join(deleted_names)}")

        return {
            "success": True,
            "deleted_count": deleted_count
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to bulk delete series: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete series: {str(e)}"
        )


@router.delete("/series/{series_id}")
@rate_limit("50/minute")
async def delete_series(
    request: Request,
    series_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Delete series from library

    Books remain in the library but their series_id is set to NULL
    (handled by DB ON DELETE SET NULL constraint).

    Args:
        series_id: Series UUID

    Returns:
        Success message with book count
    """
    validate_uuid(series_id, "Series ID")

    series = db.query(Series).filter(Series.id == series_id).first()

    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Series not found"
        )

    try:
        series_name = series.name

        # Count books in this series
        book_count = db.query(Book).filter(Book.series_id == series_id).count()

        # Delete series (books will have series_id set to NULL via ON DELETE SET NULL)
        db.delete(series)
        db.commit()

        logger.info(f"Deleted series: {series_name} (ID: {series_id}, {book_count} books retained)")

        return {
            "success": True,
            "message": f"Series '{series_name}' deleted",
            "book_count": book_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete series: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete series: {str(e)}"
        )


@router.post("/series/{series_id}/add-book")
@rate_limit("50/minute")
async def add_book_to_series(
    request: Request,
    series_id: str,
    book_request: AddBookToSeriesRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Add a book to this series

    Args:
        series_id: Series UUID
        book_request: Book ID and optional position

    Returns:
        Updated book with series info
    """
    validate_uuid(series_id, "Series ID")
    validate_uuid(book_request.book_id, "Book ID")

    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Series not found"
        )

    book = db.query(Book).filter(Book.id == book_request.book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found"
        )

    # Validate book belongs to same author
    if book.author_id != series.author_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book must belong to the same author as the series"
        )

    try:
        # Auto-increment position if not specified
        position = book_request.position
        if position is None:
            max_position = db.query(func.max(Book.series_position)).filter(
                Book.series_id == series_id
            ).scalar()
            position = (max_position or 0) + 1

        book.series_id = series_id
        book.series_position = position

        db.commit()
        db.refresh(book)

        logger.info(f"Added book '{book.title}' to series '{series.name}' at position {position}")

        return {
            "id": str(book.id),
            "title": book.title,
            "series_id": str(series_id),
            "series_name": series.name,
            "series_position": book.series_position,
            "message": f"Book added to series at position {position}"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add book to series: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add book to series: {str(e)}"
        )


@router.post("/series/{series_id}/reorder")
@rate_limit("50/minute")
async def reorder_series_books(
    request: Request,
    series_id: str,
    reorder_request: ReorderRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Reorder books within the series

    Args:
        series_id: Series UUID
        reorder_request: List of book IDs in desired order

    Returns:
        Count of reordered books
    """
    validate_uuid(series_id, "Series ID")

    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Series not found"
        )

    if not reorder_request.book_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="book_ids list cannot be empty"
        )

    # Validate all book IDs
    for book_id in reorder_request.book_ids:
        validate_uuid(book_id, "Book ID")

    try:
        # Verify all books belong to this series
        books = db.query(Book).filter(
            Book.id.in_(reorder_request.book_ids),
            Book.series_id == series_id
        ).all()

        if len(books) != len(reorder_request.book_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Some books do not belong to this series"
            )

        # Update positions (1-based)
        book_map = {str(b.id): b for b in books}
        updated_count = 0

        for position, book_id in enumerate(reorder_request.book_ids, start=1):
            book = book_map.get(book_id)
            if book:
                book.series_position = position
                updated_count += 1

        db.commit()

        logger.info(f"Reordered {updated_count} books in series '{series.name}'")

        return {
            "success": True,
            "series_id": str(series_id),
            "series_name": series.name,
            "updated_count": updated_count,
            "message": f"Reordered {updated_count} books"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to reorder books: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reorder books: {str(e)}"
        )


@router.post("/series/{series_id}/remove-book")
@rate_limit("50/minute")
async def remove_book_from_series(
    request: Request,
    series_id: str,
    book_request: AddBookToSeriesRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Remove a book from this series (unlinks it, does not delete the book).

    Args:
        series_id: Series UUID
        book_request: Book ID to remove

    Returns:
        Confirmation message
    """
    validate_uuid(series_id, "Series ID")
    validate_uuid(book_request.book_id, "Book ID")

    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Series not found"
        )

    book = db.query(Book).filter(
        Book.id == book_request.book_id,
        Book.series_id == series_id,
    ).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found in this series"
        )

    try:
        book.series_id = None
        book.series_position = None
        db.commit()

        logger.info(f"Removed book '{book.title}' from series '{series.name}'")

        return {
            "success": True,
            "book_id": str(book.id),
            "book_title": book.title,
            "message": f"Book removed from series '{series.name}'"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to remove book from series: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove book from series: {str(e)}"
        )


@router.post("/series/{series_id}/cover-art")
@rate_limit("10/minute")
async def upload_series_cover_art(
    request: Request,
    series_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Upload cover art for a series"""
    from app.services.cover_art_service import save_entity_cover_art

    validate_uuid(series_id, "Series ID")
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    filepath = await save_entity_cover_art("series", series_id, file)
    series.cover_art_url = filepath
    series.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Cover art uploaded", "cover_art_url": series.cover_art_url}


@router.post("/series/{series_id}/cover-art-from-url")
@rate_limit("10/minute")
async def upload_series_cover_art_from_url(
    request: Request,
    series_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Fetch cover art for a series from a remote URL"""
    from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url

    validate_uuid(series_id, "Series ID")
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    filepath = await fetch_and_save_entity_cover_art_from_url("series", series_id, url)
    series.cover_art_url = filepath
    series.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Cover art saved", "cover_art_url": series.cover_art_url}


@router.get("/series/{series_id}/cover-art")
async def get_series_cover_art(series_id: str, db: Session = Depends(get_db)):
    """Serve series cover art image"""
    from app.services.cover_art_service import serve_entity_cover_art

    validate_uuid(series_id, "Series ID")
    series = db.query(Series).filter(Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    return serve_entity_cover_art("series", series_id, series.cover_art_url)
