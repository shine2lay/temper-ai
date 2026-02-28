"""
Structured logging configuration and utilities.

Provides centralized logging with:
- Structured log fields (JSON format)
- Secret redaction
- Context propagation
- Multiple output formats (console, file, JSON)
- Log level configuration from environment
"""

import json
import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from urllib.parse import unquote

from temper_ai.shared.constants.limits import DEFAULT_MAX_ITEMS
from temper_ai.shared.constants.probabilities import PROB_VERY_HIGH
from temper_ai.shared.constants.sizes import SIZE_10KB

REDACTION_REPLACEMENT = "\\1=[REDACTED]"

# ASCII control character boundaries
ASCII_CONTROL_CHAR_MAX = (
    0x20  # Characters below this (0x00-0x1F) are control characters
)
ASCII_DELETE_CHAR = 0x7F  # DEL character (also a control character)

# Import secret detection for redaction
detect_secret_patterns: Callable[[str], tuple[bool, str | None]] | None = None
SECRETS_AVAILABLE = False

try:
    from temper_ai.shared.utils.secrets import detect_secret_patterns

    SECRETS_AVAILABLE = True
except ImportError:
    pass


# Precompiled patterns for performance (log injection prevention)
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


# Sensitive data patterns for redaction
# Note: Patterns should not match template references like ${env:VAR} or ${vault:...}
def _build_sensitive_patterns() -> list[tuple[re.Pattern[str], str]]:
    """Build redaction patterns from centralized registry + log-specific rules."""
    from temper_ai.shared.utils.secret_patterns import SECRET_PATTERNS

    patterns = [
        # Key=value assignment patterns (log-specific, exclude template refs)
        (
            re.compile(r"(password|passwd|pwd)[=:]\s*(?!\$\{)(\S+)", re.IGNORECASE),
            REDACTION_REPLACEMENT,
        ),
        (
            re.compile(
                r"(api[_-]?key|apikey|token)[=:]\s*(?!\$\{)(\S+)", re.IGNORECASE
            ),
            REDACTION_REPLACEMENT,
        ),
        (
            re.compile(r"(secret|credential)[=:]\s*(?!\$\{)(\S+)", re.IGNORECASE),
            REDACTION_REPLACEMENT,
        ),
    ]
    # Add ALL vendor-specific patterns from centralized registry
    for pattern in SECRET_PATTERNS.values():
        patterns.append((re.compile(pattern), "***REDACTED***"))
    return patterns


_SENSITIVE_PATTERNS = _build_sensitive_patterns()

# Unicode line terminators to block
_UNICODE_LINE_TERMINATORS = {
    "\u2028",  # Line separator
    "\u2029",  # Paragraph separator
    "\u000b",  # Vertical tab
    "\u000c",  # Form feed
    "\u0085",  # Next line (NEL)
}

# Zero-width characters to remove (prevent obfuscation)
_ZERO_WIDTH_CHARS = {
    "\u200b",  # Zero-width space
    "\u200c",  # Zero-width non-joiner
    "\u200d",  # Zero-width joiner
    "\ufeff",  # Zero-width no-break space
}


def _recursive_url_decode(text: str, max_depth: int = DEFAULT_MAX_ITEMS) -> str:
    """
    Recursively URL decode with depth limit to prevent infinite loops.

    Handles multi-encoded data (e.g., %2541 → %41 → A) up to max_depth iterations.
    This prevents attackers from bypassing sanitization via nested URL encoding.

    Args:
        text: Input text potentially containing URL-encoded data
        max_depth: Maximum decoding iterations (prevents DoS)

    Returns:
        Fully decoded text

    Security: Prevents nested URL encoding attacks while limiting recursion.
    """
    for _ in range(max_depth):
        try:
            decoded = unquote(text)
            if decoded == text:
                # No more decoding possible
                break
            text = decoded
        except Exception:
            # If URL decoding fails, stop and use current text
            break
    return text


