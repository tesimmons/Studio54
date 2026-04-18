# Per-Release Albums Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change album records from one-per-release-group to one-per-specific-release, eliminating duplicate track numbers caused by multiple editions of the same album merging into one record.

**Architecture:** Add `release_group_mbid` to `albums` so each row can be re-keyed to a specific release MBID while still tracking its parent release group. A one-time migration script splits existing mixed-release albums. The resolve-unlinked pipeline is updated to create new per-release album records instead of dumping cross-release tracks into the same album. Wanted stubs (no files) stay at release-group granularity.

**Tech Stack:** Python 3, SQLAlchemy, Alembic, FastAPI, Celery, MusicBrainz API, PostgreSQL, pytest with SQLite in-memory

**Spec:** `docs/superpowers/specs/2026-04-18-per-release-albums-design.md`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `alembic/versions/20260418_0100_058_add_release_group_mbid.py` | Create | Add `release_group_mbid` column to `albums` |
| `app/models/album.py` | Modify | Add `release_group_mbid` SQLAlchemy column |
| `app/services/album_importer.py` | Modify | Stub-only `import_release_group()`, new `import_release()` |
| `app/tasks/resolve_unlinked_task.py` | Modify | Phase 1B: call `import_release()` instead of dumping tracks |
| `app/tasks/sync_tasks.py` | Modify | File-existence check uses release MBID for per-release albums |
| `app/api/albums.py` | Modify | Add `release_group_mbid` to `get_album` response |
| `scripts/migrate_per_release_albums.py` | Create | One-time migration + validation script |
| `app/services/tests/test_album_importer.py` | Create | Tests for `import_release_group()` and `import_release()` |
| `app/tasks/tests/test_resolve_unlinked_phase1b.py` | Create | Tests for Phase 1B new-album routing |
| `scripts/tests/test_migrate_per_release_albums.py` | Create | Tests for all four migration cases + validation |

---

## Task 1: Alembic Migration — Add `release_group_mbid` Column

**Files:**
- Create: `studio54-service/alembic/versions/20260418_0100_058_add_release_group_mbid.py`

- [ ] **Step 1: Create the migration file**

```python
"""Add release_group_mbid to albums

Revision ID: 20260418_0100_058
Revises: 20260414_0100_057
Create Date: 2026-04-18

Adds release_group_mbid so albums can be re-keyed to a specific release MBID
while retaining a reference back to the parent release group.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260418_0100_058'
down_revision = '20260414_0100_057'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('albums', sa.Column(
        'release_group_mbid', sa.String(36), nullable=True
    ))
    op.create_index('ix_albums_release_group_mbid', 'albums', ['release_group_mbid'])


def downgrade():
    op.drop_index('ix_albums_release_group_mbid', table_name='albums')
    op.drop_column('albums', 'release_group_mbid')
```

- [ ] **Step 2: Run the migration**

```bash
cd /home/tesimmons/Studio54
docker exec studio54-service alembic upgrade head
```

Expected output: `Running upgrade 20260414_0100_057 -> 20260418_0100_058, Add release_group_mbid to albums`

- [ ] **Step 3: Verify column exists**

```bash
docker exec studio54-db psql -U studio54 -d studio54_db -c "\d albums" | grep release_group_mbid
```

Expected: `release_group_mbid | character varying(36) | ...`

- [ ] **Step 4: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-service/alembic/versions/20260418_0100_058_add_release_group_mbid.py
git commit -m "feat: add release_group_mbid column to albums table"
```

---

## Task 2: Update Album Model

**Files:**
- Modify: `studio54-service/app/models/album.py`

- [ ] **Step 1: Add `release_group_mbid` field to the Album class**

In `app/models/album.py`, add after the `release_mbid` line (line 39):

```python
    release_group_mbid = Column(String(36), nullable=True, index=True)  # Parent release group MBID
