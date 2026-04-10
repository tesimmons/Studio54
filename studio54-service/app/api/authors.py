"""
Authors API Router
Author management and monitoring endpoints for audiobook library
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
from app.models.author import Author
from app.models.book import Book, BookStatus
from app.models.chapter import Chapter
from app.models.series import Series
from app.security import rate_limit, validate_mbid, validate_uuid
from app.utils.search import fuzzy_search_filter
from app.services.musicbrainz_client import get_musicbrainz_client

logger = logging.getLogger(__name__)


class UpdateAuthorRequest(BaseModel):
    is_monitored: Optional[bool] = None
    quality_profile_id: Optional[str] = None
    root_folder_path: Optional[str] = None
    overview: Optional[str] = None
    genre: Optional[str] = None
    country: Optional[str] = None

router = APIRouter()


class AddAuthorRequest(BaseModel):
    """Request model for adding an author"""
    musicbrainz_id: str
    is_monitored: bool = False
    root_folder_path: Optional[str] = None
    quality_profile_id: Optional[str] = None
    monitor_type: str = "none"
    search_for_missing: bool = False


class BulkAuthorUpdateRequest(BaseModel):
    """Request model for bulk updating authors"""
    author_ids: List[str]
    is_monitored: Optional[bool] = None
    quality_profile_id: Optional[str] = None


@router.post("/authors")
@rate_limit("50/minute")
async def add_author(
    request: Request,
    author_data: AddAuthorRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Add author to monitoring

    Args:
        author_data: Author information (musicbrainz_id, is_monitored, etc.)

    Returns:
        Created author object
    """
    validate_mbid(author_data.musicbrainz_id)

    musicbrainz_id = author_data.musicbrainz_id
    is_monitored = author_data.is_monitored
    root_folder_path = author_data.root_folder_path
    quality_profile_id = author_data.quality_profile_id
    monitor_type = author_data.monitor_type
    search_for_missing = author_data.search_for_missing

    # Check if author already exists
    existing = db.query(Author).filter(Author.musicbrainz_id == musicbrainz_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Author already exists with ID {existing.id}"
        )

    try:
        # Get author details from MusicBrainz
        mb_client = get_musicbrainz_client()
        author_data_mb = mb_client.get_artist(musicbrainz_id)

        if not author_data_mb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Author not found on MusicBrainz"
            )

        # Extract top genre from MusicBrainz genres list
        genre = None
        mb_genres = author_data_mb.get("genres") or []
        if mb_genres:
            top_genre = sorted(mb_genres, key=lambda g: g.get("count", 0), reverse=True)[0]
            genre = top_genre.get("name")

        # Create author
        author = Author(
            name=author_data_mb.get("name", "Unknown Author"),
            musicbrainz_id=musicbrainz_id,
            is_monitored=is_monitored,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            monitor_type=monitor_type,
            genre=genre,
            added_at=datetime.now(timezone.utc)
        )

        db.add(author)
        db.commit()
        db.refresh(author)

        logger.info(f"Added author: {author.name} (MBID: {musicbrainz_id})")

        # Send notification
        try:
            from app.services.notification_service import send_notification
            send_notification("author_added", {
                "message": f"Author added: {author.name}",
                "author_name": author.name,
                "musicbrainz_id": musicbrainz_id,
                "is_monitored": is_monitored,
            })
        except Exception as e:
            logger.debug(f"Notification send failed: {e}")

        # Create folder if author is monitored
        if is_monitored:
            try:
                from app.services.folder_creator import get_folder_creator
                folder_creator = get_folder_creator(db)
                success, folder_path, error = folder_creator.create_author_folder(author)
                if success:
                    logger.info(f"Created folder for monitored author {author.name}: {folder_path}")
                elif error:
                    logger.warning(f"Failed to create folder for author {author.name}: {error}")
            except Exception as e:
                logger.error(f"Error creating folder for author {author.name}: {e}", exc_info=True)

        # Trigger background task to fetch books
        from app.tasks.sync_tasks import sync_author_books_standalone
        try:
            task = sync_author_books_standalone.delay(str(author.id))
            logger.info(f"Triggered book sync task {task.id} for author {author.name}")
        except Exception as e:
            logger.warning(f"Failed to trigger book sync task: {e}")
            # Don't fail the request if background task fails to start

        # Chain search for missing books if requested
        search_task_id = None
        if search_for_missing and is_monitored:
            try:
                from app.tasks.search_tasks import search_wanted_books_for_author
                search_task = search_wanted_books_for_author.apply_async(
                    args=[str(author.id)],
                    countdown=30,  # Wait 30s for sync to complete
                )
                search_task_id = search_task.id
                logger.info(f"Queued search-for-missing task {search_task.id} for author {author.name}")
            except Exception as e:
                logger.warning(f"Failed to queue search-for-missing task: {e}")

        return {
            "id": str(author.id),
            "name": author.name,
            "musicbrainz_id": author.musicbrainz_id,
            "is_monitored": author.is_monitored,
            "monitor_type": author.monitor_type,
            "search_task_id": search_task_id,
            "added_at": author.added_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add author: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add author: {str(e)}"
        )