def _sanitize_control_characters(text: str) -> str:
    """
    Sanitize control characters to prevent log injection.

    Applies whitelist approach:
    - Newlines and carriage returns: escaped as \\n and \\r
    - Tabs: escaped as \\t (prevent column confusion)
    - Other control chars (0x00-0x1F, 0x7F): escaped as \\xNN
    - Printable characters (including Unicode): preserved
    - Unicode line terminators: escaped as \\uNNNN

    ASCII control character range: 0x00-0x1F (0-31) and 0x7F (127 DEL)

    Args:
        text: Input text to sanitize

    Returns:
        Text with all control characters escaped

    Security: Prevents log injection via control characters.
    """
    # Fast path: Handle CRLF as unit (prevents Windows line ending injection)
    text = text.replace("\r\n", "\\r\\n")
    text = text.replace("\n\r", "\\n\\r")

    # Escape remaining newlines and carriage returns
    text = text.replace("\n", "\\n").replace("\r", "\\r")

    # Escape tabs (prevent column confusion in structured logs)
    text = text.replace("\t", "\\t")

    # Build sanitized string character by character
    sanitized_chars = []
    for char in text:
        if char in _UNICODE_LINE_TERMINATORS:
            # Escape Unicode line terminators
            sanitized_chars.append(f"\\u{ord(char):04x}")
        elif ord(char) < ASCII_CONTROL_CHAR_MAX or ord(char) == ASCII_DELETE_CHAR:
            # Control characters (should be mostly handled above, but double-check)
            sanitized_chars.append(f"\\x{ord(char):02x}")
        else:
            # Printable characters (ASCII and Unicode)
            sanitized_chars.append(char)

    return "".join(sanitized_chars)


def _sanitize_for_logging(text: str, max_length: int = SIZE_10KB) -> str:
    """
    Multi-layer sanitization for log injection prevention.

    Applies 8 layers of defense-in-depth:
    1. URL decode (with depth limit) - prevents %0A, %0D bypasses
    2. Length limiting (DoS prevention) - prevents log flooding
    3. Unicode normalization - prevents homograph attacks
    4. Zero-width character removal - prevents obfuscation
    5. ANSI escape stripping - prevents terminal manipulation
    6. CRLF unit handling - prevents Windows line ending injection
    7. Control character escaping - whitelist approach
    8. (Applied separately) Secret redaction

    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length before truncation

    Returns:
        Sanitized text safe for single-line logging

    Security:
        - Prevents log injection (OWASP A03:2021, CWE-117)
        - Prevents log poisoning and SIEM bypass
        - Prevents terminal injection via ANSI escapes
        - Defense-in-depth approach with multiple layers
    """
    if not text:
        return ""

    # LAYER 1: Recursive URL decode (FIRST - before any checks)
    # Handles %0A, %0D, and nested encoding like %252540A
    text = _recursive_url_decode(text, max_depth=DEFAULT_MAX_ITEMS)

    # LAYER 2: Truncate if too long (EARLY - before expensive operations)
    # Prevents DoS via huge log messages
    if len(text) > max_length:
        text = text[:max_length] + "...[TRUNCATED]"

    # LAYER 3: Unicode normalization (prevents Unicode equivalence bypass)
    # Normalizes е (Cyrillic) vs e (Latin) and other homographs
    # NOTE: NFKC is compatibility normalization - may change visual appearance
    # (e.g., ℌ→H, ①→1, ﬁ→fi) but prevents homograph attacks and standardizes forms
    text = unicodedata.normalize("NFKC", text)

    # LAYER 4: Remove zero-width characters (prevents obfuscation)
    for zw_char in _ZERO_WIDTH_CHARS:
        text = text.replace(zw_char, "")

    # LAYER 5: Strip ANSI escape codes (prevents terminal manipulation)
    # Removes color codes and other terminal control sequences
    text = _ANSI_ESCAPE.sub("", text)

    # LAYER 6-7: Control character escaping (whitelist approach)
    # Handles newlines, CR, tabs, Unicode line terminators
    text = _sanitize_control_characters(text)

    return text


