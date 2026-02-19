"""Security-related constants and threat classifications."""


class ThreatTypes:
    """Classification labels for security threats."""

    COMMAND_INJECTION = "command injection"
    PROMPT_INJECTION = "prompt injection"
    PATH_TRAVERSAL = "path traversal"
    SQL_INJECTION = "sql injection"
    ARBITRARY_CODE_EXECUTION = "arbitrary code execution"
    PRIVILEGE_ESCALATION = "privilege escalation"
    CODE_INJECTION = "code_injection"
    ROLE_MANIPULATION = "role manipulation"
    SYSTEM_PROMPT_LEAKAGE = "system prompt leakage"
    DELIMITER_INJECTION = "delimiter injection"
    ENCODING_BYPASS = "encoding bypass"
    JAILBREAK_ATTEMPT = "jailbreak attempt"


# ============================================================================
# Severity Levels
# ============================================================================

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# ============================================================================
# Rate Limiting
# ============================================================================

RATE_LIMIT_PREFIX = "rate_limit:"
RATE_LIMIT_ERROR_MESSAGE = "Rate limit exceeded: "

# ============================================================================
# Detection Messages
# ============================================================================

DETECTION_PREFIX = "Detected "

# ============================================================================
# Field Names
# ============================================================================

FIELD_ENTITY_ID = "entity_id"
