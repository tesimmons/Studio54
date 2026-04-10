"""
DJ Request model - allows users to request artists, albums, or tracks.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.database import Base


class DjRequest(Base):
    __tablename__ = "dj_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # What they're requesting
    request_type = Column(String(20), nullable=False)  # artist, album, track
    title = Column(String(500), nullable=False)  # Name of the artist/album/track
    artist_name = Column(String(500), nullable=True)  # Artist name (for album/track requests)
    notes = Column(Text, nullable=True)  # Optional notes from requester
    musicbrainz_id = Column(String(36), nullable=True)  # Artist MBID from MusicBrainz search
    musicbrainz_name = Column(String(500), nullable=True)  # Canonical MB artist name
    track_name = Column(String(500), nullable=True)  # Specific track name (for preview lookups)

    # Status workflow: pending -> approved/rejected, approved -> fulfilled
    status = Column(String(20), nullable=False, default="pending")

    # Admin response
    response_note = Column(Text, nullable=True)  # Director's note on approval/rejection
    fulfilled_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    fulfilled_by = relationship("User", foreign_keys=[fulfilled_by_id])

    def __repr__(self):
        return f"<DjRequest {self.id} type={self.request_type} title={self.title} status={self.status}>"
