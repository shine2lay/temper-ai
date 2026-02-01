"""Secret Detection Safety Policy.

Detects secrets (API keys, passwords, tokens) in code, configurations, and data
to prevent accidental exposure. Uses pattern matching and entropy analysis to
identify potential secrets.

Common patterns detected:
- API keys (AWS, Google, Azure, GitHub, etc.)
- Authentication tokens (JWT, OAuth, etc.)
- Passwords and credentials
- Private keys and certificates
- Database connection strings
"""
import re
import hashlib
from typing import Dict, Any, List, Optional
from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity


class SecretDetectionPolicy(BaseSafetyPolicy):
    """Detects secrets in code, config, and data.

    Configuration options:
        enabled_patterns: List of pattern types to check (default: all)
        entropy_threshold: Minimum entropy for flagging (default: 4.5)
        excluded_paths: File paths to exclude from scanning
        allow_test_secrets: Whether to allow obvious test secrets (default: True)

    Example:
        >>> config = {
        ...     "enabled_patterns": ["api_key", "password"],
        ...     "entropy_threshold": 5.0
        ... }
        >>> policy = SecretDetectionPolicy(config)
        >>> result = policy.validate(
        ...     action={"content": "api_key=sk_live_abc123xyz"},
        ...     context={}
        ... )
    """

    # Common secret patterns (regex)
    SECRET_PATTERNS = {
        "aws_access_key": r"AKIA[0-9A-Z]{16}",
        "aws_secret_key": r"aws(.{0,20})?['\"][0-9a-zA-Z/+]{40}['\"]",
        "github_token": r"gh[pousr]_[0-9a-zA-Z]{36}",
        "generic_api_key": r"(api[_-]?key|apikey)['\"]?\s*[:=]\s*['\"]?([0-9a-zA-Z_\-]{20,})['\"]?",
        "generic_secret": r"(secret|password|passwd|pwd)['\"]?\s*[:=]\s*['\"]?([^'\"\s]{8,})['\"]?",
        "jwt_token": r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+",
        "private_key": r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----",
        "google_api_key": r"AIza[0-9A-Za-z\\-_]{35}",
        "slack_token": r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}",
        "stripe_key": r"(sk|pk)_(test|live)_[0-9a-zA-Z]{24,}",
        "connection_string": r"(mongodb|postgres|mysql|redis)://[^'\"\s]+"
    }

    # Test/example secrets to allow
    TEST_SECRETS = [
        "test",
        "example",
        "demo",
        "placeholder",
        "changeme",
        "password123",
        "dummy",
        "fake"
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize secret detection policy.

        Args:
            config: Policy configuration (optional)
        """
        super().__init__(config or {})

        # Configuration
        self.enabled_patterns = self.config.get("enabled_patterns", list(self.SECRET_PATTERNS.keys()))
        self.entropy_threshold = self.config.get("entropy_threshold", 4.5)
        self.excluded_paths = self.config.get("excluded_paths", [])
        self.allow_test_secrets = self.config.get("allow_test_secrets", True)

        # SECURITY: Session-scoped secret key for HMAC-based violation IDs
        # Provides deduplication (same secret = same ID) without rainbow table risk
        import os
        self._session_key = os.urandom(32)

        # Compile regex patterns
        self.compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in self.SECRET_PATTERNS.items()
            if name in self.enabled_patterns
        }

    @property
    def name(self) -> str:
        """Return policy name."""
        return "secret_detection"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority.

        Secret detection has very high priority since leaked secrets are critical.
        """
        return 95

    def _calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of text.

        High entropy suggests random/encrypted data (like secrets).

        Args:
            text: Text to analyze

        Returns:
            Entropy value (0-8 for bits per character)
        """
        if not text:
            return 0.0

        # Count character frequencies
        freq: Dict[str, int] = {}
        for char in text:
            freq[char] = freq.get(char, 0) + 1

        # Calculate entropy
        import math
        length = len(text)
        entropy = 0.0
        for count in freq.values():
            p = count / length
            entropy -= p * math.log2(p)

        return entropy

    def _is_test_secret(self, text: str) -> bool:
        """Check if text appears to be a test/example secret.

        Args:
            text: Text to Check

        Returns:
            True if likely a test secret
        """
        if not self.allow_test_secrets:
            return False

        text_lower = text.lower()
        return any(
            test_word in text_lower
            for test_word in self.TEST_SECRETS
        )

    def _create_redacted_preview(self, text: str, pattern_name: str) -> str:
        """Create safe preview of detected secret.

        Shows pattern type and length, not actual value.

        Args:
            text: Detected secret text
            pattern_name: Type of secret detected

        Returns:
            Redacted preview safe for logging

        Examples:
            >>> _create_redacted_preview("AKIAIOSFODNN7EXAMPLE", "aws_access_key")
            '[AWS_ACCESS_KEY:20_chars]'

            >>> _create_redacted_preview("sk-proj-abc123def456...", "generic_api_key")
            '[GENERIC_API_KEY:50_chars]'
        """
        length = len(text)
        pattern_upper = pattern_name.upper()
        return f"[{pattern_upper}:{length}_chars]"

    def _hash_secret(self, text: str) -> str:
        """Create SHA256 hash of secret for deduplication.

        Allows tracking same secret across multiple violations without
        storing the actual value.

        Args:
            text: Secret text

        Returns:
            SHA256 hash (hex, first 16 characters)

        Example:
            >>> _hash_secret("AKIAIOSFODNN7EXAMPLE")
            'a1b2c3d4e5f6g7h8'  # First 16 chars of SHA256
        """
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Detect secrets in action content.

        Args:
            action: Action to validate, may contain:
                - content: Text content to scan
                - file_path: Path to file being modified
                - config: Configuration data to scan
            context: Execution context

        Returns:
            ValidationResult with violations for detected secrets
        """
        violations: List[SafetyViolation] = []

        # Extract content to scan
        content = ""
        file_path = action.get("file_path", "")

        # Check if path is excluded
        if any(excluded in file_path for excluded in self.excluded_paths):
            return ValidationResult(valid=True, policy_name=self.name)

        # Collect content from various sources
        if "content" in action:
            content = str(action["content"])
        elif "config" in action:
            content = str(action["config"])
        elif "data" in action:
            content = str(action["data"])

        if not content:
            return ValidationResult(valid=True, policy_name=self.name)

        # Scan for pattern matches
        for pattern_name, pattern_regex in self.compiled_patterns.items():
            matches = pattern_regex.finditer(content)
            for match in matches:
                matched_text = match.group(0)

                # Skip if likely a test secret
                if self._is_test_secret(matched_text):
                    continue

                # Extract actual secret value (usually in capture group)
                secret_value = match.group(2) if match.lastindex and match.lastindex >= 2 else matched_text

                # Calculate entropy
                entropy = self._calculate_entropy(secret_value)

                # Determine severity based on pattern and entropy
                if pattern_name in ["private_key", "aws_secret_key"]:
                    severity = ViolationSeverity.CRITICAL
                elif pattern_name in ["aws_access_key", "github_token", "generic_api_key", "stripe_key"]:
                    # API keys and tokens should always block
                    severity = ViolationSeverity.HIGH
                elif entropy > self.entropy_threshold:
                    severity = ViolationSeverity.HIGH
                else:
                    severity = ViolationSeverity.MEDIUM

                # Create safe redacted preview (never expose actual secret)
                redacted_preview = self._create_redacted_preview(matched_text, pattern_name)

                # SECURITY: Generate violation ID using HMAC for secure deduplication
                # HMAC ensures: same secret = same ID (deduplication) without rainbow table risk
                # Session key rotates per process, so IDs are not correlatable across sessions
                import hmac
                violation_id = hmac.new(
                    self._session_key,
                    matched_text.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()[:16]  # 16 chars = 64 bits = low collision probability

                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=severity,
                    message=f"Potential secret detected ({pattern_name}): {redacted_preview}",
                    action=f"file_path={file_path}, pattern={pattern_name}",
                    context=context,
                    remediation_hint="Use environment variables or secret management service",
                    metadata={
                        "pattern_type": pattern_name,
                        "entropy": round(entropy, 2),
                        "match_position": match.start(),
                        "match_length": len(matched_text),
                        "violation_id": violation_id  # For deduplication within session
                    }
                ))

        # Determine validity (invalid if any HIGH or CRITICAL violations)
        valid = not any(
            v.severity >= ViolationSeverity.HIGH
            for v in violations
        )

        return ValidationResult(
            valid=valid,
            violations=violations,
            policy_name=self.name
        )
