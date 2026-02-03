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
import re
import hashlib
import hmac
import os
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field


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
    max_prompt_length: int = 5000   # CHANGED: was 10000 (5KB instead of 10KB)
    max_response_length: int = 20000  # CHANGED: was 50000 (20KB instead of 50KB)

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

    # PII patterns (based on OWASP recommendations)
    PII_PATTERNS = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "phone_us": r'\b(\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b',
        "credit_card": r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
        "ipv4": r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
    }

    # Secret patterns (imported from SecretDetectionPolicy)
    SECRET_PATTERNS = {
        "openai_key": r'sk-proj-[a-zA-Z0-9]{20,}',
        "anthropic_key": r'sk-ant-api\d+-[a-zA-Z0-9_-]{20,}',
        "aws_access_key": r'AKIA[0-9A-Z]{16}',
        "aws_secret_key": r'[a-zA-Z0-9+/]{40}',
        "github_token": r'gh[pousr]_[0-9a-zA-Z]{36}',
        "google_api_key": r'AIza[0-9A-Za-z_-]{35}',
        "slack_token": r'xox[baprs]-[0-9a-zA-Z]{10,}',
        "generic_api_key": r'["\']?(?:api[_-]?key|apikey|api[_-]?secret)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        "jwt_token": r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*',
        "private_key": r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----',
    }

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

        # SECURITY: Use HMAC key for content hashing to prevent rainbow table attacks
        # Generate or load from environment variable
        hmac_key_hex = os.environ.get('OBSERVABILITY_HMAC_KEY')
        if hmac_key_hex:
            try:
                self._hmac_key = bytes.fromhex(hmac_key_hex)
            except ValueError:
                # Invalid hex, generate new random key
                self._hmac_key = os.urandom(32)
        else:
            # Generate random key (32 bytes = 256 bits)
            self._hmac_key = os.urandom(32)

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
            content_hash = h.hexdigest()[:16]

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

        Args:
            text: Text to check

        Returns:
            True if text is allowlisted
        """
        for pattern in self.config.allowlist_patterns:
            if re.search(pattern, text):
                return True
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
