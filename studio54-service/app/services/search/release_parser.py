"""
Release Parser - Parse indexer results into ReleaseInfo objects

Converts NewznabResult objects into ReleaseInfo with enhanced parsing
of quality, metadata, and release information from titles.

Based on Lidarr's parsing from:
- src/NzbDrone.Core/Parser/
"""
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple

from app.models.download_decision import ReleaseInfo
from app.services.newznab_client import NewznabResult

logger = logging.getLogger(__name__)


class ReleaseParser:
    """
    Parses indexer results into structured ReleaseInfo objects

    Provides quality detection, title parsing, and metadata extraction
    from release titles.
    """

    # Quality detection patterns (ordered by preference)
    QUALITY_PATTERNS = {
        'FLAC-24': [
            r'\b(?:FLAC.?24|24.?bit.?FLAC|Hi.?Res|24BIT|24-?BIT)\b',
            r'\b(?:96.?kHz|192.?kHz|DSD|MQA)\b',
        ],
        'FLAC': [
            r'\bFLAC\b(?!.?24)',
        ],
        'MP3-320': [
            r'\b(?:MP3.?320|320.?kbps|CBR320|320K)\b',
        ],
        'MP3-V0': [
            r'\b(?:MP3.?V0|V0|VBR.?V0)\b',
        ],
        'MP3-256': [
            r'\b(?:MP3.?256|256.?kbps|CBR256|256K)\b',
        ],
        'MP3-192': [
            r'\b(?:MP3.?192|192.?kbps|CBR192|192K)\b',
        ],
        'MP3-128': [
            r'\b(?:MP3.?128|128.?kbps|CBR128|128K)\b',
        ],
        'AAC-256': [
            r'\b(?:AAC.?256|M4A.?256|256.?AAC)\b',
        ],
        'AAC': [
            r'\b(?:AAC|M4A)\b(?!.?256)',
        ],
        'OPUS': [
            r'\bOPUS\b',
        ],
        'OGG': [
            r'\b(?:OGG|Vorbis)\b',
        ],
        'ALAC': [
            r'\b(?:ALAC|Apple.?Lossless)\b',
        ],
        'WAV': [
            r'\bWAV(?:E)?\b',
        ],
    }

    # Codec detection patterns
    CODEC_PATTERNS = {
        'FLAC': r'\bFLAC\b',
        'MP3': r'\bMP3\b',
        'AAC': r'\b(?:AAC|M4A)\b',
        'OPUS': r'\bOPUS\b',
        'OGG': r'\b(?:OGG|Vorbis)\b',
        'ALAC': r'\b(?:ALAC|Apple.?Lossless)\b',
        'WAV': r'\bWAV(?:E)?\b',
    }

    # Release group pattern (text after last hyphen)
    RELEASE_GROUP_PATTERN = r'-([A-Za-z0-9]+)(?:\s*$|\s*\[|\s*\()'

    # Year extraction pattern
    YEAR_PATTERN = r'\b((?:19|20)\d{2})\b'

    # Sample rate patterns (for high-res detection)
    SAMPLE_RATE_PATTERNS = {
        44100: r'\b44\.?1\s*k(?:Hz)?\b',
        48000: r'\b48\s*k(?:Hz)?\b',
        88200: r'\b88\.?2\s*k(?:Hz)?\b',
        96000: r'\b96\s*k(?:Hz)?\b',
        176400: r'\b176\.?4\s*k(?:Hz)?\b',
        192000: r'\b192\s*k(?:Hz)?\b',
    }

    # Bit depth patterns
    BIT_DEPTH_PATTERNS = {
        16: r'\b16[\s-]?bit\b',
        24: r'\b24[\s-]?bit\b',
        32: r'\b32[\s-]?bit\b',
    }

    # Artist/Album separator patterns
    SEPARATOR_PATTERNS = [
        r'^(.+?)\s*[-–—]\s*(.+?)(?:\s*[-–—]\s*|\s*\()',  # Artist - Album - or (year)
        r'^(.+?)\s*[-–—]\s*(.+)$',  # Artist - Album
    ]

    def __init__(self):
        """Initialize the release parser"""
        pass

    def parse(
        self,
        result: NewznabResult,
        indexer_id: str,
        indexer_name: Optional[str] = None
    ) -> ReleaseInfo:
        """
        Parse a NewznabResult into a ReleaseInfo

        Args:
            result: NewznabResult from indexer search
            indexer_id: UUID of the indexer
            indexer_name: Optional override for indexer name

        Returns:
            ReleaseInfo with parsed metadata
        """
        title = result.title
        name = indexer_name or result.indexer_name

        # Parse quality
        quality = self._detect_quality(title)
        codec = self._detect_codec(title)
        bitrate = self._detect_bitrate(title, result.bitrate)
        sample_rate = self._detect_sample_rate(title)
        bit_depth = self._detect_bit_depth(title)

        # Parse metadata
        artist_name, album_name = self._extract_artist_album(title)
        year = self._extract_year(title)
        release_group = self._extract_release_group(title)

        # Calculate age
        age_days = self._calculate_age(result.publish_date)
        publish_date = self._parse_publish_date(result.publish_date)

        return ReleaseInfo(
            title=title,
            guid=result.guid,
            indexer_id=indexer_id,
            indexer_name=name,
            download_url=result.download_url,
            info_url=result.info_url or None,
            size=result.size_bytes,
            age_days=age_days,
            publish_date=publish_date,
            quality=quality,
            codec=codec,
            bitrate=bitrate,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            artist_name=artist_name,
            album_name=album_name,
            year=year,
            release_group=release_group,
            protocol='usenet',
            categories=[result.category] if result.category else [],
        )

    def parse_dict(
        self,
        data: Dict[str, Any],
        indexer_id: str,
        indexer_name: str
    ) -> ReleaseInfo:
        """
        Parse a dictionary result (e.g., from JSON) into ReleaseInfo

        Args:
            data: Dictionary with indexer result data
            indexer_id: UUID of the indexer
            indexer_name: Name of the indexer

        Returns:
            ReleaseInfo with parsed metadata
        """
        title = data.get('title', '')

        # Parse quality
        quality = self._detect_quality(title)
        codec = self._detect_codec(title)
        bitrate = self._detect_bitrate(title, data.get('bitrate'))
        sample_rate = self._detect_sample_rate(title)
        bit_depth = self._detect_bit_depth(title)

        # Parse metadata
        artist_name, album_name = self._extract_artist_album(title)
        year = self._extract_year(title)
        release_group = self._extract_release_group(title)

        # Calculate age
        pub_date_str = data.get('pubDate') or data.get('publish_date')
        age_days = self._calculate_age(pub_date_str)
        publish_date = self._parse_publish_date(pub_date_str)

        return ReleaseInfo(
            title=title,
            guid=data.get('guid', ''),
            indexer_id=indexer_id,
            indexer_name=indexer_name,
            download_url=data.get('link', '') or data.get('download_url', ''),
            info_url=data.get('comments') or data.get('info_url'),
            size=int(data.get('size', 0) or data.get('size_bytes', 0)),
            age_days=age_days,
            publish_date=publish_date,
            quality=quality,
            codec=codec,
            bitrate=bitrate,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            artist_name=artist_name,
            album_name=album_name,
            year=year,
            release_group=release_group,
            protocol='usenet',
        )

    def _detect_quality(self, title: str) -> str:
        """
        Detect quality from release title

        Args:
            title: Release title

        Returns:
            Quality string (e.g., 'FLAC', 'MP3-320', 'Unknown')
        """
        for quality, patterns in self.QUALITY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, title, re.IGNORECASE):
                    return quality

        return 'Unknown'

    def _detect_codec(self, title: str) -> Optional[str]:
        """
        Detect codec from release title

        Args:
            title: Release title

        Returns:
            Codec string or None
        """
        for codec, pattern in self.CODEC_PATTERNS.items():
            if re.search(pattern, title, re.IGNORECASE):
                return codec
        return None

    def _detect_bitrate(self, title: str, existing_bitrate: Optional[int] = None) -> Optional[int]:
        """
        Detect bitrate from release title

        Args:
            title: Release title
            existing_bitrate: Bitrate already detected (e.g., from NewznabResult)

        Returns:
            Bitrate in kbps or None
        """
        if existing_bitrate:
            return existing_bitrate

        # Look for explicit bitrate
        match = re.search(r'(\d{3})\s*k?bps?', title, re.IGNORECASE)
        if match:
            bitrate = int(match.group(1))
            if 64 <= bitrate <= 500:  # Reasonable range
                return bitrate

        # V0, V1, V2 VBR patterns
        v_match = re.search(r'V([0-2])', title, re.IGNORECASE)
        if v_match:
            v_quality = int(v_match.group(1))
            return {0: 245, 1: 225, 2: 190}.get(v_quality)

        return None

    def _detect_sample_rate(self, title: str) -> Optional[int]:
        """
        Detect sample rate from release title

        Args:
            title: Release title

        Returns:
            Sample rate in Hz or None
        """
        for sample_rate, pattern in self.SAMPLE_RATE_PATTERNS.items():
            if re.search(pattern, title, re.IGNORECASE):
                return sample_rate
        return None

    def _detect_bit_depth(self, title: str) -> Optional[int]:
        """
        Detect bit depth from release title

        Args:
            title: Release title

        Returns:
            Bit depth or None
        """
        for bit_depth, pattern in self.BIT_DEPTH_PATTERNS.items():
            if re.search(pattern, title, re.IGNORECASE):
                return bit_depth
        return None

    def _extract_artist_album(self, title: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract artist and album from release title

        Args:
            title: Release title

        Returns:
            (artist_name, album_name) tuple
        """
        # Clean title first - remove common prefixes
        clean_title = title
        clean_title = re.sub(r'^\[.*?\]\s*', '', clean_title)  # Remove [SCENE-TAG]
        clean_title = re.sub(r'^\(.*?\)\s*', '', clean_title)  # Remove (CATEGORY)

        for pattern in self.SEPARATOR_PATTERNS:
            match = re.match(pattern, clean_title, re.IGNORECASE)
            if match:
                artist = match.group(1).strip()
                album = match.group(2).strip()

                # Clean up album name
                album = re.sub(r'\s*\(\d{4}\)\s*$', '', album)  # Remove (year)
                album = re.sub(r'\s*\[.*?\]\s*', '', album)  # Remove [tags]
                album = re.sub(r'\s*[-–—]\s*(?:FLAC|MP3|AAC|WEB|CD|Vinyl).*$', '', album, flags=re.IGNORECASE)

                # Clean up artist name
                artist = re.sub(r'\s*\(\d{4}\)\s*', '', artist)

                if artist and album:
                    return artist.strip(), album.strip()

        return None, None

    def _extract_year(self, title: str) -> Optional[int]:
        """
        Extract release year from title

        Args:
            title: Release title

        Returns:
            Year as integer or None
        """
        # Look for year in parentheses first (most reliable)
        match = re.search(r'\((\d{4})\)', title)
        if match:
            return int(match.group(1))

        # Look for standalone year
        matches = re.findall(self.YEAR_PATTERN, title)
        if matches:
            # Prefer years in range 1950-current+1
            current_year = datetime.now().year
            for year_str in matches:
                year = int(year_str)
                if 1950 <= year <= current_year + 1:
                    return year

        return None

    def _extract_release_group(self, title: str) -> Optional[str]:
        """
        Extract release group from title

        Args:
            title: Release title

        Returns:
            Release group name or None
        """
        match = re.search(self.RELEASE_GROUP_PATTERN, title)
        if match:
            group = match.group(1)
            # Filter out common false positives
            if group.upper() not in ['FLAC', 'MP3', 'AAC', 'WAV', 'WEB', 'CD', 'VINYL', 'LP']:
                return group
        return None

    def _calculate_age(self, pub_date_str: Optional[str]) -> int:
        """
        Calculate age in days from publish date

        Args:
            pub_date_str: Publication date string

        Returns:
            Age in days
        """
        if not pub_date_str:
            return 0

        pub_date = self._parse_publish_date(pub_date_str)
        if not pub_date:
            return 0

        now = datetime.now(timezone.utc)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)

        delta = now - pub_date
        return max(0, delta.days)

    def _parse_publish_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """
        Parse publish date string into datetime

        Args:
            date_str: Date string in various formats

        Returns:
            datetime or None
        """
        if not date_str:
            return None

        # Try ISO format first
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

        # Try RFC 2822 format (common in RSS)
        formats = [
            '%a, %d %b %Y %H:%M:%S %z',
            '%a, %d %b %Y %H:%M:%S %Z',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None


# Convenience function
def parse_newznab_results(
    results: List[NewznabResult],
    indexer_id: str,
    indexer_name: str
) -> List[ReleaseInfo]:
    """
    Parse a list of NewznabResults into ReleaseInfo objects

    Args:
        results: List of NewznabResult from indexer
        indexer_id: UUID of the indexer
        indexer_name: Name of the indexer

    Returns:
        List of ReleaseInfo
    """
    parser = ReleaseParser()
    return [
        parser.parse(result, indexer_id, indexer_name)
        for result in results
    ]