@router.get("/authors/genres")
@rate_limit("100/minute")
async def list_genres(
    request: Request,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get distinct genre values from all authors

    Returns:
        List of unique genre strings
    """
    genres = (
        db.query(Author.genre)
        .filter(Author.genre.isnot(None), Author.genre != '')
        .distinct()
        .order_by(Author.genre)
        .all()
    )
    return {"genres": [g[0] for g in genres]}


@router.get("/authors")
@rate_limit("100/minute")
async def list_authors(
    request: Request,
    search_query: Optional[str] = Query(None, description="Search author name"),
    monitored_only: bool = Query(False, description="Only return monitored authors"),
    unmonitored_only: bool = Query(False, description="Only return unmonitored authors"),
    genre: Optional[str] = Query(None, description="Filter by genre (case-insensitive partial match)"),
    sort_by: Optional[str] = Query(None, description="Sort by: name, added_at"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    List authors in library with search and filtering

    Args:
        search_query: Search author name (case-insensitive partial match)
        monitored_only: Only return monitored authors
        unmonitored_only: Only return unmonitored authors
        genre: Filter by genre
        sort_by: Sort order - name (default), added_at
        limit: Results per page (1-1000)
        offset: Pagination offset

    Returns:
        List of authors with pagination metadata including file linking stats
    """
    # Build file stats subquery (chapters with files)
    file_stats_sq = (
        db.query(
            Book.author_id,
            func.count(Chapter.id).label('total_chapters'),
            func.sum(case((Chapter.has_file == True, 1), else_=0)).label('linked_files')
        )
        .join(Chapter, Chapter.book_id == Book.id)
        .group_by(Book.author_id)
        .subquery()
    )

    # Build book count subquery (live from DB, not stored column)
    book_counts_sq = (
        db.query(
            Book.author_id,
            func.count(Book.id).label('total_books'),
            func.sum(case((Book.monitored == True, 1), else_=0)).label('monitored_books')
        )
        .group_by(Book.author_id)
        .subquery()
    )

    query = (
        db.query(
            Author,
            file_stats_sq.c.total_chapters,
            file_stats_sq.c.linked_files,
            book_counts_sq.c.total_books,
            book_counts_sq.c.monitored_books
        )
        .outerjoin(file_stats_sq, Author.id == file_stats_sq.c.author_id)
        .outerjoin(book_counts_sq, Author.id == book_counts_sq.c.author_id)
    )

    # Search by author name (fuzzy trigram + ILIKE fallback)
    _author_similarity = None
    if search_query:
        name_filter, _author_similarity = fuzzy_search_filter(Author.name, search_query)
        query = query.filter(name_filter)

    # Monitored status filters (mutually exclusive)
    if monitored_only:
        query = query.filter(Author.is_monitored == True)
    elif unmonitored_only:
        query = query.filter(Author.is_monitored == False)

    # Genre filter
    if genre:
        query = query.filter(Author.genre.ilike(f"%{genre}%"))

    total_count = query.with_entities(Author.id).count()

    # Apply sort order
    if sort_by == 'added_at':
        query = query.order_by(Author.added_at.desc().nullslast(), Author.name)
    elif _author_similarity is not None and sort_by is None:
        # When searching without explicit sort, order by relevance
        query = query.order_by(_author_similarity.desc(), Author.name)
    else:
        query = query.order_by(Author.name)

    results = query.limit(limit).offset(offset).all()

    # Build file_stats and book_stats dicts from joined results
    authors = []
    file_stats = {}
    book_stats = {}
    for row in results:
        author = row[0]
        total_chapters = row[1] or 0
        linked_files = int(row[2] or 0)
        total_books = int(row[3] or 0)
        monitored_books = int(row[4] or 0)
        authors.append(author)
        file_stats[author.id] = {
            'total_chapters': total_chapters,
            'linked_files': linked_files
        }
        book_stats[author.id] = {
            'total_books': total_books,
            'monitored_books': monitored_books,
        }

    # Fallback: for authors without image_url, get a book cover_art_url
    authors_without_image = [a.id for a in authors if not a.image_url]
    fallback_covers = {}
    if authors_without_image:
        from sqlalchemy import text as sa_text
        # Get the first book with a cover for each author
        cover_query = db.execute(sa_text("""
            SELECT DISTINCT ON (author_id) author_id, cover_art_url
            FROM books
            WHERE author_id = ANY(:author_ids)
              AND cover_art_url IS NOT NULL
            ORDER BY author_id,
                     release_date DESC NULLS LAST
        """), {"author_ids": authors_without_image})
        for row in cover_query:
            fallback_covers[row[0]] = row[1]

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "authors": [
            {
                "id": str(author.id),
                "name": author.name,
                "musicbrainz_id": author.musicbrainz_id,
                "is_monitored": author.is_monitored,
                "book_count": book_stats.get(author.id, {}).get('total_books', 0),
                "monitored_book_count": book_stats.get(author.id, {}).get('monitored_books', 0),
                "chapter_count": file_stats.get(author.id, {}).get('total_chapters', 0),
                "linked_files_count": file_stats.get(author.id, {}).get('linked_files', 0),
                "total_chapter_files": file_stats.get(author.id, {}).get('total_chapters', 0),
                "genre": author.genre,
                "image_url": author.image_url or fallback_covers.get(author.id),
                "added_at": author.added_at.isoformat() if author.added_at else None,
                "last_sync_at": author.last_sync_at.isoformat() if author.last_sync_at else None
            }
            for author in authors
        ]
    }


