# Studio54 — Engineering Enhancement Recommendations

**Version:** 1.0  
**Date:** 2026-05-14  
**Reviewer:** Senior Software Engineer  

> This document is a structured code review and architectural critique of the Studio54 codebase. Issues are graded **P0** (critical / fix now), **P1** (high / next sprint), and **P2** (medium / backlog). File and line references are pinned to the codebase as of branch `ui-update`.

---

## Table of Contents

1. [Security](#1-security)
2. [Stability & Reliability](#2-stability--reliability)
3. [Performance & Scalability](#3-performance--scalability)
4. [Error Handling](#4-error-handling)
5. [Backend Architecture](#5-backend-architecture)
6. [Frontend Architecture](#6-frontend-architecture)
7. [Infrastructure & Deployment](#7-infrastructure--deployment)
8. [Testing](#8-testing)
9. [Priority Summary](#9-priority-summary)

---

## 1. Security

### 1.1 JWT Secret Key Reused as Fernet Encryption Key — **P0**

**File:** `studio54-service/app/auth.py:10`  
```python
JWT_SECRET = settings.studio54_encryption_key
```

The JWT signing key is the **same value** as `STUDIO54_ENCRYPTION_KEY`, which is also used by `app/services/encryption.py` to Fernet-encrypt all stored API keys and webhook URLs. This means a single leaked environment variable compromises both authentication tokens and every stored secret simultaneously.

**Fix:** Introduce a dedicated `JWT_SECRET_KEY` environment variable. Keep `STUDIO54_ENCRYPTION_KEY` strictly for Fernet encryption. Update `config.py`:
```python
jwt_secret_key: str          # separate from encryption key
studio54_encryption_key: str  # Fernet only
```

---

### 1.2 JWT Tokens Stored in `localStorage` — **P0**

**File:** `studio54-web/src/api/client.ts:47`  
```typescript
const token = localStorage.getItem('studio54_token')
```

`localStorage` is accessible to any JavaScript running on the page, making tokens trivially stealable via XSS. This is a well-documented vulnerability for auth tokens. Although Studio54 is self-hosted with a controlled user base, a single stored XSS in user-controlled data (e.g., a track title with `<script>` tags not properly escaped) would fully compromise sessions.

**Fix:** Move to `httpOnly`, `Secure`, `SameSite=Strict` cookies. The backend issues the cookie on login; the browser sends it automatically and JavaScript cannot read it. This requires:
1. FastAPI `response.set_cookie(...)` on login
2. CORS credentials mode: `axios.defaults.withCredentials = true`
3. Removing the request interceptor that injects `Authorization` headers

---

### 1.3 7-Day Non-Refreshable JWTs — **P1**

**File:** `studio54-service/app/auth.py:21`  
```python
JWT_EXPIRY_HOURS = 168  # 7 days
```

A 7-day token lifetime means a stolen token gives an attacker a full week of access. The frontend attempts a `/auth/refresh` call in the 401 interceptor (`client.ts`), but no refresh endpoint is defined in `main.py`'s router registrations — meaning the refresh silently fails and falls through to the 401 path anyway.

**Fix:**
- Reduce access token lifetime to **15–60 minutes**
- Implement proper refresh tokens: long-lived (7 days), stored as `httpOnly` cookie, single-use, rotated on each refresh
- Add `POST /api/v1/auth/refresh` endpoint that verifies the refresh token and issues a new access token

---

### 1.4 Rate Limiting Is Not Distributed — **P1**

**File:** `studio54-service/app/main.py:44`  
```python
limiter = Limiter(key_func=get_remote_address)
```

`slowapi`'s default in-memory store means each Uvicorn worker process maintains its own rate limit counter. With multiple workers (and potentially multiple replicas), a client can make `N × limit` requests before being throttled. The login endpoint (a brute-force target) is particularly exposed.

**Fix:** Configure `slowapi` to use a Redis storage backend:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
```

---

### 1.5 Admin User Seeded in `startup_event` — **P2**

**File:** `studio54-service/app/main.py:117–138`

Creating a default `admin/admin` user at startup is dangerous in production. If the instance is exposed before the user changes the password (or if `must_change_password` enforcement is missing on the frontend), an attacker can log in with the well-known default credential.

**Fix:**
- Move first-run seeding to a dedicated Alembic migration or a one-shot CLI command (`python -m studio54 init`)
- Enforce `must_change_password` as a hard block in the frontend before any API calls are allowed (currently only advisory)
- Log a loud, visible warning if the default admin/admin credential is still active

---

### 1.6 Startup Event Uses `next(get_db())` Anti-Pattern — **P1**

**File:** `studio54-service/app/main.py:82, 122`  
```python
db = next(get_db())
...
db.close()
```

`get_db()` is a generator that yields a session and closes it in a `finally` block. Calling `next()` directly bypasses the `finally` — if an exception occurs between `next(get_db())` and the explicit `db.close()`, the session is leaked. Under heavy startup load this can exhaust the connection pool.

**Fix:** Use the session factory directly in startup:
```python
from app.database import SessionLocal
db = SessionLocal()
try:
    # work
    db.commit()
finally:
    db.close()
```

Or, better, move first-run logic out of `startup_event` entirely (see §1.5).

---

## 2. Stability & Reliability

### 2.1 Celery Beat Is a Single Point of Failure — **P1**

**File:** `docker-compose.yml` (studio54-beat service)

The entire periodic task schedule — download monitoring (30s), stall detection (2m), nightly sync, cleanup — depends on a single `studio54-beat` container. If it crashes or hangs, no periodic tasks fire. The handoff notes already record this as unhealthy (`studio54-beat` health issue traced to `DownloadDecision.to_dict()` at line 230).

**Fixes (choose one, in order of preference):**
1. **Short-term:** Add a Docker `restart: always` policy and a proper healthcheck to the beat container
2. **Medium-term:** Use [`celery-redbeat`](https://github.com/sibson/redbeat) — a Redis-backed beat scheduler that supports multiple redundant beat instances with leader election
3. **Long-term:** Replace Celery Beat with a dedicated scheduler service (e.g., APScheduler with Redis lock, or a cron-based solution)

---

### 2.2 No Circuit Breaker on External API Calls — **P1**

**Files:** `app/services/musicbrainz_client.py`, `app/services/sabnzbd_client.py`, `app/services/lastfm_client.py`, `app/services/fanart_service.py`

External APIs (MusicBrainz, SABnzbd, Last.fm, Fanart.tv, AcoustID) are called without circuit breakers. If MusicBrainz goes down, every sync task will fail slowly (waiting for `httpx` timeouts), accumulating in the queue and potentially causing worker starvation. The `tenacity` library is already in `requirements.txt` but is used only for DB retries.

**Fix:** Wrap external client calls with `tenacity` retry + circuit-breaker pattern or use a dedicated library like `circuitbreaker`:
```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
def fetch_release_group(mbid: str):
    ...
```
Set `httpx` timeouts explicitly on every call (connect=5s, read=30s).

---

### 2.3 MusicBrainz Rate Limiter Is Per-Process — **P1**

**File:** `studio54-service/app/services/musicbrainz_client.py` (rate_limiter usage), `app/config.py:50`  
```python
musicbrainz_rate_limit: float = 1.0  # requests per second
```

The 1 req/sec MusicBrainz API rate limit is enforced per-process. With N Celery workers on the `sync` queue, the collective request rate is N req/sec — violating MusicBrainz's terms and triggering 503 throttling.

**Fix:** Replace the in-process rate limiter with a Redis-backed token bucket:
```python
import redis, time
def acquire_mb_token(r: redis.Redis, key="mb_rate_limit", rate=1.0):
    # INCR + EXPIRE pattern or lua script for atomic token bucket
```
The `rate_limiter.py` service already exists — extend it to support Redis-backed distributed limiting.

---

### 2.4 `detect_stalled_jobs` Marks Stalled But Does Not Retry — **P2**

**File:** `studio54-service/app/tasks/monitoring_tasks.py:20–80`

Jobs marked `STALLED` require manual user intervention from the File Management UI. There is no automatic retry path for stalled `JobState` records (e.g., artist syncs, download monitors). This is especially problematic during rolling deploys where workers restart mid-task.

**Fix:** After marking a job `STALLED`, check `retry_count < max_retries` and re-dispatch the Celery task. Track which jobs were auto-retried in the `error_message` field.

---

### 2.5 Denormalized Counts Can Drift — **P2**

**Files:** `app/models/artist.py:64–66`, `app/models/author.py:51–53`  
```python
album_count = Column(Integer, default=0)
single_count = Column(Integer, default=0)
track_count = Column(Integer, default=0)
```

These counters are updated by background tasks but are not protected by DB-level constraints. If a sync task fails mid-update, or if albums are deleted directly, the counts silently diverge from the actual `COUNT(*)`. Dashboard and statistics widgets rely on these figures.

**Fix:** Either:
1. Recompute counts lazily as SQL aggregates at read time (using `@hybrid_property` + subquery) — accurate but slower
2. Add a nightly reconciliation task that recomputes all denormalized counters from source data — catches drift
3. Use PostgreSQL `AFTER INSERT/DELETE` triggers to maintain atomicity

---

### 2.6 Series Monitoring Cascade Blocks the Request Thread — **P2**

**File:** `studio54-service/app/models/series.py:52–64`  
```python
event.listen(Series, "after_update", _cascade_series_monitored)
```

When `Series.monitored` is toggled, this SQLAlchemy event listener executes a synchronous `UPDATE` over all books in the series — inside the request thread — before the HTTP response is returned. For a large series (e.g., a 30-book saga), this adds hundreds of milliseconds to a simple PATCH request.

**Fix:** Dispatch the cascade as a Celery task instead:
```python
@router.patch("/series/{id}")
async def update_series(id: UUID, ...):
    series.monitored = body.monitored
    db.commit()
    cascade_series_monitored.delay(str(series.id), body.monitored)
    return series
```

---

## 3. Performance & Scalability

### 3.1 Synchronous SQLAlchemy Blocks the Async Event Loop — **P1**

**Files:** `studio54-service/app/database.py`, `studio54-service/app/main.py` (all route handlers)

FastAPI is declared as `async def` throughout, but every database call uses the synchronous SQLAlchemy session (`SessionLocal`). Under the hood, `asyncio` runs synchronous I/O in the default thread pool — which serializes DB access under concurrent load and negates FastAPI's concurrency advantage.

**Fix (progressive):**
1. **Short-term:** Run `uvicorn` with `--workers N` (already done) and ensure `DB_POOL_SIZE` ≥ N × avg_concurrent_queries
2. **Medium-term:** Migrate to `SQLAlchemy 2.0 async` with `asyncpg`:
   ```python
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
   engine = create_async_engine("postgresql+asyncpg://...", pool_size=20)
   ```
3. **Long-term:** Rewrite route handlers to `async def` using `await db.execute(...)` — unlocking true async concurrency

---

### 3.2 No Connection Pooler Between Workers and PostgreSQL — **P1**

13 Celery queue workers + multiple Uvicorn API workers each maintain their own SQLAlchemy connection pool (`pool_size=10, max_overflow=20`). In a fully loaded deployment this can attempt hundreds of simultaneous PostgreSQL connections, exceeding PostgreSQL's `max_connections` (default: 100).

**Fix:** Deploy **PgBouncer** in transaction pooling mode between all services and PostgreSQL. With PgBouncer, all workers share a small pool of real PostgreSQL connections:
```yaml
# docker-compose.yml addition
pgbouncer:
  image: pgbouncer/pgbouncer
  environment:
    DATABASES_HOST: studio54-db
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 500
    DEFAULT_POOL_SIZE: 20
```
Set `DB_POOL_SIZE=1` per worker when PgBouncer is in transaction mode.

---

### 3.3 Cover Art URL Proxy Rewriting Runs on Every Response — **P2**

**File:** `studio54-web/src/api/client.ts:57–75`  
```typescript
function proxyCoverArtUrls(data: any): any {
  if (Array.isArray(data)) return data.map(proxyCoverArtUrls)
  if (data && typeof data === 'object') { ... }  // recursive
}
```

This recursive function runs on **every** API response body to rewrite `coverartarchive.org` URLs to the backend proxy. For large album list responses (hundreds of albums, each with nested tracks), this is O(n·depth) JavaScript executing on the main thread before the UI renders.

**Fix:** Rewrite cover art URLs **server-side** in the FastAPI response serializer — once, in Python, before sending JSON to the client. The client should never see `coverartarchive.org` URLs at all:
```python
# In the album schema / response model
@validator("cover_art_url", pre=True)
def proxy_cover_art(cls, v):
    if v and "coverartarchive.org" in v:
        return v.replace("https://coverartarchive.org/release/", "/api/v1/cover-art-proxy/")
    return v
```

---

### 3.4 Sound Booth Polls Every 30 Seconds — **P2**

**Files:** `studio54-web/src/pages/SoundBooth.tsx` (polling interval), `studio54-service/app/api/now_playing.py` (Redis TTL: 60s)

The Sound Booth "Now Listening" panel polls `GET /api/v1/now-playing` every 30 seconds. With a 60-second Redis TTL on heartbeats, a listener who stops playing can appear online for up to 60 seconds after stopping, and a new listener can take up to 30 seconds to appear. It also adds 30s × N-users of unnecessary API load.

**Fix:** Replace the polling pattern with **Server-Sent Events (SSE)** or a WebSocket. FastAPI natively supports SSE:
```python
from fastapi.responses import StreamingResponse
@router.get("/now-playing/stream")
async def stream_now_playing():
    async def event_generator():
        while True:
            listeners = get_active_listeners(redis)
            yield f"data: {json.dumps(listeners)}\n\n"
            await asyncio.sleep(5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```
Reduces latency from 30s to 5s and eliminates per-user polling load.

---

### 3.5 TanStack Query `staleTime` Not Configured — **P2**

**File:** `studio54-web/src/api/client.ts` (TanStack Query usage throughout pages)

TanStack Query defaults `staleTime: 0`, meaning every window focus event triggers a background refetch for every active query. For an app where the user might have 10+ queries active (artist list, album list, stats, now-playing, etc.), this creates a burst of API calls on every tab switch.

**Fix:** Set sensible global defaults in the `QueryClient` configuration:
```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,    // 30s — data considered fresh
      gcTime: 5 * 60_000,  // 5m — keep in cache
      retry: 2,
      refetchOnWindowFocus: false, // explicit refetch where needed
    },
  },
})
```

---

## 4. Error Handling

### 4.1 `startup_event` Silently Swallows Exceptions — **P1**

**File:** `studio54-service/app/main.py:53–138`

Every block in `startup_event` wraps its logic in `try/except Exception as e: logger.error(...)`. This means a broken encryption service, a missing DB table, or a misconfigured SABnzbd connection all produce a log line — and the application starts anyway in an unknown state.

**Fix:** Distinguish between fatal and non-fatal startup failures:
```python
# Fatal — app cannot function without these
engine.connect()  # raises immediately if DB is unreachable — good
assert settings.studio54_encryption_key, "STUDIO54_ENCRYPTION_KEY is required"

# Non-fatal — log and continue (SABnzbd, MUSE may be temporarily offline)
try:
    auto_configure_sabnzbd(db)
except Exception as e:
    logger.warning(f"SABnzbd auto-config skipped: {e}")
```
Use FastAPI's `lifespan` context manager (the `@app.on_event` API is deprecated since FastAPI 0.95):
```python
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield
    await shutdown()
app = FastAPI(lifespan=lifespan)
```

---

### 4.2 No Dead Letter Queue for Failed Celery Tasks — **P1**

Permanently failed Celery tasks (exhausted retries, hard exceptions) are logged but disappear into the void. There is no way to audit what failed, replay tasks, or alert on persistent failures without querying `job_states` manually.

**Fix:** Configure a dead letter queue in Redis:
```python
# celery_app.py
celery_app.conf.update(
    task_reject_on_worker_lost=True,  # already set ✓
    task_acks_late=True,              # already set ✓
    # Add dead letter routing
    task_routes={
        ...,
    },
    # Route failed tasks to a dead letter exchange after max_retries
)
```
Alternatively, add a Celery `task_failure` signal handler that writes to a dedicated `failed_tasks` Redis list for monitoring:
```python
from celery.signals import task_failure
@task_failure.connect
def on_task_failure(task_id, exception, **kwargs):
    redis_client.lpush("studio54:dead_letter", json.dumps({
        "task_id": task_id, "error": str(exception), "ts": time.time()
    }))
```

---

### 4.3 Alternate NZB Retry Is Non-Atomic — **P2**

**Files:** `app/tasks/download_tasks.py` (`add_download`), `app/tasks/download_tasks.py` (`monitor_active_downloads`)

When SABnzbd rejects an NZB (duplicate, password-protected, etc.), the fallback to alternate NZBs is triggered **from the monitoring poll** rather than inline in `add_download`. This means there is a 30-second window where the album sits with a failed download record and no retry in flight. If the monitoring task itself fails during that window, the alternate is never tried.

**Fix:** Handle alternate submission synchronously inside `add_download`:
```python
for candidate in [primary] + alternates:
    result = sabnzbd.add_url(candidate["nzb_url"], ...)
    if result.get("status"):
        record_download(db, album, candidate)
        return {"success": True, "nzb": candidate["nzb_title"]}
    # Log rejection and try next
return {"success": False, "error": "All candidates rejected by SABnzbd"}
```

---

### 4.4 `_match_release_to_album` Is Pure String Substring Matching — **P2**

**File:** `studio54-service/app/services/decision_engine/decision_maker.py:245–276`  
```python
if album_title_lower in release_title_lower:
    return album
```

Matching a release to an album by checking if the album title is a substring of the NZB title fails on:
- Abbreviations (`DSOTM` for `The Dark Side of the Moon`)
- Punctuation differences (`AC/DC` vs `ACDC`)
- Multi-disc releases with suffixes (`Disc 1`, `Complete Edition`)
- False positives (an album titled `II` matching any release containing `II`)

**Fix:** Use fuzzy matching (the `rapidfuzz` library — lightweight, no C deps required):
```python
from rapidfuzz import fuzz
MATCH_THRESHOLD = 80
for album in albums:
    score = fuzz.token_set_ratio(release.album_name or release.title, album.title)
    if score >= MATCH_THRESHOLD:
        return album
```

---

## 5. Backend Architecture

### 5.1 `@app.on_event` Is Deprecated — **P1**

**File:** `studio54-service/app/main.py:53, 141`  
```python
@app.on_event("startup")
@app.on_event("shutdown")
```

These decorators are deprecated since FastAPI 0.95 and will be removed in a future release. The recommended pattern is the `lifespan` context manager (see §4.1 fix above).

---

### 5.2 `library_type` Gating Is Scattered Inline — **P2**

**File:** `studio54-service/app/main.py:302–408` (stats endpoint, and repeated across other endpoints)  
```python
if library_type != "audiobook":
    artists_count = ...
if library_type != "music":
    total_authors = ...
```

The music/audiobook split is implemented as inline `if library_type !=` guards repeated in every endpoint that touches both domains. This pattern is brittle — adding a third library type (e.g., podcasts) requires touching every guarded block.

**Fix:** Extract a `LibraryDomain` strategy class:
```python
class MusicDomain:
    def get_stats(self, db) -> dict: ...
class AudiobookDomain:
    def get_stats(self, db) -> dict: ...

DOMAINS = {"music": MusicDomain(), "audiobook": AudiobookDomain()}
domain = DOMAINS.get(library_type, MusicDomain())
stats = domain.get_stats(db)
```

---

### 5.3 Config Has No Validation for Critical URLs — **P2**

**File:** `studio54-service/app/config.py`

`Settings` accepts `muse_service_url`, `ollama_url`, `sabnzbd_host` as plain strings with no format validation. A misconfigured URL (e.g., missing scheme, trailing slash in wrong place) won't be caught until the first API call at runtime.

**Fix:** Use Pydantic validators:
```python
from pydantic import AnyHttpUrl, validator

class Settings(BaseSettings):
    muse_service_url: AnyHttpUrl = "http://muse-service:8007"
    ollama_url: AnyHttpUrl = "http://ollama:11434"
```

---

## 6. Frontend Architecture

### 6.1 `window.open` / `window.location.origin` — Capacitor Blockers — **P1**

**Files:** `studio54-web/src/components/PersistentPlayer.tsx`, `studio54-web/src/pages/PopOutPlayer.tsx`

Multiple calls to `window.open(...)` and `window.location.origin` exist in the player code. In a Capacitor WebView:
- `window.open` opens Safari (leaving the app) rather than in-app
- `window.location.origin` returns `capacitor://localhost`, not the backend URL

Both must be abstracted before iOS packaging can succeed.

**Fix:** Create a platform abstraction layer:
```typescript
// src/utils/platform.ts
export const openWindow = (url: string) => {
  if (Capacitor.isNativePlatform()) {
    // Use Capacitor Browser plugin for in-app browser
    Browser.open({ url })
  } else {
    window.open(url, '_blank')
  }
}

export const getApiBase = () =>
  Capacitor.isNativePlatform()
    ? import.meta.env.VITE_API_URL
    : window.location.origin + '/api/v1'
```

---

### 6.2 No React Error Boundaries — **P2**

The application has no `ErrorBoundary` components documented or visible in the component tree. An unhandled runtime error in any page component — a null dereference on API data, a malformed track title — will crash the entire React tree, including the `PersistentPlayer`, interrupting audio playback.

**Fix:** Wrap route-level components and the `PersistentPlayer` in error boundaries:
```tsx
// PersistentPlayer is always mounted — must never crash
<ErrorBoundary fallback={<MinimalPlayerFallback />}>
  <PersistentPlayer />
</ErrorBoundary>

// Per-page boundary — only the page crashes, not the shell
<ErrorBoundary fallback={<PageErrorFallback />}>
  <Outlet />
</ErrorBoundary>
```

---

### 6.3 Audio Element Has No Web Audio API Integration — **P2**

**File:** `studio54-web/src/components/PersistentPlayer.tsx`

The player uses `react-h5-audio-player`, which wraps a plain `<audio>` element. This means no crossfade between tracks, no equalizer, no ReplayGain normalization, and no waveform visualization — all of which are achievable with the Web Audio API using the audio element as a source node.

**Fix:** Connect the `<audio>` element to a `AudioContext` graph:
```typescript
const ctx = new AudioContext()
const source = ctx.createMediaElementSource(audioRef.current)
const gainNode = ctx.createGain()
source.connect(gainNode).connect(ctx.destination)
```
This enables volume normalization and crossfade without replacing the existing player.

---

### 6.4 `VITE_API_URL` Is Baked at Build Time — **P2**

**File:** `studio54-web/src/api/client.ts:35`  
```typescript
baseURL: (import.meta as any).env?.VITE_API_URL || '/api/v1',
```

`VITE_API_URL` is embedded into the JavaScript bundle during `vite build`. Changing the backend URL (e.g., from LAN IP to a domain) requires a full frontend rebuild and container redeploy.

**Fix:** Serve a small runtime config file from Nginx that the SPA fetches on first load:
```nginx
# nginx.conf — serve a dynamic config endpoint
location /config.json {
    add_header Content-Type application/json;
    return 200 '{"apiUrl":"${STUDIO54_API_URL}"}';
}
```
```typescript
// src/main.tsx
const config = await fetch('/config.json').then(r => r.json())
window.__STUDIO54_API_URL__ = config.apiUrl
```

---

## 7. Infrastructure & Deployment

### 7.1 Redis Has No Separation of Concerns — **P2**

Redis currently serves three roles:
- **Celery broker** — task queues
- **Celery result backend** — task results (TTL 1h)
- **Now-playing heartbeats** — `studio54:now_playing:*` keys (TTL 60s)

If Redis memory is exhausted (e.g., by a runaway task result accumulation), all three systems fail simultaneously. There is no alerting on Redis memory pressure.

**Fix:**
1. Use Redis databases (DB 0 for Celery, DB 1 for now-playing) to namespace usage
2. Set `maxmemory` and `maxmemory-policy allkeys-lru` in Redis config to prevent OOM crashes
3. Add a Redis memory alert to the health check endpoint

---

### 7.2 No Database Backup Strategy — **P1**

There is no documented backup procedure for the PostgreSQL database. A `docker-compose down -v` or a failed migration would destroy the entire catalog — artist library, download history, user accounts, all job history.

**Fix:** Add a nightly `pg_dump` as a Celery Beat task or a separate `cron` container:
```yaml
# docker-compose.yml
studio54-backup:
  image: postgres:16
  volumes:
    - ./backups:/backups
    - /var/run/docker.sock:/var/run/docker.sock
  entrypoint: >
    sh -c "pg_dump $$DATABASE_URL | gzip > /backups/studio54-$$(date +%Y%m%d).sql.gz"
```
Retain 7 daily + 4 weekly backups. Test restore quarterly.

---

### 7.3 No Alembic Migration Safety Net — **P2**

**File:** `studio54-service/alembic/env.py`

Alembic migrations are applied by... nothing documented. There is no pre-flight migration check at startup, and no check that `alembic current` matches `alembic head` before the API starts accepting traffic. A failed migration leaves the schema in a partially upgraded state with no automatic rollback.

**Fix:** Add a startup migration check:
```python
# In lifespan startup
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

def assert_migrations_current():
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current = ctx.get_current_revision()
        scripts = ScriptDirectory.from_config(alembic_cfg)
        head = scripts.get_current_head()
        if current != head:
            raise RuntimeError(f"DB schema out of date: {current} != {head}. Run alembic upgrade head.")
```

---

### 7.4 Docker Compose Has No Resource Limits — **P2**

**File:** `docker-compose.yml`

No CPU or memory limits are set on any service. A runaway Celery task (e.g., recursive filesystem walk on a 1TB library) can consume all available memory, triggering the OOM killer and taking down unrelated containers (including PostgreSQL).

**Fix:**
```yaml
services:
  studio54-worker:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          memory: 512M
  studio54-service:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
```

---

## 8. Testing

### 8.1 No End-to-End Tests — **P1**

The test suite (`studio54-service/tests/`) contains unit and integration tests for individual services and models, but no end-to-end tests covering the full request-to-response lifecycle. Critical flows — add artist → sync → search → download → import — have no automated coverage.

**Fix:** Add E2E tests using `pytest` + `httpx` `TestClient` against a real test database:
```python
# tests/e2e/test_acquisition_flow.py
def test_artist_add_triggers_sync(client, db, mock_musicbrainz):
    resp = client.post("/api/v1/artists", json={"musicbrainz_id": "..."})
    assert resp.status_code == 201
    # Assert sync task was dispatched
    # Assert albums were created
```

---

### 8.2 External API Clients Have No Contract Tests — **P2**

**Files:** `app/services/musicbrainz_client.py`, `app/services/sabnzbd_client.py`, `app/services/newznab_client.py`

These clients talk to third-party APIs whose response schemas can change without notice. There are no recorded response fixtures or contract tests — a MusicBrainz API change would only be discovered when sync tasks start failing in production.

**Fix:** Record canonical API responses as JSON fixtures and add tests that assert the client correctly parses them:
```python
# tests/unit/test_musicbrainz_client.py
def test_parse_release_group(mb_client, fixture_release_group_response):
    result = mb_client._parse_release_group(fixture_release_group_response)
    assert result.title == "Abbey Road"
    assert result.release_date == date(1969, 9, 26)
```

---

## 9. Priority Summary

| # | Issue | Priority | Effort | Impact |
|---|---|---|---|---|
| 1.1 | JWT secret reused as Fernet key | **P0** | Low | Critical |
| 1.2 | JWT stored in localStorage | **P0** | Medium | Critical |
| 1.3 | 7-day non-refreshable JWTs | **P1** | Medium | High |
| 1.4 | Rate limiting not distributed | **P1** | Low | High |
| 1.5 | Admin user seeded at startup | **P2** | Low | Medium |
| 1.6 | `next(get_db())` in startup | **P1** | Low | Medium |
| 2.1 | Celery Beat SPOF | **P1** | Medium | High |
| 2.2 | No circuit breaker on external APIs | **P1** | Medium | High |
| 2.3 | MusicBrainz rate limit per-process | **P1** | Medium | Medium |
| 2.4 | Stalled jobs not auto-retried | **P2** | Low | Medium |
| 2.5 | Denormalized counts can drift | **P2** | Medium | Low |
| 2.6 | Series cascade blocks request thread | **P2** | Low | Low |
| 3.1 | Synchronous SQLAlchemy in async app | **P1** | High | High |
| 3.2 | No PgBouncer connection pooler | **P1** | Low | High |
| 3.3 | Cover art proxy runs client-side | **P2** | Low | Medium |
| 3.4 | Sound Booth polling (vs SSE) | **P2** | Medium | Low |
| 3.5 | TanStack Query staleTime not set | **P2** | Low | Low |
| 4.1 | Startup exceptions silently swallowed | **P1** | Low | High |
| 4.2 | No dead letter queue | **P1** | Medium | Medium |
| 4.3 | Alternate NZB retry is non-atomic | **P2** | Medium | Medium |
| 4.4 | Release matching is substring only | **P2** | Low | Medium |
| 5.1 | Deprecated `@app.on_event` | **P1** | Low | Low |
| 5.2 | `library_type` gating scattered | **P2** | Medium | Low |
| 5.3 | Config URLs not validated | **P2** | Low | Low |
| 6.1 | `window.open` — Capacitor blocker | **P1** | Medium | High |
| 6.2 | No React Error Boundaries | **P2** | Low | High |
| 6.3 | No Web Audio API integration | **P2** | High | Low |
| 6.4 | `VITE_API_URL` baked at build time | **P2** | Low | Medium |
| 7.1 | Redis no separation of concerns | **P2** | Low | Medium |
| 7.2 | No database backup strategy | **P1** | Low | Critical |
| 7.3 | No Alembic migration safety net | **P2** | Low | Medium |
| 7.4 | No Docker resource limits | **P2** | Low | Medium |
| 8.1 | No end-to-end tests | **P1** | High | High |
| 8.2 | No contract tests for API clients | **P2** | Medium | Medium |

### Recommended Execution Order

**Week 1 — Immediate security hardening:**
- 1.1 Split JWT secret from Fernet key (30 min)
- 1.6 Fix `next(get_db())` anti-pattern (30 min)
- 4.1 Migrate to `lifespan` + proper fatal vs. non-fatal startup (2h)
- 5.1 Deprecated `@app.on_event` (covered by 4.1)
- 7.2 Database backup strategy (2h)

**Week 2 — Stability:**
- 2.1 Celery Beat SPOF — add `restart: always` + `celery-redbeat` (4h)
- 2.2 Circuit breakers on external APIs (4h)
- 1.4 Redis-backed rate limiting (2h)
- 4.2 Dead letter queue (3h)

**Week 3 — Performance:**
- 3.2 PgBouncer deployment (2h)
- 3.3 Server-side cover art URL rewriting (1h)
- 3.5 TanStack Query staleTime defaults (30 min)
- 4.4 Fuzzy release matching (2h)

**Month 2 — Architecture:**
- 1.2 + 1.3 JWT → httpOnly cookies + refresh tokens (1 week)
- 6.1 Capacitor platform abstraction layer (3 days)
- 3.1 SQLAlchemy async migration (2 weeks — do incrementally)
- 8.1 E2E test suite foundation (1 week)

---

*Next documents: `Backend_API.md`, `Frontend.md`, `ExternalIntegrations.md`*
