"""
Data sanitization for observability logging.

Provides multi-layer protection against PII/secret exposure in logs:
- Secret pattern detection (API keys, tokens, passwords)
- PII pattern detection (emails, SSNs, phone numbers, credit cards)
- Configurable redaction policies
- Length limiting for large payloads

Example:
    >>> config = SanitizationConfig(enable_pii_detection=True)
    >>> sanitizer = DataSanitizer(config)
    >>> result = sanitizer.sanitize_text(
    ...     "Contact john.doe@company.com with API key sk-proj-abc123"
    ... )
    >>> result.sanitized_text
    'Contact [EMAIL_REDACTED] with API key [GENERIC_API_KEY_REDACTED]'
"""
import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Sanitization limit constants
DEFAULT_MAX_PROMPT_LENGTH = 5000  # 5KB instead of 10KB
DEFAULT_MAX_RESPONSE_LENGTH = 20000  # 20KB instead of 50KB
HMAC_KEY_SIZE_BYTES = 32  # 256 bits
CONTENT_HASH_TRUNCATE_LENGTH = 16


@dataclass
class SanitizationConfig:
    """
    Configuration for data sanitization.

    SECURITY: Production-secure defaults to prevent sensitive data exposure.
    All redaction flags default to True for defense-in-depth.
    """

    # Secret detection - ALWAYS REDACT
    enable_secret_detection: bool = True
    redact_high_confidence_secrets: bool = True
    redact_medium_confidence_secrets: bool = True  # CHANGED: was False

    # PII detection - ALWAYS ENABLED
    enable_pii_detection: bool = True
    redact_emails: bool = True
    redact_ssn: bool = True
    redact_phone_numbers: bool = True
    redact_credit_cards: bool = True
    redact_ip_addresses: bool = True  # CHANGED: was False (prevents network topology exposure)

    # Length limiting - REDUCED for aggressive truncation
    max_prompt_length: int = DEFAULT_MAX_PROMPT_LENGTH   # CHANGED: was 10000 (5KB instead of 10KB)
    max_response_length: int = DEFAULT_MAX_RESPONSE_LENGTH  # CHANGED: was 50000 (20KB instead of 50KB)

    # Hash generation
    include_hash: bool = True  # For debugging/correlation

    # Allowlist patterns (e.g., example.com emails for tests)
    allowlist_patterns: List[str] = field(default_factory=list)


@dataclass
class SanitizationResult:
    """Result of text sanitization."""
    sanitized_text: str
    original_length: int
    redactions: List[Dict[str, Any]]
    content_hash: Optional[str]

    @property
    def was_sanitized(self) -> bool:
        """Check if any redactions were made."""
        return len(self.redactions) > 0

    @property
    def num_redactions(self) -> int:
        """Get total number of redactions."""
        return len(self.redactions)

    def to_metadata(self) -> Dict[str, Any]:
        """Convert to metadata for logging."""
        return {
            "original_length": self.original_length,
            "sanitized_length": len(self.sanitized_text),
            "num_redactions": len(self.redactions),
            "redaction_types": list(set(r.get("type", "unknown") for r in self.redactions)),
            "content_hash": self.content_hash
        }


