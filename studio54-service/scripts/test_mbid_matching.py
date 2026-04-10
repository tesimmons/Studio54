#!/usr/bin/env python3
"""
Test MBID Matching
Test that MBID extraction from comment fields works correctly
"""

import sys
import os

# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.metadata_extractor import MetadataExtractor


def test_mbid_extraction_from_comment():
    """Test extracting MBIDs from MUSE Ponder comment format"""

    # Simulate a comment field from MUSE Ponder
    test_comment = "RecordingMBID:12345678-1234-1234-1234-123456789abc | ArtistMBID:87654321-4321-4321-4321-cba987654321 | ReleaseMBID:11111111-2222-3333-4444-555555555555 | ReleaseGroupMBID:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    print("Testing MBID extraction from comment field:")
    print(f"Comment: {test_comment}\n")

    # Test track (recording) MBID
    track_mbid = MetadataExtractor._extract_mbid_from_comment(test_comment, 'track')
    print(f"✓ Track MBID: {track_mbid}")
    assert track_mbid == "12345678-1234-1234-1234-123456789abc", f"Expected track MBID, got {track_mbid}"

    # Test artist MBID
    artist_mbid = MetadataExtractor._extract_mbid_from_comment(test_comment, 'artist')
    print(f"✓ Artist MBID: {artist_mbid}")
    assert artist_mbid == "87654321-4321-4321-4321-cba987654321", f"Expected artist MBID, got {artist_mbid}"

    # Test album (release) MBID
    album_mbid = MetadataExtractor._extract_mbid_from_comment(test_comment, 'album')
    print(f"✓ Album MBID: {album_mbid}")
    assert album_mbid == "11111111-2222-3333-4444-555555555555", f"Expected album MBID, got {album_mbid}"

    # Test release group MBID
    rg_mbid = MetadataExtractor._extract_mbid_from_comment(test_comment, 'releasegroup')
    print(f"✓ Release Group MBID: {rg_mbid}")
    assert rg_mbid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", f"Expected RG MBID, got {rg_mbid}"

    print("\n" + "=" * 80)
    print("✓ All MBID extraction tests passed!")
    print("=" * 80)


def test_partial_comment():
    """Test extracting MBID when only some fields are present"""

    # Only Recording MBID present
    partial_comment = "RecordingMBID:12345678-1234-1234-1234-123456789abc"

    print("\nTesting partial comment (only Recording MBID):")
    print(f"Comment: {partial_comment}\n")

    track_mbid = MetadataExtractor._extract_mbid_from_comment(partial_comment, 'track')
    print(f"✓ Track MBID: {track_mbid}")
    assert track_mbid == "12345678-1234-1234-1234-123456789abc"

    artist_mbid = MetadataExtractor._extract_mbid_from_comment(partial_comment, 'artist')
    print(f"✓ Artist MBID (should be None): {artist_mbid}")
    assert artist_mbid is None

    print("\n✓ Partial comment test passed!")


def test_no_mbid():
    """Test when no MBID is present in comment"""

    no_mbid_comment = "This is just a regular comment with no MBIDs"

    print("\nTesting comment with no MBIDs:")
    print(f"Comment: {no_mbid_comment}\n")

    track_mbid = MetadataExtractor._extract_mbid_from_comment(no_mbid_comment, 'track')
    print(f"✓ Track MBID (should be None): {track_mbid}")
    assert track_mbid is None

    print("\n✓ No MBID test passed!")


if __name__ == "__main__":
    print("=" * 80)
    print("Studio54 - MBID Matching Tests")
    print("=" * 80)
    print()

    try:
        test_mbid_extraction_from_comment()
        test_partial_comment()
        test_no_mbid()

        print("\n" + "=" * 80)
        print("✓ ALL TESTS PASSED!")
        print("=" * 80)

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
