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
import warnings
from typing import Any, Optional, Tuple

from cryptography.fernet import Fernet

__all__ = [
    # Secret resolution
    'SecretReference',
    'resolve_secret',
    'detect_secret_patterns',
    # URL masking
    'mask_url_password',
    # Credential obfuscation
    'ObfuscatedCredential',
    'SecureCredential',  # Deprecated alias for ObfuscatedCredential
]


def mask_url_password(url: str) -> str:
    """Mask password in a URL for safe logging.

    Replaces the password component in URLs of the form
    ``scheme://user:password@host`` with ``***``.

    Args:
        url: URL string that may contain embedded credentials.

    Returns:
        URL with password replaced by ``***``, or the original
        string unchanged if no password is found.

    Example:
        >>> mask_url_password("redis://:secret@localhost:6379/0")
        'redis://:***@localhost:6379/0'
        >>> mask_url_password("redis://localhost:6379/0")
        'redis://localhost:6379/0'
    """
    # Match scheme://[user][:password]@host patterns
    return re.sub(
        r'(://[^:@]*:)[^@]+(@)',
        r'\1***\2',
        url,
    )


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


class ObfuscatedCredential:
    """
    Obfuscated credential storage in memory.

    **SECURITY WARNING: This provides OBFUSCATION, not encryption!**

    This class prevents accidental logging or serialization of secrets by
    storing them in an obfuscated form and redacting them in string representations.
    However, it does NOT provide security against memory attacks or determined
    adversaries because:

    1. The encryption key is stored in the same process memory
    2. An attacker with memory access can extract both key and ciphertext
    3. This is security through obscurity, not cryptographic protection

    **Use Cases:**
    - ✅ Preventing accidental logging of secrets
    - ✅ Redacting secrets in error messages
    - ✅ Avoiding secrets in stack traces
    - ❌ Protecting secrets from malicious code in the same process
    - ❌ Protecting secrets from memory dumps
    - ❌ Compliance with encryption requirements

    **For True Encryption:**
    Use OS keyring integration (e.g., keyring package) or external secrets
    managers (AWS Secrets Manager, HashiCorp Vault) where keys are stored
    outside the process memory.

    Example:
        >>> cred = ObfuscatedCredential("sk-secret-api-key-123")
        >>> str(cred)  # Safe for logging
        '***REDACTED***'
        >>> cred.get()  # De-obfuscate when needed
        'sk-secret-api-key-123'
    """

    def __init__(self, value: str):
        """
        Initialize with plaintext value (obfuscated immediately).

        **SECURITY WARNING:** This is OBFUSCATION, not secure encryption!
        The encryption key is stored in the same memory as the encrypted data,
        providing no protection against memory attacks or malicious code.

        Args:
            value: Plaintext credential value
        """
        if not value:
            raise ValueError("Cannot create ObfuscatedCredential with empty value")

        # SECURITY WARNING: Key stored in same process memory as encrypted data!
        # This provides OBFUSCATION (prevents accidental logging) NOT security.
        # For real encryption, use OS keyring or external secrets manager.
        #
        # Generate encryption key (unique per instance)
        self._key = Fernet.generate_key()
        self._cipher = Fernet(self._key)

        # Encrypt and store
        self._encrypted = self._cipher.encrypt(value.encode('utf-8'))

        # Track access for audit trail
        self._access_count = 0

    def get(self) -> str:
        """
        De-obfuscate and return credential.

        Returns:
            Plaintext credential value
        """
        self._access_count += 1
        return self._cipher.decrypt(self._encrypted).decode('utf-8')

    def __repr__(self) -> str:
        """
        Redacted representation for logging/debugging.

        Returns the class name to aid debugging while preventing secret exposure.
        The actual secret is never included in the repr output.

        Returns:
            String representation with redacted value
        """
        return "ObfuscatedCredential(***REDACTED***)"

    def __str__(self) -> str:
        """Redacted string representation."""
        return "***REDACTED***"

    def __bool__(self) -> bool:
        """Credential is truthy if it exists."""
        return True


class SecureCredential(ObfuscatedCredential):
    """
    DEPRECATED: Use ObfuscatedCredential instead.

    This class name is misleading because it implies cryptographic security,
    but it only provides obfuscation (prevents accidental logging).

    **Migration:**
    Replace all usage of SecureCredential with ObfuscatedCredential:
        # Old (deprecated):
        cred = SecureCredential("secret")

        # New (recommended):
        cred = ObfuscatedCredential("secret")

    **Why Deprecated:**
    The name "SecureCredential" creates a false sense of security. While the
    implementation has extensive documentation explaining it's only obfuscation,
    the name itself is misleading. "ObfuscatedCredential" accurately describes
    what this class does.

    **Deprecation Timeline:**
    - 2026-01-31: Deprecated (warnings added)
    - Future: Will be removed in a future version

    For backward compatibility, this alias will continue to work but emits
    a DeprecationWarning on first use.
    """

    # Class-level flag to emit warning only once per process
    _warning_shown = False

    def __init__(self, value: str):
        """
        Initialize with plaintext value (emits deprecation warning).

        Args:
            value: Plaintext credential value
        """
        # Emit deprecation warning (once per process)
        if not SecureCredential._warning_shown:
            warnings.warn(
                "SecureCredential is deprecated. Use ObfuscatedCredential instead. "
                "The name 'SecureCredential' is misleading because it provides "
                "OBFUSCATION (prevents accidental logging), not cryptographic security. "
                "It does NOT protect against memory attacks or malicious code.",
                DeprecationWarning,
                stacklevel=2
            )
            SecureCredential._warning_shown = True

        super().__init__(value)


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

    **SECURITY:** Uses bounded quantifiers to prevent ReDoS (Regular Expression
    Denial of Service) attacks. Input is limited to 10KB to prevent resource exhaustion.

    ReDoS Protection:
    - All patterns use bounded quantifiers ({min,max}) instead of unbounded (+, *)
    - Input length limited to 10KB maximum
    - Patterns complete in <10ms even with malicious input
    - Previous vulnerability: crafted input caused 30+ seconds CPU time

    Args:
        text: Text to scan (max 10KB)

    Returns:
        (is_secret, confidence_level) where confidence is "high", "medium", or "low"

    Raises:
        ValueError: If input exceeds 10KB

    Example:
        >>> detect_secret_patterns("sk-proj-abc123def456")
        (True, "high")

        >>> detect_secret_patterns("normal text here")
        (False, None)
    """
    # SECURITY: Input length validation (Defense in Depth against ReDoS)
    max_input_length = 10 * 1024  # 10KB
    if len(text) > max_input_length:
        raise ValueError(
            f"Input too long for secret detection ({len(text)} bytes). "
            f"Maximum {max_input_length} bytes allowed. "
            "This protects against ReDoS attacks."
        )

    # Import high-confidence patterns from centralized registry
    from src.utils.secret_patterns import SECRET_PATTERNS

    for pattern in SECRET_PATTERNS.values():
        if re.search(pattern, text):
            return True, "high"

    # Medium-confidence patterns (generic secret-like strings)
    # These are heuristic patterns not in the central registry
    medium_confidence_patterns = [
        r'[a-f0-9]{32}',  # MD5-like hashes
        r'[a-f0-9]{40}',  # SHA1-like hashes
        r'[A-Za-z0-9+/]{40,100}={0,2}',  # Base64-encoded strings
    ]

    for pattern in medium_confidence_patterns:
        if re.search(pattern, text):
            return True, "medium"

    return False, None
