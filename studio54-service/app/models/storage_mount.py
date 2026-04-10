"""
Storage Mount model - Dynamic volume mount management for docker-compose
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class MountType(str, enum.Enum):
    """Storage mount content type"""
    MUSIC = "music"
    AUDIOBOOK = "audiobook"
    GENERIC = "generic"


class MountStatus(str, enum.Enum):
    """Mount application status"""
    APPLIED = "applied"
    PENDING = "pending"
    FAILED = "failed"


class StorageMount(Base):
    """
    StorageMount - Tracks volume mounts for docker-compose services.

    User-managed mounts can be added/removed via the Settings UI.
    System mounts (docker.sock, compose file, .env, logs) are protected.
    """
    __tablename__ = "storage_mounts"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Mount info
    name = Column(String(255), nullable=False)
    host_path = Column(Text, nullable=False, unique=True)
    container_path = Column(Text, nullable=False, unique=True)
    read_only = Column(Boolean, default=False, nullable=False)

    # Classification
    mount_type = Column(String(20), default=MountType.GENERIC.value, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Status tracking
    status = Column(String(50), default=MountStatus.PENDING.value, nullable=False)
    last_applied_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<StorageMount(id={self.id}, name='{self.name}', host_path='{self.host_path}' -> '{self.container_path}')>"
