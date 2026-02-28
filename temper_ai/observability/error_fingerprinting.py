"""Error fingerprinting — classify, deduplicate, and track error patterns.

Provides deterministic fingerprints for exceptions so that identical errors
across different executions can be aggregated, trended, and alerted on.

Fingerprint algorithm::

    1. Extract error_type (class name) and error_code (ErrorCode enum or derived)
    2. Sanitize: strip secrets via existing sanitizer
    3. Normalize: replace UUIDs, timestamps, numbers, file paths with placeholders
    4. Truncate: first 256 chars of normalized message
    5. Hash: SHA-256 of "error_type:error_code:normalized_message", first 16 hex chars

Output: deterministic 16-char hex string (e.g., "a3f7c9e2b1d045f8").
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from temper_ai.storage.database.datetime_utils import utcnow

# ============================================================================
# Constants
# ============================================================================

FINGERPRINT_LENGTH = 16  # hex chars
MAX_NORMALIZED_MESSAGE_LENGTH = 256
MAX_RECENT_IDS = 10  # Cap on stored recent workflow/agent IDs

# Normalization regex patterns (precompiled for performance)
_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_NUMBER_PATTERN = re.compile(r"\b\d{3,}\b")  # 3+ digit numbers
_PATH_PATTERN = re.compile(r"(?:/[\w.-]+){2,}")  # Unix-style paths with 2+ segments
_HEX_ID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8,}\b")  # Hex IDs (8+ chars)
_MEMORY_ADDR_PATTERN = re.compile(r"0x[0-9a-fA-F]+")  # Memory addresses


# ============================================================================
# Error Classification
# ============================================================================


class ErrorClassification(StrEnum):
    """Error classification for fingerprints."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    SAFETY = "safety"
    UNKNOWN = "unknown"


# Error codes classified as transient (imported from _sequential_helpers pattern)
_TRANSIENT_CODES = frozenset(
    {
        "LLM_CONNECTION_ERROR",
        "LLM_TIMEOUT",
        "LLM_RATE_LIMIT",
        "SYSTEM_TIMEOUT",
        "SYSTEM_RESOURCE_ERROR",
        "TOOL_TIMEOUT",
        "AGENT_TIMEOUT",
        "WORKFLOW_TIMEOUT",
    }
)

_SAFETY_CODES = frozenset(
    {
        "SAFETY_VIOLATION",
        "SAFETY_POLICY_ERROR",
        "SAFETY_ACTION_BLOCKED",
    }
)


def classify_error(error_code: str) -> ErrorClassification:
    """Classify an error code into transient/permanent/safety/unknown."""
    upper = error_code.upper()
    if upper in _TRANSIENT_CODES:
        return ErrorClassification.TRANSIENT
    if upper in _SAFETY_CODES:
        return ErrorClassification.SAFETY
    # Check for known permanent patterns
    if upper and upper not in {"UNKNOWN", ""}:
        return ErrorClassification.PERMANENT
    return ErrorClassification.UNKNOWN


# ============================================================================
# Normalization
# ============================================================================


def normalize_message(message: str) -> str:
    """Replace volatile parts of an error message with placeholders.

    Makes the message deterministic across instances so that the same
    logical error always produces the same fingerprint.
    """
    if not message:
        return ""

    result = message
    # Order matters: more specific patterns first
    result = _MEMORY_ADDR_PATTERN.sub("<ADDR>", result)
    result = _UUID_PATTERN.sub("<UUID>", result)
    result = _TIMESTAMP_PATTERN.sub("<TIMESTAMP>", result)
    result = _PATH_PATTERN.sub("<PATH>", result)
    result = _HEX_ID_PATTERN.sub("<HEX>", result)
    result = _NUMBER_PATTERN.sub("<N>", result)

    # Collapse whitespace
    result = " ".join(result.split())

    # Truncate
    if len(result) > MAX_NORMALIZED_MESSAGE_LENGTH:
        result = result[:MAX_NORMALIZED_MESSAGE_LENGTH]

    return result


# ============================================================================
# Error Code Extraction
# ============================================================================


def extract_error_code(exc: Exception) -> str:
    """Extract a canonical error code from an exception.

    Uses the ``error_code`` attribute from ``BaseError`` subclasses,
    falls back to deriving from the exception class name.
    """
    # BaseError subclasses have .error_code (an ErrorCode enum)
    if hasattr(exc, "error_code"):
        code = exc.error_code
        # Might be an Enum member
        if hasattr(code, "value"):
            return str(code.value)
        return str(code)

    # Derive from class name: e.g., TimeoutError → TIMEOUT_ERROR
    cls_name = type(exc).__name__
    # Convert CamelCase to UPPER_SNAKE
    parts = re.findall(r"[A-Z][a-z]*|[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", cls_name)
    return "_".join(p.upper() for p in parts) if parts else "UNKNOWN"


# ============================================================================
# Fingerprint Computation
# ============================================================================


def compute_fingerprint(
    error_type: str,
    error_code: str,
    error_message: str,
) -> str:
    """Compute a deterministic 16-char hex fingerprint for an error.

    Args:
        error_type: Exception class name (e.g., "LLMError")
        error_code: Canonical error code (e.g., "LLM_TIMEOUT")
        error_message: Raw error message (will be normalized)

    Returns:
        16-character hex string fingerprint
    """
    normalized = normalize_message(error_message)
    canonical = f"{error_type}:{error_code}:{normalized}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:FINGERPRINT_LENGTH]


def compute_error_fingerprint(exc: Exception) -> "ErrorFingerprintResult":
    """Compute full fingerprint result for an exception.

    This is the main entry point — extracts error info, normalizes,
    classifies, and computes the fingerprint hash.
    """
    error_type = type(exc).__name__
    error_code = extract_error_code(exc)
    error_message = str(exc)
    classification = classify_error(error_code)
    normalized = normalize_message(error_message)
    fingerprint = compute_fingerprint(error_type, error_code, error_message)

    return ErrorFingerprintResult(
        fingerprint=fingerprint,
        error_type=error_type,
        error_code=error_code,
        classification=classification,
        normalized_message=normalized,
        sample_message=error_message[:MAX_NORMALIZED_MESSAGE_LENGTH],
    )


# ============================================================================
# Result Dataclass
# ============================================================================


@dataclass
class ErrorFingerprintResult:
    """Result of fingerprint computation."""

    fingerprint: str
    error_type: str
    error_code: str
    classification: ErrorClassification
    normalized_message: str
    sample_message: str
    is_new: bool = False  # Set by backend after upsert
    occurrence_count: int = 1


@dataclass
class ErrorFingerprintRecord:
    """Persistent record for an error fingerprint (maps to DB table)."""

    fingerprint: str
    error_type: str
    error_code: str
    classification: str
    normalized_message: str
    sample_message: str
    occurrence_count: int = 1
    first_seen: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)
    recent_workflow_ids: list[str] = field(default_factory=list)
    recent_agent_names: list[str] = field(default_factory=list)
    resolved: bool = False
    resolved_at: datetime | None = None
    resolution_note: str | None = None
