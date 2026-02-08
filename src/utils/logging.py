"""
Structured logging configuration and utilities.

Provides centralized logging with:
- Structured log fields (JSON format)
- Secret redaction
- Context propagation
- Multiple output formats (console, file, JSON)
- Log level configuration from environment
"""
import functools
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import unquote

from src.constants.limits import DEFAULT_MAX_ITEMS
from src.constants.probabilities import PROB_VERY_HIGH
from src.constants.sizes import SIZE_10KB

# ASCII control character boundaries
ASCII_CONTROL_CHAR_MAX = 0x20  # Characters below this (0x00-0x1F) are control characters
ASCII_DELETE_CHAR = 0x7F  # DEL character (also a control character)

# Import secret detection for redaction
detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None
SECRETS_AVAILABLE = False

try:
    from src.utils.secrets import detect_secret_patterns
    SECRETS_AVAILABLE = True
except ImportError:
    pass


# Precompiled patterns for performance (log injection prevention)
_ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')

# Sensitive data patterns for redaction
# Note: Patterns should not match template references like ${env:VAR} or ${vault:...}
def _build_sensitive_patterns() -> list[tuple[re.Pattern[str], str]]:
    """Build redaction patterns from centralized registry + log-specific rules."""
    from src.utils.secret_patterns import SECRET_PATTERNS

    patterns = [
        # Key=value assignment patterns (log-specific, exclude template refs)
        (re.compile(r'(password|passwd|pwd)[=:]\s*(?!\$\{)(\S+)', re.IGNORECASE), r'\1=[REDACTED]'),
        (re.compile(r'(api[_-]?key|apikey|token)[=:]\s*(?!\$\{)(\S+)', re.IGNORECASE), r'\1=[REDACTED]'),
        (re.compile(r'(secret|credential)[=:]\s*(?!\$\{)(\S+)', re.IGNORECASE), r'\1=[REDACTED]'),
    ]
    # Add vendor-specific patterns from centralized registry
    for name in ('openai_key', 'anthropic_key', 'aws_access_key',
                 'github_token', 'google_api_key', 'stripe_key'):
        if name in SECRET_PATTERNS:
            patterns.append(
                (re.compile(SECRET_PATTERNS[name]), '***REDACTED***')
            )
    return patterns

_SENSITIVE_PATTERNS = _build_sensitive_patterns()

# Unicode line terminators to block
_UNICODE_LINE_TERMINATORS = {
    '\u2028',  # Line separator
    '\u2029',  # Paragraph separator
    '\u000B',  # Vertical tab
    '\u000C',  # Form feed
    '\u0085',  # Next line (NEL)
}