@router.get("/authors/{author_id}")
@rate_limit("100/minute")
async def get_author(
    request: Request,
    author_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """
    Get author details

    Args:
        author_id: Author UUID

    Returns:
        Author object with books and series
    """
    validate_uuid(author_id, "Author ID")

    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    # Get books
    books = db.query(Book).filter(Book.author_id == author_id).all()

    # Get series for this author
    series_list = (
        db.query(Series)
        .join(Book, Book.series_id == Series.id)
        .filter(Book.author_id == author_id)
        .distinct()
        .all()
    )

    # Get linked files count (author-level total)
    linked_files_count = (
        db.query(func.count(Chapter.id))
        .join(Book, Chapter.book_id == Book.id)
        .filter(Book.author_id == author_id, Chapter.has_file == True)
        .scalar()
    ) or 0

    # Get per-book chapter counts and linked files counts from actual Chapter rows
    book_ids = [b.id for b in books]
    if book_ids:
        chapter_stats_query = (
            db.query(
                Chapter.book_id,
                func.count(Chapter.id),
                func.sum(case((Chapter.has_file == True, 1), else_=0))
            )
            .filter(Chapter.book_id.in_(book_ids))
            .group_by(Chapter.book_id)
            .all()
        )
        real_chapter_counts = {book_id: int(total or 0) for book_id, total, _ in chapter_stats_query}
        linked_counts = {book_id: int(linked or 0) for book_id, _, linked in chapter_stats_query}
    else:
        real_chapter_counts = {}
        linked_counts = {}

    # Fallback image: use book cover if author has no image_url
    effective_image_url = author.image_url
    if not effective_image_url and books:
        for b in books:
            if b.cover_art_url:
                effective_image_url = b.cover_art_url
                break

    return {
        "id": str(author.id),
        "name": author.name,
        "musicbrainz_id": author.musicbrainz_id,
        "is_monitored": author.is_monitored,
        "quality_profile_id": str(author.quality_profile_id) if author.quality_profile_id else None,
        "root_folder_path": author.root_folder_path,
        "monitor_type": author.monitor_type,
        "image_url": effective_image_url,
        "overview": author.overview,
        "genre": author.genre,
        "book_count": author.book_count,
        "chapter_count": author.chapter_count,
        "linked_files_count": linked_files_count,
        "added_at": author.added_at.isoformat() if author.added_at else None,
        "last_sync_at": author.last_sync_at.isoformat() if author.last_sync_at else None,
        "books": [
            {
                "id": str(book.id),
                "title": book.title,
                "musicbrainz_id": book.musicbrainz_id,
                "release_date": book.release_date.isoformat() if book.release_date else None,
                "status": book.status.value,
                "monitored": book.monitored,
                "chapter_count": real_chapter_counts.get(book.id, book.chapter_count or 0),
                "linked_files_count": linked_counts.get(book.id, 0),
                "cover_art_url": book.cover_art_url,
                "series_id": str(book.series_id) if book.series_id else None
            }
            for book in books
        ],
        "series": [
            {
                "id": str(series.id),
                "name": series.name,
                "book_count": len(series.books),
                "monitored": series.monitored if series.monitored is not None else True,
            }
            for series in series_list
        ]
    }


@router.patch("/authors/{author_id}")
@rate_limit("50/minute")
async def update_author(
    request: Request,
    author_id: str,
    body: UpdateAuthorRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Update author settings (monitoring, bio, genre, country, etc.)
    """
    validate_uuid(author_id, "Author ID")

    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    try:
        if body.is_monitored is not None:
            author.is_monitored = body.is_monitored

        if body.quality_profile_id is not None:
            if body.quality_profile_id:
                validate_uuid(body.quality_profile_id, "Quality Profile ID")
            author.quality_profile_id = body.quality_profile_id

        if body.root_folder_path is not None:
            author.root_folder_path = body.root_folder_path

        if body.overview is not None:
            author.overview = body.overview.strip() or None

        if body.genre is not None:
            author.genre = body.genre.strip() or None

        if body.country is not None:
            author.country = body.country.strip() or None

        db.commit()
        db.refresh(author)

        # Create folder if author is now monitored
        if body.is_monitored is True:
            try:
                from app.services.folder_creator import get_folder_creator
                folder_creator = get_folder_creator(db)
                success, folder_path, error = folder_creator.create_author_folder(author)
                if success:
                    logger.info(f"Created folder for monitored author {author.name}: {folder_path}")
                elif error:
                    logger.warning(f"Failed to create folder for author {author.name}: {error}")
            except Exception as e:
                logger.error(f"Error creating folder for author {author.name}: {e}", exc_info=True)

        logger.info(f"Updated author: {author.name} (ID: {author_id})")

        return {
            "id": str(author.id),
            "name": author.name,
            "is_monitored": author.is_monitored,
            "quality_profile_id": str(author.quality_profile_id) if author.quality_profile_id else None,
            "root_folder_path": author.root_folder_path
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update author: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update author: {str(e)}"
        )


@router.delete("/authors/{author_id}")
@rate_limit("50/minute")
async def delete_author(
    request: Request,
    author_id: str,
    delete_files: bool = False,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Remove author from monitoring

    Args:
        author_id: Author UUID
        delete_files: Delete audio files from disk

    Returns:
        Success message
    """
    validate_uuid(author_id, "Author ID")

    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    try:
        author_name = author.name
        files_deleted_count = 0

        # Delete linked files from disk if requested
        if delete_files:
            import os
            chapters_with_files = (
                db.query(Chapter)
                .join(Book, Chapter.book_id == Book.id)
                .filter(Book.author_id == author_id, Chapter.has_file == True, Chapter.file_path.isnot(None))
                .all()
            )
            for chapter in chapters_with_files:
                try:
                    if os.path.exists(chapter.file_path):
                        os.remove(chapter.file_path)
                        files_deleted_count += 1
                        logger.info(f"Deleted file: {chapter.file_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete file {chapter.file_path}: {e}")

            # Clean up empty directories left behind
            dirs_to_check = set()
            for chapter in chapters_with_files:
                if chapter.file_path:
                    parent = os.path.dirname(chapter.file_path)
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

        # Delete author (cascade deletes books, chapters, downloads)
        db.delete(author)
        db.commit()

        logger.info(f"Deleted author: {author_name} (ID: {author_id}, delete_files: {delete_files}, files_deleted: {files_deleted_count})")

        return {
            "success": True,
            "message": f"Author '{author_name}' removed" + (f" ({files_deleted_count} files deleted)" if delete_files else ""),
            "files_deleted": delete_files,
            "files_deleted_count": files_deleted_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete author: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete author: {str(e)}"
        )


@router.post("/authors/{author_id}/sync")
@rate_limit("20/minute")
async def sync_author_books(
    request: Request,
    author_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Trigger book sync for author

    Args:
        author_id: Author UUID

    Returns:
        Sync job status
    """
    validate_uuid(author_id, "Author ID")

    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    try:
        # Trigger Celery background task
        from app.tasks.sync_tasks import sync_author_books

        task = sync_author_books.delay(str(author.id))

        logger.info(f"Triggered book sync for author: {author.name} (ID: {author_id}, Task: {task.id})")

        return {
            "success": True,
            "author_id": str(author.id),
            "author_name": author.name,
            "message": "Book sync started",
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger book sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger book sync: {str(e)}"
        )


@router.post("/authors/{author_id}/refresh-metadata")
@rate_limit("20/minute")
async def refresh_author_metadata_endpoint(
    request: Request,
    author_id: str,
    force: bool = False,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Refresh metadata (image, biography) for a single author

    Fetches missing author image, biography, genre, and book cover art
    without doing a full book sync from MusicBrainz.

    Args:
        author_id: Author UUID
        force: If true, re-fetch metadata even if fields already have values

    Returns:
        Refresh job status
    """
    validate_uuid(author_id, "Author ID")

    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    try:
        from app.tasks.sync_tasks import refresh_author_metadata
        from app.models.job_state import JobType

        task = refresh_author_metadata.apply_async(
            args=[str(author.id)],
            kwargs={
                'force': force,
                'job_type': JobType.METADATA_REFRESH,
                'entity_type': 'author',
                'entity_id': str(author.id)
            }
        )

        logger.info(f"Triggered metadata refresh for author: {author.name} (ID: {author_id}, Task: {task.id})")

        return {
            "success": True,
            "author_id": str(author.id),
            "author_name": author.name,
            "message": "Metadata refresh started",
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger metadata refresh: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger metadata refresh: {str(e)}"
        )


@router.post("/authors/{author_id}/detect-series")
@rate_limit("20/minute")
async def detect_author_series_endpoint(
    request: Request,
    author_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Detect and create series from file metadata for an author.

    Reads series tags from library file metadata, creates Series records,
    and links books with correct positions.

    Args:
        author_id: Author UUID

    Returns:
        Detection job status
    """
    validate_uuid(author_id, "Author ID")

    author = db.query(Author).filter(Author.id == author_id).first()

    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found"
        )

    try:
        from app.tasks.sync_tasks import detect_author_series
        from app.models.job_state import JobType

        task = detect_author_series.apply_async(
            args=[str(author.id)],
            kwargs={
                'job_type': JobType.METADATA_REFRESH,
                'entity_type': 'author',
                'entity_id': str(author.id)
            }
        )

        logger.info(f"Triggered series detection for author: {author.name} (ID: {author_id}, Task: {task.id})")

        return {
            "success": True,
            "author_id": str(author.id),
            "author_name": author.name,
            "message": "Series detection started",
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger series detection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger series detection: {str(e)}"
        )


@router.post("/authors/refresh-all-metadata")
@rate_limit("5/hour")
async def refresh_all_author_metadata_endpoint(
    request: Request,
    force: bool = False,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Refresh metadata (image, biography, genre, book covers) for ALL authors in the library.
    Queues individual refresh tasks for every author. Can take a while for large libraries.
    """
    try:
        from app.tasks.sync_tasks import refresh_all_author_metadata
        from app.models.job_state import JobType

        total_authors = db.query(Author).count()

        if total_authors == 0:
            return {"success": False, "message": "No authors in library", "total_authors": 0}

        task = refresh_all_author_metadata.apply_async(
            kwargs={
                'force': force,
                'job_type': JobType.METADATA_REFRESH,
                'entity_type': 'library',
                'entity_id': None
            }
        )

        logger.info(f"Triggered metadata refresh for all {total_authors} authors (Task: {task.id})")

        return {
            "success": True,
            "message": f"Queuing metadata refresh for {total_authors} authors",
            "total_authors": total_authors,
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"Failed to trigger bulk author metadata refresh: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger bulk metadata refresh: {str(e)}"
        )


@router.patch("/authors/bulk-update")
@rate_limit("30/minute")
async def bulk_update_authors(
    request: Request,
    update_request: BulkAuthorUpdateRequest = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Bulk update author settings

    Use case: Select multiple authors -> Monitor all
    """
    author_ids = update_request.author_ids
    is_monitored = update_request.is_monitored
    quality_profile_id = update_request.quality_profile_id

    if not author_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No author IDs provided"
        )

    # Validate all IDs
    for author_id in author_ids:
        validate_uuid(author_id, "Author ID")

    updated_count = 0

    try:
        for author_id in author_ids:
            author = db.query(Author).filter(Author.id == author_id).first()

            if not author:
                logger.warning(f"Author {author_id} not found, skipping")
                continue

            if is_monitored is not None:
                author.is_monitored = is_monitored

            if quality_profile_id is not None:
                if quality_profile_id:
                    validate_uuid(quality_profile_id, "Quality Profile ID")
                author.quality_profile_id = quality_profile_id

            updated_count += 1

        db.commit()

        logger.info(f"Bulk updated {updated_count} authors")

        return {
            "success": True,
            "updated_count": updated_count,
            "total_requested": len(author_ids)
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Bulk update failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk update failed: {str(e)}"
        )


@router.post("/authors/{author_id}/cover-art")
@rate_limit("10/minute")
async def upload_author_cover_art(
    request: Request,
    author_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Upload cover art / image for an author"""
    from app.services.cover_art_service import save_entity_cover_art

    validate_uuid(author_id, "Author ID")
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    filepath = await save_entity_cover_art("author", author_id, file)
    author.image_url = filepath
    db.commit()

    return {"message": "Cover art uploaded", "cover_art_url": author.image_url}


@router.post("/authors/{author_id}/cover-art-from-url")
@rate_limit("10/minute")
async def upload_author_cover_art_from_url(
    request: Request,
    author_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Fetch cover art / image for an author from a remote URL"""
    from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url

    validate_uuid(author_id, "Author ID")
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    filepath = await fetch_and_save_entity_cover_art_from_url("author", author_id, url)
    author.image_url = filepath
    db.commit()

    return {"message": "Cover art saved", "cover_art_url": author.image_url}


@router.get("/authors/{author_id}/cover-art")
async def get_author_cover_art(author_id: str, db: Session = Depends(get_db)):
    """Serve author cover art / image"""
    from app.services.cover_art_service import serve_entity_cover_art

    validate_uuid(author_id, "Author ID")
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    return serve_entity_cover_art("author", author_id, author.image_url)
