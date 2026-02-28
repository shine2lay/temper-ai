"""Utility modules for Temper AI.

This package provides shared utilities:
- exceptions: Custom exception hierarchy (LLMError, etc.)
- error_handling: Error handling helpers
- logging: Logging configuration
- config_helpers: Configuration loading utilities
- path_safety: Path validation and sanitization
- secret_patterns: Secret/credential detection patterns
- secrets: Secret management utilities
"""

from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

__all__ = [
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
]