# Zero-width characters to remove (prevent obfuscation)
_ZERO_WIDTH_CHARS = {
    '\u200B',  # Zero-width space
    '\u200C',  # Zero-width non-joiner
    '\u200D',  # Zero-width joiner
    '\uFEFF',  # Zero-width no-break space
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
    text = text.replace('\r\n', '\\r\\n')
    text = text.replace('\n\r', '\\n\\r')

    # Escape remaining newlines and carriage returns
    text = text.replace('\n', '\\n').replace('\r', '\\r')

    # Escape tabs (prevent column confusion in structured logs)
    text = text.replace('\t', '\\t')

    # Build sanitized string character by character
    sanitized_chars = []
    for char in text:
        if char in _UNICODE_LINE_TERMINATORS:
            # Escape Unicode line terminators
            sanitized_chars.append(f'\\u{ord(char):04x}')
        elif ord(char) < ASCII_CONTROL_CHAR_MAX or ord(char) == ASCII_DELETE_CHAR:
            # Control characters (should be mostly handled above, but double-check)
            sanitized_chars.append(f'\\x{ord(char):02x}')
        else:
            # Printable characters (ASCII and Unicode)
            sanitized_chars.append(char)

    return ''.join(sanitized_chars)


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
    text = unicodedata.normalize('NFKC', text)

    # LAYER 4: Remove zero-width characters (prevents obfuscation)
    for zw_char in _ZERO_WIDTH_CHARS:
        text = text.replace(zw_char, '')

    # LAYER 5: Strip ANSI escape codes (prevents terminal manipulation)
    # Removes color codes and other terminal control sequences
    text = _ANSI_ESCAPE.sub('', text)

    # LAYER 6-7: Control character escaping (whitelist approach)
    # Handles newlines, CR, tabs, Unicode line terminators
    text = _sanitize_control_characters(text)

    return text


class SecretRedactingFormatter(logging.Formatter):
    """
    Logging formatter that redacts secrets from log messages.

    Automatically detects and redacts:
    - API keys (OpenAI, Anthropic, AWS, etc.)
    - Secret references (${env:VAR})
    - Known secret patterns
    """

    REDACTED_KEYS = [
        'api_key', 'apikey', 'api-key', 'api_key_ref',
        'password', 'passwd', 'pwd', 'secret', 'token',
        'auth', 'credential', 'private_key', 'access_key'
    ]

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record with injection prevention and secret redaction.

        Applies security in two layers:
        1. Sanitization (prevent log injection attacks)
        2. Redaction (protect sensitive data)

        This ensures all logs are safe from injection and don't leak secrets.
        """
        # Get original message
        original_msg = record.getMessage()

        # LAYER 1: Sanitize for log injection prevention (FIRST)
        sanitized_msg = _sanitize_for_logging(original_msg)

        # LAYER 2: Redact secrets (AFTER sanitization)
        safe_msg = self._redact_secrets(sanitized_msg)

        # Update record with safe message
        record.msg = safe_msg

        # Redact secrets from extra fields
        if hasattr(record, '__dict__'):
            for key in list(record.__dict__.keys()):
                if any(pattern in key.lower() for pattern in self.REDACTED_KEYS):
                    setattr(record, key, '***REDACTED***')

        # Format the record
        formatted = super().format(record)

        # Restore original message
        record.msg = original_msg

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
        text = re.sub(r'\$\{env:([A-Z_]+)\}', r'${env:***REDACTED***}', text)
        text = re.sub(r'\$\{vault:([^}]+)\}', r'${vault:***REDACTED***}', text)
        text = re.sub(r'\$\{aws:([^}]+)\}', r'${aws:***REDACTED***}', text)

        # Apply precompiled sensitive patterns
        for pattern, replacement in _SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)

        # Use detect_secret_patterns if available (additional layer)
        # Already covered by _SENSITIVE_PATTERNS above, but detect_secret_patterns
        # provides additional detection that may catch edge cases
        if SECRETS_AVAILABLE and detect_secret_patterns is not None:
            is_secret, confidence = detect_secret_patterns(text)
            if is_secret and confidence and float(confidence) > PROB_VERY_HIGH:
                # High confidence secret detected - apply additional redaction
                text = "***REDACTED***"

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
            'timestamp': datetime.now().astimezone().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': safe_msg,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        # Add extra fields (avoiding built-in attributes)
        builtin_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName',
            'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'message', 'pathname', 'process', 'processName',
            'relativeCreated', 'thread', 'threadName', 'exc_info',
            'exc_text', 'stack_info'
        }

        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in builtin_attrs and not key.startswith('_'):
                # Redact secret fields
                if any(pattern in key.lower() for pattern in self.REDACTED_KEYS):
                    extra_fields[key] = '***REDACTED***'
                else:
                    extra_fields[key] = value

        if extra_fields:
            log_entry['extra'] = extra_fields

        return json.dumps(log_entry)


class ConsoleFormatter(SecretRedactingFormatter):
    """
    Human-readable console formatter with colors and secret redaction.

    Format: [LEVEL] logger - message
    """

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'
    }

    def __init__(self, use_colors: bool = True):
        """
        Initialize console formatter.

        Args:
            use_colors: Whether to use ANSI color codes
        """
        super().__init__(
            fmt='[%(levelname)s] %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        formatted = super().format(record)

        if self.use_colors and record.levelname in self.COLORS:
            color = self.COLORS[record.levelname]
            reset = self.COLORS['RESET']
            return f"{color}{formatted}{reset}"

        return formatted


def setup_logging(
    level: Optional[str] = None,
    format_type: str = "console",
    log_file: Optional[str] = None,
    use_colors: bool = True
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
               If None, reads from LOG_LEVEL env var (default: INFO)
        format_type: Output format ("console", "json", or "both")
        log_file: Optional file path for logging
        use_colors: Whether to use colors in console output

    Example:
        >>> setup_logging(level="DEBUG", format_type="json")
        >>> logger = get_logger(__name__)
        >>> logger.info("Application started", version="1.0")
    """
    # Get log level from environment or parameter
    if level is None:
        level = os.environ.get('LOG_LEVEL', 'INFO').upper()

    # Validate log level
    numeric_level = getattr(logging, level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Add console handler
    if format_type in ('console', 'both'):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(ConsoleFormatter(use_colors=use_colors))
        root_logger.addHandler(console_handler)

    # Add JSON handler (for structured logging)
    if format_type in ('json', 'both'):
        json_handler = logging.StreamHandler(sys.stderr)
        json_handler.setLevel(numeric_level)
        json_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(json_handler)

    # Add file handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

    # Log initial configuration
    logger = get_logger(__name__)
    logger.debug(
        f"Logging configured: level={level}, format={format_type}, file={log_file}"
    )


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


class LogContext:
    """
    Context manager for adding structured fields to log messages.

    Example:
        >>> logger = get_logger(__name__)
        >>> with LogContext(logger, user_id=123, request_id="abc"):
        ...     logger.info("Processing request")
        # Logs: Processing request {user_id: 123, request_id: "abc"}
    """

    def __init__(self, logger: logging.Logger, **context_fields: Any) -> None:
        """
        Initialize log context.

        Args:
            logger: Logger to add context to
            **context_fields: Key-value pairs to add to log messages
        """
        self.logger = logger
        self.context_fields = context_fields
        self.old_factory: Optional[Callable[..., logging.LogRecord]] = None

    def __enter__(self) -> "LogContext":
        """Enter context and install log record factory."""
        # Save old factory
        self.old_factory = logging.getLogRecordFactory()

        # Create new factory that adds context fields
        context_fields = self.context_fields
        old_factory = self.old_factory

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            """Logging record factory."""
            if old_factory is None:
                raise RuntimeError("old_factory is None in logging context manager")
            record = old_factory(*args, **kwargs)
            for key, value in context_fields.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Exit context and restore old factory."""
        if self.old_factory is not None:
            logging.setLogRecordFactory(self.old_factory)


def log_function_call(logger: logging.Logger, level: int = logging.DEBUG) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to log function entry and exit.

    Args:
        logger: Logger to use
        level: Log level for messages

    Example:
        >>> logger = get_logger(__name__)
        >>> @log_function_call(logger)
        ... def process_data(data):
        ...     return len(data)
    """
    # Parameter names that indicate sensitive values
    _sensitive_names = frozenset({
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "credentials", "auth", "authorization", "private_key", "encryption_key",
    })

    def _redact_value(name: str, value: Any) -> Any:
        """Redact value if parameter name suggests it is sensitive."""
        if name.lower() in _sensitive_names:
            return "***"
        return value

    def _safe_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return {k: _redact_value(k, v) for k, v in kwargs.items()}

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Logging decorator."""
        @functools.wraps(func)
        def wrapper(*func_args: Any, **func_kwargs: Any) -> Any:
            """Logging wrapper."""
            safe_kw = _safe_kwargs(func_kwargs)
            logger.log(level, f"Entering {func.__name__} with args={func_args}, kwargs={safe_kw}")
            try:
                result = func(*func_args, **func_kwargs)
                logger.log(level, f"Exiting {func.__name__}")
                return result
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {e}", exc_info=True)
                raise
        return wrapper
    return decorator
