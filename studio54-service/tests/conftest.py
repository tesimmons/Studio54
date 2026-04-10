"""
Pytest configuration and shared fixtures for Studio54 testing.

Uses in-memory SQLite with type adapters for PostgreSQL-specific column types
(UUID, JSONB, Enum) so integration tests can run without a real database.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine, event, String, Text, types
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# ─── Environment setup (must come before any app imports) ───
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("STUDIO54_ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")

# ─── Patch PostgreSQL types for SQLite compatibility ───
# Must happen before model imports so the Column definitions use patched types.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB

# Store originals
_orig_uuid_result_processor = PG_UUID.result_processor
_orig_uuid_bind_processor = PG_UUID.bind_processor


def _sqlite_uuid_bind_processor(self, dialect):
    """For SQLite: convert UUID objects to strings"""
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return str(value) if isinstance(value, uuid.UUID) else value
            return value
        return process
    return _orig_uuid_bind_processor(self, dialect)


def _sqlite_uuid_result_processor(self, dialect, coltype):
    """For SQLite: convert strings back to UUID objects if as_uuid=True"""
    if dialect.name == "sqlite":
        if self.as_uuid:
            def process(value):
                if value is not None:
                    return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
                return value
            return process
        return None
    return _orig_uuid_result_processor(self, dialect, coltype)


def _sqlite_uuid_get_colspec(self, **kw):
    """For SQLite: render UUID as VARCHAR(36)"""
    return "VARCHAR(36)"


# Patch the methods
PG_UUID.bind_processor = _sqlite_uuid_bind_processor
PG_UUID.result_processor = _sqlite_uuid_result_processor

# Patch JSONB for SQLite
_orig_jsonb_bind = PG_JSONB.bind_processor
_orig_jsonb_result = PG_JSONB.result_processor


def _sqlite_jsonb_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return json.dumps(value)
            return value
        return process
    return _orig_jsonb_bind(self, dialect)


def _sqlite_jsonb_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None and isinstance(value, str):
                return json.loads(value)
            return value
        return process
    return _orig_jsonb_result(self, dialect, coltype)


PG_JSONB.bind_processor = _sqlite_jsonb_bind_processor
PG_JSONB.result_processor = _sqlite_jsonb_result_processor

# Register SQLite-compatible column specs for PG types
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect_module

# Teach SQLite compiler how to render PostgreSQL types
from sqlalchemy.ext.compiler import compiles

@compiles(PG_UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

@compiles(PG_JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


# Now import app modules
from app.database import Base, get_db

# Import all models so Base.metadata knows about them for create_all()
import app.models  # noqa: F401


# ─── Database Fixtures ───

@pytest.fixture(scope="function")
def test_db():
    """Create in-memory SQLite database for testing"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable foreign keys in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_db):
    """Provide a database session for a test"""
    session = test_db()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_session):
    """Provide a FastAPI test client with database override"""
    from app.main import app

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ─── Model Factories ───

def create_test_artist(
    db_session,
    name="Test Artist",
    musicbrainz_id=None,
    is_monitored=True,
    monitor_type="all_albums",
    **kwargs
):
    """Create a test artist record"""
    from app.models.artist import Artist

    artist = Artist(
        id=uuid.uuid4(),
        name=name,
        musicbrainz_id=musicbrainz_id or str(uuid.uuid4()),
        is_monitored=is_monitored,
        monitor_type=monitor_type,
        **kwargs
    )
    db_session.add(artist)
    db_session.commit()
    db_session.refresh(artist)
    return artist


def create_test_album(
    db_session,
    artist_id,
    title="Test Album",
    musicbrainz_id=None,
    status="wanted",
    monitored=True,
    **kwargs
):
    """Create a test album record"""
    from app.models.album import Album

    album = Album(
        id=uuid.uuid4(),
        artist_id=artist_id,
        title=title,
        musicbrainz_id=musicbrainz_id or str(uuid.uuid4()),
        status=status,
        monitored=monitored,
        **kwargs
    )
    db_session.add(album)
    db_session.commit()
    db_session.refresh(album)
    return album


def create_test_track(
    db_session,
    album_id,
    title="Test Track",
    track_number=1,
    musicbrainz_id=None,
    **kwargs
):
    """Create a test track record"""
    from app.models.track import Track

    track = Track(
        id=uuid.uuid4(),
        album_id=album_id,
        title=title,
        track_number=track_number,
        musicbrainz_id=musicbrainz_id or str(uuid.uuid4()),
        **kwargs
    )
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)
    return track


def create_test_notification_profile(
    db_session,
    name="Test Webhook",
    provider="webhook",
    webhook_url="https://example.com/webhook",
    is_enabled=True,
    events=None,
    **kwargs
):
    """Create a test notification profile with encrypted webhook URL"""
    from app.models.notification import NotificationProfile
    from app.services.encryption import get_encryption_service

    encryption_service = get_encryption_service()
    profile = NotificationProfile(
        id=uuid.uuid4(),
        name=name,
        provider=provider,
        webhook_url_encrypted=encryption_service.encrypt(webhook_url),
        is_enabled=is_enabled,
        events=events if events is not None else ["album_downloaded"],
        **kwargs
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


def create_test_download(
    db_session,
    album_id,
    indexer_id,
    download_client_id,
    nzb_title="Test NZB",
    nzb_guid=None,
    status="queued",
    **kwargs
):
    """Create a test download queue record"""
    from app.models.download_queue import DownloadQueue

    download = DownloadQueue(
        id=uuid.uuid4(),
        album_id=album_id,
        indexer_id=indexer_id,
        download_client_id=download_client_id,
        nzb_title=nzb_title,
        nzb_guid=nzb_guid or str(uuid.uuid4()),
        status=status,
        queued_at=datetime.now(timezone.utc),
        **kwargs
    )
    db_session.add(download)
    db_session.commit()
    db_session.refresh(download)
    return download


def create_test_indexer(
    db_session,
    name="Test Indexer",
    base_url="https://indexer.example.com",
    api_key="test-api-key",
    **kwargs
):
    """Create a test indexer record"""
    from app.models.indexer import Indexer
    from app.services.encryption import get_encryption_service

    encryption_service = get_encryption_service()
    indexer = Indexer(
        id=uuid.uuid4(),
        name=name,
        base_url=base_url,
        api_key_encrypted=encryption_service.encrypt(api_key),
        **kwargs
    )
    db_session.add(indexer)
    db_session.commit()
    db_session.refresh(indexer)
    return indexer


def create_test_download_client(
    db_session,
    name="Test SABnzbd",
    host="192.168.1.100",
    port=8080,
    api_key="test-sab-key",
    is_default=True,
    **kwargs
):
    """Create a test download client record"""
    from app.models.download_client import DownloadClient
    from app.services.encryption import get_encryption_service

    encryption_service = get_encryption_service()
    client = DownloadClient(
        id=uuid.uuid4(),
        name=name,
        host=host,
        port=port,
        api_key_encrypted=encryption_service.encrypt(api_key),
        is_default=is_default,
        **kwargs
    )
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client
