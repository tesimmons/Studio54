"""
Series model - Ordered collection of related books by an author
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Series(Base):
    """
    Series model - An ordered collection of related books by an author

    Monitoring a series cascades to all its books.
    """
    __tablename__ = "series"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    author_id = Column(UUID(as_uuid=True), ForeignKey("authors.id", ondelete="CASCADE"), nullable=False, index=True)

    # Basic info
    name = Column(Text, nullable=False, index=True)
    musicbrainz_series_id = Column(String(36), nullable=True, index=True)
    description = Column(Text, nullable=True)
    total_expected_books = Column(Integer, nullable=True)

    # Monitoring (cascades to all books in the series)
    monitored = Column(Boolean, default=False, nullable=False)

    # Media
    cover_art_url = Column(Text, nullable=True)

    # Timestamps
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    author = relationship("Author", back_populates="series")
    books = relationship("Book", back_populates="series", order_by="Book.series_position")
    playlist = relationship("BookPlaylist", back_populates="series", uselist=False,
                            cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Series(id={self.id}, name='{self.name}', author_id='{self.author_id}')>"


def _cascade_series_monitored(mapper, connection, target):
    """When series.monitored changes, cascade to all books in the series."""
    from app.models.book import Book
    history = target.__class__.monitored.property.columns[0]
    # Use the connection to update books directly (avoids session issues)
    connection.execute(
        Book.__table__.update()
        .where(Book.__table__.c.series_id == target.id)
        .values(monitored=target.monitored)
    )


# Listen for updates to Series.monitored
event.listen(Series, "after_update", _cascade_series_monitored)
