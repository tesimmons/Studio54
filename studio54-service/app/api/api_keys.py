"""
API Keys Management
Stores Studio54 third-party API keys in studio54-keys.env,
loads them into os.environ on startup, and updates live without a full stack restart.

Alongside each key we also persist a `{KEY}_INSTALLED_AT` date (ISO format YYYY-MM-DD)
so that keys with known expiry periods (e.g. Hardcover's 1-year JWT) can display a
countdown and renewal reminder.
"""

import logging
import os
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_director
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

# Path to Studio54's own API keys file (writable inside container)
KEYS_FILE = Path("/app/compose/studio54-keys.env")

# ---------------------------------------------------------------------------
# Key registry — defines every managed key and its metadata
# ---------------------------------------------------------------------------

API_KEY_DEFS = [
    {
        "id": "HARDCOVER_API_KEY",
        "label": "Hardcover",
        "description": "Fallback source for author bios, author photos, and book cover art.",
        "docs_url": "https://hardcover.app/account/api",
        "affects": ["studio54-worker"],   # containers to restart when key changes
        "expiry_days": 365,               # Hardcover JWTs expire after 1 year
    },
    {
        "id": "FANART_API_KEY",
        "label": "Fanart.tv",
        "description": "High-quality artist images and album artwork.",
        "docs_url": "https://fanart.tv/get-an-api-key/",
        "affects": ["studio54-worker"],
        "expiry_days": None,
    },
    {
        "id": "LASTFM_API_KEY",
        "label": "Last.fm",
        "description": "Artist biographies and music metadata.",
        "docs_url": "https://www.last.fm/api/account/create",
        "affects": ["studio54-worker"],
        "expiry_days": None,
    },
    {
        "id": "ACOUSTID_API_KEY",
        "label": "AcoustID",
        "description": "Audio fingerprinting for automatic track identification.",
        "docs_url": "https://acoustid.org/login",
        "affects": ["studio54-worker"],
        "expiry_days": None,
    },
    {
        "id": "AUDD_API_TOKEN",
        "label": "AUDD",
        "description": "Music recognition and lyrics lookup.",
        "docs_url": "https://audd.io/",
        "affects": ["studio54-worker"],
        "expiry_days": None,
    },
]

# ---------------------------------------------------------------------------
# .env file helpers
# ---------------------------------------------------------------------------

def _read_keys_file() -> dict[str, str]:
    """Parse studio54-keys.env and return {KEY: value} dict."""
    result: dict[str, str] = {}
    if not KEYS_FILE.exists():
        return result
    for line in KEYS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        result[key] = val
    return result


def _write_key(key_name: str, value: str):
    """Write or update a single key in studio54-keys.env."""
    lines: list[str] = []
    found = False

    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key_name}=") or stripped.startswith(f"{key_name} ="):
                lines.append(f"{key_name}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key_name}={value}")

    KEYS_FILE.write_text("\n".join(lines) + "\n")


def _delete_key(key_name: str):
    """Remove a key (and its _INSTALLED_AT companion) from studio54-keys.env."""
    if not KEYS_FILE.exists():
        return
    installed_at_key = f"{key_name}_INSTALLED_AT"
    lines = [
        line for line in KEYS_FILE.read_text().splitlines()
        if not (
            line.strip().startswith(f"{key_name}=")
            or line.strip().startswith(f"{key_name} =")
            or line.strip().startswith(f"{installed_at_key}=")
            or line.strip().startswith(f"{installed_at_key} =")
        )
    ]
    KEYS_FILE.write_text("\n".join(lines) + "\n")


def _get_installed_at(key_name: str) -> Optional[str]:
    """Return the stored YYYY-MM-DD installation date for a key, or None."""
    return _read_keys_file().get(f"{key_name}_INSTALLED_AT")


def _set_installed_at(key_name: str, iso_date: str):
    """Write or update the _INSTALLED_AT companion entry."""
    _write_key(f"{key_name}_INSTALLED_AT", iso_date)


def load_keys_into_environ():
    """
    Called at startup: load all keys from studio54-keys.env into os.environ.
    Keys in the file override whatever was set in the main .env / docker env.
    Also backfills a today-dated INSTALLED_AT for any configured key that lacks one.
    """
    keys = _read_keys_file()
    for k, v in keys.items():
        if v:
            os.environ[k] = v
            logger.debug(f"[api_keys] Loaded {k} from studio54-keys.env")

    # Backfill INSTALLED_AT for keys that are present but have no date yet
    for defn in API_KEY_DEFS:
        kid = defn["id"]
        if keys.get(kid) and not keys.get(f"{kid}_INSTALLED_AT"):
            today = date.today().isoformat()
            _set_installed_at(kid, today)
            logger.info(f"[api_keys] Backfilled {kid}_INSTALLED_AT = {today}")


