"""
User model - Authentication and role-based access control
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


# Role constants (stored as varchar, not PG enum - matches MonitorType pattern)
class UserRole:
    DIRECTOR = "director"
    DJ = "dj"
    PARTYGOER = "partygoer"

    ALL = [DIRECTOR, DJ, PARTYGOER]


class User(Base):
    """
    User model for authentication and authorization.

    Roles:
    - director: Full admin access (Club Director)
    - dj: Editor access - browse, play, download, edit metadata, per-artist ops
    - partygoer: Listener access - browse and play only
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default=UserRole.PARTYGOER)
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    preferences = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"
