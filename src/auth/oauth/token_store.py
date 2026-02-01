"""Secure OAuth Token Storage.

SECURITY: Encrypts tokens at rest using Fernet (symmetric encryption).
Key is stored separately from encrypted data (environment variable).

Defense Layers:
1. Fernet encryption (AES-128-CBC with HMAC for authenticity)
2. Key rotation support
3. Automatic expiry tracking
4. Audit logging of token access

References:
- Fernet spec: https://github.com/fernet/spec/blob/master/Spec.md
- Cryptography lib: https://cryptography.io/en/latest/fernet/
"""
from cryptography.fernet import Fernet, InvalidToken
from typing import Optional, Dict, Any, List
import json
import os
import threading
from datetime import datetime, timedelta


class SecureTokenStore:
    """Encrypts and stores OAuth tokens.

    SECURITY NOTICE:
    - Tokens encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
    - Encryption key must be stored securely (environment variable)
    - Key rotation recommended every 90 days
    - In-memory storage (use database in production)

    Example:
        >>> # Generate encryption key (one time setup)
        >>> from cryptography.fernet import Fernet
        >>> key = Fernet.generate_key()
        >>> os.environ['OAUTH_TOKEN_ENCRYPTION_KEY'] = key.decode()

        >>> # Use token store
        >>> store = SecureTokenStore()
        >>> store.store_token("user_123", {
        ...     "access_token": "ya29.a0...",
        ...     "refresh_token": "1//...",
        ... }, expires_in=3600)
        >>> token = store.retrieve_token("user_123")
        >>> print(token["access_token"])
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize token store.

        Args:
            encryption_key: Base64-encoded Fernet key (default: from env)

        Raises:
            ValueError: If encryption key not provided or invalid
        """
        # Get encryption key from environment or parameter
        key = encryption_key or os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY")

        if not key:
            raise ValueError(
                "Encryption key required. Set OAUTH_TOKEN_ENCRYPTION_KEY environment variable.\n"
                "Generate with: python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )

        # Initialize Fernet cipher
        try:
            if isinstance(key, str):
                key = key.encode()
            self.cipher = Fernet(key)
        except Exception as e:
            raise ValueError(f"Invalid encryption key: {e}")

        # In-memory storage (use database in production)
        # Key: user_id, Value: encrypted token bytes
        self._tokens: Dict[str, bytes] = {}

        # Audit log (use proper logging in production)
        self._access_log: List[Dict[str, Any]] = []

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
                "stored_at": datetime.utcnow().isoformat(),
                "expires_at": (
                    datetime.utcnow() + timedelta(seconds=expires_in)
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
                "timestamp": datetime.utcnow().isoformat(),
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
            except (InvalidToken, json.JSONDecodeError) as e:
                # Decryption failed (corrupted data, wrong key, or tampered)
                # SECURITY: Delete corrupted token (lock is reentrant, safe to call)
                self.delete_token(user_id)
                return None

            # Check expiry
            if token_data.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(token_data["expires_at"])
                    if datetime.utcnow() > expires_at:
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
                "timestamp": datetime.utcnow().isoformat(),
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
                    "timestamp": datetime.utcnow().isoformat(),
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

        Example:
            >>> new_key = Fernet.generate_key().decode()
            >>> store.rotate_key(new_key)
        """
        with self._lock:  # CRITICAL: Block all other operations during rotation
            # Decrypt all tokens with old key
            decrypted_tokens = {}
            for user_id in list(self._tokens.keys()):
                # Direct access to avoid nested locking (already in lock)
                encrypted = self._tokens.get(user_id)
                if encrypted:
                    try:
                        decrypted = self.cipher.decrypt(encrypted)
                        token_data = json.loads(decrypted.decode())
                        decrypted_tokens[user_id] = token_data
                    except (InvalidToken, json.JSONDecodeError):
                        # Skip corrupted tokens
                        continue

            # Update cipher with new key
            try:
                if isinstance(new_key, str):
                    new_key = new_key.encode()
                self.cipher = Fernet(new_key)
            except Exception as e:
                raise ValueError(f"Invalid new encryption key: {e}")

            # Re-encrypt with new key
            self._tokens.clear()
            for user_id, token_data in decrypted_tokens.items():
                # Calculate remaining expiry
                if token_data.get("expires_at"):
                    try:
                        expires_at = datetime.fromisoformat(token_data["expires_at"])
                        expires_in = int((expires_at - datetime.utcnow()).total_seconds())
                        if expires_in > 0:
                            # Remove metadata before re-storing
                            clean_token = {
                                k: v
                                for k, v in token_data.items()
                                if k not in ["stored_at", "expires_at"]
                            }
                            # Direct encryption to avoid nested locking
                            token_with_metadata = {
                                **clean_token,
                                "stored_at": datetime.utcnow().isoformat(),
                                "expires_at": (
                                    datetime.utcnow() + timedelta(seconds=expires_in)
                                ).isoformat(),
                            }
                            token_json = json.dumps(token_with_metadata)
                            encrypted = self.cipher.encrypt(token_json.encode())
                            self._tokens[user_id] = encrypted
                    except (ValueError, TypeError):
                        # Skip tokens with invalid expiry
                        continue

            # Audit log
            self._access_log.append({
                "action": "rotate_key",
                "timestamp": datetime.utcnow().isoformat(),
                "tokens_re_encrypted": len(decrypted_tokens),
            })

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get audit log of token access.

        Returns:
            List of audit log entries

        SECURITY: Use for compliance and security monitoring
        """
        return self._access_log.copy()

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
                "timestamp": datetime.utcnow().isoformat(),
                "tokens_deleted": count,
            })

            return count