```

The full block around it should look like:

```python
    musicbrainz_id = Column(String(100), unique=True, nullable=False, index=True)  # Release MBID (or RG MBID for wanted stubs)
    release_mbid = Column(String(36), nullable=True, index=True)  # Specific release MBID (alias of musicbrainz_id for per-release albums)
    release_group_mbid = Column(String(36), nullable=True, index=True)  # Parent release group MBID
```

Also update the comment on `musicbrainz_id` from:
```python
    musicbrainz_id = Column(String(100), unique=True, nullable=False, index=True)  # Release group MBID or local-UUID stub
```
to:
```python
    musicbrainz_id = Column(String(100), unique=True, nullable=False, index=True)  # Release MBID (or RG MBID for wanted stubs / legacy)
```

- [ ] **Step 2: Write a test to confirm the field is present and settable**

Create `studio54-service/app/services/tests/test_album_importer.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it passes**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest app/services/tests/test_album_importer.py::test_album_model_has_release_group_mbid_field -v
```

Expected: `PASSED`

- [ ] **Step 4: Commit**

```bash
git add studio54-service/app/models/album.py studio54-service/app/services/tests/test_album_importer.py
git commit -m "feat: add release_group_mbid field to Album model"
```

---

## Task 3: Update `album_importer.py` — Stub-Only and New `import_release()`

**Files:**
- Modify: `studio54-service/app/services/album_importer.py`
- Test: `studio54-service/app/services/tests/test_album_importer.py`

- [ ] **Step 1: Write failing tests for the new behaviour**

Add to `app/services/tests/test_album_importer.py`:

```python
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
    media = [{
        "position": t.get("disc_position", 1),
        "tracks": [{
            "position": t["position"],
            "title": t["title"],
            "recording": {"id": t["recording_mbid"], "length": 180000},
        }],
    } for t in tracks]
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest app/services/tests/test_album_importer.py -v 2>&1 | tail -20
```

Expected: `FAILED` on the new tests (import_release not defined yet, import_release_group still creates tracks)

- [ ] **Step 3: Rewrite `import_release_group()` to be stub-only**

Replace the body of `import_release_group()` in `app/services/album_importer.py`:

```python
def import_release_group(
    db: Session,
    artist_id: UUID,
    release_group_mbid: str,
    mb_client: MusicBrainzClient,
) -> Optional[Album]:
    """
    Import a release group as a WANTED stub Album (no tracks).

    Tracks belong to specific releases — call import_release() when a file
    with a known release MBID needs a proper album record.
    """
    existing = db.query(Album).filter(Album.musicbrainz_id == release_group_mbid).first()
    if existing:
        return None

    rg = mb_client.get_release_group(release_group_mbid)
    if not rg:
        logger.warning(f"Could not fetch release group {release_group_mbid}")
        return None

    secondary_types_list = rg.get("secondary-types", [])
    album = Album(
        artist_id=artist_id,
        title=rg.get("title", "Unknown Album"),
        musicbrainz_id=release_group_mbid,
        release_group_mbid=release_group_mbid,
        release_mbid=None,
        album_type=rg.get("primary-type", "Album"),
        secondary_types=",".join(secondary_types_list) if secondary_types_list else None,
        status=AlbumStatus.WANTED,
    )
    album.release_date = _parse_mb_date(rg.get("first-release-date"))
    db.add(album)
    db.flush()

    logger.info(
        f"Imported release group stub '{album.title}' ({release_group_mbid}) "
        f"for artist {artist_id}"
    )
    return album
