"""
Storage Mounts API Router
Manage dynamic volume mounts for docker-compose services via Settings UI.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.storage_mount import StorageMount, MountStatus, MountType
from app.services.compose_manager import (
    validate_host_path,
    validate_container_path,
    apply_mounts,
    rollback,
    get_pending_changes,
)
from app.security import rate_limit, validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request Models ---

class AddMountRequest(BaseModel):
    """Request model for adding a storage mount"""
    name: str
    host_path: str
    container_path: str
    read_only: bool = False
    mount_type: str = "generic"


class UpdateMountRequest(BaseModel):
    """Request model for updating a storage mount"""
    name: Optional[str] = None
    read_only: Optional[bool] = None
    mount_type: Optional[str] = None


class ValidatePathRequest(BaseModel):
    """Request model for path validation"""
    host_path: str


# --- Helper ---

def _mount_to_dict(mount: StorageMount) -> dict:
    """Convert StorageMount to API response dict."""
    return {
        "id": str(mount.id),
        "name": mount.name,
        "host_path": mount.host_path,
        "container_path": mount.container_path,
        "read_only": mount.read_only,
        "mount_type": mount.mount_type,
        "is_system": mount.is_system,
        "is_active": mount.is_active,
        "status": mount.status,
        "last_applied_at": mount.last_applied_at.isoformat() if mount.last_applied_at else None,
        "error_message": mount.error_message,
        "created_at": mount.created_at.isoformat() if mount.created_at else None,
        "updated_at": mount.updated_at.isoformat() if mount.updated_at else None,
    }


# --- Endpoints ---

@router.get("/settings/storage-mounts")
@rate_limit("100/minute")
async def list_storage_mounts(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    List all storage mounts (system + user) with pending changes info.
    """
    mounts = db.query(StorageMount).order_by(
        StorageMount.is_system.desc(),
        StorageMount.created_at.asc(),
    ).all()

    pending_info = get_pending_changes(db)

    return {
        "mounts": [_mount_to_dict(m) for m in mounts],
        "has_pending_changes": pending_info.get("has_changes", False),
        "pending_count": pending_info.get("pending_count", 0),
    }


@router.post("/settings/storage-mounts")
@rate_limit("30/minute")
async def add_storage_mount(
    request: Request,
    mount_data: AddMountRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Add a new storage mount. Saved to DB with status='pending'.
    Must call /apply to write to compose and restart containers.
    """
    # Validate mount_type
    valid_types = [t.value for t in MountType]
    if mount_data.mount_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mount_type. Must be one of: {', '.join(valid_types)}",
        )

    # Validate container path
    container_path = mount_data.container_path.rstrip("/")
    if not container_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Container path cannot be empty",
        )

    path_error = validate_container_path(container_path)
    if path_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=path_error,
        )

    # Check for duplicate host_path
    existing_host = db.query(StorageMount).filter(
        StorageMount.host_path == mount_data.host_path
    ).first()
    if existing_host:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Host path already mounted: {mount_data.host_path}",
        )

    # Check for duplicate container_path
    existing_container = db.query(StorageMount).filter(
        StorageMount.container_path == container_path
    ).first()
    if existing_container:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Container path already in use: {container_path}",
        )

    mount = StorageMount(
        name=mount_data.name,
        host_path=mount_data.host_path,
        container_path=container_path,
        read_only=mount_data.read_only,
        mount_type=mount_data.mount_type,
        is_system=False,
        is_active=True,
        status=MountStatus.PENDING.value,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)

    logger.info(f"Added storage mount: {mount.name} ({mount.host_path} -> {mount.container_path})")

    return _mount_to_dict(mount)


@router.put("/settings/storage-mounts/{mount_id}")
@rate_limit("30/minute")
async def update_storage_mount(
    request: Request,
    mount_id: str,
    mount_data: UpdateMountRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Update a storage mount's name, read_only flag, or mount_type.
    Cannot modify system mounts.
    """
    validate_uuid(mount_id, "Mount ID")

    mount = db.query(StorageMount).filter(StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Storage mount not found",
        )

    if mount.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System mounts cannot be modified",
        )

    if mount_data.name is not None:
        mount.name = mount_data.name
    if mount_data.read_only is not None:
        mount.read_only = mount_data.read_only
    if mount_data.mount_type is not None:
        valid_types = [t.value for t in MountType]
        if mount_data.mount_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid mount_type. Must be one of: {', '.join(valid_types)}",
            )
        mount.mount_type = mount_data.mount_type

    # Mark as pending if applied mount was changed
    if mount.status == MountStatus.APPLIED.value:
        mount.status = MountStatus.PENDING.value

    db.commit()
    db.refresh(mount)

    logger.info(f"Updated storage mount: {mount.name} ({mount_id})")

    return _mount_to_dict(mount)


@router.delete("/settings/storage-mounts/{mount_id}")
@rate_limit("30/minute")
async def delete_storage_mount(
    request: Request,
    mount_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Delete a storage mount. Cannot delete system mounts.
    Requires /apply to take effect in compose.
    """
    validate_uuid(mount_id, "Mount ID")

    mount = db.query(StorageMount).filter(StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Storage mount not found",
        )

    if mount.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System mounts cannot be deleted",
        )

    mount_name = mount.name
    db.delete(mount)
    db.commit()

    logger.info(f"Deleted storage mount: {mount_name} ({mount_id})")

    return {"success": True, "message": f"Storage mount '{mount_name}' deleted"}


@router.post("/settings/storage-mounts/validate-path")
@rate_limit("30/minute")
async def validate_path(
    request: Request,
    path_data: ValidatePathRequest,
    current_user: User = Depends(require_director),
):
    """
    Validate that a host path exists using a busybox container probe.
    """
    result = validate_host_path(path_data.host_path)
    return result


@router.post("/settings/storage-mounts/apply")
@rate_limit("10/minute")
async def apply_storage_mounts(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Apply all pending mount changes to docker-compose.yml and restart containers.
    Returns immediately - frontend should poll /health until service returns.
    """
    result = apply_mounts(db)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"],
        )

    return {"status": "restarting", "message": result["message"]}


@router.post("/settings/storage-mounts/rollback")
@rate_limit("10/minute")
async def rollback_storage_mounts(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """
    Restore the previous docker-compose.yml from backup and restart containers.
    """
    result = rollback(db)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["message"],
        )

    return {"status": "restarting", "message": result["message"]}