class DataSanitizer:
    """
    Sanitizes sensitive data before logging/storage.

    Detects and redacts:
    - Secrets (API keys, tokens, passwords)
    - PII (emails, SSNs, phone numbers, credit cards)
    - Custom patterns

    Example:
        >>> sanitizer = DataSanitizer()
        >>> result = sanitizer.sanitize_text("API key: sk-proj-abc123")
        >>> print(result.sanitized_text)
        'API key: [GENERIC_API_KEY_REDACTED]'
    """

    # Import patterns from centralized registry (single source of truth)
    from src.utils.secret_patterns import (
        GENERIC_SECRET_PATTERNS as _GENERIC_SECRET_PATTERNS,
    )
    from src.utils.secret_patterns import (
        PII_PATTERNS as _PII_PATTERNS,
    )
    from src.utils.secret_patterns import (
        SECRET_PATTERNS as _SECRET_PATTERNS,
    )
    PII_PATTERNS = _PII_PATTERNS
    SECRET_PATTERNS = {**_SECRET_PATTERNS, **_GENERIC_SECRET_PATTERNS}

    def __init__(self, config: Optional[SanitizationConfig] = None):
        """
        Initialize sanitizer with configuration.

        Args:
            config: Sanitization configuration (defaults to secure settings)
        """
        self.config = config or SanitizationConfig()

        # Compile PII patterns for performance
        self.compiled_pii_patterns = {
            name: re.compile(pattern)
            for name, pattern in self.PII_PATTERNS.items()
        }

        # Compile secret patterns for performance
        self.compiled_secret_patterns = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in self.SECRET_PATTERNS.items()
        }

        # Pre-compile allowlist patterns and validate them (OB-02)
        self._compiled_allowlist: list = []
        for pattern in self.config.allowlist_patterns:
            try:
                self._compiled_allowlist.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"Invalid allowlist regex pattern '{pattern}': {e}")

        # SECURITY: Use HMAC key for content hashing to prevent rainbow table attacks
        # Generate or load from environment variable
        hmac_key_hex = os.environ.get('OBSERVABILITY_HMAC_KEY')
        if hmac_key_hex:
            try:
                self._hmac_key = bytes.fromhex(hmac_key_hex)
            except ValueError:
                # Invalid hex, generate new random key
                self._hmac_key = os.urandom(HMAC_KEY_SIZE_BYTES)
        else:
            # Generate random key (32 bytes = 256 bits)
            self._hmac_key = os.urandom(HMAC_KEY_SIZE_BYTES)

    def sanitize_text(
        self,
        text: str,
        context: Optional[str] = None
    ) -> SanitizationResult:
        """
        Sanitize text by detecting and redacting sensitive data.

        Args:
            text: Text to sanitize
            context: Optional context ("prompt", "response", "config")

        Returns:
            SanitizationResult with sanitized text and redaction metadata

        Example:
            >>> sanitizer = DataSanitizer()
            >>> result = sanitizer.sanitize_text(
            ...     "Email john@example.com with key sk-proj-abc123",
            ...     context="prompt"
            ... )
            >>> result.sanitized_text
            'Email [EMAIL_REDACTED] with key [OPENAI_KEY_REDACTED]'
        """
        if not text:
            return SanitizationResult(
                sanitized_text="",
                original_length=0,
                redactions=[],
                content_hash=None
            )

        original_length = len(text)
        redactions: List[Dict[str, Any]] = []
        sanitized = text

        # Step 1: Detect and redact secrets
        if self.config.enable_secret_detection:
            sanitized, secret_redactions = self._redact_secrets(sanitized)
            redactions.extend(secret_redactions)

        # Step 2: Detect and redact PII
        if self.config.enable_pii_detection:
            sanitized, pii_redactions = self._redact_pii(sanitized)
            redactions.extend(pii_redactions)

        # Step 3: Apply length limits
        if context == "prompt" and len(sanitized) > self.config.max_prompt_length:
            sanitized = self._truncate_text(sanitized, self.config.max_prompt_length)
            redactions.append({
                "type": "truncation",
                "original_length": original_length,
                "truncated_to": self.config.max_prompt_length
            })
        elif context == "response" and len(sanitized) > self.config.max_response_length:
            sanitized = self._truncate_text(sanitized, self.config.max_response_length)
            redactions.append({
                "type": "truncation",
                "original_length": original_length,
                "truncated_to": self.config.max_response_length
            })

        # Step 4: Generate HMAC hash for correlation
        # SECURITY: Use HMAC instead of raw SHA256 to prevent rainbow table attacks
        # This allows correlation of sanitized content without enabling brute-force
        content_hash = None
        if self.config.include_hash:
            h = hmac.new(
                self._hmac_key,
                text.encode('utf-8'),
                hashlib.sha256
            )
            content_hash = h.hexdigest()[:CONTENT_HASH_TRUNCATE_LENGTH]

        return SanitizationResult(
            sanitized_text=sanitized,
            original_length=original_length,
            redactions=redactions,
            content_hash=content_hash
        )

    def _redact_secrets(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Detect and redact secrets from text.

        Args:
            text: Text to scan for secrets

        Returns:
            Tuple of (sanitized_text, list of redactions)
        """
        redactions = []
        sanitized = text

        # Process each secret pattern
        for pattern_name, compiled_pattern in self.compiled_secret_patterns.items():
            matches = list(compiled_pattern.finditer(sanitized))

            # Process matches in reverse to maintain positions
            for match in reversed(matches):
                start, end = match.span()
                matched_text = match.group(0)

                # Check if we should redact (always redact high confidence)
                if self.config.redact_high_confidence_secrets:
                    # Create redaction marker
                    redaction_marker = f"[{pattern_name.upper()}_REDACTED]"

                    # Replace in text
                    sanitized = sanitized[:start] + redaction_marker + sanitized[end:]

                    # Record redaction
                    redactions.append({
                        "type": "secret",
                        "pattern": pattern_name,
                        "position": start,
                        "length": len(matched_text),
                        "confidence": "high"
                    })

        return sanitized, redactions

    def _redact_pii(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Detect and redact PII from text.

        Args:
            text: Text to scan for PII

        Returns:
            Tuple of (sanitized_text, list of redactions)
        """
        redactions = []
        sanitized = text

        # Map PII types to config settings
        pii_config = {
            "email": self.config.redact_emails,
            "ssn": self.config.redact_ssn,
            "phone_us": self.config.redact_phone_numbers,
            "credit_card": self.config.redact_credit_cards,
            "ipv4": self.config.redact_ip_addresses,
        }

        # Redact each PII type
        for pii_type, pattern in self.compiled_pii_patterns.items():
            if not pii_config.get(pii_type, False):
                continue

            matches = list(pattern.finditer(sanitized))

            # Process matches in reverse to maintain positions
            for match in reversed(matches):
                start, end = match.span()
                matched_text = match.group(0)

                # Skip if allowlisted
                if self._is_allowlisted(matched_text):
                    continue

                # Create redaction marker
                redaction_marker = f"[{pii_type.upper()}_REDACTED]"

                # Replace in text
                sanitized = sanitized[:start] + redaction_marker + sanitized[end:]

                # Record redaction
                redactions.append({
                    "type": "pii",
                    "pii_type": pii_type,
                    "position": start,
                    "length": len(matched_text)
                })

        return sanitized, redactions

    def _is_allowlisted(self, text: str) -> bool:
        """
        Check if text matches allowlist patterns.

        Uses pre-compiled patterns from __init__ to avoid ReDoS from
        user-supplied patterns being compiled and matched on every call (OB-02).

        Args:
            text: Text to check

        Returns:
            True if text is allowlisted
        """
        for compiled in self._compiled_allowlist:
            try:
                if compiled.search(text):
                    return True
            except (RecursionError, re.error):
                # Pattern caused excessive backtracking - skip it
                continue
        return False

    def _truncate_text(self, text: str, max_length: int) -> str:
        """
        Truncate text to max length with indicator.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text with suffix
        """
        if len(text) <= max_length:
            return text

        suffix = f"...[TRUNCATED:{len(text)-max_length}_chars]"
        return text[:max_length - len(suffix)] + suffix
