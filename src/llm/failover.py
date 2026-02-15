"""
LLM provider with automatic failover to backup providers.

Provides resilient LLM access by automatically switching to backup providers
when the primary provider fails due to transient errors.
"""
import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, List, Optional

import httpx

from src.llm.providers import BaseLLM, LLMError, LLMResponse  # M-04: Import from new location
from src.shared.constants.limits import (
    HTTP_CLIENT_ERROR_MAX,
    HTTP_CLIENT_ERROR_MIN,
    HTTP_SERVER_ERROR_MAX,
    HTTP_SERVER_ERROR_MIN,
)
from src.shared.constants.retries import DEFAULT_MAX_RETRIES
from src.shared.utils.exceptions import LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class FailoverConfig:
    """Configuration for failover behavior."""
    sticky_session: bool = True  # Use last successful provider first
    retry_primary_after: int = DEFAULT_MAX_RETRIES  # Retry primary after N successful backup calls
    failover_on_timeout: bool = True
    failover_on_rate_limit: bool = True
    failover_on_connection_error: bool = True
    failover_on_server_error: bool = True  # 5xx errors
    failover_on_client_error: bool = False  # 4xx errors (usually indicates user error)


class FailoverProvider:
    """
    LLM provider with automatic failover to backup providers.

    When the primary provider fails due to transient errors (connection,
    timeout, rate limit, 5xx), automatically tries backup providers in order.

    Features:
    - Sticky sessions: Remember last successful provider
    - Configurable failover conditions
    - Detailed logging of failover events
    - Automatic retry of primary provider after N successful backup calls

    Example:
        ```python
        from src.llm.providers import OllamaLLM, OpenAILLM  # M-04: Use new import location
        from src.llm.failover import FailoverProvider

        # Create providers
        primary = OllamaLLM(model="llama3.2")
        backup = OpenAILLM(model="gpt-4", api_key="...")

        # Create failover provider
        failover = FailoverProvider(providers=[primary, backup])

        # Use like any LLM provider - automatically fails over
        response = failover.complete("What is 2+2?")
        ```
    """

    def __init__(
        self,
        providers: List[BaseLLM],
        config: Optional[FailoverConfig] = None
    ):
        """
        Initialize failover provider.

        Args:
            providers: List of LLM providers in priority order (first = primary)
            config: Failover configuration

        Raises:
            ValueError: If providers list is empty
        """
        if not providers:
            raise ValueError("At least one provider required")

        self.providers = providers
        self.config = config or FailoverConfig()
        self._state_lock = threading.Lock()
        # Eagerly create async lock to avoid race conditions with lazy initialization.
        # NOTE: asyncio.Lock() binds to the running event loop. If no event loop is
        # running at init time (Python 3.10+), the lock binds on first use. This is
        # safe as long as all async callers share the same event loop, which is the
        # standard asyncio usage pattern.
        self._async_state_lock = asyncio.Lock()
        self.last_successful_index = 0
        self.backup_success_count = 0

        logger.info(
            f"Initialized FailoverProvider with {len(providers)} providers: "
            f"{[p.model for p in providers]}"
        )

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """
        Generate completion with automatic failover.

        Tries providers in order until one succeeds. If sticky_session is enabled,
        starts with the last successful provider.

        Args:
            prompt: Input prompt
            **kwargs: Provider-specific parameters

        Returns:
            LLMResponse from first successful provider

        Raises:
            LLMError: If all providers fail
        """
        errors = []

        # Determine starting index (read state under lock)
        with self._state_lock:
            if self.config.sticky_session and self.backup_success_count < self.config.retry_primary_after:
                start_index = self.last_successful_index
                logger.debug(f"Using sticky session, starting at provider {start_index}")
            else:
                start_index = 0
                if self.backup_success_count >= self.config.retry_primary_after:
                    logger.info(f"Retrying primary provider after {self.backup_success_count} backup successes")
                    self.backup_success_count = 0

        # Try each provider
        for attempt in range(len(self.providers)):
            index = (start_index + attempt) % len(self.providers)
            provider = self.providers[index]

            try:
                logger.info(f"Attempting provider [{index}]: {provider.model}")
                # LLM call outside lock to avoid blocking other threads
                result = provider.complete(prompt, **kwargs)

                # Success - update state atomically
                with self._state_lock:
                    if index != self.last_successful_index:
                        logger.info(
                            f"Failover successful: switched from provider {self.last_successful_index} "
                            f"to provider {index} ({provider.model})"
                        )
                    self.last_successful_index = index
                    if index != 0:
                        self.backup_success_count += 1
                    else:
                        self.backup_success_count = 0

                logger.info(f"Success with provider [{index}]: {provider.model}")
                return result

            except (LLMError, LLMTimeoutError, LLMRateLimitError, LLMAuthenticationError,
                    httpx.HTTPError, ConnectionError, TimeoutError, OSError) as e:
                error_msg = f"{provider.model}: {type(e).__name__}: {str(e)}"
                logger.warning(f"Provider [{index}] failed: {error_msg}")
                errors.append(error_msg)

                # Check if we should failover for this error type
                if not self._should_failover(e):
                    logger.info(f"Not failing over for error type: {type(e).__name__}")
                    raise

                # Continue to next provider
                continue

        # All providers failed
        error_summary = "; ".join(errors)
        raise LLMError(
            f"All {len(self.providers)} providers failed. Errors: {error_summary}"
        )

    async def acomplete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """
        Async version: Generate completion with automatic failover.

        Uses asyncio.Lock instead of threading.Lock to avoid blocking the
        event loop during state reads/writes.

        Args:
            prompt: Input prompt
            **kwargs: Provider-specific parameters

        Returns:
            LLMResponse from first successful provider

        Raises:
            LLMError: If all providers fail
        """
        errors = []

        # Determine starting index (read state under async lock)
        async with self._async_state_lock:
            if self.config.sticky_session and self.backup_success_count < self.config.retry_primary_after:
                start_index = self.last_successful_index
                logger.debug(f"Using sticky session, starting at provider {start_index}")
            else:
                start_index = 0
                if self.backup_success_count >= self.config.retry_primary_after:
                    logger.info(f"Retrying primary provider after {self.backup_success_count} backup successes")
                    self.backup_success_count = 0

        # Try each provider
        for attempt in range(len(self.providers)):
            index = (start_index + attempt) % len(self.providers)
            provider = self.providers[index]

            try:
                logger.info(f"Attempting provider [{index}]: {provider.model}")
                # LLM call outside lock to avoid blocking other coroutines
                result = await provider.acomplete(prompt, **kwargs)

                # Success - update state atomically
                async with self._async_state_lock:
                    if index != self.last_successful_index:
                        logger.info(
                            f"Failover successful: switched from provider {self.last_successful_index} "
                            f"to provider {index} ({provider.model})"
                        )
                    self.last_successful_index = index
                    if index != 0:
                        self.backup_success_count += 1
                    else:
                        self.backup_success_count = 0

                logger.info(f"Success with provider [{index}]: {provider.model}")
                return result

            except (LLMError, LLMTimeoutError, LLMRateLimitError, LLMAuthenticationError,
                    httpx.HTTPError, ConnectionError, TimeoutError, OSError) as e:
                error_msg = f"{provider.model}: {type(e).__name__}: {str(e)}"
                logger.warning(f"Provider [{index}] failed: {error_msg}")
                errors.append(error_msg)

                # Check if we should failover for this error type
                if not self._should_failover(e):
                    logger.info(f"Not failing over for error type: {type(e).__name__}")
                    raise

                # Continue to next provider
                continue

        # All providers failed
        error_summary = "; ".join(errors)
        raise LLMError(
            f"All {len(self.providers)} providers failed. Errors: {error_summary}"
        )

    def _should_failover(self, error: Exception) -> bool:
        """
        Determine if we should failover for this error type.

        Args:
            error: The exception that occurred

        Returns:
            True if we should try the next provider
        """
        # Timeout errors
        if isinstance(error, (LLMTimeoutError, httpx.TimeoutException, TimeoutError)):
            return self.config.failover_on_timeout

        # Rate limit errors
        if isinstance(error, LLMRateLimitError):
            return self.config.failover_on_rate_limit

        # Connection errors
        if isinstance(error, (httpx.ConnectError, httpx.NetworkError, ConnectionError)):
            return self.config.failover_on_connection_error

        # HTTP status errors
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            if HTTP_CLIENT_ERROR_MIN <= status_code < HTTP_CLIENT_ERROR_MAX:
                return self.config.failover_on_client_error
            elif HTTP_SERVER_ERROR_MIN <= status_code < HTTP_SERVER_ERROR_MAX:
                return self.config.failover_on_server_error

        # Authentication errors - don't failover (likely same credentials)
        if isinstance(error, LLMAuthenticationError):
            return False

        # Default: failover for unknown errors
        return True

    def reset(self) -> None:
        """Reset failover state to prefer primary provider (thread-safe)."""
        with self._state_lock:
            self.last_successful_index = 0
            self.backup_success_count = 0
        logger.info("Reset failover state to primary provider")

    @property
    def model(self) -> str:
        """Return current provider's model name (thread-safe)."""
        with self._state_lock:
            index = self.last_successful_index
        return self.providers[index].model

    @property
    def provider_name(self) -> str:
        """Return current provider's name (thread-safe)."""
        with self._state_lock:
            index = self.last_successful_index
        provider = self.providers[index]
        return getattr(provider, 'provider', provider.__class__.__name__)
