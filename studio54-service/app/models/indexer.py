"""
Indexer model - NZB indexer configurations
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class Indexer(Base):
    """
    Indexer model - NZB indexer configuration

    Stores Newznab-compatible indexer settings with encrypted API keys
    """
    __tablename__ = "indexers"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Indexer identification
    name = Column(String(255), nullable=False, unique=True, index=True)
    base_url = Column(Text, nullable=False)  # e.g., https://api.nzbgeek.info
    api_key_encrypted = Column(Text, nullable=False)  # Fernet-encrypted API key

    # Indexer settings
    indexer_type = Column(String(50), default="newznab", nullable=False)
    priority = Column(Integer, default=100, nullable=False)  # Lower = higher priority
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Search categories
    categories = Column(JSONB, default=list)  # [3000] for Audio category

    # Rate limiting
    rate_limit_per_second = Column(Float, default=1.0, nullable=False)

    # Statistics
    successful_searches = Column(Integer, default=0)
    failed_searches = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Indexer(id={self.id}, name='{self.name}', enabled={self.is_enabled})>"
