"""
Listen & Add API Router
Audio recognition via AcoustID fingerprinting with AudD fallback and MusicBrainz enrichment.

Pipeline:
1. Try AcoustID (free, open-source fingerprint DB) — works for file-based lookups
2. If AcoustID fails, try AudD (commercial recognition API designed for mic captures)
3. Enrich metadata from MusicBrainz if needed
4. Check local library for existing artist/album
"""

import logging
import os
import tempfile

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_any_user
from app.models.artist import Artist
from app.models.album import Album
from app.models.user import User
from app.security import rate_limit
from app.services.acoustid_service import get_acoustid_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/listen/identify")
@rate_limit("10/minute")
async def identify_audio(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_user),
):
    """
    Identify a song from recorded audio using AcoustID fingerprinting.
    Accepts WAV, WebM, or OGG audio captured from the browser microphone.

    Pipeline:
    1. fpcalc generates a Chromaprint fingerprint from the audio
    2. AcoustID API matches the fingerprint to recording MBIDs
    3. If AcoustID metadata is sparse, MusicBrainz API enriches with full details
    4. Checks local library for existing artist/album
    """
    # Validate file type (strip codec params like "audio/webm;codecs=opus")
    raw_type = (file.content_type or "").split(";")[0].strip().lower()
    allowed_types = {
        "audio/wav", "audio/wave", "audio/x-wav",
        "audio/webm", "audio/ogg", "audio/mpeg",
        "application/octet-stream", "",
    }
    if raw_type and raw_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {file.content_type}. Send WAV, WebM, or OGG audio.",
        )

    # Save uploaded audio to a temp file
    tmp_path = None
    try:
        contents = await file.read()
        file_size = len(contents)
        # Log WAV header and signal level info
        header_info = ""
        if file_size >= 44 and contents[:4] == b"RIFF":
            import struct
            import array
            channels = struct.unpack_from("<H", contents, 22)[0]
            sample_rate = struct.unpack_from("<I", contents, 24)[0]
            bits_per_sample = struct.unpack_from("<H", contents, 34)[0]
            audio_seconds = (file_size - 44) / (sample_rate * channels * bits_per_sample // 8) if sample_rate else 0
            # Compute peak and RMS of PCM data for diagnostics
            pcm_data = array.array("h", contents[44:])
            peak_val = max(abs(s) for s in pcm_data) if pcm_data else 0
            rms_val = (sum(s * s for s in pcm_data) / len(pcm_data)) ** 0.5 if pcm_data else 0
            header_info = (
                f", WAV: {sample_rate}Hz {bits_per_sample}bit {channels}ch {audio_seconds:.1f}s"
                f", peak={peak_val}/32768 ({peak_val/32768:.3f}), RMS={rms_val:.0f} ({rms_val/32768:.4f})"
            )
        logger.info(f"Listen/identify: received {file_size} bytes, type={file.content_type}{header_info}")

        if file_size < 1000:
            raise HTTPException(status_code=400, detail="Audio file too small")
        if file_size > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 50MB)")

        suffix = ".wav"
        if "webm" in raw_type:
            suffix = ".webm"
        elif "ogg" in raw_type:
            suffix = ".ogg"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        # Step 1: Run fpcalc fingerprinting
        acoustid = get_acoustid_service()
        fp_result = acoustid.fingerprint_file(tmp_path)
        if not fp_result:
            logger.warning("Listen/identify: fpcalc failed to generate fingerprint")
            return {
                "identified": False,
                "message": "Could not generate audio fingerprint. Try recording for longer or in a quieter environment.",
            }

        fingerprint, duration = fp_result
        logger.info(
            f"Listen/identify: fingerprint generated, duration={duration}s, "
            f"fingerprint_length={len(fingerprint)} chars"
        )

        # Step 2: Look up on AcoustID
        results = acoustid.lookup(fingerprint, duration)
        logger.info(f"Listen/identify: AcoustID returned {len(results)} results")
        if results:
            for i, r in enumerate(results[:3]):
                logger.info(
                    f"Listen/identify: result[{i}] score={r.get('score', 0):.3f}, "
                    f"recordings={len(r.get('recordings', []))}, "
                    f"id={r.get('id', 'N/A')}"
                )
        # Variables for identified song metadata
        title = None
        artist_name = None
        artist_mbid = None
        album_name = None
        album_mbid = None
        recording_mbid = None
        score = 0.0
        source = None  # "acoustid" or "audd"

        # Try to extract metadata from AcoustID results
        if results:
            best = results[0]
            score = best.get("score", 0)
            logger.info(f"Listen/identify: best AcoustID score={score}, {len(results)} total results")

            if score >= 0.3:
                recordings = best.get("recordings", [])
                if recordings:
                    recording = _pick_best_recording(recordings)
                    recording_mbid = recording.get("id")
                    title = recording.get("title")
                    artists = recording.get("artists", [])
                    artist_name = artists[0].get("name") if artists else None
                    artist_mbid = artists[0].get("id") if artists else None
                    release_groups = recording.get("releasegroups", [])
                    album_name = release_groups[0].get("title") if release_groups else None
                    album_mbid = release_groups[0].get("id") if release_groups else None
                    source = "acoustid"

        # Step 2b: If AcoustID failed, try AudD as fallback (designed for mic captures)
        if not title:
            logger.info("Listen/identify: AcoustID failed, trying AudD fallback...")
            audd_result = _try_audd_recognition(tmp_path)
            if audd_result:
                title = audd_result.get("title")
                artist_name = audd_result.get("artist")
                album_name = audd_result.get("album")
                score = 0.85  # AudD doesn't return a score; use a reasonable default
                source = "audd"
                logger.info(
                    f"Listen/identify: AudD identified '{title}' by '{artist_name}' "
                    f"album='{album_name}'"
                )

        if not title:
            logger.warning(
                f"Listen/identify: no results from AcoustID or AudD for "
                f"duration={duration}s, fingerprint_len={len(fingerprint)}"
            )
            return {
                "identified": False,
                "message": "Could not identify the song. No matches found.",
            }

        # Step 3: Enrich from MusicBrainz if metadata is incomplete
        if recording_mbid and (not title or not artist_name or not album_name):
            logger.info(f"Listen/identify: enriching from MusicBrainz for recording {recording_mbid}")
            mb_data = _lookup_musicbrainz_recording(recording_mbid)
            if mb_data:
                if not title:
                    title = mb_data.get("title")
                if not artist_name and mb_data.get("artist_name"):
                    artist_name = mb_data["artist_name"]
                if not artist_mbid and mb_data.get("artist_mbid"):
                    artist_mbid = mb_data["artist_mbid"]
                if not album_name and mb_data.get("album_name"):
                    album_name = mb_data["album_name"]
                if not album_mbid and mb_data.get("album_mbid"):
                    album_mbid = mb_data["album_mbid"]

        # If we got a result from AudD but no MBIDs, try to find the artist in MusicBrainz
        if source == "audd" and artist_name and not artist_mbid:
            mb_artist = _search_musicbrainz_artist(artist_name)
            if mb_artist:
                artist_mbid = mb_artist.get("id")
                logger.info(f"Listen/identify: found artist MBID {artist_mbid} for '{artist_name}'")

        if not title:
            title = "Unknown"
        if not artist_name:
            artist_name = "Unknown"

        logger.info(
            f"Listen/identify: identified '{title}' by '{artist_name}' "
            f"(album='{album_name}', score={score:.2f}, source={source})"
        )

        # Step 4: Check if artist exists in library
        artist_data = {
            "name": artist_name,
            "mbid": artist_mbid,
            "exists_in_library": False,
            "library_id": None,
        }
        existing_artist = None
        if artist_mbid:
            existing_artist = db.query(Artist).filter(
                Artist.musicbrainz_id == artist_mbid
            ).first()
        if not existing_artist:
            existing_artist = db.query(Artist).filter(
                Artist.name == artist_name
            ).first()
        if existing_artist:
            artist_data["exists_in_library"] = True
            artist_data["library_id"] = str(existing_artist.id)

        # Check if album exists in library
        album_data = {
            "name": album_name,
            "mbid": album_mbid,
            "exists_in_library": False,
            "library_id": None,
        }
        if album_name:
            existing_album = None
            if album_mbid:
                existing_album = db.query(Album).filter(
                    Album.musicbrainz_id == album_mbid
                ).first()
            if not existing_album and existing_artist:
                existing_album = db.query(Album).filter(
                    Album.title == album_name,
                    Album.artist_id == existing_artist.id,
                ).first()
            if existing_album:
                album_data["exists_in_library"] = True
                album_data["library_id"] = str(existing_album.id)

        return {
            "identified": True,
            "title": title,
            "recording_mbid": recording_mbid,
            "artist": artist_data,
            "album": album_data,
            "confidence": round(score, 3),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error identifying audio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to identify audio")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _pick_best_recording(recordings: list) -> dict:
    """Pick the recording with the most complete metadata."""
    best = recordings[0]
    best_score = 0
    for rec in recordings:
        s = 0
        if rec.get("title"):
            s += 2
        if rec.get("artists"):
            s += 2
        if rec.get("releasegroups"):
            s += len(rec["releasegroups"])
        if s > best_score:
            best_score = s
            best = rec
    return best


def _lookup_musicbrainz_recording(recording_mbid: str) -> dict | None:
    """
    Look up a recording on MusicBrainz (local DB first, then remote API).
    Returns dict with title, artist_name, artist_mbid, album_name, album_mbid
    or None on failure.
    """
    try:
        from app.services.musicbrainz_client import get_musicbrainz_client

        mb = get_musicbrainz_client()
        data = mb.get_recording(recording_mbid, includes=["artists", "releases"])
        if not data:
            logger.debug(f"MusicBrainz lookup returned nothing for recording {recording_mbid}")
            return None

        result = {"title": data.get("title")}

        # Extract artist
        artist_credit = data.get("artist-credit", [])
        if artist_credit:
            first_artist = artist_credit[0]
            if isinstance(first_artist, dict):
                artist_obj = first_artist.get("artist", first_artist)
                result["artist_name"] = artist_obj.get("name") or first_artist.get("name")
                result["artist_mbid"] = artist_obj.get("id") or first_artist.get("id")
        # Also check flat artist fields (local DB format)
        if not result.get("artist_name"):
            result["artist_name"] = data.get("artist_name") or data.get("artist")
        if not result.get("artist_mbid"):
            result["artist_mbid"] = data.get("artist_mbid") or data.get("artist_id")

        # Extract release (album)
        releases = data.get("releases", [])
        if releases:
            # Prefer official releases
            release = releases[0]
            for r in releases:
                if r.get("status", "").lower() == "official":
                    release = r
                    break
            result["album_name"] = release.get("title")
            # Release group MBID is what Studio54 uses for albums
            rg = release.get("release-group", {})
            result["album_mbid"] = rg.get("id") if rg else release.get("id")

        logger.info(
            f"MusicBrainz enrichment: '{result.get('title')}' by '{result.get('artist_name')}' "
            f"album='{result.get('album_name')}'"
        )
        return result

    except Exception as e:
        logger.warning(f"MusicBrainz recording lookup failed for {recording_mbid}: {e}")
        return None


def _try_audd_recognition(audio_file_path: str) -> dict | None:
    """
    Try to identify audio using AudD music recognition API.
    Designed for acoustic/microphone captures where AcoustID fails.

    Requires AUDD_API_TOKEN env var. Falls back gracefully if not configured.
    Returns dict with title, artist, album or None on failure.
    """
    api_token = os.getenv("AUDD_API_TOKEN")
    if not api_token:
        logger.info("Listen/identify: AUDD_API_TOKEN not set, skipping AudD fallback")
        return None

    try:
        with open(audio_file_path, "rb") as f:
            resp = http_requests.post(
                "https://api.audd.io/",
                data={"api_token": api_token, "return": "musicbrainz"},
                files={"file": ("audio.wav", f, "audio/wav")},
                timeout=30,
            )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "success":
            error = data.get("error", {})
            logger.warning(
                f"AudD API error: code={error.get('error_code')}, "
                f"message={error.get('error_message')}"
            )
            return None

        result = data.get("result")
        if not result:
            logger.info("Listen/identify: AudD returned no match")
            return None

        logger.info(
            f"AudD recognized: '{result.get('title')}' by '{result.get('artist')}' "
            f"album='{result.get('album')}'"
        )
        return result

    except Exception as e:
        logger.warning(f"AudD recognition failed: {e}")
        return None


def _search_musicbrainz_artist(artist_name: str) -> dict | None:
    """
    Search for an artist on MusicBrainz by name.
    Returns dict with 'id' (MBID) and 'name', or None.
    """
    try:
        from app.services.musicbrainz_client import get_musicbrainz_client

        mb = get_musicbrainz_client()
        results = mb.search_artist(artist_name, limit=1)
        if results:
            artist = results[0] if isinstance(results, list) else results
            return {"id": artist.get("id"), "name": artist.get("name")}
        return None
    except Exception as e:
        logger.debug(f"MusicBrainz artist search failed for '{artist_name}': {e}")
        return None
