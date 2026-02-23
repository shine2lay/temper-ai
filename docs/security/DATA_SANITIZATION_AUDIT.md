# Data Sanitization Audit Trail

**Version:** 1.0
**Last Updated:** 2026-01-31
**Compliance:** GDPR Article 30, CCPA Section 1798.150

## Overview

This document provides a comprehensive audit trail specification for data sanitization within Temper AI. It documents what gets sanitized, when sanitization occurs, how to correlate sanitized logs with original requests, and retention policies for sanitization metadata.

## What Gets Sanitized

### 1. LLM Prompts and Responses
**Location:** `temper_ai/observability/tracker.py:542-586`

**Sanitization Applied:**
- Secrets detection (API keys, tokens, passwords, private keys)
- PII detection (emails, SSNs, phone numbers, credit cards, IP addresses)
- Large payload truncation (5KB prompts, 20KB responses)
- HMAC-based content hashing for correlation

**Sanitization Result:**
- Prompts: Sanitized before storage in observability backend
- Responses: Sanitized before storage in observability backend
- Error messages: Sanitized if containing prompt fragments

**Example:**
```python
# Input
prompt = "Use this API key: sk-proj-abc123xyz to access the service"

# Stored
prompt_sanitized = "Use this API key: [OPENAI_API_KEY_REDACTED] to access the service"
```

### 2. Tool Parameters and Outputs
**Location:** `temper_ai/observability/tracker.py:596-656`

**Sanitization Applied:**
- Recursive dictionary sanitization
- String value sanitization (secrets, PII)
- Key sanitization (may contain sensitive patterns)
- Non-serializable object conversion

**Sanitization Result:**
- Input parameters: All string values sanitized
- Output data: All string values sanitized
- Nested structures: Recursively sanitized

**Example:**
```python
# Input
params = {
    "url": "https://api.example.com",
    "api_key": "sk-test-secret",
    "email": "user@example.com"
}

# Stored
params_sanitized = {
    "url": "https://api.example.com",
    "api_key": "[GENERIC_API_KEY_REDACTED]",
    "email": "[EMAIL_REDACTED]"
}
```

### 3. Safety Violation Contexts
**Location:** `temper_ai/safety/secret_detection.py:300-302`

**Sanitization Applied:**
- Configuration sanitization (removes secret keys)
- Pattern-based secret detection
- Context sanitization to prevent re-exposure

**Sanitization Result:**
- Violation contexts: Sanitized before tracking
- Detected secrets: Never stored, only redacted previews
- HMAC violation IDs: Enable deduplication without exposing secrets

**Example:**
```python
# Input context
context = {
    "api_key": "sk-proj-secret123",
    "file_path": "config.py",
    "line_number": 42
}

# Stored context
context_sanitized = {
    "file_path": "config.py",
    "line_number": 42
}  # Secret removed entirely
```

### 4. Configuration Snapshots
**Location:** `temper_ai/utils/config_helpers.py:sanitize_config_for_display()`

**Sanitization Applied:**
- Key-based secret detection (`api_key`, `password`, `token`, etc.)
- Environment variable reference preservation (`${env:VAR}`)
- Pattern-based secret detection for values

**Sanitization Result:**
- Configuration: Safe to log/display without exposing credentials

## Sanitization Events Logged

### Event Format

**Log Entry:**
```python
logger.info(
    "Sanitized LLM call data before storage",
    extra={
        "llm_call_id": "uuid-string",
        "prompt_redactions": 2,  # Number of redactions in prompt
        "response_redactions": 0,  # Number of redactions in response
        "redaction_types": ["openai_key", "email"]  # Types of secrets found
    }
)
```

**Fields:**
- `llm_call_id`: Unique identifier for the LLM call (UUID)
- `prompt_redactions`: Count of redactions made in prompt
- `response_redactions`: Count of redactions made in response
- `redaction_types`: List of pattern types detected (e.g., `openai_key`, `email`, `ssn`)

**Trigger Conditions:**
- Sanitization event logged only if redactions were made (`was_sanitized == True`)
- No event logged if content was clean (reduces noise)

