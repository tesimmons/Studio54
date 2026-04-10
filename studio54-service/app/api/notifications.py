"""
Notifications API Router
Webhook/Discord/Slack notification profile management
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
from app.models.notification import NotificationProfile, NotificationEvent, NotificationProvider
from app.security import rate_limit, validate_uuid
from app.services.encryption import get_encryption_service

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_EVENTS = [e.value for e in NotificationEvent]
VALID_PROVIDERS = [p.value for p in NotificationProvider]


class CreateNotificationRequest(BaseModel):
    name: str
    provider: str = "webhook"
    webhook_url: str
    is_enabled: bool = True
    events: List[str] = []


class UpdateNotificationRequest(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    webhook_url: Optional[str] = None
    is_enabled: Optional[bool] = None
    events: Optional[List[str]] = None


def _profile_to_dict(profile: NotificationProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "provider": profile.provider,
        "is_enabled": profile.is_enabled,
        "events": profile.events or [],
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.get("/notifications")
@rate_limit("100/minute")
async def list_notifications(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """List all notification profiles."""
    profiles = db.query(NotificationProfile).order_by(NotificationProfile.name).all()
    return {
        "total_count": len(profiles),
        "notifications": [_profile_to_dict(p) for p in profiles],
    }


@router.post("/notifications")
@rate_limit("20/minute")
async def create_notification(
    request: Request,
    data: CreateNotificationRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Create a new notification profile."""
    # Validate provider
    if data.provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider '{data.provider}'. Valid: {VALID_PROVIDERS}"
        )

    # Validate events
    for event in data.events:
        if event not in VALID_EVENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid event '{event}'. Valid: {VALID_EVENTS}"
            )

    # Check name uniqueness
    existing = db.query(NotificationProfile).filter(NotificationProfile.name == data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Notification profile with name '{data.name}' already exists"
        )

    try:
        encryption_service = get_encryption_service()
        encrypted_url = encryption_service.encrypt(data.webhook_url)

        profile = NotificationProfile(
            name=data.name,
            provider=data.provider,
            webhook_url_encrypted=encrypted_url,
            is_enabled=data.is_enabled,
            events=data.events,
            created_at=datetime.now(timezone.utc),
        )

        db.add(profile)
        db.commit()
        db.refresh(profile)

        logger.info(f"Created notification profile: {data.name} ({data.provider})")

        return _profile_to_dict(profile)

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create notification profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create notification profile: {str(e)}"
        )


@router.patch("/notifications/{notification_id}")
@rate_limit("20/minute")
async def update_notification(
    request: Request,
    notification_id: str,
    data: UpdateNotificationRequest = Body(...),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Update a notification profile."""
    validate_uuid(notification_id, "Notification ID")

    profile = db.query(NotificationProfile).filter(NotificationProfile.id == notification_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification profile not found")

    try:
        if data.name is not None:
            # Check name uniqueness
            existing = db.query(NotificationProfile).filter(
                NotificationProfile.name == data.name,
                NotificationProfile.id != notification_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Notification profile with name '{data.name}' already exists"
                )
            profile.name = data.name

        if data.provider is not None:
            if data.provider not in VALID_PROVIDERS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid provider '{data.provider}'. Valid: {VALID_PROVIDERS}"
                )
            profile.provider = data.provider

        if data.webhook_url is not None:
            encryption_service = get_encryption_service()
            profile.webhook_url_encrypted = encryption_service.encrypt(data.webhook_url)

        if data.is_enabled is not None:
            profile.is_enabled = data.is_enabled

        if data.events is not None:
            for event in data.events:
                if event not in VALID_EVENTS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid event '{event}'. Valid: {VALID_EVENTS}"
                    )
            profile.events = data.events

        profile.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(profile)

        logger.info(f"Updated notification profile: {profile.name} (ID: {notification_id})")

        return _profile_to_dict(profile)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update notification profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update notification profile: {str(e)}"
        )


@router.delete("/notifications/{notification_id}")
@rate_limit("20/minute")
async def delete_notification(
    request: Request,
    notification_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Delete a notification profile."""
    validate_uuid(notification_id, "Notification ID")

    profile = db.query(NotificationProfile).filter(NotificationProfile.id == notification_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification profile not found")

    try:
        profile_name = profile.name
        db.delete(profile)
        db.commit()

        logger.info(f"Deleted notification profile: {profile_name} (ID: {notification_id})")

        return {"success": True, "message": f"Notification profile '{profile_name}' deleted"}

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete notification profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notification profile: {str(e)}"
        )


@router.post("/notifications/{notification_id}/test")
@rate_limit("10/minute")
async def test_notification(
    request: Request,
    notification_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """Send a test notification to verify the webhook URL."""
    validate_uuid(notification_id, "Notification ID")

    profile = db.query(NotificationProfile).filter(NotificationProfile.id == notification_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification profile not found")

    try:
        from app.services.notification_service import send_test_notification
        send_test_notification(profile)

        return {
            "success": True,
            "message": f"Test notification sent to '{profile.name}'"
        }

    except Exception as e:
        logger.error(f"Test notification failed for '{profile.name}': {e}")
        return {
            "success": False,
            "message": f"Test failed: {str(e)}"
        }
