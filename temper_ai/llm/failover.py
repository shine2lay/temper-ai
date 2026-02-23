"""
LLM provider with automatic failover to backup providers.

Provides resilient LLM access by automatically switching to backup providers
when the primary provider fails due to transient errors.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from temper_ai.llm.providers import (  # M-04: Import from new location
    BaseLLM,
    LLMError,
    LLMResponse,
)
from temper_ai.shared.constants.limits import (
    HTTP_CLIENT_ERROR_MAX,
    HTTP_CLIENT_ERROR_MIN,
    HTTP_SERVER_ERROR_MAX,
    HTTP_SERVER_ERROR_MIN,
)
from temper_ai.shared.constants.retries import DEFAULT_MAX_RETRIES
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass
class FailoverConfig:
    """Configuration for failover behavior."""

    sticky_session: bool = True  # Use last successful provider first
    retry_primary_after: int = (
        DEFAULT_MAX_RETRIES  # Retry primary after N successful backup calls
    )
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
        from temper_ai.llm.providers import OllamaLLM, OpenAILLM  # M-04: Use new import location
        from temper_ai.llm.failover import FailoverProvider

        # Create providers
        primary = OllamaLLM(model="llama3.2")
        backup = OpenAILLM(model="gpt-4", api_key="...")

        # Create failover provider
        failover = FailoverProvider(providers=[primary, backup])

        # Use like any LLM provider - automatically fails over
        response = failover.complete("What is 2+2?")
        ```
    """

    def __init__(self, providers: list[BaseLLM], config: FailoverConfig | None = None):
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
        self._last_failover_sequence: list[str] = []

        logger.info(
            f"Initialized FailoverProvider with {len(providers)} providers: "
            f"{[p.model for p in providers]}"
        )

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Generate completion with automatic failover.

        Args:
            prompt: Input prompt
            **kwargs: Provider-specific parameters

        Returns:
            LLMResponse from first successful provider

        Raises:
            LLMError: If all providers fail
        """
        errors: list[str] = []
        failover_sequence: list[str] = []
        start_index = self._get_start_index()

        for attempt in range(len(self.providers)):
            index = (start_index + attempt) % len(self.providers)
            provider = self.providers[index]

            try:
                logger.info(f"Attempting provider [{index}]: {provider.model}")
                result = provider.complete(prompt, **kwargs)
                self._record_success(index, provider, failover_sequence)
                return result

            except (
                LLMError,
                LLMTimeoutError,
                LLMRateLimitError,
                LLMAuthenticationError,
                httpx.HTTPError,
                ConnectionError,
                TimeoutError,
                OSError,
            ) as e:
                self._record_failure(provider, e, errors, failover_sequence)
                if not self._should_failover(e):
                    self._store_sequence(failover_sequence)
                    raise

        self._store_sequence(failover_sequence)
        raise LLMError(
            f"All {len(self.providers)} providers failed. Errors: {'; '.join(errors)}"
        )

    async def acomplete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Async: Generate completion with automatic failover."""
        errors: list[str] = []
        failover_sequence: list[str] = []
        start_index = await self._async_get_start_index()

        for attempt in range(len(self.providers)):
            index = (start_index + attempt) % len(self.providers)
            provider = self.providers[index]

            try:
                logger.info(f"Attempting provider [{index}]: {provider.model}")
                result = await provider.acomplete(prompt, **kwargs)
                await self._async_record_success(index, provider, failover_sequence)
                return result

            except (
                LLMError,
                LLMTimeoutError,
                LLMRateLimitError,
                LLMAuthenticationError,
                httpx.HTTPError,
                ConnectionError,
                TimeoutError,
                OSError,
            ) as e:
                self._record_failure(provider, e, errors, failover_sequence)
                if not self._should_failover(e):
                    self._store_sequence(failover_sequence)
                    raise

        self._store_sequence(failover_sequence)
        raise LLMError(
            f"All {len(self.providers)} providers failed. Errors: {'; '.join(errors)}"
        )

    def _get_start_index(self) -> int:
        """Determine starting provider index (thread-safe)."""
        with self._state_lock:
            if (
                self.config.sticky_session
                and self.backup_success_count < self.config.retry_primary_after
            ):
                logger.debug(
                    f"Sticky session: starting at provider {self.last_successful_index}"
                )
                return self.last_successful_index
            if self.backup_success_count >= self.config.retry_primary_after:
                logger.info(
                    f"Retrying primary after {self.backup_success_count} backup successes"
                )
                self.backup_success_count = 0
            return 0

    async def _async_get_start_index(self) -> int:  # noqa: duplicate
        """Determine starting provider index (async-safe)."""
        async with self._async_state_lock:
            if (
                self.config.sticky_session
                and self.backup_success_count < self.config.retry_primary_after
            ):
                logger.debug(
                    f"Sticky session: starting at provider {self.last_successful_index}"
                )
                return self.last_successful_index
            if self.backup_success_count >= self.config.retry_primary_after:
                logger.info(
                    f"Retrying primary after {self.backup_success_count} backup successes"
                )
                self.backup_success_count = 0
            return 0

    def _record_success(
        self, index: int, provider: Any, failover_sequence: list[str]
    ) -> None:
        """Record successful provider call and update state (thread-safe)."""
        provider_name = getattr(provider, "provider", provider.__class__.__name__)
        failover_sequence.append(f"{provider_name}:{provider.model}:success")
        with self._state_lock:
            if index != self.last_successful_index:
                logger.info(
                    f"Failover: {self.last_successful_index} -> {index} ({provider.model})"
                )
            self.last_successful_index = index
            self.backup_success_count = (
                self.backup_success_count + 1 if index != 0 else 0
            )
            self._last_failover_sequence = failover_sequence
        logger.info(f"Success with provider [{index}]: {provider.model}")

    async def _async_record_success(  # noqa: duplicate
        self, index: int, provider: Any, failover_sequence: list[str]
    ) -> None:
        """Record successful provider call and update state (async-safe)."""
        provider_name = getattr(provider, "provider", provider.__class__.__name__)
        failover_sequence.append(f"{provider_name}:{provider.model}:success")
        async with self._async_state_lock:
            if index != self.last_successful_index:
                logger.info(
                    f"Failover: {self.last_successful_index} -> {index} ({provider.model})"
                )
            self.last_successful_index = index
            self.backup_success_count = (
                self.backup_success_count + 1 if index != 0 else 0
            )
            self._last_failover_sequence = failover_sequence
        logger.info(f"Success with provider [{index}]: {provider.model}")

    def _record_failure(
        self,
        provider: Any,
        error: Exception,
        errors: list[str],
        failover_sequence: list[str],
    ) -> None:
        """Record provider failure in error list and failover sequence."""
        error_msg = f"{provider.model}: {type(error).__name__}: {str(error)}"
        logger.warning(f"Provider failed: {error_msg}")
        errors.append(error_msg)
        provider_name = getattr(provider, "provider", provider.__class__.__name__)
        failover_sequence.append(
            f"{provider_name}:{provider.model}:{type(error).__name__}"
        )

    def _store_sequence(self, failover_sequence: list[str]) -> None:
        """Store failover sequence (thread-safe)."""
        with self._state_lock:
            self._last_failover_sequence = failover_sequence

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

    @property
    def last_failover_sequence(self) -> list[str]:
        """Return the failover sequence from the last call (thread-safe)."""
        with self._state_lock:
            return list(self._last_failover_sequence)

    def reset(self) -> None:
        """Reset failover state to prefer primary provider (thread-safe)."""
        with self._state_lock:
            self.last_successful_index = 0
            self.backup_success_count = 0
            self._last_failover_sequence = []
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
        return getattr(provider, "provider", provider.__class__.__name__)
