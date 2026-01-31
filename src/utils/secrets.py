"""
Secrets management utilities for secure handling of API keys and credentials.

Supports:
- Environment variable references (${env:VAR_NAME})
- AWS Secrets Manager (${aws:secret-id}) - future
- HashiCorp Vault (${vault:path}) - future
- In-memory encryption of credentials
"""
import os
import re
from typing import Optional, Dict, Any, Tuple
from cryptography.fernet import Fernet


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
        'env': re.compile(r'\$\{env:([A-Z_][A-Z0-9_]*)\}'),
        'vault': re.compile(r'\$\{vault:([a-z0-9/_-]+)\}'),
        'aws': re.compile(r'\$\{aws:([a-z0-9/_-]+)\}'),
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
        if provider == 'env':
            return cls._resolve_env(key)
        elif provider == 'vault':
            raise NotImplementedError(
                "HashiCorp Vault provider not yet implemented. "
                "Use ${env:VAR_NAME} for environment variables."
            )
        elif provider == 'aws':
            raise NotImplementedError(
                "AWS Secrets Manager provider not yet implemented. "
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
            raise ValueError(f"Secret '{name}' is empty")

        # Check for excessively long values (likely misconfiguration)
        if len(value) > 10 * 1024:  # 10KB
            raise ValueError(
                f"Secret '{name}' is too long ({len(value)} bytes). "
                "Maximum 10KB allowed."
            )

        # Check for null bytes (security risk)
        if '\x00' in value:
            raise ValueError(f"Secret '{name}' contains null bytes")


class SecureCredential:
    """
    Encrypted credential storage in memory.

    Stores credentials encrypted in memory and only decrypts when accessed.
    Prevents accidental logging or serialization of secrets.

    Example:
        >>> cred = SecureCredential("sk-secret-api-key-123")
        >>> str(cred)  # Safe for logging
        '***REDACTED***'
        >>> cred.get()  # Decrypt when needed
        'sk-secret-api-key-123'
    """

    def __init__(self, value: str):
        """
        Initialize with plaintext value (encrypted immediately).

        Args:
            value: Plaintext credential value
        """
        if not value:
            raise ValueError("Cannot create SecureCredential with empty value")

        # Generate encryption key (unique per instance)
        self._key = Fernet.generate_key()
        self._cipher = Fernet(self._key)

        # Encrypt and store
        self._encrypted = self._cipher.encrypt(value.encode('utf-8'))

        # Track access for audit trail
        self._access_count = 0

    def get(self) -> str:
        """
        Decrypt and return credential.

        Returns:
            Decrypted credential value
        """
        self._access_count += 1
        return self._cipher.decrypt(self._encrypted).decode('utf-8')

    def __repr__(self) -> str:
        """Redacted representation for logging/debugging."""
        return "SecureCredential(***REDACTED***)"

    def __str__(self) -> str:
        """Redacted string representation."""
        return "***REDACTED***"

    def __bool__(self) -> bool:
        """Credential is truthy if it exists."""
        return True


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


def detect_secret_patterns(text: str) -> Tuple[bool, Optional[str]]:
    """
    Detect if text contains patterns that look like secrets.

    Used to prevent accidental secret leakage in logs, configs, etc.

    Args:
        text: Text to scan

    Returns:
        (is_secret, confidence_level) where confidence is "high", "medium", or "low"

    Example:
        >>> detect_secret_patterns("sk-proj-abc123def456")
        (True, "high")

        >>> detect_secret_patterns("normal text here")
        (False, None)
    """
    # High-confidence patterns (known secret formats)
    high_confidence_patterns = [
        r'sk-[a-zA-Z0-9]{20,}',  # OpenAI API keys
        r'sk-proj-[a-zA-Z0-9]{20,}',  # OpenAI project keys
        r'sk-ant-api\d+-[a-zA-Z0-9]{20,}',  # Anthropic API keys
        r'AIza[0-9A-Za-z\\-_]{35}',  # Google API keys
        r'AKIA[0-9A-Z]{16}',  # AWS access keys
        r'ya29\.[0-9A-Za-z\-_]+',  # Google OAuth tokens
        r'ghp_[0-9a-zA-Z]{30,40}',  # GitHub personal access tokens
        r'gho_[0-9a-zA-Z]{30,40}',  # GitHub OAuth tokens
    ]

    # Medium-confidence patterns (generic secret-like strings)
    medium_confidence_patterns = [
        r'[a-f0-9]{32}',  # MD5-like hashes
        r'[a-f0-9]{40}',  # SHA1-like hashes
        r'[A-Za-z0-9+/]{40,}={0,2}',  # Base64-encoded strings
    ]

    for pattern in high_confidence_patterns:
        if re.search(pattern, text):
            return True, "high"

    for pattern in medium_confidence_patterns:
        if re.search(pattern, text):
            return True, "medium"

    return False, None
