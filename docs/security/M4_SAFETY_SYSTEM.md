# M4 Safety System Architecture

**Status:** Production Ready
**Last Updated:** 2026-01-27
**Milestone:** M4 - Safety & Guardrails

---

## Overview

The M4 Safety System is a comprehensive, multi-layered security framework that validates and enforces safety policies on all agent actions before execution. It provides defense-in-depth through policy composition, priority-based execution, and fail-closed architecture.

### Key Capabilities

- **Pre-execution validation** of all agent actions
- **Policy composition** - multiple policies per action type
- **Priority-based execution** - P0 (critical) → P1 (important) → P2 (optimization)
- **Short-circuit behavior** - stop on CRITICAL violations
- **Performance optimized** - result caching, <10ms overhead
- **Fail-closed architecture** - block on error, never allow
- **Observability integration** - all violations logged
- **Environment-specific** - different rules for dev/staging/prod

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Action                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              ActionPolicyEngine (Orchestrator)               │
│  • Pre-execution validation                                  │
│  • Policy lookup and execution                               │
│  • Result caching and aggregation                            │
│  • Violation logging                                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  PolicyRegistry (Lookup)                     │
│  • Action-type → Policies mapping                            │
│  • Global policies (all actions)                             │
│  • Priority ordering                                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                Safety Policies (Validators)                  │
│                                                               │
│  P0 (CRITICAL - Priority 90-200):                            │
│  ├─ ForbiddenOperationsPolicy   (200: bash file writes, rm) │
│  ├─ FileAccessPolicy             (95: path permissions)      │
│  └─ SecretDetectionPolicy        (95: API keys, passwords)   │
│                                                               │
│  P1 (IMPORTANT - Priority 80-89):                            │
│  ├─ BlastRadiusPolicy            (90: commit size limits)    │
│  ├─ RateLimitPolicy              (85: rate limiting)         │
│  ├─ ResourceLimitPolicy          (80: memory, tokens)        │
│  └─ ApprovalWorkflowPolicy       (80: require approval)      │
│                                                               │
│  P2 (OPTIMIZATION - Priority 50-79):                         │
│  └─ CircuitBreakerPolicy         (50-79: external APIs)      │
└─────────────────────────────────────────────────────────────┘
```

### Execution Flow

1. **Action Submitted** - Agent requests to perform action
2. **Policy Lookup** - Registry returns applicable policies (P0 → P1 → P2)
3. **Cache Check** - Check if result cached (optional, configurable)
4. **Policy Execution** - Execute each policy in priority order
   - **Short-circuit** - Stop on CRITICAL violation (configurable)
   - **Aggregate** - Collect all violations
5. **Decision** - Block if HIGH or CRITICAL violations present
6. **Logging** - Log violations to observability
7. **Result** - Return EnforcementResult (allowed/blocked)

---

## Core Components

### 1. ActionPolicyEngine

**Location:** `temper_ai/safety/action_policy_engine.py`

Central enforcement layer that orchestrates policy validation.

**Key Features:**
- Pre-execution validation for all agent actions
- Async policy execution
- Result caching (60s TTL, configurable)
- Short-circuit on CRITICAL violations
- Exception handling (policy failures → violations)
- Metrics tracking (cache hit rate, validations, violations)

**Configuration:**
```python
from typing import Dict, Any