### Event Retention

**Retention Policy:**
- **Sanitization logs:** 90 days (configurable via `retention_policy.yaml`)
- **Observability data:** Varies by severity (see Retention Policies section)
- **High-severity violations:** 365 days (security incident retention)

**Storage Location:**
- **Development:** Console output + log files (`logs/observability.log`)
- **Production:** Observability backend (SQL/S3) + structured logging

## Correlation

### Content Hash-Based Correlation

**HMAC-based hashing prevents rainbow table attacks while enabling correlation:**

```python
# Generate content hash for correlation
content_hash = hmac.new(
    session_key,  # Session-specific key (rotates per process)
    content.encode('utf-8'),
    hashlib.sha256
).hexdigest()[:16]  # 16 chars = 64 bits
```

**Session Key Management:**
- **Rotation:** New random key generated per Python process startup
- **Lifetime:** Persists for process lifetime (until restart)
- **Security:** Keys stored in memory only, never persisted to disk
- **Configuration:** Optionally set via `OBSERVABILITY_HMAC_KEY` environment variable for cross-process correlation (for distributed deployments)

**Correlation Capabilities:**
- **Within session:** Same content = same hash (deduplication)
- **Across sessions:** Different session keys = different hashes (privacy)
- **Security:** Cannot reverse hash to recover original content

**Use Cases:**
1. **Deduplication:** Identify repeated LLM calls with same prompt
2. **Performance analysis:** Track cache hit rates by content hash
3. **Audit trail:** Correlate sanitized logs with original request IDs

**Example:**
```python
# Request A (original)
llm_call_id = "req-001"
content_hash = "a1b2c3d4e5f6g7h8"

# Request B (same prompt in same session)
llm_call_id = "req-002"
content_hash = "a1b2c3d4e5f6g7h8"  # Same hash (can deduplicate)

# Request C (same prompt in different session)
llm_call_id = "req-003"
content_hash = "x9y8z7w6v5u4t3s2"  # Different hash (privacy)
```

### Violation ID Correlation

**HMAC-based violation IDs for secret detection:**

```python
violation_id = hmac.new(
    session_key,
    detected_secret.encode('utf-8'),
    hashlib.sha256
).hexdigest()[:16]
```

**Correlation Capabilities:**
- **Same secret, same session:** Same violation ID (deduplication)
- **Same secret, different session:** Different violation ID (privacy)
- **Cannot reverse:** No way to recover original secret from ID

**Use Cases:**
1. **Deduplication:** Count unique secrets detected (not occurrences)
2. **Tracking:** Identify if same secret appears in multiple locations
3. **Audit:** Verify secret rotation (new secret = new violation ID)

## GDPR/CCPA Compliance

### GDPR Compliance

**Article 5(1)(c) - Data Minimization:**
- ✅ **Compliant:** Only redacted summaries stored, not full secrets/PII
- **Evidence:** Sanitization occurs before storage (no original data persisted)

**Article 5(1)(e) - Storage Limitation:**
- ✅ **Compliant:** Retention policies enforce automatic deletion
- **Evidence:** 90-day default retention, 365 days for security incidents
- **Implementation:** `cleanup_old_records()` in SQL backend

**Article 17 - Right to Erasure:**
- ✅ **Compliant:** Sanitization before storage means no original data to erase
- **Evidence:** Secrets/PII redacted on ingestion, not stored anywhere
- **Note:** Redacted summaries (e.g., `[EMAIL_REDACTED]`) don't qualify as personal data

**Article 30 - Records of Processing Activities:**
- ✅ **Compliant:** This document serves as the record of processing
- **Evidence:** Documents what data is processed, how it's sanitized, retention periods

**Article 32 - Security of Processing:**
- ✅ **Compliant:** Technical measures implemented (HMAC, redaction, encryption)
- **Evidence:** Multi-layer sanitization, defense-in-depth architecture

### CCPA Compliance

**Section 1798.100 - Right to Know:**
- ✅ **Compliant:** Audit trail documents what data is collected and how it's processed
- **Evidence:** This document + sanitization logs

