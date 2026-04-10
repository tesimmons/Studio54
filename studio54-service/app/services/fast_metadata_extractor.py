"""
Fast Metadata Extraction Service for V2 Scanner (Phase 1)
Extract minimal metadata for fast library ingestion

Based on MUSE V2 fast ingestion approach:
- Minimal fields only (artist, title, album, duration, format)
- NUL byte sanitization for PostgreSQL compatibility
- File validation (skip resource forks, hidden files, system files)
- Skip statistics tracking
- 20-30x faster than full metadata extraction
"""
import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

try:
    from mutagen import File as MutagenFile
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wave import WAVE
    from mutagen.aiff import AIFF
except ImportError:
    raise ImportError("mutagen library is required. Install with: pip install mutagen")

logger = logging.getLogger(__name__)


class FastMetadataExtractor:
    """
    Fast metadata extractor for V2 scanner Phase 1

    Extracts only essential fields for quick database ingestion:
    - File info (path, size, modified_at)
    - Format (MP3, FLAC, etc.)
    - Duration
    - Basic tags (artist, title, album)

    Also extracts (cheap, critical for MBID matching in Phase 3):
    - Comment tag (contains MUSE Ponder MBIDs)
    - MusicBrainz IDs parsed from comment

    Skips expensive operations:
    - Full tag extraction (metadata_json)
    - Artwork detection
    - Bitrate/sample rate (done in Phase 2)
    """

    SUPPORTED_EXTENSIONS = {
        '.mp3', '.flac', '.m4a', '.m4b', '.aac', '.ogg', '.oga',
        '.wav', '.aiff', '.aif', '.alac', '.opus', '.wma'
    }

    # System files to skip
    SYSTEM_FILES = {
        'thumbs.db', '.ds_store', 'desktop.ini',
        '.localized', '.hidden', '.nomedia'
    }

    @classmethod
    def sanitize_string(cls, value: Optional[str]) -> Optional[str]:
        """
        Remove NUL bytes and control characters that PostgreSQL cannot store

        Critical for preventing database errors on corrupted metadata

        Args:
            value: String to sanitize

        Returns:
            Sanitized string or None
        """
        if value is None:
            return None

        # Remove NUL bytes (\x00) - PostgreSQL cannot store these
        sanitized = value.replace('\x00', '')

        # Remove other control characters except newline, tab, carriage return
        sanitized = ''.join(
            char for char in sanitized
            if ord(char) >= 32 or char in '\n\r\t'
        )

        return sanitized.strip() if sanitized.strip() else None

    @classmethod
    def should_skip_file(cls, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Check if file should be skipped before processing

        Returns:
            (should_skip: bool, reason: Optional[str])

        Skip reasons:
        - resource_fork: macOS resource fork (._filename)
        - hidden: Hidden file (.filename)
        - system: System file (Thumbs.db, .DS_Store, etc.)
        - unsupported: Unsupported file format
        """
        filename = os.path.basename(file_path)
        filename_lower = filename.lower()

        # Skip macOS resource forks
        if filename.startswith('._'):
            return True, 'resource_fork'

        # Skip hidden files
        if filename.startswith('.'):
            return True, 'hidden'

        # Skip system files
        if filename_lower in cls.SYSTEM_FILES:
            return True, 'system'

        # Check file extension
        ext = Path(file_path).suffix.lower()
        if ext not in cls.SUPPORTED_EXTENSIONS:
            return True, 'unsupported'

        return False, None

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """Check if file extension is supported"""
        ext = Path(file_path).suffix.lower()
        return ext in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def extract_fast(cls, file_path: str) -> Dict[str, Any]:
        """
        Extract minimal metadata for Phase 1 fast ingestion

        Args:
            file_path: Path to audio file

        Returns:
            Dict with minimal metadata

        Raises:
            Exception: If file cannot be read or is unsupported
        """
        # Validate file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check if should skip
        should_skip, reason = cls.should_skip_file(file_path)
        if should_skip:
            raise ValueError(f"File should be skipped ({reason}): {file_path}")

        try:
            # Get file stats
            stat_info = os.stat(file_path)
            file_size = stat_info.st_size
            file_modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)

            # Load audio file
            audio = MutagenFile(file_path, easy=False)
            if audio is None:
                raise ValueError(f"Could not read audio file: {file_path}")

            # Extract minimal metadata (Phase 1 only)
            metadata = {
                # File info
                'file_path': cls.sanitize_string(file_path),
                'file_name': cls.sanitize_string(os.path.basename(file_path)),
                'file_size_bytes': file_size,
                'file_modified_at': file_modified,

                # Audio format
                'format': cls._get_format(audio, file_path),
                'duration_seconds': cls._get_duration(audio),

                # Minimal tags (searchable fields only)
                'title': cls.sanitize_string(cls._get_tag(audio, ['title', 'TIT2', '\xa9nam'])),
                'artist': cls.sanitize_string(cls._get_tag(audio, ['artist', 'TPE1', '\xa9ART'])),
                'album': cls.sanitize_string(cls._get_tag(audio, ['album', 'TALB', '\xa9alb'])),

                # Additional tags (cheap to extract, needed for metadata-based matching)
                'album_artist': cls.sanitize_string(cls._get_tag(audio, ['albumartist', 'TPE2', 'aART'])),
                'track_number': cls._parse_int_tag(cls._get_tag(audio, ['tracknumber', 'TRCK', 'trkn'])),
                'disc_number': cls._parse_int_tag(cls._get_tag(audio, ['discnumber', 'TPOS', 'disk'])),

                # Phase 2 fields (set to None for now)
                'year': None,
                'genre': None,
                'bitrate_kbps': None,
                'sample_rate_hz': None,
                'has_embedded_artwork': False,
                'album_art_fetched': False,
                'album_art_url': None,
                'artist_image_fetched': False,
                'artist_image_url': None,
            }

            # Extract comment tag and MBIDs (cheap, critical for Phase 3 MBID matching)
            comment = cls.sanitize_string(cls._get_tag(audio, [
                'comment', 'COMM', '\xa9cmt', '©cmt',
                'COMM::eng', 'COMM::\x00\x00\x00',
            ]))
            # Also try COMM frames with description for ID3
            if not comment and audio.tags:
                for key in audio.tags:
                    if str(key).startswith('COMM:'):
                        val = audio.tags[key]
                        text = str(val) if not isinstance(val, list) else str(val[0]) if val else None
                        if text and 'MBID' in text.upper():
                            comment = cls.sanitize_string(text)
                            break

            # Parse MBIDs from comment (MUSE Ponder format: RecordingMBID:<uuid> | ...)
            mbids = cls._parse_mbids_from_comment(comment) if comment else {}

            # Build metadata_json with comment and audiobook-specific tags
            metadata_json = {}
            if comment:
                metadata_json['comment'] = comment

            # Extract audiobook-specific tags (cheap, useful for metadata-based import)
            narrator = cls.sanitize_string(
                cls._get_tag(audio, ['narrated_by', 'composer', 'TCOM', '\xa9nrt', '©nrt'])
            )
            series = cls.sanitize_string(
                cls._get_tag(audio, [
                    'SERIES', 'series', 'TXXX:SERIES',
                    '----:com.apple.iTunes:SERIES',
                ])
            )
            series_part = cls.sanitize_string(
                cls._get_tag(audio, [
                    'SERIES-PART', 'series-part', 'TXXX:SERIES-PART',
                    '----:com.apple.iTunes:SERIES-PART',
                    '----:com.apple.iTunes:SERIESPART',
                ])
            )
            asin = cls.sanitize_string(
                cls._get_tag(audio, [
                    'asin', 'ASIN', 'TXXX:ASIN', 'CDEK',
                    '----:com.apple.iTunes:ASIN',
                    '----:com.audible.com:asin',
                ])
            )
            if narrator:
                metadata_json['narrator'] = narrator
            if series:
                metadata_json['series'] = series
            if series_part:
                metadata_json['series_part'] = series_part
            if asin:
                metadata_json['asin'] = asin

            metadata.update({
                'musicbrainz_trackid': mbids.get('recording_mbid'),
                'musicbrainz_albumid': mbids.get('release_mbid'),
                'musicbrainz_artistid': mbids.get('artist_mbid'),
                'musicbrainz_releasegroupid': mbids.get('release_group_mbid'),
                'mbid_in_file': bool(mbids.get('recording_mbid')),
                'metadata_json': metadata_json if metadata_json else None,
            })

            logger.debug(f"⚡ Fast extracted: {file_path}")
            return metadata

        except Exception as e:
            logger.error(f"❌ Error extracting metadata from {file_path}: {e}")
            raise

    @staticmethod
    def _parse_mbids_from_comment(comment: str) -> Dict[str, Optional[str]]:
        """
        Parse MBIDs from MUSE Ponder comment field format:
        RecordingMBID:<uuid> | ArtistMBID:<uuid> | ReleaseMBID:<uuid> | ReleaseGroupMBID:<uuid>
        """
        if not comment:
            return {}

        result = {}
        recording = re.search(r'RecordingMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if recording:
            result['recording_mbid'] = recording.group(1)

        artist = re.search(r'ArtistMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if artist:
            result['artist_mbid'] = artist.group(1)

        release = re.search(r'ReleaseMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if release:
            result['release_mbid'] = release.group(1)

        release_group = re.search(r'ReleaseGroupMBID:([a-f0-9-]{36})', comment, re.IGNORECASE)
        if release_group:
            result['release_group_mbid'] = release_group.group(1)

        return result

    @staticmethod
    def _parse_int_tag(value: Optional[str]) -> Optional[int]:
        """
        Parse an integer from a tag value, handling formats like "3/12" (track 3 of 12)
        """
        if not value:
            return None
        try:
            # Handle "3/12" format (common for track/disc numbers)
            return int(str(value).split('/')[0].strip())
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _get_format(audio, file_path: str) -> str:
        """Determine audio format"""
        if isinstance(audio, MP3):
            return 'MP3'
        elif isinstance(audio, FLAC):
            return 'FLAC'
        elif isinstance(audio, MP4):
            return 'M4A'
        elif isinstance(audio, OggVorbis):
            return 'OGG'
        elif isinstance(audio, WAVE):
            return 'WAV'
        elif isinstance(audio, AIFF):
            return 'AIFF'
        else:
            ext = Path(file_path).suffix.upper().lstrip('.')
            return ext if ext else 'UNKNOWN'

    @staticmethod
    def _get_duration(audio) -> Optional[int]:
        """Get duration in seconds"""
        try:
            if hasattr(audio.info, 'length'):
                return int(audio.info.length)
        except:
            pass
        return None

    @staticmethod
    def _get_tag(audio, tag_names: list) -> Optional[str]:
        """
        Get tag value from multiple possible tag names

        Args:
            audio: Mutagen audio object
            tag_names: List of possible tag names (ID3, Vorbis, MP4, etc.)

        Returns:
            Tag value as string or None
        """
        if audio.tags is None:
            return None

        def _to_str(val):
            """Convert tag value to string, handling MP4 freeform bytes."""
            if isinstance(val, bytes):
                return val.decode('utf-8', errors='replace')
            return str(val)

        for tag_name in tag_names:
            try:
                # Try direct access
                if tag_name in audio.tags:
                    value = audio.tags[tag_name]
                    if isinstance(value, list) and len(value) > 0:
                        return _to_str(value[0])
                    elif value:
                        return _to_str(value)

                # Try .get() method
                value = audio.tags.get(tag_name)
                if value:
                    if isinstance(value, list) and len(value) > 0:
                        return _to_str(value[0])
                    return _to_str(value)
            except:
                continue

        return None


# Convenience function
def extract_metadata_fast(file_path: str) -> Dict[str, Any]:
    """
    Extract minimal metadata from audio file (Phase 1)

    Args:
        file_path: Path to audio file

    Returns:
        Dict with minimal metadata
    """
    return FastMetadataExtractor.extract_fast(file_path)