```

- [ ] **Step 4: Add `import_release()` function**

Add after `import_release_group()` in `app/services/album_importer.py`:

```python
def import_release(
    db: Session,
    release_mbid: str,
    release_group_mbid: str,
    artist_id: UUID,
    mb_client: MusicBrainzClient,
    title: Optional[str] = None,
    album_type: Optional[str] = None,
    release_date: Optional[date] = None,
) -> Optional[Album]:
    """
    Import a specific release as an Album + Tracks from MusicBrainz.

    Creates an album keyed by release MBID (not release group MBID) so that
    separate editions of the same album get separate records.
    """
    existing = db.query(Album).filter(Album.musicbrainz_id == release_mbid).first()
    if existing:
        return None

    release = mb_client.get_release(release_mbid)
    if not release:
        logger.warning(f"Could not fetch release {release_mbid}")
        return None

    rg = release.get("release-group", {})
    resolved_title = title or rg.get("title") or release.get("title", "Unknown Album")
    resolved_type = album_type or rg.get("primary-type", "Album")
    resolved_date = release_date or _parse_mb_date(release.get("date"))

    album = Album(
        artist_id=artist_id,
        title=resolved_title,
        musicbrainz_id=release_mbid,
        release_mbid=release_mbid,
        release_group_mbid=release_group_mbid,
        album_type=resolved_type,
        status=AlbumStatus.DOWNLOADED,
        release_date=resolved_date,
    )
    db.add(album)
    db.flush()

    tracks_added = 0
    media_list = release.get("media", [])
    for media in media_list:
        disc_number = media.get("position", 1)
        for track_data in media.get("tracks", []):
            recording = track_data.get("recording", {})
            recording_mbid = recording.get("id")
            if not recording_mbid:
                continue
            existing_track = db.query(Track).filter(
                Track.musicbrainz_id == recording_mbid,
                Track.album_id == album.id,
            ).first()
            if not existing_track:
                db.add(Track(
                    album_id=album.id,
                    title=recording.get("title") or track_data.get("title", "Unknown Track"),
                    musicbrainz_id=recording_mbid,
                    track_number=track_data.get("position", 0),
                    disc_number=disc_number,
                    duration_ms=recording.get("length"),
                    has_file=False,
                ))
                tracks_added += 1

    total_tracks = sum(len(m.get("tracks", [])) for m in media_list)
    album.track_count = total_tracks

    logger.info(
        f"Imported release '{album.title}' ({release_mbid}) "
        f"with {tracks_added} tracks for artist {artist_id}"
    )
    return album
```

- [ ] **Step 5: Remove `_import_tracks_for_album()` if it is now unused**

Check for any remaining callers:
```bash
grep -rn "_import_tracks_for_album" /home/tesimmons/Studio54/studio54-service/app --include="*.py"
```

If no callers remain outside `album_importer.py` itself, delete the function.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest app/services/tests/test_album_importer.py -v
```

Expected: All 5 tests `PASSED`

- [ ] **Step 7: Commit**

```bash
git add studio54-service/app/services/album_importer.py studio54-service/app/services/tests/test_album_importer.py
git commit -m "feat: make import_release_group stub-only, add import_release()"
```

---

## Task 4: Update `resolve_unlinked_task.py` — Phase 1B Routes to `import_release()`

**Files:**
- Modify: `studio54-service/app/tasks/resolve_unlinked_task.py`
- Create: `studio54-service/app/tasks/tests/test_resolve_unlinked_phase1b.py`

- [ ] **Step 1: Write failing tests**

Create `studio54-service/app/tasks/tests/test_resolve_unlinked_phase1b.py`:

```python
"""Tests for Phase 1B of resolve_unlinked_task: per-release album creation."""
import uuid
import pytest
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
        file_modified_at="2024-01-01 00:00:00+00",
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

    with patch("app.tasks.resolve_unlinked_task.get_musicbrainz_client", return_value=mock_mb):
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

    with patch("app.tasks.resolve_unlinked_task.get_musicbrainz_client", return_value=mock_mb):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest app/tasks/tests/test_resolve_unlinked_phase1b.py -v 2>&1 | tail -20
```

Expected: `FAILED` — Phase 1B still dumps tracks into the stub

- [ ] **Step 3: Rewrite `_phase1b_create_missing_tracks()` in `resolve_unlinked_task.py`**

Find `_phase1b_create_missing_tracks` (around line 397). Replace the entire function body with:

