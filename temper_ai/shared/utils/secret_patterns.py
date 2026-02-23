"""Centralized secret and PII pattern registry.

Single source of truth for all secret detection, sanitization,
and redaction patterns used across the framework.

Consumers:
    - src/observability/sanitization.py (DataSanitizer)
    - src/safety/secret_detection.py (SecretDetectionPolicy)
    - src/security/llm_security.py (OutputSanitizer)
    - src/utils/secrets.py (detect_secret_patterns)
    - src/utils/logging.py (log redaction)
    - src/utils/config_helpers.py (config display redaction)

SECURITY: All patterns use bounded quantifiers to prevent ReDoS attacks.
"""

# ---------------------------------------------------------------------------
# High-confidence secret patterns (vendor-specific formats)
# ---------------------------------------------------------------------------
# These match known vendor key formats with high confidence.
# All use bounded quantifiers {min,max} to prevent ReDoS.

SECRET_PATTERNS: dict[str, str] = {
    # OpenAI (project keys and general sk- keys)
    # M-15: \b word boundaries reduce false positives in prose / identifiers
    "openai_project_key": r"\bsk-proj-[a-zA-Z0-9]{20,200}\b",
    "openai_key": r"\bsk-[a-zA-Z0-9]{20,200}\b",
    # Anthropic
    "anthropic_key": r"\bsk-ant-api\d{2,4}-[a-zA-Z0-9_-]{20,200}\b",
    # AWS
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "aws_secret_key": (
        r"['\"]?(?:aws_secret_access_key|SecretAccessKey|AWS_SECRET)['\"]?"
        r"\s*[=:]\s*['\"]?([a-zA-Z0-9+/]{40})['\"]?"
    ),
    # GitHub
    "github_token": r"\bgh[pousr]_[0-9a-zA-Z]{30,40}\b",
    # Google
    "google_api_key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "google_oauth": r"\bya29\.[0-9A-Za-z_-]{1,500}\b",
    # Slack (multi-segment format: xoxb-digits-digits-alphanum)
    "slack_token": r"\bxox[baprs]-[0-9a-zA-Z-]{10,48}\b",
    # Stripe
    "stripe_key": r"\b(sk|pk)_(test|live)_[0-9a-zA-Z]{24,200}\b",
    # Connection strings (database URLs with potential credentials)
    "connection_string": r"\b(mongodb|postgres|mysql|redis)://[^'\"\s]{1,500}",
    # JWT
    "jwt_token": (
        r"\beyJ[a-zA-Z0-9_-]{1,2000}"
        r"\.eyJ[a-zA-Z0-9_-]{1,2000}"
        r"\.[a-zA-Z0-9_-]{1,2000}\b"
    ),
    # Private keys (line-anchored, no word boundary needed for dashes)
    "private_key": r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----",
}

# ---------------------------------------------------------------------------
# Generic / lower-confidence secret patterns
# ---------------------------------------------------------------------------
# These match common key=value assignment patterns but may produce false
# positives without additional entropy filtering.

GENERIC_SECRET_PATTERNS: dict[str, str] = {
    # Generic API keys with common prefixes (sk-, pk-, api_key-)
    # M-15: \b word boundaries reduce false positives
    "api_key": r"\b(sk|pk|api[_-]?key)[_-]?[a-zA-Z0-9]{20,200}\b",
    # API key assignments (key=value format)
    "generic_api_key": (
        r"\b(api[_-]?key|apikey)['\"]?\s*[:=]\s*['\"]?"
        r"([0-9a-zA-Z_\-+/]{20,500})['\"]?"
    ),
    # Secret/password assignments
    "generic_secret": (
        r"\b(secret|password|passwd|pwd)[\w_-]*['\"]?\s*[:=]\s*['\"]?"
        r"([^\s]{12,500})['\"]?"
    ),
    # Generic key/token/secret assignment (key=value, token: value)
    # Uses (?:^|(?<=[\s_-])) lookbehind instead of \b to handle compound names
    # like "secret_key=" where \b wouldn't match before "key" after "_".
    "generic_token": (
        r"(?:^|(?<=[\s_\-]))(token|key|secret)\s*[=:]\s*['\"]?"
        r"([a-zA-Z0-9_\-/+=!@#$%^&*]{16,500})"
    ),
    # Password disclosure in natural language
    "password_disclosure": (
        r"\b(password|passwd|pass)\s+(is|are)\s*:?\s*['\"]?"
        r"([a-zA-Z0-9_\-!@#$%^&*]+)"
    ),
    # Database URLs with embedded credentials (user:pass@host)
    "db_credentials": r"\b(postgres|mysql|mongodb)://[^:]+:[^@]+@",
}

# ---------------------------------------------------------------------------
# PII patterns (based on OWASP recommendations)
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, str] = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "phone_us": (r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}

# ---------------------------------------------------------------------------
# Secret key names (for config/dict key matching)
# ---------------------------------------------------------------------------
# Used to identify dictionary keys that likely hold secret values.

SECRET_KEY_NAMES: list[str] = [
    "api_key",
    "apikey",
    "api-key",
    "api_key_ref",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "auth",
    "credential",
    "private_key",
    "access_key",
]
