# 09 — Safety Stack Architecture

**Document Version:** 1.0.0
**Codebase Revision:** Post-M10 (Multi-Tenant), as of 2026-02-22
**Scope:** `temper_ai/safety/` and `temper_ai/shared/core/circuit_breaker.py`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Safety Stack Composition — `create_safety_stack()`](#3-safety-stack-composition)
4. [Interfaces and Core Data Structures](#4-interfaces-and-core-data-structures)
5. [BaseSafetyPolicy — Composition Foundation](#5-basesafetypolicy)
6. [PolicyRegistry — Routing Layer](#6-policyregistry)
7. [ActionPolicyEngine — Central Enforcement](#7-actionpolicyengine)
8. [Policy Composition — PolicyComposer](#8-policycomposer)
9. [Concrete Safety Policies](#9-concrete-safety-policies)
   - 9.1 ForbiddenOperationsPolicy
   - 9.2 SecretDetectionPolicy + EntropyAnalyzer
   - 9.3 BlastRadiusPolicy
   - 9.4 FileAccessPolicy
   - 9.5 WindowRateLimitPolicy
   - 9.6 TokenBucketRateLimitPolicy
   - 9.7 ResourceLimitPolicy
   - 9.8 ConfigChangePolicy
   - 9.9 PromptInjectionPolicy
10. [Approval Workflow](#10-approval-workflow)
11. [Circuit Breaker System](#11-circuit-breaker-system)
12. [Rollback System](#12-rollback-system)
13. [LLM Security Layer](#13-llm-security-layer)
14. [Autonomy Management System](#14-autonomy-management-system)
    - 14.1 AutonomyLevel and AutonomyConfig
    - 14.2 AutonomyManager — State Machine
    - 14.3 TrustEvaluator
    - 14.4 BudgetEnforcer
    - 14.5 EmergencyStopController
    - 14.6 ApprovalRouter — Severity x Level Matrix
    - 14.7 ShadowMode — Promotion Validation
    - 14.8 MeritSafetyBridge
    - 14.9 AutonomyPolicy — Safety Policy Integration
15. [Redaction and Secret Utilities](#15-redaction-and-secret-utilities)
16. [Stub Policies](#16-stub-policies)
17. [Exceptions Hierarchy](#17-exceptions-hierarchy)
18. [Configuration Reference](#18-configuration-reference)
19. [Design Patterns and Decisions](#19-design-patterns-and-decisions)
20. [Extension Guide](#20-extension-guide)
21. [Security Properties](#21-security-properties)

---

## 1. Executive Summary

**System Name:** Temper AI Safety Stack

**Purpose:** The safety stack is a multi-layered, composable policy enforcement system that intercepts every agent tool call and autonomous action before execution, validating it against a configurable set of safety policies, and providing rollback, approval, rate-limiting, secret detection, blast-radius control, and progressive autonomy management.

**Technology Stack:**
- Python 3.11+, asyncio, threading
- Pydantic v2 (autonomy schemas), SQLModel (autonomy persistence)
- psutil (resource monitoring)
- HMAC-SHA256, Shannon entropy analysis

**Scope of Analysis:** All files under `temper_ai/safety/`, including the autonomy subsystem, plus the canonical `temper_ai/shared/core/circuit_breaker.py`.

**Key Design Principle:** Defense in depth. Every tool call passes through multiple independent policy checks. Failures in any policy are themselves treated as CRITICAL violations (fail-closed). The system defaults to denying actions when no policies are registered.

---

## 2. Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          TEMPER AI SAFETY STACK                                 │
│                                                                                 │
│  ┌────────────────┐    ┌────────────────────────────────────────────────────┐  │
│  │   Agent /      │    │                 ToolExecutor                       │  │
│  │   Workflow     │───▶│  (entry point for all tool calls)                  │  │
│  │   Executor     │    └──────────────┬─────────────────────────────────────┘  │
│  └────────────────┘                   │                                         │
│                                       ▼                                         │
│                        ┌─────────────────────────────┐                          │
│                        │      ActionPolicyEngine       │ ◀── PolicyRegistry     │
│                        │  (validate_action / sync)     │     (routing)          │
│                        └──────────┬──────────────────┘                          │
│                                   │                                             │
│              ┌────────────────────┼────────────────────────────┐               │
│              ▼                    ▼                             ▼               │
│  ┌─────────────────┐  ┌───────────────────────┐  ┌─────────────────────────┐   │
│  │  ForbiddenOps   │  │   SecretDetection      │  │    BlastRadius           │   │
│  │  Policy (P=200) │  │   Policy (P=180)       │  │    Policy (P=90)         │   │
│  └─────────────────┘  └───────────────────────┘  └─────────────────────────┘   │
│  ┌─────────────────┐  ┌───────────────────────┐  ┌─────────────────────────┐   │
│  │  PromptInject   │  │   RateLimit (Token     │  │    ResourceLimit         │   │
│  │  Policy (P=180) │  │   Bucket) (P=150)      │  │    Policy (P=80)         │   │
│  └─────────────────┘  └───────────────────────┘  └─────────────────────────┘   │
│  ┌─────────────────┐  ┌───────────────────────┐  ┌─────────────────────────┐   │
│  │  FileAccess     │  │   WindowRateLimit      │  │    ConfigChange          │   │
│  │  Policy         │  │   Policy               │  │    Policy                │   │
│  └─────────────────┘  └───────────────────────┘  └─────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         AutonomyPolicy                                   │    │
│  │   EmergencyStop → BudgetEnforcer → ApprovalRouter                       │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                   │                                             │
│                    ┌──────────────▼──────────────┐                             │
│                    │   EnforcementResult           │                             │
│                    │   allowed: bool               │                             │
│                    │   violations: list            │                             │
│                    └──────────────┬──────────────┘                             │
│                                   │                                             │
│           ┌───────────────────────┼──────────────────────────┐                │
│           ▼                       ▼                          ▼                │
│  ┌────────────────┐   ┌──────────────────────┐  ┌──────────────────────┐    │
│  │ ApprovalWork-  │   │   RollbackManager     │  │  CircuitBreaker      │    │
│  │ flow           │   │   (snapshot / revert) │  │  (CLOSED/OPEN/HALF)  │    │
│  └────────────────┘   └──────────────────────┘  └──────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Component Map

| Component | Location | Purpose |
|---|---|---|
| `create_safety_stack()` | `safety/factory.py` | Wires all components, returns `ToolExecutor` |
| `PolicyRegistry` | `safety/policy_registry.py` | Routes actions to applicable policies |
| `ActionPolicyEngine` | `safety/action_policy_engine.py` | Central enforcement, caching, async |
| `PolicyComposer` | `safety/composition.py` | Composes policies, aggregates results |
| `BaseSafetyPolicy` | `safety/base.py` | Base class with child composition |
| `ForbiddenOperationsPolicy` | `safety/forbidden_operations.py` | Blocks bash writes, rm -rf, eval, exec |
| `SecretDetectionPolicy` | `safety/secret_detection.py` | Detects API keys, tokens, private keys |
| `EntropyAnalyzer` | `safety/entropy_analyzer.py` | Shannon entropy for generic secrets |
| `BlastRadiusPolicy` | `safety/blast_radius.py` | Limits files/lines/entities per op |
| `FileAccessPolicy` | `safety/file_access.py` | Whitelist-based file path control |
| `WindowRateLimitPolicy` | `safety/rate_limiter.py` | Sliding/fixed window rate limits |
| `TokenBucketRateLimitPolicy` | `safety/policies/rate_limit_policy.py` | Token bucket with burst support |
| `ResourceLimitPolicy` | `safety/policies/resource_limit_policy.py` | File size, memory, disk limits |
| `ConfigChangePolicy` | `safety/config_change_policy.py` | Config mutation validation |
| `PromptInjectionPolicy` | `safety/prompt_injection_policy.py` | Wraps `PromptInjectionDetector` |
| `ApprovalWorkflow` | `safety/approval.py` | Human-review workflow for high-risk actions |
| `RollbackManager` | `safety/rollback.py` | Pre-action snapshots, revert on failure |
| `CircuitBreaker` | `shared/core/circuit_breaker.py` | CLOSED/OPEN/HALF_OPEN state machine |
| `SafetyGate` | `safety/circuit_breaker.py` | Gate combining circuit breaker + policies |
| `AutonomyManager` | `safety/autonomy/manager.py` | Progressive autonomy state machine |
| `TrustEvaluator` | `safety/autonomy/trust_evaluator.py` | Merit-score-based trust computation |
| `BudgetEnforcer` | `safety/autonomy/budget_enforcer.py` | USD cost budget enforcement |
| `EmergencyStopController` | `safety/autonomy/emergency_stop.py` | O(1) global halt via threading.Event |
| `ApprovalRouter` | `safety/autonomy/approval_router.py` | Severity x autonomy level matrix |
| `ShadowMode` | `safety/autonomy/shadow_mode.py` | Shadow validation before promotion |
| `MeritSafetyBridge` | `safety/autonomy/merit_bridge.py` | Bridges merit scores to autonomy eval |

---

## 3. Safety Stack Composition

### `create_safety_stack()` — The Wiring Function

**Location:** `temper_ai/safety/factory.py:298`

This is the primary factory function that wires together all safety components and returns a `ToolExecutor` ready for production use.

```mermaid
flowchart TD
    A["create_safety_stack(tool_registry, config_path, environment)"]
    A --> B["1. Determine environment\n(TEMPER_SAFETY_ENV or 'development')"]
    B --> C["2. load_safety_config(config_path, environment)\n(YAML with env overrides)"]
    C --> D["3. create_policy_registry(config)\n- parse policy_mappings\n- parse global_policies\n- instantiate each policy"]
    D --> E["4. ActionPolicyEngine(policy_registry, engine_config)\n- cache_ttl, max_cache_size\n- short_circuit_critical\n- fail_open/fail_closed"]
    E --> F{"environment?"}
    F -- "development OR approval_mode='noop'" --> G["NoOpApprover\n(auto-approve all)"]
    F -- "staging / production" --> H["ApprovalWorkflow\n(requires human review)"]
    G --> I["5. RollbackManager()"]
    H --> I
    I --> J["6. ToolExecutor(\n  registry=tool_registry,\n  policy_engine=engine,\n  approval_workflow=approver,\n  rollback_manager=manager,\n  enable_auto_rollback=True\n)"]
    J --> K["Return ToolExecutor\n(ready for agent use)"]
```

### Built-in Policy Registry

The factory maintains two policy class registries:

```python
# temper_ai/safety/factory.py:45
_BUILTIN_POLICIES = {
    "secret_detection_policy":  SecretDetectionPolicy,
    "file_access_policy":       FileAccessPolicy,
    "forbidden_ops_policy":     ForbiddenOperationsPolicy,
    "blast_radius_policy":      BlastRadiusPolicy,
    "rate_limiter_policy":      WindowRateLimitPolicy,
    "config_change_policy":     ConfigChangePolicy,
    "rate_limit_policy":        TokenBucketRateLimitPolicy,
    "resource_limit_policy":    ResourceLimitPolicy,
    "approval_workflow_policy": ApprovalWorkflowPolicy,   # stub
    "circuit_breaker_policy":   CircuitBreakerPolicy,     # stub
    "autonomy_policy":          AutonomyPolicy,
    "prompt_injection_policy":  PromptInjectionPolicy,
}

_CUSTOM_POLICIES = {}  # populated by register_policy_class()
```

Custom policies registered via `register_policy_class(name, cls)` take precedence over built-ins.

### Policy Config Loading

```python
# configs/safety/action_policies.yaml structure (example)
policy_engine:
  cache_ttl: 60
  max_cache_size: 1000
  enable_caching: true
  short_circuit_critical: true
  log_violations: true

global_policies:
  - rate_limit_policy
  - secret_detection_policy

policy_mappings:
  file_write:
    - file_access_policy
    - forbidden_ops_policy
    - blast_radius_policy
  git_commit:
    - forbidden_ops_policy
    - rate_limit_policy

policy_config:
  rate_limit_policy:
    per_agent: true
    cooldown_multiplier: 1.0

environments:
  production:
    policy_engine:
      fail_open: false
```

Deep merge applies environment-specific overrides on top of the base config. If the YAML file does not exist, safe defaults are used (all caching on, short-circuit on, no policies registered — which triggers fail-closed behavior).

---

## 4. Interfaces and Core Data Structures

**Location:** `temper_ai/safety/interfaces.py`

### ViolationSeverity

```python
class ViolationSeverity(Enum):
    CRITICAL = 5   # Blocks immediately, no override
    HIGH     = 4   # Blocks unless approved
    MEDIUM   = 3   # Warning + logging (may require approval at low autonomy)
    LOW      = 2   # Logging only
    INFO     = 1   # Informational
```

Comparison operators are implemented so that `severity >= ViolationSeverity.HIGH` is the canonical blocking check. Any violation at HIGH or above causes `ValidationResult.valid = False`.

### SafetyViolation

```python
@dataclass
class SafetyViolation:
    policy_name:       str               # which policy detected it
    severity:          ViolationSeverity
    message:           str               # human-readable description
    action:            str               # the action that triggered it
    context:           dict[str, Any]    # execution context snapshot
    timestamp:         str               # ISO UTC timestamp (auto-set)
    remediation_hint:  str | None        # how to fix it
    metadata:          dict[str, Any]    # policy-specific details
```

### ValidationResult

```python
@dataclass
class ValidationResult:
    valid:      bool
    violations: list[SafetyViolation]   # may include INFO/LOW on valid results
    metadata:   dict[str, Any]
    policy_name: str

    def has_critical_violations(self) -> bool: ...
    def has_blocking_violations(self) -> bool:   # HIGH or CRITICAL
        return any(v.severity >= ViolationSeverity.HIGH for v in self.violations)
    def get_violations_by_severity(self, severity) -> list[SafetyViolation]: ...
```

### ActionDescriptor (TypedDict)

```python
class ActionDescriptor(TypedDict, total=False):
    type:      str          # discriminator: "tool_call", "file_op", "api_call"
    tool:      str          # tool name
    args:      dict         # tool arguments
    operation: str          # "read", "write", "delete"
    path:      str          # file path
    endpoint:  str          # API endpoint
    method:    str          # HTTP method
    command:   str          # shell command
```

### LLM Security Boundary Protocols

The interfaces file also defines three `Protocol` classes that bridge the `safety/` and `security/` layers without a hard import dependency:

```python
class PromptInjectionDetectorProtocol(Protocol):
    def detect(self, prompt: str) -> tuple[bool, list]: ...

class OutputSanitizerProtocol(Protocol):
    def sanitize(self, output: str) -> tuple[str, list]: ...

class LLMRateLimiterProtocol(Protocol):
    def check_rate_limit(self, entity_id: str) -> tuple[bool, str | None]: ...
```

---

## 5. BaseSafetyPolicy

**Location:** `temper_ai/safety/base.py:23`

`BaseSafetyPolicy` implements `SafetyPolicy` (ABC) and adds:
1. Config validation with strict security bounds
2. Child policy composition (tree structure)
3. Short-circuit on CRITICAL violations from children
4. Both sync (`validate`) and async (`validate_async`) paths

### Config Validation at Construction

```python
def __init__(self, config: dict[str, Any]):
    # Key checks:
    # - config must be dict
    # - max 100 keys (THRESHOLD_LARGE_COUNT)
    # - all keys must be strings
    # - nested dict max depth = 4 (_MAX_CONFIG_DEPTH)
    # - list/tuple max 1000 items (THRESHOLD_VERY_LARGE_COUNT)
    # - string values max MAX_TEXT_LENGTH chars
```

This prevents DoS via deeply-nested or oversized configuration payloads.

### Validation Execution Flow

```
validate(action, context)
│
├─ for child in _child_policies (sorted by priority desc):
│    child_result = child.validate(action, context)
│    if child_result.has_critical_violations():
│        metadata[SHORT_CIRCUIT_KEY] = True
│        break   ◀── short-circuit!
│
├─ if NOT short-circuited:
│    own_result = self._validate_impl(action, context)
│
└─ _finalize_validation(violations, metadata)
       valid = not any(v.severity >= HIGH for v in violations)
       for v in violations: self.report_violation(v)
       return ValidationResult(valid, violations, metadata, policy_name)
```

The async path (`validate_async`) is identical but calls `child.validate_async()` and `self._validate_async_impl()`. The default `_validate_async_impl` delegates to the synchronous `_validate_impl`.

### Validity Determination

A `ValidationResult.valid = False` only when violations include severity `HIGH` (4) or above. `MEDIUM`, `LOW`, and `INFO` violations do NOT invalidate an action — they are informational.

---

## 6. PolicyRegistry

**Location:** `temper_ai/safety/policy_registry.py:22`

The `PolicyRegistry` is the routing layer. It maps action type strings to ordered lists of applicable policies.

### Data Structure

```python
_policies: dict[str, list[SafetyPolicy]]   # action_type -> [policies sorted by priority]
_global_policies: list[SafetyPolicy]        # apply to ALL actions
_policy_mappings: dict[str, set[str]]       # policy_name -> set of action_types (empty = global)
```

### Registration

```python
# Global policy (runs on every action)
registry.register_policy(rate_limit_policy)           # action_types=None

# Action-specific policy
registry.register_policy(file_access_policy,
    action_types=["file_read", "file_write"])
```

Duplicate policy names raise `ValueError`. Policies are automatically sorted by `priority` (descending) within each action type bucket.

### Lookup

```python
def get_policies_for_action(self, action_type: str) -> list[SafetyPolicy]:
    # 1. Start with a copy of global policies
    # 2. Append action-specific policies for action_type
    # 3. Re-sort all by priority (highest first)
    # Returns combined list (global + specific), sorted
```

### Thread Safety

All read and write operations acquire `self._lock` (threading.Lock), making the registry safe for concurrent agent use.

### SA-06: Cache Invalidation on Policy Change

The `ActionPolicyEngine` tracks a "policy snapshot" (a hash of registered policy names). When the snapshot changes between calls — because a policy was registered or unregistered — the entire validation cache is cleared, preventing stale cached results from bypassing newly added policies.

---

## 7. ActionPolicyEngine

**Location:** `temper_ai/safety/action_policy_engine.py:125`

The `ActionPolicyEngine` is the central enforcement component. Every tool call validation passes through it.

### Initialization

```python
ActionPolicyEngine(
    policy_registry,          # PolicyRegistry with registered policies
    config = {
        "cache_ttl":              60,      # seconds (TTL_LONG)
        "max_cache_size":         1000,    # max cached results
        "enable_caching":         True,    # result cache
        "short_circuit_critical": True,    # stop on first CRITICAL
        "log_violations":         True,    # emit to observability
        "fail_open":              False,   # SECURITY: default deny when no policies
    },
    emergency_stop = None,    # optional EmergencyStopController
)
```

### PolicyExecutionContext

```python
@dataclass
class PolicyExecutionContext:
    agent_id:    str
    workflow_id: str
    stage_id:    str
    action_type: str           # used for policy routing
    action_data: dict[str, Any]
    metadata:    dict[str, Any]
```

### EnforcementResult

```python
@dataclass
class EnforcementResult:
    allowed:           bool          # True = action may proceed
    violations:        list[SafetyViolation]
    policies_executed: list[str]     # names of executed policies
    execution_time_ms: float
    metadata:          dict[str, Any]  # violation counts, cache hit, short_circuit
    cache_hit:         bool
```

### Async Validation Flow

```mermaid
sequenceDiagram
    participant Agent
    participant APE as ActionPolicyEngine
    participant ES as EmergencyStop
    participant Reg as PolicyRegistry
    participant Cache as LRU Cache
    participant Policy as SafetyPolicy
    participant Obs as Observability

    Agent->>APE: validate_action(action, context)
    APE->>ES: is_active()?
    alt EmergencyStop ACTIVE
        APE-->>Agent: EnforcementResult(allowed=False, reason=emergency_stop)
    end
    APE->>APE: _invalidate_cache_if_policies_changed()
    APE->>Reg: get_policies_for_action(context.action_type)
    alt No policies registered
        APE->>APE: fail_open? allow : deny
        APE-->>Agent: EnforcementResult (no policies)
    end
    loop for each policy (priority order)
        APE->>APE: compute cache_key(policy, action, context)
        APE->>Cache: get_cached_result(cache_key)
        alt Cache HIT
            Cache-->>APE: ValidationResult (cached)
        else Cache MISS
            APE->>Policy: validate_async(action, context_dict)
            Policy-->>APE: ValidationResult
            APE->>Cache: cache_result(key, result)
        end
        APE->>APE: collect violations
        alt CRITICAL violation AND short_circuit_critical
            APE->>APE: BREAK (short-circuit)
        end
    end
    APE->>Obs: log_violations(violations, context)
    APE-->>Agent: EnforcementResult(allowed, violations, ...)
```

### Blocking Criteria

```
allowed = not any(v.severity >= ViolationSeverity.HIGH for v in all_violations)
```

MEDIUM, LOW, INFO violations are collected and reported but do NOT block execution.

### Fail-Closed Default

When no policies are registered for an action type AND `fail_open=False` (the default), the engine **denies** the action. This is the secure default — unknown action types are blocked, not allowed. `fail_open=True` is documented as a development/testing-only option.

### Error Handling as CRITICAL Violations

When a policy raises an exception during validation, the engine catches `AttributeError, TypeError, ValueError, KeyError, RuntimeError, CircuitBreakerError` and converts it to a `CRITICAL` violation. This is intentional: a broken policy guard should not allow an action through. The exception type (but not the message) is included in the violation metadata.

### Performance Cache

The engine uses an `OrderedDict` as an LRU cache keyed by:
```
sha256(policy.name + str(action) + agent_id + action_type + workflow_id + stage_id)
```
Cache entries expire after `cache_ttl` seconds. The cache is bounded by `max_cache_size` (evicting oldest on overflow). Cache results are invalidated globally when the policy registry changes.

### Sync Variant

`validate_action_sync()` mirrors `validate_action()` but calls `policy.validate()` instead of `policy.validate_async()`. This is used by `StandardAgent._execute_iteration()` which runs in a synchronous context.

### Metrics

```python
engine.get_metrics() -> {
    "validations_performed": int,
    "violations_logged": int,
    "cache_size": int,
    "cache_hits": int,
    "cache_misses": int,
    "cache_hit_rate": float,
    "policies_registered": int,
}
```

---

## 8. PolicyComposer

**Location:** `temper_ai/safety/composition.py:77`

`PolicyComposer` is a higher-level aggregator that can hold multiple policies and run them as a unit. It is distinct from `ActionPolicyEngine` — while APE routes based on action type and has caching, `PolicyComposer` is a simple ordered execution container often used for `SafetyGate` integration or testing.

### CompositeValidationResult

```python
@dataclass
class CompositeValidationResult:
    valid:              bool              # True only if ALL policies passed with no violations
    violations:         list[SafetyViolation]
    policy_results:     dict[str, ValidationResult]  # per-policy results
    policies_evaluated: int
    policies_skipped:   int              # in fail_fast mode
    execution_order:    list[str]        # names in execution order
    metadata:           dict[str, Any]
```

Note: `CompositeValidationResult.valid` is `True` only when there are **zero** violations total, including INFO/LOW. This is stricter than `ValidationResult.valid`.

### Fail-Fast vs Full Evaluation

```python
PolicyComposer(policies=[], fail_fast=False)  # evaluate ALL even on violation
PolicyComposer(policies=[], fail_fast=True)   # stop after first violation
```

In `fail_fast=True` mode, subsequent policies are still tracked in `execution_order` but their evaluation is skipped (`policies_skipped` incremented).

### Error Treatment

Policy evaluation errors are converted to CRITICAL violations and stored in `policy_results[policy.name]`. Unlike APE's error handling, the `CompositeValidationResult` continues evaluating remaining policies (unless `fail_fast=True`).

---

## 9. Concrete Safety Policies

### 9.1 ForbiddenOperationsPolicy

**Location:** `temper_ai/safety/forbidden_operations.py:54`
**Priority:** 200 (highest among concrete policies — runs first)

Detects and blocks forbidden shell operations in the `command`, `bash`, or `args.command` fields of an action.

#### Pattern Categories

| Category | Key Patterns | Severity |
|---|---|---|
| `file_write` | `cat >`, `cat >>`, `cat <<EOF`, `echo >`, `echo >>`, `printf >`, `tee`, `sed -i`, `awk >`, shell redirect `>` | CRITICAL |
| `dangerous` | `rm -rf`, `dd if=`, `mkfs`, `format`, `shred`, `wget \| bash`, `curl \| sh` | CRITICAL |
| `injection` | `;` chain, `&&`, `\|\|`, backtick subshell, `$(...)` subshell | HIGH |
| `security` | `eval`, `exec`, `pickle.loads`, `__import__('os')`, `subprocess.call` | CRITICAL |
| `custom` | User-defined patterns via `custom_forbidden_patterns` config | Configurable |

#### Whitelist

Commands can be explicitly whitelisted:
```python
ForbiddenOperationsPolicy(config={
    "whitelist_commands": ["git status", "git log"],
    "check_file_writes": True,
    "check_dangerous_commands": True,
    "check_injection_patterns": True,
    "check_security_sensitive": True,
})
```

Whitelist matching uses `in` containment (substring match), not exact match.

#### ReDoS Protection

All patterns use bounded quantifiers (e.g., `.{0,200}` instead of `.*`) to prevent catastrophic backtracking. Custom patterns are validated with a `test_timeout=0.001` timeout during compilation.

#### File Write Pattern Enforcement

This policy enforces the Claude Agent coding rules (from CLAUDE.md) at the runtime level — bash file writes (`cat >`, `echo >`, etc.) are detected and blocked with a CRITICAL violation and a remediation hint pointing to the `Write()` or `Edit()` tool.

### 9.2 SecretDetectionPolicy + EntropyAnalyzer

**Location:** `temper_ai/safety/secret_detection.py:37`, `temper_ai/safety/entropy_analyzer.py:9`
**Priority:** 180 (second — runs early due to criticality of secret leakage)

#### Pattern Registry

Patterns are sourced from `temper_ai/shared/utils/secret_patterns.py` (single source of truth):

| Pattern | Type | Severity |
|---|---|---|
| `aws_access_key` | Specific | HIGH |
| `aws_secret_key` | Specific | CRITICAL |
| `github_token` | Specific | HIGH |
| `google_api_key` | Specific | MEDIUM-HIGH |
| `jwt_token` | Specific | HIGH |
| `private_key` | Specific | CRITICAL |
| `slack_token` | Specific | HIGH |
| `stripe_key` | Specific | HIGH |
| `connection_string` | Specific | HIGH |
| `generic_api_key` | Generic | HIGH (entropy-filtered) |
| `generic_secret` | Generic | HIGH (entropy-filtered) |

#### Detection Flow

```mermaid
flowchart TD
    A["_validate_impl(action, context)"]
    B["Extract content from action\n(content / config / data fields)"]
    C{"content empty\nor path excluded?"}
    D["_scan_for_secrets(content, file_path, context)"]
    E["pattern_matcher.find_matches(content)\n(PatternMatcher iterates enabled patterns)"]
    F["is_test_secret(match.value)?\n(TestSecretFilter)"]
    G["Calculate Shannon entropy\n(EntropyAnalyzer.calculate)"]
    H{"pattern is generic\n(api_key / secret)?"}
    I{"entropy < entropy_threshold_generic\n(default 3.5)?"}
    J["_create_secret_violation()\n- redacted preview: [AWS_ACCESS_KEY:20_chars]\n- HMAC hash for dedup\n- sanitized context"]
    K["Determine severity\n(private_key/aws_secret -> CRITICAL)\n(github_token/stripe -> HIGH)\n(entropy > 4.5 -> HIGH)\n(else -> MEDIUM)"]

    A --> B --> C
    C -- "no" --> D --> E
    E --> F
    F -- "yes (skip)" --> E
    F -- "no" --> G --> H
    H -- "yes" --> I
    I -- "yes (skip)" --> E
    I -- "no" --> J
    H -- "no" --> J
    J --> K
```

#### Shannon Entropy

```python
# temper_ai/safety/entropy_analyzer.py:25
def calculate(text: str) -> float:
    # H(X) = -Σ p(x) * log2(p(x))
    # Returns 0.0 to 8.0 bits/character
```

Typical entropy ranges:
- `0.0–2.0`: Very low (repetitive: "aaaa")
- `2.0–3.5`: Low (English prose, templates)
- `3.5–4.5`: Medium (mixed content) — below generic threshold
- `4.5–8.0`: High (cryptographic secrets, base64, random data)

Default thresholds:
- `entropy_threshold`: 4.5 (HIGH severity trigger for any pattern)
- `entropy_threshold_generic`: 3.5 (filter for `generic_api_key`, `generic_secret`)

#### Test Secret Allowlisting

The `TestSecretFilter` allows test/example secrets through to avoid false positives in test suites. It checks for keywords like `example`, `test`, `fake`, `dummy`, `placeholder`, `your_key_here` in the matched text.

#### Session-Scoped HMAC Hashing

Each `SecretDetectionPolicy` instance generates a random 32-byte session key (`os.urandom(32)`). Detected secret values are hashed with HMAC-SHA256 (key=session key) for deduplication IDs. This allows tracking "same secret detected again" without storing the actual secret value. The session key is ephemeral — it does not survive process restarts.

### 9.3 BlastRadiusPolicy

**Location:** `temper_ai/safety/blast_radius.py:41`
**Priority:** 90

Limits the scope of a single operation to prevent widespread damage from a runaway or malicious agent.

#### Checks

| Check | Action Field | Default Limit | Severity |
|---|---|---|---|
| File count | `action["files"]` (list) | 10 files | HIGH |
| Lines per file | `action["lines_changed"]` (dict: path→count) | 500 lines | HIGH |
| Total lines | `action["total_lines"]` (int) | 2000 lines | HIGH |
| Entities affected | `action["entities"]` (list) | 100 entities | CRITICAL |
| Forbidden patterns in content | `action["content"]` (str) | configurable | CRITICAL |

Note that exceeding `max_entities_affected` produces a CRITICAL violation (not HIGH), because affecting hundreds of users/resources simultaneously is considered the most dangerous blast radius scenario.

### 9.4 FileAccessPolicy

**Location:** `temper_ai/safety/file_access.py`

Whitelist-based file path access control. Checks `action["path"]` or `action["file_path"]` against:
- Allowed directories (whitelist)
- Forbidden patterns (e.g., `/etc/`, `/sys/`, `*.key`, `*.pem`)
- Path traversal detection (`../` sequences)

### 9.5 WindowRateLimitPolicy

**Location:** `temper_ai/safety/rate_limiter.py:56`
**Priority:** 150 (RATE_LIMIT_PRIORITY constant)

Sliding window rate limiter tracking operation timestamps per `(operation, entity)` key.

#### Default Limits

| Operation | Per Second | Per Minute | Per Hour |
|---|---|---|---|
| `llm_call` | — | 100 | 5000 |
| `tool_call` | — | 60 | — |
| `file_operation` | — | 30 | — |
| `api_call` | 20 | 1000 | — |
| `database_query` | 50 | 2000 | — |

#### Entity Key Normalization

Entity IDs are normalized before tracking to prevent bypass attacks:
```python
raw = context.get("agent_id") or context.get("user_id") or "global"
normalized = unicodedata.normalize("NFKC", str(raw)).lower().strip()
```
This prevents case variation, Unicode composition, and whitespace bypass attempts.

#### Severity Escalation

```python
overage_ratio = current_count / max_count
if overage_ratio > 2:   severity = CRITICAL
elif overage_ratio >= 1: severity = HIGH
else:                    severity = MEDIUM
```

### 9.6 TokenBucketRateLimitPolicy

**Location:** `temper_ai/safety/policies/rate_limit_policy.py:55`
**Priority:** 150

Token bucket implementation with per-agent and global limits. Uses `TokenBucketManager` and `TokenBucket` classes.

#### Token Bucket Algorithm

**Location:** `temper_ai/safety/token_bucket.py:140`

```
State: (tokens: float, last_refill: float)

consume(n):
  lock()
  _refill()                  # add tokens based on elapsed time
  if tokens >= n:
    tokens -= n
    return True              # allowed
  return False               # rate limited

_refill():                   # @requires_lock enforced
  elapsed = now - last_refill
  if elapsed >= refill_period:
    tokens = min(max_tokens, tokens + elapsed/refill_period * refill_rate)
    last_refill = now
```

The `@requires_lock` decorator enforces that `_refill()` is only called with `self.lock` held. It attempts a non-blocking acquire — if it succeeds (lock was free), it raises `RuntimeError` immediately.

#### TokenBucketManager — LRU Storage

```python
class TokenBucketManager:
    buckets: OrderedDict[tuple[str, str], TokenBucket]  # (entity_id, limit_type)
    limits:  dict[str, RateLimit]
    max_buckets: int = 10000  # LRU eviction threshold
```

`get_bucket(entity_id, limit_type)`:
1. If key exists: move to end (LRU update), return
2. If key missing: create `TokenBucket(limits[limit_type])`
3. If `len(buckets) > max_buckets`: evict `popitem(last=False)` (LRU entry)

#### Default Token Limits (Per Agent Per Hour)

| Action Type | Max Tokens | Burst Size |
|---|---|---|
| `commit` (git) | 1000 | 2 |
| `deploy` | 2 | 1 |
| `tool_call` | 500 | 1000 |
| `llm_call` | 100 | 5 |
| `api_call` | 500,000 | 100 |
| `total_tool_calls` (global) | 500,000 | 100 |

### 9.7 ResourceLimitPolicy

**Location:** `temper_ai/safety/policies/resource_limit_policy.py:110`
**Priority:** 80

System resource enforcement using `psutil` for real-time monitoring.

#### Default Limits

| Resource | Default | Config Key |
|---|---|---|
| Max file size (read) | 100 MB | `max_file_size_read` |
| Max file size (write) | 10 MB | `max_file_size_write` |
| Max memory per op | 500 MB | `max_memory_per_operation` |
| Max CPU time per op | 30 seconds | `max_cpu_time` |
| Min free disk space | 1 GB | `min_free_disk_space` |

#### Operation Tracking

```python
policy.start_operation(operation_id)  # snapshots memory usage via psutil
# ... execute operation ...
stats = policy.end_operation(operation_id)  # computes deltas
# stats: {cpu_time, memory_delta, cpu_exceeded, memory_exceeded}
```

Disk space checks include a 20% safety margin (`DISK_SPACE_SAFETY_MARGIN = 1.2`) to prevent TOCTOU race conditions.

### 9.8 ConfigChangePolicy

**Location:** `temper_ai/safety/config_change_policy.py`

Validates configuration changes (e.g., modifying agent configs, workflow definitions) to prevent dangerous mutations. Checks for:
- Prohibited config keys (e.g., `eval`, `exec`, `__class__`)
- Structural integrity of config changes
- Authorization (only owner/editor roles may change configs)

### 9.9 PromptInjectionPolicy

**Location:** `temper_ai/safety/prompt_injection_policy.py:19`
**Priority:** 180

Wraps `PromptInjectionDetector` from the security layer as a composable `SafetyPolicy`. Checks these action fields (in order):
1. `action["prompt"]`
2. `action["args"]["prompt"]`
3. `action["args"]["input"]`
4. `action["command"]`
5. `action["content"]`

Maps `SecurityViolation.severity` strings (`"critical"`, `"high"`, `"medium"`, `"low"`) to `ViolationSeverity` enum values.

---

## 10. Approval Workflow

**Location:** `temper_ai/safety/approval.py`

### ApprovalStatus States

```python
class ApprovalStatus(Enum):
    PENDING   = "pending"    # awaiting review
    APPROVED  = "approved"   # has enough approvers
    REJECTED  = "rejected"   # any rejecter voted no
    EXPIRED   = "expired"    # timeout elapsed
    CANCELLED = "cancelled"  # requester cancelled
```

### Approval Workflow Lifecycle

```mermaid
flowchart TD
    A["request_approval(params)"]
    B["Create ApprovalRequest\n(id=uuid, status=PENDING)\nexpires_at = now + timeout"]
    C["Store in _requests dict\n(thread-safe with lock)\nEvict oldest completed if > MAX_REQUESTS"]
    D{"auto_reject_on_timeout?\nAND request.has_expired()?"}
    E["expire_request()\nstatus = EXPIRED\nTrigger on_rejected callbacks"]
    F{"is_pending()?"}
    G{"Approver authorized?\n(check authorized_approvers list)\nSelf-approval blocked!"}
    H["Add to request.approvers\nCheck needs_more_approvals()"]
    I{"enough approvers?"}
    J["status = APPROVED\nTrigger on_approved callbacks"]
    K["reject(request_id, rejecter, reason)"]
    L["One rejection = REJECTED\nTrigger on_rejected callbacks"]
    M["cancel(request_id, reason)\nstatus = CANCELLED"]

    A --> B --> C --> D
    D -- "yes" --> E
    D -- "no" --> F
    F -- "PENDING" --> G
    G -- "authorized" --> H --> I
    I -- "yes" --> J
    I -- "no, wait" --> D
    K --> L
    M --> M
    G -- "unauthorized" --> PermissionError
```

### NoOpApprover

`NoOpApprover` extends `ApprovalWorkflow` and overrides `request_approval()` to immediately set `status = APPROVED`. Used in development environments to bypass human review.

```python
# In development:
approval_workflow = NoOpApprover()
# In production:
approval_workflow = ApprovalWorkflow(
    default_timeout_minutes=30,
    auto_reject_on_timeout=True,
    authorized_approvers=["alice", "bob"],
)
```

### Multi-Approver Support

```python
request = workflow.request_approval(
    action={"tool": "deploy", "environment": "production"},
    reason="Production deployment",
    required_approvers=2,   # needs 2 approvals
    timeout_minutes=60
)
```

### Callbacks

```python
workflow.on_approved(lambda req: notify_slack(f"Request {req.id} approved"))
workflow.on_rejected(lambda req: notify_slack(f"Request {req.id} rejected: {req.decision_reason}"))
```

### Thread Safety

All state modifications acquire `self._lock` (threading.Lock). The internal `_requests` dict is only accessed under this lock.

### Memory Management

The `MAX_REQUESTS = 10000` cap evicts the oldest completed (non-PENDING) requests when exceeded. Active pending requests are never evicted by the overflow logic.

---

## 11. Circuit Breaker System

**Canonical Location:** `temper_ai/shared/core/circuit_breaker.py:212`
**Safety Facade:** `temper_ai/safety/circuit_breaker.py` (shim + SafetyGate)

### Circuit Breaker State Machine

```mermaid
stateDiagram-v2
    [*] --> CLOSED : Initialize
    CLOSED --> CLOSED : success (reset failure_count=0)
    CLOSED --> OPEN : failure_count >= failure_threshold\n(default: 5 failures)
    OPEN --> HALF_OPEN : timeout elapsed\n(default: 60 seconds)
    OPEN --> OPEN : call rejected (rejected_calls++)
    HALF_OPEN --> CLOSED : success_count >= success_threshold\n(default: 2 successes)
    HALF_OPEN --> OPEN : any failure
```

### CircuitBreaker Configuration

```python
CircuitBreaker(
    name="api_calls",
    failure_threshold=5,    # failures before OPEN (1-1000)
    timeout_seconds=60,     # seconds before HALF_OPEN attempt (1-86400)
    success_threshold=2,    # successes in HALF_OPEN to return to CLOSED (1-100)
    storage=None,           # optional StateStorage for persistence
    observability_callback=None,
)
```

### Key Methods

| Method | Description |
|---|---|
| `call(func, *args, **kwargs)` | Execute function through breaker; raises `CircuitBreakerError` if OPEN |
| `async_call(func, *args, **kwargs)` | Async variant |
| `with breaker():` | Context manager usage |
| `record_success()` | Manually record a success |
| `record_failure(error)` | Manually record a failure |
| `can_execute()` | True if state != OPEN |
| `state` (property) | Auto-transitions OPEN→HALF_OPEN on timeout |
| `reset()` | Force back to CLOSED |
| `force_open()` | Manually open the breaker |
| `get_metrics()` | Returns `CircuitBreakerMetrics` |

### Auto-Transition on Timeout

The `state` property checks the elapsed time since the last failure when the state is OPEN. If `now - last_failure_time >= timeout_seconds`, it automatically transitions to HALF_OPEN. This means no background thread is needed — transitions happen lazily on the next access.

### HALF_OPEN Semaphore

A `threading.Semaphore(1)` ensures only one test request passes through during HALF_OPEN state. This prevents a burst of requests from all simultaneously discovering the service is healthy.

### CircuitBreakerMetrics

```python
@dataclass
class CircuitBreakerMetrics:
    total_calls:             int
    successful_calls:        int
    failed_calls:            int
    rejected_calls:          int     # calls blocked while OPEN
    state_changes:           int
    last_failure_time:       datetime | None
    last_state_change_time:  datetime | None

    def success_rate(self) -> float: ...  # 0.0 to 1.0
    def failure_rate(self) -> float: ...  # 1.0 - success_rate
    def to_dict(self) -> dict: ...
```

### SafetyGate

`SafetyGate` combines a `CircuitBreaker` with a `PolicyComposer` into a single execution gate:

```python
gate = SafetyGate(
    name="file_operations",
    circuit_breaker=CircuitBreaker("file_ops"),
    policy_composer=PolicyComposer([FileAccessPolicy()])
)

# Declarative check
if gate.can_pass(action, context):
    execute_action()

# Validated check with reasons
can_pass, reasons = gate.validate(action, context)

# Context manager (raises SafetyGateBlocked)
with gate(action, context):
    execute_action()
```

`can_pass()` returns False if: gate is manually blocked, circuit breaker is OPEN, or policy composer reports blocking violations.

### Deprecated Safety Shim

`temper_ai/safety/circuit_breaker.py` re-exports `CircuitBreaker`, `CircuitBreakerError`, etc. from the canonical `temper_ai.shared.core.circuit_breaker` with deprecation warnings. Callers should import directly from `temper_ai.shared.core.circuit_breaker`.

### CircuitBreakerManager

Provides lifecycle management for multiple circuit breakers and gates:

```python
manager = CircuitBreakerManager()
breaker = manager.create_breaker("database", failure_threshold=5, timeout_seconds=60)
gate = manager.create_gate("db_gate", breaker_name="database", policy_composer=composer)

manager.get_all_metrics()  # dict of name -> metrics
manager.reset_all()        # reset all breakers to CLOSED
```

---

## 12. Rollback System

**Location:** `temper_ai/safety/rollback.py`

The rollback system captures state before high-risk actions and reverts if they fail or are rejected. It integrates with the approval workflow and the `ToolExecutor`'s auto-rollback feature.

### Rollback Data Types

These are defined in `temper_ai/observability/rollback_types.py` (canonical) and re-exported from `safety/rollback.py`:

```python
class RollbackStatus(Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    PARTIAL     = "partial"    # some items reverted, some failed
    FAILED      = "failed"
    CANCELLED   = "cancelled"

@dataclass
class RollbackSnapshot:
    id:              str           # uuid
    action:          dict          # the action that was snapshotted
    context:         dict          # execution context
    file_snapshots:  dict[str, str]  # path -> file contents
    state_snapshots: dict[str, Any]  # arbitrary state
    metadata:        dict[str, Any]
    created_at:      datetime

@dataclass
class RollbackResult:
    success:        bool
    snapshot_id:    str
    status:         RollbackStatus
    reverted_items: list[str]     # successfully reverted
    failed_items:   list[str]     # failed to revert
    errors:         list[str]     # error messages
    metadata:       dict[str, Any]
    completed_at:   datetime | None
```

### Rollback Strategies

```mermaid
classDiagram
    class RollbackStrategy {
        <<abstract>>
        +name: str
        +create_snapshot(action, context) RollbackSnapshot
        +execute_rollback(snapshot) RollbackResult
        +validate_rollback(snapshot) tuple[bool, list[str]]
    }
    RollbackStrategy <|-- FileRollbackStrategy
    RollbackStrategy <|-- StateRollbackStrategy
    RollbackStrategy <|-- CompositeRollbackStrategy

    class FileRollbackStrategy {
        Captures file contents before modification
        Atomically restores on rollback
        TOCTOU protection with double-validation
    }
    class StateRollbackStrategy {
        Captures arbitrary in-memory state
        Requires state_getter callback
    }
    class CompositeRollbackStrategy {
        Composes multiple strategies
        Aggregates results across all
    }
```

### FileRollbackStrategy — Security Details

The `FileRollbackStrategy` is the default strategy used by `RollbackManager`. It has multiple layers of security validation:

1. **Path validation at snapshot time** — `validate_rollback_path(file_path)` before reading
2. **Path validation at restore time** — re-validated before writing
3. **TOCTOU protection** — path re-validated immediately before each I/O operation
4. **Symlink detection** — symlinks in path or any parent directory are rejected
5. **Dangerous directory check** — `/etc`, `/sys`, `/proc`, `/dev`, `/boot` blocked
6. **Atomic writes** — `tempfile.mkstemp()` + `os.replace()` for safe atomic restoration
7. **Null byte check** — null bytes in paths are rejected (security violation)

```python
def validate_rollback_path(file_path, allowed_directories=None, check_symlinks=True):
    # Default allowed: /tmp, /var/tmp, ~/.cache, cwd, tempfile.gettempdir()
    # Returns (is_valid: bool, error_message: str | None)
```

### Rollback Lifecycle

```mermaid
flowchart TD
    A["Before high-risk action"]
    B["manager.create_snapshot(action, context)"]
    C["Select strategy\n(from action type or strategy_name)"]
    D["strategy.create_snapshot()\nCapture file contents, state"]
    E["Store in _snapshots dict\n(bounded: evict oldest if > max_snapshots)"]
    F["Execute action"]
    G{"Action succeeded?"}
    H["Continue normally"]
    I["manager.execute_rollback(snapshot_id)"]
    J["Select strategy (from snapshot.action.type)"]
    K["strategy.validate_rollback(snapshot)"]
    L["strategy.execute_rollback(snapshot)"]
    M{"All items reverted?"}
    N["status = COMPLETED, success=True"]
    O{"Some reverted?"}
    P["status = PARTIAL, success=False"]
    Q["status = FAILED, success=False"]
    R["Append to _history\n(bounded: evict oldest if > max_history)"]
    S["Trigger on_rollback callbacks"]

    A --> B --> C --> D --> E --> F --> G
    G -- "yes" --> H
    G -- "no" --> I --> J --> K --> L --> M
    M -- "yes" --> N
    M -- "no" --> O
    O -- "partial" --> P
    O -- "none" --> Q
    N --> R --> S
    P --> R
    Q --> R
```

### Dry Run Mode

```python
result = manager.execute_rollback(snapshot_id, dry_run=True)
# Returns mock COMPLETED result with reverted_items=list(snapshot.file_snapshots.keys())
# Does NOT actually modify any files
```

### Auto-Rollback in ToolExecutor

When `ToolExecutor` is created with `enable_auto_rollback=True`, it:
1. Creates a snapshot before executing each tool call
2. On any exception or approval rejection: calls `execute_rollback(snapshot_id)` automatically
3. On success: discards the snapshot (does not rollback)

---

## 13. LLM Security Layer

**Location:** `temper_ai/safety/security/llm_security.py`

This module provides three security components operating at the LLM boundary (input and output):

### PromptInjectionDetector

Detects prompt injection attacks, jailbreaks, and system prompt leakage in LLM input.

#### Detection Categories

| Category | Examples |
|---|---|
| `command_injection` | "ignore all previous instructions", "disregard prior context" |
| `role_manipulation` | "you are now a", "act as a", "pretend you are" |
| `system_prompt_leakage` | "show me your system prompt", "repeat your instructions" |
| `delimiter_injection` | `</system>`, `[/INSTRUCTIONS]`, `System:` |
| `encoding_bypass` | `base64`, `\x41\x42`, "decode and execute" |
| `jailbreak_attempt` | "do anything now", "DAN mode", "developer mode" |

#### Input Length Protection (DoS Prevention)

```python
MAX_INPUT_LENGTH = SIZE_100KB   # 100KB: truncate before pattern matching
MAX_ENTROPY_LENGTH = SIZE_10KB  # 10KB: skip entropy for large inputs
```

Inputs larger than `MAX_INPUT_LENGTH` are truncated before pattern matching (and a HIGH violation is generated for the oversized input itself). Inputs 10KB–100KB skip entropy analysis — this is a documented tradeoff: entropy on large Unicode inputs can exhaust memory.

#### Entropy Threshold

```python
ENTROPY_THRESHOLD_RANDOM = 5.5  # >5.5 bits/char = likely obfuscated
```

English prose: ~4.0–4.5. Technical text: ~4.5–5.0. Encoded/random: >5.5.

### OutputSanitizer

Detects and redacts secrets and dangerous patterns from LLM output:
1. Detect all secret matches (centralized patterns from `shared/utils/secret_patterns.py`)
2. Collect all match spans as `(start, end, replacement)` tuples
3. **Deduplicate overlapping spans** using longest-match-first (prevents partial secret leakage)
4. Apply all replacements in reverse position order (to maintain offsets)
5. Detect dangerous patterns in the sanitized output (no redaction, just detection)

```python
sanitized, violations = sanitizer.sanitize(llm_output)
# violations may include: secret_leakage, dangerous_content
```

### LLMSecurityRateLimiter

Multi-tier sliding window rate limiter for LLM API calls:
- Per minute, per hour, and burst window limits
- Entity ID normalization (NFKC + lowercase + strip + zero-width char removal)
- Atomic check-and-record (TOCTOU fix: both check AND record inside the same lock acquisition)

```python
allowed, reason = limiter.check_and_record_rate_limit(entity_id)
```

### Global Singletons

```python
# Double-checked locking pattern for thread-safe singleton initialization:
get_prompt_detector()   -> PromptInjectionDetector
get_output_sanitizer()  -> OutputSanitizer
get_rate_limiter()      -> LLMSecurityRateLimiter
reset_security_components()  # for tests
```

---

## 14. Autonomy Management System

**Location:** `temper_ai/safety/autonomy/`

The autonomy system implements progressive autonomy — agents start fully supervised and earn greater operational independence based on their demonstrated merit scores. All state is persisted to the database for audit and recovery.

### 14.1 AutonomyLevel and AutonomyConfig

**Location:** `temper_ai/safety/autonomy/schemas.py`

```python
class AutonomyLevel(IntEnum):
    SUPERVISED   = 0   # All actions require approval
    SPOT_CHECKED = 1   # 10% of MEDIUM actions sampled for review
    RISK_GATED   = 2   # Only HIGH/CRITICAL require approval
    AUTONOMOUS   = 3   # Only CRITICAL requires approval
    STRATEGIC    = 4   # Only CRITICAL requires approval (same as AUTONOMOUS)
```

```python
class AutonomyConfig(BaseModel):
    enabled:         bool           = False        # disabled by default (backward compat)
    level:           AutonomyLevel  = SUPERVISED
    allow_escalation: bool          = True
    max_level:       AutonomyLevel  = RISK_GATED   # hard cap on auto-escalation
    shadow_mode:     bool           = True
    budget_usd:      float | None   = None
    spot_check_rate: float          = 0.10         # 10% spot-check rate at SPOT_CHECKED
```

### Progressive Autonomy Levels

```mermaid
flowchart LR
    subgraph "Increasing Trust"
        L0["SUPERVISED\nlevel=0\nAll actions need approval\n\nCRITICAL: 2 approvers\nHIGH: 1 approver\nMEDIUM: 1 approver\nLOW: auto"]
        L1["SPOT_CHECKED\nlevel=1\nMost actions auto-approved\n\nCRITICAL: 2 approvers\nHIGH: 1 approver\nMEDIUM: 10% sampled\nLOW: auto"]
        L2["RISK_GATED\nlevel=2\nOnly risky actions reviewed\n\nCRITICAL: 2 approvers\nHIGH: 1 approver\nMEDIUM: auto\nLOW: auto"]
        L3["AUTONOMOUS\nlevel=3\nHigh confidence, self-managing\n\nCRITICAL: 2 approvers\nHIGH: auto\nMEDIUM: auto\nLOW: auto"]
        L4["STRATEGIC\nlevel=4\nFully autonomous strategic ops\n\nCRITICAL: 2 approvers\nAll else: auto"]
    end
    L0 -->|"merit earned"| L1 -->|"merit earned"| L2 -->|"merit earned"| L3 -->|"merit earned"| L4
    L4 -->|"failure detected"| L3
    L3 -->|"failure detected"| L2
```

### 14.2 AutonomyManager — State Machine

**Location:** `temper_ai/safety/autonomy/manager.py:27`

The `AutonomyManager` is the central state machine controlling level transitions.

```python
AutonomyManager(
    store=AutonomyStore(session),
    trust_evaluator=TrustEvaluator(),
    max_level=AutonomyLevel.RISK_GATED,  # hard cap for auto-escalation
)
```

#### State Persistence

State is stored in the `autonomy_states` table:
```python
class AutonomyState(SQLModel, table=True):
    id:                str
    agent_name:        str
    domain:            str       # domain of expertise (e.g., "coding", "research")
    current_level:     int
    shadow_level:      int | None  # level being shadow-tested
    shadow_runs:       int
    shadow_agreements: int
    last_escalation:   datetime | None
    last_de_escalation: datetime | None
```

#### Transition Logic

```mermaid
flowchart TD
    A["evaluate_and_transition(session, agent_name, domain)"]
    B["Lock (_lock: threading.Lock)"]
    C["get_level(agent_name, domain)\n(SUPERVISED if no state exists)"]
    D["TrustEvaluator.evaluate()\nLoad AgentMeritScore\nCheck failure rate vs success rate"]
    E{"needs_de_escalation?"}
    F["_de_escalate()\n1. Check de-escalation cooldown (1 hour)\n2. new_level = max(0, current-1)\n3. Save AutonomyState\n4. Save AutonomyTransition record\n5. Log transition"]
    G{"eligible_for_escalation?"}
    H["_escalate()\n1. Check max_level cap\n2. Check escalation cooldown (24 hours)\n3. new_level = min(current+1, STRATEGIC)\n4. Save AutonomyState\n5. Save AutonomyTransition record\n6. Log transition"]
    I["Return None (no transition)"]

    A --> B --> C --> D --> E
    E -- "yes" --> F
    E -- "no" --> G
    G -- "yes" --> H
    G -- "no" --> I
```

#### Cooldown Guards

- **Escalation cooldown:** 24 hours between escalations (`ESCALATION_COOLDOWN_HOURS`)
- **De-escalation cooldown:** 1 hour between de-escalations (`DE_ESCALATION_COOLDOWN_HOURS`)

De-escalation cooldown is shorter because safety de-escalation is more urgent. These guards prevent thrashing between levels when metrics fluctuate.

#### Manual Override

```python
manager.escalate(agent_name, domain, reason="approved by CTO")
manager.de_escalate(agent_name, domain, reason="incident detected")
manager.force_level(agent_name, domain, AutonomyLevel.SUPERVISED, reason="emergency")
```

`force_level()` bypasses cooldown — used by `EmergencyStopController`.

### 14.3 TrustEvaluator

**Location:** `temper_ai/safety/autonomy/trust_evaluator.py:28`

```python
TrustEvaluator(
    min_decisions=50,        # minimum decisions before escalation considered
    escalation_rate=0.90,    # 90% success rate needed to escalate
    de_escalation_rate=0.30, # 30%+ failure rate triggers de-escalation
)
```

#### Evaluation Algorithm

```mermaid
flowchart TD
    A["evaluate(session, agent_name, domain, current_level)"]
    B["_load_merit_score(session)\nSELECT AgentMeritScore WHERE agent_name AND domain"]
    C{"merit is None?"}
    D["TrustEvaluation(evidence={'reason': 'no_merit_record'})"]
    E["_build_evidence(merit)\n{total_decisions, successful, failed, success_rate,\naverage_confidence, expertise_score}"]
    F["_compute_failure_rate(merit)\n= failed_decisions / total_decisions"]
    G{"failure_rate >= de_escalation_rate (30%)?\nAND current_level > SUPERVISED?"}
    H["needs_de_escalation=True\nrecommended_level = max(0, current-1)"]
    I{"total_decisions < min_decisions (50)?"}
    J["Insufficient data — no escalation"]
    K{"success_rate >= escalation_rate (90%)?"}
    L["eligible_for_escalation=True\nrecommended_level = min(current+1, STRATEGIC)"]
    M["No change recommended"]

    A --> B --> C
    C -- "yes" --> D
    C -- "no" --> E --> F --> G
    G -- "yes" --> H
    G -- "no" --> I
    I -- "yes (insufficient)" --> J
    I -- "no" --> K
    K -- "yes" --> L
    K -- "no" --> M
```

**De-escalation is checked before escalation** — this is intentional. Safety de-escalation always takes priority over rewarding good performance.

### 14.4 BudgetEnforcer

**Location:** `temper_ai/safety/autonomy/budget_enforcer.py:53`

Tracks and enforces USD cost budgets for autonomous agent operations.

```python
BudgetEnforcer(
    store=AutonomyStore(session),
    pricing_path="configs/model_pricing.yaml",  # model -> {input_price, output_price}
    default_budget=10.0,                        # $10 default per scope
)
```

#### Budget State

Stored in the `budget_records` table:
```python
class BudgetRecord(SQLModel, table=True):
    scope:      str    # agent name or workflow id
    period:     str    # "unlimited" or "daily", "monthly"
    budget_usd: float
    spent_usd:  float
    action_count: int
    status:     str    # "active", "warning", "exhausted"
```

#### Budget Check Flow

```mermaid
flowchart TD
    A["check_budget(scope, estimated_cost)"]
    B["_get_or_create_budget(scope)\n(creates $10 default if none exists)"]
    C["remaining = budget_usd - spent_usd"]
    D{"remaining <= 0?"}
    E["BudgetCheckResult(allowed=False, status=EXHAUSTED)"]
    F{"estimated_cost > remaining?"}
    G["BudgetCheckResult(allowed=False, status=WARNING)"]
    H["utilization = spent_usd / budget_usd"]
    I{"utilization >= 80% (BUDGET_WARNING_THRESHOLD)?"}
    J["BudgetCheckResult(allowed=True, status=WARNING)"]
    K["BudgetCheckResult(allowed=True, status=ACTIVE)"]

    A --> B --> C --> D
    D -- "yes" --> E
    D -- "no" --> F
    F -- "yes" --> G
    F -- "no" --> H --> I
    I -- "yes" --> J
    I -- "no" --> K
```

#### Cost Estimation

```python
cost = enforcer.estimate_action_cost(
    model="claude-opus-4-5",
    estimated_tokens=5000
)
# = (estimated_tokens / 1_000_000) * output_price_per_million
```

Pricing is loaded from `configs/model_pricing.yaml`.

### 14.5 EmergencyStopController

**Location:** `temper_ai/safety/autonomy/emergency_stop.py:35`

Provides O(1) cross-thread signaling to immediately halt all autonomous agent operations.

```python
# Module-level state (not per-instance)
_stop_event = threading.Event()   # O(1) is_set() check
_stop_lock = threading.Lock()
_active_event_id: str | None = None
```

```python
controller = EmergencyStopController(store=AutonomyStore(...))

# Activate (blocks all agents immediately)
event = controller.activate(
    triggered_by="security-team",
    reason="Detected unauthorized data access",
    agents_halted=["agent-1", "agent-2"]
)

# Check in hot path (O(1))
controller.is_active()            # True/False
controller.check_or_raise()       # raises EmergencyStopError if active

# Deactivate
controller.deactivate("Incident resolved")
```

The `EmergencyStop` check is the **first check** in `ActionPolicyEngine.validate_action()` — before any policy lookup. This ensures that even a cached policy result cannot bypass an active emergency stop.

All emergency stop events are persisted to `emergency_stop_events` table for audit trail, including `resolved_at` timestamp when deactivated.

### 14.6 ApprovalRouter — Severity x Level Matrix

**Location:** `temper_ai/safety/autonomy/approval_router.py:27`

The `ApprovalRouter` implements the decision matrix for approval requirements based on the maximum violation severity and current autonomy level.

#### Decision Matrix

| Severity \ Level | SUPERVISED | SPOT_CHECKED | RISK_GATED | AUTONOMOUS | STRATEGIC |
|---|---|---|---|---|---|
| CRITICAL | 2 approvers | 2 approvers | 2 approvers | 2 approvers | 2 approvers |
| HIGH | 1 approver | 1 approver | 1 approver | **auto** | **auto** |
| MEDIUM | 1 approver | **10% sampled** | **auto** | auto | auto |
| LOW/None | **auto** | auto | auto | auto | auto |

CRITICAL violations always require 2 approvers regardless of autonomy level. This is a hard safety invariant.

```python
router = ApprovalRouter(spot_check_rate=0.10)
decision = router.route_action(
    agent_name="coder-1",
    domain="coding",
    violations=[SafetyViolation(severity=ViolationSeverity.MEDIUM, ...)],
    autonomy_level=AutonomyLevel.SPOT_CHECKED,
)
# At SPOT_CHECKED with MEDIUM: 10% chance requires_approval=True
```

#### Spot Check

```python
def _spot_check_decision(self) -> ApprovalDecision:
    if random.random() < self._spot_check_rate:  # non-security random (sampling)
        return ApprovalDecision(
            requires_approval=True, required_approvers=1,
            is_sampled=True, reason="Spot-check sample (10% rate)"
        )
    return ApprovalDecision(reason="MEDIUM auto-approved (not sampled)")
```

### 14.7 ShadowMode — Promotion Validation

**Location:** `temper_ai/safety/autonomy/shadow_mode.py:35`

Shadow mode validates whether an agent is ready for promotion by running a parallel simulation at the proposed next level.

```mermaid
flowchart TD
    A["validate_shadow(agent_name, domain, violations,\ncurrent_requires_approval, proposed_level, router)"]
    B["Shadow simulation:\nrouter.route_action(violations, proposed_level)\nshadow_requires_approval = decision.requires_approval"]
    C["agrees = current_requires_approval == shadow_requires_approval"]
    D["Load/create AutonomyState"]
    E["state.shadow_runs += 1\nif agrees: state.shadow_agreements += 1"]
    F["agreement_rate = shadow_agreements / shadow_runs"]
    G["Return ShadowResult(agrees, current, shadow, runs, agreements, rate)"]

    A --> B --> C --> D --> E --> F --> G
```

#### Promotion Readiness Check

```python
shadow_mode.check_promotion_ready(agent_name, domain)
# Returns True if:
#   state.shadow_runs >= SHADOW_MIN_RUNS (default: 20 runs)
#   AND agreement_rate >= SHADOW_AGREEMENT_THRESHOLD (default: 0.80 = 80%)
```

Shadow agreements represent cases where the agent would have made the same decision at the next level. High agreement means the agent is already behaving as if it were at the higher level.

### 14.8 MeritSafetyBridge

**Location:** `temper_ai/safety/autonomy/merit_bridge.py:11`

Weakly couples the merit score system to the autonomy evaluation system. Called after each decision is recorded in the merit tracking system.

```python
bridge = MeritSafetyBridge(
    autonomy_manager=manager,
    evaluation_interval=10,  # evaluate every 10 decisions
)

# Called after each merit update
bridge.on_decision_recorded(session, agent_name, domain, outcome="success")
```

Rate-limited to evaluate every N decisions (default: 10) to avoid database overhead on every single decision. When evaluation triggers a transition, it is logged at INFO level.

### 14.9 AutonomyPolicy — Safety Policy Integration

**Location:** `temper_ai/safety/autonomy/policy.py:19`

`AutonomyPolicy` is the `SafetyPolicy` subclass that integrates all autonomy components into the standard policy chain. When autonomy is disabled (the default), it returns `valid=True` with no violations for backward compatibility.

```python
# Wire autonomy components into the policy
policy = AutonomyPolicy(config={})
policy.configure(
    manager=autonomy_manager,
    budget_enforcer=budget_enforcer,
    approval_router=approval_router,
    emergency_stop=emergency_stop,
)
```

Validation flow:
1. Check if `context["metadata"]["autonomy_config"].enabled` is True
2. If not: return `valid=True` (no-op)
3. Check emergency stop → CRITICAL violation if active
4. Check budget → HIGH violation if over budget
5. Check approval routing → MEDIUM violation if approval required

---

## 15. Redaction and Secret Utilities

**Location:** `temper_ai/safety/redaction_utils.py`

### create_redacted_preview

```python
create_redacted_preview("AKIAIOSFODNN7EXAMPLE", "aws_access_key")
# Returns: '[AWS_ACCESS_KEY:20_chars]'
```

Shows only the pattern type and character count — never the actual secret value.

### hash_secret

```python
hash_secret("AKIAIOSFODNN7EXAMPLE", session_key: bytes) -> str
# HMAC-SHA256 with session-scoped random key
# Returns first 16 hex chars (64 bits) — enough for deduplication, not for reversal
```

Session-scoped key prevents rainbow table attacks. The 64-bit hash prefix allows tracking "same secret seen again" within a session without storing or reversing the secret.

---

## 16. Stub Policies

**Location:** `temper_ai/safety/stub_policies.py`

Two stub policies exist to suppress "no built-in implementation found" warnings when these names are referenced in safety config YAML:

| Stub | Config Name | Purpose |
|---|---|---|
| `ApprovalWorkflowPolicy` | `approval_workflow_policy` | Real logic is in `ApprovalWorkflow` component |
| `CircuitBreakerPolicy` | `circuit_breaker_policy` | Real logic is in per-provider `CircuitBreaker` |

Both stubs always return `valid=True` with no violations.

---

## 17. Exceptions Hierarchy

**Location:** `temper_ai/safety/exceptions.py`

```
FrameworkException (shared)
└── SafetyViolationException
    ├── BlastRadiusViolation
    ├── ActionPolicyViolation
    ├── RateLimitViolation
    ├── ResourceLimitViolation
    ├── ForbiddenOperationViolation
    └── AccessDeniedViolation

CircuitBreakerError (= CircuitBreakerOpen alias)
├── (raised when circuit is OPEN)

SafetyGateBlocked
└── (raised by SafetyGate context manager)

RollbackSecurityError (SecurityError)
└── (raised on path validation failure in rollback)

EmergencyStopError
└── (raised by EmergencyStopController.check_or_raise())
```

---

## 18. Configuration Reference

### Safety Stack Config (YAML)

```yaml
# configs/safety/action_policies.yaml

# Engine configuration
policy_engine:
  cache_ttl: 60               # seconds (default: TTL_LONG = 60)
  max_cache_size: 1000        # max cached results (default: THRESHOLD_MEDIUM_COUNT)
  enable_caching: true        # enable result cache
  short_circuit_critical: true  # stop on first CRITICAL violation
  log_violations: true        # emit to observability
  fail_open: false            # SECURITY: false = deny when no policies

# Global policies (apply to ALL action types)
global_policies:
  - rate_limit_policy
  - secret_detection_policy

# Action-specific policies
policy_mappings:
  file_write:
    - file_access_policy
    - forbidden_ops_policy
    - blast_radius_policy
    - resource_limit_policy
  file_read:
    - file_access_policy
    - resource_limit_policy
  git_commit:
    - forbidden_ops_policy
    - rate_limit_policy
  llm_call:
    - rate_limit_policy
    - prompt_injection_policy
  tool_call:
    - rate_limit_policy

# Per-policy configuration
policy_config:
  blast_radius_policy:
    max_files_per_operation: 10
    max_lines_per_file: 500
    max_total_lines: 2000
    max_entities_affected: 100
    max_operations_per_minute: 20
    forbidden_patterns: []

  secret_detection_policy:
    enabled_patterns: []  # empty = all 11 patterns enabled
    entropy_threshold: 4.5
    entropy_threshold_generic: 3.5
    excluded_paths: []
    allow_test_secrets: true

  forbidden_ops_policy:
    check_file_writes: true
    check_dangerous_commands: true
    check_injection_patterns: true
    check_security_sensitive: true
    allow_read_only: true
    whitelist_commands: []
    custom_forbidden_patterns: {}

  rate_limit_policy:
    per_agent: true
    cooldown_multiplier: 1.0
    rate_limits:
      commit:
        max_tokens: 1000
        refill_rate: 0.000278  # 1000/3600
        refill_period: 1.0
        burst_size: 2

  resource_limit_policy:
    max_file_size_read: 104857600   # 100MB
    max_file_size_write: 10485760   # 10MB
    max_memory_per_operation: 524288000  # 500MB
    max_cpu_time: 30.0
    min_free_disk_space: 1073741824  # 1GB
    track_memory: true
    track_cpu: true
    track_disk: true

# Approval mode
approval_mode: null  # null = use environment default
                     # "noop" = always auto-approve (dev/testing)

# Environment overrides (deep merged on top of base)
environments:
  production:
    policy_engine:
      fail_open: false
      short_circuit_critical: true
    approval_mode: null  # real approval workflow
  development:
    approval_mode: noop
```

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `TEMPER_SAFETY_ENV` | `"development"` | Environment for config selection |

### AutonomyConfig (per agent YAML)

```yaml
# In agent config:
autonomy:
  enabled: false            # off by default
  level: 0                  # SUPERVISED
  allow_escalation: true
  max_level: 2              # RISK_GATED cap
  shadow_mode: true
  budget_usd: 10.0
  spot_check_rate: 0.10
```

---

## 19. Design Patterns and Decisions

### Policy Priority System

Policies are executed in descending priority order. Priority values:

| Priority | Policy |
|---|---|
| 200 | `ForbiddenOperationsPolicy` — P0 security, must run first |
| 180 | `SecretDetectionPolicy`, `PromptInjectionPolicy` — critical security |
| 150 | `TokenBucketRateLimitPolicy`, `WindowRateLimitPolicy` — resource protection |
| 100 | Default (most policies) |
| 90 | `BlastRadiusPolicy` — damage limitation |
| 80 | `ResourceLimitPolicy` — system resource protection |

### Lazy Imports Throughout

The safety package uses extensive lazy imports to prevent circular imports and reduce startup cost:
- `__init__.py` uses `__getattr__` with `_LAZY_IMPORTS` dict
- `factory.py` imports `ToolExecutor` inside `create_safety_stack()` with a comment explaining the reason
- `base.py` imports `SHORT_CIRCUIT_KEY` from `constants.py` rather than other safety modules

### Fail-Closed Default

Every security-sensitive decision in the safety stack defaults to deny:
- `ActionPolicyEngine`: `fail_open=False` means no policies → block
- Policy exceptions → CRITICAL violation → block
- `RollbackManager`: path validation failures → `RollbackSecurityError` raised
- `EmergencyStop`: is_active check is the very first thing in every action validation

### Thread Safety Pattern

All stateful safety components use `threading.Lock()`:
- `PolicyRegistry._lock`: protects policy registration/lookup
- `ApprovalWorkflow._lock`: protects `_requests` dict
- `CircuitBreaker.lock`: protects state transitions (with `Semaphore(1)` for HALF_OPEN)
- `WindowRateLimitPolicy._history_lock`: protects operation history
- `TokenBucketManager.lock`: protects bucket creation/eviction
- `TokenBucket.lock`: protects token consumption/refill

### Composition via Child Policies

`BaseSafetyPolicy` supports a tree structure: a parent policy can have child policies attached via `add_child_policy()`. Children run first (sorted by priority), and a CRITICAL violation from any child short-circuits the entire tree. This enables building hierarchical policy structures.

### Policy Snapshot Cache Invalidation (SA-06)

The APE maintains a hash of all registered policy names. On each call, it compares the current snapshot against the stored one. If they differ (policies were added/removed), the entire validation cache is cleared. This prevents stale cache entries from bypassing newly registered policies.

### No Global Mutable State in Policy Instances

Policy instances are stateless validators — they inspect actions against rules but do not store per-call state inside themselves. Rate limiting state is stored in external `dict` or `OrderedDict` structures (inside the policy but not in the `validate()` method scope).

### Two-Layer Rate Limiting

The framework provides two complementary rate limiting approaches:
1. **Window-based** (`WindowRateLimitPolicy`): sliding timestamp windows, good for per-second/minute/hour checks
2. **Token bucket** (`TokenBucketRateLimitPolicy`): smooth rate with burst allowance, good for sustained limits with burst tolerance

### Security Layer Boundary (interfaces.py Protocols)

`safety/` depends on `security/` only through `Protocol` interfaces defined in `interfaces.py`. The concrete `PromptInjectionDetector` and `OutputSanitizer` classes satisfy these protocols without `safety/` having a hard import on `security/`. The `PromptInjectionPolicy` uses a lazy import (`from temper_ai.safety.security.llm_security import ...` inside `__init__`) for the same reason.

---

## 20. Extension Guide

### Adding a New Policy

1. Create a new file in `temper_ai/safety/` (or a subdirectory)
2. Extend `BaseSafetyPolicy` and implement `_validate_impl()`, `name`, `version`
3. Optionally set a custom `priority` property
4. Register in `_BUILTIN_POLICIES` in `factory.py` or use `register_policy_class()`
5. Add to `safety_config.yaml` under `global_policies` or `policy_mappings`

```python
# Example minimal policy
from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity
from typing import Any

class MyCustomPolicy(BaseSafetyPolicy):

    @property
    def name(self) -> str:
        return "my_custom_policy"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 120  # between rate limit (150) and blast radius (90)

    def _validate_impl(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        # Your validation logic here
        if action.get("forbidden_key"):
            return ValidationResult(
                valid=False,
                violations=[SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.HIGH,
                    message="Forbidden key detected",
                    action=str(action),
                    context=context,
                    remediation_hint="Remove the forbidden_key from action",
                )],
                policy_name=self.name,
            )
        return ValidationResult(valid=True, policy_name=self.name)
```

Then register:
```python
from temper_ai.safety.factory import register_policy_class
register_policy_class("my_custom_policy", MyCustomPolicy)
```

Or add to `_BUILTIN_POLICIES` in `factory.py`.

### Adding a New Rollback Strategy

1. Extend `RollbackStrategy` and implement `name`, `create_snapshot()`, `execute_rollback()`
2. Register with the `RollbackManager`:

```python
class DatabaseRollbackStrategy(RollbackStrategy):
    @property
    def name(self) -> str:
        return "database_rollback"

    def create_snapshot(self, action, context) -> RollbackSnapshot:
        snapshot = RollbackSnapshot(action=action, context=context)
        snapshot.state_snapshots["db_state"] = capture_db_state()
        return snapshot

    def execute_rollback(self, snapshot) -> RollbackResult:
        db_state = snapshot.state_snapshots.get("db_state")
        restore_db_state(db_state)
        return RollbackResult(success=True, ...)

manager.register_strategy("database", DatabaseRollbackStrategy())
```

### Adding a Custom Approval Strategy

Extend `ApprovalWorkflow` and override `request_approval()`:

```python
class SlackApprovalWorkflow(ApprovalWorkflow):
    def request_approval(self, params=None, **kwargs) -> ApprovalRequest:
        request = super().request_approval(params=params, **kwargs)
        post_to_slack(f"Approval needed: {request.reason}")
        return request
```

### Registering a Circuit Breaker for a Service

```python
from temper_ai.safety.circuit_breaker import CircuitBreakerManager

manager = CircuitBreakerManager()
breaker = manager.create_breaker(
    name="external_api",
    failure_threshold=3,
    timeout_seconds=30,
    success_threshold=2,
)

# Use in service calls
try:
    with breaker():
        result = external_api.call(...)
except CircuitBreakerError:
    # Circuit is open, use fallback
    result = get_cached_result()
```

### Extending the Autonomy System

To integrate custom merit scoring:

1. Record decisions via `AgentMeritScore` in `temper_ai/storage/database/models.py`
2. Trigger evaluation via `MeritSafetyBridge.on_decision_recorded()`
3. The bridge will call `AutonomyManager.evaluate_and_transition()` every N decisions

---

## 21. Security Properties

### Defense in Depth

No single policy failure can compromise the system:
- Policy exceptions produce CRITICAL violations (deny-by-default)
- Emergency stop bypasses all policy caching
- Rollback validates paths at both snapshot and restore time
- Rate limiting normalizes entity IDs to prevent Unicode bypass

### Fail-Closed Defaults

| Scenario | Behavior |
|---|---|
| No policies registered for action type | DENY (fail_open=False by default) |
| Policy raises exception | CRITICAL violation → DENY |
| Path validation fails in rollback | RollbackSecurityError raised |
| Unknown approval mode | Treated as real approval workflow |
| EmergencyStop active | ALL actions blocked, no exceptions |

### ReDoS Protection

All regex patterns in the safety stack use bounded quantifiers:
- `.{0,200}` instead of `.*`
- `[a-zA-Z0-9]{20,200}` instead of `[a-zA-Z0-9]+`
- Custom patterns validated with `test_timeout=0.001` at construction

### TOCTOU Protection

The rollback system uses double-validation:
```python
# At snapshot time
is_valid, error = validate_rollback_path(file_path)

# At restore time (before I/O)
recheck_valid, recheck_err = validate_rollback_path(file_path)
```

The `LLMSecurityRateLimiter` uses atomic check-and-record inside a single lock acquisition to prevent TOCTOU race conditions in rate limit checks.

### Symlink Attack Prevention

`validate_rollback_path()` checks for symlinks in both the target path and all parent directories. A symlink anywhere in the path is rejected, preventing symlink-based path traversal attacks.

### Secret Non-Disclosure

Detected secrets are never logged in plaintext. All logging uses:
- `create_redacted_preview()` — `[TYPE:N_chars]` format
- `hash_secret()` — HMAC-SHA256 with ephemeral session key for deduplication IDs
- Action context is sanitized via `sanitize_config_for_display()` before inclusion in violations

### Config Input Validation

`BaseSafetyPolicy.__init__()` validates all config inputs:
- Type enforcement (must be `dict`)
- Max 100 keys (prevents DoS via massive configs)
- Max nesting depth of 4 (prevents stack overflow via deeply nested configs)
- Max string length `MAX_TEXT_LENGTH` per value
- Max 1000 items per list/set/tuple

### Observability Integration

Safety violations are emitted to the observability system via `_log_violations()`. The `DataSanitizer` (from `temper_ai/observability/sanitization.py`) is applied to violation messages before logging to prevent secondary secret exposure through log streams.

---

## File Reference Index

| File | Lines | Purpose |
|---|---|---|
| `safety/__init__.py` | 237 | Lazy-import registry, deprecated aliases |
| `safety/factory.py` | 389 | `create_safety_stack()`, policy instantiation |
| `safety/interfaces.py` | 437 | `SafetyPolicy` ABC, `ValidationResult`, `ViolationSeverity`, LLM protocols |
| `safety/base.py` | 392 | `BaseSafetyPolicy` with composition and short-circuit |
| `safety/action_policy_engine.py` | 611 | `ActionPolicyEngine`, `PolicyExecutionContext`, `EnforcementResult` |
| `safety/_action_policy_helpers.py` | — | Cache, context conversion, violation logging helpers |
| `safety/composition.py` | 372 | `PolicyComposer`, `CompositeValidationResult` |
| `safety/policy_registry.py` | 376 | `PolicyRegistry` with thread-safe routing |
| `safety/approval.py` | 612 | `ApprovalWorkflow`, `ApprovalRequest`, `NoOpApprover` |
| `safety/_approval_helpers.py` | — | Callback triggers, expiry, eviction |
| `safety/blast_radius.py` | 286 | `BlastRadiusPolicy` with 5 blast-radius checks |
| `safety/circuit_breaker.py` | 376 | Shim + `SafetyGate` + `CircuitBreakerManager` |
| `safety/rollback.py` | 961 | `RollbackManager`, 3 strategies, path validation |
| `safety/secret_detection.py` | 294 | `SecretDetectionPolicy` with 11 patterns |
| `safety/entropy_analyzer.py` | 73 | Shannon entropy `H(X) = -Σ p log2(p)` |
| `safety/pattern_matcher.py` | — | `PatternMatcher`, `PatternMatch` dataclass |
| `safety/redaction_utils.py` | 62 | `create_redacted_preview()`, `hash_secret()` |
| `safety/test_secret_filter.py` | — | `TestSecretFilter` for test secret allowlisting |
| `safety/forbidden_operations.py` | 404 | `ForbiddenOperationsPolicy` with 4 pattern categories |
| `safety/_forbidden_ops_helpers.py` | — | Pattern dicts, compile, whitelist, injection check |
| `safety/_forbidden_ops_pattern_config.py` | — | `PatternConfig` dataclass |
| `safety/rate_limiter.py` | 399 | `WindowRateLimitPolicy` (sliding window) |
| `safety/token_bucket.py` | 577 | `TokenBucket`, `TokenBucketManager`, `RateLimit` |
| `safety/policies/rate_limit_policy.py` | 348 | `TokenBucketRateLimitPolicy` |
| `safety/policies/resource_limit_policy.py` | 359 | `ResourceLimitPolicy` using psutil |
| `safety/prompt_injection_policy.py` | 167 | `PromptInjectionPolicy` wrapper |
| `safety/config_change_policy.py` | — | `ConfigChangePolicy` |
| `safety/file_access.py` | — | `FileAccessPolicy` with whitelist |
| `safety/validation.py` | — | `ValidationMixin` with numeric/string/regex validators |
| `safety/service_mixin.py` | — | `SafetyServiceMixin` for service integration |
| `safety/stub_policies.py` | 68 | `ApprovalWorkflowPolicy`, `CircuitBreakerPolicy` stubs |
| `safety/exceptions.py` | — | Exception hierarchy |
| `safety/security/llm_security.py` | 707 | `PromptInjectionDetector`, `OutputSanitizer`, `LLMSecurityRateLimiter` |
| `safety/autonomy/schemas.py` | 35 | `AutonomyLevel`, `AutonomyConfig` |
| `safety/autonomy/models.py` | 86 | SQLModel tables: `AutonomyState`, `AutonomyTransition`, `BudgetRecord`, `EmergencyStopEvent` |
| `safety/autonomy/manager.py` | 292 | `AutonomyManager` state machine |
| `safety/autonomy/trust_evaluator.py` | 137 | `TrustEvaluator` with merit score thresholds |
| `safety/autonomy/budget_enforcer.py` | 209 | `BudgetEnforcer` with USD cost tracking |
| `safety/autonomy/emergency_stop.py` | 134 | `EmergencyStopController` using `threading.Event` |
| `safety/autonomy/approval_router.py` | 115 | `ApprovalRouter` with severity x level matrix |
| `safety/autonomy/shadow_mode.py` | 160 | `ShadowMode` promotion validation |
| `safety/autonomy/merit_bridge.py` | 65 | `MeritSafetyBridge` rate-limited evaluation trigger |
| `safety/autonomy/policy.py` | 159 | `AutonomyPolicy` integrating all autonomy components |
| `safety/autonomy/store.py` | — | `AutonomyStore` DB access layer |
| `safety/autonomy/constants.py` | — | Thresholds: `ESCALATION_COOLDOWN_HOURS=24`, `DE_ESCALATION_COOLDOWN_HOURS=1`, `MIN_DECISIONS_FOR_ESCALATION=50`, `ESCALATION_SUCCESS_RATE=0.90`, `DE_ESCALATION_FAILURE_RATE=0.30`, `SHADOW_MIN_RUNS=20`, `SHADOW_AGREEMENT_THRESHOLD=0.80` |
| `shared/core/circuit_breaker.py` | 502 | `CircuitBreaker` (canonical), `CircuitState`, `CircuitBreakerMetrics` |
