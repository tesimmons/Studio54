"""
Download Tasks for Studio54
Celery tasks for automated music acquisition and download management.

Key features:
- Full SABnzbd API integration with structured error handling
- Automatic retry with alternate NZBs on duplicate/failure
- NZB attempt tracking to avoid re-trying the same releases
- Download path resolution for SABnzbd category mismatches
"""

from celery import shared_task
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone
import time
import logging

from app.database import SessionLocal
from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.indexer import Indexer
from app.models.download_client import DownloadClient
from app.models.download_queue import DownloadQueue, DownloadStatus
from app.models.download_decision import DownloadHistory, DownloadEventType
from app.models.job_state import JobType
from app.services.encryption import get_encryption_service
from app.services.newznab_client import create_newznab_client, create_aggregator
from app.services.sabnzbd_client import create_sabnzbd_client
from app.config import settings
from app.tasks.base_task import JobTrackedTask
from app.tasks.celery_app import celery_app
from app.tasks.search_tasks import _acquire_search_lock, _release_search_lock

logger = logging.getLogger(__name__)


def get_db() -> Session:
    """Get database session"""
    return SessionLocal()


def _get_attempted_guids_for_album(db: Session, album_id: str) -> set:
    """Get all NZB GUIDs that have been attempted for this album (across all downloads)"""
    downloads = db.query(DownloadQueue).filter(DownloadQueue.album_id == album_id).all()
    guids = set()
    for dl in downloads:
        guids.add(dl.nzb_guid)
        if dl.attempted_nzb_guids:
            guids.update(dl.attempted_nzb_guids)
    return guids


# ==================== SEARCH ====================

