"""
Naming Template Engine for Studio54
Lidarr-inspired configurable file/folder naming system

Supports template tokens like:
- {Artist Name}, {Album Title}, {Track Title}
- {track:00}, {disc:00} (with zero-padding)
- {Release Year}, {Album Type}
- {Quality Title}, {MediaInfo AudioCodec}, {MediaInfo AudioBitRate}
- Case transformation (lowercase/UPPERCASE)
- Separator substitution ({Artist-Name} converts spaces to hyphens)
"""

import re
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from datetime import datetime


class NamingTemplateEngine:
    """
    Template engine for generating file and folder names from metadata.

    Based on Lidarr's FileNameBuilder.cs implementation with improvements:
    - Python-native regex and string handling
    - Support for custom token functions
    - Comprehensive sanitization
    """

    # Token extraction regex (captures prefix, token, separator, format, suffix)
    TOKEN_REGEX = re.compile(
        r"(?P<escaped>\{\{|\}\})|"  # Escaped braces
        r"\{"  # Opening brace
        r"(?P<prefix>[-._\[(]*)"  # Leading separators
        r"(?P<token>(?:[a-z0-9]+)(?:(?P<separator>[-._\s]+)(?:[a-z0-9]+))*)"  # Token with separator (space, dot, dash, underscore)
        r"(?::(?P<format>[-0-9]+))?"  # Format specifier (e.g., :00, :20, :-15)
        r"(?P<suffix>[-._)\]]*)"  # Trailing separators
        r"\}",  # Closing brace
        re.IGNORECASE
    )

    # Illegal filename characters (cross-platform)
    ILLEGAL_CHARS = {
        '\\': '+', '/': '+', '<': '', '>': '', '?': '!', '*': '-', '|': '', '"': "'"
    }

    # Colon replacement strategies
    COLON_STRATEGIES = {
        'smart': lambda s: s.replace(': ', ' - ').replace(':', '-'),
        'dash': lambda s: s.replace(':', '-'),
        'space_dash': lambda s: s.replace(':', ' - '),
        'space_dash_space': lambda s: s.replace(':', ' - '),
        'delete': lambda s: s.replace(':', ''),
    }

    # Reserved Windows device names
    RESERVED_NAMES = re.compile(
        r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)',
        re.IGNORECASE
    )

    # Redundant separator cleanup
    SEPARATOR_CLEANUP = re.compile(r'([._\-\s])\1+')

    def __init__(self, colon_strategy: str = 'smart'):
        """
        Initialize the naming template engine.

        Args:
            colon_strategy: How to handle colons in filenames
                - 'smart': ': ' → ' - ', ':' → '-'
                - 'dash': All colons → '-'
                - 'space_dash': All colons → ' - '
                - 'delete': Remove all colons
        """
        self.colon_strategy = colon_strategy
        self.token_functions: Dict[str, Callable] = {}
        self._register_default_tokens()

    def _register_default_tokens(self):
        """Register default token replacement functions."""
        # These will be populated from metadata dict in build_path()
        # Just defining the structure here
        self.default_tokens = [
            # Artist tokens
            'artist_name', 'artist_clean_name', 'artist_mbid',
            'artist_disambiguation', 'artist_first_char',

            # Album tokens
            'album_title', 'album_clean_title', 'album_mbid',
            'album_type', 'album_disambiguation', 'release_year',
            'release_date', 'album_genre',

            # Track tokens
            'track_title', 'track_clean_title', 'track_number',
            'disc_number', 'track_mbid', 'track_artist',

            # Quality tokens
            'quality_title', 'quality_full',

            # Media Info tokens
            'mediainfo_audiocodec', 'mediainfo_audiobitrate',
            'mediainfo_audiochannels', 'mediainfo_audiosamplerate',

            # File tokens
            'original_filename', 'file_extension',
        ]

        # Token aliases (shortened forms that map to full token names)
        self.token_aliases = {
            'track': 'track_number',
            'disc': 'disc_number',
            'medium': 'disc_number',
            'artist': 'artist_name',
            'album': 'album_title',
            'title': 'track_title',
            'year': 'release_year',
        }

    def build_path(
        self,
        template: str,
        metadata: Dict[str, Any],
        is_folder: bool = False
    ) -> str:
        """
        Build a file or folder path from a template and metadata.

        Args:
            template: Template string with tokens (e.g., "{Artist Name}/{Album Title}")
            metadata: Dictionary with values for token replacement
            is_folder: If True, don't add file extension

        Returns:
            Formatted and sanitized path string

        Example:
            >>> engine = NamingTemplateEngine()
            >>> metadata = {
            ...     'artist_name': 'Pink Floyd',
            ...     'album_title': 'Dark Side of the Moon',
            ...     'release_year': 1973,
            ...     'track_number': 1,
            ...     'track_title': 'Speak to Me'
            ... }
            >>> template = "{Artist Name}/{Album Title} ({Release Year})/{track:00} - {Track Title}"
            >>> engine.build_path(template, metadata)
            'Pink Floyd/Dark Side of the Moon (1973)/01 - Speak to Me'
        """
        result = template

        # First pass: Replace all tokens
        def replace_token(match: re.Match) -> str:
            # Handle escaped braces
            if match.group('escaped'):
                return match.group('escaped')[0]  # {{ → {, }} → }

            prefix = match.group('prefix')
            token = match.group('token')
            separator = match.group('separator')
            format_spec = match.group('format')
            suffix = match.group('suffix')

            # Get token value from metadata
            token_key = token.lower().replace(' ', '_').replace('-', '_')

            # Resolve token aliases (e.g., 'track' -> 'track_number')
            if token_key in self.token_aliases:
                token_key = self.token_aliases[token_key]

            value = metadata.get(token_key)

            if value is None:
                # Token not found - remove prefix/suffix to avoid artifacts
                return ''

            # Convert value to string
            replacement = str(value)

            # Apply numeric formatting (e.g., {track:00} → 01, 02, ...)
            if format_spec and isinstance(value, (int, float)):
                if format_spec.startswith('-'):
                    # Truncation from end (e.g., :-15)
                    max_len = abs(int(format_spec))
                    replacement = replacement[-max_len:] if len(replacement) > max_len else replacement
                elif format_spec.isdigit() and int(format_spec) > 0:
                    # Truncation from start (e.g., :20) — only when value > 0
                    max_len = int(format_spec)
                    replacement = replacement[:max_len] if len(replacement) > max_len else replacement
                else:
                    # Zero-padding (e.g., :00, :000, :0)
                    try:
                        width = len(format_spec)
                        replacement = str(int(value)).zfill(width)
                    except (ValueError, TypeError):
                        pass

            # Apply case transformation based on token case
            if token.islower():
                replacement = replacement.lower()
            elif token.isupper():
                replacement = replacement.upper()
            # Mixed case or title case - keep original

            # Apply separator substitution (e.g., {Artist-Name} → Pink-Floyd)
            if separator:
                replacement = replacement.replace(' ', separator)

            # Return with prefix/suffix
            return f"{prefix}{replacement}{suffix}"

        result = self.TOKEN_REGEX.sub(replace_token, result)

        # Second pass: Sanitization
        result = self._sanitize_path(result, is_folder)

        return result

    def _sanitize_path(self, path: str, is_folder: bool = False) -> str:
        """
        Sanitize a path by replacing illegal characters and cleaning up.

        Args:
            path: Path to sanitize
            is_folder: If True, don't preserve file extension

        Returns:
            Sanitized path
        """
        # Split into components (folder/folder/file)
        parts = path.split('/')
        sanitized_parts = []

        for i, part in enumerate(parts):
            # Determine if this is a file component (last part and not a folder)
            is_file = (i == len(parts) - 1) and not is_folder

            # Handle file extension separately
            if is_file and '.' in part:
                name, ext = part.rsplit('.', 1)
                sanitized_name = self._sanitize_component(name)
                sanitized_part = f"{sanitized_name}.{ext}"
            else:
                sanitized_part = self._sanitize_component(part)

            # Skip empty components
            if sanitized_part:
                sanitized_parts.append(sanitized_part)

        return '/'.join(sanitized_parts)

    def _sanitize_component(self, component: str) -> str:
        """
        Sanitize a single path component (filename or folder name).

        Args:
            component: Component to sanitize

        Returns:
            Sanitized component
        """
        # 1. Replace illegal characters
        for illegal, replacement in self.ILLEGAL_CHARS.items():
            component = component.replace(illegal, replacement)

        # 2. Handle colons
        colon_handler = self.COLON_STRATEGIES.get(
            self.colon_strategy,
            self.COLON_STRATEGIES['smart']
        )
        component = colon_handler(component)

        # 3. Clean up redundant separators (e.g., "foo..bar" → "foo.bar")
        component = self.SEPARATOR_CLEANUP.sub(r'\1', component)

        # 4. Trim leading/trailing separators and spaces
        component = component.strip(' ._-')

        # 5. Handle reserved Windows device names (CON, PRN, etc.)
        if self.RESERVED_NAMES.match(component):
            component = component.replace('.', '_')

        return component

    def get_clean_name(self, name: str) -> str:
        """
        Get a clean version of a name (removes 'The', special chars, etc.).

        Args:
            name: Original name

        Returns:
            Cleaned name

        Example:
            >>> engine = NamingTemplateEngine()
            >>> engine.get_clean_name("The Beatles")
            'beatles'
        """
        # Remove leading "The"
        clean = re.sub(r'^the\s+', '', name, flags=re.IGNORECASE)

        # Remove special characters
        clean = re.sub(r'[^\w\s]', '', clean)

        # Lowercase and strip
        clean = clean.lower().strip()

        return clean

    def get_name_the(self, name: str) -> str:
        """
        Move leading "The" to the end.

        Args:
            name: Original name

        Returns:
            Name with "The" moved to end

        Example:
            >>> engine = NamingTemplateEngine()
            >>> engine.get_name_the("The Beatles")
            'Beatles, The'
        """
        match = re.match(r'^(the)\s+(.+)$', name, re.IGNORECASE)
        if match:
            article = match.group(1)
            rest = match.group(2)
            return f"{rest}, {article}"
        return name

    def validate_template(self, template: str) -> tuple[bool, Optional[str]]:
        """
        Validate a naming template for syntax errors.

        Args:
            template: Template string to validate

        Returns:
            Tuple of (is_valid, error_message)

        Example:
            >>> engine = NamingTemplateEngine()
            >>> engine.validate_template("{Artist Name}/{Album Title}")
            (True, None)
            >>> engine.validate_template("{Artist Name}/{Invalid Token}")
            (False, "Unknown token: 'Invalid Token'")
        """
        # Check for unmatched braces
        open_braces = template.count('{') - template.count('{{')
        close_braces = template.count('}') - template.count('}}')

        if open_braces != close_braces:
            return False, "Unmatched braces in template"

        # Extract all tokens
        tokens = []
        for match in self.TOKEN_REGEX.finditer(template):
            if not match.group('escaped'):
                token = match.group('token')
                tokens.append(token)

        # Check if all tokens are recognized
        for token in tokens:
            token_key = token.lower().replace(' ', '_').replace('-', '_')

            # Resolve aliases
            if token_key in self.token_aliases:
                token_key = self.token_aliases[token_key]

            if token_key not in self.default_tokens:
                return False, f"Unknown token: '{token}'"

        return True, None

    def get_example_output(
        self,
        template: str,
        example_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate example output for a template using sample metadata.

        Args:
            template: Template string
            example_metadata: Optional custom example metadata

        Returns:
            Example formatted path
        """
        if example_metadata is None:
            example_metadata = {
                'artist_name': 'Pink Floyd',
                'artist_clean_name': 'pinkfloyd',
                'album_title': 'Dark Side of the Moon',
                'album_clean_title': 'darksideofthemoon',
                'album_type': 'Album',
                'release_year': 1973,
                'track_number': 1,
                'track_title': 'Speak to Me',
                'disc_number': 1,
                'quality_title': 'FLAC',
                'mediainfo_audiocodec': 'FLAC',
                'mediainfo_audiobitrate': '1411 kbps',
            }

        return self.build_path(template, example_metadata)


# Pre-defined naming templates (Lidarr-inspired)
DEFAULT_TEMPLATES = {
    'standard': {
        'name': 'Standard',
        'artist_folder': '{Artist Name}',
        'album_folder': '{Album Title} ({Release Year})',
        'track_file': '{Artist Name} - {Album Title} - {track:00} - {Track Title}',
        'description': 'Artist/Album (Year)/Artist - Album - 01 - Title',
    },
    'multi_disc': {
        'name': 'Multi-Disc',
        'artist_folder': '{Artist Name}',
        'album_folder': '{Album Title} ({Release Year})',
        'track_file': '{disc:0}-{track:00} - {Track Title}',
        'description': 'Artist/Album (Year)/1-01 - Title (for multi-disc albums)',
    },
    'simple': {
        'name': 'Simple',
        'artist_folder': '{Artist Name}',
        'album_folder': '{Album Title}',
        'track_file': '{track:00} - {Track Title}',
        'description': 'Artist/Album/01 - Title',
    },
    'quality': {
        'name': 'With Quality',
        'artist_folder': '{Artist Name}',
        'album_folder': '{Album Title} ({Release Year}) [{Quality Title}]',
        'track_file': '{track:00} - {Track Title}',
        'description': 'Artist/Album (Year) [FLAC]/01 - Title',
    },
}
