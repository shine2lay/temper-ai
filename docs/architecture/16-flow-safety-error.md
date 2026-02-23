# 16 — Safety and Error Flow Traces

**Document Version:** 1.0.0
**Codebase Revision:** Post-M10 (Multi-Tenant), as of 2026-02-22
**Scope:** Complete safety enforcement and error handling paths — from tool-level blocks through LLM failover, circuit breakers, rollback, approval, and emergency stop.
**Primary Modules:** `temper_ai/safety/`, `temper_ai/llm/`, `temper_ai/tools/`, `temper_ai/stage/executors/`, `temper_ai/shared/`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview — Error and Safety Topology](#2-architecture-overview--error-and-safety-topology)
3. [Error Handling Decision Tree](#3-error-handling-decision-tree)
4. [Exception Hierarchy](#4-exception-hierarchy)
5. [Scenario 1: Forbidden Operation Blocked](#5-scenario-1-forbidden-operation-blocked)
6. [Scenario 2: Secret Detected in LLM Output](#6-scenario-2-secret-detected-in-llm-output)
7. [Scenario 3: LLM Provider Failure and Failover](#7-scenario-3-llm-provider-failure-and-failover)
8. [Scenario 4: Tool Execution Failure and Rollback](#8-scenario-4-tool-execution-failure-and-rollback)
9. [Scenario 5: Circuit Breaker Trip and Recovery](#9-scenario-5-circuit-breaker-trip-and-recovery)
10. [Scenario 6: Approval Required for High-Risk Action](#10-scenario-6-approval-required-for-high-risk-action)
11. [Scenario 7: Emergency Stop](#11-scenario-7-emergency-stop)
12. [Scenario 8: Stage Retry with Exponential Backoff](#12-scenario-8-stage-retry-with-exponential-backoff)
13. [Error Propagation Across Layers](#13-error-propagation-across-layers)
14. [Observability Integration in Error Paths](#14-observability-integration-in-error-paths)
15. [Error Fingerprinting and Deduplication](#15-error-fingerprinting-and-deduplication)
16. [Configuration Reference — Safety Parameters](#16-configuration-reference--safety-parameters)
17. [Design Patterns and Architectural Decisions](#17-design-patterns-and-architectural-decisions)
18. [Key File References](#18-key-file-references)

---

## 1. Executive Summary

**System Name:** Temper AI Safety and Error Handling Layer

**Purpose:** This document traces what happens when things go wrong in the temper-ai framework — at every level from individual tool calls up through agent loops, stage executors, and the workflow runtime. It covers eight concrete failure scenarios with exact file and line references, function-level traces, data flow diagrams, and log/observability integration points.

**Key Principles:**
- **Defense in depth.** Every tool call passes through: parameter validation, policy check (ActionPolicyEngine), snapshot creation, cache lookup, rate limiting, concurrent slot acquisition, actual execution, and auto-rollback on failure. No single failure mode bypasses all checks.
- **Fail-closed.** When `fail_open=False` (the default in production), no action is allowed unless at least one policy explicitly permits it. Policy execution errors themselves produce CRITICAL violations.
- **Emergency stop is O(1).** A module-level `threading.Event` in `emergency_stop.py` means every running thread can check `is_active()` in constant time without acquiring any lock.
- **Secrets are redacted before logging.** `sanitize_error_message()` strips AWS keys, API tokens, JWTs, passwords, and connection strings from every exception message and log line.
- **Errors are classified.** `ErrorCode` enums divide errors into CONFIG, LLM, TOOL, AGENT, WORKFLOW, SAFETY, VALIDATION, and SYSTEM categories. The `is_transient_error()` function in `_sequential_retry.py` gates which errors trigger retry.

**Technology Stack:**
- Python 3.11+, asyncio, threading
- Pydantic v2 (schema validation), SHA-256 (fingerprinting, cache keys)
- httpx (LLM API calls), HMAC (secret detection deduplication)
- Rich (console error rendering), OpenTelemetry (span tracing)

---

## 2. Architecture Overview — Error and Safety Topology

The safety and error system spans six distinct layers. Errors at lower layers can either be absorbed (retried, rolled back) or propagate upward.

```
Layer 6: WORKFLOW RUNTIME
  temper_ai/workflow/engines/native_engine.py
  temper_ai/workflow/engines/dynamic_engine.py
        |   WorkflowStageError propagates up, halts the workflow
        v
Layer 5: STAGE EXECUTOR
  temper_ai/stage/executors/sequential.py
  temper_ai/stage/executors/_sequential_retry.py
        |   retry_agent_with_backoff() on transient errors
        |   _handle_agent_failure() dispatch: halt_stage / skip_agent / retry_agent
        v
Layer 4: AGENT / LLM SERVICE
  temper_ai/agent/standard_agent.py
  temper_ai/llm/service.py
        |   call_with_retry_sync/async() in _retry.py
        |   FailoverProvider.complete() in failover.py
        |   CircuitBreaker.call() per provider
        v
Layer 3: TOOL EXECUTOR
  temper_ai/tools/executor.py
  temper_ai/tools/_executor_helpers.py
        |   10-step pipeline:
        |   validate → policy_check → snapshot → cache → rate_limit
        |   → concurrent_slot → execute → cache_store → auto-rollback
        v
Layer 2: SAFETY POLICIES
  temper_ai/safety/action_policy_engine.py
  temper_ai/safety/forbidden_operations.py
  temper_ai/safety/secret_detection.py
  temper_ai/safety/blast_radius.py
  temper_ai/safety/autonomy/emergency_stop.py
        |   validate_action_sync() → EnforcementResult(allowed=bool)
        v
Layer 1: SHARED INFRASTRUCTURE
  temper_ai/shared/core/circuit_breaker.py
  temper_ai/shared/utils/exceptions.py        <- ErrorCode taxonomy
  temper_ai/shared/utils/error_handling.py    <- retry_with_backoff decorator
  temper_ai/observability/error_fingerprinting.py
  temper_ai/observability/sanitization.py
```

### Component Map

| Component | Location | Role in Error Handling |
|---|---|---|
| `ActionPolicyEngine` | `safety/action_policy_engine.py` | Central enforcement; blocks or allows actions; CRITICAL short-circuit |
| `ForbiddenOperationsPolicy` | `safety/forbidden_operations.py` | Regex-based command blocking; P=200 priority |
| `SecretDetectionPolicy` | `safety/secret_detection.py` | Pattern + entropy scanning; blocks or flags secrets |
| `EntropyAnalyzer` | `safety/entropy_analyzer.py` | Shannon entropy for generic secrets |
| `ApprovalWorkflow` | `safety/approval.py` | Human-review for high-risk actions; thread-safe request tracking |
| `ApprovalRouter` | `safety/autonomy/approval_router.py` | Severity x autonomy-level matrix routing |
| `RollbackManager` | `safety/rollback.py` | Pre-action snapshots; revert on failure |
| `FileRollbackStrategy` | `safety/rollback.py` | File content capture + atomic restore |
| `CircuitBreaker` | `shared/core/circuit_breaker.py` | CLOSED/OPEN/HALF_OPEN state machine per provider |
| `EmergencyStopController` | `safety/autonomy/emergency_stop.py` | Module-level threading.Event; O(1) halt |
| `BudgetEnforcer` | `safety/autonomy/budget_enforcer.py` | USD cost tracking; blocks when budget exhausted |
| `FailoverProvider` | `llm/failover.py` | Multi-provider fallback chain |
| `call_with_retry_sync` | `llm/_retry.py` | Exponential backoff + jitter for LLM calls |
| `retry_agent_with_backoff` | `stage/executors/_sequential_retry.py` | Agent-level retry with transient/permanent classification |
| `ErrorCode` | `shared/utils/exceptions.py` | Standardized error taxonomy across all modules |
| `sanitize_error_message` | `shared/utils/exceptions.py` | Strips secrets from all error strings before logging |
| `ErrorFingerprinter` | `observability/error_fingerprinting.py` | SHA-256 deduplication fingerprints for error patterns |

---

## 3. Error Handling Decision Tree

This flowchart shows the complete decision path from any failure — at every layer — through to final disposition.

```mermaid
flowchart TD
    A[/"Error Occurs"/] --> B{Where did it occur?}

    B -- "Tool execution" --> C[ToolExecutor pipeline]
    B -- "LLM API call" --> D[LLM retry layer]
    B -- "Safety policy" --> E[ActionPolicyEngine]
    B -- "Stage agent" --> F[Stage executor]
    B -- "Workflow" --> G[Workflow engine]

    C --> C1{Policy check passed?}
    C1 -- "No — CRITICAL violation" --> C2[Block immediately\nreturn EnforcementResult.allowed=False]
    C1 -- "No — HIGH violation" --> C3{Approval required?}
    C3 -- Yes --> C4[ApprovalWorkflow.request_approval\nblock until approved/rejected/expired]
    C3 -- No --> C2
    C1 -- Yes --> C5[Create RollbackManager snapshot\nexecute tool]
    C5 --> C6{Tool succeeded?}
    C6 -- Yes --> C7[Store to cache\nreturn ToolResult.success=True]
    C6 -- "No — exception" --> C8{enable_auto_rollback?}
    C8 -- Yes --> C9[RollbackManager.execute_rollback\nrestore pre-action state]
    C8 -- No --> C10[Return ToolResult.success=False]
    C9 --> C10

    D --> D1{LLMError raised?}
    D1 -- Yes --> D2[call_with_retry_sync/async\nexponential backoff + jitter]
    D2 --> D3{Retries exhausted?}
    D3 -- No --> D4[Wait backoff_delay\nretry provider.complete]
    D4 --> D1
    D3 -- Yes --> D5{FailoverProvider configured?}
    D5 -- Yes --> D6[Try next provider in chain]
    D6 --> D7{All providers failed?}
    D7 -- No --> D8[Record success\nupdate sticky_session_index]
    D7 -- Yes --> D9[Raise LLMError\nall providers exhausted]
    D5 -- No --> D9

    E --> E1{Emergency stop active?}
    E1 -- Yes --> E2[Return EnforcementResult\nallowed=False\nreason=emergency_stop_active]
    E1 -- No --> E3[Execute policies in priority order]
    E3 --> E4{Any CRITICAL violation?}
    E4 -- "Yes + short_circuit_critical" --> E5[Stop policy chain\nlog CRITICAL violation\nreturn allowed=False]
    E4 -- No --> E6{Any HIGH violation?}
    E6 -- Yes --> E7[Return allowed=False\nviolations logged to observability]
    E6 -- No --> E8[Return allowed=True\nwith any MEDIUM/LOW violations noted]

    F --> F1{Agent status?}
    F1 -- success --> F2[Store output\ncontinue to next agent]
    F1 -- failed --> F3[error_handling.on_agent_failure]
    F3 -- halt_stage --> F4[Raise/return stage error\nWorkflow halted]
    F3 -- skip_agent --> F5[Log warning\ncontinue to next agent]
    F3 -- retry_agent --> F6{is_transient_error?}
    F6 -- Yes --> F7[retry_agent_with_backoff\nexponential backoff]
    F7 --> F8{Max retries hit?}
    F8 -- No --> F1
    F8 -- Yes --> F9[emit RETRY_OUTCOME_EXHAUSTED\nstore failure result]
    F6 -- No --> F10[Log permanent error\nstore failure without retry]
    F3 -- continue_with_remaining --> F10

    G --> G1{Stage error policy?}
    G1 -- halt --> G2[Raise WorkflowStageError\nworkflow terminates]
    G1 -- continue --> G3[Mark stage failed\ncontinue remaining stages]
```

---

## 4. Exception Hierarchy

**Location:** `temper_ai/shared/utils/exceptions.py`

The entire framework uses a rooted exception hierarchy, enabling selective `except` clauses without catching unrelated exceptions.

```
BaseException
└── Exception
    └── FrameworkException          (shared/utils/exceptions.py:207)
        ├── BaseError               (:223) — adds ErrorCode, ExecutionContext, sanitized __str__
        │   ├── ConfigurationError  (:342)
        │   │   ├── ConfigNotFoundError
        │   │   └── ConfigValidationError
        │   ├── LLMError            (:397) — provider, model fields
        │   │   ├── LLMTimeoutError (:426)
        │   │   ├── LLMRateLimitError (:466) — multiple inheritance with RateLimitError
        │   │   └── LLMAuthenticationError (:491)
        │   ├── ToolError           (:504)
        │   │   ├── ToolExecutionError
        │   │   ├── ToolNotFoundError
        │   │   └── ToolRegistryError
        │   ├── AgentError          (:569)
        │   │   └── MaxIterationsError (:595)
        │   ├── WorkflowError       (:623)
        │   │   └── WorkflowStageError (:649)
        │   ├── SafetyError         (:691)
        │   └── FrameworkValidationError (:722)
        ├── SecurityError           (:677) — lightweight, for path/auth violations
        ├── RateLimitError          (:442) — base for all rate limit types
        └── CircuitBreakerError     (shared/core/circuit_breaker.py:97)
```

**Key behavioral properties:**

- `BaseError.__str__()` calls `sanitize_error_message()` before returning — secrets cannot leak through string conversion.
- `BaseError.to_dict()` includes the full `ExecutionContext` (workflow_id, stage_id, agent_id, tool_name) for structured log ingestion.
- `LLMRateLimitError` uses multiple inheritance from both `LLMError` and `RateLimitError` so both `isinstance(e, LLMError)` and `isinstance(e, RateLimitError)` are true — enabling unified rate-limit handling across tool and LLM callers.
- `CircuitBreakerError` is caught specifically in `ActionPolicyEngine._execute_policies_sync()` at line 489, turning a circuit breaker trip into a CRITICAL safety violation rather than an unhandled exception.

---

## 5. Scenario 1: Forbidden Operation Blocked

**Trigger:** An agent generates a tool call containing `rm -rf /` in the `command` parameter of `BashTool`.

### 5.1 Sequence Diagram

```mermaid
sequenceDiagram
    participant Agent as StandardAgent
    participant LLM as LLMService
    participant TExec as ToolExecutor
    participant APE as ActionPolicyEngine
    participant FOP as ForbiddenOperationsPolicy
    participant Obs as ObservabilityTracker

    Agent->>LLM: run(prompt, tools=[Bash])
    LLM->>LLM: _tool_execution.execute_tools()
    LLM->>TExec: execute("bash", {"command": "rm -rf /"})

    Note over TExec: Step 1: validate_and_get_tool()
    TExec->>TExec: registry.get("bash") -> BashTool instance

    Note over TExec: Step 2: BaseTool.validate_params()
    TExec->>TExec: params valid, continue

    Note over TExec: Step 3: policy check (validate_policy)
    TExec->>APE: validate_action_sync(action={"command":"rm -rf /"}, context)

    APE->>APE: _emergency_stop.is_active() -> False
    APE->>APE: _invalidate_cache_if_policies_changed()
    APE->>APE: registry.get_policies_for_action("bash_execution") -> [FOP, ...]

    loop for each policy in priority order
        APE->>FOP: policy.validate(action, context)
        FOP->>FOP: _extract_command(action) -> "rm -rf /"
        FOP->>FOP: _is_whitelisted("rm -rf /") -> False
        FOP->>FOP: _check_all_patterns("rm -rf /", context)
        Note over FOP: Matches DANGEROUS_COMMAND_PATTERNS\n"rm -rf /" pattern: severity=CRITICAL
        FOP->>FOP: SafetyViolation(severity=CRITICAL, message="Dangerous rm command detected")
        FOP-->>APE: ValidationResult(valid=False, violations=[CRITICAL violation])
        APE->>APE: _should_short_circuit_on_critical() -> True (short_circuit_critical=True)
        APE->>APE: break policy loop early
    end

    APE->>APE: _build_enforcement_result(all_violations, ...)
    Note over APE: allowed = not any(v.severity >= HIGH) -> False
    APE->>APE: _log_violations_sync(violations, context)
    APE->>Obs: tracker.track_safety_violation(...)
    APE-->>TExec: EnforcementResult(allowed=False, violations=[CRITICAL])

    TExec->>TExec: result.allowed is False -> return ToolResult.failure()
    TExec-->>LLM: ToolResult(success=False, error="Action blocked by safety policy")
    LLM->>LLM: inject_results() — tool failure message back into conversation
    LLM-->>Agent: LLMRunResult with tool failure noted
```

### 5.2 Detailed Step Trace

**Step 1 — Entry at ToolExecutor** (`temper_ai/tools/executor.py:execute()`)

The `LLMService._tool_execution` module calls `tool_executor.execute("bash", {"command": "rm -rf /"})`. The executor calls `validate_and_get_tool()` from `_executor_helpers.py` to retrieve the `BashTool` instance from `ToolRegistry`.

**Step 2 — Parameter Validation** (`temper_ai/tools/base.py:validate_params()`)

`BaseTool.validate_params()` runs Pydantic model validation or JSON Schema validation on the input. `command` is a required string — this passes.

**Step 3 — Policy Check** (`temper_ai/tools/_executor_helpers.py:validate_policy()`)

```python
# _executor_helpers.py
enforcement = policy_engine.validate_action_sync(
    action={"type": "bash_execution", "command": "rm -rf /", ...},
    context=PolicyExecutionContext(
        agent_id=..., workflow_id=..., stage_id=...,
        action_type="bash_execution", action_data={...}
    )
)
```

**Step 4 — Emergency Stop Check** (`temper_ai/safety/action_policy_engine.py:411-418`)

```python
if self._emergency_stop is not None and self._emergency_stop.is_active():
    return EnforcementResult(allowed=False, ...)  # short-circuit
```
Emergency stop is clear in this scenario; execution continues.

**Step 5 — Policy Retrieval and Execution** (`action_policy_engine.py:422-432`)

`self.registry.get_policies_for_action("bash_execution")` returns policies sorted by priority. `ForbiddenOperationsPolicy` has `priority = 200` (the highest of all built-in policies), so it runs first.

**Step 6 — Pattern Matching** (`temper_ai/safety/forbidden_operations.py:302-323`)

```python
# forbidden_operations.py:_check_all_patterns()
for pattern_name, pattern_info in self.compiled_patterns.items():
    violation = self._check_single_pattern(command, context, pattern_name, pattern_info)
    if violation:
        violations.append(violation)
```

The compiled `DANGEROUS_COMMAND_PATTERNS` set includes a regex matching `rm\s+-rf\s+/` (or variations). `pattern_info["regex"].search("rm -rf /")` returns a match object. The resulting `SafetyViolation` carries:

```python
SafetyViolation(
    policy_name="forbidden_operations",
    severity=ViolationSeverity.CRITICAL,
    message="Dangerous recursive deletion command detected",
    action="rm -rf /",
    context={...sanitized...},
    remediation_hint="Use safe file deletion with explicit paths",
    metadata={
        "pattern_name": "rm_recursive",
        "category": "dangerous",
        "matched_text": "rm -rf /",
        "match_position": 0,
    }
)
```

**Step 7 — Short-Circuit** (`action_policy_engine.py:319-323`)

```python
if _should_short_circuit_on_critical(self.short_circuit_critical, result.violations):
    logger.warning(f"Short-circuiting on CRITICAL violation from {policy.name}")
    break  # skip remaining policies
```

Remaining policies (SecretDetection, BlastRadius, etc.) are skipped entirely.

**Step 8 — Violation Logging** (`action_policy_engine.py:496-497`)

```python
if self.log_violations and all_violations:
    self._log_violations_sync(all_violations, context)
```

This calls `log_violations_sync()` from `_action_policy_helpers.py`, which sanitizes violation messages through `DataSanitizer` before sending them to `ExecutionTracker.track_safety_violation()`.

**Step 9 — Result Building** (`action_policy_engine.py:377`)

```python
allowed = not any(v.severity >= ViolationSeverity.HIGH for v in all_violations)
# ViolationSeverity.CRITICAL >= HIGH -> True -> allowed = False
```

**Step 10 — Tool Execution Blocked**

Back in `_executor_helpers.py:validate_policy()`, the `EnforcementResult.allowed` is False. The executor returns a `ToolResult` with `success=False` and an error message summarizing the violation. No snapshot was created; no execution occurred.

### 5.3 What Gets Logged

| Level | System | Message |
|---|---|---|
| WARNING | `action_policy_engine` | `Short-circuiting on CRITICAL violation from forbidden_operations` |
| ERROR | `observability.tracker` | `safety_violation: CRITICAL — Dangerous rm command` (sanitized) |
| DEBUG | `tools.executor` | `Policy check failed for bash; action blocked` |

---

## 6. Scenario 2: Secret Detected in LLM Output

**Trigger:** An LLM response contains `AKIAIOSFODNN7EXAMPLE` (a syntactically valid AWS access key format) in a file write action.

### 6.1 Sequence Diagram

```mermaid
sequenceDiagram
    participant Agent as StandardAgent
    participant LLM as LLMService
    participant TExec as ToolExecutor
    participant APE as ActionPolicyEngine
    participant SDP as SecretDetectionPolicy
    participant EA as EntropyAnalyzer
    participant Obs as ObservabilityTracker

    Agent->>LLM: run(prompt, tools=[FileWriter])
    LLM->>LLM: provider.complete() -> LLMResponse with tool_call
    Note over LLM: Tool call: file_writer(\n  file_path="config.yaml",\n  content="aws_key: AKIAIOSFODNN7EXAMPLE"\n)
    LLM->>TExec: execute("file_writer", {"file_path":"config.yaml", "content":"aws_key: AKIAIOSFODNN7EXAMPLE"})

    TExec->>APE: validate_action_sync(action, context)
    APE->>APE: _emergency_stop.is_active() -> False
    APE->>APE: get_policies_for_action("file_write")
    Note over APE: Policies returned: [SDP(P=180), BlastRadius(P=90), ...]

    APE->>SDP: policy.validate(action, context)
    SDP->>SDP: _extract_content(action)\n-> content="aws_key: AKIAIOSFODNN7EXAMPLE"\n   file_path="config.yaml"
    SDP->>SDP: _is_excluded_path("config.yaml") -> False
    SDP->>SDP: _scan_for_secrets(content, file_path, context)
    SDP->>SDP: pattern_matcher.find_matches(content)
    Note over SDP: aws_access_key pattern matches\n"AKIAIOSFODNN7EXAMPLE"
    SDP->>EA: calculate(secret_value="AKIAIOSFODNN7EXAMPLE")
    EA-->>SDP: entropy=3.9 (high randomness)
    SDP->>SDP: _is_test_secret("AKIAIOSFODNN7EXAMPLE") -> False
    Note over SDP: Not generic pattern, so entropy threshold\nnot applied for aws_access_key
    SDP->>SDP: _determine_severity("aws_access_key", entropy=3.9) -> HIGH
    SDP->>SDP: create_redacted_preview() -> "AKIA***MPLE"
    SDP->>SDP: hash_secret() -> HMAC violation_id
    SDP->>SDP: _sanitize_context(context) -> strips any secrets from ctx dict
    SDP-->>APE: ValidationResult(valid=False,\n  violations=[SafetyViolation(severity=HIGH,\n    message="Potential secret (aws_access_key): AKIA***MPLE")])

    APE->>APE: _build_enforcement_result()
    Note over APE: Any HIGH severity -> allowed=False
    APE->>APE: _log_violations_sync(violations, context)
    APE->>Obs: track_safety_violation(sanitized_violation)
    APE-->>TExec: EnforcementResult(allowed=False)

    TExec-->>LLM: ToolResult(success=False,\n  error="Action blocked: secret detected in file content")
    LLM->>LLM: inject tool failure into conversation
    LLM-->>Agent: LLMRunResult noting blocked file write
```

### 6.2 Detailed Step Trace

**Step 1 — Content Extraction** (`temper_ai/safety/secret_detection.py:214-223`)

```python
def _extract_content(self, action: dict[str, Any]) -> tuple[str, str]:
    file_path = action.get("file_path", "")
    content = ""
    if "content" in action:
        content = str(action["content"])
    return content, file_path
```

The content `"aws_key: AKIAIOSFODNN7EXAMPLE"` and path `"config.yaml"` are extracted.

**Step 2 — Path Exclusion Check** (`secret_detection.py:200-201`)

```python
if any(excluded in file_path for excluded in self.excluded_paths):
    return ValidationResult(valid=True, ...)
```

No excluded paths configured; the check proceeds.

**Step 3 — Pattern Matching** (`secret_detection.py:234-249`)

`PatternMatcher.find_matches(content)` iterates over all `SECRET_PATTERNS` — compiled regexes imported from `temper_ai/shared/utils/secret_patterns.py`. The `aws_access_key` pattern `r'\b(AKIA|ASIA)[A-Z0-9]{16}\b'` matches `AKIAIOSFODNN7EXAMPLE`.

**Step 4 — Entropy Calculation** (`secret_detection.py:239`)

```python
entropy = self._calculate_entropy(pattern_match.secret_value)
# Shannon entropy of "AKIAIOSFODNN7EXAMPLE" -> ~3.9 bits/char
```

The `EntropyAnalyzer` at `temper_ai/safety/entropy_analyzer.py` computes Shannon entropy. For `aws_access_key` pattern, entropy filtering is only applied to the generic patterns `generic_api_key` and `generic_secret`.

**Step 5 — Test Secret Filter** (`secret_detection.py:236-237`)

```python
if self._is_test_secret(pattern_match.secret_value):
    continue
```

`TestSecretFilter.is_test_secret()` checks for keywords like `example`, `test`, `demo`, `placeholder`. The value `AKIAIOSFODNN7EXAMPLE` contains `EXAMPLE` — this might be flagged. In production configurations with `allow_test_secrets=False`, this would still be caught. With `allow_test_secrets=True` (default), test-pattern secrets are skipped.

**Step 6 — Severity Determination** (`secret_detection.py:284-293`)

```python
def _determine_severity(self, pattern_name: str, entropy: float) -> ViolationSeverity:
    if pattern_name in ("private_key", "aws_secret_key"):
        return ViolationSeverity.CRITICAL
    elif pattern_name in ("aws_access_key", "github_token", "generic_api_key", "stripe_key"):
        return ViolationSeverity.HIGH
    elif entropy > self.entropy_threshold:
        return ViolationSeverity.HIGH
    else:
        return ViolationSeverity.MEDIUM
```

`aws_access_key` maps to `ViolationSeverity.HIGH`.

**Step 7 — Redacted Preview** (`safety/redaction_utils.py:create_redacted_preview()`)

The preview shows only the first 4 and last 4 characters: `AKIA***MPLE`. The full secret value is never written to any log.

**Step 8 — HMAC Deduplication ID** (`secret_detection.py:265`)

```python
violation_id = hash_secret(pattern_match.matched_text, self._session_key)
```

A session-scoped HMAC-SHA256 hash allows deduplication of the same secret across multiple validation calls without storing the plaintext secret.

**Step 9 — Context Sanitization** (`secret_detection.py:175-179`)

```python
def _sanitize_context(self, context: dict[str, Any]) -> dict[str, Any]:
    from temper_ai.shared.utils.config_helpers import sanitize_config_for_display
    return sanitize_config_for_display(context)
```

The execution context itself (which might contain agent config, environment variables, etc.) is sanitized before being attached to the violation.

**Observability Output:**

The violation is tracked through `ExecutionTracker.track_safety_violation()` with:
- `policy_name = "secret_detection"`
- `severity = "HIGH"`
- `message = "Potential secret detected (aws_access_key): AKIA***MPLE"`
- `metadata.violation_id` = HMAC hash (for deduplication)
- `metadata.entropy = 3.9`
- `metadata.pattern_type = "aws_access_key"`

---

## 7. Scenario 3: LLM Provider Failure and Failover

**Trigger:** The Anthropic API returns HTTP 529 (overloaded). After `max_retries` exhausted, the `FailoverProvider` switches to OpenAI which succeeds.

### 7.1 Sequence Diagram

```mermaid
sequenceDiagram
    participant Agent as StandardAgent
    participant LLM as LLMService
    participant Retry as call_with_retry_sync
    participant FP as FailoverProvider
    participant Anth as AnthropicLLM
    participant OAI as OpenAILLM
    participant CB as CircuitBreaker(anthropic)
    participant Obs as ObservabilityTracker

    Agent->>LLM: run(prompt, tools=[...])
    LLM->>LLM: _build_iteration_state()
    LLM->>Retry: call_with_retry_sync(llm=FailoverProvider, ...)

    Retry->>FP: llm.complete(prompt)
    FP->>FP: _get_start_index() -> 0 (primary: Anthropic)
    FP->>CB: CircuitBreaker.call(anthropic_provider.complete, prompt)
    CB->>Anth: complete(prompt)
    Anth->>Anth: HTTP POST /v1/messages
    Anth-->>Anth: httpx.HTTPStatusError(529)
    Anth->>Anth: map 529 to LLMError("Service overloaded")
    Anth-->>CB: raises LLMError
    CB->>CB: _on_call_failure(error)
    CB->>CB: _failure_count += 1 (now 1/threshold)
    CB-->>FP: raises LLMError

    FP->>FP: _record_failure(anthropic, error, errors, failover_seq)
    FP->>FP: _should_failover(LLMError) -> True (server error)
    Note over FP: attempt=0 failed, try next provider

    FP->>OAI: provider.complete(prompt)
    OAI->>OAI: HTTP POST /v1/chat/completions
    OAI-->>OAI: 200 OK, LLMResponse
    FP->>FP: _record_success(index=1, oai_provider, failover_seq)
    FP->>FP: last_successful_index = 1
    FP->>FP: backup_success_count += 1
    FP-->>Retry: LLMResponse(content="...", tokens=...)

    Retry-->>LLM: (response, None)
    LLM->>LLM: _tracking.track_call(observer, response, attempt)
    LLM->>Obs: track_llm_call(provider="openai", model=..., tokens=..., cost=...)
    LLM-->>Agent: LLMRunResult(output="...", cost=...)

    Note over CB: Anthropic circuit NOT yet open\n(failure_count=1 < threshold)
    Note over Obs: Failover event logged:\n"anthropic:claude-3:LLMError -> openai:gpt-4:success"
```

### 7.2 LLM Retry Logic Detail

**Location:** `temper_ai/llm/_retry.py:23-65`

```python
def call_with_retry_sync(llm, inference_config, prompt, ...):
    max_retries = inference_config.max_retries       # e.g., 3
    retry_delay = float(inference_config.retry_delay_seconds)  # e.g., 1.0

    for attempt in range(max_retries + 1):
        try:
            return llm.complete(prompt, **llm_kwargs), None
        except LLMError as e:
            last_error = e
            safe_err = sanitize_error_message(str(e))  # strip secrets
            track_failed_call(observer, prompt, e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) \
                    * (RETRY_JITTER_MIN + random.random())
                # backoff_delay = 1.0 * 2^0 * (0.5 + rand) = ~0.5-1.5s on attempt 0
                # backoff_delay = 1.0 * 2^1 * (0.5 + rand) = ~1.0-3.0s on attempt 1
                # etc.
                logger.warning("LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries + 1, safe_err, backoff_delay)
                shutdown_event.wait(timeout=backoff_delay)  # interruptible sleep
            else:
                logger.error("LLM call failed after %d attempts: %s",
                    max_retries + 1, safe_err, exc_info=True)

    return None, last_error
```

Key design choices:
- `sanitize_error_message()` is called on the error string before any logging — HTTP response bodies that might include auth tokens are sanitized.
- `shutdown_event.wait(timeout=backoff_delay)` replaces `time.sleep()` — the retry loop is interruptible by a shutdown signal.
- `DEFAULT_BACKOFF_MULTIPLIER = 2.0` from `shared/constants/retries.py` — each delay doubles.
- Random jitter `(RETRY_JITTER_MIN + random.random())` prevents thundering herd when multiple agents hit the same provider simultaneously.

### 7.3 Failover Logic Detail

**Location:** `temper_ai/llm/failover.py:114-148`

```python
def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
    errors: list[str] = []
    failover_sequence: list[str] = []
    start_index = self._get_start_index()  # sticky_session: prefer last successful

    for attempt in range(len(self.providers)):
        index = (start_index + attempt) % len(self.providers)
        provider = self.providers[index]
        try:
            result = provider.complete(prompt, **kwargs)
            self._record_success(index, provider, failover_sequence)
            return result
        except (...) as e:
            self._record_failure(provider, e, errors, failover_sequence)
            if not self._should_failover(e):
                raise  # authentication errors don't failover
    raise LLMError(f"All {len(self.providers)} providers failed. Errors: {'; '.join(errors)}")
```

`_should_failover()` decisions:

| Exception Type | Failover? |
|---|---|
| `LLMTimeoutError`, `httpx.TimeoutException` | Yes (if `failover_on_timeout=True`) |
| `LLMRateLimitError` | Yes (if `failover_on_rate_limit=True`) |
| `httpx.ConnectError`, `ConnectionError` | Yes (if `failover_on_connection_error=True`) |
| HTTP 5xx (`httpx.HTTPStatusError`) | Yes (if `failover_on_server_error=True`) |
| HTTP 4xx | No by default (`failover_on_client_error=False`) |
| `LLMAuthenticationError` | Never — same key would fail everywhere |

**Sticky session semantics:** After a successful failover to OpenAI (index 1), `last_successful_index` is set to 1. Subsequent calls start at OpenAI. After `retry_primary_after` (default 3) backup successes, the next call resets to index 0 and tries Anthropic again.

---

## 8. Scenario 4: Tool Execution Failure and Rollback

**Trigger:** `FileWriter` creates `/tmp/work/output.json`, then the next tool call in the same iteration fails — triggering auto-rollback to delete the newly created file.

### 8.1 Rollback Lifecycle Flowchart

```mermaid
flowchart TD
    A["ToolExecutor.execute(file_writer, {file_path: /tmp/work/output.json})"]
    A --> B["validate_and_get_tool() -> FileWriter instance"]
    B --> C["BaseTool.validate_params() -> OK"]
    C --> D["policy_engine.validate_action_sync() -> allowed=True"]
    D --> E["RollbackManager.create_snapshot(action, context)"]

    E --> E1["FileRollbackStrategy.create_snapshot()"]
    E1 --> E2["_extract_file_paths(action) -> ['/tmp/work/output.json']"]
    E2 --> E3{"/tmp/work/output.json exists?"}
    E3 -- No --> E4["snapshot.metadata['/tmp/work/output.json_existed'] = False"]
    E3 -- Yes --> E5["read content into snapshot.file_snapshots[path]"]
    E4 --> E6["RollbackSnapshot(id=uuid, file_snapshots={}, metadata={..._existed=False})"]
    E5 --> E6

    E6 --> F["cache lookup: miss"]
    F --> G["acquire_concurrent_slot()"]
    G --> H["tool_executor ThreadPool.submit(FileWriter.execute, ...)"]
    H --> I["FileWriter writes /tmp/work/output.json"]
    I --> J["ToolResult(success=True)"]
    J --> K["cache_store(result)"]
    K --> L["release_concurrent_slot()"]
    L --> M["return ToolResult.success=True"]

    M --> N["LLMService: second tool call in same iteration"]
    N --> O["ToolExecutor.execute(second_tool, params)"]
    O --> P["second_tool.execute() RAISES exception"]
    P --> Q{enable_auto_rollback?}
    Q -- Yes --> R["handle_exception_rollback()"]
    R --> R1["RollbackManager.execute_rollback(snapshot.id)"]
    R1 --> R2["FileRollbackStrategy.execute_rollback(snapshot)"]
    R2 --> R3["validate_rollback(snapshot) -> OK"]
    R3 --> R4{"_existed = False\n(file was created by our tool)"}
    R4 -- True --> R5["_delete_created_files()"]
    R5 --> R6["validate_rollback_path('/tmp/work/output.json')"]
    R6 --> R7["realpath() + allowed_dirs check + symlink check"]
    R7 --> R8["TOCTOU: recheck path immediately before deletion"]
    R8 --> R9["os.remove(real_path)\nresult.reverted_items.append('deleted:/tmp/work/output.json')"]
    R9 --> R10["RollbackResult(success=True, status=COMPLETED)"]
    R10 --> R11["_trigger_rollback_callbacks(result)"]
    R11 --> R12["observability.rollback_logger.log_rollback_event(result)"]
    Q -- No --> S["return ToolResult.failure(error=str(exc))"]
```

### 8.2 Rollback Security Validation

Every path access in rollback operations passes through `validate_rollback_path()` at `temper_ai/safety/rollback.py:72-144`. This function:

1. Checks for null bytes in the path string (injection prevention).
2. Calls `os.path.realpath(os.path.abspath(file_path))` to resolve symlinks and relative paths.
3. If `check_symlinks=True` (default), iterates `Path.parents` checking `is_symlink()` on each ancestor directory.
4. Confirms the resolved path starts with one of the allowed directories (`/tmp`, `/var/tmp`, `~/.cache`, `os.getcwd()`).
5. Rejects paths within `["/etc", "/sys", "/proc", "/dev", "/boot"]`.

The rollback additionally performs a TOCTOU (time-of-check-time-of-use) double-check: `validate_rollback_path()` is called again immediately before the `os.remove()` call, at `rollback.py:547-556`. The path is re-resolved with `os.path.realpath()` between checks to prevent race-condition symlink swaps.

**Atomic file restoration** uses `tempfile.mkstemp()` + `os.replace()` pattern (`rollback.py:486-499`):

```python
fd, tmp_path = _tempfile.mkstemp(dir=dir_path)
try:
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp_path, file_path)  # atomic on POSIX
    return True
except Exception:
    os.unlink(tmp_path)  # clean up temp file
    raise
```

### 8.3 RollbackResult States

| `RollbackStatus` | Meaning |
|---|---|
| `IN_PROGRESS` | Rollback started, not yet complete |
| `COMPLETED` | All files/state restored successfully |
| `PARTIAL` | Some items reverted, some failed (e.g., file permissions changed) |
| `FAILED` | No items reverted (e.g., all paths failed security validation) |

---

## 9. Scenario 5: Circuit Breaker Trip and Recovery

**Trigger:** The Anthropic provider fails 5 times consecutively (default `failure_threshold=5`) — the circuit opens. Subsequent calls fast-fail. After `timeout_seconds=60`, the circuit enters HALF_OPEN and allows one probe call which succeeds, restoring CLOSED state.

### 9.1 Circuit Breaker State Diagram

```mermaid
stateDiagram-v2
    [*] --> CLOSED : Initial state

    CLOSED --> CLOSED : call() success\n_failure_count reset to 0\nrecord_success()

    CLOSED --> CLOSED : call() failure\n_failure_count < failure_threshold\nrecord_failure() increments count

    CLOSED --> OPEN : call() failure\n_failure_count >= failure_threshold\n_transition_to(OPEN)\n_opened_at = now()\n_fire_callbacks(old=CLOSED, new=OPEN)

    OPEN --> OPEN : call() attempted\ntime < timeout_seconds\n_reserve_execution() -> None\nmetrics.rejected_calls += 1\nraises CircuitBreakerError

    OPEN --> HALF_OPEN : time >= timeout_seconds\nauto-transition in .state property\n_success_count reset to 0\n_transition_to(HALF_OPEN)

    HALF_OPEN --> HALF_OPEN : probe call in flight\n_half_open_semaphore prevents\nmultiple concurrent probes

    HALF_OPEN --> OPEN : probe call() failure\n_transition_to(OPEN)\n_opened_at = now()\n_failure_count = 0\n_success_count = 0

    HALF_OPEN --> HALF_OPEN : probe call() success\n_success_count += 1\n_success_count < success_threshold (default 2)

    HALF_OPEN --> CLOSED : probe call() success\n_success_count >= success_threshold\n_transition_to(CLOSED)\n_failure_count = 0\n_success_count = 0\n_fire_callbacks(old=HALF_OPEN, new=CLOSED)
```

### 9.2 Detailed Execution Trace

**Phase 1 — Failures accumulating (CLOSED state)**

At `temper_ai/shared/core/circuit_breaker.py:352-380`, each failure calls `record_failure()`:

```python
def record_failure(self, error: Exception | None = None) -> None:
    pending = None
    with self.lock:
        self.metrics.total_calls += 1
        self.metrics.failed_calls += 1
        self.metrics.last_failure_time = datetime.now(UTC)
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                pending = self._transition_to(CircuitState.OPEN)
                self._opened_at = datetime.now(UTC)
                self._failure_count = 0  # reset counter after opening
    _fire_callbacks_helper(pending, breaker=self)
```

On the 5th failure: `_failure_count (5) >= failure_threshold (5)` triggers `_transition_to(OPEN)`.

**Phase 2 — Open state fast-fail**

At `circuit_breaker.py:382-400`, `call()` attempts:

```python
def call(self, func, *args, **kwargs):
    reserved_state = _reserve_execution_helper(self)
    if reserved_state is None:
        with self.lock:
            self.metrics.rejected_calls += 1
        raise CircuitBreakerError(
            f"Circuit breaker OPEN for {self.name}. "
            f"Retry after {_time_until_retry_helper(...):.0f}s"
        )
    ...
```

`_reserve_execution_helper()` checks `self._state != CircuitState.OPEN`. When OPEN, it returns `None`, triggering the `CircuitBreakerError` raise. No network call is made — this is the "fast fail" benefit.

**Phase 3 — Timeout and HALF_OPEN transition**

The `state` property in `circuit_breaker.py:279-297` performs auto-transition:

```python
@property
def state(self) -> CircuitState:
    with self.lock:
        if self._state == CircuitState.OPEN:
            if (self._last_failure_time is None or
                    (time.time() - self._last_failure_time) >= self.config.timeout):
                pending = self._transition_to(CircuitState.HALF_OPEN)
                self._success_count = 0
        current = self._state
    _fire_callbacks_helper(pending, breaker=self)
    return current
```

After `timeout_seconds` (default 60) pass, the next call to `.state` triggers the transition to HALF_OPEN. The `_half_open_semaphore = threading.Semaphore(1)` in `_reserve_execution_helper()` ensures only one probe call goes through concurrently.

**Phase 4 — Recovery**

If the probe call at HALF_OPEN succeeds, `record_success()` at `circuit_breaker.py:329-350` increments `_success_count`. When `_success_count >= success_threshold` (default 2), the circuit closes:

```python
if self._state == CircuitState.HALF_OPEN:
    self._success_count += 1
    if self._success_count >= self.config.success_threshold:
        pending = self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
```

### 9.3 Integration With ActionPolicyEngine

`CircuitBreakerError` is listed in the caught exception tuple at `action_policy_engine.py:325`:

```python
except (AttributeError, TypeError, ValueError, KeyError, RuntimeError, CircuitBreakerError) as e:
    violation = self._create_execution_error_violation(policy, action, context, e)
    all_violations.append(violation)
```

A circuit-breaker trip during policy execution creates a `CRITICAL` violation with `metadata={"exception_type": "CircuitBreakerError"}`. This converts a resilience event into a blocking safety result — the tool call is blocked rather than proceeding without policy validation.

### 9.4 Observability Callbacks

State change callbacks are registered via `CircuitBreaker.on_state_change()` and fire through `_fire_callbacks_helper()` at `shared/core/_circuit_breaker_helpers.py`. The `observability_callback` parameter passed at construction time allows `ExecutionTracker` to record circuit state transitions as resilience events.

---

## 10. Scenario 6: Approval Required for High-Risk Action

**Trigger:** An agent in SUPERVISED autonomy level attempts a HIGH-severity action (such as a production database write). The `ApprovalRouter` determines a human approver is required. Execution waits until approval or expiry.

### 10.1 Sequence Diagram

```mermaid
sequenceDiagram
    participant Agent as StandardAgent
    participant TExec as ToolExecutor
    participant APE as ActionPolicyEngine
    participant Router as ApprovalRouter
    participant AW as ApprovalWorkflow
    participant Human as Human Operator

    Agent->>TExec: execute("db_writer", {query: "UPDATE users SET ...", db: "prod"})
    TExec->>APE: validate_action_sync(action, context)

    APE->>APE: Execute policies in priority order...
    Note over APE: BlastRadiusPolicy detects HIGH severity\n(affects >1000 rows)
    APE-->>TExec: EnforcementResult(allowed=False,\n  violations=[HIGH: blast_radius])

    TExec->>TExec: enforcement.allowed=False AND violation.severity=HIGH
    TExec->>TExec: handle_approval_rejection()

    Note over TExec: Check if ApprovalWorkflow configured
    TExec->>Router: route_action(agent_name, domain,\n  violations=[HIGH], autonomy_level=SUPERVISED)

    Router->>Router: _get_max_severity([HIGH]) -> HIGH
    Router->>Router: autonomy_level(SUPERVISED) < AUTONOMOUS
    Router-->>TExec: ApprovalDecision(requires_approval=True,\n  required_approvers=1, reason="HIGH violation requires 1 approver")

    TExec->>AW: request_approval(params=ApprovalRequestParams(\n  action={"query":"UPDATE users..."}, reason="HIGH blast radius",\n  violations=[HIGH violation], required_approvers=1,\n  timeout_minutes=30))

    AW->>AW: Build ApprovalRequest(id=uuid,\n  status=PENDING,\n  expires_at=now()+30min,\n  required_approvers=1)
    AW->>AW: _lock.acquire() -> _requests[req.id] = request
    AW-->>TExec: ApprovalRequest(id="req-abc123", status=PENDING)

    Note over TExec: Poll until approved/rejected/expired\nor return pending result immediately

    Human->>AW: workflow.approve("req-abc123", approver="alice", reason="Confirmed safe")
    AW->>AW: _lock.acquire()
    AW->>AW: check_approver_authorized("alice", request, authorized_approvers)
    AW->>AW: request.approvers.append("alice")
    AW->>AW: not needs_more_approvals() -> True
    AW->>AW: request.status = APPROVED
    AW->>AW: trigger_approved_callbacks(request, _on_approved_callbacks)
    AW-->>Human: True (approval accepted)

    TExec->>AW: is_approved("req-abc123") -> True
    TExec->>TExec: Re-enter execution with approval confirmed
    TExec->>TExec: tool.execute(params) -> ToolResult.success
    TExec-->>Agent: ToolResult(success=True)
```

### 10.2 Approval Router Matrix

**Location:** `temper_ai/safety/autonomy/approval_router.py`

The `ApprovalRouter.route_action()` implements a severity-by-autonomy-level matrix:

| Severity | SUPERVISED | SPOT_CHECKED | RISK_GATED | AUTONOMOUS | STRATEGIC |
|---|---|---|---|---|---|
| CRITICAL | 2 approvers | 2 approvers | 2 approvers | 2 approvers | 2 approvers |
| HIGH | 1 approver | 1 approver | 1 approver | auto-approve | auto-approve |
| MEDIUM | 1 approver | 10% sampled | auto-approve | auto-approve | auto-approve |
| LOW/None | auto-approve | auto-approve | auto-approve | auto-approve | auto-approve |

`CRITICAL` violations always require 2 approvers regardless of autonomy level. This is a hard-coded policy constant (`CRITICAL_APPROVERS = 2`) at `approval_router.py:14`.

SPOT_CHECKED mode uses probabilistic sampling for MEDIUM violations. The `_spot_check_decision()` at `approval_router.py:105-114` calls `random.random()` (non-security random, explicitly noted with `# noqa: S311`) against `SPOT_CHECK_SAMPLE_RATE`.

### 10.3 Approval States

**Location:** `temper_ai/safety/approval.py:40-54`

```python
class ApprovalStatus(Enum):
    PENDING   = "pending"    # Awaiting approval
    APPROVED  = "approved"   # Required approvals received
    REJECTED  = "rejected"   # Rejected by any approver (one rejection enough)
    EXPIRED   = "expired"    # Timeout elapsed without approval
    CANCELLED = "cancelled"  # Request cancelled programmatically
```

Key behaviors:
- **One rejection is enough.** Any approver can block; approval requires `required_approvers` count.
- **Self-approval is blocked.** `check_approver_authorized()` at `_approval_helpers.py` raises `PermissionError` if `approver == request.requester` when `authorized_approvers` is set.
- **Timeout is lazy.** `has_expired()` checks `datetime.now(UTC) >= expires_at`. Expiration is processed on the next call to `is_pending()`, `approve()`, `list_pending_requests()`, or `cleanup_expired_requests()`.
- **Max requests = 10,000.** Beyond this, `evict_oldest_completed()` removes the oldest resolved requests. Pending requests are never evicted.
- **Development mode** uses `NoOpApprover` which immediately sets `status=APPROVED` on every `request_approval()` call.

---

## 11. Scenario 7: Emergency Stop

**Trigger:** The `BudgetEnforcer` detects that the agent's cost has exceeded its configured USD budget, or an external operator triggers an emergency stop via the autonomy API.

### 11.1 Emergency Stop Flowchart

```mermaid
flowchart TD
    A{Trigger source}
    A -- "Budget exhausted" --> B["BudgetEnforcer.check_budget(scope)\n-> BudgetCheckResult(allowed=False, status=EXHAUSTED)"]
    A -- "Operator API call" --> C["POST /api/autonomy/emergency-stop"]
    A -- "Anomaly detected" --> D["AutonomyManager detects\nbehavior outside policy bounds"]

    B --> E["AutonomyManager._handle_budget_exceeded()"]
    C --> E
    D --> E

    E --> F["EmergencyStopController.activate(\n  triggered_by='budget_enforcer',\n  reason='Budget $5.00 exhausted',\n  agents_halted=[...]\n)"]

    F --> F1["_stop_lock.acquire()"]
    F1 --> F2["_stop_event.set()\n(module-level threading.Event)"]
    F2 --> F3["event_id = 'es-' + uuid4().hex[:12]"]
    F3 --> F4["_active_event_id = event_id"]
    F4 --> F5["_stop_lock.release()"]
    F5 --> F6["AutonomyStore.save_emergency_event(EmergencyStopEvent)"]
    F6 --> F7["logger.warning('EMERGENCY STOP activated by ...')"]

    F7 --> G[/"All running threads checking is_active()"/]
    G --> H{"_stop_event.is_set() -> True"}

    H -- "ActionPolicyEngine.validate_action_sync()" --> I["Return EnforcementResult(\n  allowed=False,\n  metadata={'reason': 'emergency_stop_active'}\n)"]
    H -- "ActionPolicyEngine.validate_action() (async)" --> I
    H -- "EmergencyStopController.check_or_raise()" --> J["raise EmergencyStopError()"]

    I --> K["ToolExecutor receives allowed=False\nall tool calls blocked immediately"]
    J --> L["Propagates up call stack\nstage executor catches and marks stage failed"]

    K --> M["Agent loop iteration fails\nreturns error result to stage executor"]
    L --> M

    M --> N["Stage executor marks\nall pending agents as stopped"]
    N --> O["WorkflowStageError propagates\nworkflow runtime records EMERGENCY_STOP"]
    O --> P["Workflow terminates\nFinal state: STOPPED_EMERGENCY"]

    P --> Q["EmergencyStopController.deactivate(\n  resolution_reason='operator_cleared'\n)"]
    Q --> Q1["_stop_event.clear()"]
    Q1 --> Q2["_active_event_id = None"]
    Q2 --> Q3["AutonomyStore.save_emergency_event(resolved_at=now())"]
```

### 11.2 O(1) Emergency Stop Design

**Location:** `temper_ai/safety/autonomy/emergency_stop.py:20-24`

```python
# Module-level event for O(1) cross-thread signaling
_stop_event = threading.Event()
_stop_lock = threading.Lock()
_active_event_id: str | None = None
```

The key design insight is that `_stop_event` is a module-level singleton. Every `EmergencyStopController` instance (there is one per `ActionPolicyEngine`) shares the same `_stop_event`. The `is_active()` check:

```python
def is_active(self) -> bool:
    return _stop_event.is_set()  # O(1) — no lock, no allocations
```

`threading.Event.is_set()` is implemented as a single atomic boolean read in CPython — truly O(1) with no locking overhead. This is called at the very top of both `validate_action()` and `validate_action_sync()` in `ActionPolicyEngine`, meaning every tool call in every agent in every thread checks the emergency stop within microseconds of it being set.

### 11.3 Budget Enforcement Integration

**Location:** `temper_ai/safety/autonomy/budget_enforcer.py:70-108`

```python
def check_budget(self, scope: str, estimated_cost: float = 0.0) -> BudgetCheckResult:
    budget = self._get_or_create_budget(scope)
    remaining = budget.budget_usd - budget.spent_usd

    if remaining <= 0:
        return BudgetCheckResult(
            allowed=False,
            remaining_usd=0.0,
            status=STATUS_EXHAUSTED,
            message=f"Budget exhausted for scope '{scope}'"
        )
    if estimated_cost > remaining:
        return BudgetCheckResult(
            allowed=False,
            remaining_usd=remaining,
            status=STATUS_WARNING,
            message=f"Estimated cost ${estimated_cost:.4f} exceeds remaining ${remaining:.4f}"
        )
    ...
```

The `AutonomyPolicy` safety policy (listed as `"autonomy_policy"` in `factory.py`) integrates `BudgetEnforcer.check_budget()` into the standard policy execution chain. A budget exhaustion result is translated into a safety violation before being returned from `AutonomyPolicy.validate()`.

### 11.4 Audit Trail

Every emergency stop activation creates a persisted `EmergencyStopEvent` in `AutonomyStore` with:
- `id`: `"es-" + 12-char hex` (unique per event)
- `triggered_by`: who or what caused the stop
- `reason`: human-readable description
- `agents_halted`: list of agent names that were running
- `halt_duration_ms`: time elapsed between `_stop_event.set()` and completion of activation
- `resolved_at`: null until `deactivate()` is called

The `reset_emergency_state()` function at `emergency_stop.py:128-133` is only for test isolation — it clears the module-level state without creating an audit record.

---

## 12. Scenario 8: Stage Retry with Exponential Backoff

**Trigger:** An agent in a sequential stage fails with `LLM_TIMEOUT` (a transient error). The stage's `error_handling.on_agent_failure = "retry_agent"` with `max_agent_retries = 3`. The first two retries also fail. The third succeeds.

### 12.1 Retry Flow Trace

```mermaid
sequenceDiagram
    participant SExec as SequentialStageExecutor
    participant Helper as _sequential_helpers
    participant Retry as _sequential_retry
    participant Agent as StandardAgent
    participant Obs as ObservabilityTracker

    SExec->>SExec: execute_stage(stage_name, stage_config, state)
    SExec->>Helper: run_all_agents(ctx, agents, prior_outputs)

    loop for each agent_ref in stage_config.agents
        Helper->>Helper: execute_agent(ctx, agent_ref, prior_outputs)
        Helper->>Agent: agent.run(prompt, tools, ...)
        Agent-->>Helper: raises LLMTimeoutError\nor returns error result

        Helper->>Helper: result[status] = "failed"
        Helper->>Helper: error_type = "LLM_TIMEOUT"
        Helper->>Retry: _process_agent_failure(agent_name, result, error_handling, ...)
        Retry->>Retry: error_handling.on_agent_failure = "retry_agent"
        Retry->>Retry: _handle_retry_policy(agent_name, result, error_handling, ctx, ...)
        Retry->>Retry: is_transient_error("LLM_TIMEOUT") -> True
        Retry->>Retry: max_retries = error_handling.max_agent_retries = 3

        Retry->>Retry: retry_agent_with_backoff(ctx, agent_ref, outputs, max_retries=3, ...)

        Note over Retry: attempt 1
        Retry->>Retry: delay = MIN_BACKOFF_SECONDS * 2^0 = 1.0s
        Retry->>Retry: min(1.0, 30.0) = 1.0s
        Retry->>Retry: ctx.executor.shutdown_event.wait(timeout=1.0)
        Retry->>Helper: _execute_retry_attempt(ctx, agent_ref, ...)
        Helper->>Agent: agent.run(prompt, tools, ...)
        Agent-->>Helper: LLMTimeoutError again
        Helper-->>Retry: (failed_result, should_stop=False)

        Note over Retry: attempt 2
        Retry->>Retry: delay = MIN_BACKOFF_SECONDS * 2^1 = 2.0s
        Retry->>Retry: ctx.executor.shutdown_event.wait(timeout=2.0)
        Retry->>Helper: _execute_retry_attempt(...)
        Helper->>Agent: agent.run(...)
        Agent-->>Helper: LLMTimeoutError again
        Helper-->>Retry: (failed_result, should_stop=False)

        Note over Retry: attempt 3
        Retry->>Retry: delay = MIN_BACKOFF_SECONDS * 2^2 = 4.0s
        Retry->>Retry: ctx.executor.shutdown_event.wait(timeout=4.0)
        Retry->>Helper: _execute_retry_attempt(...)
        Helper->>Agent: agent.run(...)
        Agent-->>Helper: LLMRunResult(output="...", status="success")
        Helper-->>Retry: (success_result, should_stop=True)

        Retry->>Retry: success_result[METRICS][RETRIES] = 3
        Retry->>Obs: emit_retry_event(RetryEventData(\n  attempt=3, max_retries=3,\n  outcome=RETRY_OUTCOME_SUCCESS,\n  error_type="LLM_TIMEOUT",\n  is_transient=True, backoff_delay=4.0))
        Retry-->>Helper: success_result

        Helper->>Helper: store output to accum.outputs[agent_name]
        Helper->>Helper: accum.statuses[agent_name] = "success"
    end

    Helper-->>SExec: (agent_outputs, agent_statuses, agent_metrics)
    SExec->>SExec: _resolve_final_output(agent_outputs, ...)
    SExec-->>SExec: stage result: SUCCESS
```

### 12.2 Backoff Calculation

**Location:** `temper_ai/stage/executors/_sequential_retry.py:120-151`

```python
def retry_agent_with_backoff(..., max_retries: int, ...):
    base_delay = MIN_BACKOFF_SECONDS  # 1.0s from shared/constants/retries.py

    for attempt in range(1, max_retries + 1):
        delay = min(
            base_delay * (DEFAULT_BACKOFF_MULTIPLIER ** (attempt - 1)),  # 2^(attempt-1)
            SECONDS_PER_MINUTE / MAX_RETRY_BACKOFF_DIVISOR   # 60 / 2 = 30s cap
        )
        # attempt=1: delay = min(1.0 * 2^0, 30) = 1.0s
        # attempt=2: delay = min(1.0 * 2^1, 30) = 2.0s
        # attempt=3: delay = min(1.0 * 2^2, 30) = 4.0s
        # attempt=4: delay = min(1.0 * 2^3, 30) = 8.0s
        # attempt=5: delay = min(1.0 * 2^4, 30) = 16.0s
        # attempt=6: delay = min(1.0 * 2^5, 30) = 30.0s (capped)

        logger.info("Retrying agent %s (attempt %d/%d, backoff %.1fs)", ...)

        if ctx.executor.shutdown_event.wait(timeout=delay):
            raise KeyboardInterrupt("Executor shutdown requested")
```

The `shutdown_event.wait(timeout=delay)` returns `True` if the event is set (shutdown signaled) — in that case, the retry loop raises `KeyboardInterrupt` immediately rather than waiting the full backoff period. This makes retry loops responsive to graceful shutdown signals.

### 12.3 Transient vs. Permanent Error Classification

**Location:** `temper_ai/stage/executors/_sequential_retry.py:43-57`

```python
_TRANSIENT_ERROR_TYPES: frozenset[str] = frozenset({
    ErrorCode.LLM_CONNECTION_ERROR.value,   # "LLM_CONNECTION_ERROR"
    ErrorCode.LLM_TIMEOUT.value,            # "LLM_TIMEOUT"
    ErrorCode.LLM_RATE_LIMIT.value,         # "LLM_RATE_LIMIT"
    ErrorCode.SYSTEM_TIMEOUT.value,         # "SYSTEM_TIMEOUT"
    ErrorCode.SYSTEM_RESOURCE_ERROR.value,  # "SYSTEM_RESOURCE_ERROR"
    ErrorCode.TOOL_TIMEOUT.value,           # "TOOL_TIMEOUT"
    ErrorCode.AGENT_TIMEOUT.value,          # "AGENT_TIMEOUT"
    ErrorCode.WORKFLOW_TIMEOUT.value,       # "WORKFLOW_TIMEOUT"
})
```

Non-transient errors (e.g., `SAFETY_ACTION_BLOCKED`, `AGENT_MAX_ITERATIONS`, `CONFIG_INVALID`) cause the retry loop to exit immediately regardless of remaining attempts. A mid-retry permanent error triggers `should_stop=True` in `_execute_retry_attempt()` at line 86-93.

### 12.4 Error Handling Policies

**Location:** `temper_ai/stage/executors/_sequential_retry.py:246-287`

| `on_agent_failure` | Behavior |
|---|---|
| `halt_stage` | Stop all remaining agents; return "break" action; stage fails |
| `skip_agent` | Log warning; continue with remaining agents; no retry |
| `retry_agent` | Classify error; if transient + `max_retries > 0`, call `retry_agent_with_backoff()` |
| `continue_with_remaining` | Log warning; store failure; continue with remaining agents |

---

## 13. Error Propagation Across Layers

This flowchart shows how a tool-level error propagates upward through all execution layers.

```mermaid
flowchart TD
    T0["Tool.execute() raises exception\nor returns ToolResult(success=False)"]
    T0 --> T1["ToolExecutor catches exception\ncreates ToolResult.failure(error=str(exc))\nhandle_exception_rollback() if enable_auto_rollback"]
    T1 --> T2["LLM service receives ToolResult\ntool result injected into conversation\nas error message for next LLM iteration"]

    T2 --> T3{Max iterations reached?}
    T3 -- No --> T4["LLM generates next response\n(may retry tool call or give up)"]
    T3 -- Yes --> T5["MaxIterationsError raised\n(AGENT_MAX_ITERATIONS error_code)"]

    T4 --> T6{LLM call succeeds?}
    T6 -- Yes --> T7["Continue agent loop"]
    T6 -- "LLMError raised" --> T8["call_with_retry_sync retries\nwith exponential backoff"]
    T8 --> T9{Retries exhausted?}
    T9 -- No --> T6
    T9 -- Yes --> T10{"FailoverProvider\nconfigured?"}
    T10 -- Yes --> T11["Try next provider\nin failover chain"]
    T11 --> T12{All providers failed?}
    T12 -- No --> T6
    T12 -- Yes --> T13["LLMError propagates\n(all providers exhausted)"]
    T10 -- No --> T13

    T5 --> A1["StandardAgent._execute_iteration()\ncatches MaxIterationsError\nreturns error dict to stage executor"]
    T13 --> A1

    A1 --> A2["Agent.run() returns LLMRunResult\nwith status='failed', error_type='LLM_TIMEOUT'\nor raises AgentError"]

    A2 --> S1["_sequential_helpers.execute_agent()\nbuilds result dict:\n{status:'failed', error_type:'LLM_TIMEOUT'}"]
    S1 --> S2["_process_agent_failure(agent_name, result, error_handling, ...)"]
    S2 --> S3{on_agent_failure policy}
    S3 -- halt_stage --> S4["SequentialStageExecutor\nreturns state with\nstatus='failed', error=..."]
    S3 -- retry_agent+transient --> S5["retry_agent_with_backoff()\n(see Scenario 8)"]
    S5 --> S6{Max retries}
    S6 -- exhausted --> S4
    S6 -- success --> S7["Stage continues normally"]
    S3 -- skip_agent --> S7
    S3 -- continue_with_remaining --> S7

    S4 --> W1["Workflow engine receives\nstage result with status='failed'"]
    W1 --> W2{Stage error_policy}
    W2 -- halt --> W3["WorkflowStageError raised\nWorkflow terminates immediately"]
    W2 -- continue --> W4["Stage marked failed in state\nremaining stages continue"]

    W3 --> E1["WorkflowRuntime records\nFINAL_STATUS=FAILED\ntrack_workflow(status='failed', error=...)"]
    W4 --> E2["Workflow completes\nwith partial failure noted\nin final state"]
```

---

## 14. Observability Integration in Error Paths

Every failure path in the framework emits structured observability events. The `ExecutionTracker` at `temper_ai/observability/tracker.py` is the central hub.

### 14.1 Track Points by Scenario

| Scenario | Track Method | Location |
|---|---|---|
| Safety violation | `tracker.track_safety_violation(violation, context)` | `_action_policy_helpers.py:log_violations_sync()` |
| LLM call failure | `tracker.track_failed_call(...)` | `llm/_tracking.py:track_failed_call()` |
| LLM retry attempt | `logger.warning("LLM call failed (attempt N/M)")` | `llm/_retry.py:53` |
| Provider failover | `logger.info("Failover: index A -> B (model)")` | `llm/failover.py:205` |
| Tool execution failure | `ToolResult(success=False, error=...)` returned | `tools/_executor_helpers.py` |
| Rollback event | `_trigger_rollback_callbacks(result)` | `safety/rollback.py:932` |
| Agent retry | `emit_retry_event(RetryEventData(...))` | `stage/executors/_sequential_retry.py:167` |
| Retry exhausted | `emit_retry_event(outcome=RETRY_OUTCOME_EXHAUSTED)` | `stage/executors/_sequential_retry.py:191` |
| Circuit breaker state change | `_fire_callbacks_helper(pending, breaker=self)` | `shared/core/circuit_breaker.py:296` |
| Emergency stop activation | `logger.warning("EMERGENCY STOP activated by %s")` | `safety/autonomy/emergency_stop.py:83` |
| Stage failure | `tracker.track_stage(stage_name, status='failed', ...)` | `stage/executors/base.py` |
| Workflow failure | `tracker.track_workflow(status='failed', ...)` | `workflow/engines/native_engine.py` |

### 14.2 Data Sanitization in Error Paths

Before any error data reaches logs or the observability backend:

**In exceptions** (`shared/utils/exceptions.py:104-139`):
```python
def sanitize_error_message(message: str) -> str:
    message = _sanitize_aws_keys(message)        # AKIA*, ASIA*
    message = _sanitize_api_keys(message)        # sk-*, api-*, api_key=*
    message = _sanitize_jwt_tokens(message)      # Bearer ..., eyJ*
    message = _sanitize_passwords(message)       # password=*, pwd=*
    message = _sanitize_generic_tokens(message)  # token=*, auth=*
    message = _sanitize_connection_strings(message)  # mysql://:@
    return message
```

`BaseError.__str__()` at line 313 calls `sanitize_error_message(super().__str__())` — secrets are stripped even when the exception is converted to string by Python's default exception handling machinery.

**In violation logging** (`_action_policy_helpers.py:log_violations_sync()`):
```python
# Lazy-init sanitizer on first violation
if self._sanitizer is None:
    from temper_ai.observability.sanitization import DataSanitizer
    self._sanitizer = DataSanitizer()
log_violations_sync(violations, context, self._sanitizer)
```

The `DataSanitizer` at `observability/sanitization.py` applies compiled regex patterns to all string fields in the violation's `action`, `context`, and `message` before writing to the observability backend.

**In the observability backend** (`observability/backends/sql_backend.py`):

The SQL backend receives pre-sanitized records. No raw secret values should ever reach the database layer, but the backend applies a second sanitization pass to any string fields as defense-in-depth.

---

## 15. Error Fingerprinting and Deduplication

**Location:** `temper_ai/observability/error_fingerprinting.py`

### 15.1 Fingerprint Algorithm

```
1. Extract error_type (class name, e.g., "LLMTimeoutError")
2. Extract error_code (ErrorCode enum value, e.g., "LLM_TIMEOUT")
3. Sanitize message: strip secrets via DataSanitizer
4. Normalize message:
   - Replace UUIDs: [0-9a-fA-F]{8}-... -> <UUID>
   - Replace timestamps: 2026-02-22T... -> <TIMESTAMP>
   - Replace 3+ digit numbers: \b\d{3,}\b -> <N>
   - Replace Unix paths with 2+ segments: /foo/bar -> <PATH>
   - Replace hex IDs (8+ chars): [0-9a-fA-F]{8,} -> <HEX>
   - Replace memory addresses: 0x... -> <ADDR>
5. Truncate normalized message to 256 characters
6. Compute: SHA-256("error_type:error_code:normalized_message")
7. Return first 16 hex characters
```

### 15.2 Error Classification

**Location:** `error_fingerprinting.py:50-87`

```python
_TRANSIENT_CODES = frozenset({
    "LLM_CONNECTION_ERROR", "LLM_TIMEOUT", "LLM_RATE_LIMIT",
    "SYSTEM_TIMEOUT", "SYSTEM_RESOURCE_ERROR",
    "TOOL_TIMEOUT", "AGENT_TIMEOUT", "WORKFLOW_TIMEOUT",
})

_SAFETY_CODES = frozenset({
    "SAFETY_VIOLATION", "SAFETY_POLICY_ERROR", "SAFETY_ACTION_BLOCKED",
})
```

`classify_error(error_code)` returns:
- `TRANSIENT` — worth retrying; temporary condition
- `PERMANENT` — not worth retrying; fix required
- `SAFETY` — blocked by policy; requires human intervention
- `UNKNOWN` — unrecognized code

### 15.3 Usage in Dashboards

The `ErrorFingerprinter` accumulates statistics per fingerprint: `occurrence_count`, `first_seen`, `last_seen`, `recent_workflow_ids`, `recent_agent_ids`. This enables the dashboard to show "top 10 error patterns" aggregated across thousands of executions, and to differentiate a transient network issue (lots of occurrences, TRANSIENT classification) from a code bug (fewer occurrences, PERMANENT classification).

---

## 16. Configuration Reference — Safety Parameters

### 16.1 ActionPolicyEngine Configuration

Passed as `config` dict to `ActionPolicyEngine.__init__()`:

| Parameter | Default | Effect |
|---|---|---|
| `cache_ttl` | `TTL_LONG` (300s) | How long to cache policy validation results |
| `max_cache_size` | `THRESHOLD_MEDIUM_COUNT` (1000) | Maximum cached results (LRU eviction) |
| `enable_caching` | `True` | Disable for high-security environments |
| `short_circuit_critical` | `True` | Stop running policies after first CRITICAL violation |
| `log_violations` | `True` | Emit violations to observability |
| `fail_open` | `False` | SECURITY: Default deny when no policies match. Set `True` only for dev/test |

### 16.2 CircuitBreaker Configuration

Passed as `CircuitBreakerConfig` or individual kwargs:

| Parameter | Default | Effect |
|---|---|---|
| `failure_threshold` | `CIRCUIT_BREAKER_FAILURE_THRESHOLD` (5) | Failures before OPEN |
| `success_threshold` | `2` | Successes at HALF_OPEN before CLOSED |
| `timeout` | `CIRCUIT_BREAKER_RESET_TIMEOUT` (60s) | OPEN wait before HALF_OPEN probe |

Constants from `shared/constants/retries.py`.

### 16.3 LLM Retry Configuration

From `InferenceConfig` in agent YAML:

| Parameter | Default | Effect |
|---|---|---|
| `max_retries` | `3` | Attempts before error propagates |
| `retry_delay_seconds` | `1.0` | Base delay (doubles each attempt + jitter) |

### 16.4 Stage Retry Configuration

From `ErrorHandlingConfig` in stage YAML:

| Parameter | Default | Effect |
|---|---|---|
| `on_agent_failure` | `"continue_with_remaining"` | halt_stage / skip_agent / retry_agent / continue_with_remaining |
| `max_agent_retries` | `0` | Only applies when `on_agent_failure="retry_agent"` |

### 16.5 Rollback Configuration

Passed to `ToolExecutor` constructor:

| Parameter | Default | Effect |
|---|---|---|
| `enable_auto_rollback` | `True` | Automatically revert on tool failure |
| `rollback_manager` | `RollbackManager()` | Can inject custom strategies |

### 16.6 Approval Workflow Configuration

Passed to `ApprovalWorkflow.__init__()`:

| Parameter | Default | Effect |
|---|---|---|
| `default_timeout_minutes` | 30 | Auto-reject after this many minutes |
| `auto_reject_on_timeout` | `True` | Automatically mark expired requests as REJECTED |
| `authorized_approvers` | `None` | If set, only listed users can approve; self-approval blocked |
| `max_requests` | `10000` | Maximum stored requests (oldest completed evicted) |

### 16.7 EmergencyStop Configuration

| Parameter | Location | Default |
|---|---|---|
| `EMERGENCY_STOP_TIMEOUT_SECONDS` | `safety/autonomy/constants.py` | 3600 (1 hour) |

### 16.8 Budget Enforcement

| Parameter | Location | Default |
|---|---|---|
| `DEFAULT_BUDGET_USD` | `safety/autonomy/constants.py` | `10.0` |
| `BUDGET_WARNING_THRESHOLD` | `safety/autonomy/constants.py` | `0.8` (80%) |

---

## 17. Design Patterns and Architectural Decisions

### 17.1 Fail-Closed as Default

Every safety check defaults to denying actions when uncertain. When no policies match an action type and `fail_open=False` (default), the engine denies the action and logs a warning. Policy execution errors themselves produce CRITICAL violations, blocking the action. This "fail-closed" approach means a misconfigured system is safe rather than permissive.

### 17.2 Emergency Stop as O(1) Module-Level State

The `_stop_event = threading.Event()` is declared at module level in `emergency_stop.py`. This means:
- Every `EmergencyStopController` instance shares the same event (singleton pattern via module globals).
- `is_active()` is a single `Event.is_set()` call — no lock, no allocation, no function call overhead beyond CPython's native method dispatch.
- The event is process-wide: an emergency stop in one agent immediately affects all agents in the same process.

The trade-off: `reset_emergency_state()` must be called explicitly in tests to reset this global state between test cases.

### 17.3 Secret Sanitization as Defense-in-Depth

Secrets are sanitized at multiple independent layers:
1. In `BaseError.__str__()` — before Python prints the exception.
2. In `call_with_retry_sync()` — before logging retry failure messages.
3. In `_log_violations_sync()` — before writing violations to observability.
4. In `DataSanitizer` — before writing any data to the SQL backend.
5. In `sanitize_error_message()` in exception `to_dict()` — before serializing to JSON.

Any one of these layers catching a secret prevents it from being logged. All layers together provide defense against new secret patterns that are not yet covered by any single sanitizer's regexes.

### 17.4 Error Code Taxonomy as Cross-Cutting Concern

`ErrorCode` enums in `shared/utils/exceptions.py` are used by:
- `_sequential_retry.py` — to classify errors as transient vs. permanent
- `error_fingerprinting.py` — to classify errors as TRANSIENT/PERMANENT/SAFETY
- Dashboard and alerting — to route errors to appropriate handlers
- Tests — to assert on specific error categories without matching message strings

This centralization means adding a new error category (e.g., for M10 auth errors) requires a single addition to `ErrorCode` and the classification frozensets.

### 17.5 Rollback as Pre-Emptive Snapshot

The `RollbackManager.create_snapshot()` is called before every tool execution — not after failure. This is simpler and safer than a copy-on-write approach: the snapshot exists before any mutation occurs. The cost is always-paid snapshot overhead; the benefit is guaranteed rollback capability even if the failure prevents any state access after the fact.

### 17.6 Retry Loop Interruptibility

Both LLM retries (`llm/_retry.py:57`) and stage agent retries (`_sequential_retry.py:134`) use `Event.wait(timeout=delay)` instead of `time.sleep(delay)`. The event is set on shutdown. This means:
- Retry delays are interruptible by graceful shutdown.
- The worker thread can exit cleanly within `delay` seconds of a shutdown signal.
- Long backoff delays (e.g., 30s cap) do not block process termination.

### 17.7 Approval Workflow Thread Safety

The `ApprovalWorkflow._lock = threading.Lock()` at `approval.py:219` guards all access to `_requests`. Every method that reads or writes `_requests` acquires this lock. The lock is a `threading.Lock` (non-reentrant) — no method that holds the lock calls another method that also acquires it. This prevents deadlocks while ensuring correct behavior under concurrent approval/rejection from multiple threads.

### 17.8 Cache Invalidation on Policy Change

`ActionPolicyEngine._invalidate_cache_if_policies_changed()` at `action_policy_engine.py:532-540` computes a snapshot of all registered policy names and clears the validation result cache when the snapshot changes. This ensures that dynamically adding or removing policies (e.g., loading a new custom policy at runtime) immediately invalidates stale cached results that were produced under a different policy set.

---

## 18. Key File References

All paths are relative to the repository root `temper_ai/`.

### Safety Core

| File | Lines of Interest | What It Does |
|---|---|---|
| `safety/action_policy_engine.py` | 136-240 | `validate_action()` — async enforcement entry point |
| `safety/action_policy_engine.py` | 400-440 | `validate_action_sync()` — sync enforcement entry point |
| `safety/action_policy_engine.py` | 276-334 | `_execute_policies_async()` — policy loop with short-circuit |
| `safety/forbidden_operations.py` | 302-367 | `_check_all_patterns()` / `_check_single_pattern()` |
| `safety/secret_detection.py` | 181-251 | `_validate_impl()` / `_scan_for_secrets()` |
| `safety/secret_detection.py` | 284-293 | `_determine_severity()` — severity mapping |
| `safety/approval.py` | 167-305 | `ApprovalWorkflow.request_approval()` |
| `safety/approval.py` | 307-359 | `ApprovalWorkflow.approve()` — multi-approver logic |
| `safety/rollback.py` | 72-144 | `validate_rollback_path()` — security validation |
| `safety/rollback.py` | 346-398 | `FileRollbackStrategy.create_snapshot()` |
| `safety/rollback.py` | 400-427 | `FileRollbackStrategy.execute_rollback()` |
| `safety/rollback.py` | 797-895 | `RollbackManager.create_snapshot()` / `execute_rollback()` |
| `safety/autonomy/emergency_stop.py` | 20-24 | Module-level `_stop_event` declaration |
| `safety/autonomy/emergency_stop.py` | 44-87 | `EmergencyStopController.activate()` |
| `safety/autonomy/emergency_stop.py` | 114-116 | `is_active()` — O(1) check |
| `safety/autonomy/approval_router.py` | 43-95 | `ApprovalRouter.route_action()` — severity x autonomy matrix |
| `safety/autonomy/budget_enforcer.py` | 70-108 | `BudgetEnforcer.check_budget()` |
| `safety/factory.py` | 298 | `create_safety_stack()` — wires all components |

### LLM Error Handling

| File | Lines of Interest | What It Does |
|---|---|---|
| `llm/_retry.py` | 23-65 | `call_with_retry_sync()` — exponential backoff + jitter |
| `llm/_retry.py` | 68-108 | `call_with_retry_async()` — async variant |
| `llm/failover.py` | 114-148 | `FailoverProvider.complete()` — multi-provider chain |
| `llm/failover.py` | 240-275 | `_should_failover()` — error type routing |
| `llm/failover.py` | 199-209 | `_record_success()` — sticky session update |

### Stage Retry

| File | Lines of Interest | What It Does |
|---|---|---|
| `stage/executors/_sequential_retry.py` | 43-52 | `_TRANSIENT_ERROR_TYPES` frozenset |
| `stage/executors/_sequential_retry.py` | 99-151 | `retry_agent_with_backoff()` |
| `stage/executors/_sequential_retry.py` | 207-243 | `_handle_retry_policy()` |
| `stage/executors/_sequential_retry.py` | 246-287 | `_handle_agent_failure()` — policy dispatch |

### Circuit Breaker

| File | Lines of Interest | What It Does |
|---|---|---|
| `shared/core/circuit_breaker.py` | 78-103 | `CircuitState` enum, `CircuitBreakerError` |
| `shared/core/circuit_breaker.py` | 279-297 | `state` property — auto-transition OPEN->HALF_OPEN |
| `shared/core/circuit_breaker.py` | 329-350 | `record_success()` — HALF_OPEN->CLOSED transition |
| `shared/core/circuit_breaker.py` | 352-380 | `record_failure()` — CLOSED->OPEN transition |
| `shared/core/circuit_breaker.py` | 382-400 | `call()` — fast-fail when OPEN |

### Exceptions and Errors

| File | Lines of Interest | What It Does |
|---|---|---|
| `shared/utils/exceptions.py` | 104-139 | `sanitize_error_message()` — secret stripping |
| `shared/utils/exceptions.py` | 142-204 | `ErrorCode` enum taxonomy |
| `shared/utils/exceptions.py` | 207-337 | `FrameworkException` / `BaseError` hierarchy |
| `shared/utils/exceptions.py` | 466-489 | `LLMRateLimitError` — multiple inheritance |
| `shared/utils/error_handling.py` | 26-83 | `RetryParams.calculate_delay()` — delay strategies |
| `shared/utils/error_handling.py` | 86-172 | `retry_with_backoff()` decorator |

### Observability

| File | Lines of Interest | What It Does |
|---|---|---|
| `observability/error_fingerprinting.py` | 50-87 | `classify_error()` — TRANSIENT/PERMANENT/SAFETY |
| `observability/error_fingerprinting.py` | 95-100 | `normalize_message()` — volatile token replacement |
| `observability/sanitization.py` | (full file) | `DataSanitizer` — PII/secret redaction before persistence |
| `observability/resilience_events.py` | (full file) | `RetryEventData`, `emit_retry_event()` |
| `observability/rollback_logger.py` | (full file) | `log_rollback_event()` |
