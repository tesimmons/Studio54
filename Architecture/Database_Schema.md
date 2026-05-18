# Studio54 — Database Schema

**Version:** 1.0  
**Date:** 2026-05-14  
**Database:** PostgreSQL  
**ORM:** SQLAlchemy 2.0 + Alembic (62 migrations, `001` → `062`)  

---

## 1. Overview

The Studio54 database is a single PostgreSQL schema with **35 tables** organized into six logical domains. All primary keys are `UUID v4`. All timestamps are `TIMESTAMPTZ` (UTC). Encrypted secrets (API keys, webhook URLs) are stored as `TEXT` columns containing Fernet-encrypted ciphertext — never plaintext.

| Domain | Tables |
|---|---|
| **Music Library** | `artists`, `albums`, `tracks`, `track_ratings` |
| **Audiobook Library** | `authors`, `series`, `books`, `chapters`, `book_progress`, `book_playlists`, `book_playlist_chapters`, `user_listening_sessions` |
| **Playlists** | `playlists`, `playlist_tracks`, `playlist_chapters` |
| **Acquisition** | `indexers`, `download_clients`, `download_queue`, `quality_profiles` |
| **Library Scanning & File Management** | `library_paths`, `library_files`, `scan_jobs`, `library_import_jobs`, `library_artist_matches`, `file_organization_jobs`, `unlinked_files`, `duplicate_recycle_bin` |
| **Users, Jobs & Config** | `users`, `dj_requests`, `job_states`, `scheduled_jobs`, `media_management_config`, `notification_profiles`, `storage_mounts` |

---

## 2. Entity-Relationship Diagram

