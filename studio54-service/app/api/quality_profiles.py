"""
Quality Profiles API Router
CRUD operations for quality profiles with auto-seeding defaults
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_director
from app.models.user import User
from app.models.quality_profile import QualityProfile
from app.models.artist import Artist
from app.security import rate_limit, validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


# Default quality profiles (auto-seeded on first call)
DEFAULT_PROFILES = [
    {
        "name": "Any",
        "is_default": True,
        "allowed_formats": ["FLAC", "MP3-320", "MP3-V0", "MP3-256", "AAC-256", "AAC-320", "OGG-320"],
        "preferred_formats": ["FLAC", "MP3-320", "MP3-V0"],
        "min_bitrate": None,
        "max_size_mb": None,
        "upgrade_enabled": True,
        "upgrade_until_quality": "FLAC",
    },
    {
        "name": "Lossless",
        "is_default": False,
        "allowed_formats": ["FLAC", "ALAC", "WAV"],
        "preferred_formats": ["FLAC", "ALAC"],
        "min_bitrate": None,
        "max_size_mb": None,
        "upgrade_enabled": False,
        "upgrade_until_quality": None,
    },
    {
        "name": "High Quality MP3",
        "is_default": False,
        "allowed_formats": ["MP3-320", "MP3-V0", "FLAC"],
        "preferred_formats": ["MP3-320", "FLAC"],
        "min_bitrate": 256,
        "max_size_mb": None,
        "upgrade_enabled": True,
        "upgrade_until_quality": "FLAC",
    },
    {
        "name": "Standard",
        "is_default": False,
        "allowed_formats": ["MP3-192", "MP3-256", "MP3-320", "MP3-V0", "AAC-256", "AAC-320"],
        "preferred_formats": ["MP3-320", "MP3-256"],
        "min_bitrate": 192,
        "max_size_mb": 500,
        "upgrade_enabled": False,
        "upgrade_until_quality": None,
    },
]


def seed_default_profiles(db: Session):
    """Seed default quality profiles if none exist"""
    count = db.query(QualityProfile).count()
    if count > 0:
        return

    logger.info("Seeding default quality profiles")
    for profile_data in DEFAULT_PROFILES:
        profile = QualityProfile(**profile_data)
        db.add(profile)

    db.commit()
    logger.info(f"Seeded {len(DEFAULT_PROFILES)} default quality profiles")


class CreateProfileRequest(BaseModel):
    name: str
    allowed_formats: List[str]
    preferred_formats: List[str] = []
    min_bitrate: Optional[int] = None
    max_size_mb: Optional[int] = None
    upgrade_enabled: bool = False
    upgrade_until_quality: Optional[str] = None
    is_default: bool = False


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    allowed_formats: Optional[List[str]] = None
    preferred_formats: Optional[List[str]] = None
    min_bitrate: Optional[int] = None
    max_size_mb: Optional[int] = None
    upgrade_enabled: Optional[bool] = None
    upgrade_until_quality: Optional[str] = None
    is_default: Optional[bool] = None


def profile_to_dict(profile: QualityProfile) -> dict:
    """Convert profile to response dict"""
    return {
        "id": str(profile.id),
        "name": profile.name,
        "is_default": profile.is_default,
        "allowed_formats": profile.allowed_formats or [],
        "preferred_formats": profile.preferred_formats or [],
        "min_bitrate": profile.min_bitrate,
        "max_size_mb": profile.max_size_mb,
        "upgrade_enabled": profile.upgrade_enabled,
        "upgrade_until_quality": profile.upgrade_until_quality,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.get("/quality-profiles")
@rate_limit("100/minute")
async def list_quality_profiles(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    List all quality profiles

    Auto-seeds default profiles on first call if none exist.

    Returns:
        List of quality profiles
    """
    # Auto-seed defaults if empty
    seed_default_profiles(db)

    profiles = db.query(QualityProfile).order_by(
        QualityProfile.is_default.desc(),
        QualityProfile.name
    ).all()

    return {
        "quality_profiles": [profile_to_dict(p) for p in profiles]
    }


