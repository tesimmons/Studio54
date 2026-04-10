"""
AcoustID Fingerprint Service for Studio54

Provides audio fingerprinting and AcoustID lookup functionality.
Rate limited separately from MusicBrainz API (3 req/sec vs 1 req/sec).
"""

import json
import logging
import os
import subprocess
import threading
import time
from typing import Dict, List, Any, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Quality ranking for format comparison
# Higher number = better quality
FORMAT_QUALITY_RANK = {
    "FLAC": 100,
    "WAV": 90,
    "ALAC": 85,
    "M4A": 80,  # Usually AAC, could be ALAC — treat as mid-tier
    "OGG": 50,
    "MP3": 40,
    "WMA": 30,
}

# Minimum bitrate (kbps) thresholds for MP3/lossy
HIGH_BITRATE_THRESHOLD = 320
MID_BITRATE_THRESHOLD = 256


class AcoustIDService:
    """
    AcoustID client with rate limiting (3 req/sec).
    Separate from MusicBrainz client which has its own 1 req/sec limit.
    """

    BASE_URL = "https://api.acoustid.org/v2/lookup"
    USER_AGENT = "Studio54/1.0 ( https://github.com/tesimmons/MasterControl )"
    MIN_REQUEST_INTERVAL = 0.34  # ~3 requests per second

    def __init__(self):
        self.api_key = os.getenv("ACOUSTID_API_KEY")
        if not self.api_key:
            logger.warning("ACOUSTID_API_KEY not set — fingerprint lookups will fail")
        self._last_request_time = 0.0
        self._lock = threading.Lock()

    def _rate_limit(self):
        """Enforce AcoustID rate limit (3 req/sec) — independent of MB rate limit."""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_time = time.time()

    def fingerprint_file(self, file_path: str) -> Optional[Tuple[str, int]]:
        """
        Run fpcalc on an audio file to get its Chromaprint fingerprint.

        Returns:
            (fingerprint_string, duration_seconds) or None on failure.
        """
        try:
            # Get file size for logging
            try:
                fsize = os.path.getsize(file_path)
            except OSError:
                fsize = -1

            result = subprocess.run(
                ["fpcalc", "-json", "-length", "120", file_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    f"fpcalc failed (rc={result.returncode}) for {file_path} "
                    f"(size={fsize}): stderr={result.stderr.strip()}"
                )
                return None

            data = json.loads(result.stdout)
            fp = data["fingerprint"]
            dur = int(data["duration"])
            logger.info(
                f"fpcalc success: file={file_path}, size={fsize}, "
                f"duration={dur}s, fingerprint_length={len(fp)}"
            )
            return fp, dur
        except subprocess.TimeoutExpired:
            logger.debug(f"fpcalc timed out for {file_path}")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"fpcalc parse error for {file_path}: {e}")
            return None

    def lookup(self, fingerprint: str, duration: int) -> List[Dict[str, Any]]:
        """
        Look up a fingerprint on AcoustID.

        Returns list of results sorted by score (highest first).
        Each result has 'score' and 'recordings' list with 'id' (recording MBID).
        """
        if not self.api_key:
            return []

        self._rate_limit()

        try:
            resp = requests.post(
                self.BASE_URL,
                data={
                    "client": self.api_key,
                    "duration": duration,
                    "fingerprint": fingerprint,
                    "meta": "recordings releasegroups",
                },
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"AcoustID API error: {e}")
            return []

        if data.get("status") != "ok":
            error_msg = data.get("error", {}).get("message", "unknown")
            logger.warning(f"AcoustID error response: status={data.get('status')}, error={error_msg}")
            return []

        results = data.get("results", [])
        logger.info(
            f"AcoustID lookup: status=ok, {len(results)} results for "
            f"duration={duration}s, fingerprint_len={len(fingerprint)}"
        )
        if not results:
            logger.info(f"AcoustID lookup: no results — fingerprint may not be in database")
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results

    def are_same_recording(
        self,
        file_path_a: str,
        file_path_b: str,
        min_score: float = 0.80,
    ) -> Tuple[bool, float]:
        """
        Determine if two audio files are the same recording using AcoustID.

        Fingerprints both files, looks up each on AcoustID, and checks if they
        share a common MusicBrainz recording ID with sufficient confidence.

        Returns:
            (is_same, confidence_score)
        """
        fp_a = self.fingerprint_file(file_path_a)
        fp_b = self.fingerprint_file(file_path_b)
        if not fp_a or not fp_b:
            return False, 0.0

        results_a = self.lookup(fp_a[0], fp_a[1])
        results_b = self.lookup(fp_b[0], fp_b[1])

        # Collect recording MBIDs from each
        mbids_a = set()
        best_score_a = 0.0
        for r in results_a:
            score = r.get("score", 0)
            if score < min_score:
                continue
            best_score_a = max(best_score_a, score)
            for rec in r.get("recordings", []):
                if rec.get("id"):
                    mbids_a.add(rec["id"])

        mbids_b = set()
        best_score_b = 0.0
        for r in results_b:
            score = r.get("score", 0)
            if score < min_score:
                continue
            best_score_b = max(best_score_b, score)
            for rec in r.get("recordings", []):
                if rec.get("id"):
                    mbids_b.add(rec["id"])

        # Check for overlap
        common = mbids_a & mbids_b
        if common:
            return True, min(best_score_a, best_score_b)
        return False, 0.0


def compute_quality_score(
    fmt: Optional[str],
    bitrate_kbps: Optional[int],
    sample_rate_hz: Optional[int] = None,
    file_size_bytes: Optional[int] = None,
) -> int:
    """
    Compute a numeric quality score for an audio file.

    Priority: FLAC > WAV > ALAC > 320 MP3 > 256+ > rest
    Within same format, higher bitrate wins.
    Within same bitrate, higher sample rate wins.

    Returns an integer score (higher = better quality).
    """
    fmt_upper = (fmt or "").upper().strip()
    base = FORMAT_QUALITY_RANK.get(fmt_upper, 20)

    # For lossless formats, base score is already high
    # Add sample rate bonus for lossless (e.g., 96kHz FLAC > 44.1kHz FLAC)
    if base >= 80:  # Lossless
        sr_bonus = (sample_rate_hz or 44100) // 1000  # e.g., 44 for 44100, 96 for 96000
        return base * 1000 + sr_bonus

    # For lossy formats, bitrate is the primary differentiator
    br = bitrate_kbps or 128
    if br >= HIGH_BITRATE_THRESHOLD:
        return base * 1000 + br
    elif br >= MID_BITRATE_THRESHOLD:
        return (base - 5) * 1000 + br
    else:
        return (base - 10) * 1000 + br


def compare_quality(
    fmt_a: Optional[str], bitrate_a: Optional[int], sr_a: Optional[int],
    fmt_b: Optional[str], bitrate_b: Optional[int], sr_b: Optional[int],
) -> int:
    """
    Compare quality of two audio files.

    Returns:
        > 0 if A is better quality
        < 0 if B is better quality
        0 if equal
    """
    score_a = compute_quality_score(fmt_a, bitrate_a, sr_a)
    score_b = compute_quality_score(fmt_b, bitrate_b, sr_b)
    return score_a - score_b


# Singleton
_instance = None


def get_acoustid_service() -> AcoustIDService:
    """Get singleton AcoustIDService (rate limited at 3 req/sec, separate from MB)."""
    global _instance
    if _instance is None:
        _instance = AcoustIDService()
    return _instance
