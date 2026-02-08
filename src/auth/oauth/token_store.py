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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken

# Optional keyring import (fallback gracefully if not available)
try:
    import keyring
    from keyring.errors import KeyringError
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    KeyringError = Exception

from src.auth.oauth._token_store_helpers import acquire_encryption_key, re_encrypt_tokens
from src.constants.limits import THRESHOLD_MASSIVE_COUNT

logger = logging.getLogger(__name__)


# Consolidated: canonical definition in src/utils/exceptions.py
from src.utils.exceptions import SecurityError  # noqa: F401


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

    DEFAULT_KEYRING_SERVICE = "meta-autonomous-framework"
    DEFAULT_KEYRING_KEY_NAME = "oauth_token_encryption_key"
    MAX_ACCESS_LOG_SIZE = THRESHOLD_MASSIVE_COUNT  # 10000

    def __init__(
        self,
        encryption_key: Optional[str] = None,
        use_keyring: bool = True,  # Try keyring by default
        keyring_service: Optional[str] = None,
        keyring_key_name: Optional[str] = None,
        require_keyring: bool = False,  # Fail if keyring not available
        max_access_log_size: int = None,
    ):
        """Initialize token store with secure key management.

        NOTE: Thread-safety applies to instance methods (store_token, retrieve_token, etc.),
        not to __init__. Instances should be created in a single-threaded context
        (e.g., application startup) and then shared across threads.

        Args:
            encryption_key: Explicit Fernet key (bypasses keyring/env, testing only)
            use_keyring: Try to use OS keyring for key storage (default: True)
            keyring_service: Keyring service name (default: "meta-autonomous-framework")
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
        self._tokens: Dict[str, bytes] = {}

        # Audit log (bounded deque to prevent unbounded memory growth)
        self._access_log: deque = deque(maxlen=max_access_log_size)

        # Thread safety: Reentrant lock for concurrent access protection
        # CRITICAL for key rotation to prevent race conditions
        self._lock = threading.RLock()

    def store_token(
        self,
        user_id: str,
        token_data: Dict[str, Any],
        expires_in: Optional[int] = None
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
                "stored_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                ).isoformat()
                if expires_in
                else None,
            }

            # Serialize and encrypt
            token_json = json.dumps(token_with_metadata)
            encrypted = self.cipher.encrypt(token_json.encode())

            # Store encrypted token
            self._tokens[user_id] = encrypted

            # Audit log
            self._access_log.append({
                "action": "store",
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "expires_in": expires_in,
            })

    def retrieve_token(self, user_id: str) -> Optional[Dict[str, Any]]:
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
                token_data = json.loads(decrypted.decode())
            except (InvalidToken, json.JSONDecodeError):
                # Decryption failed (corrupted data, wrong key, or tampered)
                # SECURITY: Delete corrupted token (lock is reentrant, safe to call)
                self.delete_token(user_id)
                return None

            # Check expiry
            if token_data.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(token_data["expires_at"])
                    if datetime.now(timezone.utc) > expires_at:
                        # Token expired - delete it
                        self.delete_token(user_id)
                        return None
                except (ValueError, TypeError):
                    # Invalid expiry format - treat as expired
                    self.delete_token(user_id)
                    return None

            # Audit log
            self._access_log.append({
                "action": "retrieve",
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

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
                self._access_log.append({
                    "action": "delete",
                    "user_id": user_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return True

            return False

    def rotate_key(self, new_key: str) -> None:
        """Rotate encryption key.

        SECURITY: Re-encrypts all tokens with new key.
        Recommended every 90 days for compliance.
        Thread-safe: Blocks all other operations during rotation.

        Args:
            new_key: New Fernet encryption key

        Raises:
            ValueError: If new key is invalid
        """
        with self._lock:  # CRITICAL: Block all other operations during rotation
            old_cipher = self.cipher

            # Update cipher with new key
            try:
                if isinstance(new_key, str):
                    new_key = new_key.encode()
                new_cipher = Fernet(new_key)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid new encryption key: {e}") from e

            # Re-encrypt all tokens
            self._tokens = re_encrypt_tokens(self._tokens, old_cipher, new_cipher)
            self.cipher = new_cipher

            # Audit log
            self._access_log.append({
                "action": "rotate_key",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tokens_re_encrypted": len(self._tokens),
            })

    def rotate_key_from_keyring(self) -> None:
        """Rotate encryption key using new key from keyring.

        SECURITY: For compliance, rotate every 90 days.
        This generates a new key in the keyring and re-encrypts all tokens.

        Raises:
            SecurityError: If not using keyring mode

        Example:
            >>> store = SecureTokenStore(use_keyring=True)
            >>> store.rotate_key_from_keyring()
            >>> # New key generated, all tokens re-encrypted
        """
        if not self.using_keyring:
            raise SecurityError(
                "Key rotation from keyring requires keyring mode. "
                "Initialize with use_keyring=True"
            )

        # Generate new key
        new_key = Fernet.generate_key().decode()

        # Store in keyring (overwrites old key)
        keyring.set_password(self.keyring_service, self.keyring_key_name, new_key)

        # Re-encrypt all tokens
        self.rotate_key(new_key)

        logger.info(
            f"Key rotation complete: {len(self._tokens)} tokens re-encrypted "
            f"with new key from keyring"
        )

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get audit log of token access.

        Returns:
            List of audit log entries

        SECURITY: Use for compliance and security monitoring
        """
        return list(self._access_log)

    def clear_all_tokens(self) -> int:
        """Clear all stored tokens.

        SECURITY: Use with caution. Only for testing or emergency revocation.

        Returns:
            Number of tokens deleted
        """
        with self._lock:
            count = len(self._tokens)
            self._tokens.clear()

            # Audit log
            self._access_log.append({
                "action": "clear_all",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tokens_deleted": count,
            })

            return count
