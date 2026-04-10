"""
Indexers API Router
NZB indexer configuration and testing endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.indexer import Indexer
from app.security import rate_limit, validate_uuid, validate_url, validate_api_key
from app.services.encryption import get_encryption_service
from app.services.newznab_client import create_newznab_client

logger = logging.getLogger(__name__)

router = APIRouter()


class AddIndexerRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    indexer_type: str = "newznab"
    priority: int = 100
    is_enabled: bool = True
    categories: Optional[List[int]] = None
    rate_limit_per_second: float = 1.0


@router.post("/indexers")
@rate_limit("20/minute")
async def add_indexer(
    request: Request,
    data: AddIndexerRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Add new NZB indexer

    Args:
        name: Indexer display name
        base_url: Indexer API base URL
        api_key: Indexer API key (will be encrypted)
        indexer_type: Indexer type (default: newznab)
        priority: Priority for search (higher = used first)
        is_enabled: Enable indexer
        categories: Newznab category IDs (default: [3010, 3040] for MP3 and lossless audio)
        rate_limit_per_second: Rate limit (requests per second)

    Returns:
        Created indexer object
    """
    # Validate inputs
    validate_url(data.base_url, "Base URL")
    validate_api_key(data.api_key, "API Key")

    # Check if indexer name already exists
    existing = db.query(Indexer).filter(Indexer.name == data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Indexer with name '{data.name}' already exists"
        )

    try:
        # Encrypt API key
        encryption_service = get_encryption_service()
        encrypted_api_key = encryption_service.encrypt(data.api_key)

        # Default categories: MP3 (3010) and lossless (3040) audio
        categories = data.categories if data.categories else [3010, 3040]

        # Create indexer
        indexer = Indexer(
            name=data.name,
            base_url=data.base_url,
            api_key_encrypted=encrypted_api_key,
            indexer_type=data.indexer_type,
            priority=data.priority,
            is_enabled=data.is_enabled,
            categories=categories,
            rate_limit_per_second=data.rate_limit_per_second,
            created_at=datetime.now(timezone.utc)
        )

        db.add(indexer)
        db.commit()
        db.refresh(indexer)

        logger.info(f"Added indexer: {data.name} ({data.base_url})")

        return {
            "id": str(indexer.id),
            "name": indexer.name,
            "base_url": indexer.base_url,
            "indexer_type": indexer.indexer_type,
            "priority": indexer.priority,
            "is_enabled": indexer.is_enabled,
            "created_at": indexer.created_at.isoformat()
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add indexer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add indexer: {str(e)}"
        )


@router.get("/indexers")
@rate_limit("100/minute")
async def list_indexers(
    request: Request,
    enabled_only: bool = False,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    List configured indexers

    Args:
        enabled_only: Only return enabled indexers

    Returns:
        List of indexers (without API keys)
    """
    query = db.query(Indexer)

    if enabled_only:
        query = query.filter(Indexer.is_enabled == True)

    indexers = query.order_by(Indexer.priority.desc(), Indexer.name).all()

    return {
        "total_count": len(indexers),
        "indexers": [
            {
                "id": str(indexer.id),
                "name": indexer.name,
                "base_url": indexer.base_url,
                "indexer_type": indexer.indexer_type,
                "priority": indexer.priority,
                "is_enabled": indexer.is_enabled,
                "categories": indexer.categories,
                "rate_limit_per_second": indexer.rate_limit_per_second
            }
            for indexer in indexers
        ]
    }


@router.get("/indexers/{indexer_id}")
@rate_limit("100/minute")
async def get_indexer(
    request: Request,
    indexer_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get indexer details

    Args:
        indexer_id: Indexer UUID

    Returns:
        Indexer object (without API key)
    """
    validate_uuid(indexer_id, "Indexer ID")

    indexer = db.query(Indexer).filter(Indexer.id == indexer_id).first()

    if not indexer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexer not found"
        )

    return {
        "id": str(indexer.id),
        "name": indexer.name,
        "base_url": indexer.base_url,
        "indexer_type": indexer.indexer_type,
        "priority": indexer.priority,
        "is_enabled": indexer.is_enabled,
        "categories": indexer.categories,
        "rate_limit_per_second": indexer.rate_limit_per_second,
        "created_at": indexer.created_at.isoformat() if indexer.created_at else None
    }


