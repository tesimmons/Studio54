"""
MUSE Ponder Client Service
Client for calling MUSE Ponder API for audio fingerprint identification.

Ponder uses AcoustID/Chromaprint for audio fingerprinting to identify
recordings that can't be matched by metadata alone.
"""
import os
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


# Retry decorator for transient network errors
def _retry_on_network_error():
    """Create retry decorator for network operations"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


class PonderClientError(Exception):
    """Exception for Ponder client errors"""
    pass


class PonderClient:
    """
    Client for MUSE Ponder API

    Provides methods to:
    - Identify files using audio fingerprinting
    - Start batch identification jobs
    - Monitor job progress
    - Retrieve identification results

    Configuration via environment variables:
    - MUSE_SERVICE_URL: Base URL for MUSE service (default: http://muse-service:8007)
    - MUSE_API_KEY: Optional API key for authentication
    """

    DEFAULT_URL = "http://muse-service:8007"
    API_PREFIX = "/api/v1"
    DEFAULT_TIMEOUT = 30.0  # seconds
    POLLING_INTERVAL = 5.0  # seconds

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT
    ):
        """
        Initialize Ponder client.

        Args:
            base_url: MUSE service URL (default from env or http://muse-service:8007)
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or os.getenv("MUSE_SERVICE_URL", self.DEFAULT_URL)
        self.api_key = api_key or os.getenv("MUSE_API_KEY")
        self.timeout = timeout

        # Build headers
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.api_key:
            self.headers["X-API-Key"] = self.api_key

        logger.info(f"Initialized PonderClient with base_url={self.base_url}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make HTTP request to Ponder API with automatic retry on transient errors.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without prefix)
            **kwargs: Additional arguments for httpx request

        Returns:
            Response JSON as dict

        Raises:
            PonderClientError: On request failure
        """
        url = f"{self.base_url}{self.API_PREFIX}{endpoint}"

        try:
            return self._execute_request_with_retry(method, url, **kwargs)
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.json().get("detail", "")
            except Exception:
                error_detail = e.response.text
            raise PonderClientError(
                f"Ponder API error ({e.response.status_code}): {error_detail}"
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise PonderClientError(f"Ponder request failed after retries: {e}")
        except httpx.RequestError as e:
            raise PonderClientError(f"Ponder request failed: {e}")

    @_retry_on_network_error()
    def _execute_request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute HTTP request with retry logic"""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(
                method,
                url,
                headers=self.headers,
                **kwargs
            )
            response.raise_for_status()
            return response.json()

    def health_check(self) -> bool:
        """
        Check if MUSE Ponder service is available.

        Returns:
            True if service is healthy
        """
        try:
            # Try to get root endpoint
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    def identify_file(
        self,
        file_path: str,
        use_fingerprint: bool = True,
        overwrite_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Identify a single file using Ponder.

        Uses multi-step strategy:
        1. Check for existing MBID in file comment
        2. Try AcoustID fingerprint lookup (if enabled)
        3. Fall back to metadata-based search

        Args:
            file_path: Full path to audio file
            use_fingerprint: Whether to use audio fingerprinting
            overwrite_existing: Whether to overwrite existing tags

        Returns:
            Identification result dict:
            - success: bool
            - match_method: str (mbid_in_file, acoustid, metadata_search)
            - match_score: int (0-100)
            - recording_mbid: str (if found)
            - artist_mbid: str (if found)
            - tags_written: list (tags that were written)
            - original_tags: dict
            - new_tags: dict
            - error: str (if failed)
        """
        # We need to find the file_id from MUSE's perspective
        # For now, we'll use a direct file-based endpoint if available
        # or search by file_path

        # Try the direct file path approach
        try:
            result = self._make_request(
                "POST",
                "/ponder/identify-path",
                params={
                    "file_path": file_path,
                    "use_fingerprint": use_fingerprint,
                    "overwrite_existing": overwrite_existing
                }
            )
            return result
        except PonderClientError as e:
            # If endpoint doesn't exist, try alternative
            if "404" in str(e):
                logger.warning(f"Ponder identify-path endpoint not found, using file search")
                return self._identify_file_via_search(file_path, use_fingerprint, overwrite_existing)
            raise

    def _identify_file_via_search(
        self,
        file_path: str,
        use_fingerprint: bool = True,
        overwrite_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Identify file by searching MUSE database for matching file_path.

        Args:
            file_path: Path to file
            use_fingerprint: Use audio fingerprinting
            overwrite_existing: Overwrite existing tags

        Returns:
            Identification result
        """
        # Search for file in MUSE
        try:
            search_result = self._make_request(
                "GET",
                "/files/search",
                params={"path": file_path}
            )

            if not search_result.get("files"):
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": "File not found in MUSE database",
                    "match_method": None,
                    "match_score": 0
                }

            # Get file_id from search result
            file_id = search_result["files"][0]["id"]

            # Call Ponder fix-tags endpoint
            result = self._make_request(
                "POST",
                f"/ponder/fix-tags/{file_id}",
                params={
                    "use_fingerprint": use_fingerprint,
                    "overwrite_existing": overwrite_existing
                }
            )
            return result

        except PonderClientError as e:
            return {
                "success": False,
                "file_path": file_path,
                "error": str(e),
                "match_method": None,
                "match_score": 0
            }

    def start_library_identification(
        self,
        library_id: str,
        use_fingerprint: bool = True,
        overwrite_existing: bool = False,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Start batch identification for all files in a MUSE library.

        Args:
            library_id: MUSE library UUID
            use_fingerprint: Use audio fingerprinting
            overwrite_existing: Overwrite existing tags
            limit: Maximum files to process

        Returns:
            Job info dict:
            - job_id: str
            - task_id: str
            - status: str
            - progress_endpoint: str
        """
        params = {
            "use_fingerprint": use_fingerprint,
            "overwrite_existing": overwrite_existing
        }
        if limit:
            params["limit"] = limit

        result = self._make_request(
            "POST",
            f"/ponder/fix-tags/library/{library_id}",
            params=params
        )
        return result

    def get_job_progress(self, job_id: str) -> Dict[str, Any]:
        """
        Get progress of a Ponder job.

        Args:
            job_id: Ponder job UUID

        Returns:
            Progress dict:
            - job_id: str
            - status: str (queued, running, completed, failed, cancelled, paused)
            - total_files: int
            - current_file: int
            - success_count: int
            - failed_count: int
            - percent_complete: int
        """
        return self._make_request("GET", f"/ponder/jobs/{job_id}/progress")

    def wait_for_job(
        self,
        job_id: str,
        timeout_seconds: int = 3600,
        callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Wait for a Ponder job to complete.

        Args:
            job_id: Job UUID
            timeout_seconds: Maximum wait time
            callback: Optional callback function called with progress updates

        Returns:
            Final job status

        Raises:
            PonderClientError: On timeout or job failure
        """
        start_time = time.time()

        while True:
            progress = self.get_job_progress(job_id)

            if callback:
                callback(progress)

            status = progress.get("status", "")

            if status == "completed":
                return progress
            elif status in ["failed", "cancelled"]:
                raise PonderClientError(f"Job {status}: {progress.get('error', 'Unknown error')}")

            if time.time() - start_time > timeout_seconds:
                raise PonderClientError(f"Job timed out after {timeout_seconds} seconds")

            time.sleep(self.POLLING_INTERVAL)

    def get_job_report(
        self,
        job_id: str,
        failures_only: bool = False
    ) -> Dict[str, Any]:
        """
        Get detailed report of a Ponder job.

        Args:
            job_id: Job UUID
            failures_only: Only include failed files

        Returns:
            Report dict with per-file results
        """
        params = {"failures_only": failures_only}
        return self._make_request("GET", f"/ponder/jobs/{job_id}/report", params=params)

    def get_job_summary(self, job_id: str) -> Dict[str, Any]:
        """
        Get summary of a Ponder job.

        Args:
            job_id: Job UUID

        Returns:
            Summary dict with statistics and match breakdowns
        """
        return self._make_request("GET", f"/ponder/jobs/{job_id}/summary")

    def pause_job(self, job_id: str) -> Dict[str, Any]:
        """
        Pause a running Ponder job.

        Args:
            job_id: Job UUID

        Returns:
            Pause confirmation with current progress
        """
        return self._make_request("POST", f"/ponder/jobs/{job_id}/pause")

    def resume_job(self, job_id: str) -> Dict[str, Any]:
        """
        Resume a paused/failed Ponder job.

        Args:
            job_id: Job UUID

        Returns:
            Resume confirmation with new task ID
        """
        return self._make_request("POST", f"/ponder/jobs/{job_id}/resume")

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """
        Cancel a running Ponder job.

        Args:
            job_id: Job UUID

        Returns:
            Cancellation confirmation
        """
        return self._make_request("POST", f"/ponder/jobs/{job_id}/cancel")

    def get_failed_files(self, job_id: str) -> Dict[str, Any]:
        """
        Get list of files that failed identification.

        Args:
            job_id: Job UUID

        Returns:
            Failed files list with error details
        """
        return self._make_request("GET", f"/ponder/jobs/{job_id}/failed-files")


# Singleton instance
_ponder_client: Optional[PonderClient] = None


def get_ponder_client() -> PonderClient:
    """
    Get or create singleton PonderClient instance.

    Returns:
        PonderClient instance
    """
    global _ponder_client
    if _ponder_client is None:
        _ponder_client = PonderClient()
    return _ponder_client


def identify_file_with_ponder(
    file_path: str,
    use_fingerprint: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to identify a file using Ponder.

    Args:
        file_path: Path to audio file
        use_fingerprint: Use audio fingerprinting

    Returns:
        Identification result
    """
    client = get_ponder_client()
    return client.identify_file(file_path, use_fingerprint)