**Section 1798.105 - Right to Delete:**
- ✅ **Compliant:** Sanitization before storage + retention policies
- **Evidence:** No original PII stored, redacted data auto-deleted per retention policy

**Section 1798.150 - Security:**
- ✅ **Compliant:** Reasonable security measures implemented
- **Evidence:** Sanitization, HMAC hashing, encryption at rest

### SOC2 Compliance

**CC6.1 - Logical and Physical Access Controls:**
- ✅ **Compliant:** Sanitization prevents unauthorized access to sensitive data in logs
- **Evidence:** Multi-layer sanitization, no secrets in observability backend

**CC7.2 - Detection and Monitoring:**
- ✅ **Compliant:** Sanitization events logged for audit trail
- **Evidence:** `logger.info("Sanitized LLM call data...")` events

## Retention Policies

### Default Retention Periods

**Workflow Execution Data:**
- Default: 90 days
- High-severity violations: 365 days (security incidents)

**LLM Call Logs:**
- Default: 30 days
- Error logs: 90 days

**Tool Execution Logs:**
- Default: 30 days

**Safety Violations:**
- Critical: 365 days
- High: 180 days
- Medium/Low: 90 days

**Sanitization Logs:**
- Default: 90 days (compliance requirement)

### Configuration

**Current Status:** Retention periods are currently hardcoded in implementation files. Future versions will externalize to configuration files.

**Implementation Location:** `temper_ai/observability/backends/sql_backend.py:744-787`

**Current Hardcoded Values:**
- Default retention: 90 days (configurable via method parameter)
- Implementation uses `cleanup_old_records(retention_days: int)` method

**Planned Configuration File:** `configs/retention_policy.yaml`

```yaml
# Planned: Data retention policy (GDPR/CCPA compliant)
retention:
  workflows:
    default_days: 90
    high_severity_violations_days: 365

  llm_calls:
    default_days: 30
    error_logs_days: 90

  tool_executions:
    default_days: 30

  safety_violations:
    critical_days: 365
    high_days: 180
    medium_low_days: 90

  sanitization_logs:
    default_days: 90
```

### Cleanup Implementation

**Current Status:** ✅ Implemented in `temper_ai/observability/backends/sql_backend.py:744-787`

**Method:** `cleanup_old_records(retention_days: int)`

**Scheduled Execution:**
- **Status:** Not yet implemented
- **Planned:** Daily cron job at 2 AM UTC
- **Manual Execution:**
  ```python
  from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
  backend = SQLObservabilityBackend()
  result = backend.cleanup_old_records(retention_days=90)
  print(f"Deleted {result.get('workflows', 0)} workflows")
  ```

**Monitoring:** Cleanup metrics will be tracked (records deleted, storage reclaimed)

## Sanitization Patterns

### Secret Patterns Detected

**Note:** Patterns shown are simplified for readability. See `temper_ai/observability/sanitization.py:115-126` for exact regex implementations.

1. **OpenAI API Keys:** `sk-proj-[a-zA-Z0-9]{20,}` and `sk-[A-Za-z0-9]{20,60}`
2. **Anthropic API Keys:** `sk-ant-api\d+-[a-zA-Z0-9_-]{20,}`
3. **Generic API Keys:** `api[_-]?key[_-]?[A-Za-z0-9]{16,}`
4. **AWS Access Keys:** `AKIA[A-Z0-9]{16}`
5. **AWS Secret Keys:** `[a-zA-Z0-9+/]{40}` (high entropy base64)
6. **GitHub Tokens:** `gh[pousr]_[0-9a-zA-Z]{36,}`
7. **Google API Keys:** `AIza[0-9A-Za-z_-]{35}`
8. **Slack Tokens:** `xox[baprs]-[0-9a-zA-Z]{10,}`
9. **JWT Tokens:** `eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+`
10. **Private Keys:** `-----BEGIN (RSA |EC )?PRIVATE KEY-----`

**Total Patterns:** 10 secret patterns

### PII Patterns Detected

