"""
Logging Configuration Service

Manages logging levels across multiple uvicorn workers using Redis for
shared state and SIGUSR1 signals for broadcasting changes.

Usage:
    from app.services.logging_config import LoggingConfigService

    # On startup
    logging_config = LoggingConfigService()
    logging_config.initialize()

    # To change logging level (broadcasts to all workers)
    logging_config.set_level("root", "DEBUG")
"""

import logging
import logging.handlers
import signal
import os
import json
import threading
from collections import deque
from typing import Dict, Optional, List
import redis

logger = logging.getLogger(__name__)

# Redis key for storing logging configuration
REDIS_LOGGING_KEY = "studio54:logging:levels"
REDIS_WORKER_PIDS_KEY = "studio54:logging:worker_pids"

# Default logging levels
DEFAULT_LOGGING_LEVELS = {
    "root": "WARNING",
    "app": "INFO",
    "uvicorn": "INFO",
    "uvicorn.access": "WARNING",
    "uvicorn.error": "INFO",
    "sqlalchemy": "WARNING",
    "httpx": "WARNING",
    "celery": "INFO",
}


class LoggingConfigService:
    """
    Manages logging configuration across multiple uvicorn workers.

    Uses Redis to store logging levels and SIGUSR1 signals to notify
    workers when levels change.
    """

    _instance: Optional['LoggingConfigService'] = None
    _redis_client: Optional[redis.Redis] = None

    def __new__(cls):
        """Singleton pattern to ensure one instance per worker"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._worker_pid = os.getpid()

    def _get_redis(self) -> redis.Redis:
        """Get Redis client, creating if necessary"""
        if self._redis_client is None:
            from app.config import settings
            self._redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True
            )
        return self._redis_client

    def initialize(self):
        """
        Initialize the logging config service.

        - Installs the ring buffer handler for live log viewing
        - Registers this worker's PID
        - Sets up SIGUSR1 signal handler
        - Loads and applies current logging levels from Redis
        """
        try:
            # Install ring buffer handler for live log viewing
            get_ring_handler()

            r = self._get_redis()

            # Register this worker's PID
            r.sadd(REDIS_WORKER_PIDS_KEY, str(self._worker_pid))

            # Set up signal handler for SIGUSR1
            signal.signal(signal.SIGUSR1, self._handle_reload_signal)

            # Load and apply current levels from Redis (or set defaults)
            levels = self._load_levels_from_redis()
            if not levels:
                # First worker to start - set defaults
                self._save_levels_to_redis(DEFAULT_LOGGING_LEVELS)
                levels = DEFAULT_LOGGING_LEVELS

            self._apply_logging_levels(levels)

            logger.info(f"LoggingConfigService initialized for worker PID {self._worker_pid}")

        except Exception as e:
            logger.error(f"Failed to initialize LoggingConfigService: {e}")

    def cleanup(self):
        """Remove this worker's PID from Redis on shutdown"""
        try:
            r = self._get_redis()
            r.srem(REDIS_WORKER_PIDS_KEY, str(self._worker_pid))
            logger.info(f"LoggingConfigService cleanup for worker PID {self._worker_pid}")
        except Exception as e:
            logger.error(f"Failed to cleanup LoggingConfigService: {e}")

    def _load_levels_from_redis(self) -> Dict[str, str]:
        """Load logging levels from Redis"""
        try:
            r = self._get_redis()
            data = r.get(REDIS_LOGGING_KEY)
            if data:
                return json.loads(data)
            return {}
        except Exception as e:
            logger.error(f"Failed to load logging levels from Redis: {e}")
            return {}

    def _save_levels_to_redis(self, levels: Dict[str, str]):
        """Save logging levels to Redis"""
        try:
            r = self._get_redis()
            r.set(REDIS_LOGGING_KEY, json.dumps(levels))
        except Exception as e:
            logger.error(f"Failed to save logging levels to Redis: {e}")

    def _apply_logging_levels(self, levels: Dict[str, str]):
        """Apply logging levels to Python logging system"""
        for service_name, level_name in levels.items():
            try:
                level = getattr(logging, level_name.upper(), logging.INFO)

                if service_name.lower() == "root":
                    logging.getLogger().setLevel(level)
                else:
                    logging.getLogger(service_name).setLevel(level)

            except Exception as e:
                logger.error(f"Failed to set logging level for {service_name}: {e}")

    def _handle_reload_signal(self, signum, frame):
        """Signal handler for SIGUSR1 - reload logging levels from Redis"""
        try:
            levels = self._load_levels_from_redis()
            if levels:
                self._apply_logging_levels(levels)
                logger.info(f"Worker {self._worker_pid} reloaded logging levels from Redis")
        except Exception as e:
            logger.error(f"Error handling reload signal: {e}")

    def set_level(self, service: str, level: str) -> bool:
        """
        Set logging level for a service and broadcast to all workers.

        Args:
            service: Logger name (e.g., 'root', 'app', 'uvicorn')
            level: Log level (e.g., 'DEBUG', 'INFO', 'WARNING')

        Returns:
            True if successful, False otherwise
        """
        try:
            # Load current levels
            levels = self._load_levels_from_redis()
            if not levels:
                levels = DEFAULT_LOGGING_LEVELS.copy()

            # Update the level
            levels[service.lower() if service.lower() != "root" else "root"] = level.upper()

            # Save to Redis
            self._save_levels_to_redis(levels)

            # Apply locally
            self._apply_logging_levels({service: level})

            # Broadcast to other workers
            self._broadcast_reload_signal()

            return True

        except Exception as e:
            logger.error(f"Failed to set logging level: {e}")
            return False

    def _broadcast_reload_signal(self):
        """Send SIGUSR1 to all registered worker PIDs"""
        try:
            r = self._get_redis()
            worker_pids = r.smembers(REDIS_WORKER_PIDS_KEY)

            current_pid = str(self._worker_pid)

            for pid_str in worker_pids:
                pid = int(pid_str)

                # Skip current process (we already applied locally)
                if pid_str == current_pid:
                    continue

                try:
                    # Check if process exists before sending signal
                    os.kill(pid, 0)  # This raises OSError if process doesn't exist
                    os.kill(pid, signal.SIGUSR1)
                    logger.debug(f"Sent SIGUSR1 to worker PID {pid}")
                except OSError:
                    # Process doesn't exist, remove from set
                    r.srem(REDIS_WORKER_PIDS_KEY, pid_str)
                    logger.debug(f"Removed stale worker PID {pid}")
                except Exception as e:
                    logger.error(f"Failed to send signal to PID {pid}: {e}")

        except Exception as e:
            logger.error(f"Failed to broadcast reload signal: {e}")

    def get_levels(self) -> Dict[str, str]:
        """Get current logging levels from Redis"""
        levels = self._load_levels_from_redis()
        if not levels:
            return DEFAULT_LOGGING_LEVELS.copy()
        return levels

    def reset_to_defaults(self):
        """Reset all logging levels to defaults"""
        self._save_levels_to_redis(DEFAULT_LOGGING_LEVELS)
        self._apply_logging_levels(DEFAULT_LOGGING_LEVELS)
        self._broadcast_reload_signal()

    def get_effective_levels(self) -> List[Dict]:
        """
        Get effective logging levels for all loggers.

        Returns list of dicts with service, level, and effective_level.
        """
        loggers_to_check = [
            "root", "app", "uvicorn", "uvicorn.access",
            "uvicorn.error", "sqlalchemy", "celery", "httpx"
        ]

        result = []
        for logger_name in loggers_to_check:
            if logger_name == "root":
                log_obj = logging.getLogger()
            else:
                log_obj = logging.getLogger(logger_name)

            result.append({
                "service": logger_name,
                "level": logging.getLevelName(log_obj.level),
                "effective_level": log_obj.level
            })

        return result


