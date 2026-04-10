# Studio54 Improvement Plan
## Reliability, Performance, and Code Quality Enhancement

**Created:** 2026-01-28
**Status:** Ready for Review

---

## Executive Summary

This document outlines a comprehensive plan to improve the Studio54 service based on a thorough code analysis. The codebase has solid foundations with good job tracking infrastructure, but needs refinement in transaction handling, performance optimization, and reliability for production use at scale.

### Key Statistics
- **176 scattered `db.commit()` calls** across task files (92 in organization_tasks.py alone)
- **113 exception handlers** in tasks (many overly broad)
- **Multiple N+1 query patterns** in API endpoints
- **Missing heartbeat updates** in long-running operations
- **Duplicate code** in file organization services

---

## Priority 1: Critical Reliability Issues

### 1.1 Add Heartbeat Updates to Long-Running Tasks

**Problem:** Jobs marked as stalled even though still processing because heartbeat only updates with progress.

**Files to Modify:**
- `app/tasks/organization_tasks.py` (lines 250-550)
- `app/tasks/fast_ingest_tasks.py`
- `app/tasks/import_tasks.py`

**Solution:**
```python
# Add heartbeat every N iterations or seconds
HEARTBEAT_INTERVAL = 30  # seconds

def _send_heartbeat_if_needed(self, last_heartbeat_time):
    """Send heartbeat if enough time has passed."""
    now = datetime.now(timezone.utc)
    if (now - last_heartbeat_time).total_seconds() >= HEARTBEAT_INTERVAL:
        if self.job:
            self.job.last_heartbeat_at = now
            self.db.commit()
        return now
    return last_heartbeat_time
```

**Implementation:**
- Add heartbeat call at start of each batch processing loop
- Add periodic heartbeat thread for very long operations
- Update `base_task.py` with automatic heartbeat support

**Estimated Effort:** 4-6 hours
**Impact:** High - Prevents false stall detection

---

### 1.2 Implement Atomic Transactions for File Organization

**Problem:** Partial file moves can leave files in inconsistent state. Multiple commits scattered throughout operations.

**Files to Modify:**
- `app/tasks/organization_tasks.py` (92 commits!)
- `app/shared_services/atomic_file_ops.py`

**Solution:**
```python
from contextlib import contextmanager

@contextmanager
def atomic_file_operation(db, job):
    """Ensure file operation is atomic with database."""
    try:
        yield
        db.commit()
    except Exception as e:
        db.rollback()
        job.files_failed += 1
        raise

# Usage:
with atomic_file_operation(db, job):
    # Move file
    # Update database record
    # Log audit entry
```

**Implementation:**
1. Create transaction context manager
2. Consolidate commits to batch boundaries
3. Add savepoints for partial rollback
4. Implement two-phase commit for file + DB operations

**Estimated Effort:** 8-12 hours
**Impact:** High - Prevents data corruption

---

### 1.3 Fix Race Conditions in File Organization

**Problem:** Multiple workers could try to organize same file simultaneously.

**Files to Modify:**
- `app/tasks/organization_tasks.py` (lines 505-549)
- `app/models/library.py`

**Solution:**
```python
from sqlalchemy import select, update
from sqlalchemy.orm import with_for_update

# Use SELECT FOR UPDATE to lock row
file_record = db.execute(
    select(LibraryFile)
    .where(LibraryFile.id == file_id)
    .with_for_update(nowait=True)
).scalar_one_or_none()

# Or use advisory locks
from sqlalchemy import text
db.execute(text("SELECT pg_advisory_lock(:key)"), {"key": hash(file_path)})
try:
    # Organize file
finally:
    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": hash(file_path)})
```

**Implementation:**
1. Add row-level locking for file operations
2. Add unique constraint on (file_path, job_id) in audit table
3. Implement optimistic locking with version column
4. Add retry logic for lock conflicts

**Estimated Effort:** 6-8 hours
**Impact:** High - Prevents duplicate processing

---

### 1.4 Add Retry Logic for External Services

**Problem:** No retry for MusicBrainz, SABnzbd, or other external API calls.

**Files to Modify:**
- `app/services/musicbrainz_client.py`
- `app/services/sabnzbd_client.py`
- `app/services/ponder_client.py`
- `app/tasks/sync_tasks.py`

