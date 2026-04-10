"""
Root Folders API Router
Manage root folders for artist file organization (Lidarr-style)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from pydantic import BaseModel
import logging
import os

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.library import LibraryPath
from app.models.artist import Artist
from app.security import rate_limit, validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


class AddRootFolderRequest(BaseModel):
    """Request model for adding a root folder"""
    path: str
    name: Optional[str] = None
    library_type: Optional[str] = "music"  # "music" or "audiobook"


@router.get("/root-folders")
@rate_limit("100/minute")
async def list_root_folders(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    List all root folders with free space and artist counts

    Returns:
        List of root folders with metadata
    """
    library_type_filter = request.query_params.get("library_type")

    query = db.query(LibraryPath).filter(LibraryPath.is_root_folder == True)
    if library_type_filter:
        query = query.filter(LibraryPath.library_type == library_type_filter)
    root_folders = query.order_by(LibraryPath.path).all()

    results = []
    for folder in root_folders:
        # Count artists/authors using this root folder based on library type
        if getattr(folder, 'library_type', 'music') == 'audiobook':
            from app.models.author import Author
            entity_count = db.query(func.count(Author.id)).filter(
                Author.root_folder_path.like(f"{folder.path}%")
            ).scalar() or 0
        else:
            artist_count = db.query(func.count(Artist.id)).filter(
                Artist.root_folder_path.like(f"{folder.path}%")
            ).scalar() or 0
            entity_count = artist_count

        # Get free space
        free_space = None
        try:
            if os.path.exists(folder.path):
                stat = os.statvfs(folder.path)
                free_space = stat.f_frsize * stat.f_bavail
                # Update stored value
                folder.free_space_bytes = free_space
                db.commit()
        except (OSError, AttributeError):
            free_space = folder.free_space_bytes

        results.append({
            "id": str(folder.id),
            "path": folder.path,
            "name": folder.name,
            "library_type": getattr(folder, 'library_type', 'music'),
            "free_space_bytes": free_space,
            "free_space_gb": round(free_space / (1024**3), 2) if free_space else None,
            "artist_count": entity_count,
            "total_files": folder.total_files,
            "total_size_bytes": folder.total_size_bytes,
            "accessible": os.path.exists(folder.path),
        })

    return {"root_folders": results}


@router.post("/root-folders")
@rate_limit("30/minute")
async def add_root_folder(
    request: Request,
    folder_data: AddRootFolderRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Add a root folder for artist file organization

    If the path already exists as a library_path, flags it as a root folder.
    Otherwise creates a new library_path entry.

    Args:
        folder_data: Root folder path and optional name

    Returns:
        Created/updated root folder
    """
    path = folder_data.path.rstrip("/")

    if not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path cannot be empty"
        )

    # Check if path exists on filesystem
    if not os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path does not exist: {path}"
        )

    if not os.path.isdir(path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {path}"
        )

    # Check if already a root folder
    existing = db.query(LibraryPath).filter(LibraryPath.path == path).first()

    if existing:
        if existing.is_root_folder:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Path is already a root folder"
            )
        # Flag existing library path as root folder
        existing.is_root_folder = True
        if folder_data.name:
            existing.name = folder_data.name
        db.commit()
        db.refresh(existing)
        folder = existing
    else:
        # Create new library path as root folder
        name = folder_data.name or os.path.basename(path) or path
        library_type = folder_data.library_type or "music"
        if library_type not in ("music", "audiobook"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="library_type must be 'music' or 'audiobook'"
            )
        folder = LibraryPath(
            path=path,
            name=name,
            is_enabled=True,
            is_root_folder=True,
            library_type=library_type,
        )
        db.add(folder)
        db.commit()
        db.refresh(folder)

    # Get free space
    free_space = None
    try:
        stat = os.statvfs(path)
        free_space = stat.f_frsize * stat.f_bavail
        folder.free_space_bytes = free_space
        db.commit()
    except (OSError, AttributeError):
        pass

    logger.info(f"Added root folder: {path}")

    return {
        "id": str(folder.id),
        "path": folder.path,
        "name": folder.name,
        "library_type": getattr(folder, 'library_type', 'music'),
        "free_space_bytes": free_space,
        "free_space_gb": round(free_space / (1024**3), 2) if free_space else None,
        "accessible": True,
    }


@router.delete("/root-folders/{folder_id}")
@rate_limit("30/minute")
async def remove_root_folder(
    request: Request,
    folder_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Remove root folder flag from a library path

    Does not delete the library path itself, just removes the root folder designation.

    Args:
        folder_id: Library path UUID

    Returns:
        Success message
    """
    validate_uuid(folder_id, "Folder ID")

    folder = db.query(LibraryPath).filter(
        LibraryPath.id == folder_id,
        LibraryPath.is_root_folder == True
    ).first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Root folder not found"
        )

    folder.is_root_folder = False
    db.commit()

    logger.info(f"Removed root folder flag: {folder.path}")

    return {
        "success": True,
        "message": f"Root folder '{folder.path}' removed"
    }
