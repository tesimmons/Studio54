"""
SABnzbd Client for Studio54
Manages NZB downloads via SABnzbd API

Provides structured responses with full error details from SABnzbd,
including duplicate detection, fail messages, and queue labels.
"""
import time
import requests
from typing import Optional, Dict, List, Any
from urllib.parse import urljoin
import logging
from dataclasses import dataclass, field
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


@dataclass
class AddNzbResult:
    """Structured result from adding an NZB to SABnzbd"""
    success: bool
    nzo_id: Optional[str] = None
    status: bool = False            # SABnzbd's raw status field
    error: Optional[str] = None     # Error message if failed
    duplicate: bool = False         # Whether SABnzbd flagged as duplicate
    raw_response: Optional[Dict] = field(default_factory=dict)


@dataclass
class DownloadStatusResult:
    """Structured download status from SABnzbd queue or history"""
    found: bool = False
    nzo_id: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None        # Raw SABnzbd status string
    percentage: float = 0.0
    size_bytes: int = 0
    size_left_bytes: int = 0
    download_path: Optional[str] = None
    category: Optional[str] = None
    eta: Optional[str] = None
    fail_message: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    is_duplicate: bool = False
    completed: bool = False
    in_history: bool = False
    stage_log: List[Dict] = field(default_factory=list)


