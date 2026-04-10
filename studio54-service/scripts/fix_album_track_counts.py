#!/usr/bin/env python3
"""
Fix Album Track Counts
Recalculate track_count for all albums based on actual tracks in database
"""

import sys
import os

# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.album import Album
from app.models.track import Track
from app.models.artist import Artist
from sqlalchemy import func


def fix_album_track_counts():
    """Recalculate and fix track_count for all albums"""
    db = SessionLocal()

    try:
        # Get all albums
        albums = db.query(Album).all()

        print(f"Processing {len(albums)} albums...")
        print("-" * 80)

        fixed_count = 0
        unchanged_count = 0

        for album in albums:
            # Count actual tracks
            actual_count = db.query(Track).filter(Track.album_id == album.id).count()

            if album.track_count != actual_count:
                print(f"Album: {album.title}")
                print(f"  Old track_count: {album.track_count}")
                print(f"  New track_count: {actual_count}")

                album.track_count = actual_count
                fixed_count += 1
            else:
                unchanged_count += 1

        # Commit all changes
        if fixed_count > 0:
            print("\n" + "=" * 80)
            print(f"Committing changes for {fixed_count} albums...")
            db.commit()
            print("✓ Album track counts updated successfully")
        else:
            print("\n✓ All album track counts are already accurate")

        print(f"\nSummary:")
        print(f"  Fixed: {fixed_count}")
        print(f"  Unchanged: {unchanged_count}")
        print(f"  Total: {len(albums)}")

        return fixed_count

    except Exception as e:
        print(f"\n✗ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def update_artist_statistics():
    """Recalculate artist statistics after fixing album counts"""
    db = SessionLocal()

    try:
        artists = db.query(Artist).all()

        print(f"\nUpdating statistics for {len(artists)} artists...")
        print("-" * 80)

        updated_count = 0

        for artist in artists:
            # Recalculate track count from albums
            new_track_count = db.query(func.sum(Album.track_count)).filter(
                Album.artist_id == artist.id
            ).scalar() or 0

            if artist.track_count != new_track_count:
                print(f"Artist: {artist.name}")
                print(f"  Old track_count: {artist.track_count}")
                print(f"  New track_count: {new_track_count}")

                artist.track_count = new_track_count
                updated_count += 1

        if updated_count > 0:
            print(f"\nCommitting changes for {updated_count} artists...")
            db.commit()
            print("✓ Artist statistics updated successfully")
        else:
            print("\n✓ All artist statistics are already accurate")

        print(f"\nSummary:")
        print(f"  Updated: {updated_count}")
        print(f"  Total: {len(artists)}")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 80)
    print("Studio54 - Fix Album Track Counts")
    print("=" * 80)
    print()

    # Step 1: Fix album track counts
    fixed = fix_album_track_counts()

    # Step 2: Update artist statistics if we fixed any albums
    if fixed > 0:
        print()
        update_artist_statistics()

    print()
    print("=" * 80)
    print("Done!")
    print("=" * 80)
