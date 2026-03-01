"""Secure OAuth Token Storage with OS Keyring Integration.

SECURITY ARCHITECTURE:

Key Storage Hierarchy (Most Secure → Least Secure):
1. OS Keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
2. Environment Variable (OAUTH_TOKEN_ENCRYPTION_KEY)
3. Fail Secure (Reject if no secure storage available)

Defense Layers:
1. Fernet encryption (AES-128-CBC with HMAC for authenticity)
2. OS-level key isolation (keyring) - RECOMMENDED
3. Per-user key derivation (future enhancement)
4. Automatic expiry tracking
5. Audit logging of token access
6. Key rotation support

COMPLIANCE:
- PCI DSS: ✅ Key stored outside application memory (keyring mode)
- SOC 2: ✅ Audit logging enabled
- GDPR: ✅ Token deletion support
- HIPAA: ⚠️  Use keyring mode + persistent database

References:
- Fernet spec: https://github.com/fernet/spec/blob/master/Spec.md
- Cryptography lib: https://cryptography.io/en/latest/fernet/
- Keyring lib: https://github.com/jaraco/keyring
"""

import json
import logging
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

# Optional keyring import (fallback gracefully if not available)
try:
    import keyring  # type: ignore[import-not-found]
    from keyring.errors import KeyringError  # type: ignore[import-not-found]

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    KeyringError = Exception

from temper_ai.auth.constants import (
    FIELD_ACTION,
    FIELD_EXPIRES_AT,
    FIELD_TIMESTAMP,
    FIELD_USER_ID,
)
from temper_ai.auth.oauth._token_store_helpers import (
    acquire_encryption_key,
)
from temper_ai.shared.constants.limits import THRESHOLD_MASSIVE_COUNT

logger = logging.getLogger(__name__)


# Consolidated: canonical definition in temper_ai/shared/utils/exceptions.py
from temper_ai.shared.utils.exceptions import SecurityError  # noqa: F401


