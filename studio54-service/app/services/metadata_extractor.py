"""
Metadata Extraction Service
Extract metadata from audio files using mutagen
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
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


class MetadataExtractor:
    """
    Extract metadata from audio files

    Supports: MP3, FLAC, M4A/AAC, OGG, WAV, AIFF, ALAC
    """

    SUPPORTED_EXTENSIONS = {
        '.mp3', '.flac', '.m4a', '.m4b', '.aac', '.ogg', '.oga',
        '.wav', '.aiff', '.aif', '.alac', '.opus', '.wma'
    }

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """Check if file extension is supported"""
        ext = Path(file_path).suffix.lower()
        return ext in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def extract(cls, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata from audio file

        Args:
            file_path: Path to audio file

        Returns:
            Dict with extracted metadata

        Raises:
            Exception: If file cannot be read or is unsupported
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not cls.is_supported(file_path):
            raise ValueError(f"Unsupported file format: {file_path}")

        try:
            # Get file stats
            stat_info = os.stat(file_path)
            file_size = stat_info.st_size
            file_modified = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)

            # Load audio file
            audio = MutagenFile(file_path, easy=False)
            if audio is None:
                raise ValueError(f"Could not read audio file: {file_path}")

            # Extract metadata
            duration_seconds = cls._get_duration(audio)
            metadata = {
                # File info
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'file_size_bytes': file_size,
                'file_modified_at': file_modified,

                # Audio format
                'format': cls._get_format(audio, file_path),
                'bitrate_kbps': cls._get_bitrate(audio),
                'sample_rate_hz': cls._get_sample_rate(audio),
                'duration_seconds': duration_seconds,
                'duration_ms': int(duration_seconds * 1000) if duration_seconds else None,

                # Basic tags
                'title': cls._get_tag(audio, ['title', 'TIT2', '\xa9nam']),
                'artist': cls._get_tag(audio, ['artist', 'TPE1', '\xa9ART']),
                'album': cls._get_tag(audio, ['album', 'TALB', '\xa9alb']),
                'album_artist': cls._get_tag(audio, ['albumartist', 'TPE2', 'aART']),
                'track_number': cls._get_track_number(audio),
                'disc_number': cls._get_disc_number(audio),
                'year': cls._get_year(audio),
                'genre': cls._get_tag(audio, ['genre', 'TCON', '\xa9gen']),

                # MusicBrainz IDs (priority!)
                'musicbrainz_trackid': cls._get_musicbrainz_id(audio, 'track'),
                'musicbrainz_albumid': cls._get_musicbrainz_id(audio, 'album'),
                'musicbrainz_artistid': cls._get_musicbrainz_id(audio, 'artist'),
                'musicbrainz_releasegroupid': cls._get_musicbrainz_id(audio, 'releasegroup'),

                # Artwork
                'has_embedded_artwork': cls._has_artwork(audio),

                # Raw metadata (for debugging)
                'metadata_json': cls._get_all_tags(audio),
            }

            logger.debug(f"Extracted metadata from: {file_path}")
            return metadata

        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            raise

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
    def _get_bitrate(audio) -> Optional[int]:
        """Get bitrate in kbps"""
        try:
            if hasattr(audio.info, 'bitrate'):
                return int(audio.info.bitrate / 1000)
        except:
            pass
        return None

    @staticmethod
    def _get_sample_rate(audio) -> Optional[int]:
        """Get sample rate in Hz"""
        try:
            if hasattr(audio.info, 'sample_rate'):
                return int(audio.info.sample_rate)
        except:
            pass
        return None

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

        for tag_name in tag_names:
            try:
                # Try direct access
                if tag_name in audio.tags:
                    value = audio.tags[tag_name]
                    if isinstance(value, list) and len(value) > 0:
                        return str(value[0])
                    elif value:
                        return str(value)

                # Try .get() method
                value = audio.tags.get(tag_name)
                if value:
                    if isinstance(value, list) and len(value) > 0:
                        return str(value[0])
                    return str(value)
            except:
                continue

        return None

    @staticmethod
    def _get_track_number(audio) -> Optional[int]:
        """Extract track number"""
        track_tags = ['tracknumber', 'TRCK', 'trkn']
        value = MetadataExtractor._get_tag(audio, track_tags)
        if value:
            try:
                # Handle "3/12" format
                if '/' in value:
                    value = value.split('/')[0]
                return int(value)
            except:
                pass
        return None

    @staticmethod
    def _get_disc_number(audio) -> Optional[int]:
        """Extract disc number"""
        disc_tags = ['discnumber', 'TPOS', 'disk']
        value = MetadataExtractor._get_tag(audio, disc_tags)
        if value:
            try:
                if '/' in value:
                    value = value.split('/')[0]
                return int(value)
            except:
                pass
        return None

    @staticmethod
    def _get_year(audio) -> Optional[int]:
        """Extract release year"""
        year_tags = ['date', 'year', 'TDRC', 'TYER', '\xa9day']
        value = MetadataExtractor._get_tag(audio, year_tags)
        if value:
            try:
                # Handle "2023-01-15" format
                if '-' in value:
                    value = value.split('-')[0]
                # Handle "2023" format
                return int(value[:4])
            except:
                pass
        return None

    @staticmethod
    def _get_musicbrainz_id(audio, id_type: str) -> Optional[str]:
        """
        Extract MusicBrainz IDs from tags

        Priority: Use MusicBrainz IDs if available for accurate matching
        Also checks comment fields for MUSE Ponder-written MBIDs

        Args:
            audio: Mutagen audio object
            id_type: 'track', 'album', 'artist', or 'releasegroup'

        Returns:
            MusicBrainz UUID or None
        """
        tag_map = {
            'track': [
                'musicbrainz_trackid',
                'TXXX:MusicBrainz Release Track Id',
                '----:com.apple.iTunes:MusicBrainz Track Id'
            ],
            'album': [
                'musicbrainz_albumid',
                'TXXX:MusicBrainz Album Id',
                '----:com.apple.iTunes:MusicBrainz Album Id'
            ],
            'artist': [
                'musicbrainz_artistid',
                'TXXX:MusicBrainz Artist Id',
                '----:com.apple.iTunes:MusicBrainz Artist Id'
            ],
            'releasegroup': [
                'musicbrainz_releasegroupid',
                'TXXX:MusicBrainz Release Group Id',
                '----:com.apple.iTunes:MusicBrainz Release Group Id'
            ]
        }

        # Try standard MBID tags first
        tag_names = tag_map.get(id_type, [])
        value = MetadataExtractor._get_tag(audio, tag_names)

        if value:
            # Validate UUID format
            value = value.strip().lower()
            if len(value) == 36 and value.count('-') == 4:
                return value

        # If no standard MBID found, check comment field for MUSE Ponder MBIDs
        # Format: "RecordingMBID:<uuid> | ArtistMBID:<uuid> | ReleaseMBID:<uuid> | ReleaseGroupMBID:<uuid>"
        comment_value = MetadataExtractor._get_tag(audio, ['comment', 'COMM', '©cmt', '\xa9cmt'])
        if comment_value:
            mbid = MetadataExtractor._extract_mbid_from_comment(comment_value, id_type)
            if mbid:
                return mbid

        return None

    @staticmethod
    def _extract_mbid_from_comment(comment: str, id_type: str) -> Optional[str]:
        """
        Extract MBID from comment field (MUSE Ponder format)

        Format: "RecordingMBID:<uuid> | ArtistMBID:<uuid> | ReleaseMBID:<uuid> | ReleaseGroupMBID:<uuid>"

        Args:
            comment: Comment field text
            id_type: 'track', 'album', 'artist', or 'releasegroup'

        Returns:
            MusicBrainz UUID or None
        """
        # Map id_type to comment prefix
        prefix_map = {
            'track': 'RecordingMBID:',
            'album': 'ReleaseMBID:',
            'artist': 'ArtistMBID:',
            'releasegroup': 'ReleaseGroupMBID:'
        }

        prefix = prefix_map.get(id_type)
        if not prefix:
            return None

        # Look for prefix in comment
        if prefix in comment:
            # Extract the UUID after the prefix
            start_idx = comment.index(prefix) + len(prefix)
            # UUID is 36 characters long
            mbid = comment[start_idx:start_idx + 36].strip().lower()

            # Validate UUID format
            if len(mbid) == 36 and mbid.count('-') == 4:
                return mbid

        return None

    @staticmethod
    def _has_artwork(audio) -> bool:
        """Check if file has embedded artwork"""
        try:
            if isinstance(audio, MP3):
                # Check for APIC frames
                if audio.tags:
                    for key in audio.tags.keys():
                        if key.startswith('APIC'):
                            return True
            elif isinstance(audio, FLAC):
                return len(audio.pictures) > 0
            elif isinstance(audio, MP4):
                return 'covr' in audio.tags if audio.tags else False
            elif isinstance(audio, OggVorbis):
                if audio.tags:
                    return 'metadata_block_picture' in audio.tags or 'coverart' in audio.tags
        except:
            pass
        return False

    @staticmethod
    def _get_all_tags(audio) -> Dict[str, Any]:
        """Get all tags as dictionary for JSON storage"""
        def sanitize_string(s: str) -> str:
            """Remove null bytes and other problematic characters for PostgreSQL"""
            # Remove null bytes (\x00) and other control characters that break JSON/PostgreSQL
            return ''.join(char for char in s if ord(char) >= 32 or char in '\n\r\t')

        def to_str(v):
            """Convert tag value to string, handling MP4 freeform bytes."""
            if isinstance(v, bytes):
                return sanitize_string(v.decode('utf-8', errors='replace'))
            return sanitize_string(str(v))

        tags_dict = {}
        if audio.tags:
            try:
                for key in audio.tags.keys():
                    value = audio.tags[key]
                    if isinstance(value, list):
                        tags_dict[str(key)] = [to_str(v) for v in value]
                    else:
                        tags_dict[str(key)] = to_str(value)
            except:
                pass

        # Normalize known MP4 freeform atoms to simple keys for audiobook metadata.
        # detect_and_create_series looks for metadata_json['series'], etc.
        _MP4_KEY_MAP = {
            '----:com.apple.iTunes:SERIES': 'series',
            '----:com.apple.iTunes:SERIES-PART': 'series_part',
            '----:com.apple.iTunes:SERIESPART': 'series_part',
            '----:com.apple.iTunes:ASIN': 'asin',
            '----:com.audible.com:asin': 'asin',
        }
        for mp4_key, simple_key in _MP4_KEY_MAP.items():
            if mp4_key in tags_dict and simple_key not in tags_dict:
                val = tags_dict[mp4_key]
                # MP4 freeform values are stored as lists; take first element
                if isinstance(val, list) and val:
                    tags_dict[simple_key] = val[0]
                else:
                    tags_dict[simple_key] = val

        return tags_dict


# Convenience function
def extract_metadata(file_path: str) -> Dict[str, Any]:
    """
    Extract metadata from audio file

    Args:
        file_path: Path to audio file

    Returns:
        Dict with metadata
    """
    return MetadataExtractor.extract(file_path)