@router.get("/indexers/{indexer_id}/api-key")
@rate_limit("10/minute")
async def get_indexer_api_key(
    request: Request,
    indexer_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get indexer API key (decrypted)

    Args:
        indexer_id: Indexer UUID

    Returns:
        Decrypted API key
    """
    validate_uuid(indexer_id, "Indexer ID")

    indexer = db.query(Indexer).filter(Indexer.id == indexer_id).first()

    if not indexer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexer not found"
        )

    try:
        # Decrypt API key
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(indexer.api_key_encrypted)

        return {"api_key": api_key}

    except Exception as e:
        logger.error(f"Failed to decrypt indexer API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve API key"
        )


class UpdateIndexerRequest(BaseModel):
    """Request model for updating an indexer"""
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    priority: Optional[int] = None
    is_enabled: Optional[bool] = None
    categories: Optional[List[int]] = None
    rate_limit_per_second: Optional[float] = None


@router.patch("/indexers/{indexer_id}")
@rate_limit("20/minute")
async def update_indexer(
    request: Request,
    indexer_id: str,
    data: UpdateIndexerRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Update indexer configuration

    Args:
        indexer_id: Indexer UUID
        data: Update data (all fields optional)

    Returns:
        Updated indexer object
    """
    validate_uuid(indexer_id, "Indexer ID")

    indexer = db.query(Indexer).filter(Indexer.id == indexer_id).first()

    if not indexer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexer not found"
        )

    try:
        if data.name is not None:
            # Check for name conflicts
            existing = db.query(Indexer).filter(
                Indexer.name == data.name,
                Indexer.id != indexer_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Indexer with name '{data.name}' already exists"
                )
            indexer.name = data.name

        if data.base_url is not None:
            validate_url(data.base_url, "Base URL")
            indexer.base_url = data.base_url

        if data.api_key is not None:
            validate_api_key(data.api_key, "API Key")
            encryption_service = get_encryption_service()
            indexer.api_key_encrypted = encryption_service.encrypt(data.api_key)

        if data.priority is not None:
            indexer.priority = data.priority

        if data.is_enabled is not None:
            indexer.is_enabled = data.is_enabled

        if data.categories is not None:
            indexer.categories = data.categories

        if data.rate_limit_per_second is not None:
            indexer.rate_limit_per_second = data.rate_limit_per_second

        indexer.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(indexer)

        logger.info(f"Updated indexer: {indexer.name} (ID: {indexer_id})")

        return {
            "id": str(indexer.id),
            "name": indexer.name,
            "base_url": indexer.base_url,
            "priority": indexer.priority,
            "is_enabled": indexer.is_enabled,
            "updated_at": indexer.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update indexer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update indexer: {str(e)}"
        )


