"""
Quality Detection System for Studio54
Lidarr-inspired quality detection and scoring

Analyzes audio files to determine:
- Format (FLAC, MP3, AAC, etc.)
- Bitrate
- Sample rate
- Bit depth
- Overall quality score

Quality scores are used for:
- File selection during import
- Upgrade decisions
- Duplicate detection
"""

import re
from typing import Optional, Dict, Any
from enum import IntEnum
from pathlib import Path
from dataclasses import dataclass


class AudioQuality(IntEnum):
    """
    Audio quality enumeration with scoring.

    Higher values = better quality.
    Organized by format groups:
    - 1-99: Low quality lossy
    - 100-199: Standard lossy
    - 200-299: High quality lossy
    - 300-399: Very high quality lossy
    - 400-499: Lossless 16-bit
    - 500+: Lossless 24-bit
    """
    # Unknown/undetected
    UNKNOWN = 0

    # Low quality MP3 (8-64 kbps)
    MP3_008 = 10
    MP3_016 = 15
    MP3_024 = 20
    MP3_032 = 25
    MP3_040 = 30
    MP3_048 = 35
    MP3_056 = 40
    MP3_064 = 45

    # Standard MP3 (80-128 kbps)
    MP3_080 = 80
    MP3_096 = 96
    MP3_112 = 112
    MP3_128 = 128

    # High quality MP3 (160-256 kbps)
    MP3_160 = 160
    MP3_192 = 192
    MP3_224 = 224
    MP3_256 = 256

    # Very high quality MP3
    MP3_320 = 320
    MP3_VBR = 310  # VBR (average quality)
    MP3_VBR_V0 = 330  # VBR V0 (~245 kbps avg)
    MP3_VBR_V2 = 325  # VBR V2 (~190 kbps avg)

    # AAC formats
    AAC_128 = 135  # Slightly better than MP3_128
    AAC_192 = 200
    AAC_256 = 265
    AAC_320 = 330
    AAC_VBR = 270

    # OGG Vorbis (q0-q10 scale)
    VORBIS_Q5 = 160  # ~160 kbps
    VORBIS_Q6 = 192  # ~192 kbps
    VORBIS_Q7 = 224  # ~224 kbps
    VORBIS_Q8 = 256  # ~256 kbps
    VORBIS_Q9 = 320  # ~320 kbps
    VORBIS_Q10 = 350  # ~500 kbps

    # Other lossy
    OPUS = 250  # Generally very high quality
    WMA = 100  # Variable, assume low

    # Lossless 16-bit
    FLAC = 400
    ALAC = 400
    APE = 390  # Slightly lower due to less compatibility
    WAVPACK = 395
    WAV = 400

    # Lossless 24-bit (Hi-Res)
    FLAC_24 = 500
    ALAC_24 = 500
    WAV_24 = 500


@dataclass
class QualityProfile:
    """
    Represents the detected quality of an audio file.
    """
    quality: AudioQuality
    codec: str  # e.g., 'FLAC', 'MP3', 'AAC'
    bitrate: Optional[int] = None  # kbps
    sample_rate: Optional[int] = None  # Hz
    bit_depth: Optional[int] = None  # bits
    channels: Optional[int] = None
    is_vbr: bool = False
    is_lossless: bool = False

    @property
    def quality_score(self) -> int:
        """Get the numeric quality score."""
        return self.quality.value

    @property
    def quality_title(self) -> str:
        """Get human-readable quality title."""
        if self.is_lossless:
            if self.bit_depth == 24:
                return f"{self.codec} 24-bit"
            return self.codec
        elif self.is_vbr:
            return f"{self.codec} VBR"
        elif self.bitrate:
            return f"{self.codec} {self.bitrate}kbps"
        return self.codec

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'quality': self.quality.name,
            'quality_score': self.quality_score,
            'quality_title': self.quality_title,
            'codec': self.codec,
            'bitrate': self.bitrate,
            'sample_rate': self.sample_rate,
            'bit_depth': self.bit_depth,
            'channels': self.channels,
            'is_vbr': self.is_vbr,
            'is_lossless': self.is_lossless,
        }