@router.post("/quality-profiles")
@rate_limit("30/minute")
async def create_quality_profile(
    request: Request,
    profile_data: CreateProfileRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Create a new quality profile

    Args:
        profile_data: Profile configuration

    Returns:
        Created quality profile
    """
    # Check for duplicate name
    existing = db.query(QualityProfile).filter(
        QualityProfile.name == profile_data.name
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Quality profile '{profile_data.name}' already exists"
        )

    if not profile_data.allowed_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one allowed format is required"
        )

    # If setting as default, unset existing default
    if profile_data.is_default:
        db.query(QualityProfile).filter(
            QualityProfile.is_default == True
        ).update({"is_default": False})

    profile = QualityProfile(
        name=profile_data.name,
        allowed_formats=profile_data.allowed_formats,
        preferred_formats=profile_data.preferred_formats,
        min_bitrate=profile_data.min_bitrate,
        max_size_mb=profile_data.max_size_mb,
        upgrade_enabled=profile_data.upgrade_enabled,
        upgrade_until_quality=profile_data.upgrade_until_quality,
        is_default=profile_data.is_default,
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    logger.info(f"Created quality profile: {profile.name}")

    return profile_to_dict(profile)


@router.patch("/quality-profiles/{profile_id}")
@rate_limit("30/minute")
async def update_quality_profile(
    request: Request,
    profile_id: str,
    updates: UpdateProfileRequest,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Update a quality profile

    Args:
        profile_id: Profile UUID
        updates: Fields to update

    Returns:
        Updated quality profile
    """
    validate_uuid(profile_id, "Profile ID")

    profile = db.query(QualityProfile).filter(
        QualityProfile.id == profile_id
    ).first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quality profile not found"
        )

    # Check for name uniqueness if name is being changed
    if updates.name is not None and updates.name != profile.name:
        existing = db.query(QualityProfile).filter(
            QualityProfile.name == updates.name
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Quality profile '{updates.name}' already exists"
            )

    # If setting as default, unset existing default
    if updates.is_default is True:
        db.query(QualityProfile).filter(
            QualityProfile.is_default == True,
            QualityProfile.id != profile.id
        ).update({"is_default": False})

    # Apply updates
    if updates.name is not None:
        profile.name = updates.name
    if updates.allowed_formats is not None:
        profile.allowed_formats = updates.allowed_formats
    if updates.preferred_formats is not None:
        profile.preferred_formats = updates.preferred_formats
    if updates.min_bitrate is not None:
        profile.min_bitrate = updates.min_bitrate
    if updates.max_size_mb is not None:
        profile.max_size_mb = updates.max_size_mb
    if updates.upgrade_enabled is not None:
        profile.upgrade_enabled = updates.upgrade_enabled
    if updates.upgrade_until_quality is not None:
        profile.upgrade_until_quality = updates.upgrade_until_quality
    if updates.is_default is not None:
        profile.is_default = updates.is_default

    db.commit()
    db.refresh(profile)

    logger.info(f"Updated quality profile: {profile.name}")

    return profile_to_dict(profile)


@router.delete("/quality-profiles/{profile_id}")
@rate_limit("30/minute")
async def delete_quality_profile(
    request: Request,
    profile_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Delete a quality profile

    Fails if any artists are assigned to this profile.

    Args:
        profile_id: Profile UUID

    Returns:
        Success message
    """
    validate_uuid(profile_id, "Profile ID")

    profile = db.query(QualityProfile).filter(
        QualityProfile.id == profile_id
    ).first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quality profile not found"
        )

    # Check if any artists use this profile
    artist_count = db.query(Artist).filter(
        Artist.quality_profile_id == profile.id
    ).count()

    if artist_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete profile: {artist_count} artist(s) are using it"
        )

    profile_name = profile.name
    db.delete(profile)
    db.commit()

    logger.info(f"Deleted quality profile: {profile_name}")

    return {
        "success": True,
        "message": f"Quality profile '{profile_name}' deleted"
    }
