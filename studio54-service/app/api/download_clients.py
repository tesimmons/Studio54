"""
Download Clients API Router
SABnzbd and NZBGet configuration endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.download_client import DownloadClient
from app.security import rate_limit, validate_uuid, validate_url, validate_api_key
from app.services.encryption import get_encryption_service
from app.services.sabnzbd_client import create_sabnzbd_client

logger = logging.getLogger(__name__)

router = APIRouter()


class AddDownloadClientRequest(BaseModel):
    """Request model for adding a download client"""
    name: str
    client_type: str = "sabnzbd"
    host: str
    port: int = 8080
    use_ssl: bool = False
    api_key: str
    category: str = "music"
    priority: int = 0
    is_enabled: bool = True
    is_default: bool = False


@router.post("/download-clients")
@rate_limit("20/minute")
async def add_download_client(
    request: Request,
    client_data: AddDownloadClientRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Add new download client (SABnzbd/NZBGet)

    Args:
        client_data: Download client configuration

    Returns:
        Created download client object
    """
    # Validate inputs
    if client_data.client_type not in ["sabnzbd", "nzbget"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client_type. Must be 'sabnzbd' or 'nzbget'"
        )

    validate_api_key(client_data.api_key, "API Key")

    # Check if name already exists
    existing = db.query(DownloadClient).filter(DownloadClient.name == client_data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Download client with name '{client_data.name}' already exists"
        )

    try:
        # Encrypt API key
        encryption_service = get_encryption_service()
        encrypted_api_key = encryption_service.encrypt(client_data.api_key)

        # If this is set as default, unset other defaults
        if client_data.is_default:
            db.query(DownloadClient).update({"is_default": False})

        # Create download client
        download_client = DownloadClient(
            name=client_data.name,
            client_type=client_data.client_type,
            host=client_data.host,
            port=client_data.port,
            use_ssl=client_data.use_ssl,
            api_key_encrypted=encrypted_api_key,
            category=client_data.category,
            priority=client_data.priority,
            is_enabled=client_data.is_enabled,
            is_default=client_data.is_default,
            created_at=datetime.now(timezone.utc)
        )

        db.add(download_client)
        db.commit()
        db.refresh(download_client)

        logger.info(f"Added download client: {client_data.name} ({client_data.client_type})")

        return {
            "id": str(download_client.id),
            "name": download_client.name,
            "client_type": download_client.client_type,
            "host": download_client.host,
            "port": download_client.port,
            "use_ssl": download_client.use_ssl,
            "category": download_client.category,
            "is_enabled": download_client.is_enabled,
            "is_default": download_client.is_default,
            "created_at": download_client.created_at.isoformat()
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add download client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add download client: {str(e)}"
        )