```python
def _phase1b_create_missing_tracks(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 1B: For files with a release MBID (musicbrainz_albumid) not yet in albums,
    create a proper per-release album via import_release() and link the file to it.

    Previously this dumped cross-release tracks into the release-group stub, causing
    duplicate track numbers. Now each release gets its own album record.
    """
    from app.services.album_importer import import_release
    from app.services.musicbrainz_client import get_musicbrainz_client

    stats = {
        "phase1b_albums_created": 0,
        "phase1b_files_linked": 0,
    }

    # Find files that have:
    # - a release MBID (musicbrainz_albumid) not matching any album's musicbrainz_id
    # - a release group MBID matching an existing album (so the artist is known)
    # - artist present in DB
    sql = text(f"""
        SELECT DISTINCT
            lf.musicbrainz_albumid  AS release_mbid,
            lf.musicbrainz_releasegroupid AS rg_mbid,
            a.id AS artist_id
        FROM library_files lf
        JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
        JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid
        LEFT JOIN albums existing ON existing.musicbrainz_id = lf.musicbrainz_albumid
        WHERE lf.musicbrainz_albumid IS NOT NULL
          AND lf.musicbrainz_albumid != ''
          AND lf.musicbrainz_releasegroupid IS NOT NULL
          AND lf.musicbrainz_releasegroupid != ''
          AND existing.id IS NULL
          {path_filter}
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 1B: No files with unknown release MBIDs found")
        return stats

    job_logger.log_info(f"Phase 1B: Found {len(rows)} release MBIDs needing new album records")

    mb_client = get_musicbrainz_client()
    total = len(rows)

    for i, row in enumerate(rows):
        if i % 50 == 0 and i > 0:
            job.current_action = f"Phase 1B: Creating release albums {i}/{total}"
            job.progress_percent = 20 + (i / total) * 15
            try:
                db.commit()
            except Exception:
                pass

        try:
            album = import_release(
                db=db,
                release_mbid=row.release_mbid,
                release_group_mbid=row.rg_mbid,
                artist_id=row.artist_id,
                mb_client=mb_client,
            )
            if album:
                stats["phase1b_albums_created"] += 1
                # Link all files for this release to their matching tracks
                linked = _link_files_for_release(db, album)
                stats["phase1b_files_linked"] += linked
        except Exception as e:
            job_logger.log_info(f"Phase 1B: Failed to import release {row.release_mbid}: {e}")

    db.commit()
    _mark_resolved_files(db, job_logger)

    job_logger.log_info(
        f"Phase 1B: Created {stats['phase1b_albums_created']} albums, "
        f"linked {stats['phase1b_files_linked']} files"
    )
    job_logger.log_phase_complete("Phase 1B", count=stats["phase1b_albums_created"])
    return stats


def _link_files_for_release(db, album) -> int:
    """Link library files to their matching tracks within a newly-created release album."""
    linked = 0
    tracks = db.query(Track).filter(Track.album_id == album.id).all()
    for track in tracks:
        if track.has_file:
            continue
        lf = db.query(LibraryFile).filter(
            LibraryFile.musicbrainz_trackid == track.musicbrainz_id,
            LibraryFile.musicbrainz_albumid == album.musicbrainz_id,
        ).first()
        if lf:
            track.has_file = True
            track.file_path = lf.file_path
            linked += 1
    return linked
```

Also add the `LibraryFile` import at the top of `resolve_unlinked_task.py` if not already present:
```python
from app.models.library import LibraryFile
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest app/tasks/tests/test_resolve_unlinked_phase1b.py -v
```

Expected: Both tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add studio54-service/app/tasks/resolve_unlinked_task.py \
        studio54-service/app/tasks/tests/test_resolve_unlinked_phase1b.py
