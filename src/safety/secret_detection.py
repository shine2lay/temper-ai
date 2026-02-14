"""Secret Detection Safety Policy.

From src.safety.constants imports for config keys.
"""

from src.safety.constants import (
    ALLOW_TEST_SECRETS_KEY,
    ENTROPY_THRESHOLD_GENERIC_KEY,
    ENTROPY_THRESHOLD_KEY,
)

"""Original docstring:

Detects secrets (API keys, passwords, tokens) in code, configurations, and data
to prevent accidental exposure. Uses pattern matching and entropy analysis to
identify potential secrets.

Common patterns detected:
- API keys (AWS, Google, Azure, GitHub, etc.)
- Authentication tokens (JWT, OAuth, etc.)
- Passwords and credentials
- Private keys and certificates
- Database connection strings

Security Features:
- Entropy-based filtering for generic patterns (reduces false positives)
- ReDoS prevention via upper-bounded quantifiers
- Expanded test secret allowlist (sample, template, mock, etc.)
- Function call detection (filters get_secret(), etc.)
- Configurable sensitivity (entropy_threshold, entropy_threshold_generic)

False Positive Reduction:
- Low-entropy strings filtered (e.g., "aaaaaaa", "your-api-key-here")
- Documentation placeholders filtered (e.g., "your-", "-here", "todo")
- Function calls filtered (e.g., "get_api_key()", "load_from_environment()")
- Test/demo keywords filtered (e.g., "test", "example", "demo", "mock")

Integration with External Libraries:
To integrate with external secret scanning libraries (e.g., detect-secrets,
truffleHog, gitleaks), consider:
1. Subclass SecretDetectionPolicy and override _validate_impl()
2. Call external scanner via subprocess or API
3. Merge violations from both sources (deduplicate by violation_id)
4. Example:
    class EnhancedSecretDetectionPolicy(SecretDetectionPolicy):
        def _validate_impl(self, action, context):
            # Run built-in detection
            result = super()._validate_impl(action, context)
            # Run external scanner (e.g., detect-secrets)
            external_violations = self._run_external_scanner(action)
            # Merge and deduplicate
            all_violations = result.violations + external_violations
            return ValidationResult(valid=len(all_violations) == 0, violations=all_violations)
"""
from typing import Any, Dict, List, Optional

