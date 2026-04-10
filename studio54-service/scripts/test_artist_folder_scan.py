#!/usr/bin/env python3
"""
Test Artist Folder Scanning
Demonstrates how the artist folder scanning feature works
"""

import sys
import os

# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from difflib import SequenceMatcher
import re


def normalize_string(s: str) -> str:
    """Normalize string for comparison"""
    # Remove special characters, convert to lowercase
    s = re.sub(r'[^\w\s]', '', s.lower())
    # Remove common words
    for word in ['the', 'a', 'an']:
        s = s.replace(f' {word} ', ' ')
    return s.strip()


def string_similarity(s1: str, s2: str) -> float:
    """Calculate string similarity"""
    return SequenceMatcher(None, normalize_string(s1), normalize_string(s2)).ratio()


def test_folder_matching():
    """Test folder name to album title matching"""

    # Example: Pink Floyd artist folder
    artist_folder = "/music/Pink Floyd"

    # Simulated subdirectories
    folder_names = [
        "The Wall",
        "The Dark Side of the Moon",
        "Wish You Were Here",
        "Animals",
        "The Division Bell",
        "A Momentary Lapse of Reason"
    ]

    # Simulated album titles from MusicBrainz
    album_titles = [
        "The Wall",
        "The Dark Side of the Moon",
        "Wish You Were Here",
        "Animals",
        "The Division Bell",
        "A Momentary Lapse of Reason",
        "The Piper at the Gates of Dawn"  # Not in folders
    ]

    print("=" * 80)
    print("Artist Folder Scanning Test")
    print("=" * 80)
    print(f"\nArtist Folder: {artist_folder}")
    print(f"Subdirectories Found: {len(folder_names)}")
    print(f"Albums in Database: {len(album_titles)}")
    print("\n" + "-" * 80)

    matches = []
    for folder_name in folder_names:
        best_match = None
        best_score = 0.0

        for album_title in album_titles:
            score = string_similarity(folder_name, album_title)

            # Also check if album title is contained in folder name
            if normalize_string(album_title) in normalize_string(folder_name):
                score = max(score, 0.9)

            if score > best_score:
                best_score = score
                best_match = album_title

        confidence = round(best_score * 100, 1)
        auto_assign = best_score >= 0.7

        matches.append({
            "folder": folder_name,
            "album": best_match,
            "confidence": confidence,
            "auto_assigned": auto_assign
        })

        status = "✓ AUTO-ASSIGNED" if auto_assign else "✗ Manual review needed"
        print(f"\n{status}")
        print(f"  Folder: {folder_name}")
        print(f"  Album:  {best_match}")
        print(f"  Match:  {confidence}%")

    print("\n" + "=" * 80)
    auto_assigned = sum(1 for m in matches if m['auto_assigned'])
    print(f"Summary: {auto_assigned}/{len(folder_names)} folders auto-assigned")
    print("=" * 80)

    # Show unmatched albums
    matched_albums = {m['album'] for m in matches if m['auto_assigned']}
    unmatched_albums = [a for a in album_titles if a not in matched_albums]

    if unmatched_albums:
        print(f"\nAlbums without folder matches:")
        for album in unmatched_albums:
            print(f"  - {album}")


if __name__ == "__main__":
    test_folder_matching()
