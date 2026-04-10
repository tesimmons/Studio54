"""
Notification Service - Send webhook/Discord/Slack notifications for Studio54 events.

Fire-and-forget: notification failures are logged but never crash the caller.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import requests
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.notification import NotificationProfile
from app.services.encryption import get_encryption_service

logger = logging.getLogger(__name__)

TIMEOUT = 10  # seconds


def send_notification(event: str, payload: Dict, db: Optional[Session] = None):
    """
    Send notifications for a given event to all matching enabled profiles.

    Args:
        event: NotificationEvent value (e.g. "album_downloaded")
        payload: Event-specific data dict
        db: Optional database session (creates one if not provided)
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        profiles = db.query(NotificationProfile).filter(
            NotificationProfile.is_enabled == True
        ).all()

        for profile in profiles:
            if event not in (profile.events or []):
                continue

            try:
                _send_to_profile(profile, event, payload)
            except Exception as e:
                logger.error(f"Notification failed for profile '{profile.name}': {e}")

    except Exception as e:
        logger.error(f"Error querying notification profiles: {e}")
    finally:
        if close_db:
            db.close()


def _send_to_profile(profile: NotificationProfile, event: str, payload: Dict):
    """Send notification to a single profile."""
    encryption_service = get_encryption_service()
    webhook_url = encryption_service.decrypt(profile.webhook_url_encrypted)

    provider = profile.provider or "webhook"

    if provider == "discord":
        body = _format_discord(event, payload)
    elif provider == "slack":
        body = _format_slack(event, payload)
    else:
        body = _format_webhook(event, payload)

    response = requests.post(webhook_url, json=body, timeout=TIMEOUT)
    response.raise_for_status()

    logger.info(f"Notification sent: {event} -> {profile.name} ({provider})")


def _format_webhook(event: str, payload: Dict) -> Dict:
    """Generic JSON webhook format."""
    return {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }


def _format_discord(event: str, payload: Dict) -> Dict:
    """Discord webhook embed format."""
    title = _event_title(event)
    description = _event_description(event, payload)
    color = _event_color(event)

    return {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Studio54"},
                "fields": [
                    {"name": k, "value": str(v), "inline": True}
                    for k, v in payload.items()
                    if v is not None and k not in ("title", "message")
                ][:10],  # Discord max 25 fields, keep it reasonable
            }
        ]
    }


def _format_slack(event: str, payload: Dict) -> Dict:
    """Slack Block Kit format."""
    title = _event_title(event)
    description = _event_description(event, payload)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": description},
        },
    ]

    # Add fields
    fields = [
        {"type": "mrkdwn", "text": f"*{k}:* {v}"}
        for k, v in payload.items()
        if v is not None and k not in ("title", "message")
    ][:10]

    if fields:
        blocks.append({"type": "section", "fields": fields})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Studio54"}],
    })

    return {"blocks": blocks}


def _event_title(event: str) -> str:
    """Human-readable event title."""
    titles = {
        "album_downloaded": "Album Downloaded",
        "album_imported": "Album Imported",
        "album_failed": "Album Download Failed",
        "job_failed": "Job Failed",
        "job_completed": "Job Completed",
        "artist_added": "Artist Added",
    }
    return titles.get(event, event.replace("_", " ").title())


def _event_description(event: str, payload: Dict) -> str:
    """Build description from payload."""
    if "message" in payload:
        return payload["message"]

    artist = payload.get("artist_name", "")
    album = payload.get("album_title", "")

    if artist and album:
        return f"{artist} - {album}"
    elif artist:
        return artist
    elif album:
        return album

    return event.replace("_", " ").title()


def _event_color(event: str) -> int:
    """Discord embed color by event type."""
    colors = {
        "album_downloaded": 0x2ECC71,   # green
        "album_imported": 0x3498DB,     # blue
        "album_failed": 0xE74C3C,      # red
        "job_failed": 0xE74C3C,        # red
        "job_completed": 0x2ECC71,     # green
        "artist_added": 0x9B59B6,      # purple
    }
    return colors.get(event, 0x95A5A6)  # gray default


def send_test_notification(profile: NotificationProfile):
    """Send a test notification to verify the webhook URL works."""
    payload = {
        "message": "This is a test notification from Studio54",
        "artist_name": "Test Artist",
        "album_title": "Test Album",
    }
    _send_to_profile(profile, "test", payload)