**Solution:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, HTTPError)),
    before_sleep=lambda retry_state: logger.warning(
        f"Retrying {retry_state.fn.__name__} after {retry_state.outcome.exception()}"
    )
)
def call_musicbrainz_api(self, endpoint, params):
    # API call implementation
```

**Implementation:**
1. Add `tenacity` to requirements.txt
2. Wrap all external API calls with retry decorator
3. Add circuit breaker pattern for repeated failures
4. Log retry attempts for monitoring

**Estimated Effort:** 4-6 hours
**Impact:** High - Improves resilience to network issues

---

## Priority 2: Performance Optimizations

### 2.1 Fix N+1 Query Problems

**Problem:** Multiple locations load collections then query each item individually.

**Files to Modify:**
- `app/api/albums.py` (line 80)
- `app/api/artists.py` (line 139)
- `app/tasks/monitoring_tasks.py` (lines 40-46, 69-75, 102-108)
- `app/tasks/download_tasks.py` (line 87)

**Solution:**
```python
# Before (N+1):
albums = db.query(Album).limit(100).all()
for album in albums:
    print(album.artist.name)  # Lazy load each time!

# After (eager loading):
from sqlalchemy.orm import joinedload, selectinload

albums = db.query(Album)\
    .options(joinedload(Album.artist))\
    .options(selectinload(Album.tracks))\
    .limit(100).all()
```

**Implementation:**
1. Add `joinedload` for single relationships (many-to-one)
2. Add `selectinload` for collection relationships (one-to-many)
3. Create query builder helpers for common patterns
4. Add query logging to identify remaining N+1 issues

**Estimated Effort:** 6-8 hours
**Impact:** High - 10-100x improvement for list queries

---

### 2.2 Add Missing Database Indexes

**Problem:** Common query patterns lack compound indexes.

**Files to Modify:**
- `app/models/library.py`
- `alembic/versions/` (new migration)

**New Indexes to Add:**
```python
# In library.py LibraryFile model
Index('idx_library_files_path_organized', 'library_path_id', 'is_organized'),
Index('idx_library_files_path_mbid', 'library_path_id', 'musicbrainz_trackid'),
Index('idx_library_files_path_status', 'library_path_id', 'organization_status'),
Index('idx_library_files_created', 'created_at'),  # For time-based queries
Index('idx_library_files_album_track', 'album_id', 'track_number'),
```

**Implementation:**
1. Analyze slow query log to identify missing indexes
2. Create Alembic migration for new indexes
3. Add EXPLAIN ANALYZE to critical queries
4. Consider partial indexes for boolean columns

**Estimated Effort:** 2-4 hours
**Impact:** Medium-High - Faster filtering queries

---

### 2.3 Implement Batch Commit Strategy

**Problem:** 176 scattered commits cause unnecessary I/O and partial state visibility.

**Files to Modify:**
- `app/tasks/organization_tasks.py` (92 commits)
- `app/tasks/sync_tasks.py` (10 commits)
- `app/tasks/import_tasks.py` (32 commits)

**Solution:**
```python
class BatchCommitter:
    """Batch database commits for efficiency."""

    def __init__(self, db, batch_size=100):
        self.db = db
        self.batch_size = batch_size
        self.pending_count = 0

    def add(self):
        """Mark an operation pending."""
        self.pending_count += 1
        if self.pending_count >= self.batch_size:
            self.flush()

    def flush(self):
        """Commit pending changes."""
        if self.pending_count > 0:
            self.db.commit()
            self.pending_count = 0

# Usage:
committer = BatchCommitter(db, batch_size=100)
for file in files:
    process_file(file)
    committer.add()
committer.flush()  # Final commit
```

**Implementation:**
1. Create BatchCommitter utility class
2. Refactor tasks to use batch commits
3. Consolidate progress updates with data commits
4. Add configurable batch size via environment variable

**Estimated Effort:** 6-8 hours
**Impact:** Medium - Reduced I/O, faster throughput

---

### 2.4 Optimize Memory Usage for Large Libraries

**Problem:** Building entire file index in memory (500MB+ for 100K files).

**Files to Modify:**
- `app/services/library_scanner.py` (line 91)
- `app/tasks/organization_tasks.py` (lines 250-280)

**Solution:**
```python
# Before: Load all into memory
existing_files = {f.file_path: f for f in db.query(LibraryFile).all()}