config: Dict[str, Any] = {
    "cache_ttl": 60,                    # Cache results for 60 seconds
    "max_cache_size": 1000,             # Max cached results
    "enable_caching": True,             # Enable caching
    "short_circuit_critical": True,     # Stop on CRITICAL
    "log_violations": True              # Log to observability
}
```

**Cache TTL Configuration by Environment:**

| Environment | cache_ttl | Rationale |
|-------------|-----------|-----------|
| **Default** | 60s | Balanced performance (code default) |
| **Development** | 30s | Fast iteration - see fresh results quickly |
| **Testing** | 30s | Consistent with development |
| **Staging** | 60s | Production-like performance testing |
| **Production** | 120s | Maximum cache efficiency, reduced validation overhead |

**When to adjust cache_ttl:**
- **Lower (10-30s):** Rapid development, frequent policy changes, debugging
- **Default (60s):** Balanced performance for most use cases
- **Higher (120-300s):** High-throughput production, stable policies, cost optimization

**Note:** Cached results are invalidated on policy configuration changes.

**Performance:**
- Validation overhead: <10ms per action (typical)
- Cache hit rate: >70% (typical)
- Throughput: 1000+ validations/second

### 2. PolicyRegistry

**Location:** `temper_ai/safety/policy_registry.py`

Manages policy registration and lookup by action type.

**Key Features:**
- Action-specific policies (file_write, git_commit, deploy, etc.)
- Global policies (apply to all actions)
- Priority-based ordering (P0 → P1 → P2)
- Dynamic registration/unregistration
- Statistics and metrics

**Example:**
```python
from typing import List
from temper_ai.safety.policy_registry import PolicyRegistry
from temper_ai.safety.file_access import FileAccessPolicy
from temper_ai.safety.circuit_breaker import CircuitBreakerPolicy
from temper_ai.safety.interfaces import SafetyPolicy

registry = PolicyRegistry()

# Register action-specific policy
registry.register_policy(
    FileAccessPolicy(),
    action_types=["file_read", "file_write", "file_delete"]
)

# Register global policy (applies to all actions)
registry.register_policy(CircuitBreakerPolicy())

# Get policies for action
policies: List[SafetyPolicy] = registry.get_policies_for_action("file_write")
# Returns: [P0 policies, P1 policies, P2 policies] in priority order
```

### 3. PolicyComposer

**Location:** `temper_ai/safety/composition.py`

Composes multiple policies for unified validation.

**Key Features:**
- Execute multiple policies in priority order
- Fail-fast mode (short-circuit on first violation)
- Fail-safe mode (evaluate all policies)
- Violation aggregation
- Async execution support

**Example:**
```python
from typing import Dict, Any
from temper_ai.safety.composition import PolicyComposer
from temper_ai.safety.file_access import FileAccessPolicy
from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

composer = PolicyComposer(fail_fast=True, enable_reporting=True)
composer.add_policy(FileAccessPolicy())
composer.add_policy(ForbiddenOperationsPolicy())

result = composer.validate(
    action={"command": "cat > file.txt"},
    context={"agent": "agent-123"}
)

if not result.valid:
    for violation in result.violations:
        print(f"[{violation.severity.name}] {violation.message}")
```

---

## Available Policies

### P0 Policies (CRITICAL - Priority 90-200)

#### ForbiddenOperationsPolicy
**Location:** `temper_ai/safety/forbidden_operations.py`

Blocks dangerous bash operations and forbidden patterns.

**Detects:**
- **File Write Operations** (10 patterns): `cat >`, `echo >`, `sed -i`, `tee`, etc.
- **Dangerous Commands** (11 patterns): `rm -rf`, `dd`, `curl | bash`, fork bombs
- **Command Injection** (4 patterns): semicolon, backticks, subshell injection
- **Security-Sensitive** (3 patterns): passwords in commands, insecure SSH

**Why Critical:** Bash file operations bypass multi-agent file locks, causing data races. Use Write/Edit tools instead.

**Example:**
```python
from typing import Dict, Any
from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

policy = ForbiddenOperationsPolicy()

result = policy.validate(
    action={"command": "cat > file.txt"},
    context={"agent": "coder"}
)
# result.valid == False
# result.violations[0].message == "Use Write() tool instead of 'cat >' for file operations"
```

**Configuration:**
```python
from typing import Dict, Any, List