class QualityDetector:
    """
    Detects audio quality from file metadata and paths.

    Uses multiple detection strategies:
    1. Audio tag metadata (most reliable)
    2. Filename/folder parsing
    3. File extension fallback
    """

    # Codec detection regex (from filename/folder)
    CODEC_REGEX = re.compile(
        r'\b(?:'
        r'(?P<flac24>FLAC.*24[-_ ]?bit)|'
        r'(?P<flac>FLAC)|'
        r'(?P<alac>ALAC)|'
        r'(?P<aac>AAC|M4A)|'
        r'(?P<mp3>MP3|MPEG[-_ ]?Audio)|'
        r'(?P<vorbis>OGG|Vorbis)|'
        r'(?P<opus>Opus)|'
        r'(?P<wma>WMA)|'
        r'(?P<ape>APE)|'
        r'(?P<wavpack>WAVPACK|WV)|'
        r'(?P<wav>WAV|WAVE)'
        r')\b',
        re.IGNORECASE
    )

    # Bitrate detection regex
    BITRATE_REGEX = re.compile(
        r'(?P<bitrate>64|80|96|112|128|160|192|224|256|320|500)\s?kbps|'
        r'(?P<vbr>V[0-2])',
        re.IGNORECASE
    )

    # File extension to quality mapping
    EXTENSION_QUALITY = {
        '.flac': AudioQuality.FLAC,
        '.mp3': AudioQuality.MP3_320,  # Assume high quality
        '.m4a': AudioQuality.AAC_256,
        '.aac': AudioQuality.AAC_256,
        '.ogg': AudioQuality.VORBIS_Q8,
        '.opus': AudioQuality.OPUS,
        '.wma': AudioQuality.WMA,
        '.ape': AudioQuality.APE,
        '.wv': AudioQuality.WAVPACK,
        '.wav': AudioQuality.WAV,
        '.alac': AudioQuality.ALAC,
    }

    def detect_from_metadata(self, metadata: Dict[str, Any]) -> QualityProfile:
        """
        Detect quality from audio file metadata.

        Args:
            metadata: Dictionary with audio metadata (from mutagen/TagLib)
                Expected keys:
                - codec: str (e.g., 'FLAC', 'MP3')
                - bitrate: int (kbps)
                - sample_rate: int (Hz)
                - bit_depth: int (bits)
                - channels: int
                - vbr: bool

        Returns:
            QualityProfile with detected quality
        """
        codec = metadata.get('codec', '').upper()
        bitrate = metadata.get('bitrate')  # in kbps
        sample_rate = metadata.get('sample_rate')
        bit_depth = metadata.get('bit_depth')
        channels = metadata.get('channels')
        is_vbr = metadata.get('vbr', False)

        # Detect quality based on codec and bitrate
        quality = self._detect_quality(codec, bitrate, bit_depth, is_vbr)

        # Determine if lossless
        is_lossless = codec in {'FLAC', 'ALAC', 'APE', 'WAVPACK', 'WAV'}

        return QualityProfile(
            quality=quality,
            codec=codec,
            bitrate=bitrate,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            is_vbr=is_vbr,
            is_lossless=is_lossless,
        )

    def detect_from_path(self, file_path: Path) -> QualityProfile:
        """
        Detect quality from filename and folder path.

        Less reliable than metadata, but useful for quick scanning.

        Args:
            file_path: Path to audio file

        Returns:
            QualityProfile with detected quality
        """
        path_str = str(file_path)

        # Try codec detection from path
        codec_match = self.CODEC_REGEX.search(path_str)
        codec = 'Unknown'
        bit_depth = None

        if codec_match:
            # Determine which group matched
            for group_name, group_value in codec_match.groupdict().items():
                if group_value:
                    if group_name == 'flac24':
                        codec = 'FLAC'
                        bit_depth = 24
                    elif group_name == 'flac':
                        codec = 'FLAC'
                    elif group_name == 'alac':
                        codec = 'ALAC'
                    elif group_name == 'aac':
                        codec = 'AAC'
                    elif group_name == 'mp3':
                        codec = 'MP3'
                    elif group_name == 'vorbis':
                        codec = 'Vorbis'
                    elif group_name == 'opus':
                        codec = 'Opus'
                    elif group_name == 'wma':
                        codec = 'WMA'
                    elif group_name == 'ape':
                        codec = 'APE'
                    elif group_name == 'wavpack':
                        codec = 'WAVPACK'
                    elif group_name == 'wav':
                        codec = 'WAV'
                    break

        # Try bitrate detection from path
        bitrate = None
        is_vbr = False
        bitrate_match = self.BITRATE_REGEX.search(path_str)
        if bitrate_match:
            if bitrate_match.group('vbr'):
                is_vbr = True
                # Map VBR quality to bitrate
                vbr_quality = bitrate_match.group('vbr').upper()
                if vbr_quality == 'V0':
                    bitrate = 245
                elif vbr_quality == 'V2':
                    bitrate = 190
            elif bitrate_match.group('bitrate'):
                bitrate = int(bitrate_match.group('bitrate'))

        # Fallback to file extension
        if codec == 'Unknown':
            ext = file_path.suffix.lower()
            quality = self.EXTENSION_QUALITY.get(ext, AudioQuality.UNKNOWN)
            if quality == AudioQuality.FLAC:
                codec = 'FLAC'
            elif quality in {AudioQuality.MP3_320}:
                codec = 'MP3'
            elif quality in {AudioQuality.AAC_256}:
                codec = 'AAC'
            # ... etc.

        # Detect quality
        quality = self._detect_quality(codec, bitrate, bit_depth, is_vbr)
        is_lossless = codec in {'FLAC', 'ALAC', 'APE', 'WAVPACK', 'WAV'}

        return QualityProfile(
            quality=quality,
            codec=codec,
            bitrate=bitrate,
            bit_depth=bit_depth,
            is_vbr=is_vbr,
            is_lossless=is_lossless,
        )

    def _detect_quality(
        self,
        codec: str,
        bitrate: Optional[int],
        bit_depth: Optional[int],
        is_vbr: bool
    ) -> AudioQuality:
        """
        Determine AudioQuality enum from codec and bitrate.

        Args:
            codec: Audio codec name
            bitrate: Bitrate in kbps
            bit_depth: Bit depth (16, 24, etc.)
            is_vbr: Whether file uses variable bitrate

        Returns:
            AudioQuality enum value
        """
        codec = codec.upper()

        # Lossless formats
        if codec == 'FLAC':
            return AudioQuality.FLAC_24 if bit_depth == 24 else AudioQuality.FLAC
        elif codec == 'ALAC':
            return AudioQuality.ALAC_24 if bit_depth == 24 else AudioQuality.ALAC
        elif codec == 'WAV':
            return AudioQuality.WAV_24 if bit_depth == 24 else AudioQuality.WAV
        elif codec == 'APE':
            return AudioQuality.APE
        elif codec == 'WAVPACK':
            return AudioQuality.WAVPACK

        # MP3
        elif codec == 'MP3':
            if is_vbr:
                # Estimate VBR quality from bitrate
                if bitrate and bitrate >= 240:
                    return AudioQuality.MP3_VBR_V0
                elif bitrate and bitrate >= 180:
                    return AudioQuality.MP3_VBR_V2
                return AudioQuality.MP3_VBR
            elif bitrate:
                # Map bitrate to quality
                if bitrate >= 320:
                    return AudioQuality.MP3_320
                elif bitrate >= 256:
                    return AudioQuality.MP3_256
                elif bitrate >= 224:
                    return AudioQuality.MP3_224
                elif bitrate >= 192:
                    return AudioQuality.MP3_192
                elif bitrate >= 160:
                    return AudioQuality.MP3_160
                elif bitrate >= 128:
                    return AudioQuality.MP3_128
                elif bitrate >= 112:
                    return AudioQuality.MP3_112
                elif bitrate >= 96:
                    return AudioQuality.MP3_096
                elif bitrate >= 80:
                    return AudioQuality.MP3_080
                elif bitrate >= 64:
                    return AudioQuality.MP3_064
                elif bitrate >= 56:
                    return AudioQuality.MP3_056
                elif bitrate >= 48:
                    return AudioQuality.MP3_048
                elif bitrate >= 40:
                    return AudioQuality.MP3_040
                elif bitrate >= 32:
                    return AudioQuality.MP3_032
                elif bitrate >= 24:
                    return AudioQuality.MP3_024
                elif bitrate >= 16:
                    return AudioQuality.MP3_016
                else:
                    return AudioQuality.MP3_008
            else:
                # No bitrate info - assume 320
                return AudioQuality.MP3_320

        # AAC
        elif codec == 'AAC':
            if is_vbr:
                return AudioQuality.AAC_VBR
            elif bitrate:
                if bitrate >= 320:
                    return AudioQuality.AAC_320
                elif bitrate >= 256:
                    return AudioQuality.AAC_256
                elif bitrate >= 192:
                    return AudioQuality.AAC_192
                else:
                    return AudioQuality.AAC_128
            else:
                return AudioQuality.AAC_256

        # Vorbis
        elif codec in {'VORBIS', 'OGG'}:
            if bitrate:
                if bitrate >= 350:
                    return AudioQuality.VORBIS_Q10
                elif bitrate >= 320:
                    return AudioQuality.VORBIS_Q9
                elif bitrate >= 256:
                    return AudioQuality.VORBIS_Q8
                elif bitrate >= 224:
                    return AudioQuality.VORBIS_Q7
                elif bitrate >= 192:
                    return AudioQuality.VORBIS_Q6
                else:
                    return AudioQuality.VORBIS_Q5
            else:
                return AudioQuality.VORBIS_Q8

        # Other codecs
        elif codec == 'OPUS':
            return AudioQuality.OPUS
        elif codec == 'WMA':
            return AudioQuality.WMA

        return AudioQuality.UNKNOWN

    def compare_quality(
        self,
        quality1: QualityProfile,
        quality2: QualityProfile
    ) -> int:
        """
        Compare two quality profiles.

        Args:
            quality1: First quality profile
            quality2: Second quality profile

        Returns:
            -1 if quality1 < quality2
             0 if quality1 == quality2
             1 if quality1 > quality2
        """
        score1 = quality1.quality_score
        score2 = quality2.quality_score

        if score1 < score2:
            return -1
        elif score1 > score2:
            return 1
        else:
            # Same quality - compare by bitrate if available
            if quality1.bitrate and quality2.bitrate:
                if quality1.bitrate < quality2.bitrate:
                    return -1
                elif quality1.bitrate > quality2.bitrate:
                    return 1

            # Same quality and bitrate (or no bitrate) - consider equal
            return 0

    def is_upgrade(
        self,
        current: QualityProfile,
        new: QualityProfile
    ) -> bool:
        """
        Determine if new quality is an upgrade over current.

        Args:
            current: Current file quality
            new: New file quality

        Returns:
            True if new is better than current
        """
        return self.compare_quality(new, current) > 0
