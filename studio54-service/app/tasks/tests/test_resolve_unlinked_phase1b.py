"""Tests for Phase 1B of resolve_unlinked_task: per-release album creation."""
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.track import Track
from app.models.library import LibraryFile


def _make_artist(db, name="Test Artist"):
    a = Artist(id=uuid.uuid4(), name=name, musicbrainz_id=str(uuid.uuid4()))
    db.add(a)
    db.flush()
    return a


def _make_album(db, artist_id, rg_mbid, title="Test Album"):
    """Create a release-group stub album as the wanted placeholder."""
    a = Album(
        id=uuid.uuid4(),
        artist_id=artist_id,
        title=title,
        musicbrainz_id=rg_mbid,
        release_group_mbid=rg_mbid,
        status=AlbumStatus.WANTED,
    )
    db.add(a)
    db.flush()
    return a


def _make_library_file(db, file_path, recording_mbid, album_mbid, rg_mbid, track_number=1):
    from app.models.library import LibraryPath
    lp = db.query(LibraryPath).first()
    if not lp:
        lp = LibraryPath(id=uuid.uuid4(), path="/music", name="Music", library_type="music")
        db.add(lp)
        db.flush()
    lf = LibraryFile(
        id=uuid.uuid4(),
        library_path_id=lp.id,
        file_path=file_path,
        file_name=file_path.split("/")[-1],
        file_size_bytes=1000,
        file_modified_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        title="Track Title",
        track_number=track_number,
        disc_number=1,
        musicbrainz_trackid=recording_mbid,
        musicbrainz_albumid=album_mbid,
        musicbrainz_releasegroupid=rg_mbid,
    )
    db.add(lf)
    db.flush()
    return lf


def test_phase1b_creates_new_album_for_unknown_release(db_session):
    """
    Phase 1B must create a new per-release album when a file's release MBID
    does not match any existing album's musicbrainz_id, instead of dumping
    tracks into the release-group stub.
    """
    from app.tasks.resolve_unlinked_task import _phase1b_create_missing_tracks

    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    release_mbid = str(uuid.uuid4())
    recording_mbid = str(uuid.uuid4())

    # Wanted stub exists for the release group
    stub = _make_album(db_session, artist.id, rg_mbid)
    db_session.commit()

    # Library file tagged to a specific release not in DB
    lf = _make_library_file(
        db_session,
        file_path="/music/Artist/Album/01.flac",
        recording_mbid=recording_mbid,
        album_mbid=release_mbid,
        rg_mbid=rg_mbid,
        track_number=1,
    )
    db_session.commit()

    mock_mb = MagicMock()
    mock_mb.get_release.return_value = {
        "id": release_mbid,
        "title": "Test Album",
        "release-group": {"id": rg_mbid, "primary-type": "Album", "title": "Test Album"},
        "date": "2004",
        "media": [{"position": 1, "tracks": [{
            "position": 1,
            "title": "Track Title",
            "recording": {"id": recording_mbid, "length": 180000},
        }]}],
    }

    job = MagicMock()
    job_logger = MagicMock()

    with patch("app.tasks.resolve_unlinked_task.get_musicbrainz_client", return_value=mock_mb), \
         patch("app.tasks.resolve_unlinked_task._mark_resolved_files", return_value=0):
        _phase1b_create_missing_tracks(db_session, job, job_logger, "", {})

    # A NEW per-release album should exist, NOT a track added to the stub
    new_album = db_session.query(Album).filter(Album.musicbrainz_id == release_mbid).first()
    assert new_album is not None, "Expected a new per-release album to be created"
    assert new_album.release_group_mbid == rg_mbid

    stub_tracks = db_session.query(Track).filter(Track.album_id == stub.id).all()
    assert len(stub_tracks) == 0, "No tracks should be dumped into the release-group stub"


def test_phase1b_no_duplicate_track_positions(db_session):
    """
    After Phase 1B, no album should have two tracks with the same disc+track position.
    """
    from app.tasks.resolve_unlinked_task import _phase1b_create_missing_tracks
    from sqlalchemy import func

    artist = _make_artist(db_session)
    rg_mbid = str(uuid.uuid4())
    release_mbid = str(uuid.uuid4())

    _make_album(db_session, artist.id, rg_mbid)
    db_session.commit()

    for i in range(3):
        _make_library_file(
            db_session,
            file_path=f"/music/Artist/Album/0{i+1}.flac",
            recording_mbid=str(uuid.uuid4()),
            album_mbid=release_mbid,
            rg_mbid=rg_mbid,
            track_number=i + 1,
        )
    db_session.commit()

    mock_mb = MagicMock()
    mock_mb.get_release.return_value = {
        "id": release_mbid,
        "title": "Test Album",
        "release-group": {"id": rg_mbid, "primary-type": "Album", "title": "Test Album"},
        "date": "2004",
        "media": [{"position": 1, "tracks": [
            {"position": i + 1, "title": f"Track {i+1}",
             "recording": {"id": str(uuid.uuid4()), "length": 180000}}
            for i in range(3)
        ]}],
    }

    job = MagicMock()
    job_logger = MagicMock()

    with patch("app.tasks.resolve_unlinked_task.get_musicbrainz_client", return_value=mock_mb), \
         patch("app.tasks.resolve_unlinked_task._mark_resolved_files", return_value=0):
        _phase1b_create_missing_tracks(db_session, job, job_logger, "", {})

    # Check no duplicate (disc_number, track_number) within any album
    from sqlalchemy import text
    dupes = db_session.execute(text("""
        SELECT album_id, disc_number, track_number, COUNT(*) as cnt
        FROM tracks
        GROUP BY album_id, disc_number, track_number
        HAVING COUNT(*) > 1
    """)).fetchall()
    assert len(dupes) == 0, f"Found duplicate track positions: {dupes}"