# ── In-memory ring buffer for live log viewing ──

class RingBufferHandler(logging.Handler):
    """A logging handler that keeps the last N log records in memory."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.buffer: deque = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            with self._lock:
                self.buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_lines(self, count: int = 500, level_filter: Optional[str] = None,
                  logger_filter: Optional[str] = None) -> List[str]:
        """Get recent log lines, optionally filtered."""
        with self._lock:
            lines = list(self.buffer)

        if logger_filter:
            lines = [l for l in lines if logger_filter in l]

        if level_filter:
            level_upper = level_filter.upper()
            lines = [l for l in lines if level_upper in l]

        return lines[-count:]


# Singleton handler attached to root logger
_ring_handler: Optional[RingBufferHandler] = None


def get_ring_handler() -> RingBufferHandler:
    """Get or create the global ring buffer handler."""
    global _ring_handler
    if _ring_handler is None:
        _ring_handler = RingBufferHandler(capacity=2000)
        _ring_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        _ring_handler.setFormatter(formatter)
        # Attach to root logger so it captures everything
        logging.getLogger().addHandler(_ring_handler)
    return _ring_handler


# Global instance
_logging_config_service: Optional[LoggingConfigService] = None


def get_logging_config_service() -> LoggingConfigService:
    """Get the global LoggingConfigService instance"""
    global _logging_config_service
    if _logging_config_service is None:
        _logging_config_service = LoggingConfigService()
    return _logging_config_service
