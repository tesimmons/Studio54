#!/usr/bin/env python3
"""
Recalculate artist statistics (album_count, single_count, track_count)
Run this script after adding the single_count column to update existing artists.
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from app.models.artist import Artist
from app.models.album import Album
from app.config import get_settings

def recalculate_stats():
    """Recalculate statistics for all artists"""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Get all artists
        artists = db.query(Artist).all()
        total = len(artists)

        print(f"Recalculating statistics for {total} artists...")

        updated = 0
        for i, artist in enumerate(artists, 1):
            # Calculate album count (exclude singles)
            album_count = db.query(Album).filter(
                Album.artist_id == artist.id,
                Album.album_type != 'Single'
            ).count()

            # Calculate single count
            single_count = db.query(Album).filter(
                Album.artist_id == artist.id,
                Album.album_type == 'Single'
            ).count()

            # Calculate total track count
            track_count = db.query(func.sum(Album.track_count)).filter(
                Album.artist_id == artist.id
            ).scalar() or 0

            # Update if values changed
            if (artist.album_count != album_count or
                artist.single_count != single_count or
                artist.track_count != track_count):

                old_values = f"Albums: {artist.album_count}, Singles: {artist.single_count}, Tracks: {artist.track_count}"

                artist.album_count = album_count
                artist.single_count = single_count
                artist.track_count = track_count

                new_values = f"Albums: {album_count}, Singles: {single_count}, Tracks: {track_count}"

                print(f"[{i}/{total}] {artist.name}")
                print(f"  Old: {old_values}")
                print(f"  New: {new_values}")

                updated += 1

            if i % 10 == 0:
                print(f"Progress: {i}/{total} artists processed...")

        db.commit()

        print(f"\n✅ Complete! Updated {updated} out of {total} artists")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    recalculate_stats()