@router.get("/download-clients")
@rate_limit("100/minute")
async def list_download_clients(
    request: Request,
    enabled_only: bool = False,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    List configured download clients

    Args:
        enabled_only: Only return enabled clients

    Returns:
        List of download clients (without API keys)
    """
    query = db.query(DownloadClient)

    if enabled_only:
        query = query.filter(DownloadClient.is_enabled == True)

    clients = query.order_by(DownloadClient.is_default.desc(), DownloadClient.name).all()

    return {
        "total_count": len(clients),
        "clients": [
            {
                "id": str(client.id),
                "name": client.name,
                "client_type": client.client_type,
                "host": client.host,
                "port": client.port,
                "use_ssl": client.use_ssl,
                "base_url": client.base_url,
                "category": client.category,
                "priority": client.priority,
                "is_enabled": client.is_enabled,
                "is_default": client.is_default,
                "successful_downloads": client.successful_downloads,
                "failed_downloads": client.failed_downloads,
                "last_used_at": client.last_used_at.isoformat() if client.last_used_at else None
            }
            for client in clients
        ]
    }


@router.get("/download-clients/{client_id}")
@rate_limit("100/minute")
async def get_download_client(
    request: Request,
    client_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get download client details

    Args:
        client_id: Download client UUID

    Returns:
        Download client object (without API key)
    """
    validate_uuid(client_id, "Client ID")

    client = db.query(DownloadClient).filter(DownloadClient.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download client not found"
        )

    return {
        "id": str(client.id),
        "name": client.name,
        "client_type": client.client_type,
        "host": client.host,
        "port": client.port,
        "use_ssl": client.use_ssl,
        "base_url": client.base_url,
        "category": client.category,
        "priority": client.priority,
        "is_enabled": client.is_enabled,
        "is_default": client.is_default,
        "successful_downloads": client.successful_downloads,
        "failed_downloads": client.failed_downloads,
        "last_error": client.last_error,
        "last_used_at": client.last_used_at.isoformat() if client.last_used_at else None,
        "created_at": client.created_at.isoformat() if client.created_at else None,
        "updated_at": client.updated_at.isoformat() if client.updated_at else None
    }


@router.get("/download-clients/{client_id}/api-key")
@rate_limit("10/minute")
async def get_download_client_api_key(
    request: Request,
    client_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get download client API key (decrypted)

    Args:
        client_id: Download client UUID

    Returns:
        Decrypted API key
    """
    validate_uuid(client_id, "Client ID")

    client = db.query(DownloadClient).filter(DownloadClient.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download client not found"
        )

    try:
        # Decrypt API key
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(client.api_key_encrypted)

        return {"api_key": api_key}

    except Exception as e:
        logger.error(f"Failed to decrypt download client API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve API key"
        )


class UpdateDownloadClientRequest(BaseModel):
    """Request model for updating a download client"""
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    use_ssl: Optional[bool] = None
    api_key: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None
    is_enabled: Optional[bool] = None
    is_default: Optional[bool] = None


@router.patch("/download-clients/{client_id}")
@rate_limit("20/minute")
async def update_download_client(
    request: Request,
    client_id: str,
    data: UpdateDownloadClientRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Update download client configuration

    Args:
        client_id: Download client UUID
        data: Update data (all fields optional)

    Returns:
        Updated download client object
    """
    validate_uuid(client_id, "Client ID")

    client = db.query(DownloadClient).filter(DownloadClient.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download client not found"
        )

    try:
        if data.name is not None:
            # Check for name conflicts
            existing = db.query(DownloadClient).filter(
                DownloadClient.name == data.name,
                DownloadClient.id != client_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Download client with name '{data.name}' already exists"
                )
            client.name = data.name

        if data.host is not None:
            client.host = data.host

        if data.port is not None:
            client.port = data.port

        if data.use_ssl is not None:
            client.use_ssl = data.use_ssl

        if data.api_key is not None:
            validate_api_key(data.api_key, "API Key")
            encryption_service = get_encryption_service()
            client.api_key_encrypted = encryption_service.encrypt(data.api_key)

        if data.category is not None:
            client.category = data.category

        if data.priority is not None:
            client.priority = data.priority

        if data.is_enabled is not None:
            client.is_enabled = data.is_enabled

        if data.is_default is not None and data.is_default:
            # Unset other defaults
            db.query(DownloadClient).filter(DownloadClient.id != client_id).update({"is_default": False})
            client.is_default = True

        client.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(client)

        logger.info(f"Updated download client: {client.name} (ID: {client_id})")

        return {
            "id": str(client.id),
            "name": client.name,
            "client_type": client.client_type,
            "host": client.host,
            "port": client.port,
            "is_enabled": client.is_enabled,
            "is_default": client.is_default,
            "updated_at": client.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update download client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update download client: {str(e)}"
        )


@router.delete("/download-clients/{client_id}")
@rate_limit("20/minute")
async def delete_download_client(
    request: Request,
    client_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Delete download client

    Args:
        client_id: Download client UUID

    Returns:
        Success message
    """
    validate_uuid(client_id, "Client ID")

    client = db.query(DownloadClient).filter(DownloadClient.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download client not found"
        )

    try:
        client_name = client.name

        db.delete(client)
        db.commit()

        logger.info(f"Deleted download client: {client_name} (ID: {client_id})")

        return {
            "success": True,
            "message": f"Download client '{client_name}' deleted"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete download client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete download client: {str(e)}"
        )


@router.post("/download-clients/test-config")
@rate_limit("10/minute")
async def test_download_client_config(
    request: Request,
    client_data: AddDownloadClientRequest = Body(...),
):
    """
    Test download client configuration without saving

    Args:
        client_data: Download client configuration to test

    Returns:
        Test result with connection status
    """
    if client_data.client_type != "sabnzbd":
        return {
            "success": False,
            "message": "Only SABnzbd client testing is currently supported"
        }

    try:
        # Build base URL
        protocol = "https" if client_data.use_ssl else "http"
        base_url = f"{protocol}://{client_data.host}:{client_data.port}"

        # Test connection
        sabnzbd_client = create_sabnzbd_client(base_url, client_data.api_key)
        success = sabnzbd_client.test_connection()

        if success:
            return {
                "success": True,
                "message": "Connection test successful!"
            }
        else:
            return {
                "success": False,
                "message": "Failed to connect to download client. Check host, port, and API key."
            }

    except Exception as e:
        logger.error(f"Download client test failed: {e}")
        return {
            "success": False,
            "message": f"Connection failed: {str(e)}"
        }


@router.post("/download-clients/{client_id}/test")
@rate_limit("10/minute")
async def test_download_client(
    request: Request,
    client_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Test download client connection

    Args:
        client_id: Download client UUID

    Returns:
        Test result with connection status
    """
    validate_uuid(client_id, "Client ID")

    client = db.query(DownloadClient).filter(DownloadClient.id == client_id).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download client not found"
        )

    if client.client_type != "sabnzbd":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only SABnzbd client testing is currently supported"
        )

    try:
        # Decrypt API key
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(client.api_key_encrypted)

        # Test connection
        sabnzbd_client = create_sabnzbd_client(client.base_url, api_key)
        success = sabnzbd_client.test_connection()

        if success:
            logger.info(f"Download client test successful: {client.name}")

            return {
                "success": True,
                "client_id": str(client.id),
                "client_name": client.name,
                "message": "Connection test successful"
            }
        else:
            logger.warning(f"Download client test failed: {client.name}")

            return {
                "success": False,
                "client_id": str(client.id),
                "client_name": client.name,
                "message": "Connection test failed"
            }

    except Exception as e:
        logger.error(f"Download client test error for {client.name}: {e}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection test failed: {str(e)}"
        )
