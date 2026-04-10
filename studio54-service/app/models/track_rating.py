"""
TrackRating model - Per-user track ratings
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class TrackRating(Base):
    """
    Per-user track rating (1-5 stars).

    Each user can rate each track once. The unique constraint on
    (user_id, track_id) ensures upsert semantics.
    """
    __tablename__ = "track_ratings"
    __table_args__ = (
        UniqueConstraint('user_id', 'track_id', name='uq_track_ratings_user_track'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User")
    track = relationship("Track")

    def __repr__(self):
        return f"<TrackRating(user_id={self.user_id}, track_id={self.track_id}, rating={self.rating})>"
