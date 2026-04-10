"""
Job Checkpoint Manager Service
Manage job checkpoints for safe pause/resume functionality.

Uses Redis for checkpoint storage (fast, persistent with RDB).
Also saves to file as backup (survives Redis restart).
"""
import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import redis, but allow graceful fallback
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using file-only checkpoints")


class JobCheckpointManager:
    """
    Manage job checkpoints for safe pause/resume functionality.

    Uses Redis for checkpoint storage (fast, persistent with RDB).
    Supports all job types with consistent interface.

    Usage:
        checkpoint_manager = JobCheckpointManager(job_id)

        # Save checkpoint
        checkpoint_manager.save_checkpoint({
            'last_processed_index': 100,
            'stats': {'processed': 100, 'failed': 5}
        })

        # Load checkpoint for resume
        checkpoint = checkpoint_manager.load_checkpoint()
        start_index = checkpoint.get('last_processed_index', 0)

        # Check for pause request
        if checkpoint_manager.is_pause_requested():
            checkpoint_manager.save_checkpoint({...})
            return {'status': 'paused'}

        # Clear on completion
        checkpoint_manager.clear_checkpoint()
    """

    CHECKPOINT_PREFIX = "job_checkpoint:"
    PAUSE_REQUEST_PREFIX = "job_pause_request:"
    CHECKPOINT_DIR = "/app/checkpoints"

    def __init__(self, job_id: str, redis_url: str = None):
        """
        Initialize checkpoint manager for a job.

        Args:
            job_id: Unique job identifier
            redis_url: Optional Redis URL (defaults to REDIS_URL env var)
        """
        self.job_id = str(job_id)
        self.checkpoint_key = f"{self.CHECKPOINT_PREFIX}{self.job_id}"
        self.pause_key = f"{self.PAUSE_REQUEST_PREFIX}{self.job_id}"

        # Initialize Redis client
        self.redis_client = None
        if REDIS_AVAILABLE:
            try:
                redis_url = redis_url or os.getenv('REDIS_URL', 'redis://studio54-redis:6379/0')
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                # Test connection
                self.redis_client.ping()
            except Exception as e:
                logger.warning(f"Could not connect to Redis: {e}, using file-only checkpoints")
                self.redis_client = None

        # Ensure checkpoint directory exists
        try:
            Path(self.CHECKPOINT_DIR).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create checkpoint directory: {e}")

    def save_checkpoint(self, checkpoint_data: Dict[str, Any]) -> bool:
        """
        Save checkpoint data for job.

        Checkpoint includes:
        - last_processed_index: Index of last successfully processed item
        - stats: Current statistics
        - timestamp: When checkpoint was saved
        - Additional job-specific data

        Args:
            checkpoint_data: Dictionary of checkpoint data

        Returns:
            True if saved successfully
        """
        checkpoint = {
            'job_id': self.job_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'data': checkpoint_data
        }

        success = False

        # Save to Redis (primary - fast)
        if self.redis_client:
            try:
                self.redis_client.set(
                    self.checkpoint_key,
                    json.dumps(checkpoint),
                    ex=86400 * 7  # Expire after 7 days
                )
                success = True
                logger.debug(f"Saved checkpoint to Redis for job {self.job_id}")
            except Exception as e:
                logger.error(f"Failed to save checkpoint to Redis for job {self.job_id}: {e}")

        # Also save to file (backup - survives Redis restart)
        try:
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint, f, indent=2)
            success = True
            logger.debug(f"Saved checkpoint to file for job {self.job_id}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint to file for job {self.job_id}: {e}")

        return success

    def load_checkpoint(self) -> Dict[str, Any]:
        """
        Load checkpoint data if exists.

        Returns:
            Checkpoint data dictionary, or empty dict if no checkpoint
        """
        # Try Redis first (most recent)
        if self.redis_client:
            try:
                data = self.redis_client.get(self.checkpoint_key)
                if data:
                    checkpoint = json.loads(data)
                    logger.info(f"Loaded checkpoint from Redis for job {self.job_id}")
                    return checkpoint.get('data', {})
            except Exception as e:
                logger.warning(f"Failed to load checkpoint from Redis: {e}")

        # Fallback to file
        try:
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            if checkpoint_file.exists():
                with open(checkpoint_file, 'r') as f:
                    checkpoint = json.load(f)
                    logger.info(f"Loaded checkpoint from file for job {self.job_id}")
                    return checkpoint.get('data', {})
        except Exception as e:
            logger.warning(f"Failed to load checkpoint from file: {e}")

        return {}

    def clear_checkpoint(self) -> bool:
        """
        Clear checkpoint after successful completion.

        Returns:
            True if cleared successfully
        """
        success = True

        # Clear from Redis
        if self.redis_client:
            try:
                self.redis_client.delete(self.checkpoint_key)
                logger.debug(f"Cleared checkpoint from Redis for job {self.job_id}")
            except Exception as e:
                logger.error(f"Failed to clear checkpoint from Redis: {e}")
                success = False

        # Clear file
        try:
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                logger.debug(f"Cleared checkpoint file for job {self.job_id}")
        except Exception as e:
            logger.error(f"Failed to clear checkpoint file: {e}")
            success = False

        return success

    def request_pause(self) -> bool:
        """
        Request job to pause at next safe point.

        The job should check is_pause_requested() periodically and
        save checkpoint before pausing.

        Returns:
            True if request was sent
        """
        if self.redis_client:
            try:
                self.redis_client.set(self.pause_key, "1", ex=3600)  # Expire in 1 hour
                logger.info(f"Pause requested for job {self.job_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to request pause: {e}")
                return False
        else:
            # Fallback to file-based pause request
            try:
                pause_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.pause"
                pause_file.touch()
                logger.info(f"Pause requested (file) for job {self.job_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to request pause (file): {e}")
                return False

    def is_pause_requested(self) -> bool:
        """
        Check if pause has been requested.

        Jobs should call this periodically (e.g., every N items)
        and pause gracefully if True.

        Returns:
            True if pause has been requested
        """
        # Check Redis
        if self.redis_client:
            try:
                if self.redis_client.exists(self.pause_key):
                    return True
            except Exception:
                pass

        # Check file fallback
        try:
            pause_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.pause"
            if pause_file.exists():
                return True
        except Exception:
            pass

        return False

    def clear_pause_request(self) -> bool:
        """
        Clear pause request (after pausing or resuming).

        Returns:
            True if cleared
        """
        success = True

        # Clear from Redis
        if self.redis_client:
            try:
                self.redis_client.delete(self.pause_key)
            except Exception as e:
                logger.error(f"Failed to clear pause request from Redis: {e}")
                success = False

        # Clear file
        try:
            pause_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.pause"
            if pause_file.exists():
                pause_file.unlink()
        except Exception as e:
            logger.error(f"Failed to clear pause request file: {e}")
            success = False

        return success

    def has_checkpoint(self) -> bool:
        """
        Check if checkpoint exists for resume.

        Returns:
            True if checkpoint exists
        """
        # Check Redis
        if self.redis_client:
            try:
                if self.redis_client.exists(self.checkpoint_key):
                    return True
            except Exception:
                pass

        # Check file
        try:
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            if checkpoint_file.exists():
                return True
        except Exception:
            pass

        return False

    def get_checkpoint_age_seconds(self) -> Optional[float]:
        """
        Get age of checkpoint in seconds.

        Returns:
            Age in seconds, or None if no checkpoint
        """
        checkpoint = self.load_checkpoint()
        if not checkpoint:
            return None

        # Get full checkpoint with timestamp
        if self.redis_client:
            try:
                data = self.redis_client.get(self.checkpoint_key)
                if data:
                    full_checkpoint = json.loads(data)
                    timestamp_str = full_checkpoint.get('timestamp')
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
                        return age
            except Exception:
                pass

        # Try file
        try:
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            if checkpoint_file.exists():
                with open(checkpoint_file, 'r') as f:
                    full_checkpoint = json.load(f)
                    timestamp_str = full_checkpoint.get('timestamp')
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
                        return age
        except Exception:
            pass

        return None


# Convenience functions for use without instantiating class

def request_job_pause(job_id: str) -> bool:
    """Request a job to pause"""
    return JobCheckpointManager(job_id).request_pause()


def is_job_pause_requested(job_id: str) -> bool:
    """Check if pause is requested for a job"""
    return JobCheckpointManager(job_id).is_pause_requested()


def has_job_checkpoint(job_id: str) -> bool:
    """Check if job has a checkpoint"""
    return JobCheckpointManager(job_id).has_checkpoint()


def get_job_checkpoint(job_id: str) -> Dict[str, Any]:
    """Get checkpoint data for a job"""
    return JobCheckpointManager(job_id).load_checkpoint()