class ExecutionContextFilter(logging.Filter):
    """Logging filter that injects execution context into every LogRecord.

    Reads from the shared ``current_execution_context`` ContextVar (set by
    the ExecutionTracker's context managers) and sets ``workflow_id``,
    ``stage_id``, ``agent_id``, and ``session_id`` attributes on the record.

    When OpenTelemetry is active, ``trace_id`` and ``span_id`` are also
    injected from the current span context.

    Attach to handlers (not loggers) so it works globally without
    touching any of the 795+ existing log call sites.
    """

    # Context field names to inject into log records
    _CONTEXT_FIELDS = ("workflow_id", "stage_id", "agent_id", "session_id")

    def filter(self, record: logging.LogRecord) -> bool:
        """Enrich *record* with execution context fields. Always returns True."""
        # Read execution context from the shared ContextVar
        from temper_ai.shared.core.context import current_execution_context

        ctx = current_execution_context.get(None)
        for field_name in self._CONTEXT_FIELDS:
            setattr(record, field_name, getattr(ctx, field_name, None) if ctx else None)

        # Optionally inject OTEL trace/span IDs
        record.trace_id = None
        record.span_id = None
        try:
            from opentelemetry import trace as otel_trace

            get_span = getattr(otel_trace, "get_current_span", None)
            if get_span is not None:
                span = get_span()
                span_ctx = span.get_span_context()
                if span_ctx and span_ctx.trace_id:
                    record.trace_id = format(span_ctx.trace_id, "032x")
                    record.span_id = format(span_ctx.span_id, "016x")
        except ImportError:
            pass  # opentelemetry not installed — skip

        return True


