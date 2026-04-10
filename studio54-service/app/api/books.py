"""
Books API Router
Book management and search endpoints for audiobook library
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Body, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, or_
from app.utils.search import fuzzy_search_filter
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_dj_or_above, require_any_user
from app.models.user import User
from app.models.book import Book, BookStatus
from app.models.author import Author
from app.models.chapter import Chapter
from app.models.series import Series
from app.models.download_queue import DownloadQueue, DownloadStatus
from app.security import rate_limit, validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request bodies
class BookUpdateRequest(BaseModel):
    monitored: Optional[bool] = None
    status: Optional[BookStatus] = None
    custom_folder_path: Optional[str] = None
    series_id: Optional[str] = None
    series_position: Optional[float] = None
    related_series: Optional[str] = None


class BookMetadataEditRequest(BaseModel):
    title: Optional[str] = None
    author_name: Optional[str] = None  # Written to file tags (and credit_name); reassignment via author_id
    author_id: Optional[str] = None    # Reassigns the book to a different author record


class BulkBookUpdateRequest(BaseModel):
    book_ids: List[str]
    monitored: bool


class MonitorByAuthorRequest(BaseModel):
    author_id: str
    monitored: bool


@router.get("/books")
@rate_limit("100/minute")
async def list_books(
    request: Request,
    search_query: Optional[str] = Query(None, description="Search book title or author name (fuzzy)"),
    status_filter: Optional[BookStatus] = Query(None, description="Filter by book status"),
    author_id: Optional[str] = Query(None, description="Filter by author ID"),
    series_id: Optional[str] = Query(None, description="Filter by series ID"),
    monitored_only: bool = Query(False, description="Only return monitored books"),
    in_library: Optional[bool] = Query(None, description="Filter by library status (true=downloaded, false=wanted/searching/etc)"),
    sort_by: Optional[str] = Query(None, description="Sort by: title, release_date, added_at"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List books with filtering

    Args:
        search_query: Search book title or author name (fuzzy)
        status_filter: Filter by book status (wanted, downloading, downloaded, etc.)
        author_id: Filter by author ID
        series_id: Filter by series ID
        monitored_only: Only return monitored books
        in_library: Filter by library status (true=DOWNLOADED, false=WANTED/etc)
        sort_by: Sort by title, release_date, or added_at
        limit: Results per page (1-1000)
        offset: Pagination offset

    Returns:
        List of books with author and series info
    """
    # Subquery for chapter stats per book (total chapters + linked files)
    chapter_stats_sq = (
        db.query(
            Chapter.book_id,
            func.count(Chapter.id).label("total_chapters"),
            func.sum(case((Chapter.has_file == True, 1), else_=0)).label("linked_count")
        )
        .group_by(Chapter.book_id)
        .subquery()
    )

    query = (
        db.query(Book, chapter_stats_sq.c.linked_count, chapter_stats_sq.c.total_chapters)
        .outerjoin(chapter_stats_sq, Book.id == chapter_stats_sq.c.book_id)
        .options(
            joinedload(Book.author),
            joinedload(Book.series)
        )
    )

    # Fuzzy search on book title and author name
    _best_similarity = None
    if search_query:
        query = query.join(Author, Book.author_id == Author.id)
        title_filter, title_sim = fuzzy_search_filter(Book.title, search_query)
        author_filter, author_sim = fuzzy_search_filter(Author.name, search_query)

        query = query.filter(or_(title_filter, author_filter))
        _best_similarity = func.greatest(title_sim, author_sim)

    if status_filter:
        query = query.filter(Book.status == status_filter)

    if author_id:
        validate_uuid(author_id, "Author ID")
        query = query.filter(Book.author_id == author_id)

    if series_id:
        validate_uuid(series_id, "Series ID")
        query = query.filter(Book.series_id == series_id)

    if monitored_only:
        query = query.filter(Book.monitored == True)

    # in_library filter: true=DOWNLOADED, false=not DOWNLOADED
    if in_library is not None:
        if in_library:
            query = query.filter(Book.status == BookStatus.DOWNLOADED)
        else:
            query = query.filter(Book.status != BookStatus.DOWNLOADED)

    total_count = query.with_entities(Book.id).count()

    # Apply sort order
    if sort_by == 'title':
        query = query.order_by(Book.title)
    elif sort_by == 'added_at':
        query = query.order_by(Book.added_at.desc().nullslast(), Book.title)
    elif sort_by == 'author':
        if not search_query:  # search already joins Author
            query = query.join(Author, Book.author_id == Author.id)
        query = query.order_by(Author.name, Book.title)
    elif _best_similarity is not None and sort_by is None:
        # When searching without explicit sort, order by relevance
        query = query.order_by(_best_similarity.desc(), Book.title)
    else:
        query = query.order_by(Book.release_date.desc().nullslast(), Book.title)

    results = query.limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "books": [
            {
                "id": str(book.id),
                "title": book.title,
                "author_id": str(book.author_id),
                "author_name": book.author.name if book.author else "Unknown",
                "series_id": str(book.series_id) if book.series_id else None,
                "series_name": book.series.name if book.series else None,
                "series_position": book.series_position,
                "release_date": book.release_date.isoformat() if book.release_date else None,
                "status": book.status.value,
                "monitored": book.monitored,
                "chapter_count": book.chapter_count,
                "cover_art_url": book.cover_art_url,
                "credit_name": book.credit_name,
                "custom_folder_path": book.custom_folder_path,
                "linked_files_count": int(linked_count or 0),
                "related_series": book.related_series
            }
            for book, linked_count, total_chapters in results
        ]
    }