```mermaid
erDiagram

    %% ── Music Library ──────────────────────────────────────────
    quality_profiles {
        uuid id PK
        string name
        bool is_default
        jsonb allowed_formats
        jsonb preferred_formats
        int min_bitrate
        int max_size_mb
        bool upgrade_enabled
        string upgrade_until_quality
    }

    artists {
        uuid id PK
        text name
        string musicbrainz_id UK
        bool is_monitored
        uuid quality_profile_id FK
        string monitor_type
        text root_folder_path
        text overview
        string genre
        string country
        text image_url
        string import_source
        uuid muse_library_id
        uuid studio54_library_path_id FK
        bool is_stub
        int rating_override
        int album_count
        int single_count
        int track_count
        timestamptz added_at
        timestamptz last_sync_at
        timestamptz updated_at
    }

    albums {
        uuid id PK
        uuid artist_id FK
        text title
        string musicbrainz_id UK
        string release_mbid
        string release_group_mbid
        date release_date
        string album_type
        text secondary_types
        int track_count
        enum status
        bool monitored
        text cover_art_url
        text custom_folder_path
        bool is_stub
        timestamptz last_search_time
        bool quality_meets_cutoff
        uuid muse_library_id
        bool muse_verified
        bool retry_enabled
        timestamptz next_retry_at
        int download_retry_count
        timestamptz added_at
        timestamptz searched_at
        timestamptz downloaded_at
        timestamptz updated_at
    }

    tracks {
        uuid id PK
        uuid album_id FK
        text title
        string musicbrainz_id
        int track_number
        int disc_number
        int duration_ms
        bool has_file
        text file_path
        uuid muse_file_id
        bool is_stub
        text synced_lyrics
        text plain_lyrics
        string lyrics_source
        int play_count
        timestamptz last_played_at
        int rating
        float average_rating
        timestamptz created_at
        timestamptz updated_at
    }

    track_ratings {
        uuid id PK
        uuid user_id FK
        uuid track_id FK
        int rating
        timestamptz created_at
        timestamptz updated_at
    }

    %% ── Audiobook Library ──────────────────────────────────────
    authors {
        uuid id PK
        text name
        string musicbrainz_id UK
        bool is_stub
        bool is_monitored
        uuid quality_profile_id FK
        string monitor_type
        text root_folder_path
        text overview
        string genre
        string country
        text image_url
        string import_source
        uuid studio54_library_path_id FK
        int book_count
        int series_count
        int chapter_count
        timestamptz added_at
        timestamptz last_sync_at
        timestamptz updated_at
    }

    series {
        uuid id PK
        uuid author_id FK
        text name
        string musicbrainz_series_id
        text description
        int total_expected_books
        bool monitored
        text cover_art_url
        timestamptz added_at
        timestamptz updated_at
    }

    books {
        uuid id PK
        uuid author_id FK
        uuid series_id FK
        int series_position
        text related_series
        text title
        string musicbrainz_id UK
        string release_mbid
        date release_date
        string album_type
        text secondary_types
        int chapter_count
        enum status
        bool monitored
        text credit_name
        text co_authors
        string genre
        text description
        text cover_art_url
        text custom_folder_path
        timestamptz last_search_time
        bool quality_meets_cutoff
        timestamptz added_at
        timestamptz searched_at
        timestamptz downloaded_at
        timestamptz updated_at
    }

    chapters {
        uuid id PK
        uuid book_id FK
        text title
        string musicbrainz_id
        int chapter_number
        int disc_number
        int duration_ms
        bool has_file
        text file_path
        int play_count
        timestamptz last_played_at
        timestamptz created_at
        timestamptz updated_at
    }

    book_progress {
        uuid id PK
        uuid user_id FK
        uuid book_id FK
        uuid chapter_id FK
        int position_ms
        bool completed
        timestamptz updated_at
    }

    book_playlists {
        uuid id PK
        uuid series_id FK
        string name
        text description
        timestamptz created_at
        timestamptz updated_at
    }

    book_playlist_chapters {
        uuid id PK
        uuid playlist_id FK
        uuid chapter_id FK
        int position
        int book_position
        timestamptz created_at
    }

    user_listening_sessions {
        uuid id PK
        uuid user_id FK
        string session_type
        uuid book_id FK
        uuid series_id FK
        json chapter_queue
        int current_index
        timestamptz archived_at
        timestamptz pending_delete_at
        timestamptz created_at
        timestamptz updated_at
    }

    %% ── Playlists ──────────────────────────────────────────────
    playlists {
        uuid id PK
        uuid user_id FK
        string name
        text description
        bool is_published
        text cover_art_url
        timestamptz created_at
        timestamptz updated_at
    }

    playlist_tracks {
        uuid playlist_id FK
        uuid track_id FK
        int position
        timestamptz added_at
    }

    playlist_chapters {
        uuid playlist_id FK
        uuid chapter_id FK
        int position
        timestamptz added_at
    }

    %% ── Acquisition ────────────────────────────────────────────
    indexers {
        uuid id PK
        string name UK
        text base_url
        text api_key_encrypted
        string indexer_type
        int priority
        bool is_enabled
        jsonb categories
        float rate_limit_per_second
        int successful_searches
        int failed_searches
        text last_error
        timestamptz created_at
        timestamptz updated_at
        timestamptz last_used_at
    }

    download_clients {
        uuid id PK
        string name UK
        string client_type
        text host
        int port
        bool use_ssl
        text api_key_encrypted
        string category
        int priority
        bool is_enabled
        bool is_default
        int successful_downloads
        int failed_downloads
        text last_error
        timestamptz created_at
        timestamptz updated_at
        timestamptz last_used_at
    }

    download_queue {
        uuid id PK
        uuid album_id FK
        uuid artist_id FK
        uuid book_id FK
        uuid author_id FK
        string library_type
        uuid indexer_id FK
        uuid download_client_id FK
        text nzb_title
        text nzb_guid UK
        text nzb_url
        string sabnzbd_id
        enum status
        int progress_percent
        bigint size_bytes
        text download_path
        text error_message
        text sab_fail_message
        int retry_count
        jsonb attempted_nzb_guids
        jsonb pending_alternates
        timestamptz queued_at
        timestamptz started_at
        timestamptz completed_at
        timestamptz updated_at
    }

    %% ── Library Scanning ───────────────────────────────────────
    library_paths {
        uuid id PK
        text path UK
        string name
        bool is_enabled
        string library_type
        bool is_root_folder
        bigint free_space_bytes
        int total_files
        bigint total_size_bytes
        timestamptz last_scan_at
        int last_scan_duration_seconds
        timestamptz created_at
        timestamptz updated_at
    }

    library_files {
        uuid id PK
        uuid library_path_id FK
        string library_type
        text file_path UK
        text file_name
        bigint file_size_bytes
        timestamptz file_modified_at
        string format
        int bitrate_kbps
        int sample_rate_hz
        int duration_seconds
        text title
        text artist
        text album
        text album_artist
        int track_number
        int disc_number
        int year
        text genre
        string musicbrainz_trackid
        string musicbrainz_albumid
        string musicbrainz_artistid
        string musicbrainz_releasegroupid
        jsonb metadata_json
        bool has_embedded_artwork
        bool album_art_fetched
        text album_art_url
        bool artist_image_fetched
        text artist_image_url
        bool mbid_in_file
        bool is_organized
        timestamptz mbid_verified_at
        string organization_status
        text target_path
        timestamptz last_organization_check
        timestamptz indexed_at
        timestamptz updated_at
    }

    scan_jobs {
        uuid id PK
        uuid library_path_id FK
        string celery_task_id UK
        string status
        int files_scanned
        int files_added
        int files_updated
        int files_skipped
        int files_failed
        int files_removed
        bool pause_requested
        jsonb checkpoint_data
        jsonb skip_statistics
        int elapsed_seconds
        int estimated_remaining_seconds
        text current_action
        text error_message
        text log_file_path
        timestamptz started_at
        timestamptz completed_at
        timestamptz created_at
    }

    library_import_jobs {
        uuid id PK
        uuid library_path_id FK
        string status
        string current_phase
        numeric progress_percent
        string current_action
        string phase_scanning
        string phase_artist_matching
        string phase_metadata_sync
        string phase_folder_matching
        string phase_track_matching
        string phase_enrichment
        string phase_finalization
        int artists_found
        int artists_matched
        int artists_created
        int tracks_matched
        int files_scanned
        bool auto_match_artists
        int confidence_threshold
        text error_message
        json warnings
        text log_file_path
        timestamptz started_at
        timestamptz completed_at
        string celery_task_id
        bool pause_requested
        bool cancel_requested
        timestamptz created_at
        timestamptz updated_at
    }

    library_artist_matches {
        uuid id PK
        uuid import_job_id FK
        string library_artist_name
        int file_count
        json sample_albums
        json sample_file_paths
        string musicbrainz_id
        numeric confidence_score
        string status
        json musicbrainz_suggestions
        uuid matched_artist_id FK
        text rejection_reason
        timestamptz created_at
        timestamptz updated_at
    }

    file_organization_jobs {
        uuid id PK
        enum job_type
        enum status
        string celery_task_id
        uuid library_path_id FK
        uuid artist_id FK
        uuid album_id FK
        float progress_percent
        text current_action
        int files_total
        int files_processed
        int files_renamed
        int files_moved
        int files_failed
        timestamptz started_at
        timestamptz completed_at
        timestamptz created_at
        timestamptz last_heartbeat_at
        text current_file_path
        int current_file_index
        uuid last_processed_file_id
        text error_message
        text log_file_path
        int files_without_mbid
        uuid parent_job_id FK
        uuid source_library_path_id FK
        uuid destination_library_path_id FK
        uuid followup_job_id FK
    }

    unlinked_files {
        uuid id PK
        uuid library_file_id FK
        text file_path
        text artist
        text album
        text title
        string musicbrainz_trackid
        string reason
        text reason_detail
        uuid job_id FK
        timestamptz detected_at
        timestamptz resolved_at
    }

    duplicate_recycle_bin {
        uuid id PK
        string musicbrainz_trackid
        text original_file_path
        text staging_file_path
        text kept_file_path
        int removed_bitrate_kbps
        string removed_format
        int kept_bitrate_kbps
        string kept_format
        timestamptz recycled_at
        timestamptz expires_at
        string status
        timestamptz restored_at
        timestamptz deleted_at
    }

    %% ── Users, Jobs & Config ───────────────────────────────────
    users {
        uuid id PK
        string username UK
        string password_hash
        string display_name
        string role
        bool is_active
        bool must_change_password
        jsonb preferences
        timestamptz created_at
        timestamptz updated_at
        timestamptz last_login_at
    }

    dj_requests {
        uuid id PK
        uuid user_id FK
        string request_type
        string title
        string artist_name
        text notes
        string musicbrainz_id
        string musicbrainz_name
        string track_name
        string status
        text response_note
        uuid fulfilled_by_id FK
        timestamptz created_at
        timestamptz updated_at
    }

    job_states {
        uuid id PK
        enum job_type
        string entity_type
        uuid entity_id
        string celery_task_id UK
        string worker_id
        enum status
        string current_step
        float progress_percent
        int items_processed
        int items_total
        float speed_metric
        int eta_seconds
        timestamptz last_heartbeat_at
        jsonb checkpoint_data
        int retry_count
        int max_retries
        jsonb result_data
        text error_message
        text error_traceback
        text log_file_path
        uuid album_id FK
        uuid scan_job_id FK
        uuid download_queue_id FK
        timestamptz created_at
        timestamptz started_at
        timestamptz updated_at
        timestamptz completed_at
    }

    scheduled_jobs {
        uuid id PK
        string name
        string task_key
        string frequency
        bool enabled
        int run_at_hour
        int day_of_week
        int day_of_month
        json task_params
        timestamptz last_run_at
        timestamptz next_run_at
        uuid last_job_id
        string last_status
        timestamptz created_at
        timestamptz updated_at
    }

    media_management_config {
        uuid id PK
        text artist_folder_template
        text album_folder_template
        text track_file_template
        text multi_disc_track_template
        text music_library_path
        string colon_replacement
        bool rename_tracks
        bool replace_existing_files
        bool use_hardlinks
        text recycle_bin_path
        int recycle_bin_cleanup_days
        bool auto_cleanup_recycle_bin
        int minimum_file_size_mb
        bool skip_free_space_check
        int minimum_free_space_mb
        text sabnzbd_download_path
        bool import_extra_files
        text extra_file_extensions
        bool create_empty_artist_folders
        bool delete_empty_folders
        bool create_folders_on_monitor
        bool set_permissions_linux
        string chmod_folder
        string chmod_file
        string chown_group
        bool upgrade_allowed
        bool prefer_lossless
        int minimum_quality_score
        timestamptz created_at
        timestamptz updated_at
    }

    notification_profiles {
        uuid id PK
        string name UK
        string provider
        text webhook_url_encrypted
        bool is_enabled
        jsonb events
        timestamptz created_at
        timestamptz updated_at
    }

    storage_mounts {
        uuid id PK
        string name
        text host_path UK
        text container_path UK
        bool read_only
        string mount_type
        bool is_system
        bool is_active
        string status
        timestamptz last_applied_at
        text error_message
        timestamptz created_at
        timestamptz updated_at
    }

    %% ── Relationships ──────────────────────────────────────────

    %% Music Library
    quality_profiles ||--o{ artists : "assigned to"
    quality_profiles ||--o{ authors : "assigned to"
    artists ||--o{ albums : "has"
    albums ||--o{ tracks : "has"
    users ||--o{ track_ratings : "gives"
    tracks ||--o{ track_ratings : "receives"

    %% Audiobook Library
    authors ||--o{ series : "writes"
    authors ||--o{ books : "writes"
    series ||--o{ books : "contains"
    books ||--o{ chapters : "has"
    users ||--o{ book_progress : "tracks"
    books ||--o{ book_progress : "tracked by"
    chapters ||--o{ book_progress : "position in"
    series ||--|| book_playlists : "has one"
    book_playlists ||--o{ book_playlist_chapters : "contains"
    chapters ||--o{ book_playlist_chapters : "referenced by"
    users ||--o{ user_listening_sessions : "has"
    books ||--o{ user_listening_sessions : "referenced by"
    series ||--o{ user_listening_sessions : "referenced by"

    %% Playlists
    users ||--o{ playlists : "owns"
    playlists ||--o{ playlist_tracks : "has"
    tracks ||--o{ playlist_tracks : "appears in"
    playlists ||--o{ playlist_chapters : "has"
    chapters ||--o{ playlist_chapters : "appears in"

    %% Acquisition
    artists ||--o{ download_queue : "triggers"
    albums ||--o{ download_queue : "triggers"
    authors ||--o{ download_queue : "triggers"
    books ||--o{ download_queue : "triggers"
    indexers ||--o{ download_queue : "sourced from"
    download_clients ||--o{ download_queue : "handled by"

    %% Library Scanning
    library_paths ||--o{ library_files : "indexes"
    library_paths ||--o{ scan_jobs : "scanned by"
    library_paths ||--o{ library_import_jobs : "imports"
    library_import_jobs ||--o{ library_artist_matches : "produces"
    artists ||--o{ library_artist_matches : "matched to"
    library_files ||--|| unlinked_files : "explains"
    file_organization_jobs ||--o{ unlinked_files : "detected by"
    file_organization_jobs ||--o| file_organization_jobs : "parent of"

    %% Jobs
    job_states ||--o| albums : "targets"
    job_states ||--o| scan_jobs : "tracks"
    job_states ||--o| download_queue : "tracks"

    %% Users
    users ||--o{ dj_requests : "submits"
    users ||--o{ dj_requests : "fulfills"

    %% Artist → Library Path
    artists ||--o| library_paths : "imported from"
    authors ||--o| library_paths : "imported from"
```

