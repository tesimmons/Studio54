"""
Naming Engine Service

Generates consistent, template-based filenames and directory names:
- Template parsing with tokens
- Filesystem-safe sanitization
- Multi-disc album support
- Compilation album support
- Unicode normalization
- Length limits
"""

import re
import unicodedata
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class TrackContext:
    """Context for track naming"""
    artist_name: str
    album_title: str
    track_title: str
    track_number: int
    release_year: Optional[int] = None
    disc_number: Optional[int] = 1
    total_discs: Optional[int] = 1
    medium_format: Optional[str] = "CD"  # CD, Vinyl, Digital, etc.
    album_type: Optional[str] = "Album"  # Album, EP, Single, Compilation
    file_extension: Optional[str] = "flac"
    is_compilation: bool = False
    compilation_artist: Optional[str] = None  # For Various Artists


@dataclass
class AlbumContext:
    """Context for album directory naming"""
    album_title: str
    artist_name: str
    release_year: Optional[int] = None
    album_type: Optional[str] = "Album"


@dataclass
class ArtistContext:
    """Context for artist directory naming"""
    artist_name: str


class NamingEngine:
    """
    Service for generating consistent filenames using templates

    Supported tokens:
    - {Artist Name} - Artist name
    - {Album Title} - Album title
    - {Track Title} - Track title
    - {Release Year} - Album release year
    - {track:00} - Track number (zero-padded)
    - {medium:00} - Disc/medium number
    - {Medium Format} - CD, Vinyl, Digital, etc.
    - {Album Type} - Album, EP, Single, Compilation
    - {ext} - File extension
    """

    # Default templates
    DEFAULT_TRACK_TEMPLATE = "{Artist Name}/{Album Title} ({Release Year})/{track:00} - {Track Title}.{ext}"
    DEFAULT_MULTI_DISC_TEMPLATE = "{Artist Name}/{Album Title} ({Release Year})/{Medium Format} {medium:00}/{track:00} - {Track Title}.{ext}"
    DEFAULT_COMPILATION_TEMPLATE = "Various Artists/{Album Title} ({Release Year})/{track:00} - {Artist Name} - {Track Title}.{ext}"
    DEFAULT_ARTIST_TEMPLATE = "{Artist Name}"
    DEFAULT_ALBUM_TEMPLATE = "{Album Title} ({Release Year})"

    # Invalid filesystem characters (will be replaced with _)
    # Note: / is NOT included here because it's used as path separator
    INVALID_CHARS = r'[<>:"\\|?*\x00-\x1f]'

    # Maximum filename length (most filesystems support 255)
    MAX_FILENAME_LENGTH = 255

    def __init__(
        self,
        track_template: Optional[str] = None,
        multi_disc_template: Optional[str] = None,
        compilation_template: Optional[str] = None,
        artist_template: Optional[str] = None,
        album_template: Optional[str] = None
    ):
        """
        Initialize NamingEngine with custom templates

        Args:
            track_template: Template for single-disc track filenames
            multi_disc_template: Template for multi-disc track filenames
            compilation_template: Template for compilation track filenames
            artist_template: Template for artist directory names
            album_template: Template for album directory names
        """
        self.track_template = track_template or self.DEFAULT_TRACK_TEMPLATE
        self.multi_disc_template = multi_disc_template or self.DEFAULT_MULTI_DISC_TEMPLATE
        self.compilation_template = compilation_template or self.DEFAULT_COMPILATION_TEMPLATE
        self.artist_template = artist_template or self.DEFAULT_ARTIST_TEMPLATE
        self.album_template = album_template or self.DEFAULT_ALBUM_TEMPLATE

        logger.info("NamingEngine initialized with custom templates")

    def generate_track_filename(
        self,
        context: TrackContext,
        template: Optional[str] = None
    ) -> str:
        """
        Generate filename for a track

        Args:
            context: Track context with all metadata
            template: Optional custom template (overrides defaults)

        Returns:
            Sanitized filename
        """
        # Select appropriate template
        if template:
            selected_template = template
        elif context.is_compilation:
            selected_template = self.compilation_template
        elif context.total_discs and context.total_discs > 1:
            selected_template = self.multi_disc_template
        else:
            selected_template = self.track_template

        # Build token mapping
        tokens = {
            'Artist Name': context.artist_name,
            'Album Title': context.album_title,
            'Track Title': context.track_title,
            'Release Year': str(context.release_year) if context.release_year else "Unknown",
            'track:00': f"{context.track_number:02d}",
            'track:000': f"{context.track_number:03d}",
            'medium:00': f"{context.disc_number:02d}" if context.disc_number else "01",
            'Medium Format': context.medium_format or "CD",
            'Album Type': context.album_type or "Album",
            'ext': context.file_extension or "flac"
        }

        # Parse template
        filename = self._parse_template(selected_template, tokens)

        # Sanitize
        filename = self.sanitize_filename(filename)

        logger.debug(f"Generated track filename: {filename}")

        return filename

    def generate_album_directory(
        self,
        context: AlbumContext,
        template: Optional[str] = None
    ) -> str:
        """
        Generate album directory name

        Args:
            context: Album context with metadata
            template: Optional custom template

        Returns:
            Sanitized directory name
        """
        selected_template = template or self.album_template

        tokens = {
            'Album Title': context.album_title,
            'Artist Name': context.artist_name,
            'Release Year': str(context.release_year) if context.release_year else "Unknown",
            'Album Type': context.album_type or "Album"
        }

        directory_name = self._parse_template(selected_template, tokens)
        directory_name = self.sanitize_filename(directory_name)

        logger.debug(f"Generated album directory: {directory_name}")

        return directory_name

    def generate_artist_directory(
        self,
        context: ArtistContext,
        template: Optional[str] = None
    ) -> str:
        """
        Generate artist directory name

        Args:
            context: Artist context with metadata
            template: Optional custom template

        Returns:
            Sanitized directory name
        """
        selected_template = template or self.artist_template

        tokens = {
            'Artist Name': context.artist_name
        }

        directory_name = self._parse_template(selected_template, tokens)
        directory_name = self.sanitize_filename(directory_name)

        logger.debug(f"Generated artist directory: {directory_name}")

        return directory_name

    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for filesystem compatibility

        Rules:
        1. Replace invalid characters with _
        2. Normalize Unicode (NFC)
        3. Trim leading/trailing spaces and dots
        4. Collapse multiple spaces
        5. Truncate to max length
        6. Remove control characters

        Args:
            filename: Raw filename

        Returns:
            Sanitized filename
        """
        # Unicode normalization (NFC)
        filename = unicodedata.normalize('NFC', filename)

        # Replace invalid filesystem characters
        filename = re.sub(self.INVALID_CHARS, '_', filename)

        # Remove control characters
        filename = ''.join(char for char in filename if unicodedata.category(char)[0] != 'C')

        # Collapse multiple spaces
        filename = re.sub(r'\s+', ' ', filename)

        # Trim leading/trailing spaces and dots
        filename = filename.strip(' .')

        # Handle path separators (/) for nested structures
        parts = filename.split('/')
        sanitized_parts = []

        for part in parts:
            # Trim each part
            part = part.strip(' .')

            # Truncate if needed (preserve extension for files)
            if '.' in part and len(parts) == len(parts):  # Likely a filename
                name, ext = part.rsplit('.', 1)
                if len(part) > self.MAX_FILENAME_LENGTH:
                    # Truncate name, preserve extension
                    max_name_length = self.MAX_FILENAME_LENGTH - len(ext) - 4  # -4 for "..." + "."
                    name = name[:max_name_length] + "..."
                    part = f"{name}.{ext}"
            else:
                # Directory or filename without extension
                if len(part) > self.MAX_FILENAME_LENGTH:
                    part = part[:self.MAX_FILENAME_LENGTH - 3] + "..."

            sanitized_parts.append(part)

        filename = '/'.join(sanitized_parts)

        return filename

    def parse_track_number(self, track_str: str) -> Optional[int]:
        """
        Parse track number from various formats

        Handles:
        - Simple numbers: "1", "12"
        - Zero-padded: "01", "012"
        - With labels: "Track 5", "No. 3"
        - With totals: "3/12", "03 of 12"

        Args:
            track_str: Track number string

        Returns:
            Integer track number or None
        """
        # Remove common labels
        track_str = re.sub(r'(?i)(track|no\.?|number|#)\s*', '', track_str)

        # Extract number before slash or "of"
        match = re.search(r'(\d+)\s*[/of]\s*\d+', track_str)
        if match:
            return int(match.group(1))

        # Extract simple number
        match = re.search(r'(\d+)', track_str)
        if match:
            return int(match.group(1))

        return None

    def normalize_artist_name(self, artist_name: str) -> str:
        """
        Normalize artist name for consistent sorting

        Handles "The Beatles" vs "Beatles, The" style variations

        Args:
            artist_name: Raw artist name

        Returns:
            Normalized artist name
        """
        # Handle "Artist, The" format
        match = re.match(r'^(.+),\s*(The|A|An)$', artist_name, re.IGNORECASE)
        if match:
            article = match.group(2)
            name = match.group(1)
            return f"{article} {name}"

        return artist_name

    def split_extension(self, filename: str) -> tuple[str, str]:
        """
        Split filename into name and extension

        Args:
            filename: Filename with extension

        Returns:
            Tuple of (name, extension)
        """
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            return (name, ext)
        return (filename, '')

    def _parse_template(self, template: str, tokens: Dict[str, str]) -> str:
        """
        Parse template string with token replacement

        Args:
            template: Template string with {tokens}
            tokens: Dict mapping token names to values

        Returns:
            Parsed string
        """
        result = template

        # Replace each token
        for token_name, token_value in tokens.items():
            # Escape special regex characters in token name
            pattern = re.escape(f"{{{token_name}}}")
            result = re.sub(pattern, str(token_value), result)

        # Handle any remaining unreplaced tokens by removing them
        result = re.sub(r'\{[^}]+\}', '', result)

        return result

    def validate_template(self, template: str) -> tuple[bool, Optional[str]]:
        """
        Validate a template string

        Args:
            template: Template to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for unclosed braces
        open_braces = template.count('{')
        close_braces = template.count('}')

        if open_braces != close_braces:
            return (False, "Mismatched braces in template")

        # Check for valid token names
        tokens = re.findall(r'\{([^}]+)\}', template)
        valid_tokens = {
            'Artist Name', 'Album Title', 'Track Title', 'Release Year',
            'track:00', 'track:000', 'medium:00', 'Medium Format',
            'Album Type', 'ext'
        }

        for token in tokens:
            if token not in valid_tokens:
                return (False, f"Invalid token: {{{token}}}")

        return (True, None)

    def get_safe_filename(self, unsafe_filename: str, replacement: str = "_") -> str:
        """
        Quick sanitization for user input filenames

        Args:
            unsafe_filename: Potentially unsafe filename
            replacement: Character to replace invalid chars with

        Returns:
            Safe filename
        """
        # Remove path components
        unsafe_filename = Path(unsafe_filename).name

        # Sanitize
        safe = self.sanitize_filename(unsafe_filename)

        # Additional safety: replace any remaining problematic chars
        safe = re.sub(r'[^\w\s\-_.()]', replacement, safe)

        return safe

    def generate_unique_filename(
        self,
        base_filename: str,
        directory: str,
        max_attempts: int = 1000
    ) -> str:
        """
        Generate unique filename by appending counter if needed

        Args:
            base_filename: Base filename
            directory: Target directory
            max_attempts: Maximum number of attempts

        Returns:
            Unique filename
        """
        directory_path = Path(directory)

        # Try base filename first
        if not (directory_path / base_filename).exists():
            return base_filename

        # Split name and extension
        name, ext = self.split_extension(base_filename)

        # Try with counters
        for i in range(1, max_attempts):
            candidate = f"{name} ({i}).{ext}" if ext else f"{name} ({i})"

            if not (directory_path / candidate).exists():
                return candidate

        # Fallback: use timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{name}_{timestamp}.{ext}" if ext else f"{name}_{timestamp}"

    def compare_filenames(self, filename1: str, filename2: str) -> bool:
        """
        Compare filenames ignoring case and minor variations

        Args:
            filename1: First filename
            filename2: Second filename

        Returns:
            True if filenames are equivalent
        """
        # Normalize both
        norm1 = self.sanitize_filename(filename1).lower()
        norm2 = self.sanitize_filename(filename2).lower()

        return norm1 == norm2
