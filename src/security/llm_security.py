"""
LLM Security Module - Prompt Injection Detection, Output Sanitization, Rate Limiting.

Provides security controls for LLM interactions including:
- Prompt injection and jailbreak detection
- System prompt leakage prevention
- Output sanitization (secrets, dangerous content)
- Rate limiting per agent/workflow
"""
import logging
import math
import os
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

from src.constants.durations import (
    RATE_LIMIT_WINDOW_BURST,
    RATE_LIMIT_WINDOW_HOUR,
    RATE_LIMIT_WINDOW_MINUTE,
)
from src.constants.limits import (
    MAX_SHORT_STRING_LENGTH,
    SMALL_ITEM_LIMIT,
)
from src.constants.sizes import SIZE_10KB, SIZE_100KB
from src.security.constants import (
    DETECTION_PREFIX,
    RATE_LIMIT_ERROR_MESSAGE,
    RATE_LIMIT_PREFIX,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    ThreatTypes,
)

# Entropy threshold for detecting obfuscated attacks
ENTROPY_THRESHOLD_RANDOM = 5.5
# Evidence prefix length for security violations
EVIDENCE_PREFIX_LENGTH = 20

logger = logging.getLogger(__name__)

# Try to import Redis (optional dependency)
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using in-memory rate limiting only")


# Lua script for atomic rate limit check (prevents TOCTOU race condition)
# Combined version checks all limits (minute, hour, burst) in a single atomic operation
RATE_LIMIT_LUA_SCRIPT = f"""
-- Atomically check all rate limits (minute, hour, burst) in single operation
-- This prevents partial rollback issues and reduces Redis roundtrips
local minute_key = KEYS[1]
local hour_key = KEYS[2]
local burst_key = KEYS[3]

local minute_limit = tonumber(ARGV[1])
local hour_limit = tonumber(ARGV[2])
local burst_limit = tonumber(ARGV[3])

-- Get current counts (default 0)
local minute_count = tonumber(redis.call('GET', minute_key)) or 0
local hour_count = tonumber(redis.call('GET', hour_key)) or 0
local burst_count = tonumber(redis.call('GET', burst_key)) or 0

-- Check ALL limits BEFORE incrementing (prevents partial success)
-- If limit=100, allows requests when current=0..99, blocks when current=100
if minute_count >= minute_limit then
    return {{0, 'minute'}}  -- Rate limited by minute
end

if hour_count >= hour_limit then
    return {{0, 'hour'}}  -- Rate limited by hour
end

if burst_count >= burst_limit then
    return {{0, 'burst'}}  -- Rate limited by burst
end

-- All checks passed - increment ALL counters atomically
redis.call('INCR', minute_key)
redis.call('EXPIRE', minute_key, {RATE_LIMIT_WINDOW_MINUTE})
redis.call('INCR', hour_key)
redis.call('EXPIRE', hour_key, {RATE_LIMIT_WINDOW_HOUR})
redis.call('INCR', burst_key)
redis.call('EXPIRE', burst_key, {RATE_LIMIT_WINDOW_BURST})

return {{1, 'allowed'}}  -- Success
"""


def normalize_entity_id(entity_id: str) -> str:
    """
    Normalize entity ID to prevent bypass attacks.

    Security: Prevents case/Unicode/whitespace bypass attempts.

    Args:
        entity_id: Raw entity identifier

    Returns:
        Normalized entity ID

    Examples:
        normalize_entity_id("Admin") -> "admin"
        normalize_entity_id("admin\\u200B") -> "admin"  # Zero-width space removed
        normalize_entity_id("аdmin") -> "аdmin"  # Cyrillic preserved after NFC
    """
    if not entity_id:
        return ""

    # Lowercase + Unicode NFC normalization + strip whitespace
    normalized = unicodedata.normalize('NFC', entity_id.lower().strip())

    # Remove zero-width characters (bypass attempt)
    for zwc in ['\u200B', '\u200C', '\u200D', '\uFEFF']:
        normalized = normalized.replace(zwc, '')

    return normalized