# After: Stream with generator
def iter_existing_files(db, library_path_id, batch_size=1000):
    """Stream files in batches to reduce memory."""
    offset = 0
    while True:
        batch = db.query(LibraryFile)\
            .filter(LibraryFile.library_path_id == library_path_id)\
            .order_by(LibraryFile.id)\
            .offset(offset)\
            .limit(batch_size)\
            .all()
        if not batch:
            break
        yield from batch
        offset += batch_size

# Or use server-side cursor
from sqlalchemy import create_engine
engine = create_engine(url, execution_options={"stream_results": True})
```

**Implementation:**
1. Replace `.all()` with streaming generators
2. Use server-side cursors for large result sets
3. Process files in batches, not all at once
4. Add memory profiling to identify hotspots

**Estimated Effort:** 4-6 hours
**Impact:** Medium - Enables processing of very large libraries

---

## Priority 3: Code Quality Improvements

### 3.1 Consolidate Error Handling Patterns

**Problem:** 113 exception handlers with inconsistent patterns, including bare `except:` clauses.

**Files to Modify:**
- `app/tasks/base_task.py` (lines 125-126, 212-213, 341)
- All task files

**Solution:**
```python
# Create centralized error categorization
class TaskError(Exception):
    """Base class for task errors."""
    is_retryable = False

class TransientError(TaskError):
    """Error that should be retried."""
    is_retryable = True

class FatalError(TaskError):
    """Error that should not be retried."""
    is_retryable = False

class FileSystemError(TaskError):
    """File system related error."""
    pass

# Decorator for consistent handling
def handle_task_errors(max_retries=3):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except TransientError as e:
                if attempt < max_retries:
                    logger.warning(f"Transient error, retrying: {e}")
                    raise self.retry(exc=e)
                raise
            except FatalError as e:
                logger.error(f"Fatal error: {e}")
                raise
            except Exception as e:
                logger.exception(f"Unexpected error: {e}")
                raise
        return wrapper
    return decorator
```

**Implementation:**
1. Create error hierarchy in `app/errors.py`
2. Replace bare except clauses with specific types
3. Add error categorization decorator
4. Update tasks to use new error handling

**Estimated Effort:** 6-8 hours
**Impact:** Medium - Better debugging and error recovery

---

### 3.2 Unify Job Status Enums

**Problem:** Two different JobStatus enums with different values.

**Files to Modify:**
- `app/models/job_state.py` (lines 30-40)
- `app/models/file_organization_job.py` (lines 30-38)
- `app/api/jobs.py` (lines 180-186)

**Solution:**
```python
# Create single source of truth in app/models/enums.py
from enum import Enum