git commit -m "feat: Phase 1B creates per-release albums instead of dumping tracks into RG stub"
```

---

## Task 5: Update `sync_tasks.py` — File-Existence Check for Per-Release Albums

**Files:**
- Modify: `studio54-service/app/tasks/sync_tasks.py`

The file-existence check at line ~492 currently matches library files using `LibraryFile.musicbrainz_releasegroupid == album.musicbrainz_id`. After the migration, per-release albums have `musicbrainz_id` = release MBID, so the check must also cover `LibraryFile.musicbrainz_albumid`.

- [ ] **Step 1: Update the library file existence check**

Find the block in `sync_tasks.py` (around line 490–497):

```python
            studio54_file_count = db.query(LibraryFile).filter(
                LibraryFile.musicbrainz_releasegroupid == album.musicbrainz_id
            ).count()
            if studio54_file_count >= min_track_count:
                album.status = AlbumStatus.DOWNLOADED
                logger.info(f"Album '{album.title}' found in Studio54 library ({studio54_file_count} files)")
```

Replace with:

```python
            # Per-release albums: match by release MBID; stubs: match by RG MBID
            is_per_release = bool(album.release_group_mbid and album.musicbrainz_id != album.release_group_mbid)
            if is_per_release:
                studio54_file_count = db.query(LibraryFile).filter(
                    LibraryFile.musicbrainz_albumid == album.musicbrainz_id
                ).count()
            else:
                studio54_file_count = db.query(LibraryFile).filter(
                    LibraryFile.musicbrainz_releasegroupid == album.musicbrainz_id
                ).count()
            if studio54_file_count >= min_track_count:
                album.status = AlbumStatus.DOWNLOADED
                logger.info(f"Album '{album.title}' found in Studio54 library ({studio54_file_count} files)")
```

- [ ] **Step 2: Run the existing test suite to ensure no regressions**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/ app/ -v --ignore=app/tasks/tests/test_resolve_unlinked_phase1b.py -x 2>&1 | tail -30
```

Expected: All existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add studio54-service/app/tasks/sync_tasks.py
git commit -m "feat: use release MBID for file-existence check on per-release albums"
```

---

## Task 6: Expose `release_group_mbid` in Album API Response

**Files:**
- Modify: `studio54-service/app/api/albums.py`

The `get_album` endpoint (line ~587) returns a dict. Add `release_group_mbid` to it and to the `list_albums` response.

- [ ] **Step 1: Add `release_group_mbid` to `get_album` response**

In `get_album` (line ~587), add after `"release_mbid": album.release_mbid,`:

```python
        "release_group_mbid": album.release_group_mbid,
```

- [ ] **Step 2: Add `release_group_mbid` to `list_albums` response**

In `app/api/albums.py`, find the `list_albums` album dict (around line 162). Add after `"release_mbid": album.release_mbid,`:

```python
                "release_group_mbid": album.release_group_mbid,
```

The updated block looks like:

```python
            {
                "id": str(album.id),
                "title": album.title,
                "artist_id": str(album.artist_id),
                "artist_name": album.artist.name if album.artist else "Unknown",
                "musicbrainz_id": album.musicbrainz_id,
                "release_mbid": album.release_mbid,
                "release_group_mbid": album.release_group_mbid,
                "release_date": album.release_date.isoformat() if album.release_date else None,
                "album_type": album.album_type,
                "status": album.status.value,
                "monitored": album.monitored,
                "track_count": album.track_count,
                "cover_art_url": album.cover_art_url,
                "custom_folder_path": album.custom_folder_path,
                "muse_verified": album.muse_verified,
                "linked_files_count": int(linked_count or 0)
            }
```

- [ ] **Step 3: Write a quick integration test**

Add to `app/services/tests/test_album_importer.py`:

```python
def test_get_album_api_includes_release_group_mbid(client, db_session):
    """GET /albums/{id} response must include release_group_mbid."""
    from app.models.artist import Artist
    from app.models.album import Album, AlbumStatus
    import uuid

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

    response = client.get(f"/api/v1/albums/{album.id}")
    assert response.status_code == 200
    data = response.json()
    assert "release_group_mbid" in data
    assert data["release_group_mbid"] == rg_mbid
```

- [ ] **Step 4: Run the test**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest app/services/tests/test_album_importer.py::test_get_album_api_includes_release_group_mbid -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add studio54-service/app/api/albums.py studio54-service/app/services/tests/test_album_importer.py
git commit -m "feat: expose release_group_mbid in album API response"
```

---

