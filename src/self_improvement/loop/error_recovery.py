"""
Error recovery strategy for M5 Self-Improvement Loop.

Implements intelligent retry logic, backoff, and recovery actions.
"""
import logging
import time
from typing import Optional

from .models import Phase, RecoveryAction
from .config import LoopConfig

logger = logging.getLogger(__name__)


class ErrorRecoveryStrategy:
    """
    Implement error recovery with retry logic and backoff.

    Determines whether errors are transient or permanent, and decides
    on appropriate recovery actions (retry, skip, rollback, fail).
    """

    # Errors that are safe to retry
    TRANSIENT_ERRORS = {
        "InsufficientDataError",  # Not enough data yet, may appear later
        "DatabaseQueryError",  # Temporary DB issue
        "TimeoutError",  # Temporary timeout
        "ConnectionError",  # Network issue
    }

    # Errors that should skip iteration
    PERMANENT_ERRORS = {
        "ValueError",  # Invalid input
        "ConfigurationError",  # Bad configuration
    }

    def __init__(self, config: LoopConfig):
        """
        Initialize error recovery strategy.

        Args:
            config: Loop configuration
        """
        self.config = config

    def handle_phase_error(
        self,
        agent_name: str,
        phase: Phase,
        error: Exception,
        attempt: int
    ) -> RecoveryAction:
        """
        Determine recovery action for phase error.

        Args:
            agent_name: Name of agent
            phase: Phase that failed
            error: Exception that occurred
            attempt: Current retry attempt (1-indexed)

        Returns:
            RecoveryAction to take
        """
        error_type = type(error).__name__

        # Check if error is transient and retries remaining
        if self.should_retry(error, attempt):
            logger.info(
                f"Phase {phase.value} failed for {agent_name} (attempt {attempt}): {error}. "
                f"Will retry after backoff."
            )
            return RecoveryAction.RETRY

        # Check if error is permanent
        if self._is_permanent_error(error):
            if self.config.fail_on_permanent_error:
                logger.error(
                    f"Permanent error in phase {phase.value} for {agent_name}: {error}. "
                    f"Failing iteration."
                )
                return RecoveryAction.FAIL
            else:
                logger.warning(
                    f"Permanent error in phase {phase.value} for {agent_name}: {error}. "
                    f"Skipping iteration."
                )
                return RecoveryAction.SKIP

        # Max retries exceeded - skip or fail
        if self.config.fail_on_permanent_error:
            logger.error(
                f"Max retries exceeded for phase {phase.value} ({agent_name}): {error}. "
                f"Failing iteration."
            )
            return RecoveryAction.FAIL
        else:
            logger.warning(
                f"Max retries exceeded for phase {phase.value} ({agent_name}): {error}. "
                f"Skipping iteration."
            )
            return RecoveryAction.SKIP

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """
        Determine if error should be retried.

        Args:
            error: Exception that occurred
            attempt: Current attempt number (1-indexed)

        Returns:
            True if should retry
        """
        # Check max retries
        if attempt >= self.config.max_retries_per_phase:
            return False

        # Check if transient error
        error_type = type(error).__name__
        return error_type in self.TRANSIENT_ERRORS

    def get_retry_delay(self, attempt: int) -> float:
        """
        Calculate retry delay with exponential backoff.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Delay in seconds
        """
        delay = self.config.initial_retry_delay_seconds * (
            self.config.retry_backoff_multiplier ** (attempt - 1)
        )
        return min(delay, 300.0)  # Cap at 5 minutes

    def wait_for_retry(self, attempt: int) -> None:
        """
        Wait before retry with exponential backoff.

        Args:
            attempt: Current attempt number (1-indexed)
        """
        delay = self.get_retry_delay(attempt)
        logger.info(f"Waiting {delay:.1f}s before retry (attempt {attempt})")
        time.sleep(delay)

    def should_rollback(self, error: Exception) -> bool:
        """
        Determine if error requires rollback.

        Args:
            error: Exception that occurred

        Returns:
            True if should rollback (not currently used - phases are sequential)
        """
        # Rollback not supported for sequential phases
        return False

    def _is_permanent_error(self, error: Exception) -> bool:
        """
        Check if error is permanent (not worth retrying).

        Args:
            error: Exception that occurred

        Returns:
            True if permanent error
        """
        error_type = type(error).__name__
        return error_type in self.PERMANENT_ERRORS

    def _is_transient_error(self, error: Exception) -> bool:
        """
        Check if error is transient (safe to retry).

        Args:
            error: Exception that occurred

        Returns:
            True if transient error
        """
        error_type = type(error).__name__
        return error_type in self.TRANSIENT_ERRORS