@dataclass
class SecurityViolation:
    """Record of a security violation."""
    violation_type: str
    severity: str  # "critical", "high", "medium", "low"
    description: str
    evidence: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "violation_type": self.violation_type,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
        }


class PromptInjectionDetector:
    """
    Detect prompt injection attacks, jailbreaks, and system prompt leakage attempts.

    Features:
    - Pattern-based detection (regex + keywords)
    - Entropy analysis for obfuscated attacks
    - System prompt leakage detection
    - Jailbreak attempt detection
    """

    # Maximum input length before pattern matching (DoS protection)
    MAX_INPUT_LENGTH = SIZE_100KB  # pattern matching is O(n)

    # Maximum input length for entropy calculation (DoS protection)
    MAX_ENTROPY_LENGTH = SIZE_10KB  # entropy is O(n*m) with large m for Unicode
    # NOTE: Inputs 10KB-100KB skip entropy check (acceptable tradeoff for performance)
    # This is intentional: entropy calculation on large Unicode inputs can exhaust memory.

    # Maximum evidence length in violation reports (prevent log injection)
    MAX_EVIDENCE_LENGTH = MAX_SHORT_STRING_LENGTH  # Balance detail vs log safety

    def __init__(self) -> None:
        """Initialize detector with ReDoS-safe attack patterns."""
        # Prompt injection patterns (ReDoS-safe - no nested quantifiers)
        # Multiple patterns per attack type to maintain detection coverage
        self.injection_patterns = [
            # Direct command injection - whitespace separators (most common)
            (r"ignore\s+all\s+previous\s+(?:instructions|steps|context|prompts)", ThreatTypes.COMMAND_INJECTION),
            (r"ignore\s+previous\s+(?:\w+\s+)?(?:instructions|steps|context|prompts)", ThreatTypes.COMMAND_INJECTION),
            (r"disregard\s+all\s+(?:previous|prior)\s+(?:instructions|prompts|context|steps)", ThreatTypes.COMMAND_INJECTION),
            (r"disregard\s+(?:previous|prior)\s+(?:\w+\s+)?(?:instructions|prompts|context|steps)", ThreatTypes.COMMAND_INJECTION),
            (r"forget\s+all\s+(?:previous|prior)\s+(?:instructions|context|steps)", ThreatTypes.COMMAND_INJECTION),
            (r"forget\s+(?:previous|prior)\s+(?:\w+\s+)?(?:instructions|context|steps)", ThreatTypes.COMMAND_INJECTION),
            (r"override\s+your\s+(?:training|instructions|rules|programming)", ThreatTypes.COMMAND_INJECTION),
            (r"override\s+(?:training|instructions|rules|programming)", ThreatTypes.COMMAND_INJECTION),

            # Direct command injection - alternative separators (tokenization exploits)
            # Limited character class [._-] without nested quantifiers
            (r"ignore[._-]+all[._-]+previous[._-]+instructions", ThreatTypes.COMMAND_INJECTION),
            (r"ignore[._-]+previous[._-]+instructions", ThreatTypes.COMMAND_INJECTION),
            (r"disregard[._-]+all[._-]+(?:previous|prior)[._-]+instructions", ThreatTypes.COMMAND_INJECTION),
            (r"disregard[._-]+(?:previous|prior)[._-]+instructions", ThreatTypes.COMMAND_INJECTION),

            # Role manipulation
            (r"you\s+are\s+now\s+(?:a|an)\s+", ThreatTypes.ROLE_MANIPULATION),
            (r"act\s+as\s+(?:a|an)\s+", ThreatTypes.ROLE_MANIPULATION),
            (r"pretend\s+(?:you\s+are|to\s+be)\s+", ThreatTypes.ROLE_MANIPULATION),
            (r"new\s+(?:role|persona|character)\s*:", ThreatTypes.ROLE_MANIPULATION),

            # System prompt extraction
            (r"(?:show|reveal|display|print)\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?(?:prompt|instructions)", ThreatTypes.SYSTEM_PROMPT_LEAKAGE),
            (r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions)", ThreatTypes.SYSTEM_PROMPT_LEAKAGE),
            (r"repeat\s+(?:your\s+)?(?:instructions|prompt|everything\s+above)", ThreatTypes.SYSTEM_PROMPT_LEAKAGE),
            (r"(?:translate|summarize)\s+(?:your\s+)?(?:instructions|prompt|what\s+you\s+were\s+told)", ThreatTypes.SYSTEM_PROMPT_LEAKAGE),
            (r"what\s+(?:are\s+)?(?:the\s+)?rules\s+you", ThreatTypes.SYSTEM_PROMPT_LEAKAGE),
            (r"output\s+your\s+(?:initialization|initial)\s+message", ThreatTypes.SYSTEM_PROMPT_LEAKAGE),

            # Delimiter injection
            (r"</?\s*(?:system|user|assistant|instructions?)\s*>", ThreatTypes.DELIMITER_INJECTION),
            (r"\[/?\s*(?:SYSTEM|USER|ASSISTANT|INSTRUCTIONS?)\s*\]", ThreatTypes.DELIMITER_INJECTION),
            (r"(?:System|User|Assistant)\s*:", ThreatTypes.DELIMITER_INJECTION),

            # Encoding bypass attempts - length-limited to prevent ReDoS
            (r"(?:decode|execute|run)\s+(?:and\s+)?(?:execute|run)?\s*:\s*[a-zA-Z0-9+/=]{20,200}", ThreatTypes.ENCODING_BYPASS),
            (r"base64|hex\s+encoded|rot13", ThreatTypes.ENCODING_BYPASS),
            (r"\\x[0-9a-f]{2}", ThreatTypes.ENCODING_BYPASS),  # hex encoding detection

            # DAN/Jailbreak patterns
            (r"(?:do\s+anything\s+now|DAN\s+mode)", ThreatTypes.JAILBREAK_ATTEMPT),
            (r"developer\s+mode", ThreatTypes.JAILBREAK_ATTEMPT),
            (r"evil\s+mode", ThreatTypes.JAILBREAK_ATTEMPT),
        ]

        # Compile patterns for performance
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE | re.UNICODE), name)
            for pattern, name in self.injection_patterns
        ]

        # High-risk keywords
        self.high_risk_keywords = [
            "sudo", "root", "bypass", "jailbreak",
            "unrestricted", "unfiltered", "uncensored"
        ]

    def detect(self, prompt: str) -> Tuple[bool, List[SecurityViolation]]:
        """
        Detect prompt injection attempts with ReDoS protection.

        Args:
            prompt: Input prompt to analyze

        Returns:
            Tuple of (is_safe, violations_list)
        """
        violations = []

        # Length check to prevent DoS (ReDoS protection layer 1)
        if len(prompt) > self.MAX_INPUT_LENGTH:
            violation = SecurityViolation(
                violation_type="oversized_input",
                severity=SEVERITY_HIGH,
                description=f"Input exceeds maximum length ({self.MAX_INPUT_LENGTH} chars)",
                evidence=f"Length: {len(prompt)}"
            )
            violations.append(violation)
            # Truncate for analysis to prevent DoS
            prompt = prompt[:self.MAX_INPUT_LENGTH]

        # Pattern-based detection (ReDoS protection layer 2: safe patterns)
        # Use search() instead of findall() for efficiency (stops at first match)
        for pattern, attack_type in self.compiled_patterns:
            match = pattern.search(prompt)
            if match:
                # Limit evidence length to prevent log injection
                evidence_text = match.group(0)
                if len(evidence_text) > self.MAX_EVIDENCE_LENGTH:
                    evidence = evidence_text[:self.MAX_EVIDENCE_LENGTH] + "... [truncated]"
                else:
                    evidence = evidence_text

                violation = SecurityViolation(
                    violation_type="prompt_injection",
                    severity=SEVERITY_HIGH,
                    description=f"{DETECTION_PREFIX}{attack_type}",
                    evidence=evidence
                )
                violations.append(violation)

        # Keyword-based detection
        prompt_lower = prompt.lower()
        detected_keywords = [kw for kw in self.high_risk_keywords if kw in prompt_lower]
        if detected_keywords:
            violation = SecurityViolation(
                violation_type="high_risk_keywords",
                severity=SEVERITY_MEDIUM,
                description="High-risk keywords detected",
                evidence=", ".join(detected_keywords[:SMALL_ITEM_LIMIT])
            )
            violations.append(violation)

        # Entropy analysis (detect obfuscated attacks) with length protection
        if self._high_entropy(prompt):
            violation = SecurityViolation(
                violation_type="high_entropy",
                severity="medium",
                description="High entropy detected (possible obfuscation)",
                evidence=f"Entropy: {self._calculate_entropy(prompt):.2f}"
            )
            violations.append(violation)

        is_safe = len(violations) == 0
        return is_safe, violations

    def _calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of text using Shannon formula: -Σ(p * log2(p))."""
        if not text:
            return 0.0

        # Count character frequencies
        char_counts: DefaultDict[str, int] = defaultdict(int)
        for char in text:
            char_counts[char] += 1

        # Calculate entropy using Shannon formula
        entropy = 0.0
        text_len = len(text)
        for count in char_counts.values():
            probability = count / text_len
            if probability > 0:  # log is undefined for 0
                entropy -= probability * math.log2(probability)

        return entropy

    def _high_entropy(self, text: str, threshold: float = ENTROPY_THRESHOLD_RANDOM) -> bool:
        """
        Check if text has suspiciously high entropy.

        Threshold selection (empirically tested):
        - Normal English prose: ~4.0-4.5 bits/char
        - Technical/code: ~4.5-5.0 bits/char
        - Multilingual: ~5.0-5.5 bits/char
        - Random/encoded: >5.5 bits/char (DETECT)

        DoS Protection: Skip entropy check for very long inputs to prevent
        memory exhaustion from large Unicode character dictionaries.
        """
        # Skip entropy check for very long inputs (DoS protection)
        if len(text) > self.MAX_ENTROPY_LENGTH:
            return False
        return self._calculate_entropy(text) > threshold


class OutputSanitizer:
    """
    Sanitize LLM output to prevent secret leakage and dangerous content.

    Features:
    - Secret detection (API keys, tokens, passwords)
    - Dangerous content filtering
    - PII detection (optional)
    - Path traversal prevention
    """

    # Severity mapping for centralized patterns
    _SECRET_SEVERITY: dict[str, str] = {
        "openai_key": "critical",
        "anthropic_key": "critical",
        "aws_access_key": "critical",
        "aws_secret_key": "critical",
        "github_token": "critical",
        "google_api_key": "high",
        "google_oauth": "high",
        "slack_token": "high",
        "stripe_key": "critical",
        "connection_string": "critical",
        "jwt_token": "high",
        "private_key": "critical",
        "api_key": "high",
        "generic_api_key": "high",
        "generic_secret": "high",
        "generic_token": "high",
        "password_disclosure": "critical",
        "db_credentials": "critical",
    }

    _PII_SEVERITY: dict[str, str] = {
        "ssn": "high",
        "credit_card": "critical",
        "email": "medium",
        "phone_us": "medium",
        "ipv4": "low",
    }

    def __init__(self) -> None:
        """Initialize sanitizer with detection patterns from centralized registry."""
        from src.utils.secret_patterns import (
            GENERIC_SECRET_PATTERNS,
            PII_PATTERNS,
            SECRET_PATTERNS,
        )

        # Build secret pattern list with severity from centralized registry.
        # Exclude key=value assignment patterns (generic_api_key, generic_secret)
        # which consume JSON/config key names during inline redaction.
        _detection_only = {"generic_api_key", "generic_secret"}
        self.secret_patterns = []
        for name, pattern in {**SECRET_PATTERNS, **GENERIC_SECRET_PATTERNS}.items():
            if name in _detection_only:
                continue
            severity = self._SECRET_SEVERITY.get(name, "high")
            self.secret_patterns.append((pattern, name, severity))
        for name, pattern in PII_PATTERNS.items():
            severity = self._PII_SEVERITY.get(name, "medium")
            self.secret_patterns.append((pattern, name, severity))

        # Compile patterns
        self.compiled_secret_patterns = [
            (re.compile(pattern, re.IGNORECASE), name, severity)
            for pattern, name, severity in self.secret_patterns
        ]

        # Dangerous content patterns
        self.dangerous_patterns = [
            (r"rm\s+-rf\s+/", "destructive_command"),
            (r"DROP\s+TABLE", "sql_injection"),
            (r"eval\s*\(", "code_injection"),
            (r"exec\s*\(", "code_injection"),
            (r"__import__\s*\(['\"]os['\"]", "code_injection"),
            (r";\s*(curl|wget|bash|sh|nc|netcat)", "command_chaining"),
            (r"\|\s*(bash|sh|/bin)", "command_piping"),
        ]

        self.compiled_dangerous_patterns = [
            (re.compile(pattern, re.IGNORECASE), name)
            for pattern, name in self.dangerous_patterns
        ]

    def _detect_secrets(
        self, output: str
    ) -> Tuple[List[SecurityViolation], List[Tuple[int, int, str]]]:
        """Detect secrets in output and collect replacements."""
        violations: List[SecurityViolation] = []
        replacements: List[Tuple[int, int, str]] = []
        for pattern, secret_type, severity in self.compiled_secret_patterns:
            for match in pattern.finditer(output):
                violations.append(
                    SecurityViolation(
                        violation_type="secret_leakage",
                        severity=severity,
                        description=f"Detected {secret_type} in output",
                        evidence=f"{match.group(0)[:EVIDENCE_PREFIX_LENGTH]}...",
                    )
                )
                replacements.append(
                    (match.start(), match.end(), f"[REDACTED_{secret_type.upper()}]")
                )
        return violations, replacements

    def _deduplicate_replacements(
        self, replacements: List[Tuple[int, int, str]]
    ) -> List[Tuple[int, int, str]]:
        """Deduplicate overlapping replacements, keeping longest matches first.

        SECURITY FIX (code-crit-20): Uses longest-match-first strategy to prevent
        partial secret leakage when patterns overlap.
        """
        # Sort by length (longest first), then start position (leftmost first)
        replacements.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
        deduplicated: List[Tuple[int, int, str]] = []
        for start, end, replacement in replacements:
            overlaps = any(
                not (end <= es or start >= ee) for es, ee, _ in deduplicated
            )
            if not overlaps:
                deduplicated.append((start, end, replacement))
        # Sort by start position in reverse for safe string replacement
        deduplicated.sort(key=lambda x: x[0], reverse=True)
        return deduplicated

    def _detect_dangerous_content(self, text: str) -> List[SecurityViolation]:
        """Detect dangerous content patterns (no redaction, just detection)."""
        violations: List[SecurityViolation] = []
        for pattern, danger_type in self.compiled_dangerous_patterns:
            for match in pattern.finditer(text):
                violations.append(
                    SecurityViolation(
                        violation_type="dangerous_content",
                        severity="high",
                        description=f"Detected {danger_type} in output",
                        evidence=match.group(0),
                    )
                )
        return violations

    def sanitize(self, output: str) -> Tuple[str, List[SecurityViolation]]:
        """
        Sanitize LLM output.

        Args:
            output: LLM output text to sanitize

        Returns:
            Tuple of (sanitized_output, violations_list)
        """
        sanitized = output

        # Detect secrets and collect replacements
        violations, replacements = self._detect_secrets(output)

        # Deduplicate overlapping replacements (keep longest match)
        deduplicated = self._deduplicate_replacements(replacements)

        # Apply all deduplicated replacements
        for start, end, replacement in deduplicated:
            sanitized = sanitized[:start] + replacement + sanitized[end:]

        # Detect dangerous content
        violations.extend(self._detect_dangerous_content(sanitized))

        return sanitized, violations

    def contains_secrets(self, text: str) -> bool:
        """Quick check if text contains secrets."""
        for pattern, _, _ in self.compiled_secret_patterns:
            if pattern.search(text):
                return True
        return False


class LLMSecurityRateLimiter:
    """Rate limit LLM calls per agent/workflow to prevent abuse.

    Features:
    - Per-agent rate limiting
    - Per-workflow rate limiting
    - Sliding window algorithm
    - Burst protection
    - Optional Redis backend for distributed rate limiting

    For simpler single-tier rate limiting, see
    :class:`~src.safety.token_bucket.TokenBucket` which provides a canonical
    token bucket implementation. This class is specifically designed for
    multi-tier LLM call limiting with optional Redis backend.
    """

    # Default rate limiting parameters
    DEFAULT_MAX_CALLS_PER_MINUTE = 60
    DEFAULT_MAX_CALLS_PER_HOUR = 1000
    DEFAULT_BURST_SIZE = 10

    def __init__(
        self,
        max_calls_per_minute: int = DEFAULT_MAX_CALLS_PER_MINUTE,
        max_calls_per_hour: int = DEFAULT_MAX_CALLS_PER_HOUR,
        burst_size: int = DEFAULT_BURST_SIZE,
        redis_url: Optional[str] = None,
        fallback_mode: str = 'in_memory'
    ):
        """
        Initialize rate limiter.

        Args:
            max_calls_per_minute: Maximum calls per minute per entity
            max_calls_per_hour: Maximum calls per hour per entity
            burst_size: Maximum burst size (consecutive calls)
            redis_url: Redis connection URL (default: from REDIS_URL env var)
            fallback_mode: 'fail_closed' (deny all) or 'in_memory' (local fallback)
        """
        self.max_calls_per_minute = max_calls_per_minute
        self.max_calls_per_hour = max_calls_per_hour
        self.burst_size = burst_size
        self.fallback_mode = fallback_mode

        # Track call history per entity (agent_id or workflow_id)
        self.call_history: Dict[str, List[float]] = defaultdict(list)

        # Track burst activity
        self.burst_tracker: Dict[str, List[float]] = defaultdict(list)

        # Thread safety lock
        self._lock = Lock()

        # Initialize Redis connection (optional)
        self._redis = None
        self._rate_limit_script = None
        self._redis_available = False

        if REDIS_AVAILABLE:
            redis_url = redis_url or os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

            try:
                redis_connect_timeout = 1  # seconds
                redis_socket_timeout = 2  # seconds
                self._redis = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=redis_connect_timeout,
                    socket_timeout=redis_socket_timeout
                )
                # Test connection
                self._redis.ping()
                # Register Lua script
                self._rate_limit_script = self._redis.register_script(RATE_LIMIT_LUA_SCRIPT)
                self._redis_available = True
                from src.utils.secrets import mask_url_password
                logger.info(
                    "Redis rate limiting enabled",
                    extra={'redis_url': mask_url_password(redis_url)}
                )

            except Exception as e:
                from src.utils.secrets import mask_url_password
                logger.warning(
                    f"Redis unavailable, using {fallback_mode} mode: {e}",
                    extra={'redis_url': mask_url_password(redis_url)}
                )
                self._redis = None
                self._redis_available = False

    def check_and_record_rate_limit(self, entity_id: str) -> Tuple[bool, Optional[str]]:
        """
        ATOMIC: Check and record rate limit in a single operation.

        This method fixes the TOCTOU race condition by combining check and record
        into a single atomic operation using Redis Lua scripts (distributed) or
        thread-safe in-memory operations (fallback).

        SECURITY FIX: Prevents concurrent threads from bypassing rate limits by
        checking and recording in separate operations.

        Args:
            entity_id: Agent ID or workflow ID

        Returns:
            Tuple of (allowed, reason_if_blocked)

        Note:
            This is the atomic method that prevents TOCTOU race conditions.
        """
        # Normalize entity ID (prevent bypass attacks)
        normalized_id = normalize_entity_id(entity_id)

        if not normalized_id:
            logger.warning("Empty entity_id after normalization", extra={'raw_entity_id': entity_id})
            return False, "Invalid entity ID"

        # Try Redis (primary - distributed, atomic)
        if self._redis_available and self._rate_limit_script:
            try:
                return self._check_redis_atomic(normalized_id)

            except Exception as e:
                logger.error(
                    f"Redis rate limit failed: {e}",
                    exc_info=True,
                    extra={'entity_id': normalized_id}
                )
                # Fall through to fallback

        # Fallback mode
        if self.fallback_mode == 'fail_closed':
            logger.warning(
                f"Rate limiting unavailable, denying: {normalized_id}",
                extra={'entity_id': normalized_id}
            )
            return False, "Rate limiting unavailable (failing safe)"

        elif self.fallback_mode == 'in_memory':
            logger.debug(
                f"Using in-memory fallback for: {normalized_id}",
                extra={'entity_id': normalized_id}
            )
            return self._check_local_atomic(normalized_id)

        else:
            # Unknown mode, fail closed
            logger.error(
                f"Invalid fallback mode: {self.fallback_mode}",
                extra={'fallback_mode': self.fallback_mode}
            )
            return False, "Invalid fallback mode"

    def _check_redis_atomic(self, entity_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check rate limit using Redis Lua script (atomic operation).

        This uses a combined Lua script that checks all limits (minute, hour, burst)
        in a single atomic operation, eliminating the need for rollback logic.

        Args:
            entity_id: Normalized entity ID

        Returns:
            Tuple of (allowed, reason_if_blocked)
        """
        if self._rate_limit_script is None:
            raise RuntimeError("Rate limit script not initialized")

        minute_key = f"{RATE_LIMIT_PREFIX}{entity_id}:minute"
        hour_key = f"{RATE_LIMIT_PREFIX}{entity_id}:hour"
        burst_key = f"{RATE_LIMIT_PREFIX}{entity_id}:burst"

        # Single atomic check of all limits
        result = self._rate_limit_script(
            keys=[minute_key, hour_key, burst_key],
            args=[self.max_calls_per_minute, self.max_calls_per_hour, self.burst_size]
        )

        allowed = result[0]
        reason = result[1]

        if allowed == 0:
            # Build detailed error message based on which limit was hit
            limit_messages = {
                'minute': f"{RATE_LIMIT_ERROR_MESSAGE}{self.max_calls_per_minute} calls/minute",
                'hour': f"{RATE_LIMIT_ERROR_MESSAGE}{self.max_calls_per_hour} calls/hour",
                'burst': f"Burst limit exceeded: {self.burst_size} calls in {RATE_LIMIT_WINDOW_BURST} seconds"
            }

            logger.warning(
                f"Rate limit exceeded ({reason}): {entity_id}",
                extra={
                    'entity_id': entity_id,
                    'limit_type': reason
                }
            )

            return False, limit_messages.get(reason, f"{RATE_LIMIT_ERROR_MESSAGE}{reason}")

        return True, None

    def _check_local_atomic(self, entity_id: str) -> Tuple[bool, Optional[str]]:
        """
        Fallback: In-memory rate limiting (thread-safe, NOT distributed).

        This combines check and record into a single operation within the lock,
        preventing TOCTOU race conditions within a single process.

        Args:
            entity_id: Normalized entity ID

        Returns:
            Tuple of (allowed, reason_if_blocked)
        """
        with self._lock:
            now = time.time()

            # Clean up old entries
            self._cleanup_old_entries(entity_id, now)

            # Check minute limit
            minute_ago = now - RATE_LIMIT_WINDOW_MINUTE
            recent_calls = [t for t in self.call_history[entity_id] if t > minute_ago]
            if len(recent_calls) >= self.max_calls_per_minute:
                return False, f"{RATE_LIMIT_ERROR_MESSAGE}{self.max_calls_per_minute} calls/minute"

            # Check hour limit
            hour_ago = now - RATE_LIMIT_WINDOW_HOUR
            hourly_calls = [t for t in self.call_history[entity_id] if t > hour_ago]
            if len(hourly_calls) >= self.max_calls_per_hour:
                return False, f"{RATE_LIMIT_ERROR_MESSAGE}{self.max_calls_per_hour} calls/hour"

            # Check burst limit
            burst_window = now - RATE_LIMIT_WINDOW_BURST
            burst_calls = [t for t in self.call_history[entity_id] if t > burst_window]
            if len(burst_calls) >= self.burst_size:
                return False, f"Burst limit exceeded: {self.burst_size} calls in {RATE_LIMIT_WINDOW_BURST} seconds"

            # ATOMIC: Record the call immediately after checks pass
            self.call_history[entity_id].append(now)

            return True, None

    def _cleanup_old_entries(self, entity_id: str, now: float) -> None:
        """Remove entries older than 1 hour and evict empty entity keys."""
        hour_ago = now - RATE_LIMIT_WINDOW_HOUR
        self.call_history[entity_id] = [
            t for t in self.call_history[entity_id] if t > hour_ago
        ]
        # AG-10: Evict entity keys that have no remaining entries to prevent
        # unbounded memory growth from stale entity IDs.
        if not self.call_history[entity_id]:
            del self.call_history[entity_id]

    def get_stats(self, entity_id: str) -> Dict[str, int]:
        """
        Get rate limit statistics for entity (thread-safe).

        Args:
            entity_id: Agent ID or workflow ID

        Returns:
            Dict with current usage statistics
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_entries(entity_id, now)

            minute_ago = now - RATE_LIMIT_WINDOW_MINUTE
            hour_ago = now - RATE_LIMIT_WINDOW_HOUR

            minute_calls = len([t for t in self.call_history[entity_id] if t > minute_ago])
            hour_calls = len([t for t in self.call_history[entity_id] if t > hour_ago])

            return {
                "calls_last_minute": minute_calls,
                "calls_last_hour": hour_calls,
                "minute_limit": self.max_calls_per_minute,
                "hour_limit": self.max_calls_per_hour,
                "minute_remaining": max(0, self.max_calls_per_minute - minute_calls),
                "hour_remaining": max(0, self.max_calls_per_hour - hour_calls),
            }

    def reset(self, entity_id: Optional[str] = None) -> None:
        """
        Reset rate limits (thread-safe).

        Args:
            entity_id: Specific entity to reset, or None for all
        """
        with self._lock:
            if entity_id:
                self.call_history[entity_id].clear()
                self.burst_tracker[entity_id].clear()
            else:
                self.call_history.clear()
                self.burst_tracker.clear()


# Global instances
_prompt_detector: Optional[PromptInjectionDetector] = None
_output_sanitizer: Optional[OutputSanitizer] = None
_rate_limiter: Optional[LLMSecurityRateLimiter] = None
_security_lock = Lock()


def get_prompt_detector() -> PromptInjectionDetector:
    """Get global PromptInjectionDetector instance."""
    global _prompt_detector
    # Double-check locking pattern
    if _prompt_detector is None:
        with _security_lock:
            # Check again inside lock
            if _prompt_detector is None:
                _prompt_detector = PromptInjectionDetector()
    return _prompt_detector


def get_output_sanitizer() -> OutputSanitizer:
    """Get global OutputSanitizer instance."""
    global _output_sanitizer
    # Double-check locking pattern
    if _output_sanitizer is None:
        with _security_lock:
            # Check again inside lock
            if _output_sanitizer is None:
                _output_sanitizer = OutputSanitizer()
    return _output_sanitizer


def get_rate_limiter() -> LLMSecurityRateLimiter:
    """Get global LLMSecurityRateLimiter instance."""
    global _rate_limiter
    # Double-check locking pattern
    if _rate_limiter is None:
        with _security_lock:
            # Check again inside lock
            if _rate_limiter is None:
                _rate_limiter = LLMSecurityRateLimiter()
    return _rate_limiter


def reset_security_components() -> None:
    """Reset all global security components (useful for testing)."""
    global _prompt_detector, _output_sanitizer, _rate_limiter
    with _security_lock:
        _prompt_detector = None
        _output_sanitizer = None
        _rate_limiter = None
