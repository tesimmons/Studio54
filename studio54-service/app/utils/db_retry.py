"""
Database retry utilities for transient connection errors.
"""
from sqlalchemy.exc import OperationalError, DisconnectionError
import logging
import time

logger = logging.getLogger(__name__)


def retry_db_commit(session, max_attempts=3):
    """Retry a session commit on transient DB errors (connection drops, timeouts)."""
    for attempt in range(max_attempts):
        try:
            session.commit()
            return
        except (OperationalError, DisconnectionError) as e:
            if attempt < max_attempts - 1:
                logger.warning(f"DB commit failed (attempt {attempt + 1}/{max_attempts}): {e}")
                session.rollback()
                time.sleep(2 ** attempt)
            else:
                raise