config: Dict[str, Any] = {
    "check_file_writes": True,          # Detect bash file operations
    "check_dangerous_commands": True,   # Detect dangerous commands
    "check_injection_patterns": True,   # Detect command injection
    "check_security_sensitive": True,   # Detect security issues
    "custom_forbidden_patterns": {},    # Add custom patterns
    "whitelist_commands": []            # Whitelist specific commands
}
```

#### FileAccessPolicy
**Location:** `temper_ai/safety/file_access.py`

Enforces file and directory access restrictions.

**Features:**
- Forbidden paths (read/write/delete)
- Read-only paths (no write/delete)
- System directory protection
- Path traversal prevention

#### SecretDetectionPolicy
**Location:** `temper_ai/safety/secret_detection.py`

Detects secrets (API keys, passwords, tokens) in code and commands.

**Detects:**
- AWS keys, GitHub tokens, API keys
- Passwords and credentials
- Private keys and certificates
- Database connection strings
- JWT tokens

### P1 Policies (IMPORTANT - Priority 80-89)

#### RateLimitPolicy
**Location:** `temper_ai/safety/rate_limiter.py`

Rate limiting for various operations.

**Limits:**
- File writes: 100/minute
- Git commits: 10/hour
- Git pushes: 5/hour
- Deployments: 2/hour
- LLM calls: 1000/hour

#### ResourceLimitPolicy
**Location:** `temper_ai/safety/policies/resource_limit_policy.py`

Resource consumption limits.

**Limits:**
- File size limits
- Memory limits
- Token limits (LLM)
- Concurrent operation limits

#### BlastRadiusPolicy
**Location:** `temper_ai/safety/blast_radius.py`

Limits commit size to reduce blast radius.

**Limits:**
- Max 20 files per commit
- Max 500 lines per file
- Max 2000 total lines per commit

#### ApprovalWorkflowPolicy
**Location:** `temper_ai/safety/approval.py`

Requires approval for sensitive operations.

**Requires Approval:**
- All deployments
- All rollbacks
- Database deletes
- Sensitive file deletes

### P2 Policies (OPTIMIZATION - Priority 50-79)

#### CircuitBreakerPolicy
**Location:** `temper_ai/safety/circuit_breaker.py`

Circuit breaker for external API calls.

**Features:**
- Open after 5 failures
- Try again after 60 seconds
- Close after 2 successes

---

## Policy Priority Levels

### Priority Numbering System

Policies use numeric priorities where **higher values execute first**:
- **P0 (Critical):** Priority 90-200 - Security and data protection
- **P1 (Important):** Priority 80-89 - Resource management and blast radius
- **P2 (Optimization):** Priority 50-79 - Performance and reliability

**Note:** Priority values within each tier can vary to establish fine-grained execution order. For example, ForbiddenOperationsPolicy (200) runs before FileAccessPolicy (95), even though both are P0-level.

### P0 - CRITICAL (Priority 90-200) - NEVER COMPROMISE

**Purpose:** Prevent security breaches, data loss, and system damage.

**Policies:**
- ForbiddenOperationsPolicy (priority: 200)
- FileAccessPolicy (priority: 95)
- SecretDetectionPolicy (priority: 95)
- BlastRadiusPolicy (priority: 90)

**Enforcement:**
- Always enabled
- Short-circuit on violations (stop immediately)
- Cannot be disabled in production

**Examples:**
- Block `rm -rf /`
- Block bash file writes (use Write/Edit tools)
- Block secrets in code/commands
- Block access to forbidden paths
- Prevent widespread file modifications

### P1 - IMPORTANT (Priority 80-89) - Balance Safety & Productivity

**Purpose:** Prevent resource exhaustion, enforce best practices.

**Policies:**
- RateLimitPolicy (priority: 85)
- ResourceLimitPolicy (priority: 80)
- ApprovalWorkflowPolicy (priority: 80)

**Enforcement:**
- Enabled by default
- Can be relaxed in development
- Strict in production

**Examples:**
- Rate limit: 10 commits/hour
- Require approval for deployments
- Limit commit size to 20 files
- Limit file size to 10MB

### P2 - OPTIMIZATION (Priority 50-79) - Can Be Relaxed

**Purpose:** Improve reliability, reduce costs, optimize performance.

**Policies:**
- CircuitBreakerPolicy (priority: 50-79)
- CachingPolicy (future)
- OptimizationPolicy (future)

**Enforcement:**
- Can be disabled if needed
- Flexible configuration
- Focus on improvement, not blocking

**Examples:**
- Circuit breaker for external APIs
- Cache optimization policies
- Performance monitoring policies

---

## Configuration

### Policy-to-Action-Type Mappings

**Location:** `configs/safety/action_policies.yaml`

Maps policies to action types:

```yaml
policy_mappings:
  file_write:
    - file_access_policy          # P0
    - forbidden_ops_policy        # P0
    - secret_detection_policy     # P0
    - resource_limit_policy       # P1
    - rate_limit_policy           # P1

  git_commit:
    - forbidden_ops_policy        # P0
    - secret_detection_policy     # P0
    - file_access_policy          # P0
    - rate_limit_policy           # P1
    - blast_radius_policy         # P1

  deploy:
    - approval_workflow_policy    # P0
    - rate_limit_policy           # P1
    - circuit_breaker_policy      # P1

