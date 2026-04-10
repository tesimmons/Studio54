"""
Checkpointable Task Mixin
Base task class with checkpoint/pause support for all Celery tasks.

Provides consistent checkpoint/resume functionality across all job types.
"""
import logging
from typing import Dict, Any, Optional
from celery import Task

from app.services.job_checkpoint_manager import JobCheckpointManager

logger = logging.getLogger(__name__)


class CheckpointableTask(Task):
    """
    Base task class with checkpoint/pause support.

    Provides methods for:
    - Saving/loading checkpoints
    - Checking for pause requests
    - Resuming from saved state

    Usage:
        @shared_task(bind=True, base=CheckpointableTask)
        def my_task(self, job_id: str):
            # Initialize checkpoint manager
            self.init_checkpoint(job_id)

            # Load checkpoint for resume
            checkpoint = self.load_checkpoint()
            start_index = checkpoint.get('last_processed_index', 0)

            for i, item in enumerate(items):
                # Skip already processed (resume)
                if i < start_index:
                    continue

                # Check for pause request
                if self.should_pause():
                    self.save_checkpoint_and_pause({
                        'last_processed_index': i,
                        'stats': stats
                    })
                    return {'status': 'paused', 'index': i}

                # Process item...

                # Save checkpoint periodically
                if i % 100 == 0:
                    self.save_checkpoint({
                        'last_processed_index': i,
                        'stats': stats
                    })

            # Clear checkpoint on successful completion
            self.clear_checkpoint()
            return {'status': 'completed'}
    """

    # Task-level attributes (reset for each task instance)
    _checkpoint_manager: Optional[JobCheckpointManager] = None
    _job_id: Optional[str] = None

    def init_checkpoint(self, job_id: str) -> None:
        """
        Initialize checkpoint manager for this task.

        Must be called at the start of the task before using
        other checkpoint methods.

        Args:
            job_id: The job ID to track checkpoints for
        """
        self._job_id = str(job_id)
        self._checkpoint_manager = JobCheckpointManager(job_id)
        logger.debug(f"Initialized checkpoint manager for job {job_id}")

    def load_checkpoint(self) -> Dict[str, Any]:
        """
        Load existing checkpoint data for resume.

        Returns:
            Checkpoint data dict, or empty dict if no checkpoint
        """
        if self._checkpoint_manager:
            checkpoint = self._checkpoint_manager.load_checkpoint()
            if checkpoint:
                logger.info(f"Loaded checkpoint for job {self._job_id}: {checkpoint.get('last_processed_index', 'N/A')}")
            return checkpoint
        return {}

    def save_checkpoint(self, data: Dict[str, Any]) -> bool:
        """
        Save checkpoint data.

        Should be called periodically (e.g., every 100 items) to
        allow resume from recent state on failure.

        Args:
            data: Checkpoint data to save (must include 'last_processed_index')

        Returns:
            True if saved successfully
        """
        if self._checkpoint_manager:
            return self._checkpoint_manager.save_checkpoint(data)
        logger.warning("Cannot save checkpoint: checkpoint manager not initialized")
        return False

    def clear_checkpoint(self) -> bool:
        """
        Clear checkpoint after successful completion.

        Call this when task completes successfully to clean up
        checkpoint data.

        Returns:
            True if cleared successfully
        """
        if self._checkpoint_manager:
            return self._checkpoint_manager.clear_checkpoint()
        return False

    def should_pause(self) -> bool:
        """
        Check if pause has been requested.

        Call this periodically (e.g., at start of each item processing)
        to check if user has requested pause.

        Returns:
            True if pause has been requested
        """
        if self._checkpoint_manager:
            return self._checkpoint_manager.is_pause_requested()
        return False

    def save_checkpoint_and_pause(self, data: Dict[str, Any]) -> bool:
        """
        Save checkpoint and clear pause request.

        Call this when pausing to save state before returning.

        Args:
            data: Checkpoint data to save

        Returns:
            True if saved successfully
        """
        if self._checkpoint_manager:
            # Save checkpoint
            saved = self._checkpoint_manager.save_checkpoint(data)
            # Clear pause request
            self._checkpoint_manager.clear_pause_request()
            logger.info(f"Job {self._job_id} paused at checkpoint: {data.get('last_processed_index', 'N/A')}")
            return saved
        return False

    def has_checkpoint(self) -> bool:
        """
        Check if checkpoint exists for resume.

        Returns:
            True if checkpoint exists
        """
        if self._checkpoint_manager:
            return self._checkpoint_manager.has_checkpoint()
        return False

    def request_pause(self) -> bool:
        """
        Request this task to pause (usually called externally via API).

        Returns:
            True if request was sent
        """
        if self._checkpoint_manager:
            return self._checkpoint_manager.request_pause()
        return False


def with_checkpoint_support(task_func):
    """
    Decorator to add checkpoint support to existing task functions.

    Usage:
        @shared_task(bind=True)
        @with_checkpoint_support
        def my_task(self, job_id: str, checkpoint_manager: JobCheckpointManager):
            # checkpoint_manager is injected
            checkpoint = checkpoint_manager.load_checkpoint()
            ...
    """
    def wrapper(self, job_id: str, *args, **kwargs):
        # Create checkpoint manager
        checkpoint_manager = JobCheckpointManager(job_id)

        # Inject into task
        return task_func(self, job_id, checkpoint_manager=checkpoint_manager, *args, **kwargs)

    wrapper.__name__ = task_func.__name__
    wrapper.__doc__ = task_func.__doc__
    return wrapper