## Task 7: Write the One-Time Migration Script

**Files:**
- Create: `studio54-service/scripts/migrate_per_release_albums.py`
- Create: `studio54-service/scripts/tests/test_migrate_per_release_albums.py`

- [ ] **Step 1: Write tests for all four migration cases**

Create `studio54-service/scripts/tests/test_migrate_per_release_albums.py`:

```python
"""Tests for the per-release album migration script."""
import uuid
import pytest
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


def _lf(db, lp_id, file_path, recording_mbid, album_mbid, rg_mbid):
    lf = LibraryFile(
        id=uuid.uuid4(), library_path_id=lp_id, file_path=file_path,
        file_name=file_path.split("/")[-1], file_size_bytes=1000,
        file_modified_at="2024-01-01 00:00:00+00", title="T",
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
        file_size_bytes=1000, file_modified_at="2024-01-01 00:00:00+00",
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest scripts/tests/test_migrate_per_release_albums.py -v 2>&1 | tail -20
```

Expected: `ERROR` — script does not exist yet

- [ ] **Step 3: Write the migration script**

Create `studio54-service/scripts/migrate_per_release_albums.py`:

```python
"""
One-time migration: split albums from one-per-release-group to one-per-release.

Run with:
    docker exec studio54-service python scripts/migrate_per_release_albums.py

Or from outside the container:
    docker exec studio54-service python -m scripts.migrate_per_release_albums
"""
import sys
import os
import uuid
import logging
from collections import defaultdict
from typing import Optional

# Allow running from the service root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import SessionLocal
from app.models.album import Album, AlbumStatus
from app.models.track import Track
from app.models.library import LibraryFile

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BATCH_SIZE = 500


def migrate_album(db: Session, album: Album, mb_client=None) -> str:
    """
    Migrate a single album. Returns one of: 'stub', 'converted', 'split', 'legacy'.

    - stub: no files, release_group_mbid set, musicbrainz_id unchanged
    - converted: single release, musicbrainz_id re-keyed to release MBID
    - split: mixed releases, album split into multiple records
    - legacy: files present but no musicbrainz_albumid tags, marked as legacy
    """
    # Skip if already migrated
    if album.release_group_mbid is not None:
        return "already_done"

    # Find tracks with files and their library file release MBIDs
    file_tracks = db.query(Track).filter(
        Track.album_id == album.id,
        Track.has_file == True,
        Track.file_path.isnot(None),
    ).all()

    if not file_tracks:
        # Case 1: No files — wanted stub
        album.release_group_mbid = album.musicbrainz_id
        return "stub"

    # Look up musicbrainz_albumid for each file
    release_to_tracks = defaultdict(list)
    no_albumid_tracks = []

    for track in file_tracks:
        lf = db.query(LibraryFile).filter(
            LibraryFile.file_path == track.file_path
        ).first()
        if lf and lf.musicbrainz_albumid:
            release_to_tracks[lf.musicbrainz_albumid].append(track)
        else:
            no_albumid_tracks.append(track)

    if not release_to_tracks:
        # Case 4: Has files but no musicbrainz_albumid on any
        album.release_group_mbid = album.musicbrainz_id
        return "legacy"

    old_rg_mbid = album.musicbrainz_id

    if len(release_to_tracks) == 1:
        # Case 2: Single release — re-key this album
        release_mbid = list(release_to_tracks.keys())[0]
        # Guard: another album may already use this release MBID
        conflict = db.query(Album).filter(
            Album.musicbrainz_id == release_mbid,
            Album.id != album.id,
        ).first()
        if conflict:
            album.release_group_mbid = old_rg_mbid
            return "legacy"
        album.musicbrainz_id = release_mbid
        album.release_mbid = release_mbid
        album.release_group_mbid = old_rg_mbid
        return "converted"

    # Case 3: Mixed releases — split
    # Sort releases by number of tracks (descending); largest group keeps the original record
    sorted_releases = sorted(release_to_tracks.items(), key=lambda x: len(x[1]), reverse=True)

    primary_release_mbid, primary_tracks = sorted_releases[0]
    conflict = db.query(Album).filter(
        Album.musicbrainz_id == primary_release_mbid,
        Album.id != album.id,
    ).first()
    if not conflict:
        album.musicbrainz_id = primary_release_mbid
        album.release_mbid = primary_release_mbid
    album.release_group_mbid = old_rg_mbid

    # Prune tracks from this album that don't belong to the primary release
    primary_track_ids = {t.id for t in primary_tracks}
    for track in file_tracks:
        if track.id not in primary_track_ids:
            db.delete(track)

    # Create new album records for remaining releases
    for release_mbid, tracks in sorted_releases[1:]:
        conflict = db.query(Album).filter(Album.musicbrainz_id == release_mbid).first()
        if conflict:
            continue

        new_album = Album(
            id=uuid.uuid4(),
            artist_id=album.artist_id,
            title=album.title,
            musicbrainz_id=release_mbid,
            release_mbid=release_mbid,
            release_group_mbid=old_rg_mbid,
            album_type=album.album_type,
            secondary_types=album.secondary_types,
            release_date=album.release_date,
            status=album.status,
            monitored=album.monitored,
            cover_art_url=album.cover_art_url,
        )
        db.add(new_album)
        db.flush()

        for track in tracks:
            track.album_id = new_album.id

    return "split"


def run_migration(db: Session) -> dict:
    """Run the full migration over all albums in batches."""
    stats = {"stub": 0, "converted": 0, "split": 0, "legacy": 0,
             "already_done": 0, "errors": 0}

    offset = 0
    while True:
        batch = db.query(Album).filter(
            Album.release_group_mbid.is_(None)
        ).limit(BATCH_SIZE).offset(offset).all()

        if not batch:
            break

        for album in batch:
            try:
                result = migrate_album(db, album)
                stats[result] = stats.get(result, 0) + 1
            except Exception as e:
                logger.error(f"Error migrating album {album.id} ({album.musicbrainz_id}): {e}")
                stats["errors"] += 1
                db.rollback()

        db.commit()
        offset += BATCH_SIZE
        logger.info(f"Processed {offset} albums... {stats}")

    return stats


def run_validation(db: Session) -> dict:
    """
    Run post-migration validation checks.
    Returns a dict of check_name -> {pass: bool, count: int, sample_ids: list}.
    """
    report = {}

    # Check 1: No duplicate track positions
    rows = db.execute(text("""
        SELECT album_id, COUNT(*) as cnt
        FROM (
            SELECT album_id, disc_number, track_number
            FROM tracks
            WHERE track_number IS NOT NULL
            GROUP BY album_id, disc_number, track_number
            HAVING COUNT(*) > 1
        ) dupes
        GROUP BY album_id
    """)).fetchall()
    report["duplicate_track_positions"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 2: No cross-release file contamination
    rows = db.execute(text("""
        SELECT t.album_id, COUNT(DISTINCT lf.musicbrainz_albumid) as release_count
        FROM tracks t
        JOIN library_files lf ON lf.file_path = t.file_path
        WHERE lf.musicbrainz_albumid IS NOT NULL AND lf.musicbrainz_albumid != ''
          AND t.has_file = true
        GROUP BY t.album_id
        HAVING COUNT(DISTINCT lf.musicbrainz_albumid) > 1
    """)).fetchall()
    report["cross_release_contamination"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 3: release_group_mbid populated on all albums
    rows = db.execute(text("""
        SELECT id FROM albums WHERE release_group_mbid IS NULL
    """)).fetchall()
    report["release_group_mbid_populated"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 4: musicbrainz_id uniqueness
    rows = db.execute(text("""
        SELECT musicbrainz_id, COUNT(*) FROM albums
        GROUP BY musicbrainz_id HAVING COUNT(*) > 1
    """)).fetchall()
    report["musicbrainz_id_uniqueness"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 5: No orphaned tracks (file's albumid != track's album's musicbrainz_id)
    rows = db.execute(text("""
        SELECT t.id
        FROM tracks t
        JOIN library_files lf ON lf.file_path = t.file_path
        JOIN albums al ON al.id = t.album_id
        WHERE t.has_file = true
          AND lf.musicbrainz_albumid IS NOT NULL
          AND lf.musicbrainz_albumid != ''
          AND lf.musicbrainz_albumid != al.musicbrainz_id
    """)).fetchall()
    report["orphaned_tracks"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    return report


def print_report(report: dict):
    print("\n=== Validation Report ===")
    all_passed = True
    for check, result in report.items():
        icon = "✓" if result["pass"] else "✗"
        print(f"  {icon} {check}: count={result['count']}")
        if not result["pass"]:
            all_passed = False
            for aid in result.get("sample_ids", []):
                print(f"      → {aid}")
    print(f"\nOverall: {'PASSED' if all_passed else 'FAILED'}")
    return all_passed


if __name__ == "__main__":
    logger.info("Starting per-release album migration...")
    db = SessionLocal()
    try:
        stats = run_migration(db)
        logger.info(f"Migration complete: {stats}")

        report = run_validation(db)
        passed = print_report(report)
        sys.exit(0 if passed else 1)
    finally:
        db.close()
```