@router.delete("/indexers/{indexer_id}")
@rate_limit("20/minute")
async def delete_indexer(
    request: Request,
    indexer_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Delete indexer

    Args:
        indexer_id: Indexer UUID

    Returns:
        Success message
    """
    validate_uuid(indexer_id, "Indexer ID")

    indexer = db.query(Indexer).filter(Indexer.id == indexer_id).first()

    if not indexer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexer not found"
        )

    try:
        indexer_name = indexer.name

        db.delete(indexer)
        db.commit()

        logger.info(f"Deleted indexer: {indexer_name} (ID: {indexer_id})")

        return {
            "success": True,
            "message": f"Indexer '{indexer_name}' deleted"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete indexer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete indexer: {str(e)}"
        )


@router.post("/indexers/test-config")
@rate_limit("10/minute")
async def test_indexer_config(
    request: Request,
    data: AddIndexerRequest = Body(...),
    current_user: User = Depends(require_director),
):
    """
    Test indexer configuration without saving

    Args:
        data: Indexer configuration to test

    Returns:
        Test result with connection status
    """
    try:
        # Validate inputs
        validate_url(data.base_url, "Base URL")
        validate_api_key(data.api_key, "API Key")

        # Use configured categories or default to MP3 + lossless
        categories = data.categories if data.categories else [3010, 3040]

        # Create client and test connection
        client = create_newznab_client(data.base_url, data.api_key, data.name, categories)

        # Test connection using built-in method
        connection_success = client.test_connection()

        if not connection_success:
            return {
                "success": False,
                "message": "Failed to connect to indexer. Check URL and API key."
            }

        # Test basic search to verify functionality
        try:
            results = client.search("test", limit=1)
            return {
                "success": True,
                "message": f"Connection successful! Indexer is responding correctly."
            }
        except Exception as search_error:
            # Connection worked but search failed - still consider it mostly successful
            return {
                "success": True,
                "message": f"Connection successful! (Note: Search test had issues: {str(search_error)})"
            }

    except Exception as e:
        logger.error(f"Indexer test failed: {e}")
        return {
            "success": False,
            "message": f"Connection failed: {str(e)}"
        }


@router.post("/indexers/{indexer_id}/test")
@rate_limit("10/minute")
async def test_indexer(
    request: Request,
    indexer_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Test indexer connection and API

    Args:
        indexer_id: Indexer UUID

    Returns:
        Test result with connection status
    """
    validate_uuid(indexer_id, "Indexer ID")

    indexer = db.query(Indexer).filter(Indexer.id == indexer_id).first()

    if not indexer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexer not found"
        )

    try:
        # Decrypt API key
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(indexer.api_key_encrypted)

        # Use indexer's configured categories or default to MP3 + lossless
        categories = indexer.categories if indexer.categories else [3010, 3040]

        # Create client and test connection
        client = create_newznab_client(indexer.base_url, api_key, indexer.name, categories)
        success = client.test_connection()

        if success:
            # Update success stats
            indexer.successful_searches += 1
            indexer.last_used_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(f"Indexer test successful: {indexer.name}")

            return {
                "success": True,
                "indexer_id": str(indexer.id),
                "indexer_name": indexer.name,
                "message": "Connection test successful"
            }
        else:
            # Update failure stats
            indexer.failed_searches += 1
            indexer.last_used_at = datetime.now(timezone.utc)
            db.commit()

            logger.warning(f"Indexer test failed: {indexer.name}")

            return {
                "success": False,
                "indexer_id": str(indexer.id),
                "indexer_name": indexer.name,
                "message": "Connection test failed"
            }

    except Exception as e:
        # Update failure stats
        indexer.failed_searches += 1
        indexer.last_used_at = datetime.now(timezone.utc)
        indexer.last_error = str(e)
        db.commit()

        logger.error(f"Indexer test error for {indexer.name}: {e}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Indexer test failed: {str(e)}"
        )


@router.post("/indexers/search")
@rate_limit("20/minute")
async def search_indexers(
    request: Request,
    query: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    limit_per_indexer: int = 50,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Search all enabled indexers

    Args:
        query: Search query string
        artist: Artist name filter
        album: Album name filter
        limit_per_indexer: Max results per indexer

    Returns:
        Aggregated and ranked search results
    """
    try:
        # Get enabled indexers
        indexers = db.query(Indexer).filter(Indexer.is_enabled == True).order_by(Indexer.priority.desc()).all()

        if not indexers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No enabled indexers configured"
            )

        # Create clients
        encryption_service = get_encryption_service()
        clients = []

        for indexer in indexers:
            try:
                api_key = encryption_service.decrypt(indexer.api_key_encrypted)
                # Use indexer's configured categories or default to MP3 + lossless
                categories = indexer.categories if indexer.categories else [3010, 3040]
                client = create_newznab_client(indexer.base_url, api_key, indexer.name, categories)
                client.rate_limit_interval = indexer.rate_limit_per_second
                clients.append(client)
            except Exception as e:
                logger.error(f"Failed to create client for indexer {indexer.name}: {e}")
                continue

        if not clients:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to initialize any indexers"
            )

        # Create aggregator and search
        from app.services.newznab_client import create_aggregator

        aggregator = create_aggregator(clients)

        if artist or album:
            results = aggregator.search_music(artist, album, limit_per_indexer)
        else:
            results = aggregator.search(query, limit_per_indexer=limit_per_indexer)

        logger.info(f"Indexer search completed: {len(results)} results for query '{query}'")

        return {
            "query": query,
            "artist": artist,
            "album": album,
            "total_results": len(results),
            "indexers_searched": len(clients),
            "results": [result.to_dict() for result in results]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Indexer search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )
