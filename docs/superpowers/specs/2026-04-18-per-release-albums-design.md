# Per-Release Albums Design

**Date:** 2026-04-18  
**Status:** Approved  
**Problem:** Multiple releases of the same album (e.g. Elephant 2004 + Elephant XX 2023) collapse into one album record, producing duplicate track numbers and mixed track lists.  
**Root cause:** `albums.musicbrainz_id` stores the MusicBrainz release group MBID (the umbrella concept), not a specific release MBID. Phase 1B of `resolve_unlinked_task` dumps files from any release of the same release group into the same album record.

---

## Decision Summary

- **Granularity:** One album record per specific release — but only for releases we have files for. No phantom stubs for every pressing or country variant.
- **Monitoring:** Stays at the release group level. Wanted stubs keep `musicbrainz_id` = RG MBID. Per-release owned albums have `musicbrainz_id` = release MBID.
- **Existing data:** Full migration — split mixed-release albums, re-key owned albums to release MBIDs, leave unresolvable albums as legacy.
- **Data model:** Approach 2 — add `release_group_mbid` column to `albums`. No new tables.

---

## Section 1: Schema Changes

### New column

```sql
ALTER TABLE albums ADD COLUMN release_group_mbid VARCHAR(36);
CREATE INDEX ix_albums_release_group_mbid ON albums(release_group_mbid);
```

### Semantics

| Album type | `musicbrainz_id` | `release_group_mbid` | `release_mbid` |
|---|---|---|---|
| Wanted stub (no files) | RG MBID | same as `musicbrainz_id` | NULL |
| Per-release owned | Release MBID | Parent RG MBID | same as `musicbrainz_id` |
| Legacy (unresolvable) | RG MBID | same as `musicbrainz_id` | NULL |

The existing `UNIQUE` constraint on `musicbrainz_id` stays intact — RG MBIDs and release MBIDs live in separate namespaces in MusicBrainz, so they never collide.

`release_mbid` (already exists in schema) becomes an alias for `musicbrainz_id` on per-release albums. Migration sets `release_mbid = musicbrainz_id` for owned albums so both fields stay consistent.

---

## Section 2: Migration Pass

Runs as a one-time offline script (not Celery — too destructive for async). Processes all albums in batches.

### Case 1 — Wanted stub (no files)
Set `release_group_mbid = musicbrainz_id`. Leave `musicbrainz_id` as RG MBID. No other changes.

### Case 2 — Single release (all files share one `musicbrainz_albumid`)
- Set `musicbrainz_id = that release MBID`
- Set `release_group_mbid = old musicbrainz_id`
- Set `release_mbid = musicbrainz_id`
- Fetch track list for the specific release from MusicBrainz
- Reconcile tracks: update `track_number` / `disc_number` from real release data

### Case 3 — Mixed releases (files tagged with multiple `musicbrainz_albumid` values)
- Group files (and their tracks) by `musicbrainz_albumid`
- Largest group keeps the existing album record, re-keyed to its release MBID
- Each other group gets a new album record cloned from the original (`artist_id`, `title`, `status`, cover art, etc.), keyed to its release MBID, with `release_group_mbid` pointing to the original RG MBID
- Tracks are re-assigned to their correct album
- Orphan tracks (no file, not belonging to any remaining release) are pruned

### Case 4 — Has files but no `musicbrainz_albumid` on any file
Cannot determine specific release. Set `release_group_mbid = musicbrainz_id`, leave `musicbrainz_id` as RG MBID. Marked as "legacy" — won't be split, won't accept new cross-release files from the new pipeline.

### Migration output
Logs a summary: albums converted, albums split, albums left as legacy, errors.

### Validation pass (runs after migration)
Script asserts all of the following and prints a pass/fail report with counts and first 10 offending album IDs per failure:

1. **No duplicate track positions** — no two tracks under the same album share `(disc_number, track_number)`
2. **No cross-release file contamination** — all files linked to an album share the same `musicbrainz_albumid` (or have none)
3. **`release_group_mbid` populated on all albums** — no NULLs (every album — stub, per-release, or legacy — has this set)
4. **`musicbrainz_id` uniqueness holds** — UNIQUE constraint still intact
5. **No orphaned tracks** — no track whose file's `musicbrainz_albumid` doesn't match the track's album's `musicbrainz_id`

---

## Section 3: Pipeline Changes

### `album_importer.py`

**`import_release_group()` — becomes stub-only**
Creates a WANTED album with `musicbrainz_id` = RG MBID and `release_group_mbid` = same value. No longer calls `select_best_release()` or creates tracks. Tracks belong to specific releases, not stubs.

**New `import_release(release_mbid, release_group_mbid, artist_id, db, mb_client)`**
- Fetches the specific release by release MBID
- Creates tracks with correct `track_number` / `disc_number` from that release's data
- Sets `musicbrainz_id` = release MBID, `release_group_mbid` = parent RG MBID, `release_mbid` = release MBID

### `resolve_unlinked_task.py` — Phase 1B

**Before:** Finds files whose recording MBID isn't in tracks, dumps them as new tracks under whatever album matches the RG MBID — causing duplicate track numbers.

**After:** When a file has a `musicbrainz_albumid` (release MBID) that doesn't match any existing album's `musicbrainz_id`, calls `import_release()` to create a proper per-release album, then links the file to it. If the release MBID already has an album, links normally. Cross-release track dumping is eliminated.

### `sync_tasks.py`

Unchanged for artist sync — still creates wanted stubs per release group. One change: when linking files to a synced album, checks `musicbrainz_albumid` on the file and routes to the per-release album rather than the stub.

---

## Section 4: API & UI Changes

### API (`albums.py`)
Add `release_group_mbid` to the album response schema. No other endpoint changes.

### Frontend — Artist page
Multiple owned releases of the same album appear as separate album cards, disambiguated by title and year. No grouping UI required for this iteration.

### Frontend — Album detail page
No structural changes. Track list will be correct (no duplicate track numbers). A "part of release group" link is a follow-on, out of scope here.

### Frontend — Wanted stubs
Stubs and per-release albums coexist on the artist page. Display logic to hide stubs once a release is owned is a follow-on.

---

## Files Changed

| File | Change |
|---|---|
| `alembic/versions/YYYYMMDD_release_group_mbid.py` | Add `release_group_mbid` column + index |
| `scripts/migrate_per_release_albums.py` | One-time migration + validation script |
| `app/models/album.py` | Add `release_group_mbid` field |
| `app/services/album_importer.py` | Stub-only `import_release_group()`, new `import_release()` |
| `app/tasks/resolve_unlinked_task.py` | Phase 1B: route to `import_release()` instead of dumping tracks |
| `app/tasks/sync_tasks.py` | Route file linking through release MBID |
| `app/api/albums.py` | Expose `release_group_mbid` in response schema |

---

## Out of Scope

- UI grouping of releases under a release group header
- Hiding wanted stubs once a release is owned
- Handling albums with no MusicBrainz tags at all
- Audiobook / book model (separate system)
