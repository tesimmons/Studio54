"""
Notification Profile model - Webhook/Discord/Slack notification configuration
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class NotificationEvent(str, enum.Enum):
    """Events that can trigger notifications"""
    ALBUM_DOWNLOADED = "album_downloaded"
    ALBUM_IMPORTED = "album_imported"
    ALBUM_FAILED = "album_failed"
    JOB_FAILED = "job_failed"
    JOB_COMPLETED = "job_completed"
    ARTIST_ADDED = "artist_added"


class NotificationProvider(str, enum.Enum):
    """Supported notification providers"""
    WEBHOOK = "webhook"
    DISCORD = "discord"
    SLACK = "slack"


class NotificationProfile(Base):
    """
    Notification Profile model - Stores webhook/notification endpoint configurations

    Users configure one or more profiles, each with a provider type, webhook URL,
    and list of events that should trigger notifications.
    """
    __tablename__ = "notification_profiles"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Profile identification
    name = Column(String(100), nullable=False, unique=True, index=True)
    provider = Column(String(20), nullable=False, default="webhook")  # webhook, discord, slack
    webhook_url_encrypted = Column(Text, nullable=False)  # Fernet-encrypted webhook URL

    # Configuration
    is_enabled = Column(Boolean, default=True, nullable=False)
    events = Column(JSONB, nullable=False, default=list)  # List of NotificationEvent values

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<NotificationProfile(id={self.id}, name='{self.name}', provider='{self.provider}', enabled={self.is_enabled})>"