from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    DEFAULT_ENTROPY_THRESHOLD,
    DEFAULT_ENTROPY_THRESHOLD_GENERIC,
    MAX_EXCLUDED_PATH_LENGTH,
    MAX_EXCLUDED_PATHS,
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

    Configuration options:
        enabled_patterns: List of pattern types to check (default: all 11 patterns)
        entropy_threshold: Minimum entropy for HIGH severity flagging (default: 4.5)
            - Applies to all patterns to determine severity
            - Range: 0.0 to 8.0 (Shannon entropy bits per character)
            - Higher = stricter (fewer false positives, may miss some secrets)
        entropy_threshold_generic: Minimum entropy for generic patterns (default: 3.5)
            - Filters generic_api_key and generic_secret patterns
            - Must be >= this to be considered a potential secret
            - Range: 0.0 to 8.0
            - Lower = more sensitive (more detections, more false positives)
        excluded_paths: File paths to exclude from scanning (default: [])
        allow_test_secrets: Whether to allow obvious test secrets (default: True)
            - Filters test/demo/example/mock/placeholder keywords
            - Set to False for strict scanning (e.g., pre-commit hooks)

    Pattern Types:
        Specific patterns (always checked, no entropy filter):
        - aws_access_key, aws_secret_key, github_token, google_api_key
        - jwt_token, private_key, slack_token, stripe_key, connection_string

        Generic patterns (filtered by entropy_threshold_generic):
        - generic_api_key, generic_secret

    Example:
        >>> # Default configuration (balanced - good for development)
        >>> policy = SecretDetectionPolicy()
        >>> result = policy.validate(
        ...     action={"content": "api_key=sk_live_abc123xyz"},
        ...     context={}
        ... )

        >>> # Strict configuration (for pre-commit hooks)
        >>> config = {
        ...     "allow_test_secrets": False,
        ...     "entropy_threshold_generic": 3.0,  # More sensitive
        ...     "excluded_paths": [".git/", "node_modules/", "venv/"]
        ... }
        >>> strict_policy = SecretDetectionPolicy(config)

        >>> # Specific patterns only (reduce false positives)
        >>> config = {
        ...     "enabled_patterns": ["aws_access_key", "github_token", "private_key"],
        ...     "entropy_threshold": 5.0  # Stricter severity threshold
        ... }
        >>> specific_policy = SecretDetectionPolicy(config)
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

        # SECURITY (code-high-12): Validate all configuration inputs
        # Prevents type confusion, negative values, and extreme values

        # Validate and store patterns
        self.enabled_patterns = self._init_enabled_patterns()

        # Validate and store entropy thresholds
        self._init_entropy_thresholds()

        # Validate and store excluded paths
        self.excluded_paths = self._init_excluded_paths()

        # Validate allow_test_secrets (boolean)
        self.allow_test_secrets = self._validate_boolean(
            self.config.get(ALLOW_TEST_SECRETS_KEY,True),
            "allow_test_secrets",
            default=True
        )

        # Initialize session key and helper modules
        self._init_helpers()

    def _init_enabled_patterns(self) -> List[str]:
        """Initialize and validate enabled patterns.

        Returns:
            List of validated enabled patterns

        Raises:
            ValueError: If validation fails
        """
        enabled_patterns_raw = self.config.get("enabled_patterns", list(self.SECRET_PATTERNS.keys()))
        if not isinstance(enabled_patterns_raw, list):
            # Convert single string to list for convenience
            if isinstance(enabled_patterns_raw, str):
                enabled_patterns_raw = [enabled_patterns_raw]
            else:
                raise ValueError(
                    f"enabled_patterns must be a list of strings, got {type(enabled_patterns_raw).__name__}"
                )

        # Validate each pattern name exists
        valid_patterns = set(self.SECRET_PATTERNS.keys())
        enabled_patterns = []
        for pattern in enabled_patterns_raw:
            if not isinstance(pattern, str):
                raise ValueError(f"enabled_patterns items must be strings, got {type(pattern).__name__}")
            if pattern not in valid_patterns:
                raise ValueError(
                    f"Unknown pattern '{pattern}'. Valid patterns: {', '.join(sorted(valid_patterns))}"
                )
            enabled_patterns.append(pattern)

        if not enabled_patterns:
            raise ValueError("enabled_patterns cannot be empty. At least one pattern must be enabled.")

        return enabled_patterns

    def _init_entropy_thresholds(self) -> None:
        """Initialize and validate entropy thresholds."""
        # Shannon entropy for bytes is max 8.0 bits per character
        self.entropy_threshold = self._validate_float_range(
            self.config.get(ENTROPY_THRESHOLD_KEY,DEFAULT_ENTROPY_THRESHOLD),
            "entropy_threshold",
            min_value=MIN_ENTROPY_VALUE,
            max_value=MAX_SHANNON_ENTROPY
        )

        # SECURITY: Minimum entropy for generic patterns to reduce false positives
        self.entropy_threshold_generic = self._validate_float_range(
            self.config.get(ENTROPY_THRESHOLD_GENERIC_KEY,DEFAULT_ENTROPY_THRESHOLD_GENERIC),
            "entropy_threshold_generic",
            min_value=MIN_ENTROPY_VALUE,
            max_value=MAX_SHANNON_ENTROPY
        )

    def _init_excluded_paths(self) -> List[str]:
        """Initialize and validate excluded paths.

        Returns:
            List of validated excluded paths

        Raises:
            ValueError: If validation fails
        """
        excluded_paths_raw = self.config.get("excluded_paths", [])
        if not isinstance(excluded_paths_raw, list):
            raise ValueError(
                f"excluded_paths must be a list of strings, got {type(excluded_paths_raw).__name__}"
            )

        excluded_paths = []
        for path in excluded_paths_raw:
            if not isinstance(path, str):
                raise ValueError(f"excluded_paths items must be strings, got {type(path).__name__}")
            if len(path) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(f"excluded_paths items must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(path)}")
            excluded_paths.append(path)

        if len(excluded_paths) > MAX_EXCLUDED_PATHS:
            raise ValueError(f"excluded_paths must have <= {MAX_EXCLUDED_PATHS} items, got {len(excluded_paths)}")

        return excluded_paths

    def _init_helpers(self) -> None:
        """Initialize session key and helper modules."""
        # SECURITY: Session-scoped secret key for HMAC-based violation IDs
        # Provides deduplication (same secret = same ID) without rainbow table risk
        import os
        self._session_key = os.urandom(SECRET_DETECTION_SESSION_KEY_SIZE)

        # Initialize helper modules
        self.entropy_analyzer = EntropyAnalyzer()
        self.test_secret_filter = TestSecretFilter(self.allow_test_secrets)
        self.pattern_matcher = PatternMatcher(
            self.enabled_patterns,
            self.SECRET_PATTERNS
        )

        # Keep compiled_patterns for backward compatibility (if needed by subclasses)
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
        """Return policy priority.

        Secret detection has very high priority since leaked secrets are critical.
        """
        return SECRET_DETECTION_PRIORITY

    def _calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of text.

        High entropy suggests random/encrypted data (like secrets).

        Args:
            text: Text to analyze

        Returns:
            Entropy value (0-8 for bits per character)
        """
        return self.entropy_analyzer.calculate(text)

    def _is_test_secret(self, text: str) -> bool:
        """Check if text appears to be a test/example secret.

        Uses two types of matching:
        1. Keyword matching (substring) - for words like "test", "demo", "example"
        2. Pattern matching (exact) - for patterns like "abcdefgh", "12345678"
        3. Function call detection - filters out function calls like "get_secret()"

        This prevents false positives where legitimate secrets happen to contain
        common patterns as substrings (e.g., "sk_live_...abcdefgh..." is NOT a test secret).

        Args:
            text: Text to Check

        Returns:
            True if likely a test secret or non-literal value
        """
        return self.test_secret_filter.is_test_secret(text)

    def _create_redacted_preview(self, text: str, pattern_name: str) -> str:
        """Create safe preview of detected secret.

        Shows pattern type and length, not actual value.

        Args:
            text: Detected secret text
            pattern_name: Type of secret detected

        Returns:
            Redacted preview safe for logging
        """
        return create_redacted_preview(text, pattern_name)

    def _hash_secret(self, text: str) -> str:
        """Create hash of secret for deduplication.

        Allows tracking same secret across multiple violations without
        storing the actual value.

        Args:
            text: Secret text

        Returns:
            HMAC-SHA256 hash (hex, first 16 characters)
        """
        return hash_secret(text, self._session_key)

    def get_detection_summary(self) -> Dict[str, Any]:
        """Get summary of detection configuration and capabilities.

        Useful for debugging, logging, and understanding what will be detected.

        Returns:
            Dictionary with configuration summary

        Example:
            >>> policy = SecretDetectionPolicy()
            >>> summary = policy.get_detection_summary()
            >>> print(summary)
            {
                'enabled_patterns': ['aws_access_key', 'github_token', ...],
                'entropy_threshold': 4.5,
                'entropy_threshold_generic': 3.5,
                'allow_test_secrets': True,
                'excluded_paths': [],
                'pattern_count': 11,
                'specific_patterns': ['aws_access_key', ...],
                'generic_patterns': ['generic_api_key', 'generic_secret']
            }
        """
        generic_names = set(self._GENERIC_SECRET_PATTERNS.keys())
        specific_patterns = [
            name for name in self.enabled_patterns
            if name not in generic_names
        ]
        generic_patterns = [
            name for name in self.enabled_patterns
            if name in generic_names
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
            "test_secret_patterns": len(TestSecretFilter.TEST_SECRET_PATTERNS)
        }

    def _sanitize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize execution context to prevent re-exposure of detected secrets.

        The context parameter comes from the action validation call and may contain
        the full action data structure including the content that was scanned for
        secrets. We must sanitize this to avoid re-exposing the secrets we detected.

        Args:
            context: Raw execution context

        Returns:
            Sanitized context safe for logging

        Example:
            >>> context = {"api_key": "sk-proj-secret123", "file_path": "config.py"}
            >>> _sanitize_context(context)
            {'file_path': 'config.py'}  # Secret removed/redacted
        """
        from src.utils.config_helpers import sanitize_config_for_display
        return sanitize_config_for_display(context)

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
        # Extract and validate content
        content, file_path = self._extract_content(action)
        if not content:
            return ValidationResult(valid=True, policy_name=self.name)

        # Check if path is excluded
        if self._is_path_excluded(file_path):
            return ValidationResult(valid=True, policy_name=self.name)

        # Scan for secrets
        violations = self._scan_for_secrets(content, file_path, context)

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

    def _extract_content(self, action: Dict[str, Any]) -> tuple[str, str]:
        """Extract content to scan from action.

        Args:
            action: Action containing content

        Returns:
            Tuple of (content, file_path)
        """
        file_path = action.get("file_path", "")
        content = ""

        # Collect content from various sources
        if "content" in action:
            content = str(action["content"])
        elif "config" in action:
            content = str(action["config"])
        elif "data" in action:
            content = str(action["data"])

        return content, file_path

    def _is_path_excluded(self, file_path: str) -> bool:
        """Check if file path is excluded from scanning.

        Args:
            file_path: Path to check

        Returns:
            True if path is excluded, False otherwise
        """
        return any(excluded in file_path for excluded in self.excluded_paths)

    def _scan_for_secrets(
        self,
        content: str,
        file_path: str,
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Scan content for secret patterns.

        Args:
            content: Content to scan
            file_path: File path for context
            context: Execution context

        Returns:
            List of violations detected
        """
        violations: List[SafetyViolation] = []

        for pattern_match in self.pattern_matcher.find_matches(content):
            # Skip test secrets
            if self._is_test_secret(pattern_match.secret_value):
                continue

            # Check entropy for generic patterns
            entropy = self._calculate_entropy(pattern_match.secret_value)
            if not self._should_flag_match(pattern_match.pattern_name, entropy):
                continue

            # Create violation
            violation = self._create_secret_violation(
                pattern_match, entropy, file_path, context
            )
            violations.append(violation)

        return violations

    def _should_flag_match(self, pattern_name: str, entropy: float) -> bool:
        """Check if pattern match should be flagged based on entropy.

        Args:
            pattern_name: Name of the pattern
            entropy: Entropy of the match

        Returns:
            True if match should be flagged, False otherwise
        """
        # SECURITY FIX (code-high-14): Filter generic patterns by entropy
        if pattern_name in ["generic_api_key", "generic_secret"]:
            return entropy >= self.entropy_threshold_generic
        return True

    def _create_secret_violation(
        self,
        pattern_match: Any,
        entropy: float,
        file_path: str,
        context: Dict[str, Any]
    ) -> SafetyViolation:
        """Create a SafetyViolation for a detected secret.

        Args:
            pattern_match: Pattern match object
            entropy: Calculated entropy
            file_path: File path for context
            context: Execution context

        Returns:
            SafetyViolation for the detected secret
        """
        # Determine severity
        severity = self._determine_severity(pattern_match.pattern_name, entropy)

        # Create safe redacted preview (never expose actual secret)
        redacted_preview = create_redacted_preview(pattern_match.matched_text, pattern_match.pattern_name)

        # SECURITY: Generate violation ID using HMAC for secure deduplication
        violation_id = hash_secret(pattern_match.matched_text, self._session_key)

        # SECURITY: Sanitize context to prevent re-exposing detected secrets
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
                "violation_id": violation_id
            }
        )

    def _determine_severity(self, pattern_name: str, entropy: float) -> ViolationSeverity:
        """Determine violation severity based on pattern and entropy.

        Args:
            pattern_name: Name of the pattern
            entropy: Calculated entropy

        Returns:
            ViolationSeverity level
        """
        if pattern_name in ["private_key", "aws_secret_key"]:
            return ViolationSeverity.CRITICAL
        elif pattern_name in ["aws_access_key", "github_token", "generic_api_key", "stripe_key"]:
            return ViolationSeverity.HIGH
        elif entropy > self.entropy_threshold:
            return ViolationSeverity.HIGH
        else:
            return ViolationSeverity.MEDIUM
