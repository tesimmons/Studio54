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