global_policies:
  - circuit_breaker_policy        # Applies to ALL actions
```

### Environment-Specific Configuration

```yaml
environments:
  development:
    policy_engine:
      cache_ttl: 30
      short_circuit_critical: false  # See all violations

    policy_config:
      approval_workflow_policy:
        require_approval: []     # No approvals in dev

  production:
    policy_engine:
      cache_ttl: 120
      short_circuit_critical: true

    policy_config:
      rate_limit_policy:
        limits:
          deploy: 1/hour        # Stricter in production
```

See [POLICY_CONFIGURATION_GUIDE.md](./POLICY_CONFIGURATION_GUIDE.md) for complete configuration documentation.

---

## Integration

### Pre-Execution Validation (Agent Executor)

```python
from typing import Dict, Any
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext

class AgentExecutor:
    def __init__(self, policy_engine: ActionPolicyEngine, ...) -> None:
        self.policy_engine = policy_engine

    async def execute_action(self, action: Dict[str, Any]) -> Any:
        """Execute action with policy enforcement."""

        # PRE-EXECUTION: Validate with policy engine
        context = PolicyExecutionContext(
            agent_id=self.agent_id,
            workflow_id=self.workflow_id,
            stage_id=self.stage_id,
            action_type=action['type'],
            action_data=action
        )

        result = await self.policy_engine.validate_action(action, context)

        if not result.allowed:
            # Action blocked by safety policy
            raise SafetyViolationError(
                f"Action blocked: {result.violations[0].message}",
                violations=result.violations
            )

        # Execute the action
        return await self._execute_action_impl(action)
```

### Service Initialization

```python
from typing import Dict, Any
from temper_ai.safety.action_policy_engine import ActionPolicyEngine
from temper_ai.safety.policy_registry import PolicyRegistry

# Create policy registry
registry = PolicyRegistry()

# Create policy engine
engine_config: Dict[str, Any] = {}  # Your configuration here
engine = ActionPolicyEngine(registry, config=engine_config)

# Use the engine and registry in your application
# These instances can be stored and reused as needed
```

---

## Observability

### Violation Logging

All violations are logged to the observability system:

```python
from typing import Dict, Any

# Logged for each violation
violation_log: Dict[str, Any] = {
    "agent_id": "agent-123",
    "workflow_id": "wf-456",
    "stage_id": "research",
    "policy_name": "forbidden_operations",
    "severity": "CRITICAL",
    "action_type": "file_write",
    "message": "Use Write() tool instead of 'cat >' for file operations",
    "timestamp": "2026-01-27T10:00:00Z",
    "context": {...}
}
```

### Metrics Tracking

Engine metrics available via `engine.get_metrics()`:

```python
from typing import Dict, Any

