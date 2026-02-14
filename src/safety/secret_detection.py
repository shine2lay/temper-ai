"""Secret Detection Safety Policy.

Detects secrets (API keys, passwords, tokens) in code, configurations, and data
to prevent accidental exposure. Uses pattern matching and entropy analysis.
"""

from typing import Any, Dict, List, Optional

from src.safety._secret_detection_helpers import (
    validate_enabled_patterns,
    validate_excluded_paths,
)
from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    ALLOW_TEST_SECRETS_KEY,
    DEFAULT_ENTROPY_THRESHOLD,
    DEFAULT_ENTROPY_THRESHOLD_GENERIC,
    ENTROPY_THRESHOLD_GENERIC_KEY,
    ENTROPY_THRESHOLD_KEY,
    MAX_SHANNON_ENTROPY,
    MIN_ENTROPY_VALUE,
    SECRET_DETECTION_PRIORITY,
    SECRET_DETECTION_SESSION_KEY_SIZE,
)
from src.safety.entropy_analyzer import EntropyAnalyzer
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.pattern_matcher import PatternMatcher
from src.safety.redaction_utils import create_redacted_preview, hash_secret
from src.safety.test_secret_filter import TestSecretFilter
from src.safety.validation import ValidationMixin


class SecretDetectionPolicy(BaseSafetyPolicy, ValidationMixin):
    """Detects secrets in code, config, and data.

    Configuration:
        enabled_patterns: Pattern types to check (default: all 11)
        entropy_threshold: Min entropy for HIGH severity (default: 4.5, range 0-8)
        entropy_threshold_generic: Min entropy for generic patterns (default: 3.5)
        excluded_paths: File paths to skip (default: [])
        allow_test_secrets: Allow test/demo secrets (default: True)

    Pattern Types:
        Specific (always checked): aws_access_key, aws_secret_key, github_token,
            google_api_key, jwt_token, private_key, slack_token, stripe_key,
            connection_string
        Generic (entropy-filtered): generic_api_key, generic_secret
    """

    # Import patterns from centralized registry (single source of truth)
    # SECURITY: All patterns use bounded quantifiers to prevent ReDoS attacks
    from src.utils.secret_patterns import (
        GENERIC_SECRET_PATTERNS as _GENERIC_SECRET_PATTERNS,
    )
    from src.utils.secret_patterns import (
        SECRET_PATTERNS as _SECRET_PATTERNS,
    )
    SECRET_PATTERNS = {**_SECRET_PATTERNS, **_GENERIC_SECRET_PATTERNS}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize secret detection policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration parameters are invalid
        """
        super().__init__(config or {})

        # Validate and store patterns (delegated to helper)
        self.enabled_patterns = validate_enabled_patterns(self.config, self.SECRET_PATTERNS)

        # Validate and store entropy thresholds (inlined)
        self.entropy_threshold = self._validate_float_range(
            self.config.get(ENTROPY_THRESHOLD_KEY, DEFAULT_ENTROPY_THRESHOLD),
            "entropy_threshold",
            min_value=MIN_ENTROPY_VALUE,
            max_value=MAX_SHANNON_ENTROPY,
        )
        self.entropy_threshold_generic = self._validate_float_range(
            self.config.get(ENTROPY_THRESHOLD_GENERIC_KEY, DEFAULT_ENTROPY_THRESHOLD_GENERIC),
            "entropy_threshold_generic",
            min_value=MIN_ENTROPY_VALUE,
            max_value=MAX_SHANNON_ENTROPY,
        )

        # Validate and store excluded paths (delegated to helper)
        self.excluded_paths = validate_excluded_paths(self.config)

        # Validate allow_test_secrets (boolean)
        self.allow_test_secrets = self._validate_boolean(
            self.config.get(ALLOW_TEST_SECRETS_KEY, True),
            "allow_test_secrets",
            default=True,
        )

        # Initialize session key and helper modules
        self._init_helpers()

    def _init_helpers(self) -> None:
        """Initialize session key and helper modules."""
        import os

        # SECURITY: Session-scoped secret key for HMAC-based violation IDs
        self._session_key = os.urandom(SECRET_DETECTION_SESSION_KEY_SIZE)

        self.entropy_analyzer = EntropyAnalyzer()
        self.test_secret_filter = TestSecretFilter(self.allow_test_secrets)
        self.pattern_matcher = PatternMatcher(
            self.enabled_patterns,
            self.SECRET_PATTERNS,
        )
        # Backward compatibility for subclasses
        self.compiled_patterns = self.pattern_matcher.compiled_patterns

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
        """Return policy priority (high - leaked secrets are critical)."""
        return SECRET_DETECTION_PRIORITY

    def _calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of text (0-8 bits per character)."""
        return self.entropy_analyzer.calculate(text)

    def _is_test_secret(self, text: str) -> bool:
        """Check if text appears to be a test/example secret."""
        return self.test_secret_filter.is_test_secret(text)

    def _create_redacted_preview(self, text: str, pattern_name: str) -> str:
        """Create safe preview of detected secret for logging."""
        return create_redacted_preview(text, pattern_name)

    def _hash_secret(self, text: str) -> str:
        """Create HMAC-SHA256 hash of secret for deduplication."""
        return hash_secret(text, self._session_key)

    def get_detection_summary(self) -> Dict[str, Any]:
        """Get summary of detection configuration and capabilities."""
        generic_names = set(self._GENERIC_SECRET_PATTERNS.keys())
        specific_patterns = [
            name for name in self.enabled_patterns if name not in generic_names
        ]
        generic_patterns = [
            name for name in self.enabled_patterns if name in generic_names
        ]

        return {
            "enabled_patterns": self.enabled_patterns,
            "entropy_threshold": self.entropy_threshold,
            "entropy_threshold_generic": self.entropy_threshold_generic,
            "allow_test_secrets": self.allow_test_secrets,
            "excluded_paths": self.excluded_paths,
            "pattern_count": len(self.enabled_patterns),
            "specific_patterns": specific_patterns,
            "generic_patterns": generic_patterns,
            "test_secret_keywords": len(TestSecretFilter.TEST_SECRET_KEYWORDS),
            "test_secret_patterns": len(TestSecretFilter.TEST_SECRET_PATTERNS),
        }

    def _sanitize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize execution context to prevent re-exposure of detected secrets."""
        from src.utils.config_helpers import sanitize_config_for_display

        return sanitize_config_for_display(context)

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ValidationResult:
        """Detect secrets in action content.

        Args:
            action: Action to validate (content, file_path, config, or data).
            context: Execution context.

        Returns:
            ValidationResult with violations for detected secrets.
        """
        content, file_path = self._extract_content(action)
        if not content:
            return ValidationResult(valid=True, policy_name=self.name)

        # Check if path is excluded
        if any(excluded in file_path for excluded in self.excluded_paths):
            return ValidationResult(valid=True, policy_name=self.name)

        violations = self._scan_for_secrets(content, file_path, context)

        valid = not any(
            v.severity >= ViolationSeverity.HIGH for v in violations
        )
        return ValidationResult(
            valid=valid,
            violations=violations,
            policy_name=self.name,
        )

    def _extract_content(self, action: Dict[str, Any]) -> tuple[str, str]:
        """Extract content to scan from action. Returns (content, file_path)."""
        file_path = action.get("file_path", "")
        content = ""
        if "content" in action:
            content = str(action["content"])
        elif "config" in action:
            content = str(action["config"])
        elif "data" in action:
            content = str(action["data"])
        return content, file_path

    def _scan_for_secrets(
        self,
        content: str,
        file_path: str,
        context: Dict[str, Any],
    ) -> List[SafetyViolation]:
        """Scan content for secret patterns."""
        violations: List[SafetyViolation] = []

        for pattern_match in self.pattern_matcher.find_matches(content):
            if self._is_test_secret(pattern_match.secret_value):
                continue

            entropy = self._calculate_entropy(pattern_match.secret_value)

            # SECURITY FIX (code-high-14): Filter generic patterns by entropy
            if pattern_match.pattern_name in ("generic_api_key", "generic_secret"):
                if entropy < self.entropy_threshold_generic:
                    continue

            violation = self._create_secret_violation(
                pattern_match, entropy, file_path, context
            )
            violations.append(violation)

        return violations

    def _create_secret_violation(
        self,
        pattern_match: Any,
        entropy: float,
        file_path: str,
        context: Dict[str, Any],
    ) -> SafetyViolation:
        """Create a SafetyViolation for a detected secret."""
        severity = self._determine_severity(pattern_match.pattern_name, entropy)
        redacted_preview = create_redacted_preview(
            pattern_match.matched_text, pattern_match.pattern_name
        )
        violation_id = hash_secret(pattern_match.matched_text, self._session_key)
        sanitized_context = self._sanitize_context(context)

        return SafetyViolation(
            policy_name=self.name,
            severity=severity,
            message=f"Potential secret detected ({pattern_match.pattern_name}): {redacted_preview}",
            action=f"file_path={file_path}, pattern={pattern_match.pattern_name}",
            context=sanitized_context,
            remediation_hint="Use environment variables or secret management service",
            metadata={
                "pattern_type": pattern_match.pattern_name,
                "entropy": round(entropy, 2),
                "match_position": pattern_match.match_position,
                "match_length": pattern_match.match_length,
                "violation_id": violation_id,
            },
        )

    def _determine_severity(self, pattern_name: str, entropy: float) -> ViolationSeverity:
        """Determine violation severity based on pattern and entropy."""
        if pattern_name in ("private_key", "aws_secret_key"):
            return ViolationSeverity.CRITICAL
        elif pattern_name in ("aws_access_key", "github_token", "generic_api_key", "stripe_key"):
            return ViolationSeverity.HIGH
        elif entropy > self.entropy_threshold:
            return ViolationSeverity.HIGH
        else:
            return ViolationSeverity.MEDIUM
