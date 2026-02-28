"""
Secrets management utilities for handling API keys and credentials.

**SECURITY NOTICE:**
The ObfuscatedCredential class provides OBFUSCATION, not cryptographic security.
It prevents accidental logging but does NOT protect against memory attacks.
For production security, use OS keyring or external secrets managers.

Supports:
- Environment variable references (${env:VAR_NAME})
- AWS Secrets Manager (${aws:secret-id}) - future
- HashiCorp Vault (${vault:path}) - future
- In-memory obfuscation of credentials (prevents accidental logging)
"""

import os
import re
from typing import Any

from temper_ai.shared.constants.sizes import SIZE_10KB, SIZE_100KB

ERROR_SECRET_PREFIX = "Secret '"  # noqa: S105

__all__ = [
    # Secret resolution
    "SecretReference",
    "resolve_secret",
    "detect_secret_patterns",
]


class SecretReference:
    """
    Reference to a secret in external store.

    Supports multiple providers:
    - env: Environment variables (${env:VAR_NAME})
    - vault: HashiCorp Vault (${vault:path}) - not yet implemented
    - aws: AWS Secrets Manager (${aws:secret-id}) - not yet implemented

    Example:
        >>> SecretReference.resolve("${env:OPENAI_API_KEY}")
        "sk-abc123..."

        >>> SecretReference.is_reference("${env:MY_KEY}")
        True

        >>> SecretReference.is_reference("plain-text-value")
        False
    """

    # Regex patterns for each provider
    PATTERNS = {
        "env": re.compile(r"\$\{env:([A-Z_][A-Z0-9_]*)\}"),
        "vault": re.compile(r"\$\{vault:([a-z0-9/_-]+)\}"),
        "aws": re.compile(r"\$\{aws:([a-z0-9/_-]+)\}"),
    }

    @classmethod
    def is_reference(cls, value: str) -> bool:
        """
        Check if value is a secret reference.

        Args:
            value: String value to check

        Returns:
            True if value matches any secret reference pattern
        """
        if not isinstance(value, str):
            return False  # type: ignore[unreachable]

        for pattern in cls.PATTERNS.values():
            if pattern.match(value):
                return True
        return False

    @classmethod
    def resolve(cls, reference: str) -> str:
        """
        Resolve secret reference to actual value.

        Args:
            reference: Secret reference string (e.g., "${env:API_KEY}")

        Returns:
            Resolved secret value

        Raises:
            ValueError: If reference format is invalid or secret not found
            NotImplementedError: If provider is not yet implemented
        """
        # Try each provider pattern
        for provider, pattern in cls.PATTERNS.items():
            match = pattern.match(reference)
            if match:
                key = match.group(1)
                return cls._resolve_provider(provider, key)

        # If not a reference pattern, return as-is (backward compatibility)
        return reference

    @classmethod
    def _resolve_provider(cls, provider: str, key: str) -> str:
        """
        Resolve secret from specific provider.

        Args:
            provider: Provider name (env, vault, aws)
            key: Secret key/path

        Returns:
            Secret value

        Raises:
            ValueError: If secret not found
            NotImplementedError: If provider not yet implemented
        """
        if provider == "env":
            return cls._resolve_env(key)
        elif provider == "vault":
            raise NotImplementedError(
                "HashiCorp Vault provider is planned for v1.1. "
                "Use ${env:VAR_NAME} for environment variables."
            )
        elif provider == "aws":
            raise NotImplementedError(
                "AWS Secrets Manager provider is planned for v1.1. "
                "Use ${env:VAR_NAME} for environment variables."
            )
        else:
            raise ValueError(f"Unknown secret provider: {provider}")

    @classmethod
    def _resolve_env(cls, var_name: str) -> str:
        """
        Resolve environment variable.

        Args:
            var_name: Environment variable name

        Returns:
            Environment variable value

        Raises:
            ValueError: If environment variable not set
        """
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(
                f"Environment variable '{var_name}' not set. "
                f"Set it with: export {var_name}=<value>"
            )

        # Validate secret value
        cls._validate_secret_value(var_name, value)

        return value

    @classmethod
    def _validate_secret_value(cls, name: str, value: str) -> None:
        """
        Validate secret value for security issues.

        Args:
            name: Secret name (for error messages)
            value: Secret value

        Raises:
            ValueError: If value contains suspicious patterns
        """
        # Check for empty value
        if not value or not value.strip():
            raise ValueError(f"{ERROR_SECRET_PREFIX}{name}' is empty")

        # Check for excessively long values (likely misconfiguration)
        if len(value) > SIZE_10KB:
            raise ValueError(
                f"{ERROR_SECRET_PREFIX}{name}' is too long ({len(value)} bytes). "
                f"Maximum {SIZE_10KB} bytes allowed."
            )

        # Check for null bytes (security risk)
        if "\x00" in value:
            raise ValueError(f"{ERROR_SECRET_PREFIX}{name}' contains null bytes")


def resolve_secret(value: Any) -> Any:
    """
    Resolve a value that might be a secret reference.

    If value is a secret reference (e.g., "${env:API_KEY}"), resolves it.
    Otherwise returns value as-is.

    Args:
        value: Value to resolve (can be string, dict, list, etc.)

    Returns:
        Resolved value

    Example:
        >>> resolve_secret("${env:API_KEY}")
        "sk-abc123..."

        >>> resolve_secret("plain-value")
        "plain-value"

        >>> resolve_secret({"key": "${env:SECRET}"})
        {"key": "sk-abc123..."}
    """
    if isinstance(value, str):
        if SecretReference.is_reference(value):
            return SecretReference.resolve(value)
        return value
    elif isinstance(value, dict):
        return {k: resolve_secret(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_secret(item) for item in value]
    else:
        return value


def detect_secret_patterns(text: str) -> tuple[bool, str | None]:
    """
    Detect if text contains patterns that look like secrets.

    Used to prevent accidental secret leakage in logs, configs, etc.

    **SECURITY:** Uses bounded quantifiers to prevent ReDoS (Regular Expression
    Denial of Service) attacks. Input is limited to 100KB to prevent resource exhaustion.

    ReDoS Protection:
    - All patterns use bounded quantifiers ({min,max}) instead of unbounded (+, *)
    - Input length limited to 100KB maximum
    - Patterns complete in <10ms even with malicious input
    - Previous vulnerability: crafted input caused 30+ seconds CPU time

    Args:
        text: Text to scan (max 100KB)

    Returns:
        (is_secret, confidence_level) where confidence is "high", "medium", or "low"

    Raises:
        ValueError: If input exceeds 100KB

    Example:
        >>> detect_secret_patterns("sk-proj-abc123def456")
        (True, "high")

        >>> detect_secret_patterns("normal text here")
        (False, None)
    """
    # SECURITY: Input length validation (Defense in Depth against ReDoS)
    # 100KB limit supports multi-stage workflows with accumulated context
    if len(text) > SIZE_100KB:
        raise ValueError(
            f"Input too long for secret detection ({len(text)} bytes). "
            f"Maximum {SIZE_100KB} bytes allowed. "
            "This protects against ReDoS attacks."
        )

    # Import patterns from centralized registry
    from temper_ai.shared.utils.secret_patterns import (
        MEDIUM_CONFIDENCE_PATTERNS,
        SECRET_PATTERNS,
    )

    for pattern in SECRET_PATTERNS.values():
        if re.search(pattern, text):
            return True, "high"

    for pattern in MEDIUM_CONFIDENCE_PATTERNS.values():
        if re.search(pattern, text):
            return True, "medium"

    return False, None