def _restart_containers(names: list[str]):
    """Restart named containers via Docker SDK (socket available at /var/run/docker.sock)."""
    try:
        import docker  # type: ignore
        client = docker.from_env()
        for name in names:
            try:
                container = client.containers.get(name)
                container.restart(timeout=10)
                logger.info(f"[api_keys] Restarted container: {name}")
            except Exception as e:
                logger.warning(f"[api_keys] Could not restart {name}: {e}")
    except Exception as e:
        logger.warning(f"[api_keys] Docker restart failed: {e}")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ApiKeyStatus(BaseModel):
    id: str
    label: str
    description: str
    docs_url: str
    configured: bool
    key_preview: Optional[str] = None    # last 4 chars, rest masked
    expiry_days: Optional[int] = None    # None = no expiry tracking
    installed_at: Optional[str] = None   # YYYY-MM-DD
    expires_at: Optional[str] = None     # YYYY-MM-DD (computed)
    days_until_expiry: Optional[int] = None  # negative = already expired


class ApiKeyUpdate(BaseModel):
    value: str


class ApiKeyInstalledAtUpdate(BaseModel):
    installed_at: str  # YYYY-MM-DD


class ApiKeyTestResult(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_live_value(key_name: str) -> Optional[str]:
    """Return the live value of an API key (os.environ first, file second)."""
    # os.environ is authoritative since we update it on save
    return os.environ.get(key_name) or _read_keys_file().get(key_name) or None


def _make_preview(value: str) -> str:
    if len(value) >= 4:
        return "•" * max(0, len(value) - 4) + value[-4:]
    return "••••"


def _build_status(defn: dict, value: Optional[str]) -> ApiKeyStatus:
    """Build a complete ApiKeyStatus including expiry info."""
    expiry_days = defn.get("expiry_days")
    installed_at_str = _get_installed_at(defn["id"]) if value else None
    expires_at_str = None
    days_until_expiry = None

    if installed_at_str and expiry_days:
        try:
            installed = date.fromisoformat(installed_at_str)
            expires = installed + timedelta(days=expiry_days)
            expires_at_str = expires.isoformat()
            days_until_expiry = (expires - date.today()).days
        except ValueError:
            pass

    return ApiKeyStatus(
        id=defn["id"],
        label=defn["label"],
        description=defn["description"],
        docs_url=defn["docs_url"],
        configured=bool(value),
        key_preview=_make_preview(value) if value else None,
        expiry_days=expiry_days,
        installed_at=installed_at_str,
        expires_at=expires_at_str,
        days_until_expiry=days_until_expiry,
    )


# ---------------------------------------------------------------------------
# Test functions per key
# ---------------------------------------------------------------------------

def _test_hardcover(api_key: str) -> ApiKeyTestResult:
    try:
        resp = requests.post(
            "https://api.hardcover.app/v1/graphql",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": "{ books(limit: 1) { id title } }"},
            timeout=15,
        )
        if resp.status_code in (401, 403):
            return ApiKeyTestResult(success=False, message="Invalid API key (unauthorized)")
        body = resp.json()
        errors = body.get("errors", [])
        for err in errors:
            msg = str(err.get("message", "")).lower()
            if any(w in msg for w in ("unauthorized", "forbidden", "authentication", "jwt", "invalid")):
                return ApiKeyTestResult(success=False, message=f"Auth error: {err.get('message')}")
        books = (body.get("data") or {}).get("books") or []
        return ApiKeyTestResult(success=True, message=f"Connected to Hardcover ({len(books)} book(s) returned)")
    except Exception as e:
        return ApiKeyTestResult(success=False, message=f"Request failed: {e}")


def _test_fanart(api_key: str) -> ApiKeyTestResult:
    # Test using Pink Floyd's MBID — well-known entry
    try:
        resp = requests.get(
            "https://webservice.fanart.tv/v3/music/f27ec8db-af05-4f36-916e-3d57f91ecf7e",
            params={"api_key": api_key},
            timeout=10,
        )
        if resp.status_code == 401 or resp.status_code == 403:
            return ApiKeyTestResult(success=False, message="Invalid API key")
        if resp.status_code == 200:
            return ApiKeyTestResult(success=True, message="Connected to Fanart.tv")
        return ApiKeyTestResult(success=False, message=f"Unexpected status: {resp.status_code}")
    except Exception as e:
        return ApiKeyTestResult(success=False, message=f"Request failed: {e}")


def _test_lastfm(api_key: str) -> ApiKeyTestResult:
    try:
        resp = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "chart.getTopArtists",
                "api_key": api_key,
                "format": "json",
                "limit": "1",
            },
            timeout=10,
        )
        data = resp.json()
        if "error" in data:
            return ApiKeyTestResult(success=False, message=data.get("message", "Invalid API key"))
        artists = data.get("artists", {}).get("artist", [])
        return ApiKeyTestResult(success=True, message=f"Connected to Last.fm ({len(artists)} artist(s) returned)")
    except Exception as e:
        return ApiKeyTestResult(success=False, message=f"Request failed: {e}")