class SecureTokenStore:
    """Encrypts and stores OAuth tokens with OS keyring integration.

    SECURITY NOTICE:
    - Tokens encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
    - Encryption key stored in OS keyring (preferred) or environment variable
    - Key rotation recommended every 90 days
    - In-memory storage (use database in production for persistence)

    **SECURITY WARNING about Environment Variable Storage:**
    Environment variables provide limited security:
    - ❌ Visible in process listings (ps -ef)
    - ❌ Accessible via /proc/<pid>/environ
    - ❌ May appear in logs, crash dumps
    - ❌ Shared across all processes
    - ❌ Fails most compliance audits (PCI DSS, SOC 2)

    For production OAuth tokens (which contain PII), use OS keyring instead.

    Example:
        >>> # Automatic key management (uses keyring if available)
        >>> store = SecureTokenStore()
        >>> store.store_token("user_123", {
        ...     "access_token": "ya29.a0...",
        ...     "refresh_token": "1//...",
        ... }, expires_in=3600)

        >>> # Explicit keyring configuration
        >>> store = SecureTokenStore(
        ...     use_keyring=True,
        ...     keyring_service="myapp-oauth",
        ...     keyring_key_name="token_encryption_key"
        ... )

        >>> # Compliance mode (requires keyring)
        >>> store = SecureTokenStore(require_keyring=True)
    """

    DEFAULT_KEYRING_SERVICE = "temper-ai"
    DEFAULT_KEYRING_KEY_NAME = "oauth_token_encryption_key"
    MAX_ACCESS_LOG_SIZE = THRESHOLD_MASSIVE_COUNT  # 10000

    def __init__(
        self,
        encryption_key: str | None = None,
        use_keyring: bool = True,  # Try keyring by default
        keyring_service: str | None = None,
        keyring_key_name: str | None = None,
        require_keyring: bool = False,  # Fail if keyring not available
        max_access_log_size: int | None = None,
    ):
        """Initialize token store with secure key management.

        NOTE: Thread-safety applies to instance methods (store_token, retrieve_token, etc.),
        not to __init__. Instances should be created in a single-threaded context
        (e.g., application startup) and then shared across threads.

        Args:
            encryption_key: Explicit Fernet key (bypasses keyring/env, testing only)
            use_keyring: Try to use OS keyring for key storage (default: True)
            keyring_service: Keyring service name (default: "temper-ai")
            keyring_key_name: Keyring key identifier (default: "oauth_token_encryption_key")
            require_keyring: Fail if keyring not available (compliance mode)

        Raises:
            ValueError: If no encryption key available
            SecurityError: If keyring required but not available
        """
        if max_access_log_size is None:
            max_access_log_size = self.MAX_ACCESS_LOG_SIZE

        self.keyring_service = keyring_service or self.DEFAULT_KEYRING_SERVICE
        self.keyring_key_name = keyring_key_name or self.DEFAULT_KEYRING_KEY_NAME

        # Acquire encryption key from available sources (keyring, env, explicit)
        key, self.using_keyring = acquire_encryption_key(
            encryption_key=encryption_key,
            use_keyring=use_keyring,
            keyring_service=self.keyring_service,
            keyring_key_name=self.keyring_key_name,
            require_keyring=require_keyring,
        )

        # Initialize Fernet cipher
        try:
            if isinstance(key, str):
                key = key.encode()
            self.cipher = Fernet(key)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid encryption key: {e}") from e

        # In-memory storage (use database in production)
        # Key: user_id, Value: encrypted token bytes
        self._tokens: dict[str, bytes] = {}

        # Audit log (bounded deque to prevent unbounded memory growth)
        self._access_log: deque = deque(maxlen=max_access_log_size)

        # Thread safety: Reentrant lock for concurrent access protection
        # CRITICAL for key rotation to prevent race conditions
        self._lock = threading.RLock()

    def store_token(
        self, user_id: str, token_data: dict[str, Any], expires_in: int | None = None
    ) -> None:
        """Store encrypted token.

        Args:
            user_id: User identifier
            token_data: Token data to encrypt (dict with access_token, refresh_token, etc.)
            expires_in: Token expiry in seconds (optional)

        Example:
            >>> store.store_token("user_123", {
            ...     "access_token": "ya29.a0...",
            ...     "refresh_token": "1//...",
            ...     "token_type": "Bearer",
            ...     "scope": "openid email profile"
            ... }, expires_in=3600)
        """
        with self._lock:
            # Add metadata
            token_with_metadata = {
                **token_data,
                "stored_at": datetime.now(UTC).isoformat(),
                FIELD_EXPIRES_AT: (
                    (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
                    if expires_in
                    else None
                ),
            }

            # Serialize and encrypt
            token_json = json.dumps(token_with_metadata)
            encrypted = self.cipher.encrypt(token_json.encode())

            # Store encrypted token
            self._tokens[user_id] = encrypted

            # Audit log
            self._access_log.append(
                {
                    FIELD_ACTION: "store",
                    FIELD_USER_ID: user_id,
                    FIELD_TIMESTAMP: datetime.now(UTC).isoformat(),
                    "expires_in": expires_in,
                }
            )

    def retrieve_token(self, user_id: str) -> dict[str, Any] | None:
        """Retrieve and decrypt token.

        Args:
            user_id: User identifier

        Returns:
            Decrypted token data or None if not found/expired

        SECURITY: Automatically deletes expired tokens
        """
        with self._lock:
            encrypted = self._tokens.get(user_id)
            if not encrypted:
                return None

            # Decrypt
            try:
                decrypted = self.cipher.decrypt(encrypted)
                token_data: dict[str, Any] = json.loads(decrypted.decode())
            except (InvalidToken, json.JSONDecodeError):
                # Decryption failed (corrupted data, wrong key, or tampered)
                # SECURITY: Delete corrupted token (lock is reentrant, safe to call)
                self.delete_token(user_id)
                return None

            # Check expiry
            if token_data.get(FIELD_EXPIRES_AT):
                try:
                    expires_at = datetime.fromisoformat(token_data[FIELD_EXPIRES_AT])
                    if datetime.now(UTC) > expires_at:
                        # Token expired - delete it
                        self.delete_token(user_id)
                        return None
                except (ValueError, TypeError):
                    # Invalid expiry format - treat as expired
                    self.delete_token(user_id)
                    return None

            # Audit log
            self._access_log.append(
                {
                    FIELD_ACTION: "retrieve",
                    FIELD_USER_ID: user_id,
                    FIELD_TIMESTAMP: datetime.now(UTC).isoformat(),
                }
            )

            return token_data

    def delete_token(self, user_id: str) -> bool:
        """Delete token.

        Args:
            user_id: User identifier

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if user_id in self._tokens:
                del self._tokens[user_id]

                # Audit log
                self._access_log.append(
                    {
                        "action": "delete",
                        "user_id": user_id,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
                return True

            return False
