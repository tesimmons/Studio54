# Studio54 — Admin & Operations Guide

> **Audience:** DevOps / SysAdmin team  
> **Last updated:** 2026-05-14  
> **Version:** 1.0.0

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Prerequisites](#2-prerequisites)
3. [First-Run Setup](#3-first-run-setup)
4. [Environment Variables Reference](#4-environment-variables-reference)
5. [Service Architecture](#5-service-architecture)
6. [Port Reference](#6-port-reference)
7. [Data Directory Layout](#7-data-directory-layout)
8. [Management CLI (`./studio54`)](#8-management-cli-studio54)
9. [Deployment & Updates](#9-deployment--updates)
10. [Database Migrations (Alembic)](#10-database-migrations-alembic)
11. [Celery Worker Management](#11-celery-worker-management)
12. [Backup & Restore](#12-backup--restore)
13. [MusicBrainz Local Mirror](#13-musicbrainz-local-mirror)
14. [MasterControl Integration](#14-mastercontrol-integration)
15. [Auto-Updates (Watchtower)](#15-auto-updates-watchtower)
16. [Monitoring & Logs](#16-monitoring--logs)
17. [Healthchecks](#17-healthchecks)
18. [Security Notes](#18-security-notes)
19. [Troubleshooting](#19-troubleshooting)

---

## 1. System Overview

Studio54 is a self-hosted music and audiobook acquisition and library management system — conceptually similar to Lidarr but extended with audiobooks, AI-assisted metadata, and a full-featured React frontend.

The system runs as a **Docker Compose stack** containing 6 core services plus optional profiles (log viewer, auto-updater) and an optional full MusicBrainz local mirror (7 additional containers).

```mermaid
graph TD
    Browser -->|:8009| nginx[studio54-web\nNginx + React SPA]
    nginx -->|/api/ proxy| api[studio54-service\nFastAPI :8010]
    api --> db[(studio54-db\nPostgreSQL :5434)]
    api --> redis[(studio54-redis\nRedis :6381)]
    api -->|enqueue tasks| worker[studio54-worker\nCelery]
    beat[studio54-beat\nCelery Beat] -->|scheduled tasks| redis
    worker --> db
    worker --> redis
    worker -->|metadata| mbdb[(musicbrainz-db)]
    worker -->|downloads| sabnzbd[SABnzbd\nexternal]
    worker -->|AI| ollama[Ollama\nexternal]
```

---

## 2. Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| Docker Engine | 24.x | Must support Compose v2 (`docker compose`) |
| Docker Compose | v2.20+ | Bundled with Docker Desktop; standalone via `docker-compose-plugin` |
| Disk space (core) | 20 GB | Postgres + Redis data + cover art |
| Disk space (MusicBrainz) | +70 GB | Only needed for local MB mirror |
| RAM (core stack) | 4 GB | 8 GB recommended with Celery autoscale at max |
| RAM (with MusicBrainz) | +4 GB | Solr heap = 2 GB, Postgres shared_buffers = 2 GB |
| CPU | 2 cores | 4+ cores recommended for Celery autoscale |
| Python 3.11 | Setup only | Only needed to generate the Fernet encryption key during setup |

**Verify prerequisites before first run:**
```bash
./studio54 check
```

---

## 3. First-Run Setup

### Step 1 — Clone and enter the repo
```bash
git clone <repo-url> /opt/studio54
cd /opt/studio54
chmod +x ./studio54
```

### Step 2 — Run interactive setup
```bash
./studio54 setup
```

This command:
- Copies `.env.example` → `.env`
- Generates a random `STUDIO54_DB_PASSWORD` via `openssl rand -hex 32`
- Generates a random `STUDIO54_ENCRYPTION_KEY` via Python Fernet
- Creates the data directories under `STUDIO54_DATA_DIR` (default `/docker/studio54`)

> **Warning:** The generated `STUDIO54_ENCRYPTION_KEY` is used to encrypt all stored credentials (indexer API keys, download client API keys, webhook URLs). **Back this key up immediately** — losing it means all stored credentials must be re-entered.

### Step 3 — Edit `.env`

At minimum, configure:
- `MUSIC_LIBRARY_PATH` — absolute host path to your music library (must be readable/writable)
- `AUDIOBOOKS_PATH` — absolute host path to your audiobook library
- `SABNZBD_HOST`, `SABNZBD_PORT`, `SABNZBD_API_KEY`, `SABNZBD_DOWNLOAD_DIR` — if using SABnzbd
- `LASTFM_API_KEY`, `FANART_API_KEY`, `ACOUSTID_API_KEY` — optional external API keys

### Step 4 — Start
```bash
./studio54 start
```

Services start in dependency order (DB → Redis → Service → Worker → Beat → Web).  
The API container has a 90-second `start_period` for Alembic migrations to complete before the healthcheck fires.

### Step 5 — Verify
```bash
./studio54 status
# Open: http://<host>:8009
# Default admin credentials are created on first startup (see startup logs)
```

---

## 4. Environment Variables Reference

All variables are read from `.env` in the project root. Required variables have no defaults and will cause startup failure if absent.

### Core (Required)

| Variable | Default | Description |
|---|---|---|
| `STUDIO54_DB_PASSWORD` | *(none)* | PostgreSQL password for the `studio54` user |
| `STUDIO54_ENCRYPTION_KEY` | *(none)* | Fernet key — encrypts all stored API credentials. **Never rotate without re-encrypting stored data.** |

### Database

| Variable | Default | Description |
|---|---|---|
| `STUDIO54_DB_NAME` | `studio54_db` | PostgreSQL database name |
| `STUDIO54_DB_USER` | `studio54` | PostgreSQL username |
| `STUDIO54_DATA_DIR` | `/docker/studio54` | Host base path for all persistent volumes |

> The service container builds its `DATABASE_URL` internally:  
> `postgresql://<USER>:<PASS>@studio54-db:5432/<DB_NAME>`

### Ports

| Variable | Default | Description |
|---|---|---|
| `STUDIO54_WEB_PORT` | `8009` | Host port for the Nginx web UI |
| `STUDIO54_SERVICE_PORT` | `8010` | Host port for the FastAPI service |
| `STUDIO54_DB_PORT` | `5434` | Host port for PostgreSQL (external access) |
| `STUDIO54_REDIS_PORT` | `6381` | Host port for Redis (external access) |
| `STUDIO54_DOZZLE_PORT` | `9998` | Host port for Dozzle log viewer |

### Library Paths

| Variable | Default | Description |
|---|---|---|
| `MUSIC_LIBRARY_PATH` | `/music` | Host path to music library root — mounted `rw` at `/music` inside containers |
| `AUDIOBOOKS_PATH` | `/audiobooks` | Host path to audiobook library root — mounted `rw` at `/audio_books` inside containers |
| `SABNZBD_DOWNLOAD_DIR` | `/downloads/music` | Host path where SABnzbd drops completed downloads — mounted `rw` at the same path inside containers |

### SABnzbd Integration

| Variable | Default | Description |
|---|---|---|
| `SABNZBD_HOST` | *(empty)* | Hostname or IP of SABnzbd |
| `SABNZBD_PORT` | `8080` | SABnzbd port |
| `SABNZBD_API_KEY` | *(empty)* | SABnzbd API key (stored in DB encrypted; this env var seeds the default on first startup) |

### AI / Ollama

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Model used for semantic search embeddings |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model used for smart metadata matching |

### External API Keys (all optional)

| Variable | Description |
|---|---|
| `FANART_API_KEY` | Fanart.tv — high-quality artist/album artwork |
| `LASTFM_API_KEY` | Last.fm — additional metadata, scrobbling support |
| `ACOUSTID_API_KEY` | AcoustID — audio fingerprinting for track identification |
| `AUDD_API_TOKEN` | AudD — music recognition via audio sample |

### MusicBrainz

| Variable | Default | Description |
|---|---|---|
| `MUSICBRAINZ_LOCAL_DB_ENABLED` | `false` | Enable the local MusicBrainz mirror instead of the remote API |
| `MUSICBRAINZ_LOCAL_DB_URL` | *(empty)* | Set automatically by `./studio54 musicbrainzdb setup` |
| `MUSICBRAINZ_RATE_LIMIT` | `1.0` | Requests/sec to the **remote** MusicBrainz API. Do not exceed 1.0 per MusicBrainz ToS. |

### MUSE

| Variable | Default | Description |
|---|---|---|
| `MUSE_SERVICE_URL` | `http://muse-service:8007` | URL of the MUSE duplicate-detection sidecar. Leave empty to disable. |

### Celery Workers

| Variable | Default | Description |
|---|---|---|
| `CELERY_AUTOSCALE_MAX` | `8` | Maximum concurrent Celery worker processes |
| `CELERY_AUTOSCALE_MIN` | `2` | Minimum concurrent Celery worker processes |
| `CELERY_LOG_LEVEL` | `info` | Celery log verbosity (`debug`, `info`, `warning`, `error`) |

### Deployment Mode

| Variable | Default | Description |
|---|---|---|
| `STUDIO54_MANAGED_BY` | *(empty)* | Set to `mastercontrol` when running inside a MasterControl stack. Suppresses Dozzle/Watchtower. |
| `COMPOSE_PROFILES` | `dozzle` | Active Docker Compose profiles. See [Profiles](#profiles). |

### Watchtower (auto-updates)

| Variable | Default | Description |
|---|---|---|
| `WATCHTOWER_INTERVAL` | `86400` | Seconds between Watchtower update checks (86400 = daily) |
| `WATCHTOWER_STUDIO54_DB` | `false` | Auto-update the PostgreSQL container |
| `WATCHTOWER_STUDIO54_REDIS` | `true` | Auto-update the Redis container |
| `WATCHTOWER_STUDIO54_SERVICE` | `true` | Auto-update the API service container |
| `WATCHTOWER_STUDIO54_WORKER` | `true` | Auto-update the Celery worker container |
| `WATCHTOWER_STUDIO54_BEAT` | `true` | Auto-update the Celery Beat container |
| `WATCHTOWER_STUDIO54_WEB` | `true` | Auto-update the Nginx web container |
| `WATCHTOWER_DOZZLE` | `true` | Auto-update the Dozzle log viewer |

### Frontend Build Variable

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `/api/v1` | API base URL baked into the React build at compile time. The default `/api/v1` is correct for Docker deployments where Nginx proxies `/api/` to the backend. Change only for non-standard deployments or development. |

> **Note:** `VITE_API_URL` lives in `studio54-web/.env` (not the root `.env`) and is consumed at `npm run build` time, not at runtime.

---

## 5. Service Architecture

```mermaid
graph LR
    subgraph Core Stack
        web[studio54-web\nNginx 1.27\nPort 8009]
        svc[studio54-service\nFastAPI + Uvicorn\n2 workers, Port 8010]
        worker[studio54-worker\nCelery autoscale 2–8]
        beat[studio54-beat\nCelery Beat scheduler]
        db[(studio54-db\nPostgreSQL 15)]
        redis[(studio54-redis\nRedis 7 AOF)]
    end

    subgraph Optional Profiles
        dozzle[studio54-dozzle\nLog viewer\nPort 9998]
        watchtower[studio54-watchtower\nAuto-updater]
    end

    subgraph MusicBrainz Mirror
        mbdb[(musicbrainz-db\nPostgreSQL 16)]
        mbserver[musicbrainz-server\nPort 5000]
        mbsearch[musicbrainz-search\nSolr]
        mbmq[musicbrainz-mq\nRabbitMQ]
        mbredis[musicbrainz-redis]
        mbindexer[musicbrainz-indexer]
    end

    web --> svc
    svc --> db
    svc --> redis
    svc --> worker
    beat --> redis
    worker --> db
    worker --> redis
    worker --> mbdb
```

### Startup Dependency Order

```
studio54-db (healthy) ──┐
                         ├──> studio54-service (healthy) ──┬──> studio54-worker (healthy)
studio54-redis (healthy)─┘                                  ├──> studio54-beat
                                                            └──> studio54-web
```

### Container Images

| Container | Image | Built From |
|---|---|---|
| `studio54-service` | `studio54/service:latest` | `studio54-service/Dockerfile` (Python 3.11-slim) |
| `studio54-worker` | `studio54/service:latest` | Same image as service, different `CMD` |
| `studio54-beat` | `studio54/service:latest` | Same image as service, different `CMD` |
| `studio54-web` | `studio54/web:latest` | `studio54-web/Dockerfile` (Node 20 builder → Nginx 1.27 Alpine) |
| `studio54-db` | `postgres:15-alpine` | Official image |
| `studio54-redis` | `redis:7-alpine` | Official image |
| `musicbrainz-db` | `studio54/musicbrainz-db:<POSTGRES_VERSION>` | Custom build in `musicbrainz-docker/` |

### Profiles

| Profile | Enables | When to use |
|---|---|---|
| *(none)* | Core 6 services only | Managed mode (MasterControl) |
| `dozzle` | + Dozzle log viewer on port 9998 | **Default standalone** — set `COMPOSE_PROFILES=dozzle` |
| `watchtower` | + Watchtower auto-updater | Standalone with automatic updates — set `COMPOSE_PROFILES=dozzle,watchtower` |

---

## 6. Port Reference

| Port | Service | Protocol | Notes |
|---|---|---|---|
| **8009** | `studio54-web` | HTTP | Web UI (React SPA + API proxy) |
| **8010** | `studio54-service` | HTTP | FastAPI REST API + Swagger docs at `/docs` |
| **5434** | `studio54-db` | TCP | PostgreSQL — external access for psql/pgAdmin |
| **6381** | `studio54-redis` | TCP | Redis — external access for redis-cli |
| **9998** | `studio54-dozzle` | HTTP | Container log viewer (optional profile) |
| **5000** | `musicbrainz-server` | HTTP | MusicBrainz web UI (optional mirror) |

All inter-container communication happens over `studio54_network` using Docker service names as hostnames. Host port bindings above are for external access only. To restrict PostgreSQL and Redis from external access, remove their `ports:` entries from `docker-compose.yml` or bind to `127.0.0.1`.

---

## 7. Data Directory Layout

```
STUDIO54_DATA_DIR/          (default: /docker/studio54)
├── postgres/               # PostgreSQL data files
├── redis/                  # Redis AOF persistence
└── cover-art/              # Downloaded artist/album artwork

/docker/musicbrainz/        # MusicBrainz mirror (separate)
├── pgdata/                 # MusicBrainz PostgreSQL data (~65 GB)
└── dbdump/                 # MusicBrainz dump files

MUSIC_LIBRARY_PATH/         # Your music files (host path, mounted rw at /music)
AUDIOBOOKS_PATH/            # Your audiobook files (mounted rw at /audio_books)
SABNZBD_DOWNLOAD_DIR/       # SABnzbd completed downloads (mounted rw at same path)

studio54-job-logs           # Docker named volume — Celery job log files
```

> All bind-mount paths must exist on the host before `./studio54 start`. The `./studio54 setup` command creates `STUDIO54_DATA_DIR` subdirectories automatically but **does not** create `MUSIC_LIBRARY_PATH`, `AUDIOBOOKS_PATH`, or `SABNZBD_DOWNLOAD_DIR` — create these manually and verify correct ownership before starting.

---

## 8. Management CLI (`./studio54`)

The `./studio54` script is the primary management interface. All commands must be run from the project root.

```bash
./studio54 <command> [options]
```

### Setup Commands

```bash
./studio54 check           # Prerequisite check — Docker, ports, disk space, .env validation
./studio54 setup           # Interactive first-run: creates .env, generates secrets, creates directories
```

### Service Control

```bash
./studio54 start                    # Start all services
./studio54 start studio54-worker    # Start a specific service
./studio54 stop                     # Stop all services
./studio54 stop studio54-beat       # Stop a specific service
./studio54 restart                  # Restart all services
./studio54 restart studio54-service # Restart a specific service
./studio54 status                   # Show container status, access URLs, and host resource usage
```

### Logs

```bash
./studio54 logs                     # Follow all service logs (tail 200)
./studio54 logs studio54-service    # Follow logs for a specific service
./studio54 logs studio54-worker     # Follow Celery worker logs
```

Alternatively, use Dozzle at `http://<host>:9998` for a browser-based log UI.

### Deployment

```bash
./studio54 deploy studio54-service  # Rebuild (no-cache) and redeploy a specific service
./studio54 update                   # Pull latest images and restart all services
./studio54 update studio54-web      # Pull and redeploy a specific service
```

### Backup & Restore

```bash
./studio54 backup all               # Backup PostgreSQL data, Redis data, and cover art
./studio54 backup db                # Backup PostgreSQL only
./studio54 restore ./data/backups/studio54-db_20260514_020000.tar.gz
```

Backups are saved to `./data/backups/` as timestamped `.tar.gz` archives.

### Watchtower

```bash
./studio54 watchtower enable        # Start Watchtower auto-update container
./studio54 watchtower disable       # Stop and remove Watchtower container
./studio54 watchtower status        # Show Watchtower status and per-service update flags
```

### MusicBrainz Mirror

```bash
./studio54 musicbrainzdb setup <token>  # Configure local MusicBrainz mirror
./studio54 musicbrainzdb status         # Show mirror enable state and DB URL
./studio54 musicbrainzdb logs [lines]   # Tail MusicBrainz DB container logs
```

---

## 9. Deployment & Updates

### Rebuilding Application Images

Application images (`studio54/service:latest`, `studio54/web:latest`) are **built locally** — they are not pulled from a registry. Rebuild after a code change:

```bash
# Rebuild and redeploy the API/worker image
./studio54 deploy studio54-service
# Worker and Beat share the same image — redeploy them too:
./studio54 restart studio54-worker
./studio54 restart studio54-beat

# Rebuild and redeploy the web UI
./studio54 deploy studio54-web
```

The `deploy` command runs `docker compose build --no-cache` then `docker compose up -d`, ensuring a clean rebuild without layer cache artifacts.

### Rolling Update (Zero-Downtime)

Because the worker and beat containers share the service image, a full update order is:

```bash
./studio54 deploy studio54-service   # 1. Rebuild image (also used by worker/beat)
./studio54 restart studio54-worker   # 2. Restart worker (picks up new image)
./studio54 restart studio54-beat     # 3. Restart beat
./studio54 deploy studio54-web       # 4. Rebuild and redeploy frontend
```

The API service has a 90-second `start_period` — dependent services (web) won't receive traffic until the healthcheck passes.

### Database Migrations on Deploy

Alembic migrations run **automatically at service startup** via the startup event in `app/main.py`. No manual migration step is required during normal deploys. To verify the migration state:

```bash
docker exec studio54-service alembic current
```

---

## 10. Database Migrations (Alembic)

Migration files live in `studio54-service/alembic/versions/`. There are currently **62 migrations**.

### Common Commands

All Alembic commands must run inside the `studio54-service` container (which has the correct `DATABASE_URL`):

```bash
# Show current migration head
docker exec studio54-service alembic current

# Show migration history
docker exec studio54-service alembic history --verbose

# Upgrade to latest (runs automatically on startup, but can be run manually)
docker exec studio54-service alembic upgrade head

# Downgrade one step (use with caution — may be irreversible)
docker exec studio54-service alembic downgrade -1

# Generate a new migration from model changes (run from the service directory)
docker exec studio54-service alembic revision --autogenerate -m "add_my_new_table"
```

### Migration File Naming

Files follow the format: `YYYYmmdd_HHMM_<revisionid>_<slug>.py`

Example: `20260112_1430_a1b2c3d4_add_book_progress_table.py`

### Before Running Migrations on Production

1. **Back up the database first:** `./studio54 backup db`
2. Review the generated SQL: `docker exec studio54-service alembic upgrade head --sql`
3. Check for destructive operations (DROP COLUMN, DROP TABLE, NOT NULL constraints on large tables)

---

## 11. Celery Worker Management

### Queues

The worker container subscribes to all 12 queues simultaneously:

| Queue | Purpose | Beat Schedule |
|---|---|---|
| `monitoring` | Download status polling | Every 30 seconds |
| `monitoring` | Stalled job detection | Every 2 minutes |
| `search` | Wanted album searches | Every 15 minutes |
| `sync` | MusicBrainz artist sync | Every 6 hours |
| `library` | Library cleanup | Every 24 hours |
| `downloads` | NZB submission to SABnzbd | On demand |
| `organization` | File organization after import | On demand |
| `scan` | V2 library scanner coordinator | On demand |
| `ingest_fast` | File ingestion (first pass) | On demand |
| `index_metadata` | Audio metadata extraction | On demand |
| `fetch_images` | Cover art download | On demand |
| `calculate_hashes` | AcoustID fingerprinting | On demand |

### Inspecting the Queue

```bash
# Ping workers
docker exec studio54-worker celery -A app.tasks.celery_app inspect ping

# List active tasks
docker exec studio54-worker celery -A app.tasks.celery_app inspect active

# List scheduled tasks
docker exec studio54-worker celery -A app.tasks.celery_app inspect scheduled

# Queue lengths via redis-cli
docker exec studio54-redis redis-cli llen monitoring
docker exec studio54-redis redis-cli llen downloads
```

### Scaling Workers

Change autoscale bounds in `.env` and restart the worker:

```bash
# .env
CELERY_AUTOSCALE_MAX=12
CELERY_AUTOSCALE_MIN=4

./studio54 restart studio54-worker
```

The worker configuration uses:
- `worker_prefetch_multiplier = 1` — prevents a single worker from hoarding tasks
- `worker_max_tasks_per_child = 50` — worker processes recycle after 50 tasks to prevent memory leaks

### Revoking a Task

```bash
docker exec studio54-worker celery -A app.tasks.celery_app control revoke <task-id> --terminate
```

Find task IDs in the Celery worker logs or via the Studio54 Jobs UI.

### Beat Scheduler

The Beat container is a single-process scheduler (SPOF). If Beat crashes, periodic tasks stop firing. Monitor with:

```bash
./studio54 logs studio54-beat
```

Beat has `restart: unless-stopped` — Docker will restart it automatically after a crash.

---

## 12. Backup & Restore

### Automated Backup

```bash
./studio54 backup all
# Creates:
#   ./data/backups/studio54-db_<timestamp>.tar.gz     (PostgreSQL data directory)
#   ./data/backups/studio54-redis_<timestamp>.tar.gz  (Redis AOF data)
#   ./data/backups/studio54-cover-art_<timestamp>.tar.gz
```

### PostgreSQL-Native Backup (Recommended for Production)

For reliable cross-version restores, use `pg_dump` instead of a file-level backup:

```bash
# Dump
docker exec studio54-db pg_dump \
  -U studio54 -d studio54_db -Fc \
  > /backup/studio54_$(date +%Y%m%d_%H%M%S).dump

# Restore
docker exec -i studio54-db pg_restore \
  -U studio54 -d studio54_db --clean \
  < /backup/studio54_20260514_020000.dump
```

### Redis Backup

Redis is configured with `--appendonly yes` (AOF persistence). The AOF file is in `STUDIO54_DATA_DIR/redis/`. A Redis BGSAVE snapshot can be triggered:

```bash
docker exec studio54-redis redis-cli BGSAVE
docker exec studio54-redis redis-cli LASTSAVE  # timestamp of last save
```

### Restore from CLI Backup

```bash
./studio54 restore ./data/backups/studio54-db_20260514_020000.tar.gz
```

The restore command stops the API, worker, and beat services before extracting, then restarts all services.

### Critical: Back Up the Encryption Key

The `STUDIO54_ENCRYPTION_KEY` in `.env` encrypts all stored credentials in the database. If this key is lost, all indexer API keys, download client API keys, and webhook URLs must be re-entered manually. Store this key in a secrets manager or password vault separately from the database backup.

---

## 13. MusicBrainz Local Mirror

The local MusicBrainz mirror eliminates remote API rate limiting (1 req/sec) for metadata lookups. It requires approximately **70 GB of disk space** and **4+ GB of RAM** (Solr + PostgreSQL combined).

### Initial Setup

1. Obtain a MetaBrainz replication token at `https://metabrainz.org/supporters/account-type`

2. Store your token:
   ```bash
   mkdir -p ./musicbrainz-docker/local/secrets
   echo -n "your-token-here" > ./musicbrainz-docker/local/secrets/metabrainz_access_token
   ```

3. Start the MusicBrainz containers:
   ```bash
   docker compose up -d musicbrainz-db musicbrainz-mq musicbrainz-search musicbrainz-redis musicbrainz-server musicbrainz-indexer
   ```

4. Wait for the initial data import (1–3 hours on first run):
   ```bash
   docker logs -f musicbrainz-server
   # Look for: "Setup complete" or Plack server startup messages
   ```

5. Enable in Studio54:
   ```bash
   # .env
   MUSICBRAINZ_LOCAL_DB_ENABLED=true
   MUSICBRAINZ_LOCAL_DB_URL=postgresql://musicbrainz:musicbrainz@musicbrainz-db:5432/musicbrainz_db
   ```

6. Restart the service and worker:
   ```bash
   ./studio54 restart studio54-service
   ./studio54 restart studio54-worker
   ```

### Replication / Keeping Data Current

MusicBrainz publishes daily replication packets. The `musicbrainz-server` container runs a replication cron configured via:

```bash
# Default cron config
./musicbrainz-docker/default/replication.cron

# Override with custom schedule:
MUSICBRAINZ_REPLICATION_CRON=./musicbrainz-docker/local/replication.cron
```

Check replication status:
```bash
./studio54 musicbrainzdb status
./studio54 musicbrainzdb logs 50
```

### MusicBrainz Disk Usage

| Component | Approximate Size |
|---|---|
| PostgreSQL data (`musicbrainz-pgdata`) | ~60 GB |
| Dump files (`musicbrainz-dbdump`) | ~8 GB |
| Solr index (`musicbrainz-solrdata`) | ~2 GB |

These volumes are bind-mounted to `/docker/musicbrainz/` on the host (not inside `STUDIO54_DATA_DIR`).

---

## 14. MasterControl Integration

When Studio54 runs as a sub-stack under MasterControl, apply the override file:

```bash
# Start with MasterControl override
docker compose \
  -f docker-compose.yml \
  -f docker-compose.mastercontrol.yml \
  up -d
```

Or set `COMPOSE_FILE` in the environment:
```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.mastercontrol.yml
```

The override:
- Joins `studio54-service`, `studio54-worker`, and `musicbrainz-db` to the external `ai_network`
- Enables cross-project service discovery (other MasterControl services can reach Studio54's API by hostname)
- Does **not** start Dozzle or Watchtower (MasterControl provides its own instances)

When `STUDIO54_MANAGED_BY=mastercontrol` is set in `.env`, the `./studio54 start` command automatically suppresses all profiles (no Dozzle/Watchtower).

---

## 15. Auto-Updates (Watchtower)

Watchtower watches for new image versions of labelled containers and restarts them automatically.

### Enable / Disable

```bash
./studio54 watchtower enable    # Starts studio54-watchtower container
./studio54 watchtower disable   # Stops and removes it
```

### Per-Service Control

Each service has a `com.centurylinklabs.watchtower.enable` Docker label. The label values are controlled by `WATCHTOWER_STUDIO54_*` variables in `.env`:

| Service | Default | Rationale |
|---|---|---|
| `studio54-db` | `false` | Major PostgreSQL version upgrades require manual data migration |
| `studio54-redis` | `true` | Redis patch updates are safe |
| `studio54-service` | `true` | Application updates |
| `studio54-worker` | `true` | Application updates (same image as service) |
| `studio54-beat` | `true` | Application updates (same image as service) |
| `studio54-web` | `true` | Frontend updates |

> **Note:** Since `studio54-service`, `studio54-worker`, and `studio54-beat` all use the same `studio54/service:latest` image built locally, Watchtower will only auto-update them if you push the image to a registry. For local builds, use `./studio54 deploy` instead.

### Update Interval

```bash
# .env — check for updates every 6 hours (21600 seconds)
WATCHTOWER_INTERVAL=21600
```

---

## 16. Monitoring & Logs

### Dozzle (Browser Log Viewer)

Available at `http://<host>:9998` when the `dozzle` profile is active. Filtered to show only `studio54` containers via `DOZZLE_FILTER=name=studio54`.

### CLI Log Access

```bash
./studio54 logs                       # All services
./studio54 logs studio54-service      # API logs
./studio54 logs studio54-worker       # Celery task logs
./studio54 logs studio54-beat         # Scheduled task dispatch logs
./studio54 logs studio54-db           # PostgreSQL logs
```

Docker log drivers use `json-file` with rotation configured on MusicBrainz containers (10 MB max, 10 files). The core Studio54 containers use Docker's default log driver — configure rotation in `/etc/docker/daemon.json` if needed:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
```

### Redis Monitoring

```bash
# Real-time Redis stats
docker exec studio54-redis redis-cli monitor

# Info summary
docker exec studio54-redis redis-cli info

# Now Playing keys (60s TTL, set by heartbeat)
docker exec studio54-redis redis-cli keys "studio54:now_playing:*"

# Celery queue depths
for q in monitoring downloads search sync organization library scan ingest_fast index_metadata fetch_images calculate_hashes; do
  echo "$q: $(docker exec studio54-redis redis-cli llen $q)"
done
```

### API Health Check

```bash
curl http://localhost:8010/health
# Returns: {"status": "healthy", ...}
```

### Resource Usage

```bash
./studio54 status
# Includes: per-container CPU/MEM, host CPU/MEM/DISK
```

---

## 17. Healthchecks

All core services define Docker healthchecks. A service is only considered `healthy` when its check passes, which controls startup ordering.

| Service | Check | Interval | Start Period | Retries |
|---|---|---|---|---|
| `studio54-db` | `pg_isready` | 10s | 10s | 5 |
| `studio54-redis` | `redis-cli ping` | 10s | 5s | 3 |
| `studio54-service` | HTTP GET `/health` | 30s | **90s** | 3 |
| `studio54-worker` | `celery inspect ping` | 30s | 40s | 3 |
| `studio54-web` | HTTP GET `/health` | 30s | 10s | 3 |
| `musicbrainz-db` | `pg_isready` | 30s | 60s | 5 |

The 90-second `start_period` on `studio54-service` is intentional — Alembic migrations run at startup and may take 10–30 seconds on a freshly initialized database.

**Check status manually:**
```bash
docker inspect --format='{{.State.Health.Status}}' studio54-service
# healthy | starting | unhealthy
```

---

## 18. Security Notes

The following are known issues documented for operational awareness. See `Architecture/Enhancements.md` for full remediation details.

| Severity | Issue | Location | Impact |
|---|---|---|---|
| **P0** | `JWT_SECRET` is the same value as `STUDIO54_ENCRYPTION_KEY` | `app/auth.py:10` | Compromising either secret compromises both authentication tokens and stored credentials |
| **P0** | JWT stored in `localStorage` | `studio54-web/src/api/client.ts:47` | XSS attacks can steal session tokens |
| **P1** | JWT expires after 7 days with no refresh mechanism | `app/auth.py:21` | Revoking a stolen token requires waiting 7 days or rotating the secret (logout all users) |
| **P1** | Rate limiting is per-process, not distributed | `app/main.py`, `app/security.py` | Rate limits are ineffective with the default 2 Uvicorn workers; bypassed entirely by direct API access |
| **P1** | No database backup strategy is automated | infrastructure | Data loss risk |

### Operational Mitigations (Until Code-Level Fixes Are Applied)

- **Enforce HTTPS** at the reverse proxy layer (nginx/Caddy/Traefik in front of port 8009). This is essential given localStorage JWT storage.
- **Rotate `STUDIO54_ENCRYPTION_KEY` carefully** — changing it invalidates all stored credentials. Coordinate with application admins before rotating.
- **Firewall ports 5434 (PostgreSQL) and 6381 (Redis)** — these should never be exposed to the internet. Bind to `127.0.0.1` in production.
- **Schedule daily `pg_dump` backups** via cron until automated backup is implemented.

---

## 19. Troubleshooting

### Service Won't Start

```bash
./studio54 logs studio54-service
# Look for: Alembic errors, connection refused (DB/Redis not ready), missing env vars
```

Verify all required env vars are set:
```bash
grep -E "^(STUDIO54_DB_PASSWORD|STUDIO54_ENCRYPTION_KEY)=" .env
# Both must have non-empty values
```

### Database Connection Refused

```bash
docker inspect studio54-db --format='{{.State.Health.Status}}'
# If "starting" — wait; start_period is 10s
# If "unhealthy" — check logs:
docker logs studio54-db --tail=50
```

### Celery Tasks Not Processing

```bash
# Verify worker is alive
docker exec studio54-worker celery -A app.tasks.celery_app inspect ping

# Check queue backlogs
docker exec studio54-redis redis-cli llen downloads

# Verify Redis connectivity from worker
docker exec studio54-worker redis-cli -u redis://studio54-redis:6379 ping
```

### Migrations Failed / Database Out of Sync

```bash
docker exec studio54-service alembic current
docker exec studio54-service alembic history | head -10

# If migration is partially applied:
./studio54 backup db     # Backup first!
docker exec studio54-service alembic upgrade head
```

### Cover Art Not Loading

Cover art is stored at `STUDIO54_DATA_DIR/cover-art/` on the host, mounted into the container at `/docker/studio54`. Verify the mount and permissions:

```bash
docker exec studio54-service ls /docker/studio54/
# Should show image directories

ls -la /docker/studio54/cover-art/
# Owner must be writable by the container process (UID 1000 or root depending on image)
```

### MusicBrainz Local DB Not Being Used

```bash
./studio54 musicbrainzdb status
# Verify: MUSICBRAINZ_LOCAL_DB_ENABLED=true and MUSICBRAINZ_LOCAL_DB_URL is set

docker inspect musicbrainz-db --format='{{.State.Health.Status}}'
# Must be "healthy" before the Studio54 service will connect to it
```

### Reset Admin Password

The admin user is seeded on first startup via the startup event in `app/main.py`. To reset:

```bash
# Connect to the database directly
docker exec -it studio54-db psql -U studio54 -d studio54_db

# Find the admin user
SELECT id, username, role FROM users WHERE role = 'director';

# Update the password (the hash must be generated by bcrypt — do not insert plain text)
# Use the API endpoint instead:
curl -X POST http://localhost:8010/api/v1/admin/reset-password \
  -H "Authorization: Bearer <valid-director-token>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<uuid>", "new_password": "newpass"}'
```

### High Memory Usage

Celery workers recycle after 50 tasks (`worker_max_tasks_per_child=50`) to prevent memory leaks. If memory is still climbing:

```bash
# Reduce max workers
# .env
CELERY_AUTOSCALE_MAX=4

./studio54 restart studio54-worker
```

If PostgreSQL is consuming excessive memory, consider adding a PgBouncer connection pooler (see `Architecture/Enhancements.md` §3.2).