def _test_acoustid(api_key: str) -> ApiKeyTestResult:
    # Send a minimal fingerprint; error code 6 = invalid application key
    try:
        resp = requests.get(
            "https://api.acoustid.org/v2/lookup",
            params={
                "client": api_key,
                "meta": "recordings",
                "duration": "241",
                "fingerprint": "AQAABaklAERRBBEAAAQABAAAAAAAAAAAAAAAAAAAA",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "error":
            err = data.get("error", {})
            code = err.get("code")
            msg = err.get("message", "Unknown error")
            # Code 6 = invalid application API key
            if code == 6:
                return ApiKeyTestResult(success=False, message=f"Invalid API key: {msg}")
            # Any other error means the key was accepted (fingerprint was just invalid)
            return ApiKeyTestResult(success=True, message=f"Connected to AcoustID (key valid, test fingerprint invalid as expected)")
        return ApiKeyTestResult(success=True, message="Connected to AcoustID")
    except Exception as e:
        return ApiKeyTestResult(success=False, message=f"Request failed: {e}")


def _test_audd(api_key: str) -> ApiKeyTestResult:
    try:
        resp = requests.get(
            "https://api.audd.io/findLyrics/",
            params={"q": "hello", "api_token": api_key},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "error":
            err = data.get("error", {})
            return ApiKeyTestResult(success=False, message=err.get("error_message", "Invalid API key"))
        return ApiKeyTestResult(success=True, message="Connected to AUDD")
    except Exception as e:
        return ApiKeyTestResult(success=False, message=f"Request failed: {e}")


_TEST_FUNCTIONS = {
    "HARDCOVER_API_KEY": _test_hardcover,
    "FANART_API_KEY": _test_fanart,
    "LASTFM_API_KEY": _test_lastfm,
    "ACOUSTID_API_KEY": _test_acoustid,
    "AUDD_API_TOKEN": _test_audd,
}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/settings/api-keys")
def list_api_keys(current_user: User = Depends(require_director)) -> list[ApiKeyStatus]:
    """Return status and masked preview for all managed API keys."""
    return [_build_status(defn, _get_live_value(defn["id"])) for defn in API_KEY_DEFS]


@router.put("/settings/api-keys/{key_id}")
def save_api_key(
    key_id: str,
    body: ApiKeyUpdate,
    current_user: User = Depends(require_director),
) -> ApiKeyStatus:
    """Save an API key to studio54-keys.env and update the live process."""
    defn = next((d for d in API_KEY_DEFS if d["id"] == key_id), None)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_id}")

    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Value must not be empty")

    # Persist to file
    _write_key(key_id, value)

    # Record installation date (only if not already set, so updates don't overwrite)
    if not _get_installed_at(key_id):
        _set_installed_at(key_id, date.today().isoformat())

    # Update live process immediately
    os.environ[key_id] = value

    # Reset singletons that cache the key
    _reset_singleton(key_id)

    # Restart worker containers so Celery tasks pick up the new value
    if defn["affects"]:
        _restart_containers(defn["affects"])

    return _build_status(defn, value)


@router.patch("/settings/api-keys/{key_id}/installed-at")
def update_installed_at(
    key_id: str,
    body: ApiKeyInstalledAtUpdate,
    current_user: User = Depends(require_director),
) -> ApiKeyStatus:
    """Manually set the installation date for a key (YYYY-MM-DD)."""
    defn = next((d for d in API_KEY_DEFS if d["id"] == key_id), None)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_id}")

    # Validate date format
    try:
        date.fromisoformat(body.installed_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="installed_at must be YYYY-MM-DD")

    value = _get_live_value(key_id)
    if not value:
        raise HTTPException(status_code=400, detail="No API key is configured for this entry")

    _set_installed_at(key_id, body.installed_at)
    return _build_status(defn, value)


@router.delete("/settings/api-keys/{key_id}")
def delete_api_key(
    key_id: str,
    current_user: User = Depends(require_director),
) -> ApiKeyStatus:
    """Remove an API key from studio54-keys.env."""
    defn = next((d for d in API_KEY_DEFS if d["id"] == key_id), None)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_id}")

    _delete_key(key_id)
    os.environ.pop(key_id, None)
    _reset_singleton(key_id)

    if defn["affects"]:
        _restart_containers(defn["affects"])

    return _build_status(defn, None)


@router.post("/settings/api-keys/{key_id}/test")
def test_api_key(
    key_id: str,
    current_user: User = Depends(require_director),
) -> ApiKeyTestResult:
    """Test the currently saved API key for a given service."""
    defn = next((d for d in API_KEY_DEFS if d["id"] == key_id), None)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_id}")

    value = _get_live_value(key_id)
    if not value:
        return ApiKeyTestResult(success=False, message="No API key configured")

    test_fn = _TEST_FUNCTIONS.get(key_id)
    if not test_fn:
        return ApiKeyTestResult(success=False, message="No test available for this key")

    return test_fn(value)


def _reset_singleton(key_id: str):
    """Reset any service singleton that caches the API key value."""
    try:
        if key_id == "HARDCOVER_API_KEY":
            from app.services.hardcover import reset_hardcover_service
            reset_hardcover_service()
    except Exception:
        pass