- [ ] **Step 4: Create `scripts/tests/__init__.py`** (`scripts/` already exists)

```bash
mkdir -p /home/tesimmons/Studio54/studio54-service/scripts/tests
touch /home/tesimmons/Studio54/studio54-service/scripts/__init__.py
touch /home/tesimmons/Studio54/studio54-service/scripts/tests/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest scripts/tests/test_migrate_per_release_albums.py -v
```

Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add studio54-service/scripts/migrate_per_release_albums.py \
        studio54-service/scripts/__init__.py \
        studio54-service/scripts/tests/__init__.py \
        studio54-service/scripts/tests/test_migrate_per_release_albums.py
git commit -m "feat: add per-release album migration script with validation"
```

---

## Task 8: Run Full Test Suite

- [ ] **Step 1: Run all tests**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/ app/ scripts/ -v 2>&1 | tail -40
```

Expected: All tests pass, no regressions.

- [ ] **Step 2: If any tests fail, fix them before proceeding**

---

## Task 9: Execute the Migration Against the Live Database

> **WARNING:** This is destructive and irreversible. Run on a database snapshot first if possible.

- [ ] **Step 1: Take a database snapshot**

```bash
docker exec studio54-db pg_dump -U studio54 studio54_db > /tmp/studio54_pre_migration_$(date +%Y%m%d_%H%M%S).sql
```