@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.download_tasks.search_album",
    max_retries=3,
    default_retry_delay=120,
    autoretry_for=(ConnectionError, TimeoutError)
)
def search_album(self, album_id: str, job_id: str = None, track_title: str = None, **kwargs):
    """
    Search indexers for a specific album and submit best result to SABnzbd.
    Automatically tries alternates if SABnzbd rejects the primary (duplicate, etc).
    Tracks all attempted NZB GUIDs so future retries skip already-tried releases.
    """
    db = self.db

    # Acquire distributed lock to prevent concurrent searches for the same album
    if not _acquire_search_lock(album_id, self.request.id or ""):
        return {"success": False, "skipped": True, "error": "Search already in-flight"}

    try:
        album = db.query(Album).filter(Album.id == album_id).first()
        if not album:
            logger.error(f"Album not found: {album_id}")
            return {"success": False, "error": "Album not found"}

        artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
        if not artist:
            logger.error(f"Artist not found for album: {album_id}")
            return {"success": False, "error": "Artist not found"}

        # Initialize job logger
        search_label = f"Track Search: {artist.name} - {track_title}" if track_title else f"Album Search: {artist.name} - {album.title}"
        job_logger = self.init_job_logger("download", search_label)
        job_logger.log_download_start(
            source="Newznab Indexers",
            album_title=track_title or album.title,
            artist_name=artist.name
        )

        search_title = track_title or album.title
        self.update_progress(percent=5.0, step=f"Starting search for {artist.name} - {search_title}", items_processed=0)

        # Get previously attempted GUIDs so we skip them
        previously_attempted = _get_attempted_guids_for_album(db, album_id)
        if previously_attempted:
            job_logger.log_info(f"Skipping {len(previously_attempted)} previously attempted NZBs")

        # Get enabled indexers
        self.update_progress(percent=10.0, step=f"Getting enabled indexers")
        indexers = db.query(Indexer).filter(Indexer.is_enabled == True).all()
        if not indexers:
            job_logger.log_warning("No enabled indexers configured")
            return {"success": False, "error": "No enabled indexers"}

        job_logger.log_info(f"Found {len(indexers)} enabled indexers")

        # Update album status
        album.status = AlbumStatus.SEARCHING
        db.commit()

        # Create indexer clients
        self.update_progress(percent=20.0, step=f"Connecting to {len(indexers)} indexers")
        encryption_service = get_encryption_service()
        clients = []
        for idx, indexer in enumerate(indexers):
            try:
                api_key = encryption_service.decrypt(indexer.api_key_encrypted)
                categories = indexer.categories if indexer.categories else None
                client = create_newznab_client(indexer.base_url, api_key, indexer.name, categories)
                client.rate_limit_interval = indexer.rate_limit_per_second
                clients.append(client)
                job_logger.log_info(f"  [INDEXER] Connected to {indexer.name}")
                self.update_progress(
                    percent=20.0 + (idx / len(indexers)) * 20.0,
                    step=f"Connected to {indexer.name}",
                    items_processed=idx + 1, items_total=len(indexers)
                )
            except Exception as e:
                logger.error(f"Failed to create client for {indexer.name}: {e}")
                job_logger.log_warning(f"Failed to connect to {indexer.name}: {e}")

        if not clients:
            album.status = AlbumStatus.WANTED
            db.commit()
            job_logger.log_error("No working indexers available")
            return {"success": False, "error": "No working indexers"}

        # Search all indexers
        self.update_progress(percent=50.0, step=f"Searching {len(clients)} indexers for {artist.name} - {search_title}")
        job_logger.log_info(f"\nSearching indexers...")

        aggregator = create_aggregator(clients)
        results = aggregator.search_music(artist=artist.name, album=search_title, limit_per_indexer=50)

        self.update_progress(percent=80.0, step="Processing search results")

        if not results:
            logger.info(f"No results found for: {artist.name} - {search_title}")
            job_logger.log_info("No results found")
            album.status = AlbumStatus.WANTED
            db.commit()
            self.update_progress(percent=100.0, step="Search complete - no results found")
            return {"success": False, "error": "No results found", "total_results": 0}

        # Log top results
        job_logger.log_info(f"Found {len(results)} results")
        job_logger.log_info(f"\nTop 5 results:")
        for i, result in enumerate(results[:5], 1):
            job_logger.log_info(f"  {i}. {result.title}")
            job_logger.log_info(f"     Format: {result.format}, Quality: {result.quality_score} pts")
            job_logger.log_info(f"     Size: {result.size_bytes / (1024*1024):.1f} MB, Indexer: {result.indexer_name}")

        logger.info(f"Found {len(results)} results. Best: {results[0].title} ({results[0].format}, {results[0].quality_score} pts)")

        # Build candidate list, excluding previously attempted GUIDs
        job_logger.log_info(f"\nBuilding download candidates...")
        download_candidates = []
        skipped_count = 0
        for result in results[:20]:  # Consider top 20
            if result.guid in previously_attempted:
                skipped_count += 1
                continue
            result_indexer = db.query(Indexer).filter(Indexer.name == result.indexer_name).first()
            if result_indexer:
                download_candidates.append({
                    "nzb_url": result.download_url,
                    "nzb_title": result.title,
                    "nzb_guid": result.guid,
                    "indexer_id": str(result_indexer.id),
                    "size_bytes": result.size_bytes,
                    "quality_score": result.quality_score,
                    "format": result.format
                })

        if skipped_count:
            job_logger.log_info(f"  Skipped {skipped_count} previously attempted NZBs")

        if not download_candidates:
            job_logger.log_error("No new results to try (all previously attempted)")
            album.status = AlbumStatus.WANTED
            db.commit()
            self.update_progress(percent=100.0, step="No new results available")
            return {
                "success": False,
                "error": f"All {len(results)} results already attempted",
                "total_results": len(results),
                "skipped": skipped_count
            }

        job_logger.log_info(f"  {len(download_candidates)} new candidates to try")
        job_logger.log_info(f"\nSelected best: {download_candidates[0]['nzb_title']}")

        # Submit to add_download with all candidates for fallback
        best = download_candidates[0]
        alternates = download_candidates[1:] if len(download_candidates) > 1 else []

        download_result = add_download.delay(
            album_id=str(album.id),
            nzb_url=best["nzb_url"],
            nzb_title=best["nzb_title"],
            nzb_guid=best["nzb_guid"],
            indexer_id=best["indexer_id"],
            size_bytes=best["size_bytes"],
            alternate_nzbs=alternates
        )

        logger.info(f"Download task submitted: {download_result.id}")
        job_logger.log_download_complete(
            album_title=album.title,
            artist_name=artist.name,
            files_count=1,
            destination_path=best["nzb_title"]
        )
        job_logger.log_info(f"Download task ID: {download_result.id}")
        if alternates:
            job_logger.log_info(f"  ({len(alternates)} alternate results available for fallback)")

        self.update_progress(percent=100.0, step=f"Download started - {best['nzb_title']}")

        return {
            "success": True,
            "total_results": len(results),
            "candidates": len(download_candidates),
            "skipped_previously_attempted": skipped_count,
            "download_triggered": True,
            "download_task_id": download_result.id,
            "album_id": str(album.id),
            "album_title": album.title,
            "artist_name": artist.name
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Search failed for album {album_id}: {e}")
        if self.job_logger:
            self.job_logger.log_error(f"Search failed: {e}")
        raise
    finally:
        _release_search_lock(album_id)


# ==================== ADD DOWNLOAD ====================

@shared_task(name="app.tasks.download_tasks.add_download")
def add_download(album_id: str, nzb_url: str, nzb_title: str, nzb_guid: str,
                 indexer_id: str, size_bytes: int = 0, alternate_nzbs: list = None):
    """
    Add NZB download to SABnzbd with automatic fallback on rejection.

    Tries each candidate in order. Records ALL attempted GUIDs (success or failure)
    so future searches skip them. Captures SABnzbd's error messages verbatim.
    """
    db = get_db()
    try:
        # Get download client
        download_client = db.query(DownloadClient).filter(
            DownloadClient.is_enabled == True,
            DownloadClient.is_default == True
        ).first()
        if not download_client:
            download_client = db.query(DownloadClient).filter(DownloadClient.is_enabled == True).first()
        if not download_client:
            logger.error("No enabled download client configured")
            return {"success": False, "error": "No download client configured"}

        # Create SABnzbd client
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(download_client.api_key_encrypted)
        sabnzbd = create_sabnzbd_client(download_client.base_url, api_key)

        # Build ordered candidate list
        candidates = [{
            "nzb_url": nzb_url, "nzb_title": nzb_title, "nzb_guid": nzb_guid,
            "indexer_id": indexer_id, "size_bytes": size_bytes
        }]
        if alternate_nzbs:
            candidates.extend(alternate_nzbs)

        # Track all attempted GUIDs during this run
        all_attempted_guids = []
        last_error = None

        for attempt, candidate in enumerate(candidates):
            c_url = candidate["nzb_url"]
            c_title = candidate["nzb_title"]
            c_guid = candidate["nzb_guid"]
            c_indexer_id = candidate["indexer_id"]
            c_size = candidate.get("size_bytes", 0)

            all_attempted_guids.append(c_guid)

            # Check if GUID already in our download queue
            existing = db.query(DownloadQueue).filter(DownloadQueue.nzb_guid == c_guid).first()
            if existing:
                logger.info(f"[Attempt {attempt+1}/{len(candidates)}] GUID already in DB: {c_title}")
                last_error = f"Already in download queue: {c_title}"
                continue

            # Submit to SABnzbd - now returns structured AddNzbResult
            logger.info(f"[Attempt {attempt+1}/{len(candidates)}] Sending to SABnzbd: {c_title}")
            result = sabnzbd.add_nzb_url(c_url, category=download_client.category, nzb_name=c_title)

            if not result.success:
                reason = "duplicate" if result.duplicate else "rejected"
                logger.warning(
                    f"[Attempt {attempt+1}/{len(candidates)}] SABnzbd {reason}: {c_title} - {result.error}"
                )
                last_error = result.error
                continue

            # SABnzbd accepted - but it may process duplicate detection asynchronously
            # and silently discard the NZO. Verify it's actually in the queue/history.
            logger.info(f"[Attempt {attempt+1}/{len(candidates)}] SABnzbd accepted, verifying NZO {result.nzo_id}...")
            time.sleep(3)  # Give SABnzbd time to process duplicate check

            verify = sabnzbd.get_download_status(result.nzo_id)

            if not verify.found:
                # SABnzbd discarded it after accepting (async duplicate detection)
                logger.warning(
                    f"[Attempt {attempt+1}/{len(candidates)}] SABnzbd accepted but then discarded: {c_title} "
                    f"(NZO {result.nzo_id} vanished - likely async duplicate rejection)"
                )
                last_error = f"SABnzbd accepted then discarded (async duplicate): {c_title}"
                continue

            if verify.found and verify.in_history and not verify.completed:
                # Already failed to history (duplicate or other immediate failure)
                fail_msg = verify.fail_message or "Failed immediately"
                logger.warning(
                    f"[Attempt {attempt+1}/{len(candidates)}] SABnzbd failed immediately: {c_title} - {fail_msg}"
                )
                # Clean up the failed history entry
                sabnzbd.delete_history_item(result.nzo_id)
                last_error = f"SABnzbd failed immediately: {fail_msg}"
                continue

            if verify.is_duplicate:
                # In queue but flagged as duplicate (paused with DUPLICATE label)
                logger.warning(
                    f"[Attempt {attempt+1}/{len(candidates)}] SABnzbd flagged as duplicate in queue: {c_title}"
                )
                sabnzbd.delete_download(result.nzo_id)
                last_error = f"SABnzbd flagged as duplicate in queue: {c_title}"
                continue

            # Verified - download is genuinely active in SABnzbd
            logger.info(f"[Attempt {attempt+1}/{len(candidates)}] Verified in SABnzbd: {c_title} (status: {verify.status})")

            # Look up artist_id from album
            album_for_artist = db.query(Album).filter(Album.id == album_id).first()
            download = DownloadQueue(
                album_id=album_id,
                artist_id=album_for_artist.artist_id if album_for_artist else None,
                indexer_id=c_indexer_id,
                download_client_id=download_client.id,
                nzb_title=c_title,
                nzb_guid=c_guid,
                nzb_url=c_url,
                sabnzbd_id=result.nzo_id,
                status=DownloadStatus.QUEUED,
                size_bytes=c_size,
                queued_at=datetime.now(timezone.utc),
                attempted_nzb_guids=all_attempted_guids  # Record all GUIDs tried
            )
            db.add(download)

            # Update album status
            album = db.query(Album).filter(Album.id == album_id).first()
            if album:
                album.status = AlbumStatus.DOWNLOADING

            db.commit()
            db.refresh(download)

            if attempt > 0:
                logger.info(
                    f"Download added on attempt {attempt+1}: {c_title} "
                    f"(NZO: {result.nzo_id}) - previous candidates were rejected"
                )
            else:
                logger.info(f"Download added: {c_title} (NZO: {result.nzo_id})")

            return {
                "success": True,
                "download_id": str(download.id),
                "sabnzbd_id": result.nzo_id,
                "nzb_title": c_title,
                "attempt": attempt + 1,
                "total_candidates": len(candidates)
            }

        # All candidates failed - record the attempted GUIDs for future reference
        logger.error(f"All {len(candidates)} candidates rejected for album {album_id}")

        # Store attempt record so future searches skip these GUIDs
        # Create a failed download entry to track what was tried
        album_for_artist = db.query(Album).filter(Album.id == album_id).first()
        download = DownloadQueue(
            album_id=album_id,
            artist_id=album_for_artist.artist_id if album_for_artist else None,
            indexer_id=candidates[0]["indexer_id"],
            download_client_id=download_client.id,
            nzb_title=f"[All {len(candidates)} rejected] {candidates[0]['nzb_title']}",
            nzb_guid=f"_failed_{album_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            status=DownloadStatus.FAILED,
            error_message=f"All {len(candidates)} results rejected by SABnzbd. Last: {last_error}",
            queued_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            attempted_nzb_guids=all_attempted_guids
        )
        db.add(download)

        # Reset album to WANTED
        album = db.query(Album).filter(Album.id == album_id).first()
        if album and album.status in (AlbumStatus.SEARCHING, AlbumStatus.DOWNLOADING):
            album.status = AlbumStatus.WANTED

        db.commit()

        return {
            "success": False,
            "error": f"All {len(candidates)} results rejected. Last: {last_error}",
            "attempts": len(candidates),
            "attempted_guids": len(all_attempted_guids)
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add download: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== MONITOR ====================

@shared_task(name="app.tasks.download_tasks.monitor_active_downloads")
def monitor_active_downloads():
    """
    Monitor all active downloads and update status.
    Periodic task (runs every 30 seconds via beat schedule).

    Handles all SABnzbd statuses:
    - Queue: Downloading, Queued, Paused, Grabbing, Fetching, Propagating
    - History: Completed, Failed, Verifying, Repairing, Extracting, Moving, Running
    - Detects stale downloads (NZO ID not found after 10 min)
    - On failure: triggers auto-retry with next alternate NZB
    """
    db = get_db()
    try:
        active = db.query(DownloadQueue).filter(
            DownloadQueue.status.in_([
                DownloadStatus.QUEUED,
                DownloadStatus.DOWNLOADING,
                DownloadStatus.POST_PROCESSING
            ])
        ).all()

        if not active:
            return {"active_downloads": 0}

        logger.info(f"Monitoring {len(active)} active downloads")

        updated_count = 0
        retry_count = 0

        for download in active:
            try:
                download_client = db.query(DownloadClient).filter(
                    DownloadClient.id == download.download_client_id
                ).first()
                if not download_client:
                    continue

                encryption_service = get_encryption_service()
                api_key = encryption_service.decrypt(download_client.api_key_encrypted)
                sabnzbd = create_sabnzbd_client(download_client.base_url, api_key)

                # Get structured status from SABnzbd
                status = sabnzbd.get_download_status(download.sabnzbd_id)

                if not status.found:
                    # NZO ID not found - check if stale
                    queued_at = download.queued_at or download.updated_at
                    if queued_at:
                        aware_queued = queued_at.replace(tzinfo=timezone.utc) if queued_at.tzinfo is None else queued_at
                        stale_minutes = (datetime.now(timezone.utc) - aware_queued).total_seconds() / 60
                        if stale_minutes > 10:
                            logger.warning(
                                f"Download {download.id} stale ({stale_minutes:.0f} min) - "
                                f"SABnzbd NZO {download.sabnzbd_id} not found"
                            )
                            _mark_download_failed(
                                db, download,
                                error_message=f"SABnzbd lost track of download after {stale_minutes:.0f} min (NZO not found)",
                                sab_fail_message="NZO ID not found in queue or history",
                                reset_album_to_wanted=True
                            )
                            # Trigger auto-retry
                            _trigger_auto_retry(db, download)
                            retry_count += 1
                            updated_count += 1
                    continue

                # Update progress
                download.progress_percent = int(status.percentage)
                download.updated_at = datetime.now(timezone.utc)

                sab_status = (status.status or "").lower()

                # Duplicate detected in queue (paused with DUPLICATE label)
                if status.is_duplicate and "paused" in sab_status:
                    logger.warning(f"Download {download.id} flagged as DUPLICATE in SABnzbd queue")
                    sabnzbd.delete_download(download.sabnzbd_id)
                    _mark_download_failed(
                        db, download,
                        error_message="SABnzbd flagged as duplicate (paused in queue)",
                        sab_fail_message="DUPLICATE label in queue",
                        reset_album_to_wanted=True
                    )
                    _trigger_auto_retry(db, download)
                    retry_count += 1

                # Active download states
                elif sab_status in ("downloading", "queued", "grabbing", "fetching", "propagating"):
                    if download.status == DownloadStatus.QUEUED:
                        download.status = DownloadStatus.DOWNLOADING
                        download.started_at = datetime.now(timezone.utc)

                elif sab_status == "paused":
                    pass  # Keep current status, user or SABnzbd paused it

                # Post-processing states
                elif sab_status in ("extracting", "unpacking", "verifying", "quickcheck",
                                    "repairing", "moving", "running"):
                    download.status = DownloadStatus.POST_PROCESSING

                # Completed
                elif sab_status == "completed" or status.completed:
                    download.status = DownloadStatus.COMPLETED
                    download.completed_at = datetime.now(timezone.utc)
                    download.download_path = status.download_path

                    from app.tasks.download_tasks import import_download
                    import_download.delay(str(download.id))

                # Failed
                elif sab_status == "failed":
                    fail_msg = status.fail_message or "Download failed"
                    is_dup = status.is_duplicate or "duplicate" in fail_msg.lower()

                    _mark_download_failed(
                        db, download,
                        error_message=fail_msg,
                        sab_fail_message=fail_msg,
                        reset_album_to_wanted=is_dup
                    )

                    if not is_dup:
                        # Non-duplicate failure: set album FAILED but still try auto-retry
                        album = db.query(Album).filter(Album.id == download.album_id).first()
                        if album:
                            album.status = AlbumStatus.FAILED

                    # Trigger auto-retry for any failure
                    _trigger_auto_retry(db, download)
                    retry_count += 1

                updated_count += 1

            except Exception as e:
                logger.error(f"Failed to monitor download {download.id}: {e}")
                continue

        db.commit()

        result = {"active_downloads": len(active), "updated": updated_count}
        if retry_count:
            result["auto_retries_triggered"] = retry_count
        return result

    except Exception as e:
        logger.error(f"Download monitoring failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def _mark_download_failed(db: Session, download: DownloadQueue, error_message: str,
                          sab_fail_message: str = None, reset_album_to_wanted: bool = False):
    """Mark a download as failed with full error details"""
    download.status = DownloadStatus.FAILED
    download.error_message = error_message
    download.sab_fail_message = sab_fail_message
    download.completed_at = datetime.now(timezone.utc)

    album = db.query(Album).filter(Album.id == download.album_id).first()

    if reset_album_to_wanted:
        if album and album.status in (AlbumStatus.DOWNLOADING, AlbumStatus.SEARCHING):
            album.status = AlbumStatus.WANTED
            logger.info(f"Reset album '{album.title}' to WANTED")

    # Send failure notification (only if max retries exceeded)
    if download.retry_count >= 3:
        try:
            from app.services.notification_service import send_notification
            artist = db.query(Artist).filter(Artist.id == album.artist_id).first() if album else None
            send_notification("album_failed", {
                "message": f"Download failed: {artist.name if artist else 'Unknown'} - {album.title if album else 'Unknown'}",
                "artist_name": artist.name if artist else "Unknown",
                "album_title": album.title if album else "Unknown",
                "error": error_message,
                "retries_exhausted": True,
            })
        except Exception as e:
            logger.debug(f"Notification send failed: {e}")


def _trigger_auto_retry(db: Session, failed_download: DownloadQueue):
    """
    Trigger automatic retry with a new search for alternate NZBs.
    Only retries if retry_count < 3 to avoid infinite loops.
    """
    if failed_download.retry_count >= 3:
        logger.info(
            f"Download {failed_download.id} already retried {failed_download.retry_count} times, "
            f"not auto-retrying"
        )
        return

    failed_download.retry_count += 1

    album = db.query(Album).filter(Album.id == failed_download.album_id).first()
    if not album:
        return

    # Only retry if album is WANTED (reset by _mark_download_failed) or FAILED
    if album.status not in (AlbumStatus.WANTED, AlbumStatus.FAILED):
        return

    logger.info(
        f"Auto-retry #{failed_download.retry_count} for album '{album.title}' "
        f"(previous: {failed_download.error_message})"
    )

    # Queue a new search - it will skip previously attempted GUIDs
    search_album.apply_async(
        args=[str(album.id)],
        kwargs={
            'job_type': JobType.ALBUM_SEARCH,
            'entity_type': 'album',
            'entity_id': str(album.id)
        },
        countdown=30  # Wait 30 seconds before retrying
    )


# ==================== IMPORT ====================

@shared_task(name="app.tasks.download_tasks.import_download")
def import_download(download_id: str):
    """Import completed download to music library"""
    db = get_db()
    try:
        download = db.query(DownloadQueue).filter(DownloadQueue.id == download_id).first()
        if not download:
            logger.error(f"Download not found: {download_id}")
            return {"success": False, "error": "Download not found"}

        if download.status != DownloadStatus.COMPLETED:
            logger.warning(f"Download not completed: {download_id}")
            return {"success": False, "error": "Download not completed"}

        album = db.query(Album).filter(Album.id == download.album_id).first()
        if not album:
            logger.error(f"Album not found for download: {download_id}")
            return {"success": False, "error": "Album not found"}

        artist = db.query(Artist).filter(Artist.id == album.artist_id).first()
        if not artist:
            logger.error(f"Artist not found for album: {album.id}")
            return {"success": False, "error": "Artist not found"}

        download.status = DownloadStatus.IMPORTING
        db.commit()

        # Resolve download path - SABnzbd may report wrong category dir
        import os
        from pathlib import Path
        from app.models.media_management import MediaManagementConfig
        source_directory = download.download_path

        if source_directory and not Path(source_directory).exists():
            logger.warning(f"Download path not found: {source_directory}")
            folder_name = os.path.basename(source_directory)

            # Get base download dir from DB config, then env var, then default
            mm_config = db.query(MediaManagementConfig).first()
            base_download_dir = None
            if mm_config and mm_config.sabnzbd_download_path:
                # Use the parent of the configured path (e.g. /mnt/sabnzbd/download from /mnt/sabnzbd/download/music)
                base_download_dir = os.path.dirname(mm_config.sabnzbd_download_path)
            if not base_download_dir or not os.path.isdir(base_download_dir):
                base_download_dir = os.environ.get("SABNZBD_DOWNLOAD_DIR", "/downloads")

            found_path = None
            if os.path.isdir(base_download_dir):
                # Search all subdirectories (handles category dir mismatches like movies/ vs music/)
                for subdir in os.listdir(base_download_dir):
                    candidate = os.path.join(base_download_dir, subdir, folder_name)
                    if os.path.isdir(candidate):
                        found_path = candidate
                        logger.info(f"Found download in {subdir}/ subdirectory")
                        break
                if not found_path:
                    candidate = os.path.join(base_download_dir, folder_name)
                    if os.path.isdir(candidate):
                        found_path = candidate

            if found_path:
                logger.info(f"Resolved download path: {source_directory} -> {found_path}")
                download.download_path = found_path
                source_directory = found_path
                db.commit()
            else:
                logger.error(f"Could not find download folder '{folder_name}' in {base_download_dir}")

        # Import album
        from app.services.enhanced_import_service import EnhancedImportService
        import_service = EnhancedImportService(db)

        result = import_service.import_album(
            album=album,
            source_directory=source_directory
        )

        if result["success"]:
            download.status = DownloadStatus.COMPLETED
            album.status = AlbumStatus.DOWNLOADED

            if result.get("imported_files"):
                from app.models.track import Track
                for import_info in result["imported_files"]:
                    track = db.query(Track).filter(
                        Track.album_id == album.id,
                        Track.has_file == False
                    ).first()
                    if track:
                        track.file_path = import_info["destination"]
                        track.has_file = True

            db.commit()

            # Record IMPORTED event in download history
            try:
                imported_count = len(result.get("imported_files", []))
                history = DownloadHistory(
                    album_id=album.id,
                    artist_id=artist.id,
                    release_guid=download.nzb_guid,
                    release_title=download.nzb_title,
                    event_type=DownloadEventType.IMPORTED,
                    quality=download.quality,
                    source=download.indexer,
                    message=f"Successfully imported {imported_count} file(s)",
                    data={
                        "imported_files": imported_count,
                        "upgraded_files": len(result.get("upgraded_files", [])),
                        "skipped_files": len(result.get("skipped_files", [])),
                        "download_path": source_directory,
                    },
                )
                db.add(history)
                db.commit()
            except Exception as hist_err:
                logger.warning(f"Failed to record download history: {hist_err}")

            logger.info(
                f"Successfully imported: {artist.name} - {album.title} "
                f"({len(result.get('imported_files', []))} files)"
            )

            # Send notification
            try:
                from app.services.notification_service import send_notification
                send_notification("album_downloaded", {
                    "message": f"Downloaded: {artist.name} - {album.title}",
                    "artist_name": artist.name,
                    "album_title": album.title,
                    "imported_files": len(result.get("imported_files", [])),
                })
            except Exception as e:
                logger.debug(f"Notification send failed: {e}")

            # Auto-organize if enabled
            try:
                auto_organize = os.getenv("STUDIO54_AUTO_ORG_AFTER_DOWNLOAD", "false").lower() == "true"
                if auto_organize and result.get("imported_files"):
                    logger.info(f"Auto-organizing: {artist.name} - {album.title}")
                    from app.tasks.organization_tasks import organize_artist_files_task
                    from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

                    org_job = FileOrganizationJob(
                        job_type=JobType.ORGANIZE_ARTIST,
                        status=OrgJobStatus.PENDING,
                        artist_id=artist.id,
                        album_id=album.id
                    )
                    db.add(org_job)
                    db.commit()
                    db.refresh(org_job)

                    organize_artist_files_task.delay(
                        job_id=str(org_job.id),
                        artist_id=str(artist.id),
                        options={
                            'dry_run': False, 'create_metadata_files': True,
                            'backup_before_move': False, 'only_with_mbid': True,
                            'only_unorganized': True
                        }
                    )
                    logger.info(f"File organization job {org_job.id} queued for {artist.name}")
            except Exception as e:
                logger.error(f"Failed to trigger file organization: {e}")

            return {
                "success": True,
                "download_id": str(download.id),
                "album_id": str(album.id),
                "imported_files": len(result.get("imported_files", [])),
                "upgraded_files": len(result.get("upgraded_files", [])),
                "skipped_files": len(result.get("skipped_files", [])),
                "errors": result.get("errors", [])
            }
        else:
            download.status = DownloadStatus.FAILED
            download.error_message = result.get("error", "Import failed")
            album.status = AlbumStatus.FAILED
            db.commit()

            # Record IMPORT_FAILED event in download history
            try:
                history = DownloadHistory(
                    album_id=album.id,
                    artist_id=artist.id,
                    release_guid=download.nzb_guid,
                    release_title=download.nzb_title,
                    event_type=DownloadEventType.IMPORT_FAILED,
                    quality=download.quality,
                    source=download.indexer,
                    message=result.get("error", "Import failed"),
                    data={"download_path": source_directory},
                )
                db.add(history)
                db.commit()
            except Exception as hist_err:
                logger.warning(f"Failed to record download history: {hist_err}")

            logger.error(f"Import failed for {download_id}: {result.get('error')}")
            return {"success": False, "error": result.get("error"), "download_id": str(download.id)}

    except Exception as e:
        db.rollback()
        logger.error(f"Import failed for {download_id}: {e}")
        try:
            download = db.query(DownloadQueue).filter(DownloadQueue.id == download_id).first()
            if download:
                download.status = DownloadStatus.FAILED
                download.error_message = str(e)
                # Record IMPORT_FAILED event in download history
                history = DownloadHistory(
                    album_id=download.album_id,
                    release_guid=download.nzb_guid,
                    release_title=download.nzb_title,
                    event_type=DownloadEventType.IMPORT_FAILED,
                    quality=download.quality,
                    source=download.indexer,
                    message=str(e),
                )
                db.add(history)
                db.commit()
        except:
            pass
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== PERIODIC SEARCH ====================

@shared_task(name="app.tasks.download_tasks.search_wanted_albums")
def search_wanted_albums():
    """
    Automatic search for wanted albums (periodic, every 6 hours).
    Checks MUSE library first to avoid duplicate downloads.
    """
    db = get_db()
    try:
        wanted = db.query(Album).join(Artist).filter(
            Artist.is_monitored == True,
            Album.monitored == True,
            Album.status == AlbumStatus.WANTED
        ).limit(50).all()

        if not wanted:
            logger.info("No wanted albums to search")
            return {"wanted_albums": 0, "searched": 0, "found_in_muse": 0}

        logger.info(f"Checking {len(wanted)} wanted albums")

        from app.services.muse_client import get_muse_client
        muse_client = get_muse_client()

        searched_count = 0
        found_in_muse_count = 0

        for album in wanted:
            try:
                if album.musicbrainz_id:
                    exists, file_count = muse_client.album_exists(
                        musicbrainz_id=album.musicbrainz_id,
                        min_track_count=album.track_count or 1
                    )
                    if exists:
                        album.status = AlbumStatus.DOWNLOADED
                        album.muse_verified = True
                        db.commit()
                        found_in_muse_count += 1
                        logger.info(f"Album found in MUSE: {album.title} ({file_count} files)")
                        continue

                search_album.apply_async(
                    args=[str(album.id)],
                    kwargs={
                        'job_type': JobType.ALBUM_SEARCH,
                        'entity_type': 'album',
                        'entity_id': str(album.id)
                    }
                )
                searched_count += 1

            except Exception as e:
                logger.error(f"Failed to process album {album.id}: {e}")

        return {
            "wanted_albums": len(wanted),
            "searched": searched_count,
            "found_in_muse": found_in_muse_count
        }

    except Exception as e:
        logger.error(f"Wanted albums search failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


# ==================== AUDIOBOOK SEARCH ====================

def _get_attempted_guids_for_book(db: Session, book_id: str) -> set:
    """Get all NZB GUIDs that have been attempted for this book (across all downloads)"""
    downloads = db.query(DownloadQueue).filter(DownloadQueue.book_id == book_id).all()
    guids = set()
    for dl in downloads:
        guids.add(dl.nzb_guid)
        if dl.attempted_nzb_guids:
            guids.update(dl.attempted_nzb_guids)
    return guids


@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.download_tasks.search_book",
    max_retries=3,
    default_retry_delay=120,
    autoretry_for=(ConnectionError, TimeoutError)
)
def search_book(self, book_id: str, job_id: str = None, **kwargs):
    """
    Search indexers for a specific audiobook and submit best result to SABnzbd.
    Mirrors search_album but uses Author/Book models and audiobook search category.
    """
    from app.models.book import Book, BookStatus
    from app.models.author import Author

    db = self.db

    # Acquire distributed lock
    if not _acquire_search_lock(f"book_{book_id}", self.request.id or ""):
        return {"success": False, "skipped": True, "error": "Search already in-flight"}

    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            logger.error(f"Book not found: {book_id}")
            return {"success": False, "error": "Book not found"}

        author = db.query(Author).filter(Author.id == book.author_id).first()
        if not author:
            logger.error(f"Author not found for book: {book_id}")
            return {"success": False, "error": "Author not found"}

        # Initialize job logger
        job_logger = self.init_job_logger("download", f"Book Search: {author.name} - {book.title}")
        job_logger.log_download_start(
            source="Newznab Indexers",
            album_title=book.title,
            artist_name=author.name
        )

        self.update_progress(percent=5.0, step=f"Starting search for {author.name} - {book.title}")

        # Get previously attempted GUIDs
        previously_attempted = _get_attempted_guids_for_book(db, book_id)
        if previously_attempted:
            job_logger.log_info(f"Skipping {len(previously_attempted)} previously attempted NZBs")

        # Get enabled indexers
        indexers = db.query(Indexer).filter(Indexer.is_enabled == True).all()
        if not indexers:
            job_logger.log_warning("No enabled indexers configured")
            return {"success": False, "error": "No enabled indexers"}

        # Update book status
        book.status = BookStatus.SEARCHING
        db.commit()

        # Create indexer clients
        encryption_service = get_encryption_service()
        clients = []
        for indexer in indexers:
            try:
                api_key = encryption_service.decrypt(indexer.api_key_encrypted)
                categories = indexer.categories if indexer.categories else None
                client = create_newznab_client(indexer.base_url, api_key, indexer.name, categories)
                client.rate_limit_interval = indexer.rate_limit_per_second
                clients.append(client)
            except Exception as e:
                logger.error(f"Failed to create client for {indexer.name}: {e}")

        if not clients:
            book.status = BookStatus.WANTED
            db.commit()
            return {"success": False, "error": "No working indexers"}

        # Search - use "Author Name - Book Title" format
        self.update_progress(percent=50.0, step=f"Searching indexers for {author.name} - {book.title}")
        aggregator = create_aggregator(clients)
        results = aggregator.search_music(artist=author.name, album=book.title, limit_per_indexer=50)

        if not results:
            book.status = BookStatus.WANTED
            db.commit()
            return {"success": False, "error": "No results found", "total_results": 0}

        # Build candidate list
        download_candidates = []
        skipped_count = 0
        for result in results[:20]:
            if result.guid in previously_attempted:
                skipped_count += 1
                continue
            result_indexer = db.query(Indexer).filter(Indexer.name == result.indexer_name).first()
            if result_indexer:
                download_candidates.append({
                    "nzb_url": result.download_url,
                    "nzb_title": result.title,
                    "nzb_guid": result.guid,
                    "indexer_id": str(result_indexer.id),
                    "size_bytes": result.size_bytes,
                    "quality_score": result.quality_score,
                    "format": result.format
                })

        if not download_candidates:
            book.status = BookStatus.WANTED
            db.commit()
            return {"success": False, "error": "All results previously attempted"}

        # Submit to add_download (reuse music download pipeline with book_id)
        best = download_candidates[0]
        alternates = download_candidates[1:] if len(download_candidates) > 1 else []

        # Use add_download but pass book_id context
        download_result = add_download_book.delay(
            book_id=str(book.id),
            author_id=str(author.id),
            nzb_url=best["nzb_url"],
            nzb_title=best["nzb_title"],
            nzb_guid=best["nzb_guid"],
            indexer_id=best["indexer_id"],
            size_bytes=best["size_bytes"],
            alternate_nzbs=alternates
        )

        self.update_progress(percent=100.0, step=f"Download started - {best['nzb_title']}")

        return {
            "success": True,
            "total_results": len(results),
            "candidates": len(download_candidates),
            "download_triggered": True,
            "download_task_id": download_result.id,
            "book_id": str(book.id),
            "book_title": book.title,
            "author_name": author.name
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Search failed for book {book_id}: {e}")
        raise
    finally:
        _release_search_lock(f"book_{book_id}")


@shared_task(name="app.tasks.download_tasks.add_download_book")
def add_download_book(book_id: str, author_id: str, nzb_url: str, nzb_title: str,
                      nzb_guid: str, indexer_id: str, size_bytes: int = 0,
                      alternate_nzbs: list = None):
    """
    Add audiobook NZB download to SABnzbd.
    Mirrors add_download but creates DownloadQueue with book_id/author_id instead of album_id/artist_id.
    """
    from app.models.book import Book, BookStatus

    db = get_db()
    try:
        download_client = db.query(DownloadClient).filter(
            DownloadClient.is_enabled == True,
            DownloadClient.is_default == True
        ).first()
        if not download_client:
            download_client = db.query(DownloadClient).filter(DownloadClient.is_enabled == True).first()
        if not download_client:
            return {"success": False, "error": "No download client configured"}

        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(download_client.api_key_encrypted)
        sabnzbd = create_sabnzbd_client(download_client.base_url, api_key)

        candidates = [{
            "nzb_url": nzb_url, "nzb_title": nzb_title, "nzb_guid": nzb_guid,
            "indexer_id": indexer_id, "size_bytes": size_bytes
        }]
        if alternate_nzbs:
            candidates.extend(alternate_nzbs)

        all_attempted_guids = []

        for attempt, candidate in enumerate(candidates):
            c_url = candidate["nzb_url"]
            c_title = candidate["nzb_title"]
            c_guid = candidate["nzb_guid"]
            c_indexer_id = candidate["indexer_id"]
            c_size = candidate.get("size_bytes", 0)

            all_attempted_guids.append(c_guid)

            # Check if GUID already in queue
            existing = db.query(DownloadQueue).filter(DownloadQueue.nzb_guid == c_guid).first()
            if existing:
                continue

            # Use audiobook category if configured, fallback to music
            category = getattr(download_client, 'category', 'music') or 'music'
            result = sabnzbd.add_nzb_url(c_url, category=category, nzb_name=c_title)

            if not result.success:
                logger.warning(f"[Book attempt {attempt+1}/{len(candidates)}] SABnzbd rejected: {c_title} - {result.error}")
                continue

            # Create download queue entry
            download_entry = DownloadQueue(
                book_id=book_id,
                author_id=author_id,
                library_type='audiobook',
                indexer_id=c_indexer_id,
                download_client_id=str(download_client.id),
                nzb_url=c_url,
                nzb_title=c_title,
                nzb_guid=c_guid,
                size_bytes=c_size,
                status=DownloadStatus.QUEUED,
                sabnzbd_nzo_id=result.nzo_id,
                attempted_nzb_guids=all_attempted_guids,
            )
            db.add(download_entry)

            # Update book status
            book = db.query(Book).filter(Book.id == book_id).first()
            if book:
                book.status = BookStatus.DOWNLOADING
                book.last_search_time = datetime.now(timezone.utc)

            db.commit()
            logger.info(f"Audiobook download queued: {c_title}")

            return {
                "success": True,
                "download_id": str(download_entry.id),
                "nzb_title": c_title,
                "sabnzbd_nzo_id": result.nzo_id,
            }

        # All candidates failed
        book = db.query(Book).filter(Book.id == book_id).first()
        if book:
            book.status = BookStatus.WANTED
        db.commit()

        return {"success": False, "error": "All download candidates failed"}

    except Exception as e:
        db.rollback()
        logger.error(f"Add download failed for book {book_id}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()