metrics: Dict[str, Any] = {
    "validations_performed": 1500,
    "violations_logged": 45,
    "cache_size": 234,
    "cache_hits": 1050,
    "cache_misses": 450,
    "cache_hit_rate": 0.70,      # 70%
    "policies_registered": 12
}
```

### Dashboards (Future)

- Violation trends over time
- Policy effectiveness (violations prevented)
- Cache performance
- Policy execution time
- Top violated policies

---

## Performance

### Benchmarks

- **Validation overhead:** <10ms per action (typical)
- **Throughput:** 1000+ validations/second
- **Cache hit rate:** >70% (typical)
- **Memory usage:** <50MB for 1000 cached results

### Optimization Strategies

1. **Result Caching**
   - Cache validation results (default: 60s, configurable per environment)
   - Cache key: hash(policy, action, agent_id, action_type)
   - LRU eviction when cache exceeds max size
   - See [Cache TTL Configuration](#cache-ttl-configuration-by-environment) for environment-specific values

2. **Short-Circuit Evaluation**
   - Stop on CRITICAL violations (save ~30% CPU)
   - Configurable per environment

3. **Async Execution**
   - Policies execute asynchronously
   - Non-blocking validation

4. **Priority Ordering**
   - P0 policies execute first
   - Catch critical issues early

---

## Failure Modes

### Fail-Closed Architecture

**Principle:** If the safety system fails, block the action (don't allow).

**Examples:**
- Policy execution exception → CRITICAL violation
- Policy engine unavailable → block action
- Configuration error → block action

**Rationale:** Better to be safe than sorry. False negatives (missed violations) are worse than false positives (blocked safe actions).

### Exception Handling

#### Exception Hierarchy

**Module:** `temper_ai.safety.exceptions`

All safety violations can be raised as exceptions for flow control:

```
SafetyViolationException (base)
├── BlastRadiusViolation          (HIGH severity)
├── ActionPolicyViolation         (CRITICAL severity)
├── RateLimitViolation            (MEDIUM severity)
├── ResourceLimitViolation        (HIGH severity)
├── ForbiddenOperationViolation   (CRITICAL severity)
└── AccessDeniedViolation         (CRITICAL severity)
```

#### Exception Types

**SafetyViolationException** - Base exception for all safety violations

```python
from typing import Any
from temper_ai.safety.exceptions import SafetyViolationException

try:
    # Execute action
    result: Any = agent.execute(action)
except SafetyViolationException as e:
    print(f"Severity: {e.severity.name}")
    print(f"Policy: {e.policy_name}")
    print(f"Message: {e.message}")
    print(f"Remediation: {e.remediation_hint}")
    # Log violation for audit
    logger.error("Safety violation", extra=e.to_dict())
```

**BlastRadiusViolation** - Too many files/changes affected

```python
from typing import Dict, Any, List
from temper_ai.safety.exceptions import BlastRadiusViolation

try:
    modify_files(large_file_list)
except BlastRadiusViolation as e:
    # Split into smaller batches
    metadata: Dict[str, Any] = e.metadata
    print(f"Limit: {metadata['limit']}, Attempted: {metadata['files_affected']}")
    # Remediation: e.remediation_hint suggests splitting changes
```

**ActionPolicyViolation** - Forbidden action/tool

```python
from typing import Dict, Any
from temper_ai.safety.exceptions import ActionPolicyViolation

try:
    execute_tool("forbidden_shell_command")
except ActionPolicyViolation as e:
    # Use approved alternative
    metadata: Dict[str, Any] = e.metadata
    print(f"Forbidden: {metadata.get('forbidden_tool')}")
    print(f"Reason: {metadata.get('reason')}")
```

**RateLimitViolation** - Rate limit exceeded

```python
import time
from typing import Dict, Any
from temper_ai.safety.exceptions import RateLimitViolation

try:
    make_api_call()
except RateLimitViolation as e:
    # Wait and retry
    metadata: Dict[str, Any] = e.metadata
    retry_after: int = metadata.get('retry_after', 60)
    time.sleep(retry_after)
```

**ResourceLimitViolation** - Resource quota exceeded

```python
from typing import Dict, Any, Optional
from temper_ai.safety.exceptions import ResourceLimitViolation

try:
    load_large_dataset()
except ResourceLimitViolation as e:
    # Process in chunks
    metadata: Dict[str, Any] = e.metadata
    resource: Optional[str] = metadata.get('resource')  # e.g., "memory"
    limit: Optional[int] = metadata.get('limit')
    # Remediation: reduce resource consumption
```

**ForbiddenOperationViolation** - Dangerous operation blocked

```python
from typing import Dict, Any, Optional
from temper_ai.safety.exceptions import ForbiddenOperationViolation

try:
    access_secrets()
