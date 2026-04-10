"""
Quality Profile model - Download quality preferences
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class QualityProfile(Base):
    """
    Quality Profile model - Defines download quality preferences

    Controls which formats to download and quality thresholds
    """
    __tablename__ = "quality_profiles"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Profile settings
    name = Column(String(255), nullable=False, unique=True, index=True)
    is_default = Column(Boolean, default=False)

    # Format preferences
    allowed_formats = Column(JSONB, nullable=False, default=list)  # ['FLAC', 'MP3-320', 'MP3-V0']
    preferred_formats = Column(JSONB, nullable=False, default=list)  # Ordered by preference

    # Quality thresholds
    min_bitrate = Column(Integer, nullable=True)  # Minimum bitrate in kbps
    max_size_mb = Column(Integer, nullable=True)  # Maximum file size per album

    # Upgrade settings
    upgrade_enabled = Column(Boolean, default=False)
    upgrade_until_quality = Column(String(50), nullable=True)  # e.g., 'FLAC'

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    artists = relationship("Artist", back_populates="quality_profile")

    def __repr__(self):
        return f"<QualityProfile(id={self.id}, name='{self.name}', formats={self.allowed_formats})>"

    def to_dict(self):
        """Convert to dict for decision engine"""
        return {
            "allowed_formats": self.allowed_formats or [],
            "preferred_formats": self.preferred_formats or [],
            "min_bitrate": self.min_bitrate,
            "max_size_mb": self.max_size_mb,
            "upgrade_enabled": self.upgrade_enabled,
        }