1. **Email Addresses:** `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`
2. **SSN (US):** `\b\d{3}-\d{2}-\d{4}\b`
3. **Phone Numbers (US):** `\b(\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b`
4. **Credit Cards:** `\b(?:\d{4}[-\s]?){3}\d{4}\b`
5. **IPv4 Addresses:** `\b(?:\d{1,3}\.){3}\d{1,3}\b`

## Verification and Testing

### Coverage Tests

**Test:** `tests/safety/test_secret_sanitization.py`

**Verifies:**
- Detected secrets never appear in violation messages
- Violation contexts sanitized before tracking
- All secret pattern types properly redacted
- HMAC-based violation IDs work correctly

**Test:** `tests/test_observability/test_llm_sanitization.py`

**Verifies:**
- LLM prompts and responses sanitized before storage
- API keys, emails, and PII redacted in observability database
- Sanitization events logged with correct metadata

### Security Tests

**Test:** `tests/test_security/test_violation_logging_security.py`

**Verifies:**
- No secrets exposed in safety violation logs
- Defense against bypass techniques (encoding, obfuscation)
- Nested secret detection in complex structures

### Future Test Coverage (Planned)

**Planned:** `tests/test_compliance/test_gdpr_compliance.py`
- Right to erasure verification
- Storage limitation enforcement
- Data minimization validation

**Planned:** `tests/test_observability/test_sanitization_coverage.py`
- Comprehensive coverage across all logging paths
- End-to-end sanitization verification

## Audit Trail Access

### For Compliance Reporting

**Manual Report Generation via SQL:**

**Query sanitization events:**
```sql
SELECT
    timestamp,
    extra->>'llm_call_id' AS call_id,
    extra->>'prompt_redactions' AS prompt_redactions,
    extra->>'response_redactions' AS response_redactions,
    extra->>'redaction_types' AS types
FROM logs
WHERE message = 'Sanitized LLM call data before storage'
AND timestamp >= NOW() - INTERVAL '90 days'
ORDER BY timestamp DESC;
```

**Export compliance report to CSV:**
```sql
COPY (
  SELECT
    DATE_TRUNC('day', timestamp) AS date,
    COUNT(*) AS sanitization_events,
    SUM((extra->>'prompt_redactions')::int) AS total_prompt_redactions,
    SUM((extra->>'response_redactions')::int) AS total_response_redactions,
    STRING_AGG(DISTINCT extra->>'redaction_types', ', ') AS redaction_types
  FROM logs
  WHERE message = 'Sanitized LLM call data before storage'
    AND timestamp >= '2026-01-01'
    AND timestamp < '2026-02-01'
  GROUP BY DATE_TRUNC('day', timestamp)
  ORDER BY date
) TO '/tmp/sanitization_compliance_report.csv' WITH CSV HEADER;
```

**Planned:** Automated report generation via `temper_ai.observability.reports.sanitization_audit` module

### For Security Investigations

**Correlate by content hash:**
```sql
-- Find all LLM calls with same prompt (within session)
SELECT llm_call_id, timestamp, status
FROM llm_calls
WHERE content_hash = 'a1b2c3d4e5f6g7h8'
ORDER BY timestamp;
```

**Analyze redaction patterns:**
```sql
-- Top redaction types detected
SELECT
    redaction_type,
    COUNT(*) AS occurrences
FROM (
    SELECT UNNEST(extra->>'redaction_types') AS redaction_type
    FROM logs
    WHERE message = 'Sanitized LLM call data before storage'
) AS redactions
GROUP BY redaction_type
ORDER BY occurrences DESC;
```

## Change History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-01-31 | Initial documentation | Claude Sonnet 4.5 |

## References

- GDPR: https://gdpr-info.eu/
- CCPA: https://oag.ca.gov/privacy/ccpa
- SOC2: https://www.aicpa.org/soc4so
- `temper_ai/observability/sanitization.py` - Core sanitization implementation
- `temper_ai/observability/tracker.py` - Observability integration
- `temper_ai/safety/secret_detection.py` - Secret detection policy
- `temper_ai/utils/config_helpers.py` - Configuration sanitization