class JobStatus(str, Enum):
    """Unified job status enum."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALLED = "stalled"
    RETRYING = "retrying"
    ROLLED_BACK = "rolled_back"

# Import from single location
from app.models.enums import JobStatus
```

**Implementation:**
1. Create `app/models/enums.py` with unified enums
2. Update all models to import from enums.py
3. Create Alembic migration to standardize stored values
4. Update API to use single enum

**Estimated Effort:** 4-6 hours
**Impact:** Medium - Eliminates status mapping bugs

---

### 3.3 Implement Checkpoint/Resume for Organization Tasks

**Problem:** Tasks restart from beginning even if checkpoint exists.

**Files to Modify:**
- `app/tasks/organization_tasks.py`
- `app/tasks/checkpoint_mixin.py`
- `app/services/job_checkpoint_manager.py`

**Solution:**
```python
@shared_task(bind=True, base=JobTrackedTask)
def organize_library_files_task(self, job_id: str, library_path_id: str, options: dict):
    # Load checkpoint if resuming
    checkpoint = self.load_checkpoint()
    start_offset = checkpoint.get('last_processed_offset', 0) if checkpoint else 0

    files = query.offset(start_offset).all()

    for i, file in enumerate(files):
        # Process file

        # Save checkpoint periodically
        if i % 100 == 0:
            self.save_checkpoint({
                'last_processed_offset': start_offset + i,
                'files_processed': job.files_processed,
                'files_moved': job.files_moved
            })

        # Check for pause request
        if self.check_should_pause():
            self.save_checkpoint({...})
            job.status = JobStatus.PAUSED
            db.commit()
            return
```

**Implementation:**
1. Add checkpoint loading at task start
2. Save checkpoint every N files processed
3. Implement pause checking in main loop
4. Store checkpoint in Redis for fast access

**Estimated Effort:** 6-8 hours
**Impact:** Medium - Enables resume after failures/restarts

---

### 3.4 Add Configuration for Hardcoded Values

**Problem:** Timeouts, batch sizes, and limits are hardcoded throughout.

**Files to Modify:**
- `app/config.py` (create)
- Multiple task and service files

**Solution:**
```python
# app/config.py
from pydantic_settings import BaseSettings

class TaskConfig(BaseSettings):
    """Task configuration settings."""

    # Batch processing
    BATCH_SIZE: int = 100
    COMMIT_INTERVAL: int = 500
    HEARTBEAT_INTERVAL: int = 30

    # Timeouts
    HEALTH_CHECK_TIMEOUT: int = 5
    EXTERNAL_API_TIMEOUT: int = 30
    FILE_OPERATION_TIMEOUT: int = 60

    # Retry settings
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    RETRY_BACKOFF: float = 2.0

    # Error thresholds
    MAX_CONSECUTIVE_ERRORS: int = 5
    MAX_TOTAL_ERRORS_PERCENT: float = 0.1  # 10%

    class Config:
        env_prefix = "STUDIO54_"

config = TaskConfig()
```

**Implementation:**
1. Create centralized config module
2. Replace hardcoded values with config references
3. Add environment variable overrides
4. Document all configuration options

**Estimated Effort:** 4-6 hours
**Impact:** Low-Medium - Easier tuning without code changes

---

## Priority 4: Architecture Improvements

### 4.1 Consolidate File Organization Services

**Problem:** Duplicate logic in multiple files.

**Files to Consolidate:**
- `app/services/file_organizer.py`
- `app/shared_services/file_organizer.py`
- Inline code in `app/tasks/organization_tasks.py`

**Solution:**
Create single authoritative service:
```
app/services/file_management/
├── __init__.py
├── organizer.py          # Core organization logic
├── naming_engine.py      # File naming templates
├── atomic_ops.py         # Atomic file operations
├── audit_logger.py       # Audit trail
└── validators.py         # Path validation
```

**Estimated Effort:** 8-12 hours
**Impact:** Medium - Reduced maintenance burden

---

### 4.2 Create Repository Pattern for Database Access

**Problem:** Raw SQL and inconsistent query patterns throughout.

**Solution:**
```python
# app/repositories/library_file_repository.py
class LibraryFileRepository:
    """Repository for LibraryFile database operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_unorganized_files(
        self,
        library_path_id: UUID,
        only_with_mbid: bool = True,
        limit: int = 1000
    ) -> List[LibraryFile]:
        """Get files needing organization."""
        query = self.db.query(LibraryFile)\
            .filter(LibraryFile.library_path_id == library_path_id)\
            .filter(LibraryFile.is_organized == False)

        if only_with_mbid:
            query = query.filter(LibraryFile.musicbrainz_trackid.isnot(None))

        return query.options(
            joinedload(LibraryFile.album).joinedload(Album.artist)
        ).limit(limit).all()

    def bulk_update_organized_status(
        self,
        file_ids: List[UUID],
        is_organized: bool
    ) -> int:
        """Bulk update organized status."""
        return self.db.query(LibraryFile)\
            .filter(LibraryFile.id.in_(file_ids))\
            .update({LibraryFile.is_organized: is_organized})