@router.get("/books/wanted")
@rate_limit("100/minute")
async def get_wanted_books(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get wanted books (monitored books not yet downloaded)

    Args:
        limit: Results per page
        offset: Pagination offset

    Returns:
        List of wanted books
    """
    query = db.query(Book).options(joinedload(Book.author)).filter(
        Book.monitored == True,
        Book.status == BookStatus.WANTED
    )

    total_count = query.with_entities(Book.id).count()
    books = query.order_by(Book.release_date.desc().nullslast()).limit(limit).offset(offset).all()

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "wanted_books": [
            {
                "id": str(book.id),
                "title": book.title,
                "author_name": book.author.name if book.author else "Unknown",
                "release_date": book.release_date.isoformat() if book.release_date else None,
                "chapter_count": book.chapter_count
            }
            for book in books
        ]
    }


@router.patch("/books/bulk-update")
@rate_limit("20/minute")
async def bulk_update_books(
    request: Request,
    bulk_request: BulkBookUpdateRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Bulk update monitoring status for multiple books

    Args:
        bulk_request: Book IDs and monitored flag

    Returns:
        Count of updated books
    """
    if not bulk_request.book_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="book_ids list cannot be empty"
        )

    for bid in bulk_request.book_ids:
        validate_uuid(bid, "Book ID")

    updated = db.query(Book).filter(
        Book.id.in_(bulk_request.book_ids)
    ).update(
        {"monitored": bulk_request.monitored, "updated_at": datetime.now(timezone.utc)},
        synchronize_session="fetch"
    )

    db.commit()

    logger.info(f"Bulk updated {updated} books: monitored={bulk_request.monitored}")

    return {
        "success": True,
        "updated_count": updated,
        "monitored": bulk_request.monitored
    }


