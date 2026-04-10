# Studio54 Workflow Test Results
**Test Date:** 2026-02-06 (Updated: 2026-02-07)
**Test Artist:** Johnny Cash (ID: `61a9b2d0-1e0b-422a-acf7-721d69071e19`)

---

## Summary

| Category | Working | Broken | Notes |
|----------|---------|--------|-------|
| Artist Management | 5/5 | 0/5 | All endpoints functional |
| Album Management | 5/5 | 0/5 | PATCH requires JSON body (documented) |
| Search & Decision Engine | 3/3 | 0/3 | ~~Grab FK bug~~ **FIXED** |
| File Organization | 7/7 | 0/7 | ~~verify-audio 500~~ **FIXED** |
| Queue Management | 3/3 | 0/3 | All working |
| Job Management | 2/3 | 1/3 | Jobs can get stuck at 0% (needs monitoring) |

## Fixes Applied

### FIX #1: Grab FK Violation ✅ FIXED
- **File:** `app/services/download/process_decisions.py`
- **Change:** Added `self.db.flush()` after adding TrackedDownload to session
- **Status:** Tested and working

### FIX #2: verify-audio 500 Error ✅ FIXED
- **File:** `app/api/file_management.py`
- **Change:** Changed `created_at` to `indexed_at` (column didn't exist)
- **Status:** Tested and working

---

## Working Endpoints ✅

### Artist Management
- `POST /api/v1/artists/search?query=...` - MusicBrainz artist search ✅
- `POST /api/v1/artists` - Add artist to library ✅
- `GET /api/v1/artists/{id}` - Get artist details ✅
- `PATCH /api/v1/artists/{id}?is_monitored=true` - Update artist (query params) ✅
- `POST /api/v1/artists/{id}/sync` - Sync artist from MusicBrainz ✅

### Album Management
- `GET /api/v1/albums` - List all albums ✅
- `GET /api/v1/albums/{id}` - Get album details ✅
- `PATCH /api/v1/albums/{id}` - Update album (requires JSON body: `{"monitored": true}`) ✅
- `GET /api/v1/albums/wanted` - List wanted albums ✅

### Search & Decision Engine
- `POST /api/v1/search/albums/{album_id}` - Search indexers for album releases ✅
  - Note: Path is `/albums/` (plural), NOT `/album/` (singular)
  - Returns decisions with approved/rejected status and rejection reasons
- `POST /api/v1/search/artists/{artist_id}` - Search all wanted albums for artist ✅

### File Organization
- `GET /api/v1/file-organization/jobs` - List organization jobs ✅
- `POST /api/v1/file-organization/library-paths/{id}/validate` - Validate structure ✅
- `POST /api/v1/file-organization/library-paths/{id}/fetch-metadata` - Fetch MBIDs ✅
- `POST /api/v1/file-organization/library-paths/{id}/validate-mbid` - Validate MBIDs ✅
- `POST /api/v1/file-organization/library-paths/{id}/link-files` - Link files to tracks ✅
- `POST /api/v1/file-organization/library-paths/{id}/reindex-albums` - Reindex albums ✅

### Queue Management
- `GET /api/v1/queue` - Get download queue ✅
- `GET /api/v1/queue/blacklist` - Get blacklisted releases ✅
- `GET /api/v1/queue/history` - Get download history ✅

### Other
- `GET /api/v1/indexers` - List configured indexers ✅
- `GET /api/v1/download-clients` - List download clients ✅
- `GET /api/v1/library/paths` - List library paths ✅
- `GET /api/v1/jobs` - List all jobs (unified endpoint) ✅
- `POST /api/v1/jobs/{id}/cancel` - Cancel a job ✅

---

## Issues Found and Fixed

### BUG #1: Grab Workflow FK Violation ✅ FIXED
**Endpoint:** `POST /api/v1/search/albums/{album_id}/grab`
**Error:**
```
ForeignKeyViolation: insert or update on table "download_history" violates
foreign key constraint "download_history_tracked_download_id_fkey"
Key (tracked_download_id)=(...) is not present in table "tracked_downloads"
```

**Root Cause:** In `app/services/download/process_decisions.py`, the `process_single()` method:
1. Line 214: `self.db.add(tracked)` - adds TrackedDownload to session
2. Line 217: `self._record_grabbed(...)` - creates DownloadHistory referencing tracked.id
3. Line 222: `self.db.commit()` - commits both

The TrackedDownload is not flushed before creating DownloadHistory, causing FK violation.

**Fix:** Add `self.db.flush()` after line 214:
```python
self.db.add(tracked)
self.db.flush()  # Ensure tracked download exists before referencing
self._record_grabbed(release_info, album, artist, tracked, client_model)
```

**File:** `studio54-service/app/services/download/process_decisions.py:214`

---

### BUG #2: verify-audio Returns 500 Internal Server Error ✅ FIXED
**Endpoint:** `POST /api/v1/file-organization/library-paths/{id}/verify-audio`
**Request:** `{"days_back": 7}` (note: field is `days_back`, not `days`)
**Response:** Now returns properly

**Root Cause:** Query used non-existent `created_at` column instead of `indexed_at`

**Fix:** Changed line 1807 in `app/api/file_management.py`:
```sql
-- Before: AND created_at >= :cutoff_date
-- After:  AND indexed_at >= :cutoff_date
```

---

### BUG #3: Jobs Can Stall Indefinitely at 0%
**Observed:** Two jobs (`album_search` and `artist_sync`) ran for 6+ hours at 0% progress with no error message.

**Task IDs:**
- album_search: `01beaee6-bb90-4ad7-be19-076bb0763520`
- artist_sync: `22bcc838-b4cc-48aa-a526-724e0d413749`

**Root Cause:** Tasks appear to have been accepted by Celery but never executed or silently failed without updating job status.

**Recommendations:**
1. Add heartbeat mechanism - jobs should update `last_heartbeat_at` regularly
2. Add job timeout handling - mark jobs as failed if no progress after X hours
3. Add better error capturing - ensure exceptions update job status
4. Consider a job monitor task that checks for stale jobs

---

### BUG #4: studio54-web Container Unhealthy
**Status:** Container shows `unhealthy` but service appears functional
**Impact:** May affect health checks and orchestration

---

### Issue #5: API Inconsistency - Artist vs Album Update
**Artist Update:** Uses query parameters
```
PATCH /api/v1/artists/{id}?is_monitored=true
```

**Album Update:** Uses JSON body
```
PATCH /api/v1/albums/{id}
Content-Type: application/json
{"monitored": true}
```

**Recommendation:** Standardize on one approach (prefer JSON body for PATCH requests per REST conventions)

---

## Test Commands Reference

### Search for Album Releases
```bash
curl -X POST "http://localhost:8010/api/v1/search/albums/{album_id}" \
  -H "Content-Type: application/json"
```

### Monitor an Artist
```bash
curl -X PATCH "http://localhost:8010/api/v1/artists/{artist_id}?is_monitored=true"
```

### Monitor an Album
```bash
curl -X PATCH "http://localhost:8010/api/v1/albums/{album_id}" \
  -H "Content-Type: application/json" \
  -d '{"monitored": true}'
```

### Grab a Release (currently broken)
```bash
curl -X POST "http://localhost:8010/api/v1/search/albums/{album_id}/grab" \
  -H "Content-Type: application/json" \
  -d '{
    "release_guid": "...",
    "release_data": {
      "title": "...",
      "guid": "...",
      "indexer_id": "{valid-uuid}",
      "indexer_name": "...",
      "download_url": "...",
      "size": 123456,
      "quality": "FLAC"
    }
  }'
```

### Cancel a Stalled Job
```bash
curl -X POST "http://localhost:8010/api/v1/jobs/{job_id}/cancel"
```

---

## Fix Priority

1. **HIGH** - BUG #1: Grab FK Violation - Blocks all download functionality
2. **HIGH** - BUG #3: Job Stalling - Can leave orphaned jobs consuming resources
3. **MEDIUM** - BUG #2: verify-audio 500 - Feature unusable
4. **LOW** - BUG #4: Web unhealthy - Cosmetic/monitoring issue
5. **LOW** - Issue #5: API inconsistency - Developer experience

---

## Files to Modify

| File | Bug | Change Required |
|------|-----|-----------------|
| `app/services/download/process_decisions.py` | #1 | Add `self.db.flush()` after line 214 |
| `app/api/file_management.py` | #2 | Investigate and fix verify-audio endpoint |
| `app/tasks/*.py` | #3 | Add heartbeat and timeout handling |
| `Dockerfile` or `docker-compose.yml` | #4 | Fix web container health check |