except ForbiddenOperationViolation as e:
    # Use secure alternative
    metadata: Dict[str, Any] = e.metadata
    operation: Optional[str] = metadata.get('operation')  # e.g., "secret_access"
    # Remediation: use secrets management API
```

**AccessDeniedViolation** - Path/resource access denied

```python
from typing import Dict, Any, List, Optional
from temper_ai.safety.exceptions import AccessDeniedViolation

try:
    read_file("/etc/passwd")
except AccessDeniedViolation as e:
    # Restrict to allowed paths
    metadata: Dict[str, Any] = e.metadata
    allowed_paths: List[str] = metadata.get('allowed_paths', [])
    denied_path: Optional[str] = metadata.get('path')
```

#### Generic Exception Handling

For policy execution errors (not violations):

```python
from typing import Dict, Any
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity
from temper_ai.safety.exceptions import SafetyViolationException

try:
    result = await policy.validate_async(action, context)
except SafetyViolationException:
    # Safety violation - expected, handle appropriately
    raise
except Exception as e:
    # Policy execution error - treat as CRITICAL violation
    violation = SafetyViolation(
        policy_name=policy.name,
        severity=ViolationSeverity.CRITICAL,
        message=f"Policy execution error: {str(e)}",
        action=str(action),
        context=context
    )
    # Action will be blocked
```

---

## Best Practices

### 1. Always Use P0 Policies

Never disable P0 policies in any environment. They prevent:
- Security breaches
- Data loss
- System damage

### 2. Tune P1 Policies for Environment

P1 policies should be:
- **Lenient in development** - fast iteration
- **Moderate in staging** - realistic testing
- **Strict in production** - maximum safety

### 3. Use Environment-Specific Configuration

```yaml
environments:
  development:
    # Fast iteration, see all violations
  staging:
    # Realistic production-like settings
  production:
    # Maximum safety, performance optimized
```

### 4. Monitor Violation Trends

Track violations over time to identify:
- Frequently violated policies (may need tuning)
- Policy effectiveness (violations prevented)
- Developer friction points

### 5. Cache Wisely

- Use caching in production (120s TTL recommended)
- Use shorter TTL in development (30s for fresh results)
- Default TTL is 60s (balanced for most use cases)
- Monitor cache hit rate (target: >70%)
- See [Cache TTL Configuration](#cache-ttl-configuration-by-environment) for environment-specific recommendations

### 6. Custom Policies

Create custom policies for domain-specific rules:
- Business logic validation
- Compliance requirements
- Company-specific security policies

See [CUSTOM_POLICY_DEVELOPMENT.md](./CUSTOM_POLICY_DEVELOPMENT.md) for development guide.

---

## Testing

### Unit Tests

Test individual policies:

```python
from typing import Dict, Any
from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

def test_forbidden_operations_blocks_cat_redirect() -> None:
    policy = ForbiddenOperationsPolicy()

    result = policy.validate(
        action={"command": "cat > file.txt"},
        context={}
    )

    assert result.valid is False
    assert any("Write()" in v.message for v in result.violations)
```

### Integration Tests

Test policy engine with multiple policies:

```python
from typing import Dict, Any
import pytest
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from temper_ai.safety.policy_registry import PolicyRegistry
from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy

@pytest.mark.asyncio
async def test_engine_blocks_on_critical_violation() -> None:
    registry = PolicyRegistry()
    registry.register_policy(
        ForbiddenOperationsPolicy(),
        action_types=["bash_command"]
    )

    engine = ActionPolicyEngine(registry)

    result = await engine.validate_action(
        action={"command": "rm -rf /"},
        context=PolicyExecutionContext(...)
    )

    assert result.allowed is False
    assert result.has_critical_violations()
```

### End-to-End Tests

Test full agent executor integration:

```python
from typing import Dict, Any
import pytest

@pytest.mark.asyncio
async def test_agent_executor_blocks_unsafe_action() -> None:
    executor = AgentExecutor(...)

    unsafe_action: Dict[str, Any] = {
        "type": "bash_command",
        "command": "cat > file.txt"
    }

    with pytest.raises(SafetyViolationError):
        await executor.execute_action(unsafe_action)
