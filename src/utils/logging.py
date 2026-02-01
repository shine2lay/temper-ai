"""
Structured logging configuration and utilities.

Provides centralized logging with:
- Structured log fields (JSON format)
- Secret redaction
- Context propagation
- Multiple output formats (console, file, JSON)
- Log level configuration from environment
"""
import os
import sys
import logging
import json
from typing import Any, Dict, Optional, Callable, Tuple
from pathlib import Path
from datetime import datetime


# Import secret detection for redaction
detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None
SECRETS_AVAILABLE = False

try:
    from src.utils.secrets import detect_secret_patterns
    SECRETS_AVAILABLE = True
except ImportError:
    pass


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
        """Format log record with secret redaction."""
        # Redact secrets from the message
        original_msg = record.getMessage()
        record.msg = self._redact_secrets(original_msg)

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
        """Redact secrets from text."""
        if not isinstance(text, str):
            return text  # type: ignore[unreachable]

        # Sanitize control characters to prevent log injection
        # Replace newlines, carriage returns, tabs, and other control chars
        import re
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)  # Remove control chars except \t, \n
        text = text.replace('\n', '\\n')  # Escape newlines
        text = text.replace('\r', '\\r')  # Escape carriage returns
        text = text.replace('\t', '\\t')  # Escape tabs

        # Redact secret references
        text = re.sub(r'\$\{env:([A-Z_]+)\}', r'${env:***REDACTED***}', text)
        text = re.sub(r'\$\{vault:([^}]+)\}', r'${vault:***REDACTED***}', text)
        text = re.sub(r'\$\{aws:([^}]+)\}', r'${aws:***REDACTED***}', text)

        # Detect and redact secret patterns
        if SECRETS_AVAILABLE and detect_secret_patterns is not None:
            is_secret, confidence = detect_secret_patterns(text)
            if is_secret and confidence == "high":
                # Redact high-confidence secrets
                text = re.sub(r'sk-[a-zA-Z0-9]{20,}', '***REDACTED***', text)
                text = re.sub(r'sk-proj-[a-zA-Z0-9]{20,}', '***REDACTED***', text)
                text = re.sub(r'sk-ant-api\d+-[a-zA-Z0-9]{20,}', '***REDACTED***', text)
                text = re.sub(r'AKIA[0-9A-Z]{16}', '***REDACTED***', text)

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
        """Format log record as JSON."""
        # Build structured log entry
        log_entry = {
            'timestamp': datetime.now().astimezone().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': self._redact_secrets(record.getMessage()),
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
            assert old_factory is not None, "old_factory should be set"
            record = old_factory(*args, **kwargs)
            for key, value in context_fields.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*func_args: Any, **func_kwargs: Any) -> Any:
            logger.log(level, f"Entering {func.__name__} with args={func_args}, kwargs={func_kwargs}")
            try:
                result = func(*func_args, **func_kwargs)
                logger.log(level, f"Exiting {func.__name__} with result={result}")
                return result
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {e}", exc_info=True)
                raise
        return wrapper
    return decorator
