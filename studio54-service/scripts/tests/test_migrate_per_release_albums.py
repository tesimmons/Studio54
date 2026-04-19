"""Tests for the per-release album migration script."""
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.track import Track
from app.models.library import LibraryFile, LibraryPath


def _artist(db):
    a = Artist(id=uuid.uuid4(), name="A", musicbrainz_id=str(uuid.uuid4()))
    db.add(a)
    db.flush()
    return a


def _lib_path(db):
    lp = db.query(LibraryPath).first()
    if not lp:
        lp = LibraryPath(id=uuid.uuid4(), path="/music", name="Music", library_type="music")
        db.add(lp)
        db.flush()
    return lp


def _album(db, artist_id, rg_mbid, title="Album", status=AlbumStatus.WANTED):
    a = Album(
        id=uuid.uuid4(), artist_id=artist_id, title=title,
        musicbrainz_id=rg_mbid, status=status,
    )
    db.add(a)
    db.flush()
    return a


def _track(db, album_id, recording_mbid, has_file=False, file_path=None, track_number=1):
    t = Track(
        id=uuid.uuid4(), album_id=album_id, title="T",
        musicbrainz_id=recording_mbid, track_number=track_number,
        disc_number=1, has_file=has_file, file_path=file_path,
    )
    db.add(t)
    db.flush()
    return t


_MODIFIED_AT = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _lf(db, lp_id, file_path, recording_mbid, album_mbid, rg_mbid):
    lf = LibraryFile(
        id=uuid.uuid4(), library_path_id=lp_id, file_path=file_path,
        file_name=file_path.split("/")[-1], file_size_bytes=1000,
        file_modified_at=_MODIFIED_AT, title="T",
        track_number=1, disc_number=1,
        musicbrainz_trackid=recording_mbid,
        musicbrainz_albumid=album_mbid,
        musicbrainz_releasegroupid=rg_mbid,
    )
    db.add(lf)
    db.flush()
    return lf


# ── Case 1: Wanted stub ────────────────────────────────────────────────────

def test_case1_wanted_stub_gets_release_group_mbid(db_session):
    """Wanted stubs (no files) get release_group_mbid = musicbrainz_id, unchanged otherwise."""
    from scripts.migrate_per_release_albums import migrate_album

    artist = _artist(db_session)
    rg_mbid = str(uuid.uuid4())
    album = _album(db_session, artist.id, rg_mbid, status=AlbumStatus.WANTED)
    db_session.commit()

    result = migrate_album(db_session, album, mb_client=MagicMock())

    assert result == "stub"
    db_session.refresh(album)
    assert album.release_group_mbid == rg_mbid
    assert album.musicbrainz_id == rg_mbid  # unchanged


# ── Case 2: Single release ────────────────────────────────────────────────

def test_case2_single_release_rekeys_album(db_session):
    """Albums where all files share one musicbrainz_albumid get re-keyed to that release MBID."""
    from scripts.migrate_per_release_albums import migrate_album

    artist = _artist(db_session)
    lp = _lib_path(db_session)
    rg_mbid = str(uuid.uuid4())
    release_mbid = str(uuid.uuid4())
    recording_mbid = str(uuid.uuid4())

    album = _album(db_session, artist.id, rg_mbid, status=AlbumStatus.DOWNLOADED)
    track = _track(db_session, album.id, recording_mbid, has_file=True,
                   file_path="/music/a/01.flac", track_number=1)
    _lf(db_session, lp.id, "/music/a/01.flac", recording_mbid, release_mbid, rg_mbid)
    db_session.commit()

    result = migrate_album(db_session, album, mb_client=MagicMock())

    assert result == "converted"
    db_session.refresh(album)
    assert album.musicbrainz_id == release_mbid
    assert album.release_group_mbid == rg_mbid
    assert album.release_mbid == release_mbid


# ── Case 3: Mixed releases ────────────────────────────────────────────────

