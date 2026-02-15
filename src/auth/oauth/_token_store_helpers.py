"""Helper functions extracted from SecureTokenStore to reduce class size.

These are internal implementation details - use SecureTokenStore's public API.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from src.auth.constants import FIELD_EXPIRES_AT, FIELD_STORED_AT

logger = logging.getLogger(__name__)

# Optional keyring import
try:
    import keyring  # type: ignore[import-not-found]
    from keyring.errors import KeyringError  # type: ignore[import-not-found]
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    KeyringError = Exception

from src.shared.utils.exceptions import SecurityError


def get_or_create_keyring_key(
    keyring_service: str,
    keyring_key_name: str,
) -> str:
    """Get encryption key from OS keyring or create new one.

    Args:
        keyring_service: Keyring service name
        keyring_key_name: Keyring key identifier

    Returns:
        Fernet encryption key (base64-encoded)

    Raises:
        KeyringError: If keyring backend not available
        ImportError: If keyring library not installed
    """
    if not KEYRING_AVAILABLE:
        raise ImportError(
            "Keyring library not installed. "
            "Install with: pip install keyring"
        )

    key: Optional[str] = keyring.get_password(keyring_service, keyring_key_name)

    if key is None:
        logger.info(
            f"Generating new encryption key in OS keyring: "
            f"{keyring_service}/{keyring_key_name}"
        )
        new_key: str = Fernet.generate_key().decode()
        keyring.set_password(keyring_service, keyring_key_name, new_key)
        return new_key

    return key


def _try_keyring_acquisition(
    keyring_service: str, keyring_key_name: str, require_keyring: bool
) -> Optional[str]:
    """Try to acquire key from OS keyring.

    Args:
        keyring_service: Keyring service name
        keyring_key_name: Keyring key identifier
        require_keyring: Fail if keyring unavailable

    Returns:
        Key string or None if keyring unavailable and not required

    Raises:
        SecurityError: If keyring required but unavailable
    """
    try:
        key = get_or_create_keyring_key(keyring_service, keyring_key_name)
        logger.info(f"Using OS keyring for key storage: {keyring_service}/{keyring_key_name}")
        return key
    except KeyringError as e:
        if require_keyring:
            raise SecurityError(
                f"Keyring required but not available: {e}\n"
                "Install keyring backend: pip install keyring"
            ) from e
        logger.warning(
            f"OS keyring backend not configured ({e}), falling back to environment variable. "
            "For production security, configure keyring backend."
        )
    except ImportError as e:
        if require_keyring:
            raise SecurityError(
                f"Keyring library required but not installed: {e}\n"
                "Install with: pip install keyring"
            ) from e
        logger.warning(
            "Keyring library not installed, falling back to environment variable. "
            "For production security, install keyring: pip install keyring"
        )
    except (RuntimeError, OSError, AttributeError) as e:
        logger.error(f"Keyring error: {e}", exc_info=True)
        if require_keyring:
            raise SecurityError(
                f"Keyring error (keyring required): {e}\n"
                "Check keyring configuration and logs"
            ) from e
        logger.warning(
            "Falling back to environment variable due to keyring error. "
            "See logs for details."
        )
    return None


def _try_env_acquisition() -> Optional[str]:
    """Try to acquire key from environment variable.

    Returns:
        Key string or None if not found
    """
    key = os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY")
    if not key:
        return None

    logger.warning(
        "SECURITY: Using environment variable for encryption key. "
        "For production, use OS keyring (install 'keyring' package)."
    )
    env_name = (
        os.getenv("ENVIRONMENT")
        or os.getenv("ENV")
        or os.getenv("APP_ENV")
        or ""
    ).lower()
    if env_name in ("production", "prod"):
        logger.warning(
            "PRODUCTION SECURITY WARNING: Encryption key loaded from "
            "environment variable OAUTH_TOKEN_ENCRYPTION_KEY in a "
            "production environment (%s). Environment variables are "
            "visible in /proc/<pid>/environ, process listings, and "
            "may leak into logs or crash dumps. Migrate to OS keyring "
            "for compliance (PCI DSS, SOC 2).",
            env_name,
        )
    return key


def acquire_encryption_key(
    encryption_key: Optional[str],
    use_keyring: bool,
    keyring_service: str,
    keyring_key_name: str,
    require_keyring: bool,
) -> tuple:
    """Acquire encryption key from available sources.

    Key acquisition priority:
    1. Explicit parameter (testing/override)
    2. OS Keyring (most secure)
    3. Environment variable (fallback)
    4. Fail (no insecure defaults)
    """
    if encryption_key:
        logger.warning("Using explicit encryption key. For production, use OS keyring.")
        return encryption_key, False

    if use_keyring:
        key = _try_keyring_acquisition(keyring_service, keyring_key_name, require_keyring)
        if key is not None:
            return key, True

    env_key = _try_env_acquisition()
    if env_key:
        return env_key, False

    raise ValueError(
        "No encryption key available. Options:\n"
        "1. Install keyring: pip install keyring (RECOMMENDED for production)\n"
        "2. Set OAUTH_TOKEN_ENCRYPTION_KEY environment variable (development only)\n"
        "3. Pass encryption_key parameter (testing only)\n"
        "\n"
        "Generate key: python -c 'from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())'"
    )


def _decrypt_and_parse_token(encrypted: bytes, old_cipher: Fernet) -> Optional[dict]:
    """Decrypt and parse token data.

    Args:
        encrypted: Encrypted token bytes
        old_cipher: Fernet cipher with old key

    Returns:
        Parsed token dict or None if decryption fails
    """
    try:
        decrypted = old_cipher.decrypt(encrypted)
        result: Optional[dict] = json.loads(decrypted.decode())
        return result
    except (InvalidToken, json.JSONDecodeError):
        return None


def _re_encrypt_single_token(
    token_data: dict, new_cipher: Fernet
) -> Optional[bytes]:
    """Re-encrypt a single token with new cipher.

    Args:
        token_data: Decrypted token data
        new_cipher: Fernet cipher with new key

    Returns:
        Re-encrypted token bytes or None if processing fails
    """
    try:
        # Handle tokens with expiration
        if token_data.get(FIELD_EXPIRES_AT):
            expires_at = datetime.fromisoformat(token_data[FIELD_EXPIRES_AT])
            expires_in = int((expires_at - datetime.now(timezone.utc)).total_seconds())
            if expires_in <= 0:
                return None  # Skip expired tokens

            clean_token = {
                k: v for k, v in token_data.items()
                if k not in [FIELD_STORED_AT, FIELD_EXPIRES_AT]
            }
            token_with_metadata = {
                **clean_token,
                FIELD_STORED_AT: datetime.now(timezone.utc).isoformat(),
                FIELD_EXPIRES_AT: (
                    datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                ).isoformat(),
            }
        else:
            # Handle tokens without expiration
            clean_token = {
                k: v for k, v in token_data.items()
                if k not in [FIELD_STORED_AT]
            }
            token_with_metadata = {
                **clean_token,
                FIELD_STORED_AT: datetime.now(timezone.utc).isoformat(),
            }

        token_json = json.dumps(token_with_metadata)
        return new_cipher.encrypt(token_json.encode())

    except (ValueError, TypeError):
        return None


def re_encrypt_tokens(
    tokens: Dict[str, bytes],
    old_cipher: Fernet,
    new_cipher: Fernet,
) -> Dict[str, bytes]:
    """Re-encrypt all tokens with a new cipher."""
    re_encrypted = {}

    for user_id in list(tokens.keys()):
        encrypted = tokens.get(user_id)
        if not encrypted:
            continue

        # Decrypt and parse
        token_data = _decrypt_and_parse_token(encrypted, old_cipher)
        if not token_data:
            continue

        # Re-encrypt with new cipher
        new_encrypted = _re_encrypt_single_token(token_data, new_cipher)
        if new_encrypted:
            re_encrypted[user_id] = new_encrypted

    return re_encrypted
