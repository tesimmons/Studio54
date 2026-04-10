"""
Distributed Rate Limiter using Redis

Provides distributed rate limiting across multiple processes/workers using Redis.
Ensures external API rate limits (like MusicBrainz) are properly enforced.
"""
import time
import redis
from typing import Optional
from app.config import settings


class DistributedRateLimiter:
    """
    Redis-based distributed rate limiter

    Ensures only N requests per time window across all workers/processes.
    Uses Redis atomic operations (INCR + EXPIRE) for coordination.
    """

    def __init__(self, redis_url: str, service_name: str, requests_per_second: float = 1.0):
        """
        Initialize rate limiter

        Args:
            redis_url: Redis connection URL
            service_name: Unique name for this rate limiter (e.g., "musicbrainz")
            requests_per_second: Maximum requests allowed per second
        """
        self.redis_client = redis.from_url(redis_url)
        self.service_name = service_name
        self.min_interval = 1.0 / requests_per_second  # Minimum seconds between requests
        self.key_prefix = f"ratelimit:{service_name}"

    def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire rate limit permission (blocks until available)

        Args:
            timeout: Maximum seconds to wait for permission

        Returns:
            True if permission acquired, False if timeout
        """
        start_time = time.time()

        while True:
            # Try to acquire
            if self._try_acquire():
                return True

            # Check timeout
            if time.time() - start_time >= timeout:
                return False

            # Wait a bit before retrying (50ms intervals)
            time.sleep(0.05)

    def _try_acquire(self) -> bool:
        """
        Try to acquire rate limit permission (non-blocking)

        Uses Redis SETNX (set if not exists) with TTL for distributed coordination.

        Returns:
            True if permission acquired, False if rate limited
        """
        current_time = time.time()
        key = f"{self.key_prefix}:last_request"

        # Get last request timestamp
        last_request_time_str = self.redis_client.get(key)

        if last_request_time_str:
            last_request_time = float(last_request_time_str)
            time_since_last = current_time - last_request_time

            if time_since_last < self.min_interval:
                # Rate limited - need to wait
                return False

        # Try to set new timestamp atomically
        # Use SET with NX (only if not exists) and EX (expiry)
        # This prevents race conditions
        new_timestamp = str(current_time)
        expiry_seconds = int(self.min_interval * 2)  # Keep for 2x interval for safety

        # Use Lua script for atomic get-check-set operation
        lua_script = """
        local key = KEYS[1]
        local new_timestamp = ARGV[1]
        local min_interval = tonumber(ARGV[2])
        local expiry = tonumber(ARGV[3])

        local last_timestamp = redis.call('GET', key)

        if last_timestamp then
            local time_since_last = tonumber(new_timestamp) - tonumber(last_timestamp)
            if time_since_last < min_interval then
                return 0  -- Rate limited
            end
        end

        redis.call('SET', key, new_timestamp, 'EX', expiry)
        return 1  -- Acquired
        """

        result = self.redis_client.eval(
            lua_script,
            1,  # Number of keys
            key,  # KEYS[1]
            new_timestamp,  # ARGV[1]
            self.min_interval,  # ARGV[2]
            expiry_seconds  # ARGV[3]
        )

        return bool(result)

    def wait(self, timeout: float = 30.0):
        """
        Wait for rate limit permission (blocking)

        Args:
            timeout: Maximum seconds to wait

        Raises:
            TimeoutError: If timeout is reached
        """
        if not self.acquire(timeout):
            raise TimeoutError(f"Rate limit timeout after {timeout}s")


# Singleton instances
_musicbrainz_limiter: Optional[DistributedRateLimiter] = None


def get_musicbrainz_rate_limiter() -> DistributedRateLimiter:
    """
    Get MusicBrainz rate limiter singleton (1 request/second)

    Returns:
        Shared DistributedRateLimiter for MusicBrainz API
    """
    global _musicbrainz_limiter
    if _musicbrainz_limiter is None:
        _musicbrainz_limiter = DistributedRateLimiter(
            redis_url=settings.redis_url,
            service_name="musicbrainz",
            requests_per_second=1.0  # 1 req/s for anonymous clients
        )
    return _musicbrainz_limiter