```

**Estimated Effort:** 12-16 hours
**Impact:** Medium - Better testability and query optimization

---

## Implementation Timeline

### Phase 1: Critical Reliability (Week 1-2)
| Task | Effort | Priority |
|------|--------|----------|
| 1.1 Heartbeat Updates | 4-6 hrs | Critical |
| 1.2 Atomic Transactions | 8-12 hrs | Critical |
| 1.3 Race Condition Fixes | 6-8 hrs | Critical |
| 1.4 External Service Retries | 4-6 hrs | Critical |

**Deliverables:**
- Jobs no longer falsely marked as stalled
- File operations atomic and recoverable
- No duplicate file processing
- Resilient to network issues

### Phase 2: Performance (Week 3-4)
| Task | Effort | Priority |
|------|--------|----------|
| 2.1 Fix N+1 Queries | 6-8 hrs | High |
| 2.2 Add Database Indexes | 2-4 hrs | High |
| 2.3 Batch Commit Strategy | 6-8 hrs | Medium |
| 2.4 Memory Optimization | 4-6 hrs | Medium |

**Deliverables:**
- 10-100x faster list queries
- Reduced database I/O
- Support for 100K+ file libraries

### Phase 3: Code Quality (Week 5-6)
| Task | Effort | Priority |
|------|--------|----------|
| 3.1 Error Handling Patterns | 6-8 hrs | Medium |
| 3.2 Unify Job Status Enums | 4-6 hrs | Medium |
| 3.3 Checkpoint/Resume | 6-8 hrs | Medium |
| 3.4 Configuration Module | 4-6 hrs | Low |

**Deliverables:**
- Consistent error handling
- No status mapping bugs
- Jobs can resume after restart
- Configurable without code changes

### Phase 4: Architecture (Week 7-8)
| Task | Effort | Priority |
|------|--------|----------|
| 4.1 Consolidate Services | 8-12 hrs | Medium |
| 4.2 Repository Pattern | 12-16 hrs | Low |

**Deliverables:**
- Single source of truth for file operations
- Testable database layer
- Cleaner codebase

---

## Monitoring & Metrics

### Recommended Metrics to Track

1. **Job Health**
   - Jobs completed vs failed per hour
   - Average job duration by type
   - Stalled job count
   - Retry rate

2. **Performance**
   - Query duration (p50, p95, p99)
   - Database connections in use
   - Memory usage per worker
   - Commit rate per second

3. **Reliability**
   - External API error rate
   - File operation failure rate
   - Rollback count
   - Data inconsistency alerts

### Suggested Alerts

```python
# Example Prometheus alert rules
groups:
  - name: studio54_alerts
    rules:
      - alert: HighJobFailureRate
        expr: rate(studio54_job_failures_total[5m]) > 0.1
        for: 5m

      - alert: JobsStalled
        expr: studio54_stalled_jobs_count > 5
        for: 10m

      - alert: SlowQueries
        expr: histogram_quantile(0.95, studio54_query_duration) > 5
        for: 5m
```

---

## Testing Requirements

### Unit Tests Needed
- [ ] Atomic file operation rollback
- [ ] Checkpoint save/load
- [ ] Error categorization
- [ ] Batch committer
- [ ] Retry logic

### Integration Tests Needed
- [ ] Full job lifecycle with pause/resume
- [ ] Concurrent file organization (race conditions)
- [ ] Large library scan (memory)
- [ ] External service failure recovery

### Load Tests Needed
- [ ] 10K files organization
- [ ] 100K files scan
- [ ] 10 concurrent workers

---

## Success Criteria

After implementation:

1. **Reliability**
   - Zero false stall detections
   - < 0.1% data inconsistencies
   - 99.9% job completion rate

2. **Performance**
   - API responses < 200ms (p95)
   - 1000 files/minute organization rate
   - < 2GB memory for 100K file library

3. **Maintainability**
   - All configuration externalized
   - 80%+ test coverage on critical paths
   - Single source of truth for business logic

---

## Appendix: Quick Wins (< 2 hours each)

These improvements can be made immediately with minimal risk:

1. **Replace bare except clauses** in `base_task.py`
   ```python
   # Change: except:
   # To: except Exception:
   ```

2. **Add missing indexes** via Alembic migration

3. **Add tenacity retry** to MusicBrainz client

4. **Add heartbeat** to organization task main loop

5. **Consolidate commits** in monitoring_tasks.py (move outside loop)

6. **Add eager loading** to album list endpoint

7. **Create unified JobStatus enum** file

---

## References

- [SQLAlchemy Session Best Practices](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [Celery Task Best Practices](https://docs.celeryq.dev/en/stable/userguide/tasks.html#best-practices)
- [PostgreSQL Index Design](https://www.postgresql.org/docs/current/indexes.html)
- [Tenacity Retry Library](https://tenacity.readthedocs.io/)
