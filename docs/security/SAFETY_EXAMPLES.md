# M4 Safety System - Practical Examples

This document provides practical examples of using the M4 safety system in real-world scenarios. For architecture details, see [M4_SAFETY_SYSTEM.md](./M4_SAFETY_SYSTEM.md). For configuration, see [POLICY_CONFIGURATION_GUIDE.md](./POLICY_CONFIGURATION_GUIDE.md).

---

## Table of Contents

1. [Quick Start Examples](#quick-start-examples)
2. [Common Scenarios](#common-scenarios)
3. [Policy Configuration Examples](#policy-configuration-examples)
4. [Integration Patterns](#integration-patterns)
5. [Error Handling Examples](#error-handling-examples)
6. [Testing Examples](#testing-examples)
7. [Troubleshooting Scenarios](#troubleshooting-scenarios)

---

## Quick Start Examples

### Example 1: Basic Action Validation

```python
from typing import Dict, Any
from temper_ai.safety.policy_registry import PolicyRegistry
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy
from temper_ai.safety.file_access import FileAccessPolicy

# Setup
registry = PolicyRegistry()
registry.register_policy(
    ForbiddenOperationsPolicy(),
    action_types=["bash_command", "file_write"]
)
registry.register_policy(
    FileAccessPolicy(),
    action_types=["file_read", "file_write", "file_delete"]
)

engine = ActionPolicyEngine(registry, config={
    "cache_ttl": 60,
    "short_circuit_critical": True
})

# Validate an action
context = PolicyExecutionContext(
    agent_id="agent-001",
    workflow_id="workflow-123",
    stage_id="research",
    action_type="file_write",
    action_data={"path": "/tmp/output.txt", "content": "data"}
)

action: Dict[str, Any] = {
    "type": "file_write",
    "command": "cat > /tmp/output.txt",
    "path": "/tmp/output.txt"
}

# Run validation
result = await engine.validate_action(action, context)

if result.allowed:
    print("✅ Action allowed - proceed with execution")
else:
    print(f"❌ Action blocked by {len(result.violations)} policies:")
    for violation in result.violations:
        print(f"  [{violation.severity.name}] {violation.message}")
        print(f"  Hint: {violation.remediation_hint}")
```

### Example 2: Registering Global Policies

```python
from temper_ai.safety.circuit_breaker import CircuitBreakerPolicy
from temper_ai.safety.rate_limit import RateLimitPolicy

# Global policies apply to ALL actions
registry.register_policy(CircuitBreakerPolicy())  # No action_types = global
registry.register_policy(RateLimitPolicy())

# Now all actions will be validated against these policies
# in addition to their action-specific policies
```

### Example 3: Custom Policy Registration

```python
from typing import Dict, Any, List
from datetime import datetime
from temper_ai.safety.base import BaseSafetyPolicy, ViolationSeverity, SafetyViolation

class BusinessHoursPolicy(BaseSafetyPolicy):
    """Only allow deployments during business hours."""

    @property
    def name(self) -> str:
        return "business_hours_policy"

    @property
    def priority(self) -> int:
        return 100  # P1

    async def validate_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        current_hour: int = datetime.now().hour
        if not (9 <= current_hour < 17):
            return [SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message="Deployments only allowed during business hours (9am-5pm)",
                remediation_hint="Schedule deployment for business hours or request override"
            )]
        return []

# Register for specific actions
registry.register_policy(
    BusinessHoursPolicy(),
    action_types=["deploy", "rollback", "db_migration"]
)
```

---

## Common Scenarios

### Scenario 1: File Operations

#### Problem: Agent wants to write a file

```python
from typing import Dict, Any

# Agent action
action: Dict[str, Any] = {
    "type": "file_write",
    "command": "cat > /app/config/settings.json",
    "path": "/app/config/settings.json",
    "content": '{"api_key": "sk-1234567890"}'
}

context = PolicyExecutionContext(
    agent_id="agent-writer",
    action_type="file_write",
    action_data={"path": "/app/config/settings.json"}
)

result = await engine.validate_action(action, context)
```

#### Outcome: Blocked by multiple policies

```
❌ Action blocked:
  [CRITICAL] Use Write() tool instead of 'cat >' for file operations
    Policy: forbidden_operations_policy
    Hint: Replace with Write(file_path="/app/config/settings.json", content=...)

  [CRITICAL] Potential secret detected: API key pattern in content
    Policy: secret_detection_policy
    Hint: Remove secrets from code, use environment variables or secret manager

  [HIGH] File path /app/config/settings.json is protected
    Policy: file_access_policy
    Hint: Configuration files require explicit approval
```

#### Solution: Fix violations

```python
from typing import Dict, Any
from temper_ai.safety.approval_workflow import request_approval

# 1. Use Write() tool instead of cat
# 2. Remove hardcoded secret
# 3. Request approval for config file write

# Fixed action
action: Dict[str, Any] = {
    "type": "file_write",
    "tool": "Write",
    "path": "/app/config/settings.json",
    "content": '{"api_key": "${API_KEY}"}'  # Use env var
}

# Request approval (if needed)
approval = await request_approval(
    action=action,
    context=context,
    reason="Update API configuration with new endpoint"
)

if approval.granted:
    result = await engine.validate_action(action, context)
    # Now passes
```

### Scenario 2: Deployment Actions

#### Problem: Agent wants to deploy to production

```python
from typing import Dict, Any

action: Dict[str, Any] = {
    "type": "deploy",
    "environment": "production",
    "command": "kubectl apply -f deployment.yaml"
}

context = PolicyExecutionContext(
    agent_id="deploy-agent",
    action_type="deploy",
    action_data={"environment": "production"}
)

result = await engine.validate_action(action, context)
```

#### Outcome: Requires approval and rate limiting

```
❌ Action blocked:
  [CRITICAL] Deployment to production requires approval
    Policy: approval_workflow_policy
    Hint: Submit approval request with deployment justification

  [HIGH] Rate limit exceeded: 1 deployment in last hour (max: 1/hour)
    Policy: rate_limit_policy
    Hint: Wait 45 minutes or request rate limit override
```

#### Solution: Follow approval workflow

```python
import asyncio
from typing import Dict, Any
from temper_ai.safety.approval_workflow import ApprovalRequest

# Step 1: Submit approval request
approval_request = ApprovalRequest(
    action=action,
    context=context,
    justification="Deploy hotfix for critical bug #1234",
    approvers=["team-lead@example.com"]
)

approval = await submit_approval_request(approval_request)

# Step 2: Wait for approval (async notification)
while approval.status == "pending":
    await asyncio.sleep(10)
    approval = await get_approval_status(approval.id)

# Step 3: Check rate limit (may need to wait)
result = await engine.validate_action(action, context)

if not result.allowed:
    # Still blocked by rate limit
    wait_time: int = get_rate_limit_reset_time(context.agent_id, "deploy")
    print(f"Wait {wait_time} seconds for rate limit reset")
    await asyncio.sleep(wait_time)

    # Retry
    result = await engine.validate_action(action, context)

if result.allowed:
    # Proceed with deployment
    await execute_deployment(action)
```

### Scenario 3: Git Operations

#### Problem: Agent wants to commit changes

```python
from typing import Dict, Any, List

action: Dict[str, Any] = {
    "type": "git_commit",
    "command": "git add . && git commit -m 'Update config'",
    "files": [
        "temper_ai/app.py",
        "config/database.yaml",
        ".env",  # Oops!
        "requirements.txt"
    ]
}

context = PolicyExecutionContext(
    agent_id="git-agent",
    action_type="git_commit",
    action_data={"files": action["files"]}
)

result = await engine.validate_action(action, context)
```

#### Outcome: Blocked by multiple policies

```
❌ Action blocked:
  [CRITICAL] Attempting to commit protected file: .env
    Policy: file_access_policy
    Hint: Remove .env from git staging area

  [HIGH] Blast radius exceeds limits: 4 files modified (max: 3)
    Policy: blast_radius_policy
    Hint: Split commit into smaller changes

  [MEDIUM] Potential secret in .env: DATABASE_PASSWORD=...
    Policy: secret_detection_policy
    Hint: Never commit .env files
```

#### Solution: Fix violations

```python
from typing import Dict, Any

# 1. Remove .env from staging
# 2. Split into smaller commits
# 3. Add .gitignore entry

# Fixed action - first commit
action_1: Dict[str, Any] = {
    "type": "git_commit",
    "command": "git add temper_ai/app.py requirements.txt && git commit -m 'Update app dependencies'",
    "files": ["temper_ai/app.py", "requirements.txt"]
}

result_1 = await engine.validate_action(action_1, context)
# ✅ Passes

# Second commit
action_2: Dict[str, Any] = {
    "type": "git_commit",
    "command": "git add config/database.yaml && git commit -m 'Update database config'",
    "files": ["config/database.yaml"]
}

result_2 = await engine.validate_action(action_2, context)
# ✅ Passes

# Add .gitignore entry (separate action)
action_3: Dict[str, Any] = {
    "type": "file_write",
    "tool": "Edit",
    "path": ".gitignore",
    "content": "\n.env\n"
}
# ✅ Passes
```

### Scenario 4: Database Operations

#### Problem: Agent wants to delete database records

```python
from typing import Dict, Any

action: Dict[str, Any] = {
    "type": "db_delete",
    "command": "DELETE FROM users WHERE last_login < '2024-01-01'",
    "table": "users",
    "estimated_rows": 15000
}

context = PolicyExecutionContext(
    agent_id="cleanup-agent",
    action_type="db_delete",
    action_data={"table": "users", "estimated_rows": 15000}
)

result = await engine.validate_action(action, context)
```

#### Outcome: Requires approval and backup

```
❌ Action blocked:
  [CRITICAL] Bulk delete operation requires approval (>1000 rows)
    Policy: approval_workflow_policy
    Hint: Request approval with deletion justification

  [CRITICAL] Database backup required before bulk delete
    Policy: data_integrity_policy
    Hint: Create backup before proceeding
```

#### Solution: Backup and approval workflow

```python
from typing import Dict, Any

# Step 1: Create backup
backup_action: Dict[str, Any] = {
    "type": "db_backup",
    "command": "pg_dump users > /backups/users_$(date +%Y%m%d).sql",
    "table": "users"
}

backup_result = await engine.validate_action(backup_action, context)
backup_id: str
if backup_result.allowed:
    backup_id = await execute_backup(backup_action)

# Step 2: Request approval with backup reference
approval = await request_approval(
    action=action,
    context=context,
    reason=f"Delete inactive users (backup: {backup_id})",
    metadata={"backup_id": backup_id}
)

# Step 3: Validate again after approval
if approval.granted:
    result = await engine.validate_action(action, context)
    if result.allowed:
        await execute_delete(action)
```

---

## Policy Configuration Examples

### Example 1: Development Environment (Lenient)

```yaml
# configs/safety/action_policies.yaml
environments:
  development:
    policy_engine:
      cache_ttl: 30
      short_circuit_critical: false  # See all violations
      enable_caching: true

    policy_config:
      approval_workflow_policy:
        require_approval: []  # No approvals in dev

      rate_limit_policy:
        limits:
          deploy: 100/hour      # Unlimited practically
          git_commit: 100/hour
          api_call: 1000/hour
        cooldown_seconds: 0

      blast_radius_policy:
        max_files_per_commit: 20     # Lenient
        max_lines_per_file: 1000
        forbidden_paths: []           # Allow all paths

      circuit_breaker_policy:
        enabled: false  # Disabled in dev
```

### Example 2: Staging Environment (Moderate)

```yaml
environments:
  staging:
    policy_engine:
      cache_ttl: 60
      short_circuit_critical: true

    policy_config:
      approval_workflow_policy:
        require_approval:
          - deploy        # Staging deploys need approval

      rate_limit_policy:
        limits:
          deploy: 5/hour
          git_commit: 20/hour
          db_delete: 3/hour

      blast_radius_policy:
        max_files_per_commit: 10
        max_lines_per_file: 500
        forbidden_paths:
          - config/production/*
          - secrets/*

      circuit_breaker_policy:
        enabled: true
        failure_threshold: 10
        timeout_seconds: 60
```

### Example 3: Production Environment (Strict)

```yaml
environments:
  production:
    policy_engine:
      cache_ttl: 120
      short_circuit_critical: true
      enable_caching: true

    policy_config:
      approval_workflow_policy:
        require_approval:
          - deploy
          - rollback
          - db_delete
          - db_migration
          - config_update
        approval_timeout_minutes: 30

      rate_limit_policy:
        limits:
          deploy: 1/hour        # Very strict
          rollback: 2/hour
          git_push: 3/hour
          db_delete: 1/day
          api_call: 100/minute

      blast_radius_policy:
        max_files_per_commit: 5
        max_lines_per_file: 200
        forbidden_paths:
          - config/*
          - secrets/*
          - .env*
          - credentials.*

      secret_detection_policy:
        enabled: true
        entropy_threshold: 4.5  # Stricter
        patterns:
          - api_key
          - secret
          - password
          - token
          - private_key

      circuit_breaker_policy:
        enabled: true
        failure_threshold: 5    # Stricter
        timeout_seconds: 300    # Longer timeout
        half_open_requests: 1
```

### Example 4: Action-Specific Configuration

```yaml
policy_mappings:
  # Critical operations - maximum protection
  deploy:
    - approval_workflow_policy    # P0
    - forbidden_ops_policy        # P0
    - rate_limit_policy           # P1
    - circuit_breaker_policy      # P1
    - blast_radius_policy         # P1

  db_delete:
    - approval_workflow_policy    # P0
    - data_integrity_policy       # P0
    - rate_limit_policy           # P1
    - audit_log_policy            # P1

  # File operations - moderate protection
  file_write:
    - file_access_policy          # P0
    - forbidden_ops_policy        # P0
    - secret_detection_policy     # P0
    - resource_limit_policy       # P1

  # Read operations - minimal protection
  file_read:
    - file_access_policy          # P0
    - rate_limit_policy           # P1

# Global policies (apply to ALL actions)
global_policies:
  - circuit_breaker_policy
  - audit_log_policy
```

---

## Integration Patterns

### Pattern 1: Agent Executor Integration

```python
from typing import Dict, Any
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext

class AgentExecutor:
    """Agent executor with integrated safety validation."""

    def __init__(self, policy_engine: ActionPolicyEngine) -> None:
        self.policy_engine = policy_engine

    async def execute_action(self, action: Dict[str, Any], context: PolicyExecutionContext) -> Any:
        """Execute action with pre-execution safety validation."""

        # PRE-EXECUTION: Validate with policy engine
        result = await self.policy_engine.validate_action(action, context)

        if not result.allowed:
            # Log violations
            for violation in result.violations:
                logger.error(
                    f"Action blocked by {violation.policy_name}: {violation.message}",
                    extra={
                        "agent_id": context.agent_id,
                        "action_type": context.action_type,
                        "severity": violation.severity.name
                    }
                )

            # Raise exception with detailed error
            raise SafetyViolationError(
                message=f"Action blocked by {len(result.violations)} policies",
                violations=result.violations,
                action=action
            )

        # Action allowed - execute
        try:
            execution_result = await self._execute_action_impl(action)

            # Log successful execution
            logger.info(
                f"Action executed successfully",
                extra={
                    "agent_id": context.agent_id,
                    "action_type": context.action_type,
                    "execution_time_ms": result.execution_time_ms
                }
            )

            return execution_result

        except Exception as e:
            # Log execution failure
            logger.error(
                f"Action execution failed: {e}",
                extra={
                    "agent_id": context.agent_id,
                    "action_type": context.action_type
                }
            )
            raise

    async def _execute_action_impl(self, action: Dict[str, Any]) -> Any:
        """Actual action execution logic."""
        # Implementation here
        pass
```

### Pattern 2: Workflow Integration

```python
from typing import Callable, Any
from langgraph.graph import StateGraph
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext

class SafeWorkflowBuilder:
    """Build LangGraph workflows with safety validation."""

    def __init__(self, policy_engine: ActionPolicyEngine) -> None:
        self.policy_engine = policy_engine

    def build_workflow(self) -> Any:
        workflow = StateGraph(WorkflowState)

        # Add safety validation node before each action stage
        workflow.add_node("validate_research", self._create_validation_node("research"))
        workflow.add_node("research", self._research_stage)

        workflow.add_node("validate_plan", self._create_validation_node("plan"))
        workflow.add_node("plan", self._plan_stage)

        workflow.add_node("validate_execute", self._create_validation_node("execute"))
        workflow.add_node("execute", self._execute_stage)

        # Chain: validate → action → validate → action
        workflow.add_edge("validate_research", "research")
        workflow.add_edge("research", "validate_plan")
        workflow.add_edge("validate_plan", "plan")
        workflow.add_edge("plan", "validate_execute")
        workflow.add_edge("validate_execute", "execute")

        return workflow.compile()

    def _create_validation_node(self, stage_name: str) -> Callable:
        """Create safety validation node for a stage."""

        async def validate_node(state: WorkflowState) -> WorkflowState:
            # Get planned action for this stage
            action = state.stage_outputs.get(f"{stage_name}_planned_action")

            if action:
                context = PolicyExecutionContext(
                    agent_id=state.agent_id,
                    workflow_id=state.workflow_id,
                    stage_id=stage_name,
                    action_type=action.get("type"),
                    action_data=action
                )

                result = await self.policy_engine.validate_action(action, context)

                if not result.allowed:
                    # Store violations in state
                    state.stage_outputs[f"{stage_name}_violations"] = result.violations
                    state.current_stage = "blocked"
                    return state

            # Validation passed
            return state

        return validate_node
```

### Pattern 3: Observability Integration

```python
from typing import Any, Dict, List
from datetime import datetime, timezone
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity

class ObservabilityIntegration:
    """Integrate policy violations with observability system."""

    def __init__(self, policy_engine: ActionPolicyEngine, observability_db: Any) -> None:
        self.policy_engine = policy_engine
        self.db = observability_db

        # Hook into policy engine
        self.policy_engine.add_violation_callback(self._log_violation)

    async def _log_violation(self, violation: SafetyViolation, context: PolicyExecutionContext) -> None:
        """Log violation to observability database."""

        await self.db.insert("safety_violations", {
            "timestamp": datetime.now(timezone.utc),
            "agent_id": context.agent_id,
            "workflow_id": context.workflow_id,
            "stage_id": context.stage_id,
            "action_type": context.action_type,
            "policy_name": violation.policy_name,
            "severity": violation.severity.name,
            "message": violation.message,
            "remediation_hint": violation.remediation_hint,
            "metadata": context.metadata
        })

        # Alert on critical violations
        if violation.severity == ViolationSeverity.CRITICAL:
            await self._send_alert(violation, context)

    async def _send_alert(self, violation: SafetyViolation, context: PolicyExecutionContext) -> None:
        """Send alert for critical violation."""
        # Implementation: Slack, PagerDuty, etc.
        pass

    async def get_violation_trends(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get violation trends over time."""

        query = """
        SELECT
            policy_name,
            severity,
            COUNT(*) as violation_count,
            DATE_TRUNC('hour', timestamp) as hour
        FROM safety_violations
        WHERE timestamp > NOW() - INTERVAL '{hours} hours'
        GROUP BY policy_name, severity, hour
        ORDER BY hour DESC
        """

        return await self.db.query(query, hours=hours)
```

---

## Error Handling Examples

### Example 1: Graceful Degradation

```python
from typing import Dict, Any, Optional

async def execute_with_fallback(action: Dict[str, Any], context: PolicyExecutionContext) -> Any:
    """Execute action with fallback on policy failure."""

    try:
        # Try validation
        result = await engine.validate_action(action, context)

        if result.allowed:
            return await execute_action(action)
        else:
            # Try alternative action
            alternative: Optional[Dict[str, Any]] = create_alternative_action(action, result.violations)
            if alternative:
                alt_result = await engine.validate_action(alternative, context)
                if alt_result.allowed:
                    logger.info(f"Using alternative action after violation")
                    return await execute_action(alternative)

            # No alternative - fail
            raise SafetyViolationError(result.violations)

    except PolicyEngineError as e:
        # Policy engine failed - decide on fail-open vs fail-closed
        if is_critical_action(action):
            # Fail closed for critical actions
            logger.error(f"Policy engine failed for critical action: {e}")
            raise
        else:
            # Fail open for non-critical actions (with logging)
            logger.warning(f"Policy engine failed, allowing action: {e}")
            return await execute_action(action)
```

### Example 2: Retry with Backoff

```python
import asyncio
from typing import Dict, Any
from temper_ai.safety.action_policy_engine import PolicyExecutionContext, EnforcementResult

async def validate_with_retry(
    action: Dict[str, Any],
    context: PolicyExecutionContext,
    max_retries: int = 3
) -> EnforcementResult:
    """Validate action with exponential backoff on transient errors."""

    for attempt in range(max_retries):
        try:
            result = await engine.validate_action(action, context)
            return result

        except PolicyEngineError as e:
            if attempt == max_retries - 1:
                raise

            # Exponential backoff
            wait_time: int = 2 ** attempt
            logger.warning(f"Validation failed, retrying in {wait_time}s: {e}")
            await asyncio.sleep(wait_time)

    # Should not reach here
    raise PolicyEngineError("Max retries exceeded")
```

### Example 3: Partial Validation

```python
from typing import Dict, Any, List
from temper_ai.safety.action_policy_engine import PolicyExecutionContext, EnforcementResult

async def validate_batch_actions(
    actions: List[Dict[str, Any]],
    context: PolicyExecutionContext
) -> List[Dict[str, Any]]:
    """Validate batch of actions, continue on individual failures."""

    results: List[Dict[str, Any]] = []

    for i, action in enumerate(actions):
        try:
            result: EnforcementResult = await engine.validate_action(action, context)
            results.append({"index": i, "action": action, "result": result})

        except Exception as e:
            logger.error(f"Validation failed for action {i}: {e}")
            results.append({
                "index": i,
                "action": action,
                "error": str(e),
                "result": None
            })

    # Return results for all actions
    return results
```

---

## Testing Examples

### Example 1: Unit Test for Policy Validation

```python
from typing import Dict, Any
import pytest
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from temper_ai.safety.policy_registry import PolicyRegistry
from temper_ai.safety.forbidden_operations import ForbiddenOperationsPolicy
from temper_ai.safety.interfaces import ViolationSeverity

@pytest.fixture
def engine() -> ActionPolicyEngine:
    """Create policy engine with test policies."""
    registry = PolicyRegistry()

    # Register test policies
    registry.register_policy(
        ForbiddenOperationsPolicy(),
        action_types=["bash_command"]
    )

    return ActionPolicyEngine(registry)

@pytest.mark.asyncio
async def test_forbidden_command_blocked(engine: ActionPolicyEngine) -> None:
    """Test that forbidden commands are blocked."""

    action: Dict[str, Any] = {
        "type": "bash_command",
        "command": "rm -rf /"
    }

    context = PolicyExecutionContext(
        agent_id="test-agent",
        action_type="bash_command"
    )

    result = await engine.validate_action(action, context)

    assert not result.allowed
    assert len(result.violations) > 0
    assert result.violations[0].severity == ViolationSeverity.CRITICAL
    assert "rm -rf" in result.violations[0].message

@pytest.mark.asyncio
async def test_safe_command_allowed(engine: ActionPolicyEngine) -> None:
    """Test that safe commands are allowed."""

    action: Dict[str, Any] = {
        "type": "bash_command",
        "command": "ls -la"
    }

    context = PolicyExecutionContext(
        agent_id="test-agent",
        action_type="bash_command"
    )

    result = await engine.validate_action(action, context)

    assert result.allowed
    assert len(result.violations) == 0
```

### Example 2: Integration Test with Agent Executor

```python
from typing import Dict, Any
import pytest
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from temper_ai.safety.interfaces import ViolationSeverity

@pytest.mark.asyncio
async def test_agent_executor_blocks_unsafe_action(policy_engine: ActionPolicyEngine) -> None:
    """Test that agent executor blocks unsafe actions."""

    executor = AgentExecutor(policy_engine)

    unsafe_action: Dict[str, Any] = {
        "type": "file_write",
        "command": "cat > /etc/passwd",
        "path": "/etc/passwd"
    }

    context = PolicyExecutionContext(
        agent_id="test-agent",
        action_type="file_write"
    )

    with pytest.raises(SafetyViolationError) as exc_info:
        await executor.execute_action(unsafe_action, context)

    assert len(exc_info.value.violations) > 0
    assert any(v.severity == ViolationSeverity.CRITICAL
               for v in exc_info.value.violations)
```

### Example 3: Performance Test

```python
from typing import Dict, Any
import time
import pytest
from temper_ai.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext

@pytest.mark.asyncio
async def test_policy_engine_performance(engine: ActionPolicyEngine) -> None:
    """Test that policy validation is fast (<10ms per action)."""

    action: Dict[str, Any] = {
        "type": "file_read",
        "path": "/tmp/test.txt"
    }

    context = PolicyExecutionContext(
        agent_id="perf-test",
        action_type="file_read"
    )

    # Warm up cache
    await engine.validate_action(action, context)

    # Measure 100 validations
    start: float = time.time()
    for _ in range(100):
        result = await engine.validate_action(action, context)
    end: float = time.time()

    avg_time_ms: float = (end - start) * 1000 / 100

    assert avg_time_ms < 10, f"Average validation time {avg_time_ms}ms exceeds 10ms target"
```

---

## Troubleshooting Scenarios

### Scenario 1: Action Blocked Unexpectedly

**Problem:** Action that should be allowed is being blocked.

**Diagnosis:**

```python
# Enable debug logging
import logging
logging.getLogger("temper_ai.safety").setLevel(logging.DEBUG)

# Run validation
result = await engine.validate_action(action, context)

# Check detailed violations
for violation in result.violations:
    print(f"Policy: {violation.policy_name}")
    print(f"Severity: {violation.severity}")
    print(f"Message: {violation.message}")
    print(f"Details: {violation.details}")
    print(f"Hint: {violation.remediation_hint}")
    print("---")

# Check which policies ran
policies = engine.registry.get_policies_for_action(context.action_type)
print(f"Policies checked: {[p.name for p in policies]}")
```

**Common Causes:**
1. **Wrong action_type**: Ensure action_type matches policy mapping
2. **Overly strict policy config**: Check environment-specific settings
3. **Cache issue**: Clear cache and retry
4. **Pattern match too broad**: Check regex patterns in policy

**Solutions:**
```python
# 1. Check action type mapping
print(engine.registry.get_action_types_for_policy("file_access_policy"))

# 2. Check policy configuration
from temper_ai.utils.config_loader import load_config
config = load_config("configs/safety/action_policies.yaml")
print(config["policy_config"]["file_access_policy"])

# 3. Clear cache
engine.clear_cache()

# 4. Test specific policy
policy = engine.registry.get_policy_by_name("file_access_policy")
policy_result = await policy.validate_async(action, context_dict)
print(policy_result)
```

### Scenario 2: High Latency

**Problem:** Policy validation taking too long (>50ms).

**Diagnosis:**

```python
# Get engine metrics
metrics = engine.get_metrics()
print(f"Average validation time: {metrics['avg_validation_time_ms']}ms")
print(f"Cache hit rate: {metrics['cache_hit_rate']:.2%}")
print(f"Total validations: {metrics['validations_performed']}")

# Profile individual policies
for policy in policies:
    start = time.time()
    await policy.validate_async(action, context_dict)
    duration = (time.time() - start) * 1000
    print(f"{policy.name}: {duration:.2f}ms")
```

**Common Causes:**
1. **Cache disabled or low hit rate**
2. **Slow policy (network calls, heavy regex)**
3. **Too many policies per action**
4. **Short-circuit disabled**

**Solutions:**

```python
# 1. Enable/tune caching
engine.config["enable_caching"] = True
engine.config["cache_ttl"] = 120  # Increase TTL

# 2. Enable short-circuit
engine.config["short_circuit_critical"] = True

# 3. Optimize slow policy
class OptimizedPolicy(BaseSafetyPolicy):
    def __init__(self):
        super().__init__()
        # Compile regex patterns once
        self._patterns = [re.compile(p) for p in self.patterns]

    async def validate_async(self, action, context):
        # Use pre-compiled patterns
        for pattern in self._patterns:
            if pattern.search(action["command"]):
                return [violation]

# 4. Profile and optimize
import cProfile
cProfile.run('await engine.validate_action(action, context)')
```

### Scenario 3: Policy Not Running

**Problem:** Policy registered but not being executed.

**Diagnosis:**

```python
# Check if policy is registered
all_policies = engine.registry.list_all_policies()
print(f"Registered policies: {[p['name'] for p in all_policies]}")

# Check for specific action type
policies = engine.registry.get_policies_for_action("file_write")
print(f"Policies for file_write: {[p.name for p in policies]}")

# Check global policies
global_policies = engine.registry._global_policies
print(f"Global policies: {[p.name for p in global_policies]}")
```

**Common Causes:**
1. **Policy not registered**: Registration call missing
2. **Wrong action_type**: Policy registered for different action
3. **Policy disabled in config**: Check YAML configuration
4. **Priority too low**: Policy being skipped

**Solutions:**

```python
# 1. Register policy
registry.register_policy(
    MyPolicy(),
    action_types=["file_write", "file_delete"]
)

# 2. Check action type matches
context = PolicyExecutionContext(
    action_type="file_write",  # Must match registration
    ...
)

# 3. Check configuration
config = load_config("configs/safety/action_policies.yaml")
if "my_policy" in config["policy_config"]:
    if config["policy_config"]["my_policy"].get("enabled") == False:
        print("Policy disabled in configuration!")

# 4. Check priority
print(f"Policy priority: {MyPolicy().priority}")
# Ensure priority is appropriate (P0=200, P1=100, P2=50)
```

---

## Best Practices Checklist

### Before Deployment

- [ ] All policies registered with correct action types
- [ ] Policy configurations validated for each environment
- [ ] Cache TTL tuned for performance
- [ ] Short-circuit enabled for production
- [ ] Observability integration configured
- [ ] Approval workflows tested
- [ ] Rate limits appropriate for traffic
- [ ] Unit tests cover all policies (>90% coverage)
- [ ] Integration tests with agent executor
- [ ] Performance benchmarked (<10ms per action)
- [ ] Error handling tested (fail-closed verified)
- [ ] Metrics and alerting configured

### During Operation

- [ ] Monitor violation rates and trends
- [ ] Track cache hit rates (target >70%)
- [ ] Review blocked actions regularly
- [ ] Adjust rate limits based on usage
- [ ] Update forbidden patterns as needed
- [ ] Review and approve policy overrides
- [ ] Test policy changes in staging first
- [ ] Document all policy exceptions

---

## Additional Resources

- **Architecture**: [M4_SAFETY_SYSTEM.md](./M4_SAFETY_SYSTEM.md)
- **Configuration**: [POLICY_CONFIGURATION_GUIDE.md](./POLICY_CONFIGURATION_GUIDE.md)
- **Custom Policies**: [CUSTOM_POLICY_DEVELOPMENT.md](./CUSTOM_POLICY_DEVELOPMENT.md)
- **API Reference**: See inline docstrings in `temper_ai/safety/`
- **Change Logs**: `changes/0131-action-policy-engine.md`

---

## Getting Help

If you encounter issues not covered here:

1. **Check logs**: Enable DEBUG logging for detailed policy execution
2. **Review metrics**: Use `engine.get_metrics()` to diagnose performance
3. **Test in isolation**: Run individual policies to identify issues
4. **Consult documentation**: Review architecture and configuration guides
5. **Create issue**: Document problem with minimal reproduction case
