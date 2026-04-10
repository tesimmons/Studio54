"""
Metadata Writer Service
Write metadata and MBIDs to audio files using mutagen

Supports: MP3, FLAC, M4A/AAC, OGG
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

try:
    from mutagen import File as MutagenFile
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    from mutagen.id3 import ID3, COMM, TXXX, TIT2, TPE1, TALB, TRCK, TPOS, TDRC, TCON, TPE2, TENC
    from mutagen.id3 import ID3NoHeaderError
except ImportError:
    raise ImportError("mutagen library is required. Install with: pip install mutagen")

logger = logging.getLogger(__name__)


class MetadataWriteResult:
    """Result of a metadata write operation"""

    def __init__(
        self,
        success: bool,
        file_path: str,
        error: Optional[str] = None,
        mbids_written: Optional[Dict[str, str]] = None,
        tags_written: Optional[Dict[str, str]] = None
    ):
        self.success = success
        self.file_path = file_path
        self.error = error
        self.mbids_written = mbids_written or {}
        self.tags_written = tags_written or {}

    def __repr__(self):
        return f"<MetadataWriteResult(success={self.success}, file='{self.file_path}')>"


class MetadataWriter:
    """
    Write metadata and MBIDs to audio files

    Supports: MP3, FLAC, M4A/AAC, OGG
    """

    SUPPORTED_EXTENSIONS = {
        '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.oga', '.opus'
    }

    # MBID comment format used by MUSE Ponder
    MBID_COMMENT_FORMAT = "RecordingMBID:{recording_mbid} | ArtistMBID:{artist_mbid} | ReleaseMBID:{release_mbid} | ReleaseGroupMBID:{release_group_mbid}"

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """Check if file extension is supported for writing"""
        ext = Path(file_path).suffix.lower()
        return ext in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def write_mbids(
        cls,
        file_path: str,
        recording_mbid: Optional[str] = None,
        artist_mbid: Optional[str] = None,
        release_mbid: Optional[str] = None,
        release_group_mbid: Optional[str] = None,
        overwrite: bool = False
    ) -> MetadataWriteResult:
        """
        Write MBIDs to audio file comment field

        Format: "RecordingMBID:<uuid> | ArtistMBID:<uuid> | ReleaseMBID:<uuid> | ReleaseGroupMBID:<uuid>"

        Args:
            file_path: Path to audio file
            recording_mbid: MusicBrainz Recording ID (track)
            artist_mbid: MusicBrainz Artist ID
            release_mbid: MusicBrainz Release ID (album)
            release_group_mbid: MusicBrainz Release Group ID
            overwrite: If True, overwrite existing MBIDs. If False, skip if already present.

        Returns:
            MetadataWriteResult with success status and details
        """
        if not os.path.exists(file_path):
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"File not found: {file_path}"
            )

        if not cls.is_supported(file_path):
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"Unsupported file format: {file_path}"
            )

        try:
            # Check if MBIDs already exist
            if not overwrite:
                existing = cls.verify_mbid_in_file(file_path)
                if existing.get('has_mbid'):
                    logger.debug(f"MBIDs already exist in file, skipping: {file_path}")
                    return MetadataWriteResult(
                        success=True,
                        file_path=file_path,
                        mbids_written={}
                    )

            # Build MBID comment string
            mbid_comment = cls.MBID_COMMENT_FORMAT.format(
                recording_mbid=recording_mbid or '',
                artist_mbid=artist_mbid or '',
                release_mbid=release_mbid or '',
                release_group_mbid=release_group_mbid or ''
            )

            # Determine file type and write appropriately
            ext = Path(file_path).suffix.lower()

            if ext == '.mp3':
                result = cls._write_mp3_mbid(file_path, mbid_comment)
            elif ext == '.flac':
                result = cls._write_flac_mbid(file_path, mbid_comment)
            elif ext in ('.m4a', '.aac'):
                result = cls._write_mp4_mbid(file_path, mbid_comment)
            elif ext in ('.ogg', '.oga', '.opus'):
                result = cls._write_ogg_mbid(file_path, mbid_comment)
            else:
                return MetadataWriteResult(
                    success=False,
                    file_path=file_path,
                    error=f"Unsupported format for writing: {ext}"
                )

            if result:
                mbids_written = {}
                if recording_mbid:
                    mbids_written['recording_mbid'] = recording_mbid
                if artist_mbid:
                    mbids_written['artist_mbid'] = artist_mbid
                if release_mbid:
                    mbids_written['release_mbid'] = release_mbid
                if release_group_mbid:
                    mbids_written['release_group_mbid'] = release_group_mbid

                logger.info(f"Successfully wrote MBIDs to: {file_path}")
                return MetadataWriteResult(
                    success=True,
                    file_path=file_path,
                    mbids_written=mbids_written
                )
            else:
                return MetadataWriteResult(
                    success=False,
                    file_path=file_path,
                    error="Failed to write MBIDs to file"
                )

        except Exception as e:
            logger.error(f"Error writing MBIDs to {file_path}: {e}")
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=str(e)
            )

    @classmethod
    def _write_mp3_mbid(cls, file_path: str, mbid_comment: str) -> bool:
        """Write MBID comment to MP3 file using ID3"""
        try:
            try:
                audio = ID3(file_path)
            except ID3NoHeaderError:
                # Create ID3 header if it doesn't exist
                audio = ID3()
                audio.save(file_path)
                audio = ID3(file_path)

            # Remove existing COMM frames with same description
            audio.delall('COMM::eng')
            audio.delall('COMM:MBID:eng')

            # Add new COMM frame with MBID data
            audio.add(COMM(
                encoding=3,  # UTF-8
                lang='eng',
                desc='MBID',
                text=mbid_comment
            ))

            # Also write to standard MusicBrainz TXXX frames for compatibility
            cls._write_mp3_txxx_mbids(audio, mbid_comment)

            audio.save(file_path, v2_version=3)
            return True

        except Exception as e:
            logger.error(f"Failed to write MP3 MBID: {e}")
            return False

    @classmethod
    def _write_mp3_txxx_mbids(cls, audio: ID3, mbid_comment: str) -> None:
        """Write MBIDs to standard TXXX frames for cross-application compatibility"""
        # Parse MBIDs from comment
        mbids = cls._parse_mbid_comment(mbid_comment)

        if mbids.get('recording_mbid'):
            audio.delall('TXXX:MusicBrainz Release Track Id')
            audio.add(TXXX(
                encoding=3,
                desc='MusicBrainz Release Track Id',
                text=[mbids['recording_mbid']]
            ))

        if mbids.get('artist_mbid'):
            audio.delall('TXXX:MusicBrainz Artist Id')
            audio.add(TXXX(
                encoding=3,
                desc='MusicBrainz Artist Id',
                text=[mbids['artist_mbid']]
            ))

        if mbids.get('release_mbid'):
            audio.delall('TXXX:MusicBrainz Album Id')
            audio.add(TXXX(
                encoding=3,
                desc='MusicBrainz Album Id',
                text=[mbids['release_mbid']]
            ))

        if mbids.get('release_group_mbid'):
            audio.delall('TXXX:MusicBrainz Release Group Id')
            audio.add(TXXX(
                encoding=3,
                desc='MusicBrainz Release Group Id',
                text=[mbids['release_group_mbid']]
            ))

    @classmethod
    def _write_flac_mbid(cls, file_path: str, mbid_comment: str) -> bool:
        """Write MBID comment to FLAC file"""
        try:
            audio = FLAC(file_path)

            # Add/update comment
            audio['comment'] = mbid_comment

            # Also write standard MusicBrainz tags
            mbids = cls._parse_mbid_comment(mbid_comment)
            if mbids.get('recording_mbid'):
                audio['musicbrainz_trackid'] = mbids['recording_mbid']
            if mbids.get('artist_mbid'):
                audio['musicbrainz_artistid'] = mbids['artist_mbid']
            if mbids.get('release_mbid'):
                audio['musicbrainz_albumid'] = mbids['release_mbid']
            if mbids.get('release_group_mbid'):
                audio['musicbrainz_releasegroupid'] = mbids['release_group_mbid']

            audio.save()
            return True

        except Exception as e:
            logger.error(f"Failed to write FLAC MBID: {e}")
            return False

    @classmethod
    def _write_mp4_mbid(cls, file_path: str, mbid_comment: str) -> bool:
        """Write MBID comment to M4A/AAC file"""
        try:
            audio = MP4(file_path)

            # Write to comment tag
            audio['\xa9cmt'] = mbid_comment

            # Also write to iTunes custom tags for MBIDs
            mbids = cls._parse_mbid_comment(mbid_comment)
            if mbids.get('recording_mbid'):
                audio['----:com.apple.iTunes:MusicBrainz Track Id'] = mbids['recording_mbid'].encode('utf-8')
            if mbids.get('artist_mbid'):
                audio['----:com.apple.iTunes:MusicBrainz Artist Id'] = mbids['artist_mbid'].encode('utf-8')
            if mbids.get('release_mbid'):
                audio['----:com.apple.iTunes:MusicBrainz Album Id'] = mbids['release_mbid'].encode('utf-8')
            if mbids.get('release_group_mbid'):
                audio['----:com.apple.iTunes:MusicBrainz Release Group Id'] = mbids['release_group_mbid'].encode('utf-8')

            audio.save()
            return True

        except Exception as e:
            logger.error(f"Failed to write MP4 MBID: {e}")
            return False

    @classmethod
    def _write_ogg_mbid(cls, file_path: str, mbid_comment: str) -> bool:
        """Write MBID comment to OGG/Opus file"""
        try:
            audio = OggVorbis(file_path)

            # Add comment
            audio['comment'] = mbid_comment

            # Also write standard MusicBrainz tags
            mbids = cls._parse_mbid_comment(mbid_comment)
            if mbids.get('recording_mbid'):
                audio['musicbrainz_trackid'] = mbids['recording_mbid']
            if mbids.get('artist_mbid'):
                audio['musicbrainz_artistid'] = mbids['artist_mbid']
            if mbids.get('release_mbid'):
                audio['musicbrainz_albumid'] = mbids['release_mbid']
            if mbids.get('release_group_mbid'):
                audio['musicbrainz_releasegroupid'] = mbids['release_group_mbid']

            audio.save()
            return True

        except Exception as e:
            logger.error(f"Failed to write OGG MBID: {e}")
            return False

    @classmethod
    def _parse_mbid_comment(cls, mbid_comment: str) -> Dict[str, Optional[str]]:
        """Parse MBID comment string into individual IDs"""
        result = {
            'recording_mbid': None,
            'artist_mbid': None,
            'release_mbid': None,
            'release_group_mbid': None
        }

        prefixes = {
            'RecordingMBID:': 'recording_mbid',
            'ArtistMBID:': 'artist_mbid',
            'ReleaseMBID:': 'release_mbid',
            'ReleaseGroupMBID:': 'release_group_mbid'
        }

        for prefix, key in prefixes.items():
            if prefix in mbid_comment:
                start_idx = mbid_comment.index(prefix) + len(prefix)
                mbid = mbid_comment[start_idx:start_idx + 36].strip()
                # Validate UUID format
                if len(mbid) == 36 and mbid.count('-') == 4:
                    result[key] = mbid.lower()

        return result

    @classmethod
    def verify_mbid_in_file(cls, file_path: str) -> Dict[str, Any]:
        """
        Verify if MBID is stored in file comments

        Args:
            file_path: Path to audio file

        Returns:
            Dict with:
                - has_mbid: bool - True if any MBID found
                - recording_mbid: Optional[str]
                - artist_mbid: Optional[str]
                - release_mbid: Optional[str]
                - release_group_mbid: Optional[str]
                - comment: Optional[str] - Raw comment field
        """
        result = {
            'has_mbid': False,
            'recording_mbid': None,
            'artist_mbid': None,
            'release_mbid': None,
            'release_group_mbid': None,
            'comment': None
        }

        if not os.path.exists(file_path):
            return result

        if not cls.is_supported(file_path):
            return result

        try:
            audio = MutagenFile(file_path, easy=False)
            if audio is None or audio.tags is None:
                return result

            # Get comment field
            comment = None
            comment_tags = ['comment', 'COMM::eng', 'COMM:MBID:eng', '\xa9cmt']

            for tag in comment_tags:
                if tag in audio.tags:
                    value = audio.tags[tag]
                    if isinstance(value, list) and len(value) > 0:
                        comment = str(value[0])
                    else:
                        comment = str(value)
                    break

            # For MP3, try to get COMM frame specifically
            if comment is None and isinstance(audio, MP3):
                for key in audio.tags.keys():
                    if key.startswith('COMM'):
                        frame = audio.tags[key]
                        if hasattr(frame, 'text'):
                            comment = str(frame.text[0]) if isinstance(frame.text, list) else str(frame.text)
                        break

            if comment:
                result['comment'] = comment
                mbids = cls._parse_mbid_comment(comment)
                result.update(mbids)
                result['has_mbid'] = any(v for v in mbids.values() if v)

            return result

        except Exception as e:
            logger.error(f"Error verifying MBID in file {file_path}: {e}")
            return result

    # Validation Tag Constants
    VALIDATION_TAG_PREFIX = "S54:"
    VALIDATION_STATUSES = {"VALIDATED", "CORRECTED", "FETCHED", "FINGERPRINT"}

    @classmethod
    def write_validation_tag(
        cls,
        file_path: str,
        status: str,
        confidence: int,
        timestamp: Optional[datetime] = None
    ) -> MetadataWriteResult:
        """
        Write validation status tag to "Encoded By" metadata field

        Format: S54:{status}@{confidence}:{iso_timestamp}
        Example: S54:VALIDATED@95:2026-02-02T12:34:56Z

        Field Mapping by Format:
        - MP3: TENC (ID3v2 Encoded By)
        - FLAC: ENCODEDBY (Vorbis comment)
        - M4A: \\xa9too (iTunes encoder)
        - OGG: ENCODEDBY (Vorbis comment)

        Args:
            file_path: Path to audio file
            status: Validation status (VALIDATED, CORRECTED, FETCHED, FINGERPRINT)
            confidence: Confidence percentage (0-100)
            timestamp: Timestamp of validation (defaults to now)

        Returns:
            MetadataWriteResult with success status and details
        """
        if not os.path.exists(file_path):
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"File not found: {file_path}"
            )

        if not cls.is_supported(file_path):
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"Unsupported file format: {file_path}"
            )

        # Validate status
        status = status.upper()
        if status not in cls.VALIDATION_STATUSES:
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"Invalid validation status: {status}. Must be one of: {cls.VALIDATION_STATUSES}"
            )

        # Validate confidence
        confidence = max(0, min(100, int(confidence)))

        # Build validation tag
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        validation_tag = f"{cls.VALIDATION_TAG_PREFIX}{status}@{confidence}:{timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}"

        try:
            ext = Path(file_path).suffix.lower()

            if ext == '.mp3':
                result = cls._write_mp3_validation_tag(file_path, validation_tag)
            elif ext == '.flac':
                result = cls._write_flac_validation_tag(file_path, validation_tag)
            elif ext in ('.m4a', '.aac'):
                result = cls._write_mp4_validation_tag(file_path, validation_tag)
            elif ext in ('.ogg', '.oga', '.opus'):
                result = cls._write_ogg_validation_tag(file_path, validation_tag)
            else:
                return MetadataWriteResult(
                    success=False,
                    file_path=file_path,
                    error=f"Unsupported format for validation tag: {ext}"
                )

            if result:
                logger.info(f"Successfully wrote validation tag to: {file_path} ({validation_tag})")
                return MetadataWriteResult(
                    success=True,
                    file_path=file_path,
                    tags_written={'validation_tag': validation_tag}
                )
            else:
                return MetadataWriteResult(
                    success=False,
                    file_path=file_path,
                    error="Failed to write validation tag to file"
                )

        except Exception as e:
            logger.error(f"Error writing validation tag to {file_path}: {e}")
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=str(e)
            )

    @classmethod
    def _write_mp3_validation_tag(cls, file_path: str, validation_tag: str) -> bool:
        """Write validation tag to MP3 file using TENC frame"""
        try:
            try:
                audio = ID3(file_path)
            except ID3NoHeaderError:
                audio = ID3()
                audio.save(file_path)
                audio = ID3(file_path)

            # Remove existing TENC frame
            audio.delall('TENC')

            # Add new TENC frame with validation tag
            audio.add(TENC(encoding=3, text=validation_tag))

            audio.save(file_path, v2_version=3)
            return True

        except Exception as e:
            logger.error(f"Failed to write MP3 validation tag: {e}")
            return False

    @classmethod
    def _write_flac_validation_tag(cls, file_path: str, validation_tag: str) -> bool:
        """Write validation tag to FLAC file using ENCODEDBY"""
        try:
            audio = FLAC(file_path)
            audio['encodedby'] = validation_tag
            audio.save()
            return True

        except Exception as e:
            logger.error(f"Failed to write FLAC validation tag: {e}")
            return False

    @classmethod
    def _write_mp4_validation_tag(cls, file_path: str, validation_tag: str) -> bool:
        """Write validation tag to M4A/AAC file using \\xa9too (encoder)"""
        try:
            audio = MP4(file_path)
            audio['\xa9too'] = validation_tag
            audio.save()
            return True

        except Exception as e:
            logger.error(f"Failed to write MP4 validation tag: {e}")
            return False

    @classmethod
    def _write_ogg_validation_tag(cls, file_path: str, validation_tag: str) -> bool:
        """Write validation tag to OGG/Opus file using ENCODEDBY"""
        try:
            audio = OggVorbis(file_path)
            audio['encodedby'] = validation_tag
            audio.save()
            return True

        except Exception as e:
            logger.error(f"Failed to write OGG validation tag: {e}")
            return False

    @classmethod
    def read_validation_tag(cls, file_path: str) -> Dict[str, Any]:
        """
        Read validation status from "Encoded By" metadata field

        Args:
            file_path: Path to audio file

        Returns:
            Dict with:
                - has_validation_tag: bool - True if valid S54 validation tag found
                - status: Optional[str] - VALIDATED, CORRECTED, FETCHED, FINGERPRINT
                - confidence: Optional[int] - 0-100
                - validated_at: Optional[datetime] - When validation occurred
                - raw_tag: Optional[str] - Raw tag value
        """
        result = {
            'has_validation_tag': False,
            'status': None,
            'confidence': None,
            'validated_at': None,
            'raw_tag': None
        }

        if not os.path.exists(file_path):
            return result

        if not cls.is_supported(file_path):
            return result

        try:
            audio = MutagenFile(file_path, easy=False)
            if audio is None or audio.tags is None:
                return result

            # Get encoded by field based on format
            ext = Path(file_path).suffix.lower()
            encoded_by = None

            if ext == '.mp3':
                # Try to get TENC frame
                if isinstance(audio, MP3):
                    for key in audio.tags.keys():
                        if key.startswith('TENC'):
                            frame = audio.tags[key]
                            if hasattr(frame, 'text'):
                                encoded_by = str(frame.text[0]) if isinstance(frame.text, list) else str(frame.text)
                            break
            elif ext == '.flac':
                if 'encodedby' in audio:
                    value = audio['encodedby']
                    encoded_by = value[0] if isinstance(value, list) else str(value)
            elif ext in ('.m4a', '.aac'):
                if '\xa9too' in audio:
                    value = audio['\xa9too']
                    encoded_by = value[0] if isinstance(value, list) else str(value)
            elif ext in ('.ogg', '.oga', '.opus'):
                if 'encodedby' in audio:
                    value = audio['encodedby']
                    encoded_by = value[0] if isinstance(value, list) else str(value)

            if not encoded_by or not encoded_by.startswith(cls.VALIDATION_TAG_PREFIX):
                return result

            result['raw_tag'] = encoded_by

            # Parse validation tag: S54:STATUS@CONFIDENCE:TIMESTAMP
            # Example: S54:VALIDATED@95:2026-02-02T12:34:56Z
            try:
                tag_content = encoded_by[len(cls.VALIDATION_TAG_PREFIX):]  # Remove "S54:" prefix

                # Split by @
                status_part, rest = tag_content.split('@', 1)

                # Split by :
                confidence_str, timestamp_str = rest.split(':', 1)

                # Validate and assign
                status = status_part.upper()
                if status in cls.VALIDATION_STATUSES:
                    result['status'] = status
                    result['confidence'] = int(confidence_str)
                    result['validated_at'] = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    result['has_validation_tag'] = True

            except (ValueError, IndexError) as e:
                logger.debug(f"Failed to parse validation tag '{encoded_by}': {e}")

            return result

        except Exception as e:
            logger.error(f"Error reading validation tag from {file_path}: {e}")
            return result

    @classmethod
    def write_metadata(
        cls,
        file_path: str,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        album_artist: Optional[str] = None,
        track_number: Optional[int] = None,
        total_tracks: Optional[int] = None,
        disc_number: Optional[int] = None,
        total_discs: Optional[int] = None,
        year: Optional[int] = None,
        genre: Optional[str] = None,
        overwrite: bool = True
    ) -> MetadataWriteResult:
        """
        Write standard metadata tags to audio file

        Args:
            file_path: Path to audio file
            title: Track title
            artist: Artist name
            album: Album name
            album_artist: Album artist name
            track_number: Track number
            total_tracks: Total tracks in album
            disc_number: Disc number
            total_discs: Total discs
            year: Release year
            genre: Genre
            overwrite: If True, overwrite existing tags. If False, only write if empty.

        Returns:
            MetadataWriteResult with success status and details
        """
        if not os.path.exists(file_path):
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"File not found: {file_path}"
            )

        if not cls.is_supported(file_path):
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=f"Unsupported file format: {file_path}"
            )

        try:
            ext = Path(file_path).suffix.lower()
            tags_written = {}

            if ext == '.mp3':
                tags_written = cls._write_mp3_metadata(
                    file_path, title, artist, album, album_artist,
                    track_number, total_tracks, disc_number, total_discs,
                    year, genre, overwrite
                )
            elif ext == '.flac':
                tags_written = cls._write_flac_metadata(
                    file_path, title, artist, album, album_artist,
                    track_number, total_tracks, disc_number, total_discs,
                    year, genre, overwrite
                )
            elif ext in ('.m4a', '.aac'):
                tags_written = cls._write_mp4_metadata(
                    file_path, title, artist, album, album_artist,
                    track_number, total_tracks, disc_number, total_discs,
                    year, genre, overwrite
                )
            elif ext in ('.ogg', '.oga', '.opus'):
                tags_written = cls._write_ogg_metadata(
                    file_path, title, artist, album, album_artist,
                    track_number, total_tracks, disc_number, total_discs,
                    year, genre, overwrite
                )
            else:
                return MetadataWriteResult(
                    success=False,
                    file_path=file_path,
                    error=f"Unsupported format for metadata writing: {ext}"
                )

            logger.info(f"Successfully wrote metadata to: {file_path}")
            return MetadataWriteResult(
                success=True,
                file_path=file_path,
                tags_written=tags_written
            )

        except Exception as e:
            logger.error(f"Error writing metadata to {file_path}: {e}")
            return MetadataWriteResult(
                success=False,
                file_path=file_path,
                error=str(e)
            )

    @classmethod
    def _write_mp3_metadata(
        cls,
        file_path: str,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str],
        album_artist: Optional[str],
        track_number: Optional[int],
        total_tracks: Optional[int],
        disc_number: Optional[int],
        total_discs: Optional[int],
        year: Optional[int],
        genre: Optional[str],
        overwrite: bool
    ) -> Dict[str, str]:
        """Write metadata to MP3 file"""
        tags_written = {}

        try:
            audio = ID3(file_path)
        except ID3NoHeaderError:
            audio = ID3()
            audio.save(file_path)
            audio = ID3(file_path)

        # Title
        if title and (overwrite or 'TIT2' not in audio):
            audio.delall('TIT2')
            audio.add(TIT2(encoding=3, text=title))
            tags_written['title'] = title

        # Artist
        if artist and (overwrite or 'TPE1' not in audio):
            audio.delall('TPE1')
            audio.add(TPE1(encoding=3, text=artist))
            tags_written['artist'] = artist

        # Album
        if album and (overwrite or 'TALB' not in audio):
            audio.delall('TALB')
            audio.add(TALB(encoding=3, text=album))
            tags_written['album'] = album

        # Album Artist
        if album_artist and (overwrite or 'TPE2' not in audio):
            audio.delall('TPE2')
            audio.add(TPE2(encoding=3, text=album_artist))
            tags_written['album_artist'] = album_artist

        # Track Number
        if track_number and (overwrite or 'TRCK' not in audio):
            track_str = f"{track_number}/{total_tracks}" if total_tracks else str(track_number)
            audio.delall('TRCK')
            audio.add(TRCK(encoding=3, text=track_str))
            tags_written['track_number'] = track_str

        # Disc Number
        if disc_number and (overwrite or 'TPOS' not in audio):
            disc_str = f"{disc_number}/{total_discs}" if total_discs else str(disc_number)
            audio.delall('TPOS')
            audio.add(TPOS(encoding=3, text=disc_str))
            tags_written['disc_number'] = disc_str

        # Year
        if year and (overwrite or 'TDRC' not in audio):
            audio.delall('TDRC')
            audio.add(TDRC(encoding=3, text=str(year)))
            tags_written['year'] = str(year)

        # Genre
        if genre and (overwrite or 'TCON' not in audio):
            audio.delall('TCON')
            audio.add(TCON(encoding=3, text=genre))
            tags_written['genre'] = genre

        audio.save(file_path, v2_version=3)
        return tags_written

    @classmethod
    def _write_flac_metadata(
        cls,
        file_path: str,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str],
        album_artist: Optional[str],
        track_number: Optional[int],
        total_tracks: Optional[int],
        disc_number: Optional[int],
        total_discs: Optional[int],
        year: Optional[int],
        genre: Optional[str],
        overwrite: bool
    ) -> Dict[str, str]:
        """Write metadata to FLAC file"""
        tags_written = {}
        audio = FLAC(file_path)

        if title and (overwrite or 'title' not in audio):
            audio['title'] = title
            tags_written['title'] = title

        if artist and (overwrite or 'artist' not in audio):
            audio['artist'] = artist
            tags_written['artist'] = artist

        if album and (overwrite or 'album' not in audio):
            audio['album'] = album
            tags_written['album'] = album

        if album_artist and (overwrite or 'albumartist' not in audio):
            audio['albumartist'] = album_artist
            tags_written['album_artist'] = album_artist

        if track_number and (overwrite or 'tracknumber' not in audio):
            track_str = f"{track_number}/{total_tracks}" if total_tracks else str(track_number)
            audio['tracknumber'] = track_str
            tags_written['track_number'] = track_str

        if disc_number and (overwrite or 'discnumber' not in audio):
            disc_str = f"{disc_number}/{total_discs}" if total_discs else str(disc_number)
            audio['discnumber'] = disc_str
            tags_written['disc_number'] = disc_str

        if year and (overwrite or 'date' not in audio):
            audio['date'] = str(year)
            tags_written['year'] = str(year)

        if genre and (overwrite or 'genre' not in audio):
            audio['genre'] = genre
            tags_written['genre'] = genre

        audio.save()
        return tags_written

    @classmethod
    def _write_mp4_metadata(
        cls,
        file_path: str,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str],
        album_artist: Optional[str],
        track_number: Optional[int],
        total_tracks: Optional[int],
        disc_number: Optional[int],
        total_discs: Optional[int],
        year: Optional[int],
        genre: Optional[str],
        overwrite: bool
    ) -> Dict[str, str]:
        """Write metadata to M4A/AAC file"""
        tags_written = {}
        audio = MP4(file_path)

        if title and (overwrite or '\xa9nam' not in audio):
            audio['\xa9nam'] = title
            tags_written['title'] = title

        if artist and (overwrite or '\xa9ART' not in audio):
            audio['\xa9ART'] = artist
            tags_written['artist'] = artist

        if album and (overwrite or '\xa9alb' not in audio):
            audio['\xa9alb'] = album
            tags_written['album'] = album

        if album_artist and (overwrite or 'aART' not in audio):
            audio['aART'] = album_artist
            tags_written['album_artist'] = album_artist

        if track_number and (overwrite or 'trkn' not in audio):
            audio['trkn'] = [(track_number, total_tracks or 0)]
            tags_written['track_number'] = f"{track_number}/{total_tracks or 0}"

        if disc_number and (overwrite or 'disk' not in audio):
            audio['disk'] = [(disc_number, total_discs or 0)]
            tags_written['disc_number'] = f"{disc_number}/{total_discs or 0}"

        if year and (overwrite or '\xa9day' not in audio):
            audio['\xa9day'] = str(year)
            tags_written['year'] = str(year)

        if genre and (overwrite or '\xa9gen' not in audio):
            audio['\xa9gen'] = genre
            tags_written['genre'] = genre

        audio.save()
        return tags_written

    @classmethod
    def _write_ogg_metadata(
        cls,
        file_path: str,
        title: Optional[str],
        artist: Optional[str],
        album: Optional[str],
        album_artist: Optional[str],
        track_number: Optional[int],
        total_tracks: Optional[int],
        disc_number: Optional[int],
        total_discs: Optional[int],
        year: Optional[int],
        genre: Optional[str],
        overwrite: bool
    ) -> Dict[str, str]:
        """Write metadata to OGG/Opus file"""
        tags_written = {}
        audio = OggVorbis(file_path)

        if title and (overwrite or 'title' not in audio):
            audio['title'] = title
            tags_written['title'] = title

        if artist and (overwrite or 'artist' not in audio):
            audio['artist'] = artist
            tags_written['artist'] = artist

        if album and (overwrite or 'album' not in audio):
            audio['album'] = album
            tags_written['album'] = album

        if album_artist and (overwrite or 'albumartist' not in audio):
            audio['albumartist'] = album_artist
            tags_written['album_artist'] = album_artist

        if track_number and (overwrite or 'tracknumber' not in audio):
            track_str = f"{track_number}/{total_tracks}" if total_tracks else str(track_number)
            audio['tracknumber'] = track_str
            tags_written['track_number'] = track_str

        if disc_number and (overwrite or 'discnumber' not in audio):
            disc_str = f"{disc_number}/{total_discs}" if total_discs else str(disc_number)
            audio['discnumber'] = disc_str
            tags_written['disc_number'] = disc_str

        if year and (overwrite or 'date' not in audio):
            audio['date'] = str(year)
            tags_written['year'] = str(year)

        if genre and (overwrite or 'genre' not in audio):
            audio['genre'] = genre
            tags_written['genre'] = genre

        audio.save()
        return tags_written

    @classmethod
    def write_all(
        cls,
        file_path: str,
        recording_mbid: Optional[str] = None,
        artist_mbid: Optional[str] = None,
        release_mbid: Optional[str] = None,
        release_group_mbid: Optional[str] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        album_artist: Optional[str] = None,
        track_number: Optional[int] = None,
        total_tracks: Optional[int] = None,
        disc_number: Optional[int] = None,
        total_discs: Optional[int] = None,
        year: Optional[int] = None,
        genre: Optional[str] = None,
        overwrite_mbid: bool = False,
        overwrite_metadata: bool = True
    ) -> MetadataWriteResult:
        """
        Write both MBIDs and metadata tags to audio file

        Args:
            file_path: Path to audio file
            recording_mbid: MusicBrainz Recording ID
            artist_mbid: MusicBrainz Artist ID
            release_mbid: MusicBrainz Release ID
            release_group_mbid: MusicBrainz Release Group ID
            title: Track title
            artist: Artist name
            album: Album name
            album_artist: Album artist name
            track_number: Track number
            total_tracks: Total tracks in album
            disc_number: Disc number
            total_discs: Total discs
            year: Release year
            genre: Genre
            overwrite_mbid: Overwrite existing MBIDs
            overwrite_metadata: Overwrite existing metadata tags

        Returns:
            MetadataWriteResult with combined results
        """
        all_mbids_written = {}
        all_tags_written = {}
        errors = []

        # Write MBIDs if any provided
        if any([recording_mbid, artist_mbid, release_mbid, release_group_mbid]):
            mbid_result = cls.write_mbids(
                file_path=file_path,
                recording_mbid=recording_mbid,
                artist_mbid=artist_mbid,
                release_mbid=release_mbid,
                release_group_mbid=release_group_mbid,
                overwrite=overwrite_mbid
            )
            if mbid_result.success:
                all_mbids_written = mbid_result.mbids_written
            else:
                errors.append(f"MBID: {mbid_result.error}")

        # Write metadata if any provided
        if any([title, artist, album, album_artist, track_number, disc_number, year, genre]):
            metadata_result = cls.write_metadata(
                file_path=file_path,
                title=title,
                artist=artist,
                album=album,
                album_artist=album_artist,
                track_number=track_number,
                total_tracks=total_tracks,
                disc_number=disc_number,
                total_discs=total_discs,
                year=year,
                genre=genre,
                overwrite=overwrite_metadata
            )
            if metadata_result.success:
                all_tags_written = metadata_result.tags_written
            else:
                errors.append(f"Metadata: {metadata_result.error}")

        success = len(errors) == 0
        error_msg = "; ".join(errors) if errors else None

        return MetadataWriteResult(
            success=success,
            file_path=file_path,
            error=error_msg,
            mbids_written=all_mbids_written,
            tags_written=all_tags_written
        )


# Convenience functions
def write_mbids(
    file_path: str,
    recording_mbid: Optional[str] = None,
    artist_mbid: Optional[str] = None,
    release_mbid: Optional[str] = None,
    release_group_mbid: Optional[str] = None,
    overwrite: bool = False
) -> MetadataWriteResult:
    """Write MBIDs to audio file"""
    return MetadataWriter.write_mbids(
        file_path=file_path,
        recording_mbid=recording_mbid,
        artist_mbid=artist_mbid,
        release_mbid=release_mbid,
        release_group_mbid=release_group_mbid,
        overwrite=overwrite
    )


def verify_mbid_in_file(file_path: str) -> Dict[str, Any]:
    """Verify if MBID exists in file comments"""
    return MetadataWriter.verify_mbid_in_file(file_path)


def write_metadata(
    file_path: str,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    **kwargs
) -> MetadataWriteResult:
    """Write metadata to audio file"""
    return MetadataWriter.write_metadata(
        file_path=file_path,
        title=title,
        artist=artist,
        album=album,
        **kwargs
    )


def write_validation_tag(
    file_path: str,
    status: str,
    confidence: int,
    timestamp: Optional[datetime] = None
) -> MetadataWriteResult:
    """Write validation tag to audio file's Encoded By field"""
    return MetadataWriter.write_validation_tag(
        file_path=file_path,
        status=status,
        confidence=confidence,
        timestamp=timestamp
    )


def read_validation_tag(file_path: str) -> Dict[str, Any]:
    """Read validation tag from audio file's Encoded By field"""
    return MetadataWriter.read_validation_tag(file_path)