```

---

## Troubleshooting

### Issue: Action Blocked Unexpectedly

**Symptom:** Safe action is being blocked.

**Diagnosis:**
1. Check violation message for policy name
2. Review policy configuration
3. Check if policy is too strict

**Solution:**
- Add to whitelist if legitimately safe
- Adjust policy configuration
- Consider environment-specific settings

### Issue: High Cache Miss Rate

**Symptom:** Cache hit rate <50%.

**Diagnosis:**
1. Check cache TTL (too short?)
2. Check action variation (too diverse?)
3. Check cache size (too small?)

**Solution:**
- Increase cache TTL (60-120s)
- Increase max cache size (1000-5000)
- Review cache key strategy

### Issue: Slow Validation

**Symptom:** Validation takes >50ms.

**Diagnosis:**
1. Check number of policies (too many?)
2. Check policy complexity (slow validation?)
3. Check short-circuit (enabled?)

**Solution:**
- Enable short-circuit for CRITICAL violations
- Enable caching
- Profile slow policies
- Consider async optimization

### Issue: Policy Not Executing

**Symptom:** Expected policy not running.

**Diagnosis:**
1. Check policy registration
2. Check action type mapping
3. Check policy priority

**Solution:**
- Verify policy registered: `registry.is_registered("policy_name")`
- Check mappings: `configs/safety/action_policies.yaml`
- Verify priority: `registry.get_policies_for_action("action_type")`

---

## References

### Documentation
- [Policy Configuration Guide](./POLICY_CONFIGURATION_GUIDE.md) - Complete configuration documentation
- [Custom Policy Development](./CUSTOM_POLICY_DEVELOPMENT.md) - Guide to creating custom policies
- [Safety Examples](./SAFETY_EXAMPLES.md) - Common patterns and examples

### Source Code
- `temper_ai/safety/action_policy_engine.py` - Central enforcement engine
- `temper_ai/safety/policy_registry.py` - Policy registration and lookup
- `temper_ai/safety/composition.py` - Policy composition layer
- `temper_ai/safety/forbidden_operations.py` - Forbidden operations policy
- `configs/safety/action_policies.yaml` - Policy configuration

### Tests
- `tests/safety/test_action_policy_engine.py` - Engine tests (25 tests)
- `tests/safety/test_policy_registry.py` - Registry tests (29 tests)
- `tests/safety/test_forbidden_operations.py` - Forbidden ops tests (48 tests)
- `tests/safety/test_composer.py` - Composer tests (37 tests)

---

## FAQ

**Q: Can I disable P0 policies?**
A: No. P0 policies prevent critical security issues and cannot be disabled in any environment.

**Q: How do I add a custom policy?**
A: Implement `SafetyPolicy` interface, register with `PolicyRegistry`. See [Custom Policy Development](./CUSTOM_POLICY_DEVELOPMENT.md).

**Q: What's the performance impact?**
A: <10ms per action typically. Caching reduces to <1ms for cache hits.

**Q: Can I run policies in parallel?**
A: Currently sequential (in priority order). Parallel execution planned for future.

**Q: How do I whitelist a safe command?**
A: Add to policy configuration: `whitelist_commands: ["safe_script.sh"]`

**Q: What happens if a policy crashes?**
A: Exception treated as CRITICAL violation. Action is blocked (fail-closed).

**Q: How do I test my custom policy?**
A: Create unit tests following pattern in `tests/safety/test_*.py`. Test both valid and invalid cases.

**Q: Can I use different policies per agent?**
A: Not directly, but you can use context-based logic in policies to vary behavior by agent_id.

---

## Version History

- **2026-01-27** - Initial M4 release
  - ActionPolicyEngine (m4-08)
  - PolicyRegistry
  - PolicyComposer (m4-02)
  - ForbiddenOperationsPolicy (m4-07)
  - Configuration system

---

## Support

For issues or questions:
1. Check this documentation
2. Review examples in [SAFETY_EXAMPLES.md](./SAFETY_EXAMPLES.md)
3. Check test files for usage patterns
4. File issue in project repository