class SecretRedactingFormatter(logging.Formatter):
    """
    Logging formatter that redacts secrets from log messages.

    Automatically detects and redacts:
    - API keys (OpenAI, Anthropic, AWS, etc.)
    - Secret references (${env:VAR})
    - Known secret patterns
    """

    from temper_ai.shared.utils.secret_patterns import SECRET_KEY_NAMES

    REDACTED_KEYS = SECRET_KEY_NAMES

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record with injection prevention and secret redaction.

        Applies security in two layers:
        1. Sanitization (prevent log injection attacks)
        2. Redaction (protect sensitive data)

        This ensures all logs are safe from injection and don't leak secrets.
        """
        # Save original msg template and args so we can restore after formatting
        original_msg = record.msg
        original_args = record.args

        # Get formatted message (applies % args to msg template)
        formatted_msg = record.getMessage()

        # LAYER 1: Sanitize for log injection prevention (FIRST)
        sanitized_msg = _sanitize_for_logging(formatted_msg)

        # LAYER 2: Redact secrets (AFTER sanitization)
        safe_msg = self._redact_secrets(sanitized_msg)

        # Set safe message and clear args (already formatted)
        record.msg = safe_msg
        record.args = None

        # Redact secrets from extra fields
        if hasattr(record, "__dict__"):
            for key in list(record.__dict__.keys()):
                if any(pattern in key.lower() for pattern in self.REDACTED_KEYS):
                    setattr(record, key, "***REDACTED***")

        # Format the record
        formatted = super().format(record)

        # Restore original msg template and args for other handlers
        record.msg = original_msg
        record.args = original_args

        return formatted

    def _redact_secrets(self, text: str) -> str:
        """
        Redact sensitive data from text.

        Applies regex patterns to detect and redact:
        - Passwords, API keys, tokens
        - Secret references (${env:VAR}, ${vault:...}, ${aws:...})
        - Known secret patterns (OpenAI, Anthropic, AWS, etc.)

        Args:
            text: Input text to redact

        Returns:
            Text with secrets redacted

        Note: This should be called AFTER _sanitize_for_logging to ensure
        injection is prevented first.
        """
        if not isinstance(text, str):
            return text  # type: ignore[unreachable]

        # Redact secret references (${env:VAR}, ${vault:...}, ${aws:...})
        text = re.sub(r"\$\{env:([A-Z_]+)\}", r"${env:***REDACTED***}", text)
        text = re.sub(r"\$\{vault:([^}]+)\}", r"${vault:***REDACTED***}", text)
        text = re.sub(r"\$\{aws:([^}]+)\}", r"${aws:***REDACTED***}", text)

        # Apply precompiled sensitive patterns
        for pattern, replacement in _SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)

        # Use detect_secret_patterns if available (additional layer)
        # Already covered by _SENSITIVE_PATTERNS above, but detect_secret_patterns
        # provides additional detection that may catch edge cases
        if SECRETS_AVAILABLE and detect_secret_patterns is not None:
            try:
                is_secret, confidence = detect_secret_patterns(text)
                if is_secret and confidence and float(confidence) > PROB_VERY_HIGH:
                    # High confidence secret detected - apply additional redaction
                    text = "***REDACTED***"
            except ValueError:
                pass  # Skip detection for oversized inputs

        return text


class StructuredFormatter(SecretRedactingFormatter):
    """
    JSON formatter for structured logging with secret redaction.

    Outputs logs as JSON with fields:
    - timestamp: ISO 8601 timestamp
    - level: Log level name
    - logger: Logger name
    - message: Log message
    - extra: Additional context fields
    """

    # Attributes that belong to LogRecord itself or are promoted to top-level
    _BUILTIN_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            # Context fields already promoted in format()
            "workflow_id",
            "stage_id",
            "agent_id",
            "session_id",
            "trace_id",
            "span_id",
        }
    )

    # Execution-context fields promoted to top-level JSON keys
    _CONTEXT_FIELDS = (
        "workflow_id",
        "stage_id",
        "agent_id",
        "session_id",
        "trace_id",
        "span_id",
    )

    def _collect_extra_fields(self, record: logging.LogRecord) -> dict:
        """Extract non-builtin record attributes, redacting secrets.

        Returns:
            Dict of extra fields (may be empty).
        """
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key in self._BUILTIN_ATTRS or key.startswith("_"):
                continue
            if any(pattern in key.lower() for pattern in self.REDACTED_KEYS):
                extra_fields[key] = "***REDACTED***"
            else:
                extra_fields[key] = value
        return extra_fields

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON with injection prevention and secret redaction.

        Applies sanitization before redaction to ensure safe JSON output.
        """
        # Get message and apply sanitization + redaction
        original_msg = record.getMessage()
        sanitized_msg = _sanitize_for_logging(original_msg)
        safe_msg = self._redact_secrets(sanitized_msg)

        # Build structured log entry
        log_entry = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": safe_msg,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Promote execution context fields to top-level JSON
        # (injected by ExecutionContextFilter)
        for ctx_field in self._CONTEXT_FIELDS:
            value = getattr(record, ctx_field, None)
            if value is not None:
                log_entry[ctx_field] = value

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        extra_fields = self._collect_extra_fields(record)
        if extra_fields:
            log_entry["extra"] = extra_fields

        return json.dumps(log_entry)


class ConsoleFormatter(SecretRedactingFormatter):
    """
    Human-readable console formatter with colors and secret redaction.

    Format: [LEVEL] logger - message
    """

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def __init__(self, use_colors: bool = True):
        """
        Initialize console formatter.

        Args:
            use_colors: Whether to use ANSI color codes
        """
        super().__init__(
            fmt="[%(levelname)s] %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        formatted = super().format(record)

        if self.use_colors and record.levelname in self.COLORS:
            color = self.COLORS[record.levelname]
            reset = self.COLORS["RESET"]
            return f"{color}{formatted}{reset}"

        return formatted


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started", user_id=123)
    """
    return logging.getLogger(name)
