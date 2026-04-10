"""
MBID Confidence Scorer Service
Calculate confidence scores for MusicBrainz matches.

Evaluates matches based on:
- Title similarity (0-40 points)
- Artist similarity (0-30 points)
- Album similarity (0-15 points)
- Duration match (0-15 points)

Total score: 0-100 points
- 90+: High confidence (auto-accept)
- 70-89: Medium confidence (acceptable)
- 50-69: Low confidence (needs review)
- <50: Very low confidence (likely wrong)
"""
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class MBIDConfidenceScorer:
    """
    Calculate confidence scores for MusicBrainz recording matches.

    Used to evaluate the quality of matches before accepting them.
    """

    # Score thresholds
    HIGH_CONFIDENCE = 90
    MEDIUM_CONFIDENCE = 70
    LOW_CONFIDENCE = 50

    # Maximum score weights
    TITLE_WEIGHT = 40
    ARTIST_WEIGHT = 30
    ALBUM_WEIGHT = 15
    DURATION_WEIGHT = 15

    # Duration tolerance in seconds
    DURATION_EXACT_TOLERANCE = 1  # ±1 second for full points
    DURATION_CLOSE_TOLERANCE = 5  # ±5 seconds for partial points
    DURATION_MAX_TOLERANCE = 15   # Beyond this, 0 points

    @classmethod
    def score_match(
        cls,
        file_metadata: Dict[str, Any],
        mb_recording: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate confidence score for a MusicBrainz recording match.

        Args:
            file_metadata: Metadata extracted from file
                - title: str
                - artist: str
                - album: str (optional)
                - duration: int (seconds, optional)
            mb_recording: MusicBrainz recording data
                - title: str
                - artist-credit: list of artist credit dicts
                - releases: list of release dicts (optional)
                - length: int (milliseconds)

        Returns:
            Dict with:
                - total_score: int (0-100)
                - confidence_level: str (high/medium/low/very_low)
                - breakdown: dict with individual scores
                - recording_mbid: str
                - recommendation: str
        """
        breakdown = {}

        # Extract comparable values
        file_title = file_metadata.get('title', '')
        file_artist = file_metadata.get('artist', '')
        file_album = file_metadata.get('album', '')
        file_duration = file_metadata.get('duration')

        mb_title = mb_recording.get('title', '')
        mb_length_ms = mb_recording.get('length', 0)
        mb_duration = mb_length_ms // 1000 if mb_length_ms else None

        # Extract artist from artist-credit
        artist_credits = mb_recording.get('artist-credit', [])
        mb_artist = ''
        if artist_credits:
            # Combine all artists with their join phrases
            parts = []
            for credit in artist_credits:
                if isinstance(credit, dict):
                    artist_name = credit.get('artist', {}).get('name', '') or credit.get('name', '')
                    join_phrase = credit.get('joinphrase', '')
                    parts.append(artist_name + join_phrase)
                elif isinstance(credit, str):
                    parts.append(credit)
            mb_artist = ''.join(parts)

        # Extract album from releases
        releases = mb_recording.get('releases', [])
        mb_album = ''
        if releases:
            mb_album = releases[0].get('title', '')

        # Calculate individual scores
        title_score = cls._score_similarity(file_title, mb_title, cls.TITLE_WEIGHT)
        breakdown['title'] = {
            'score': title_score,
            'max': cls.TITLE_WEIGHT,
            'file': file_title,
            'mb': mb_title
        }

        artist_score = cls._score_similarity(file_artist, mb_artist, cls.ARTIST_WEIGHT)
        breakdown['artist'] = {
            'score': artist_score,
            'max': cls.ARTIST_WEIGHT,
            'file': file_artist,
            'mb': mb_artist
        }

        album_score = 0
        if file_album and mb_album:
            album_score = cls._score_similarity(file_album, mb_album, cls.ALBUM_WEIGHT)
        elif not file_album:
            # No album in file, give partial credit if MB has album
            album_score = cls.ALBUM_WEIGHT * 0.5 if mb_album else 0
        breakdown['album'] = {
            'score': album_score,
            'max': cls.ALBUM_WEIGHT,
            'file': file_album or '(none)',
            'mb': mb_album or '(none)'
        }

        duration_score = cls._score_duration(file_duration, mb_duration)
        breakdown['duration'] = {
            'score': duration_score,
            'max': cls.DURATION_WEIGHT,
            'file': file_duration,
            'mb': mb_duration,
            'difference': abs(file_duration - mb_duration) if file_duration and mb_duration else None
        }

        # Calculate total
        total_score = title_score + artist_score + album_score + duration_score
        total_score = min(100, max(0, int(total_score)))

        # Determine confidence level
        if total_score >= cls.HIGH_CONFIDENCE:
            confidence_level = 'high'
            recommendation = 'Auto-accept recommended'
        elif total_score >= cls.MEDIUM_CONFIDENCE:
            confidence_level = 'medium'
            recommendation = 'Acceptable match'
        elif total_score >= cls.LOW_CONFIDENCE:
            confidence_level = 'low'
            recommendation = 'Needs manual review'
        else:
            confidence_level = 'very_low'
            recommendation = 'Likely incorrect - skip or review'

        return {
            'total_score': total_score,
            'confidence_level': confidence_level,
            'breakdown': breakdown,
            'recording_mbid': mb_recording.get('id'),
            'artist_mbid': artist_credits[0].get('artist', {}).get('id') if artist_credits else None,
            'release_mbid': releases[0].get('id') if releases else None,
            'recommendation': recommendation
        }

    @classmethod
    def score_all_matches(
        cls,
        file_metadata: Dict[str, Any],
        mb_recordings: List[Dict[str, Any]],
        min_score: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Score all MusicBrainz matches and return sorted by confidence.

        Args:
            file_metadata: Metadata from file
            mb_recordings: List of MusicBrainz recording results
            min_score: Minimum score to include (default 50)

        Returns:
            List of scored matches, sorted by score descending
        """
        scored = []
        for recording in mb_recordings:
            try:
                result = cls.score_match(file_metadata, recording)
                if result['total_score'] >= min_score:
                    scored.append(result)
            except Exception as e:
                logger.warning(f"Error scoring recording {recording.get('id')}: {e}")

        # Sort by score descending
        scored.sort(key=lambda x: x['total_score'], reverse=True)
        return scored

    @classmethod
    def get_best_match(
        cls,
        file_metadata: Dict[str, Any],
        mb_recordings: List[Dict[str, Any]],
        min_score: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Get the best matching recording above minimum score.

        Args:
            file_metadata: Metadata from file
            mb_recordings: List of MusicBrainz recording results
            min_score: Minimum acceptable score (default 50)

        Returns:
            Best scored match, or None if no match above threshold
        """
        scored = cls.score_all_matches(file_metadata, mb_recordings, min_score)
        return scored[0] if scored else None

    @classmethod
    def _score_similarity(cls, str1: str, str2: str, max_score: float) -> float:
        """
        Calculate similarity score between two strings.

        Uses normalized strings and SequenceMatcher for fuzzy matching.

        Args:
            str1: First string
            str2: Second string
            max_score: Maximum score for this field

        Returns:
            Score between 0 and max_score
        """
        if not str1 or not str2:
            return 0.0

        # Normalize strings
        norm1 = cls._normalize_string(str1)
        norm2 = cls._normalize_string(str2)

        # Exact match (normalized)
        if norm1 == norm2:
            return max_score

        # Fuzzy match
        ratio = SequenceMatcher(None, norm1, norm2).ratio()

        # Apply scoring curve - reward high matches more
        if ratio >= 0.95:
            return max_score
        elif ratio >= 0.9:
            return max_score * 0.95
        elif ratio >= 0.8:
            return max_score * 0.85
        elif ratio >= 0.7:
            return max_score * 0.7
        elif ratio >= 0.6:
            return max_score * 0.5
        elif ratio >= 0.5:
            return max_score * 0.3
        else:
            return max_score * ratio * 0.5

    @classmethod
    def _normalize_string(cls, s: str) -> str:
        """
        Normalize string for comparison.

        Lowercases, removes common variations, standardizes punctuation.
        """
        if not s:
            return ''

        # Lowercase
        result = s.lower()

        # Remove common prefixes/suffixes
        result = re.sub(r'\s*\(feat\.?\s+[^)]+\)', '', result)
        result = re.sub(r'\s*\[feat\.?\s+[^\]]+\]', '', result)
        result = re.sub(r'\s*ft\.?\s+.*$', '', result)
        result = re.sub(r'\s*featuring\s+.*$', '', result, flags=re.IGNORECASE)

        # Remove common suffixes
        result = re.sub(r'\s*-?\s*remaster(ed)?\s*(version|edition)?.*$', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*-?\s*bonus\s*track.*$', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*-?\s*radio\s*edit.*$', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*-?\s*album\s*version.*$', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*-?\s*single\s*version.*$', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*-?\s*explicit.*$', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*-?\s*clean.*$', '', result, flags=re.IGNORECASE)

        # Standardize punctuation - remove various quote styles
        # Using explicit Unicode escapes to avoid encoding issues
        # U+0027 ' APOSTROPHE, U+0022 " QUOTATION MARK
        # U+2018 ' LEFT SINGLE QUOTATION MARK, U+2019 ' RIGHT SINGLE QUOTATION MARK
        # U+201C " LEFT DOUBLE QUOTATION MARK, U+201D " RIGHT DOUBLE QUOTATION MARK
        # U+00B4 ´ ACUTE ACCENT, U+0060 ` GRAVE ACCENT
        result = re.sub(r'[\u0027\u0022\u2018\u2019\u201C\u201D\u00B4\u0060]', '', result)
        # U+2013 – EN DASH, U+2014 — EM DASH
        result = re.sub(r'[\u2013\u2014]', '-', result)
        result = re.sub(r'\s*-\s*', ' ', result)
        result = re.sub(r'&', ' and ', result)

        # Remove extra whitespace
        result = re.sub(r'\s+', ' ', result).strip()

        return result

    @classmethod
    def _score_duration(cls, file_duration: Optional[int], mb_duration: Optional[int]) -> float:
        """
        Score duration match.

        Args:
            file_duration: File duration in seconds
            mb_duration: MusicBrainz duration in seconds

        Returns:
            Score between 0 and DURATION_WEIGHT
        """
        if file_duration is None or mb_duration is None:
            # No duration info, give partial credit
            return cls.DURATION_WEIGHT * 0.5

        diff = abs(file_duration - mb_duration)

        if diff <= cls.DURATION_EXACT_TOLERANCE:
            return cls.DURATION_WEIGHT
        elif diff <= cls.DURATION_CLOSE_TOLERANCE:
            # Linear scale from 100% to 75%
            return cls.DURATION_WEIGHT * (1.0 - (diff - cls.DURATION_EXACT_TOLERANCE) / cls.DURATION_CLOSE_TOLERANCE * 0.25)
        elif diff <= cls.DURATION_MAX_TOLERANCE:
            # Linear scale from 75% to 25%
            return cls.DURATION_WEIGHT * (0.75 - (diff - cls.DURATION_CLOSE_TOLERANCE) / (cls.DURATION_MAX_TOLERANCE - cls.DURATION_CLOSE_TOLERANCE) * 0.5)
        else:
            # Beyond tolerance - significant penalty
            return cls.DURATION_WEIGHT * 0.1


def calculate_match_confidence(
    file_metadata: Dict[str, Any],
    mb_recording: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Convenience function to calculate match confidence.

    Args:
        file_metadata: Metadata from file (title, artist, album, duration)
        mb_recording: MusicBrainz recording result

    Returns:
        Score result with total_score, confidence_level, breakdown
    """
    return MBIDConfidenceScorer.score_match(file_metadata, mb_recording)


def get_best_match_with_confidence(
    file_metadata: Dict[str, Any],
    mb_recordings: List[Dict[str, Any]],
    min_confidence: int = 50
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to get best match above minimum confidence.

    Args:
        file_metadata: Metadata from file
        mb_recordings: List of MusicBrainz recording results
        min_confidence: Minimum confidence score (default 50)

    Returns:
        Best match or None
    """
    return MBIDConfidenceScorer.get_best_match(file_metadata, mb_recordings, min_confidence)
