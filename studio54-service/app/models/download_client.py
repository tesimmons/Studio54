"""
Download Client model - SABnzbd configurations
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class DownloadClient(Base):
    """
    Download Client model - SABnzbd/NZBGet configuration

    Stores download client settings with encrypted API keys
    """
    __tablename__ = "download_clients"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Client identification
    name = Column(String(255), nullable=False, unique=True, index=True)
    client_type = Column(String(50), default="sabnzbd", nullable=False)  # sabnzbd or nzbget

    # Connection settings
    host = Column(Text, nullable=False)  # e.g., 192.168.150.99
    port = Column(Integer, default=8080, nullable=False)
    use_ssl = Column(Boolean, default=False)
    api_key_encrypted = Column(Text, nullable=False)  # Fernet-encrypted API key

    # Download settings
    category = Column(String(100), default="music", nullable=False)
    priority = Column(Integer, default=0)  # Download priority (0 = default)

    # Status
    is_enabled = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    # Statistics
    successful_downloads = Column(Integer, default=0)
    failed_downloads = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<DownloadClient(id={self.id}, name='{self.name}', type='{self.client_type}')>"

    @property
    def base_url(self):
        """Construct base URL from host, port, and SSL settings"""
        protocol = "https" if self.use_ssl else "http"
        return f"{protocol}://{self.host}:{self.port}"
