"""
LLM Security Module - Prompt Injection Detection, Output Sanitization, Rate Limiting.

Provides security controls for LLM interactions including:
- Prompt injection and jailbreak detection
- System prompt leakage prevention
- Output sanitization (secrets, dangerous content)
- Rate limiting per agent/workflow
"""
import re
import time
import math
import hashlib
from typing import Dict, List, Tuple, Optional, Any, DefaultDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock
import logging

logger = logging.getLogger(__name__)


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

    def __init__(self) -> None:
        """Initialize detector with attack patterns."""
        # Prompt injection patterns
        self.injection_patterns = [
            # Direct command injection (flexible separators to catch tokenization exploits)
            (r"ignore[\s._\-|]+(all[\s._\-|]+)?previous[\s._\-|]+instructions", "command injection"),
            (r"disregard[\s._\-|]+(all[\s._\-|]+)?(previous|prior)[\s._\-|]+(instructions|prompts|context)", "command injection"),
            (r"forget[\s._\-|]+(all[\s._\-|]+)?(previous|prior)[\s._\-|]+(instructions|context)", "command injection"),
            (r"override[\s._\-|]+(your[\s._\-|]+)?(training|instructions|rules|programming)", "command injection"),

            # Role manipulation
            (r"you\s+are\s+now\s+(a|an)\s+", "role manipulation"),
            (r"act\s+as\s+(a|an)\s+", "role manipulation"),
            (r"pretend\s+(you\s+are|to\s+be)\s+", "role manipulation"),
            (r"new\s+(role|persona|character)\s*:", "role manipulation"),

            # System prompt extraction
            (r"(show|reveal|display|print)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions)", "system prompt leakage"),
            (r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions)", "system prompt leakage"),
            (r"repeat\s+(your\s+)?(instructions|prompt|everything\s+above)", "system prompt leakage"),
            (r"(translate|summarize)\s+(your\s+)?(instructions|prompt|what\s+you\s+were\s+told)", "system prompt leakage"),
            (r"what\s+(are\s+)?(the\s+)?rules\s+you", "system prompt leakage"),
            (r"output\s+your\s+(initialization|initial)\s+message", "system prompt leakage"),

            # Delimiter injection
            (r"</?\s*(system|user|assistant|instructions?)\s*>", "delimiter injection"),
            (r"\[/?\s*(SYSTEM|USER|ASSISTANT|INSTRUCTIONS?)\s*\]", "delimiter injection"),
            (r"(System|User|Assistant)\s*:", "delimiter injection"),

            # Encoding bypass attempts
            (r"(decode|execute|run)\s+(and\s+)?(execute|run)?\s*:\s*[a-zA-Z0-9+/=]{20,}", "encoding bypass"),
            (r"base64|hex\s+encoded|rot13|unicode", "encoding bypass"),
            (r"\\x[0-9a-f]{2}", "encoding bypass"),

            # DAN/Jailbreak patterns
            (r"(do\s+anything\s+now|DAN\s+mode)", "jailbreak attempt"),
            (r"developer\s+mode", "jailbreak attempt"),
            (r"evil\s+mode", "jailbreak attempt"),
        ]

        # Compile patterns for performance
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), name)
            for pattern, name in self.injection_patterns
        ]

        # High-risk keywords
        self.high_risk_keywords = [
            "sudo", "root", "bypass", "jailbreak",
            "unrestricted", "unfiltered", "uncensored"
        ]

    def detect(self, prompt: str) -> Tuple[bool, List[SecurityViolation]]:
        """
        Detect prompt injection attempts.

        Args:
            prompt: Input prompt to analyze

        Returns:
            Tuple of (is_safe, violations_list)
        """
        violations = []

        # Pattern-based detection
        for pattern, attack_type in self.compiled_patterns:
            matches = pattern.findall(prompt)
            if matches:
                violation = SecurityViolation(
                    violation_type="prompt_injection",
                    severity="high",
                    description=f"Detected {attack_type}",
                    evidence=str(matches[:3])  # First 3 matches
                )
                violations.append(violation)

        # Keyword-based detection
        prompt_lower = prompt.lower()
        detected_keywords = [kw for kw in self.high_risk_keywords if kw in prompt_lower]
        if detected_keywords:
            violation = SecurityViolation(
                violation_type="high_risk_keywords",
                severity="medium",
                description="High-risk keywords detected",
                evidence=", ".join(detected_keywords[:5])
            )
            violations.append(violation)

        # Entropy analysis (detect obfuscated attacks)
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

    def _high_entropy(self, text: str, threshold: float = 4.5) -> bool:
        """Check if text has suspiciously high entropy."""
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

    def __init__(self) -> None:
        """Initialize sanitizer with detection patterns."""
        # Secret patterns
        self.secret_patterns = [
            # Specific API key formats (high confidence)
            (r"sk-[a-zA-Z0-9]{48}", "openai_key", "critical"),  # OpenAI
            (r"sk-ant-api03-[a-zA-Z0-9_\-]{95}", "anthropic_key", "critical"),  # Anthropic
            (r"(ghp|gho|ghs|ghu)_[a-zA-Z0-9]{36}", "github_token", "critical"),  # GitHub tokens

            # Generic API keys with common prefixes
            (r"(sk|pk|api[_-]?key)[_-]?[a-zA-Z0-9]{20,}", "api_key", "high"),

            # AWS credentials
            (r"AKIA[0-9A-Z]{16}", "aws_access_key", "critical"),
            (r"aws_secret_access_key\s*=\s*['\"]?([a-zA-Z0-9/+=]{40})", "aws_secret_key", "critical"),

            # Generic secrets with explicit labels (key=value pattern)
            (r"(token|key|secret)\s*[=:]\s*['\"]?([a-zA-Z0-9_\-/+=!@#$%^&*]{16,})", "generic_secret", "high"),

            # Password patterns (explicit "password is" statements)
            (r"(password|passwd|pass)\s+(is|are)\s*:?\s*['\"]?([a-zA-Z0-9_\-!@#$%^&*]+)", "password", "critical"),

            # Private keys
            (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private_key", "critical"),

            # Database URLs with credentials
            (r"(postgres|mysql|mongodb)://[^:]+:[^@]+@", "db_credentials", "critical"),

            # JWT tokens
            (r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "jwt_token", "high"),

            # PII patterns
            (r"\b\d{3}-\d{2}-\d{4}\b", "ssn", "high"),  # US SSN: 123-45-6789
            (r"\b(?:\d{4}[\s\-]?){3}\d{4}\b", "credit_card", "critical"),  # Credit card: 1234 5678 9012 3456
            (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email", "medium"),  # Email
            (r"\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b", "phone", "medium"),  # Phone: (123) 456-7890
            (r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", "ip_address", "low"),  # IPv4
        ]

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

    def sanitize(self, output: str) -> Tuple[str, List[SecurityViolation]]:
        """
        Sanitize LLM output.

        Args:
            output: LLM output text to sanitize

        Returns:
            Tuple of (sanitized_output, violations_list)
        """
        violations = []
        sanitized = output

        # Collect all replacements first to avoid index shifting issues
        replacements = []

        # Detect secrets and collect replacements
        for pattern, secret_type, severity in self.compiled_secret_patterns:
            for match in pattern.finditer(output):
                violation = SecurityViolation(
                    violation_type="secret_leakage",
                    severity=severity,
                    description=f"Detected {secret_type} in output",
                    evidence=f"{match.group(0)[:20]}..."
                )
                violations.append(violation)

                # Collect replacement (will apply in reverse order later)
                replacements.append((match.start(), match.end(), f"[REDACTED_{secret_type.upper()}]"))

        # Sort replacements by start position in reverse order to preserve indices
        replacements.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate overlapping replacements (keep the first one in sorted order, which is the rightmost)
        deduplicated: List[Tuple[int, int, str]] = []
        for start, end, replacement in replacements:
            # Check if this replacement overlaps with any already added
            overlaps = False
            for existing_start, existing_end, _ in deduplicated:
                if not (end <= existing_start or start >= existing_end):
                    # Overlaps with existing, skip this one
                    overlaps = True
                    break
            if not overlaps:
                deduplicated.append((start, end, replacement))

        # Apply all deduplicated replacements
        for start, end, replacement in deduplicated:
            sanitized = sanitized[:start] + replacement + sanitized[end:]

        # Detect dangerous content (no redaction, just detection)
        for pattern, danger_type in self.compiled_dangerous_patterns:
            for match in pattern.finditer(sanitized):
                violation = SecurityViolation(
                    violation_type="dangerous_content",
                    severity="high",
                    description=f"Detected {danger_type} in output",
                    evidence=match.group(0)
                )
                violations.append(violation)

        return sanitized, violations

    def contains_secrets(self, text: str) -> bool:
        """Quick check if text contains secrets."""
        for pattern, _, _ in self.compiled_secret_patterns:
            if pattern.search(text):
                return True
        return False


class RateLimiter:
    """
    Rate limit LLM calls per agent/workflow to prevent abuse.

    Features:
    - Per-agent rate limiting
    - Per-workflow rate limiting
    - Sliding window algorithm
    - Burst protection
    """

    def __init__(
        self,
        max_calls_per_minute: int = 60,
        max_calls_per_hour: int = 1000,
        burst_size: int = 10
    ):
        """
        Initialize rate limiter.

        Args:
            max_calls_per_minute: Maximum calls per minute per entity
            max_calls_per_hour: Maximum calls per hour per entity
            burst_size: Maximum burst size (consecutive calls)
        """
        self.max_calls_per_minute = max_calls_per_minute
        self.max_calls_per_hour = max_calls_per_hour
        self.burst_size = burst_size

        # Track call history per entity (agent_id or workflow_id)
        self.call_history: Dict[str, List[float]] = defaultdict(list)

        # Track burst activity
        self.burst_tracker: Dict[str, List[float]] = defaultdict(list)

        # Thread safety lock
        self._lock = Lock()

    def check_rate_limit(self, entity_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if entity is within rate limits (thread-safe).

        Args:
            entity_id: Agent ID or workflow ID

        Returns:
            Tuple of (allowed, reason_if_blocked)
        """
        with self._lock:
            now = time.time()

            # Clean up old entries
            self._cleanup_old_entries(entity_id, now)

            # Check minute limit
            minute_ago = now - 60
            recent_calls = [t for t in self.call_history[entity_id] if t > minute_ago]
            if len(recent_calls) >= self.max_calls_per_minute:
                return False, f"Rate limit exceeded: {self.max_calls_per_minute} calls/minute"

            # Check hour limit
            hour_ago = now - 3600
            hourly_calls = [t for t in self.call_history[entity_id] if t > hour_ago]
            if len(hourly_calls) >= self.max_calls_per_hour:
                return False, f"Rate limit exceeded: {self.max_calls_per_hour} calls/hour"

            # Check burst limit
            burst_window = now - 5  # 5 second burst window
            burst_calls = [t for t in self.call_history[entity_id] if t > burst_window]
            if len(burst_calls) >= self.burst_size:
                return False, f"Burst limit exceeded: {self.burst_size} calls in 5 seconds"

            return True, None

    def record_call(self, entity_id: str) -> None:
        """
        Record a successful call (thread-safe).

        Args:
            entity_id: Agent ID or workflow ID
        """
        with self._lock:
            now = time.time()
            self.call_history[entity_id].append(now)

    def _cleanup_old_entries(self, entity_id: str, now: float) -> None:
        """Remove entries older than 1 hour."""
        hour_ago = now - 3600
        self.call_history[entity_id] = [
            t for t in self.call_history[entity_id] if t > hour_ago
        ]

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

            minute_ago = now - 60
            hour_ago = now - 3600

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
_rate_limiter: Optional[RateLimiter] = None


def get_prompt_detector() -> PromptInjectionDetector:
    """Get global PromptInjectionDetector instance."""
    global _prompt_detector
    if _prompt_detector is None:
        _prompt_detector = PromptInjectionDetector()
    return _prompt_detector


def get_output_sanitizer() -> OutputSanitizer:
    """Get global OutputSanitizer instance."""
    global _output_sanitizer
    if _output_sanitizer is None:
        _output_sanitizer = OutputSanitizer()
    return _output_sanitizer


def get_rate_limiter() -> RateLimiter:
    """Get global RateLimiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def reset_security_components() -> None:
    """Reset all global security components (useful for testing)."""
    global _prompt_detector, _output_sanitizer, _rate_limiter
    _prompt_detector = None
    _output_sanitizer = None
    _rate_limiter = None
