"""
Security utilities for Studio54
Input validation, sanitization, and rate limiting
"""
import re
from typing import Optional
from fastapi import HTTPException, status


# Rate limiting - to be initialized by main.py
_limiter = None


def set_limiter(limiter):
    """Set the global rate limiter instance"""
    global _limiter
    _limiter = limiter


def rate_limit(limit_string: str):
    """
    Decorator for rate limiting API endpoints

    Args:
        limit_string: Rate limit string (e.g., "100/minute", "10/second")

    Usage:
        @router.get("/endpoint")
        @rate_limit("100/minute")
        async def my_endpoint(request: Request):
            ...
    """
    def decorator(func):
        if _limiter:
            return _limiter.limit(limit_string)(func)
        return func
    return decorator


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize a filename to prevent security issues

    Args:
        filename: The filename to sanitize
        max_length: Maximum allowed filename length

    Returns:
        str: Sanitized filename safe for filesystem use
    """
    # Remove path separators
    filename = filename.replace('/', '_').replace('\\', '_')

    # Remove null bytes and dangerous characters
    filename = filename.replace('\x00', '')
    filename = re.sub(r'[<>:"|?*]', '_', filename)

    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')

    # Ensure filename isn't empty
    if not filename:
        filename = 'unnamed'

    # Truncate to max length
    if len(filename) > max_length:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        if ext:
            max_name_length = max_length - len(ext) - 1
            filename = f"{name[:max_name_length]}.{ext}"
        else:
            filename = filename[:max_length]

    return filename


def validate_uuid(uuid_string: str, field_name: str = "ID") -> bool:
    """
    Validate UUID format

    Args:
        uuid_string: The UUID string to validate
        field_name: Name of the field for error messages

    Returns:
        bool: True if UUID is valid

    Raises:
        HTTPException: If UUID is invalid
    """
    import uuid as uuid_lib

    try:
        uuid_lib.UUID(uuid_string)
        return True
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format (must be valid UUID)"
        )


def validate_mbid(mbid: str) -> bool:
    """
    Validate MusicBrainz ID format (UUIDs with hyphens)

    Args:
        mbid: The MusicBrainz ID to validate

    Returns:
        bool: True if MBID is valid

    Raises:
        HTTPException: If MBID is invalid
    """
    if not mbid or len(mbid) < 32:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MusicBrainz ID format"
        )

    return validate_uuid(mbid, "MusicBrainz ID")


def validate_pagination(limit: int, offset: int, max_limit: int = 10000) -> tuple[int, int]:
    """
    Validate and sanitize pagination parameters

    Args:
        limit: Requested number of results
        offset: Offset for pagination
        max_limit: Maximum allowed limit

    Returns:
        tuple: (validated_limit, validated_offset)

    Raises:
        HTTPException: If parameters are invalid
    """
    if limit < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit must be at least 1"
        )

    if limit > max_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Limit cannot exceed {max_limit}"
        )

    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Offset cannot be negative"
        )

    return limit, offset


def validate_api_key(api_key: str, field_name: str = "API key") -> bool:
    """
    Validate API key format (basic validation)

    Args:
        api_key: The API key to validate
        field_name: Name of the field for error messages

    Returns:
        bool: True if API key is valid

    Raises:
        HTTPException: If API key is invalid
    """
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} cannot be empty"
        )

    if len(api_key) < 10 or len(api_key) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be between 10 and 255 characters"
        )

    # Check for dangerous characters
    if any(char in api_key for char in ['\x00', '\r', '\n', ';', '&', '|']):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} contains invalid characters"
        )

    return True


def validate_url(url: str, field_name: str = "URL") -> bool:
    """
    Validate URL format

    Args:
        url: The URL to validate
        field_name: Name of the field for error messages

    Returns:
        bool: True if URL is valid

    Raises:
        HTTPException: If URL is invalid
    """
    if not url or not url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} cannot be empty"
        )

    # Basic URL validation
    url_pattern = r'^https?://'
    if not re.match(url_pattern, url.lower()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must start with http:// or https://"
        )

    return True
