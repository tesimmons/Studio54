"""
Cover Art Service
Handles cover art upload and retrieval for all entity types.
Supports file uploads and fetching from a remote URL.
TIFF and BMP are accepted but auto-converted to JPEG for browser compatibility.
"""

import io
import logging
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image

logger = logging.getLogger(__name__)

BASE_ART_DIR = Path("/docker/studio54")

# Content types accepted on ingest (superset of what browsers can display)
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/tiff",
    "image/bmp",
    "image/x-bmp",
}

# Types that browsers cannot display natively → convert to JPEG on save
CONVERT_TO_JPEG = {"image/tiff", "image/bmp", "image/x-bmp"}

# Extension → content-type for URL sniffing fallback
EXT_TO_CT = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".tif":  "image/tiff",
    ".tiff": "image/tiff",
    ".bmp":  "image/bmp",
}

# Stored content-type → file extension
CT_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png":  "png",
    "image/gif":  "gif",
    "image/webp": "webp",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _art_dir(entity_type: str) -> Path:
    """Return the directory for storing cover art of the given entity type."""
    return BASE_ART_DIR / f"{entity_type}-art"


def _normalise_content_type(ct: str) -> str:
    """Normalise minor content-type variants (e.g. image/jpg → image/jpeg)."""
    ct = ct.split(";")[0].strip().lower()
    if ct == "image/jpg":
        ct = "image/jpeg"
    return ct


def _save_bytes(entity_type: str, entity_id: str, content: bytes, content_type: str) -> str:
    """
    Write image bytes to disk, converting TIFF/BMP → JPEG first.

    Returns the filesystem path of the saved file.
    """
    if content_type in CONVERT_TO_JPEG:
        try:
            img = Image.open(io.BytesIO(content))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            content = buf.getvalue()
            content_type = "image/jpeg"
            logger.info(f"Converted {content_type} → JPEG for {entity_type} {entity_id}")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not convert image to JPEG: {e}",
            )

    ext = CT_TO_EXT.get(content_type, "jpg")
    art_dir = _art_dir(entity_type)
    art_dir.mkdir(parents=True, exist_ok=True)
    filepath = art_dir / f"{entity_id}.{ext}"

    # Remove any existing cover art with a different extension
    for old in art_dir.glob(f"{entity_id}.*"):
        old.unlink()

    filepath.write_bytes(content)
    logger.info(f"Saved cover art for {entity_type} {entity_id}: {filepath}")
    return str(filepath)


async def save_entity_cover_art(
    entity_type: str,
    entity_id: str,
    file: UploadFile,
) -> str:
    """
    Validate and save an uploaded cover art file to disk.

    Accepts JPEG, PNG, GIF, WebP, TIFF, BMP.
    TIFF and BMP are auto-converted to JPEG for browser compatibility.

    Returns the filesystem path where the file was saved.
    """
    ct = _normalise_content_type(file.content_type or "")

    if ct not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Accepted formats: JPEG, PNG, GIF, WebP, TIFF, BMP",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image must be under 10 MB",
        )

    return _save_bytes(entity_type, entity_id, content, ct)


async def fetch_and_save_entity_cover_art_from_url(
    entity_type: str,
    entity_id: str,
    image_url: str,
) -> str:
    """
    Fetch a remote image URL, validate it, and save it as cover art.

    Accepts JPEG, PNG, GIF, WebP, TIFF, BMP.
    TIFF and BMP are auto-converted to JPEG for browser compatibility.

    Returns the filesystem path where the file was saved.
    """
    if not image_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(
                image_url,
                headers={"User-Agent": "Studio54/1.0 (cover-art-fetcher)"},
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request timed out fetching the image URL")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Remote server returned {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to fetch image: {str(e)}")

    ct = _normalise_content_type(response.headers.get("content-type", ""))

    # Fall back to URL extension if content-type is unhelpful
    if ct not in ALLOWED_CONTENT_TYPES:
        suffix = PurePosixPath(urlparse(image_url).path).suffix.lower()
        ct = EXT_TO_CT.get(suffix, ct)

    if ct not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL must point to a JPEG, PNG, GIF, WebP, TIFF, or BMP image (detected: {ct or 'unknown'})",
        )

    content = response.content
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image must be under 10 MB",
        )

    return _save_bytes(entity_type, entity_id, content, ct)


def serve_entity_cover_art(
    entity_type: str,
    entity_id: str,
    cover_art_url: str | None,
):
    """
    Serve a cover art image for an entity.

    Handles four cases for cover_art_url stored in the DB:
      1. External http/https URL  → 302 redirect to that URL
      2. Internal /api/v1/ path   → 302 redirect to that internal endpoint
      3. Local filesystem path    → stream the file directly
      4. null / missing           → scan art directory, or 404
    """
    from fastapi.responses import RedirectResponse

    if cover_art_url:
        # Case 1: external URL (e.g. Cover Art Archive, MusicBrainz images)
        if cover_art_url.startswith(("http://", "https://")):
            return RedirectResponse(url=cover_art_url, status_code=302)

        # Case 2: internal API path (e.g. /api/v1/books/{id}/cover-art)
        # Only redirect if it's not a self-referential loop (entity_id not in the URL)
        if cover_art_url.startswith("/api/v1/") and entity_id not in cover_art_url:
            return RedirectResponse(url=cover_art_url, status_code=302)

        # Case 3: local filesystem path
        filepath = Path(cover_art_url)
        if filepath.exists():
            ext = filepath.suffix.lower()
            media_type = (
                "image/jpeg" if ext in (".jpg", ".jpeg")
                else "image/png"  if ext == ".png"
                else "image/gif"  if ext == ".gif"
                else "image/webp" if ext == ".webp"
                else "image/jpeg"
            )
            return FileResponse(filepath, media_type=media_type)

    # Case 3: scan the entity art directory for any locally-saved file
    art_dir = _art_dir(entity_type)
    for ext in ("jpg", "jpeg", "png", "gif", "webp"):
        candidate = art_dir / f"{entity_id}.{ext}"
        if candidate.exists():
            media_type = (
                "image/jpeg" if ext in ("jpg", "jpeg")
                else "image/png"  if ext == "png"
                else "image/gif"  if ext == "gif"
                else "image/webp"
            )
            return FileResponse(candidate, media_type=media_type)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No cover art found",
    )