@router.post("/books/monitor-by-author")
@rate_limit("20/minute")
async def monitor_by_author(
    request: Request,
    monitor_request: MonitorByAuthorRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Monitor or unmonitor all books for a specific author

    Args:
        monitor_request: Author ID and monitored flag

    Returns:
        Count of updated books
    """
    validate_uuid(monitor_request.author_id, "Author ID")

    author = db.query(Author).filter(Author.id == monitor_request.author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    query = db.query(Book).filter(Book.author_id == monitor_request.author_id)

    updated = query.update(
        {"monitored": monitor_request.monitored, "updated_at": datetime.now(timezone.utc)},
        synchronize_session="fetch"
    )

    db.commit()

    logger.info(
        f"Updated {updated} books for {author.name}: "
        f"monitored={monitor_request.monitored}"
    )

    return {
        "success": True,
        "author_id": monitor_request.author_id,
        "author_name": author.name,
        "updated_count": updated,
        "monitored": monitor_request.monitored
    }


@router.get("/books/{book_id}")
@rate_limit("100/minute")
async def get_book(
    request: Request,
    book_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get book details

    Args:
        book_id: Book UUID

    Returns:
        Book object with chapters and download history
    """
    validate_uuid(book_id, "Book ID")

    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found"
        )

    # Get chapters
    chapters = db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.disc_number, Chapter.chapter_number).all()

    # Get download history
    downloads = db.query(DownloadQueue).filter(DownloadQueue.book_id == book_id).all()

    return {
        "id": str(book.id),
        "title": book.title,
        "author_id": str(book.author_id),
        "author_name": book.author.name if book.author else "Unknown",
        "series_id": str(book.series_id) if book.series_id else None,
        "series_name": book.series.name if book.series else None,
        "series_position": book.series_position,
        "related_series": book.related_series,
        "release_date": book.release_date.isoformat() if book.release_date else None,
        "status": book.status.value,
        "monitored": book.monitored,
        "cover_art_url": book.cover_art_url,
        "credit_name": book.credit_name,
        "custom_folder_path": book.custom_folder_path,
        "chapter_count": len(chapters),
        "added_at": book.added_at.isoformat() if book.added_at else None,
        "updated_at": book.updated_at.isoformat() if book.updated_at else None,
        "chapters": [
            {
                "id": str(chapter.id),
                "title": chapter.title,
                "chapter_number": chapter.chapter_number,
                "disc_number": chapter.disc_number,
                "duration_ms": chapter.duration_ms,
                "has_file": chapter.has_file,
                "file_path": chapter.file_path
            }
            for chapter in chapters
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


COVER_ART_NAMES = ["cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png"]


def _find_cover_art(book: Book, db: Session) -> Optional[Path]:
    """Find cover art file in the book's directory from chapter file paths.

    Checks the chapter's parent directory first, then one level up
    (handles books with chapter-level subdirectories like disc folders).
    """
    chapter = db.query(Chapter).filter(
        Chapter.book_id == book.id,
        Chapter.file_path.isnot(None),
    ).first()

    if not chapter:
        return None

    chapter_dir = Path(chapter.file_path).parent

    # Search the chapter dir and one level up (for nested chapter dirs)
    dirs_to_check = [chapter_dir]
    if chapter_dir.parent != chapter_dir:
        dirs_to_check.append(chapter_dir.parent)

    for d in dirs_to_check:
        for name in COVER_ART_NAMES:
            cover_path = d / name
            if cover_path.is_file():
                return cover_path
    return None


@router.get("/books/{book_id}/cover-art")
async def get_book_cover_art(
    book_id: str,
    db: Session = Depends(get_db),
):
    """Serve cover art for a book.

    Priority:
      1. Uploaded/fetched art stored via cover_art_url (local file or redirect)
      2. cover.jpg / folder.jpg found in the chapter file directory
    """
    from app.services.cover_art_service import serve_entity_cover_art

    validate_uuid(book_id, "Book ID")

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Priority 1: uploaded / URL-fetched art
    if book.cover_art_url:
        return serve_entity_cover_art("book", book_id, book.cover_art_url)

    # Priority 2: cover.jpg embedded in the audiobook file directory
    cover_path = _find_cover_art(book, db)
    if cover_path:
        suffix = cover_path.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")
        return FileResponse(str(cover_path), media_type=media_type)

    raise HTTPException(status_code=404, detail="No cover art found")


@router.patch("/books/{book_id}")
@rate_limit("50/minute")
async def update_book(
    request: Request,
    book_id: str,
    updates: BookUpdateRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Update book settings

    Args:
        book_id: Book UUID
        updates: Book update fields (monitored, status, custom_folder_path, series_id, series_position, related_series)

    Returns:
        Updated book object
    """
    validate_uuid(book_id, "Book ID")

    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found"
        )

    try:
        if updates.monitored is not None:
            book.monitored = updates.monitored

        if updates.status is not None:
            book.status = updates.status

        if updates.custom_folder_path is not None:
            book.custom_folder_path = updates.custom_folder_path

        if updates.series_id is not None:
            validate_uuid(updates.series_id, "Series ID")
            book.series_id = updates.series_id

        if updates.series_position is not None:
            book.series_position = updates.series_position

        if updates.related_series is not None:
            book.related_series = updates.related_series

        book.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(book)

        # Create folder if book is now monitored
        if updates.monitored is True:
            try:
                from app.services.folder_creator import get_folder_creator
                author = db.query(Author).filter(Author.id == book.author_id).first()
                if author:
                    folder_creator = get_folder_creator(db)
                    success, folder_path, error = folder_creator.create_book_folder(book, author)
                    if success:
                        logger.info(f"Created folder for monitored book {book.title}: {folder_path}")
                    elif error:
                        logger.warning(f"Failed to create folder for book {book.title}: {error}")
            except Exception as e:
                logger.error(f"Error creating folder for book {book.title}: {e}", exc_info=True)

        logger.info(f"Updated book: {book.title} (ID: {book_id})")

        return {
            "id": str(book.id),
            "title": book.title,
            "monitored": book.monitored,
            "status": book.status.value,
            "custom_folder_path": book.custom_folder_path,
            "series_id": str(book.series_id) if book.series_id else None,
            "series_position": book.series_position,
            "related_series": book.related_series,
            "updated_at": book.updated_at.isoformat()
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update book: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update book: {str(e)}"
        )


@router.post("/books/{book_id}/search")
@rate_limit("20/minute")
async def search_book(
    request: Request,
    book_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Trigger manual book search

    Searches indexers for the book using "Author Name - Book Title" format.

    Args:
        book_id: Book UUID

    Returns:
        Search task info
    """
    validate_uuid(book_id, "Book ID")

    book = db.query(Book).filter(Book.id == book_id).first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found"
        )

    try:
        # Trigger search
        from app.tasks.download_tasks import search_book as search_book_task
        from app.models.job_state import JobType

        # Create folder before searching
        try:
            from app.services.folder_creator import get_folder_creator
            author = db.query(Author).filter(Author.id == book.author_id).first()
            if author:
                folder_creator = get_folder_creator(db)
                success, folder_path, error = folder_creator.create_book_folder(book, author)
                if success:
                    logger.info(f"Created folder for book search {book.title}: {folder_path}")
                elif error:
                    logger.warning(f"Failed to create folder for book {book.title}: {error}")
        except Exception as e:
            logger.error(f"Error creating folder for book {book.title}: {e}", exc_info=True)

        task = search_book_task.apply_async(
            args=[str(book.id)],
            kwargs={
                'job_type': JobType.BOOK_SEARCH,
                'entity_type': 'book',
                'entity_id': str(book.id)
            }
        )

        logger.info(f"Triggered manual search for book: {book.title} (ID: {book_id})")

        return {
            "success": True,
            "book_id": str(book.id),
            "book_title": book.title,
            "author_name": book.author.name if book.author else "Unknown",
            "message": "Book search started",
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger book search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger book search: {str(e)}"
        )


@router.post("/chapters/{chapter_id}/record-play")
@rate_limit("200/minute")
async def record_chapter_play(
    request: Request,
    chapter_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Record a play for a chapter. Increments play_count and sets last_played_at.
    Called by the frontend when a chapter finishes playing naturally.
    """
    validate_uuid(chapter_id, "Chapter ID")

    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )

    chapter.play_count = (chapter.play_count or 0) + 1
    chapter.last_played_at = datetime.now(timezone.utc)
    db.commit()

    return {"play_count": chapter.play_count}


@router.post("/books/{book_id}/cover-art")
@rate_limit("10/minute")
async def upload_book_cover_art(
    request: Request,
    book_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Upload cover art for a book"""
    from app.services.cover_art_service import save_entity_cover_art

    validate_uuid(book_id, "Book ID")
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    filepath = await save_entity_cover_art("book", book_id, file)
    book.cover_art_url = filepath
    book.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Cover art uploaded", "cover_art_url": book.cover_art_url}


@router.post("/books/{book_id}/cover-art-from-url")
@rate_limit("10/minute")
async def upload_book_cover_art_from_url(
    request: Request,
    book_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Fetch cover art for a book from a remote URL"""
    from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url

    validate_uuid(book_id, "Book ID")
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    filepath = await fetch_and_save_entity_cover_art_from_url("book", book_id, url)
    book.cover_art_url = filepath
    book.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Cover art saved", "cover_art_url": book.cover_art_url}


@router.post("/books/{book_id}/edit-metadata")
@rate_limit("20/minute")
async def edit_book_metadata(
    request: Request,
    book_id: str,
    body: BookMetadataEditRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """
    Update book title and/or author name in the database AND write the new
    values to the ID3/Vorbis/MP4 tags of every chapter audio file.

    author_name only updates file tags (and book.credit_name); it does not
    reassign the DB author record.  Use the author management UI for that.
    """
    validate_uuid(book_id)
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    new_title = (body.title or "").strip() or None
    new_author = (body.author_name or "").strip() or None
    new_author_id = (body.author_id or "").strip() or None

    if not new_title and not new_author and not new_author_id:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")

    # Validate and resolve new author record
    new_author_record = None
    if new_author_id:
        validate_uuid(new_author_id)
        import uuid as uuid_lib
        new_author_record = db.query(Author).filter(Author.id == uuid_lib.UUID(new_author_id)).first()
        if not new_author_record:
            raise HTTPException(status_code=404, detail="Target author not found")

    # Apply DB changes
    if new_title:
        book.title = new_title
    if new_author:
        book.credit_name = new_author
    if new_author_record:
        book.author_id = new_author_record.id
        # If no explicit author_name given, use the new author's name for file tags
        if not new_author:
            new_author = new_author_record.name
            book.credit_name = None  # clear override so it inherits author name
    book.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Dispatch Celery task to rewrite audio file tags (only if something tag-relevant changed)
    chapter_count = db.query(Chapter).filter(
        Chapter.book_id == book.id,
        Chapter.has_file == True,
        Chapter.file_path.isnot(None),
    ).count()

    task_id = None
    if new_title or new_author:
        from app.tasks.sync_tasks import rewrite_book_file_tags
        from app.models.job_state import JobType
        task = rewrite_book_file_tags.apply_async(
            args=[book_id],
            kwargs={
                "new_title": new_title,
                "new_author": new_author,
                "job_type": JobType.METADATA_REFRESH,
                "entity_type": "book",
                "entity_id": book_id,
            }
        )
        task_id = task.id

    return {
        "success": True,
        "book_id": book_id,
        "title": book.title,
        "author_id": str(book.author_id),
        "author_name": new_author_record.name if new_author_record else None,
        "credit_name": book.credit_name,
        "chapters_to_update": chapter_count if task_id else 0,
        "task_id": task_id,
    }


