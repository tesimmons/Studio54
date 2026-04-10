"""
Filesystem Browser API Router
Browse directories for custom folder path selection
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import logging
import os
from pathlib import Path

from app.security import rate_limit
from app.auth import require_any_user
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic schemas
class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_directory: bool
    size: Optional[int] = None
    modified: Optional[float] = None


class DirectoryListing(BaseModel):
    current_path: str
    parent_path: Optional[str]
    entries: List[DirectoryEntry]


@router.get("/filesystem/browse")
@rate_limit("100/minute")
async def browse_directory(
    request: Request,
    path: str = Query("/", description="Directory path to browse"),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """
    Browse filesystem directories for custom folder path selection.
    Returns list of directories (not files) in the specified path.

    Security: Restricted to common music/media directories for safety.
    """
    try:
        # Normalize path
        target_path = Path(path).resolve()

        # Security: Define allowed base paths
        # Users can browse within these directories
        allowed_bases = [
            Path("/music"),
            Path("/mnt"),
            Path("/media"),
            Path("/data"),
            Path("/storage"),
            Path("/docker"),
            Path("/home"),
        ]

        # Also allow browsing paths from active storage mounts
        try:
            from app.models.storage_mount import StorageMount
            active_mounts = db.query(StorageMount).filter(
                StorageMount.is_active == True,
                StorageMount.is_system == False,
            ).all()
            for mount in active_mounts:
                mount_path = Path(mount.container_path)
                if mount_path not in allowed_bases:
                    allowed_bases.append(mount_path)
        except Exception as e:
            logger.debug(f"Could not load storage mounts for allowed paths: {e}")

        # Check if path is within allowed bases
        is_allowed = any(
            str(target_path).startswith(str(base)) or str(base).startswith(str(target_path))
            for base in allowed_bases
        )

        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to path '{path}' is not allowed. Browse within: {', '.join(str(b) for b in allowed_bases)}"
            )

        # Check if path exists
        if not target_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Path '{path}' does not exist"
            )

        # Check if it's a directory
        if not target_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Path '{path}' is not a directory"
            )

        # Get parent path
        parent_path = str(target_path.parent) if target_path.parent != target_path else None

        # List directories (not files)
        entries = []
        try:
            for item in sorted(target_path.iterdir()):
                # Only include directories, skip hidden directories
                if item.is_dir() and not item.name.startswith('.'):
                    try:
                        stat = item.stat()
                        entries.append(DirectoryEntry(
                            name=item.name,
                            path=str(item),
                            is_directory=True,
                            size=None,  # Don't calculate directory sizes (expensive)
                            modified=stat.st_mtime
                        ))
                    except (OSError, PermissionError) as e:
                        # Skip directories we can't access
                        logger.debug(f"Skipping {item}: {e}")
                        continue
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied to read directory '{path}'"
            )

        return DirectoryListing(
            current_path=str(target_path),
            parent_path=parent_path,
            entries=entries
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error browsing directory '{path}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error browsing directory: {str(e)}"
        )
