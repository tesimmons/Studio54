"""Tests for album_importer — import_release_group and import_release."""
import uuid
import pytest
from unittest.mock import MagicMock, patch

from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.track import Track


def _make_artist(db):
    artist = Artist(
        id=uuid.uuid4(),
        name="Test Artist",
        musicbrainz_id=str(uuid.uuid4()),
    )
    db.add(artist)
    db.flush()
    return artist


def _make_mb_client_stub(rg_mbid, rg_title="Test Album", primary_type="Album"):
    """Return a mock MusicBrainzClient for import_release_group tests."""
    client = MagicMock()
    client.get_release_group.return_value = {
        "id": rg_mbid,
        "title": rg_title,
        "primary-type": primary_type,
        "secondary-types": [],
        "first-release-date": "2004-01-01",
    }
    return client


def _make_mb_client_release(release_mbid, rg_mbid, tracks):
    """Return a mock MusicBrainzClient for import_release tests.

    tracks: list of dicts with keys: recording_mbid, title, position, disc_position
    """
    client = MagicMock()
    # Collapse tracks onto same disc properly
    by_disc = {}
    for t in tracks:
        disc = t.get("disc_position", 1)
        by_disc.setdefault(disc, []).append({
            "position": t["position"],
            "title": t["title"],
            "recording": {"id": t["recording_mbid"], "length": 180000},
        })
    media = [{"position": disc, "tracks": trks} for disc, trks in sorted(by_disc.items())]
    client.get_release.return_value = {
        "id": release_mbid,
        "release-group": {"id": rg_mbid},
        "media": media,
    }
    return client


def test_import_release_group_creates_stub_with_no_tracks(db_session):
    """import_release_group creates a WANTED stub keyed by RG MBID with no tracks."""
    from app.services.album_importer import import_release_group
    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    client = _make_mb_client_stub(rg_mbid)

    album = import_release_group(db_session, artist.id, rg_mbid, client)

    assert album is not None
    assert album.musicbrainz_id == rg_mbid
    assert album.release_group_mbid == rg_mbid
    assert album.release_mbid is None
    assert album.status == AlbumStatus.WANTED
    tracks = db_session.query(Track).filter(Track.album_id == album.id).all()
    assert len(tracks) == 0


def test_import_release_group_idempotent(db_session):
    """Calling import_release_group twice returns None on second call (already exists)."""
    from app.services.album_importer import import_release_group
    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    client = _make_mb_client_stub(rg_mbid)

    first = import_release_group(db_session, artist.id, rg_mbid, client)
    db_session.commit()
    second = import_release_group(db_session, artist.id, rg_mbid, client)

    assert first is not None
    assert second is None


def test_import_release_creates_album_keyed_by_release_mbid(db_session):
    """import_release creates an album with musicbrainz_id = release MBID."""
    from app.services.album_importer import import_release
    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    release_mbid = str(uuid.uuid4())
    tracks = [
        {"recording_mbid": str(uuid.uuid4()), "title": "Track One", "position": 1},
        {"recording_mbid": str(uuid.uuid4()), "title": "Track Two", "position": 2},
    ]
    client = _make_mb_client_release(release_mbid, rg_mbid, tracks)

    album = import_release(db_session, release_mbid, rg_mbid, artist.id, client)

    assert album is not None
    assert album.musicbrainz_id == release_mbid
    assert album.release_mbid == release_mbid
    assert album.release_group_mbid == rg_mbid
    db_tracks = db_session.query(Track).filter(Track.album_id == album.id).order_by(Track.track_number).all()
    assert len(db_tracks) == 2
    assert db_tracks[0].track_number == 1
    assert db_tracks[0].title == "Track One"
    assert db_tracks[1].track_number == 2


def test_import_release_idempotent(db_session):
    """Calling import_release twice returns None on second call."""
    from app.services.album_importer import import_release
    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    release_mbid = str(uuid.uuid4())
    tracks = [{"recording_mbid": str(uuid.uuid4()), "title": "T1", "position": 1}]
    client = _make_mb_client_release(release_mbid, rg_mbid, tracks)

    first = import_release(db_session, release_mbid, rg_mbid, artist.id, client)
    db_session.commit()
    second = import_release(db_session, release_mbid, rg_mbid, artist.id, client)

    assert first is not None
    assert second is None


def test_album_model_has_release_group_mbid_field(db_session):
    """Album model accepts and persists release_group_mbid."""
    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    rel_mbid = str(uuid.uuid4())
    album = Album(
        artist_id=artist.id,
        title="Test Album",
        musicbrainz_id=rel_mbid,
        release_mbid=rel_mbid,
        release_group_mbid=rg_mbid,
        status=AlbumStatus.DOWNLOADED,
    )
    db_session.add(album)
    db_session.commit()
    fetched = db_session.query(Album).filter(Album.id == album.id).first()
    assert fetched.release_group_mbid == rg_mbid
    assert fetched.release_mbid == rel_mbid
    assert fetched.musicbrainz_id == rel_mbid


def test_get_album_api_includes_release_group_mbid(client, db_session):
    """GET /albums/{id} response must include release_group_mbid."""
    from app.models.user import User, UserRole
    from app.auth import create_access_token, hash_password

    # Create a test user so the auth dependency can resolve
    user = User(
        id=uuid.uuid4(),
        username="testuser_rg",
        password_hash=hash_password("testpass"),
        role=UserRole.DIRECTOR,
        is_active=True,
    )
    db_session.add(user)

    artist = Artist(id=uuid.uuid4(), name="API Test Artist", musicbrainz_id=str(uuid.uuid4()))
    db_session.add(artist)

    rg_mbid = str(uuid.uuid4())
    rel_mbid = str(uuid.uuid4())
    album = Album(
        id=uuid.uuid4(),
        artist_id=artist.id,
        title="API Test Album",
        musicbrainz_id=rel_mbid,
        release_mbid=rel_mbid,
        release_group_mbid=rg_mbid,
        status=AlbumStatus.DOWNLOADED,
    )
    db_session.add(album)
    db_session.commit()

    token = create_access_token(str(user.id), user.username, user.role)
    response = client.get(
        f"/api/v1/albums/{album.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "release_group_mbid" in data
    assert data["release_group_mbid"] == rg_mbid