def test_case3_mixed_releases_splits_into_separate_albums(db_session):
    """Albums with files from multiple releases are split into separate per-release records."""
    from scripts.migrate_per_release_albums import migrate_album

    artist = _artist(db_session)
    lp = _lib_path(db_session)
    rg_mbid = str(uuid.uuid4())
    release_a = str(uuid.uuid4())
    release_b = str(uuid.uuid4())
    rec_a1 = str(uuid.uuid4())
    rec_b1 = str(uuid.uuid4())

    album = _album(db_session, artist.id, rg_mbid, status=AlbumStatus.DOWNLOADED)
    _track(db_session, album.id, rec_a1, has_file=True, file_path="/music/a/01.flac", track_number=1)
    _track(db_session, album.id, rec_b1, has_file=True, file_path="/music/b/01.flac", track_number=1)
    _lf(db_session, lp.id, "/music/a/01.flac", rec_a1, release_a, rg_mbid)
    _lf(db_session, lp.id, "/music/b/01.flac", rec_b1, release_b, rg_mbid)
    db_session.commit()

    original_album_id = album.id
    result = migrate_album(db_session, album, mb_client=MagicMock())
    db_session.commit()

    assert result == "split"

    # Two albums total for this RG
    albums = db_session.query(Album).filter(Album.release_group_mbid == rg_mbid).all()
    assert len(albums) == 2
    mbids = {a.musicbrainz_id for a in albums}
    assert release_a in mbids
    assert release_b in mbids

    # No album still using the bare RG MBID as musicbrainz_id
    assert not any(a.musicbrainz_id == rg_mbid for a in albums)


# ── Case 4: Files but no musicbrainz_albumid ──────────────────────────────

def test_case4_legacy_album_gets_release_group_mbid_set(db_session):
    """Albums with files but no musicbrainz_albumid tags are left as legacy."""
    from scripts.migrate_per_release_albums import migrate_album

    artist = _artist(db_session)
    lp = _lib_path(db_session)
    rg_mbid = str(uuid.uuid4())
    recording_mbid = str(uuid.uuid4())

    album = _album(db_session, artist.id, rg_mbid, status=AlbumStatus.DOWNLOADED)
    _track(db_session, album.id, recording_mbid, has_file=True, file_path="/music/a/01.flac")
    # Library file has NO musicbrainz_albumid
    lf = LibraryFile(
        id=uuid.uuid4(), library_path_id=lp.id,
        file_path="/music/a/01.flac", file_name="01.flac",
        file_size_bytes=1000, file_modified_at=_MODIFIED_AT,
        title="T", track_number=1, disc_number=1,
        musicbrainz_trackid=recording_mbid,
        musicbrainz_albumid=None,
        musicbrainz_releasegroupid=rg_mbid,
    )
    db_session.add(lf)
    db_session.commit()

    result = migrate_album(db_session, album, mb_client=MagicMock())

    assert result == "legacy"
    db_session.refresh(album)
    assert album.release_group_mbid == rg_mbid
    assert album.musicbrainz_id == rg_mbid  # unchanged


# ── Validation ────────────────────────────────────────────────────────────

def test_validation_detects_duplicate_track_positions(db_session):
    """Validation check 1 catches albums with duplicate (disc, track) positions."""
    from scripts.migrate_per_release_albums import run_validation

    artist = _artist(db_session)
    rg_mbid = str(uuid.uuid4())
    rel_mbid = str(uuid.uuid4())
    album = Album(
        id=uuid.uuid4(), artist_id=artist.id, title="Bad Album",
        musicbrainz_id=rel_mbid, release_group_mbid=rg_mbid,
        status=AlbumStatus.DOWNLOADED,
    )
    db_session.add(album)
    db_session.flush()
    for _ in range(2):
        db_session.add(Track(
            id=uuid.uuid4(), album_id=album.id, title="T",
            musicbrainz_id=str(uuid.uuid4()), track_number=1,
            disc_number=1, has_file=False,
        ))
    db_session.commit()

    report = run_validation(db_session)
    assert report["duplicate_track_positions"]["pass"] is False
    assert report["duplicate_track_positions"]["count"] > 0


def test_validation_passes_clean_db(db_session):
    """Validation passes when the database is clean."""
    from scripts.migrate_per_release_albums import run_validation

    artist = _artist(db_session)
    rel_mbid = str(uuid.uuid4())
    rg_mbid = str(uuid.uuid4())
    album = Album(
        id=uuid.uuid4(), artist_id=artist.id, title="Good Album",
        musicbrainz_id=rel_mbid, release_group_mbid=rg_mbid,
        status=AlbumStatus.DOWNLOADED,
    )
    db_session.add(album)
    db_session.flush()
    db_session.add(Track(
        id=uuid.uuid4(), album_id=album.id, title="T",
        musicbrainz_id=str(uuid.uuid4()), track_number=1,
        disc_number=1, has_file=False,
    ))
    db_session.commit()

    report = run_validation(db_session)
    for check_name, check in report.items():
        assert check["pass"] is True, f"Check '{check_name}' failed: {check}"