---

## 3. Table Reference

### Music Library Domain

#### `artists`
Central catalog entry for a monitored music artist. Linked to MusicBrainz via `musicbrainz_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | TEXT NOT NULL | Indexed |
| `musicbrainz_id` | VARCHAR(100) UNIQUE NOT NULL | MBID; indexed |
| `is_monitored` | BOOL NOT NULL | Default `false` |
| `quality_profile_id` | UUID FK → `quality_profiles` | Nullable |
| `monitor_type` | VARCHAR(30) | `all_albums`, `future_only`, `existing_only`, `first_album`, `latest_album`, `none` |
| `root_folder_path` | TEXT | Base directory path |
| `overview` | TEXT | Biography |
| `genre`, `country` | VARCHAR | Metadata |
| `image_url` | TEXT | From MusicBrainz / Fanart.tv |
| `import_source` | VARCHAR(100) | `muse`, `studio54`, `manual` |
| `muse_library_id` | UUID | External MUSE reference |
| `studio54_library_path_id` | UUID FK → `library_paths` | Nullable |
| `is_stub` | BOOL NOT NULL | Synthetic record (no MB match) |
| `rating_override` | INT | Manual 1–5 star override |
| `album_count`, `single_count`, `track_count` | INT | Denormalized stats |
| `added_at`, `last_sync_at`, `updated_at` | TIMESTAMPTZ | |

**Cascade:** `DELETE artist → DELETE albums → DELETE tracks`

---

#### `albums`
A music release. Tracks both release-group and specific release MBIDs.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `artist_id` | UUID FK → `artists` NOT NULL | CASCADE delete |
| `title` | TEXT NOT NULL | |
| `musicbrainz_id` | VARCHAR(100) UNIQUE NOT NULL | Release MBID (or RG MBID for stubs) |
| `release_mbid` | VARCHAR(36) | Specific release MBID |
| `release_group_mbid` | VARCHAR(36) | Parent release group MBID |
| `release_date` | DATE | |
| `album_type` | VARCHAR(50) | `Album`, `EP`, `Single` |
| `secondary_types` | TEXT | Comma-separated: `Compilation`, `Live` |
| `track_count` | INT | |
| `status` | ENUM NOT NULL | `wanted`, `searching`, `downloading`, `downloaded`, `failed` |
| `monitored` | BOOL NOT NULL | |
| `cover_art_url` | TEXT | |
| `custom_folder_path` | TEXT | Override default Artist/Album structure |
| `is_stub` | BOOL NOT NULL | |
| `last_search_time` | TIMESTAMPTZ | |
| `quality_meets_cutoff` | BOOL NOT NULL | |
| `muse_library_id`, `muse_verified` | UUID / BOOL | MUSE integration |
| `retry_enabled`, `next_retry_at`, `download_retry_count` | BOOL / TIMESTAMPTZ / INT | Retry state |
| `added_at`, `searched_at`, `downloaded_at`, `updated_at` | TIMESTAMPTZ | |

**Cascade:** `DELETE album → DELETE tracks, download_queue`

---

#### `tracks`
Individual recording. Holds file location, lyrics, play stats, and rating data.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `album_id` | UUID FK → `albums` NOT NULL | CASCADE delete |
| `title` | TEXT NOT NULL | |
| `musicbrainz_id` | VARCHAR(100) | Recording MBID or local-UUID stub |
| `track_number`, `disc_number` | INT | |
| `duration_ms` | INT | |
| `has_file` | BOOL | |
| `file_path` | TEXT | Absolute path; indexed |
| `muse_file_id` | UUID | MUSE music_file reference |
| `is_stub` | BOOL NOT NULL | |
| `synced_lyrics` | TEXT | LRC format with timestamps |
| `plain_lyrics` | TEXT | Plain text fallback |
| `lyrics_source` | VARCHAR(50) | e.g. `lrclib` |
| `play_count` | INT | |
| `last_played_at` | TIMESTAMPTZ | |
| `rating` | INT | Legacy single-user rating (1–5) |
| `average_rating` | FLOAT | Precomputed from `track_ratings` |

---

#### `track_ratings`
Per-user track ratings. Unique constraint on `(user_id, track_id)` enables upsert semantics.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `users` NOT NULL | CASCADE delete |
| `track_id` | UUID FK → `tracks` NOT NULL | CASCADE delete |
| `rating` | INT NOT NULL | 1–5 |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

**Unique:** `(user_id, track_id)`

---

### Audiobook Library Domain

The audiobook domain **mirrors the music library** with parallel tables:

| Music | Audiobook | Notes |
|---|---|---|
| `artists` | `authors` | Identical structure |
| `albums` | `books` | + `series_id`, `series_position`, `co_authors`, `description` |
| `tracks` | `chapters` | No lyrics fields |

#### `series`
Ordered collection of books by a single author. Monitoring cascades to all books via SQLAlchemy `after_update` event.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `author_id` | UUID FK → `authors` NOT NULL | CASCADE delete |
| `name` | TEXT NOT NULL | |
| `musicbrainz_series_id` | VARCHAR(36) | |
| `description` | TEXT | |
| `total_expected_books` | INT | |
| `monitored` | BOOL | Cascades to all `books` |
| `cover_art_url` | TEXT | |

---

#### `book_progress`
Tracks the current chapter and millisecond position for a user within a book. One row per `(user, book)`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `users` | CASCADE delete |
| `book_id` | UUID FK → `books` | CASCADE delete |
| `chapter_id` | UUID FK → `chapters` | CASCADE delete |
| `position_ms` | INT | Millisecond position in chapter |
| `completed` | BOOL | |

**Unique:** `(user_id, book_id)`

---

#### `book_playlists` / `book_playlist_chapters`
Auto-generated sequential playlist of all chapters across all books in a series. One playlist per series (1:1).

| `book_playlists` Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `series_id` | UUID FK → `series` UNIQUE | CASCADE delete |
| `name`, `description` | TEXT | |

| `book_playlist_chapters` Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `playlist_id` | UUID FK → `book_playlists` | CASCADE delete |
| `chapter_id` | UUID FK → `chapters` | CASCADE delete |
| `position` | INT | Global order within playlist |
| `book_position` | INT | Position within parent book |

**Unique:** `(playlist_id, chapter_id)`

---

#### `user_listening_sessions`
Tracks an active listening session (book or series) for a user. Holds the full chapter queue as JSON.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `users` | CASCADE delete |
| `session_type` | VARCHAR(10) | `book` or `series` |
| `book_id` | UUID FK → `books` | Nullable; CHECK: exactly one of book_id/series_id |
| `series_id` | UUID FK → `series` | Nullable |
| `chapter_queue` | JSON | Ordered chapter ID list |
| `current_index` | INT | Position in queue |
| `archived_at` | TIMESTAMPTZ | Soft-archived (Mark as Read) |
| `pending_delete_at` | TIMESTAMPTZ | Scheduled hard-delete timestamp |

**Check constraint:** `(book_id IS NOT NULL AND series_id IS NULL) OR (book_id IS NULL AND series_id IS NOT NULL)`  
**Partial unique indexes:** one active session per user per book, one per user per series.

---

### Playlists Domain

#### `playlists`
User-created playlist. Can contain both music tracks and audiobook chapters.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `users` NOT NULL | |
| `name` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `is_published` | BOOL | |
| `cover_art_url` | TEXT | |

#### `playlist_tracks` / `playlist_chapters`
Junction tables with an ordered `position` field. Both use composite PKs.

| Column | Type | Notes |
|---|---|---|
| `playlist_id` | UUID FK → `playlists` PK | CASCADE delete |
| `track_id` / `chapter_id` | UUID FK PK | CASCADE delete |
| `position` | INT NOT NULL | Manual ordering |
| `added_at` | TIMESTAMPTZ | |

---

### Acquisition Domain

#### `indexers`
Newznab-compatible NZB indexer configurations. API keys stored Fernet-encrypted.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE NOT NULL | |
| `base_url` | TEXT NOT NULL | |
| `api_key_encrypted` | TEXT NOT NULL | Fernet ciphertext |
| `indexer_type` | VARCHAR(50) | Default `newznab` |
| `priority` | INT | Lower = higher priority |
| `is_enabled` | BOOL | |
| `categories` | JSONB | e.g. `[3000]` for Audio |
| `rate_limit_per_second` | FLOAT | |
| `successful_searches`, `failed_searches` | INT | Stats |

---

#### `download_clients`
SABnzbd / NZBGet connection config. API keys stored Fernet-encrypted.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE NOT NULL | |
| `client_type` | VARCHAR(50) | `sabnzbd` or `nzbget` |
| `host`, `port`, `use_ssl` | TEXT / INT / BOOL | Connection |
| `api_key_encrypted` | TEXT NOT NULL | Fernet ciphertext |
| `category` | VARCHAR(100) | e.g. `music` |
| `is_default` | BOOL | |

---

#### `download_queue`
Tracks every NZB grab from indexer to import completion. Supports both music and audiobook downloads.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `album_id` | UUID FK → `albums` | Nullable; CASCADE delete |
| `artist_id` | UUID FK → `artists` | Nullable; CASCADE delete |
| `book_id` | UUID FK → `books` | Nullable; CASCADE delete |
| `author_id` | UUID FK → `authors` | Nullable; CASCADE delete |
| `library_type` | VARCHAR(20) | `music` or `audiobook` |
| `indexer_id` | UUID FK → `indexers` | SET NULL on delete |
| `download_client_id` | UUID FK → `download_clients` | SET NULL on delete |
| `nzb_title` | TEXT NOT NULL | |
| `nzb_guid` | TEXT UNIQUE | Deduplicate grabs |
| `sabnzbd_id` | VARCHAR(255) | NZO ID for SABnzbd polling |
| `status` | ENUM | `queued`, `downloading`, `post_processing`, `importing`, `completed`, `failed` |
| `progress_percent` | INT | |
| `size_bytes` | BIGINT | |
| `error_message`, `sab_fail_message` | TEXT | |
| `retry_count` | INT | |
| `attempted_nzb_guids` | JSONB | GUIDs tried for this album |
| `pending_alternates` | JSONB | Alternate NZBs queued |

---

#### `quality_profiles`
Named quality profiles assigned to artists/authors. Controls which formats and bitrates the decision engine accepts.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE NOT NULL | |
| `is_default` | BOOL | |
| `allowed_formats` | JSONB | e.g. `["FLAC","MP3-320"]` |
| `preferred_formats` | JSONB | Ordered by preference |
| `min_bitrate` | INT | kbps |
| `max_size_mb` | INT | Per album |
| `upgrade_enabled` | BOOL | |
| `upgrade_until_quality` | VARCHAR(50) | e.g. `FLAC` |

---

### Library Scanning & File Management Domain

#### `library_paths`
Root directories registered for scanning. `is_root_folder = true` marks Lidarr-style root folders.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `path` | TEXT UNIQUE NOT NULL | |
| `name` | VARCHAR(255) NOT NULL | |
| `is_enabled` | BOOL | |
| `library_type` | VARCHAR(20) | `music` or `audiobook` |
| `is_root_folder` | BOOL | Root folder mode |
| `free_space_bytes`, `total_size_bytes` | BIGINT | |
| `total_files` | INT | |
| `last_scan_at` | TIMESTAMPTZ | |

---

#### `library_files`
Every indexed audio file on disk. The raw filesystem catalog — separate from the curated `tracks`/`chapters` catalog.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `library_path_id` | UUID FK → `library_paths` NOT NULL | CASCADE delete |
| `library_type` | VARCHAR(20) | |
| `file_path` | TEXT UNIQUE NOT NULL | Absolute path |
| `file_size_bytes`, `file_modified_at` | BIGINT / TIMESTAMPTZ | |
| `format` | VARCHAR(20) | `MP3`, `FLAC`, `WAV`, etc. |
| `bitrate_kbps`, `sample_rate_hz`, `duration_seconds` | INT | |
| `title`, `artist`, `album`, `album_artist` | TEXT | From file tags |
| `track_number`, `disc_number`, `year`, `genre` | INT / TEXT | |
| `musicbrainz_trackid`, `musicbrainz_albumid`, `musicbrainz_artistid`, `musicbrainz_releasegroupid` | VARCHAR(36) | All indexed |
| `metadata_json` | JSONB | Full tag dump |
| `has_embedded_artwork`, `album_art_fetched`, `artist_image_fetched` | BOOL | Image status |
| `mbid_in_file` | BOOL | Recording MBID written to file Comment tag |
| `is_organized` | BOOL | File at correct location |
| `organization_status` | VARCHAR(50) | `unprocessed`, `validated`, `needs_rename`, `needs_move`, `organized` |
| `target_path` | TEXT | Calculated ideal path |

**Composite indexes:** `(artist, album)`, `(library_path_id, organization_status)`, MBID columns individually.

---

#### `scan_jobs`
V2 scanner job with pause/resume via `checkpoint_data`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `library_path_id` | UUID FK → `library_paths` | CASCADE delete |
| `celery_task_id` | VARCHAR(255) UNIQUE | |
| `status` | VARCHAR(50) | `pending`, `running`, `completed`, `failed` |
| `checkpoint_data` | JSONB | Phase, last_batch, counters |
| `pause_requested` | BOOL | |
| `skip_statistics` | JSONB | Counts by skip reason |

---

#### `library_import_jobs`
Multi-phase import orchestration job (scan → artist matching → metadata sync → folder matching → track matching → enrichment → finalization).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `library_path_id` | UUID FK → `library_paths` | CASCADE delete |
| `status` | VARCHAR(20) | `pending`, `running`, `paused`, `completed`, `failed`, `cancelled` |
| `current_phase` | VARCHAR(50) | Name of active phase |
| `phase_scanning` … `phase_finalization` | VARCHAR(20) | Per-phase status |
| `confidence_threshold` | INT | 0–100 for auto-matching |
| `pause_requested`, `cancel_requested` | BOOL | Cooperative stop signals |

---

#### `library_artist_matches`
Intermediate matching results produced during library import. Stores MB search candidates for manual review.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `import_job_id` | UUID FK → `library_import_jobs` | CASCADE delete |
| `library_artist_name` | VARCHAR(500) NOT NULL | From file tags |
| `musicbrainz_id` | VARCHAR(36) | Matched MBID (null if unmatched) |
| `confidence_score` | NUMERIC(5,2) | 0–100 |
| `status` | VARCHAR(20) | `pending`, `matched`, `rejected`, `manual_review`, `failed` |
| `musicbrainz_suggestions` | JSON | Candidate list with scores |
| `matched_artist_id` | UUID FK → `artists` | SET NULL on delete |

---

#### `file_organization_jobs`
Tracks file organize, validate, link, rename, migrate, and rollback operations. Self-referential via `parent_job_id` and `followup_job_id`.

**Job types:** `organize_library`, `organize_artist`, `organize_album`, `validate_structure`, `fetch_metadata`, `validate_mbid`, `validate_mbid_metadata`, `link_files`, `reindex_albums`, `verify_audio`, `rollback`, `library_migration`, `migration_fingerprint`, `associate_and_organize`, `validate_file_links`, `resolve_unlinked`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `job_type` | ENUM NOT NULL | See above |
| `status` | ENUM | `pending`, `running`, `paused`, `completed`, `failed`, `cancelled`, `rolled_back` |
| `library_path_id` | UUID FK | Nullable |
| `artist_id` | UUID FK → `artists` | Nullable |
| `album_id` | UUID FK → `albums` | Nullable |
| `parent_job_id` | UUID FK → self | Validation → fetch_metadata chain |
| `source_library_path_id`, `destination_library_path_id` | UUID FK | For migration jobs |
| `followup_job_id` | UUID FK → self | Ponder fingerprint follow-up |
| `last_heartbeat_at` | TIMESTAMPTZ | Stall detection |

---

#### `unlinked_files`
Records why a `library_file` couldn't be linked to a `track` or `chapter`. One row per file (unique on `library_file_id`). Resolved when the file is eventually linked.

| Column | Type | Notes |
|---|---|---|
| `library_file_id` | UUID FK → `library_files` UNIQUE | CASCADE delete |
| `reason` | VARCHAR(100) NOT NULL | e.g. `no_mbid`, `artist_not_found`, `album_not_monitored` |
| `reason_detail` | TEXT | |
| `job_id` | UUID FK → `file_organization_jobs` | SET NULL |
| `resolved_at` | TIMESTAMPTZ | NULL = still unlinked |

---

#### `duplicate_recycle_bin`
Holds duplicate files staged for review. Entries expire automatically after `expires_at`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `musicbrainz_trackid` | VARCHAR(36) NOT NULL | |
| `original_file_path`, `staging_file_path`, `kept_file_path` | TEXT NOT NULL | |
| `removed_bitrate_kbps`, `removed_format` | INT / VARCHAR | The file that was recycled |
| `kept_bitrate_kbps`, `kept_format` | INT / VARCHAR | The file that was kept |
| `status` | VARCHAR(30) | `pending_review`, `permanently_deleted`, `restored` |
| `expires_at` | TIMESTAMPTZ NOT NULL | Auto-cleanup threshold |

---

### Users, Jobs & Config Domain

#### `users`
Authentication and RBAC. Three roles: `director` (admin), `dj` (editor), `partygoer` (read-only).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `username` | VARCHAR(100) UNIQUE NOT NULL | |
| `password_hash` | VARCHAR(255) NOT NULL | bcrypt |
| `role` | VARCHAR(20) | `director`, `dj`, `partygoer` |
| `is_active`, `must_change_password` | BOOL | |
| `preferences` | JSONB | Per-user UI preferences |

---

#### `dj_requests`
User-submitted requests for content. Two FK references to `users` (submitter + fulfiller).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `users` NOT NULL | Submitter |
| `request_type` | VARCHAR(20) | `artist`, `album`, `track` |
| `status` | VARCHAR(20) | `pending`, `approved`, `rejected`, `fulfilled` |
| `fulfilled_by_id` | UUID FK → `users` | Nullable |
| `musicbrainz_id`, `musicbrainz_name` | VARCHAR | For auto-add on approval |

---

#### `job_states`
Universal job tracker for all background operations. Supports heartbeat monitoring, checkpointing, and ETA calculation.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `job_type` | ENUM | `album_search`, `download_monitor`, `import_download`, `library_scan`, `artist_sync`, `metadata_refresh`, `image_fetch`, `cleanup`, `deduplicate` |
| `entity_type`, `entity_id` | VARCHAR / UUID | Polymorphic target reference |
| `celery_task_id` | VARCHAR(255) UNIQUE | Celery task correlation |
| `status` | ENUM | `pending`, `running`, `paused`, `completed`, `failed`, `cancelled`, `stalled`, `retrying` |
| `progress_percent` | FLOAT | 0–100 |
| `last_heartbeat_at` | TIMESTAMPTZ | Stall detection |
| `checkpoint_data` | JSONB | Resume state |
| `album_id` | UUID FK → `albums` | SET NULL |
| `scan_job_id` | UUID FK → `scan_jobs` | CASCADE |
| `download_queue_id` | UUID FK → `download_queue` | CASCADE |

---

#### `scheduled_jobs`
User-configurable periodic tasks checked by Celery Beat every 5 minutes.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `task_key` | VARCHAR(255) NOT NULL | Dispatch key |
| `frequency` | VARCHAR(50) | `daily`, `weekly`, `monthly`, `quarterly` |
| `run_at_hour`, `day_of_week`, `day_of_month` | INT | Schedule parameters |
| `task_params` | JSON | Optional task arguments |
| `next_run_at`, `last_run_at` | TIMESTAMPTZ | |

---

#### `media_management_config`
Single-row configuration table for file naming templates, import behavior, and permissions.

Notable columns: `artist_folder_template`, `album_folder_template`, `track_file_template`, `multi_disc_track_template`, `colon_replacement`, `rename_tracks`, `use_hardlinks`, `recycle_bin_path`, `chmod_folder`, `chmod_file`.

---

#### `notification_profiles`
Webhook/Discord/Slack notification endpoints. URLs stored Fernet-encrypted.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(100) UNIQUE | |
| `provider` | VARCHAR(20) | `webhook`, `discord`, `slack` |
| `webhook_url_encrypted` | TEXT | Fernet ciphertext |
| `events` | JSONB | List of trigger events |

---

#### `storage_mounts`
Docker volume mount management. System mounts are write-protected; user mounts can be added/removed via Settings UI.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `host_path` | TEXT UNIQUE NOT NULL | |
| `container_path` | TEXT UNIQUE NOT NULL | |
| `mount_type` | VARCHAR(20) | `music`, `audiobook`, `generic` |
| `is_system` | BOOL | Protected from UI deletion |
| `status` | VARCHAR(50) | `applied`, `pending`, `failed` |

---

## 4. Key Design Decisions

| Decision | Detail |
|---|---|
| **UUID PKs everywhere** | No auto-increment integers; all IDs are `uuid4`. Avoids enumeration attacks and works across distributed workers. |
| **Encrypted secrets** | `api_key_encrypted`, `webhook_url_encrypted` fields store Fernet ciphertext. The key lives in `STUDIO54_ENCRYPTION_KEY` env var. |
| **Dual library mirrors** | Music (`artists/albums/tracks`) and Audiobook (`authors/books/chapters`) are structurally identical, enabling shared acquisition and job infrastructure. |
| **`is_stub` flag** | Both music and audiobook entities carry `is_stub` for synthetic records created from file metadata when no MusicBrainz match exists. |
| **Denormalized counts** | `artists.album_count`, `authors.book_count` etc. are updated by background tasks rather than computed at query time. |
| **JSONB for flexible data** | `checkpoint_data`, `metadata_json`, `pending_alternates`, `attempted_nzb_guids`, `chapter_queue` use JSONB/JSON to avoid schema churn on evolving fields. |
| **Partial unique indexes** | `user_listening_sessions` uses `postgresql_where` partial indexes to enforce one-active-session-per-user per book or series without blocking multiple rows per user. |
| **Series monitoring cascade** | `Series.monitored` changes propagate to all child `Book` rows via SQLAlchemy `after_update` event listener — not a DB-level trigger. |
| **Self-referential jobs** | `file_organization_jobs.parent_job_id` and `followup_job_id` create job chains (validate → fetch_metadata → fingerprint) without a separate job-dependency table. |
| **62 Alembic migrations** | Migration history starts `2025-12-19` and covers all schema evolution. Migration filenames encode date+sequence for deterministic ordering. |

---

*Next documents: `Backend_API.md`, `Frontend.md`, `TaskQueue.md`, `ExternalIntegrations.md`*