# Retry decorator for transient network errors
def _retry_on_network_error():
    """Create retry decorator for network operations"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


class SABnzbdClient:
    """
    SABnzbd API client for download management

    Integrates with user's SABnzbd instance for automated music downloads.
    Returns structured results with full error details instead of swallowing errors.
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key

    def _make_request(
        self,
        mode: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Make API request to SABnzbd with automatic retry on transient errors.

        Returns raw JSON dict or None on network/parse failure.
        Does NOT swallow SABnzbd error responses - callers must check for errors.
        """
        if params is None:
            params = {}

        request_params = {
            "apikey": self.api_key,
            "mode": mode,
            "output": "json"
        }
        request_params.update(params)

        url = f"{self.base_url}/api"

        try:
            data = self._execute_request_with_retry(url, request_params, timeout)
            return data

        except requests.exceptions.Timeout:
            logger.error(f"[SABnzbd] Request timeout after {timeout}s (after retries)")
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"[SABnzbd] Request failed after retries: {e}")
            return None

        except ValueError as e:
            logger.error(f"[SABnzbd] Invalid JSON response: {e}")
            return None

    @_retry_on_network_error()
    def _execute_request_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
        timeout: int
    ) -> Dict[str, Any]:
        """Execute HTTP request with retry logic"""
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()

    # ==================== NZB SUBMISSION ====================

    def add_nzb_url(
        self,
        nzb_url: str,
        category: str = "music",
        priority: int = 0,
        nzb_name: Optional[str] = None
    ) -> AddNzbResult:
        """
        Add NZB download by URL with full structured response.

        SABnzbd duplicate detection modes:
          no_dupes=0: Off (always accept)
          no_dupes=1: Discard (reject silently, empty nzo_ids)
          no_dupes=2: Pause (accept but pause, label DUPLICATE)
          no_dupes=3: Fail to history (nzo_id returned, job in history as Failed)
          no_dupes=4: Tag only (accept normally, label DUPLICATE)

        Returns:
            AddNzbResult with success, nzo_id, duplicate flag, and error details
        """
        params = {
            "name": nzb_url,
            "cat": category,
            "priority": priority
        }

        if nzb_name:
            params["nzbname"] = nzb_name

        result = self._make_request("addurl", params)

        if result is None:
            return AddNzbResult(
                success=False,
                error="SABnzbd connection failed - no response",
                raw_response={}
            )

        # Check for explicit API error
        if isinstance(result, dict) and result.get("error"):
            return AddNzbResult(
                success=False,
                error=f"SABnzbd API error: {result['error']}",
                raw_response=result
            )

        sab_status = result.get("status", False)
        nzo_ids = result.get("nzo_ids", [])

        # Case 1: Success with NZO ID
        if nzo_ids and len(nzo_ids) > 0:
            nzo_id = nzo_ids[0]

            # Check if this was a "fail to history" duplicate (no_dupes=3)
            # SABnzbd returns status=true with nzo_id, but job is already in history as Failed
            if sab_status:
                # Could be genuine success OR fail-to-history duplicate
                # Check history to distinguish
                hist_item = self._get_raw_history_item(nzo_id)
                if hist_item and hist_item.get("status") == "Failed":
                    fail_msg = hist_item.get("fail_message", "")
                    if "duplicate" in fail_msg.lower():
                        logger.warning(f"[SABnzbd] Duplicate (failed to history): {nzb_name} - {fail_msg}")
                        return AddNzbResult(
                            success=False,
                            nzo_id=nzo_id,
                            status=sab_status,
                            error=f"Duplicate NZB (failed to history): {fail_msg}",
                            duplicate=True,
                            raw_response=result
                        )

            logger.info(f"[SABnzbd] Added download: {nzo_id} - {nzb_name or nzb_url}")
            return AddNzbResult(
                success=True,
                nzo_id=nzo_id,
                status=sab_status,
                raw_response=result
            )

        # Case 2: Empty nzo_ids - rejected (discard duplicate or other error)
        error_msg = "SABnzbd rejected NZB"
        if not sab_status:
            error_msg = "SABnzbd rejected NZB (likely duplicate - no_dupes=Discard)"

        logger.warning(f"[SABnzbd] Rejected: {nzb_name or nzb_url} - {error_msg}")
        return AddNzbResult(
            success=False,
            status=sab_status,
            error=error_msg,
            duplicate=True,  # Most common reason for empty nzo_ids
            raw_response=result
        )

    # ==================== STATUS MONITORING ====================

    def get_download_status(self, nzo_id: str) -> DownloadStatusResult:
        """
        Get comprehensive status of a specific download.
        Checks both queue and history, returns structured result.

        Returns:
            DownloadStatusResult - always returns a result (check .found)
        """
        # Check queue first
        queue_result = self._check_queue_for_nzo(nzo_id)
        if queue_result.found:
            return queue_result

        # Check history
        history_result = self._check_history_for_nzo(nzo_id)
        if history_result.found:
            return history_result

        # Not found anywhere
        return DownloadStatusResult(found=False, nzo_id=nzo_id)

    def _check_queue_for_nzo(self, nzo_id: str) -> DownloadStatusResult:
        """Check SABnzbd queue for a specific NZO ID"""
        result = self._make_request("queue")
        if not result or "queue" not in result:
            return DownloadStatusResult(found=False, nzo_id=nzo_id)

        for slot in result["queue"].get("slots", []):
            if slot.get("nzo_id") == nzo_id:
                labels = slot.get("labels", [])
                is_dup = "DUPLICATE" in labels
                return DownloadStatusResult(
                    found=True,
                    nzo_id=nzo_id,
                    name=slot.get("filename"),
                    status=slot.get("status"),
                    percentage=float(slot.get("percentage", 0)),
                    size_bytes=int(float(slot.get("mb", 0)) * 1024 * 1024),
                    size_left_bytes=int(float(slot.get("mbleft", 0)) * 1024 * 1024),
                    eta=slot.get("timeleft"),
                    category=slot.get("cat"),
                    labels=labels,
                    is_duplicate=is_dup,
                    in_history=False
                )

        return DownloadStatusResult(found=False, nzo_id=nzo_id)

    def _check_history_for_nzo(self, nzo_id: str) -> DownloadStatusResult:
        """Check SABnzbd history for a specific NZO ID"""
        raw_item = self._get_raw_history_item(nzo_id)
        if not raw_item:
            return DownloadStatusResult(found=False, nzo_id=nzo_id)

        status_str = raw_item.get("status", "")
        fail_msg = raw_item.get("fail_message", "")
        is_completed = status_str == "Completed"
        is_dup = "duplicate" in fail_msg.lower()

        # Resolve download path
        download_path = raw_item.get("storage", "")
        if not download_path:
            download_path = self._construct_download_path(raw_item)

        return DownloadStatusResult(
            found=True,
            nzo_id=nzo_id,
            name=raw_item.get("name"),
            status=status_str,
            percentage=100.0 if is_completed else 0.0,
            size_bytes=int(raw_item.get("bytes", 0)),
            download_path=download_path,
            category=raw_item.get("category"),
            fail_message=fail_msg if fail_msg else None,
            is_duplicate=is_dup,
            completed=is_completed,
            in_history=True,
            stage_log=raw_item.get("stage_log", [])
        )

    def _get_raw_history_item(self, nzo_id: str) -> Optional[Dict[str, Any]]:
        """Get raw history slot by NZO ID"""
        params = {"limit": 100}
        result = self._make_request("history", params)
        if not result or "history" not in result:
            return None

        for slot in result["history"].get("slots", []):
            if slot.get("nzo_id") == nzo_id:
                return slot

        return None

    def _construct_download_path(self, history_item: Dict[str, Any]) -> Optional[str]:
        """Construct download path from config when SABnzbd doesn't return storage path"""
        config = self.get_config()
        if not config:
            return None

        complete_dir = config.get("misc", {}).get("complete_dir")
        category = history_item.get("category", "")
        filename = history_item.get("name", "")

        if complete_dir and filename:
            import os
            if category:
                path = os.path.join(complete_dir, category, filename)
            else:
                path = os.path.join(complete_dir, filename)
            logger.info(f"[SABnzbd] Constructed download path: {path}")
            return path

        return None

    # ==================== QUEUE & HISTORY ====================

    def get_queue(self) -> List[Dict[str, Any]]:
        """Get current download queue with all slot details"""
        result = self._make_request("queue")
        if not result or "queue" not in result:
            return []

        downloads = []
        for slot in result["queue"].get("slots", []):
            downloads.append({
                "nzo_id": slot.get("nzo_id"),
                "filename": slot.get("filename"),
                "status": slot.get("status"),
                "percentage": float(slot.get("percentage", 0)),
                "size_mb": float(slot.get("mb", 0)),
                "size_left_mb": float(slot.get("mbleft", 0)),
                "eta": slot.get("timeleft"),
                "priority": slot.get("priority"),
                "category": slot.get("cat"),
                "labels": slot.get("labels", [])
            })

        return downloads

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get download history with full details"""
        params = {"limit": limit}
        result = self._make_request("history", params)
        if not result or "history" not in result:
            return []

        downloads = []
        for slot in result["history"].get("slots", []):
            downloads.append({
                "nzo_id": slot.get("nzo_id"),
                "name": slot.get("name"),
                "status": slot.get("status"),
                "size_bytes": int(slot.get("bytes", 0)),
                "download_path": slot.get("storage"),
                "download_time": int(slot.get("download_time", 0)),
                "completed_timestamp": int(slot.get("completed", 0)),
                "category": slot.get("category"),
                "fail_message": slot.get("fail_message", ""),
                "stage_log": slot.get("stage_log", []),
                "duplicate_key": slot.get("duplicate_key", "")
            })

        return downloads

    def get_history_item(self, nzo_id: str) -> Optional[Dict[str, Any]]:
        """Get specific history item by NZO ID (formatted)"""
        history = self.get_history(limit=100)
        for item in history:
            if item["nzo_id"] == nzo_id:
                return item
        return None

    def get_config(self) -> Optional[Dict[str, Any]]:
        """Get SABnzbd configuration"""
        result = self._make_request("get_config")
        if result and "config" in result:
            return result["config"]
        return None

    # ==================== DOWNLOAD MANAGEMENT ====================

    def pause_download(self, nzo_id: str) -> bool:
        """Pause specific download"""
        params = {"value": nzo_id}
        result = self._make_request("queue", params={"name": "pause", **params})
        if result and result.get("status"):
            logger.info(f"[SABnzbd] Paused download: {nzo_id}")
            return True
        return False

    def resume_download(self, nzo_id: str) -> bool:
        """Resume paused download"""
        params = {"value": nzo_id}
        result = self._make_request("queue", params={"name": "resume", **params})
        if result and result.get("status"):
            logger.info(f"[SABnzbd] Resumed download: {nzo_id}")
            return True
        return False

    def delete_download(self, nzo_id: str, delete_files: bool = False) -> bool:
        """Delete download from queue"""
        params = {"name": "delete", "value": nzo_id}
        if delete_files:
            params["del_files"] = 1
        result = self._make_request("queue", params)
        if result and result.get("status"):
            logger.info(f"[SABnzbd] Deleted from queue: {nzo_id}")
            return True
        return False

    def delete_history_item(self, nzo_id: str, delete_files: bool = False) -> bool:
        """Delete item from history"""
        params = {"name": "delete", "value": nzo_id}
        if delete_files:
            params["del_files"] = 1
        result = self._make_request("history", params)
        if result and result.get("status"):
            logger.info(f"[SABnzbd] Deleted from history: {nzo_id}")
            return True
        return False

    def retry_download(self, nzo_id: str) -> bool:
        """Retry a failed download from history"""
        result = self._make_request("retry", params={"value": nzo_id})
        if result and result.get("status"):
            logger.info(f"[SABnzbd] Retrying download: {nzo_id}")
            return True
        return False

    # ==================== INFO ====================

    def get_categories(self) -> List[str]:
        """Get list of available categories"""
        result = self._make_request("get_cats")
        if result and "categories" in result:
            return result["categories"]
        return []

    def test_connection(self) -> bool:
        """Test connection to SABnzbd"""
        result = self._make_request("version")
        if result and "version" in result:
            logger.info(f"[SABnzbd] Connected (version: {result['version']})")
            return True
        logger.error("[SABnzbd] Connection test failed")
        return False

    def get_server_stats(self) -> Optional[Dict[str, Any]]:
        """Get SABnzbd server statistics"""
        result = self._make_request("queue")
        if not result or "queue" not in result:
            return None

        queue_data = result["queue"]
        return {
            "speed_bytes_per_sec": float(queue_data.get("speed", 0)) * 1024,
            "size_left_mb": float(queue_data.get("mbleft", 0)),
            "total_size_mb": float(queue_data.get("mb", 0)),
            "disk_space_gb": float(queue_data.get("diskspace1", 0)),
            "download_dir": queue_data.get("download_dir"),
            "paused": queue_data.get("paused", False),
            "active_downloads": len(queue_data.get("slots", []))
        }


# Factory
def create_sabnzbd_client(base_url: str, api_key: str) -> SABnzbdClient:
    """Create SABnzbd client instance"""
    return SABnzbdClient(base_url, api_key)
