"""Safe redaction and hashing utilities for logging.

Provides functions to create safe previews of detected secrets
and generate deterministic hashes for deduplication without
exposing actual values.
"""

import hashlib
import hmac

# Hash prefix length for deduplication (16 chars = 64 bits)
HASH_PREFIX_LENGTH = 16


def create_redacted_preview(text: str, pattern_name: str) -> str:
    """Create safe preview of detected secret for logging.

    Shows pattern type and length, never exposes actual value.

    Args:
        text: Detected secret text
        pattern_name: Type of secret (e.g., "aws_access_key")

    Returns:
        Redacted preview safe for logging

    Examples:
        >>> create_redacted_preview("AKIAIOSFODNN7EXAMPLE", "aws_access_key")
        '[AWS_ACCESS_KEY:20_chars]'

        >>> create_redacted_preview("sk-proj-abc123def456", "openai_key")
        '[OPENAI_KEY:20_chars]'
    """
    length = len(text)
    pattern_upper = pattern_name.upper()
    return f"[{pattern_upper}:{length}_chars]"


def hash_secret(text: str, session_key: bytes) -> str:
    """Create HMAC-SHA256 hash of secret for deduplication.

    Allows tracking same secret across violations without storing
    the actual value. Session-scoped key prevents rainbow tables.

    Args:
        text: Secret text
        session_key: Session-scoped random key (32 bytes)

    Returns:
        HMAC-SHA256 hash (hex, first 16 characters = 64 bits)

    Example:
        >>> import os
        >>> key = os.urandom(32)
        >>> hash_secret("AKIAIOSFODNN7EXAMPLE", key)
        'a1b2c3d4e5f6g7h8'  # First 16 chars (deterministic)
    """
    return hmac.new(session_key, text.encode("utf-8"), hashlib.sha256).hexdigest()[
        :HASH_PREFIX_LENGTH
    ]
