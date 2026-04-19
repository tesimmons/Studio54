"""Pytest configuration for app.services.tests.

This allows tests in app/services/tests to discover the main conftest.py fixtures.
"""
import sys
import os
from pathlib import Path

# Add the parent directories to Python path so we can import from tests/
root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(root))
os.chdir(str(root))

# Import all fixtures from the main conftest
from tests.conftest import (  # noqa: F401, F403
    test_db,
    db_session,
    client,
    create_test_artist,
    create_test_album,
    create_test_track,
    create_test_notification_profile,
    create_test_download,
    create_test_indexer,
    create_test_download_client,
)