- [ ] **Step 2: Run the migration script**

```bash
docker exec studio54-service python scripts/migrate_per_release_albums.py
```

Expected output ends with:
```
=== Validation Report ===
  ✓ duplicate_track_positions: count=0
  ✓ cross_release_contamination: count=0
  ✓ release_group_mbid_populated: count=0
  ✓ musicbrainz_id_uniqueness: count=0
  ✓ orphaned_tracks: count=0

Overall: PASSED
```

- [ ] **Step 3: Spot-check the problem album in the database**

```bash
docker exec studio54-db psql -U studio54 -d studio54_db -c "
SELECT a.musicbrainz_id, a.release_group_mbid, t.track_number, t.disc_number, t.title
FROM tracks t
JOIN albums a ON a.id = t.album_id
WHERE a.release_group_mbid = (
  SELECT release_group_mbid FROM albums WHERE id = '4e6c28be-c946-4343-90fe-79a57d827c5b'
)
ORDER BY a.musicbrainz_id, t.disc_number, t.track_number;"
```

Expected: Multiple albums each with non-duplicate track numbers. No two tracks share the same `(disc_number, track_number)` within the same album.

- [ ] **Step 4: Rebuild and redeploy**

```bash
cd /home/tesimmons/Studio54
docker compose build studio54-service studio54-web
docker compose up -d studio54-service studio54-web studio54-worker studio54-beat
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: run per-release album migration on live database"
```
