# Policy Configuration Guide

**Last Updated:** 2026-01-27
**Related:** [M4 Safety System Architecture](./M4_SAFETY_SYSTEM.md)

---

## Overview

This guide covers configuring the M4 Safety System through the `configs/safety/action_policies.yaml` file. Learn how to:
- Map policies to action types
- Configure policy behavior
- Set environment-specific settings
- Tune performance parameters
- Add custom policies

---

## Configuration File Structure

**Location:** `configs/safety/action_policies.yaml`

```yaml
# Engine configuration
policy_engine:
  cache_ttl: 60
  short_circuit_critical: true
  # ...

# Policy-to-action mappings
policy_mappings:
  file_write:
    - forbidden_ops_policy
    - file_access_policy
  # ...

# Global policies
global_policies:
  - circuit_breaker_policy

# Policy-specific configuration
policy_config:
  rate_limit_policy:
    limits:
      deploy: 2/hour
  # ...

# Environment overrides
environments:
  development:
    # Dev-specific settings
  production:
    # Prod-specific settings
```

---

## Policy Engine Configuration

### Basic Settings

```yaml
policy_engine:
  # Result caching
  cache_ttl: 60              # Cache validation results for 60 seconds
  max_cache_size: 1000       # Maximum number of cached results
  enable_caching: true       # Enable/disable caching

  # Execution behavior
  short_circuit_critical: true   # Stop validation on CRITICAL violations
  enable_async: true             # Use async validation

  # Observability
  log_violations: true       # Log all violations to observability
  metrics_enabled: true      # Track performance metrics
```

### Performance Tuning

#### High-Throughput Environment

```yaml
policy_engine:
  cache_ttl: 120            # Longer cache for better hit rate
  max_cache_size: 5000      # Larger cache
  short_circuit_critical: true  # Skip unnecessary validations
```

**Result:** Higher cache hit rate, lower latency

#### Development Environment

```yaml
policy_engine:
  cache_ttl: 30             # Shorter cache for faster feedback
  short_circuit_critical: false  # See all violations at once
  enable_caching: false     # (Optional) Disable for testing
```

**Result:** Fresh results, complete violation visibility

---

## Policy-to-Action-Type Mappings

### Syntax

```yaml
policy_mappings:
  <action_type>:
    - <policy_name_1>    # Highest priority executes first
    - <policy_name_2>
    - <policy_name_3>
```

### Available Action Types

| Action Type | Description | Example |
|------------|-------------|---------|
| `file_read` | Reading files | `cat file.txt` |
| `file_write` | Writing/creating files | `Write(path="...")` |
| `file_delete` | Deleting files | `rm file.txt` |
| `bash_command` | Bash command execution | Any bash command |
| `git_commit` | Git commits | `git commit` |
| `git_push` | Git pushes | `git push` |
| `deploy` | Deployments | Deploy action |
| `rollback` | Rollbacks | Rollback action |
| `tool_call` | Tool execution | Any tool call |
| `llm_call` | LLM API calls | LLM provider calls |
| `api_call` | External API calls | HTTP requests |
| `db_write` | Database writes | INSERT, UPDATE |
| `db_delete` | Database deletes | DELETE |

### Example: File Operations

```yaml
policy_mappings:
  file_write:
    - file_access_policy          # P0 - Check path permissions
    - forbidden_ops_policy        # P0 - Block bash file writes
    - secret_detection_policy     # P0 - Scan for secrets
    - resource_limit_policy       # P1 - Check file size limits
    - rate_limit_policy           # P1 - Rate limiting

  file_read:
    - file_access_policy          # P0 - Check read permissions
    - resource_limit_policy       # P1 - Check file size limits

  file_delete:
    - file_access_policy          # P0 - Check delete permissions
    - approval_workflow_policy    # P1 - Require approval for sensitive paths
```

### Example: Git Operations

```yaml
policy_mappings:
  git_commit:
    - forbidden_ops_policy        # P0 - Block dangerous git operations
    - secret_detection_policy     # P0 - Scan commits for secrets
    - file_access_policy          # P0 - Check file permissions
    - rate_limit_policy           # P1 - Limit commit rate
    - blast_radius_policy         # P1 - Check commit size

  git_push:
    - rate_limit_policy           # P1 - Limit push rate
    - approval_workflow_policy    # P1 - Require approval for production
```

### Example: Deployment Operations

```yaml
policy_mappings:
  deploy:
    - approval_workflow_policy    # P0 - Always require approval
    - rate_limit_policy           # P1 - Limit deployment rate
    - circuit_breaker_policy      # P1 - Check circuit breaker state

  rollback:
    - approval_workflow_policy    # P1 - Require approval
    - circuit_breaker_policy      # P1 - Check circuit breaker state
```

---

## Global Policies

Global policies apply to **ALL** action types regardless of specific mappings.

```yaml
global_policies:
  - circuit_breaker_policy        # Global circuit breaker
  # Add more global policies as needed
```

**Use Cases:**
- Cross-cutting concerns (circuit breakers, monitoring)
- Policies that apply universally (audit logging)
- Emergency kill switches

**Example:** Add rate limiting to all actions

```yaml
global_policies:
  - circuit_breaker_policy
  - global_rate_limit_policy
```

---

## Policy-Specific Configuration

### Rate Limit Policy

```yaml
policy_config:
  rate_limit_policy:
    limits:
      file_write: 100/min       # 100 file writes per minute
      file_delete: 10/min       # 10 file deletes per minute
      git_commit: 10/hour       # 10 commits per hour
      git_push: 5/hour          # 5 pushes per hour
      deploy: 2/hour            # 2 deployments per hour
      rollback: 3/hour          # 3 rollbacks per hour
      llm_call: 1000/hour       # 1000 LLM calls per hour
      api_call: 100/min         # 100 API calls per minute

    # Rate limit algorithm
    algorithm: "token_bucket"   # token_bucket or sliding_window

    # Burst allowance (token bucket only)
    burst: 10                   # Allow burst of 10 above limit
```

### File Access Policy

```yaml
policy_config:
  file_access_policy:
    # Forbidden paths (no read/write/delete)
    forbidden_paths:
      - /etc/passwd
      - /etc/shadow
      - /root
      - /sys
      - /proc
      - .ssh/id_rsa
      - .ssh/id_ed25519
      - .env.production
      - credentials.json

    # Read-only paths (no write/delete)
    read_only_paths:
      - /usr
      - /lib
      - /lib64
      - /bin
      - /sbin

    # Allowed paths (whitelist - optional)
    allowed_paths:
      - /tmp
      - /workspace
      - /home/agent

    # Path traversal protection
    prevent_path_traversal: true
```

### Forbidden Operations Policy

```yaml
policy_config:
  forbidden_ops_policy:
    # Enable/disable check categories
    check_file_writes: true
    check_dangerous_commands: true
    check_injection_patterns: true
    check_security_sensitive: true

    # Whitelist specific commands (use with caution)
    whitelist_commands:
      - safe_script.sh
      - allowed_operation.py

    # Custom forbidden patterns
    custom_forbidden_patterns:
      custom_pattern_1:
        pattern: "\\bforbidden_keyword\\b"
        message: "Custom forbidden pattern detected"
        severity: HIGH
```

### Blast Radius Policy

```yaml
policy_config:
  blast_radius_policy:
    # Commit size limits
    max_files_per_commit: 20
    max_lines_per_file: 500
    max_total_lines_per_commit: 2000

    # File type limits
    max_binary_file_size: 10485760  # 10 MB

    # Exclusions
    excluded_paths:
      - vendor/
      - node_modules/
      - .lock
```

### Secret Detection Policy

```yaml
policy_config:
  secret_detection_policy:
    # Enabled pattern types
    enabled_patterns:
      - aws_access_key
      - github_token
      - generic_api_key
      - generic_secret
      - private_key
      - slack_token
      - stripe_key

    # Entropy threshold for detection
    entropy_threshold: 4.5

    # Allow test secrets (demo, example, placeholder)
    allow_test_secrets: true

    # Excluded paths
    excluded_paths:
      - tests/
      - test_
      - examples/
      - .example
```

### Approval Workflow Policy

```yaml
policy_config:
  approval_workflow_policy:
    # Actions requiring approval
    require_approval:
      - deploy                    # All deployments
      - rollback                  # All rollbacks
      - db_delete                 # All database deletes
      - file_delete              # Sensitive file deletes

    # Approval timeout (seconds)
    approval_timeout: 3600        # 1 hour

    # Required approvers
    required_approvers: 1         # Number of approvals needed

    # Auto-approve for specific agents (use with caution)
    auto_approve_agents:
      - admin-agent
      - ci-cd-agent
```

### Circuit Breaker Policy

```yaml
policy_config:
  circuit_breaker_policy:
    # Circuit breaker thresholds
    failure_threshold: 5          # Open after 5 failures
    timeout_seconds: 60           # Try again after 60 seconds
    success_threshold: 2          # Close after 2 successes

    # Per-service configuration
    services:
      external_api:
        failure_threshold: 3
        timeout_seconds: 30

      llm_provider:
        failure_threshold: 10
        timeout_seconds: 120
```

### Resource Limit Policy

```yaml
policy_config:
  resource_limit_policy:
    # File size limits
    max_file_size: 10485760       # 10 MB

    # Memory limits
    max_memory_mb: 1024           # 1 GB

    # Token limits (LLM)
    max_tokens_per_request: 4096
    max_tokens_per_hour: 100000

    # Concurrent operation limits
    max_concurrent_operations: 10
```

---

## Environment-Specific Configuration

Override settings for different environments (dev, staging, prod).

### Development Environment

```yaml
environments:
  development:
    policy_engine:
      cache_ttl: 30              # Shorter cache for faster feedback
      short_circuit_critical: false  # See all violations
      log_violations: true       # Still log for learning

    policy_config:
      approval_workflow_policy:
        require_approval: []     # No approvals in dev

      rate_limit_policy:
        limits:
          file_write: 1000/min   # Much higher limits
          git_commit: 100/hour
          deploy: 100/hour

      blast_radius_policy:
        max_files_per_commit: 100  # More lenient
```

### Staging Environment

```yaml
environments:
  staging:
    policy_engine:
      cache_ttl: 60
      short_circuit_critical: true

    policy_config:
      approval_workflow_policy:
        require_approval:
          - deploy               # Only deployments in staging

      rate_limit_policy:
        limits:
          deploy: 5/hour        # Moderate limits

      blast_radius_policy:
        max_files_per_commit: 30  # Moderate limits
```

### Production Environment

```yaml
environments:
  production:
    policy_engine:
      cache_ttl: 120            # Longer cache for performance
      max_cache_size: 5000      # Larger cache
      short_circuit_critical: true

    policy_config:
      approval_workflow_policy:
        require_approval:
          - deploy
          - rollback
          - db_delete
          - file_delete

      rate_limit_policy:
        limits:
          deploy: 1/hour        # Strict limits
          git_push: 3/hour
          db_delete: 1/hour

      blast_radius_policy:
        max_files_per_commit: 20  # Strict limits
        max_lines_per_file: 500

      file_access_policy:
        forbidden_paths:
          - /etc/
          - /root/
          - /sys/
          - /proc/
          - .env.production
          - credentials.json
```

---

## Complete Configuration Example

```yaml
# ===========================================================================
# M4 Safety System Configuration
# ===========================================================================

# Policy Engine Configuration
policy_engine:
  cache_ttl: 60
  max_cache_size: 1000
  enable_caching: true
  short_circuit_critical: true
  enable_async: true
  log_violations: true
  metrics_enabled: true

# Policy-to-Action-Type Mappings
policy_mappings:
  # File Operations
  file_write:
    - file_access_policy
    - forbidden_ops_policy
    - secret_detection_policy
    - resource_limit_policy
    - rate_limit_policy

  file_read:
    - file_access_policy
    - resource_limit_policy

  file_delete:
    - file_access_policy
    - approval_workflow_policy

  # Git Operations
  git_commit:
    - forbidden_ops_policy
    - secret_detection_policy
    - file_access_policy
    - rate_limit_policy
    - blast_radius_policy

  git_push:
    - rate_limit_policy
    - approval_workflow_policy

  # Deployment Operations
  deploy:
    - approval_workflow_policy
    - rate_limit_policy
    - circuit_breaker_policy

  rollback:
    - approval_workflow_policy
    - circuit_breaker_policy

  # Tool & Command Execution
  bash_command:
    - forbidden_ops_policy
    - secret_detection_policy

  tool_call:
    - forbidden_ops_policy
    - resource_limit_policy
    - rate_limit_policy

  # LLM Operations
  llm_call:
    - rate_limit_policy
    - resource_limit_policy

  # API Operations
  api_call:
    - rate_limit_policy
    - circuit_breaker_policy

  # Database Operations
  db_write:
    - approval_workflow_policy
    - rate_limit_policy

  db_delete:
    - approval_workflow_policy

# Global Policies (apply to all actions)
global_policies:
  - circuit_breaker_policy

# Policy-Specific Configuration
policy_config:
  rate_limit_policy:
    limits:
      file_write: 100/min
      git_commit: 10/hour
      git_push: 5/hour
      deploy: 2/hour
      llm_call: 1000/hour
    algorithm: token_bucket
    burst: 10

  file_access_policy:
    forbidden_paths:
      - /etc/passwd
      - /etc/shadow
      - /root
      - .ssh/id_rsa
    read_only_paths:
      - /usr
      - /lib

  blast_radius_policy:
    max_files_per_commit: 20
    max_lines_per_file: 500
    max_total_lines_per_commit: 2000

  approval_workflow_policy:
    require_approval:
      - deploy
      - rollback
      - db_delete
    approval_timeout: 3600
    required_approvers: 1

  circuit_breaker_policy:
    failure_threshold: 5
    timeout_seconds: 60
    success_threshold: 2

# Environment-Specific Overrides
environments:
  development:
    policy_engine:
      cache_ttl: 30
      short_circuit_critical: false
    policy_config:
      approval_workflow_policy:
        require_approval: []
      rate_limit_policy:
        limits:
          git_commit: 100/hour
          deploy: 100/hour

  production:
    policy_engine:
      cache_ttl: 120
      max_cache_size: 5000
    policy_config:
      rate_limit_policy:
        limits:
          deploy: 1/hour
          git_push: 3/hour
```

---

## Testing Configuration

### Validate Configuration Syntax

```bash
# Use YAML linter
yamllint configs/safety/action_policies.yaml

# Or Python YAML parser
python -c "import yaml; yaml.safe_load(open('configs/safety/action_policies.yaml'))"
```

### Test Configuration Loading

```python
import yaml
from pathlib import Path

config_path = Path("configs/safety/action_policies.yaml")
with open(config_path) as f:
    config = yaml.safe_load(f)

# Validate required sections
assert "policy_engine" in config
assert "policy_mappings" in config
assert "policy_config" in config

print("Configuration valid!")
```

### Test Policy Execution

```python
from temper_ai.safety.action_policy_engine import ActionPolicyEngine
from temper_ai.safety.policy_registry import PolicyRegistry

# Load configuration
# ... (load config from YAML)

# Test specific action type
policies = registry.get_policies_for_action("file_write")
print(f"Policies for file_write: {[p.name for p in policies]}")

# Test validation
result = await engine.validate_action(
    action={"command": "cat > file.txt"},
    context=PolicyExecutionContext(
        agent_id="test-agent",
        workflow_id="test-wf",
        stage_id="test",
        action_type="bash_command",
        action_data={}
    )
)

print(f"Allowed: {result.allowed}")
print(f"Violations: {len(result.violations)}")
```

---

## Common Configuration Patterns

### Pattern 1: Strict Production, Lenient Development

```yaml
environments:
  development:
    policy_config:
      rate_limit_policy:
        limits:
          deploy: 1000/hour     # Effectively unlimited
      approval_workflow_policy:
        require_approval: []     # No approvals

  production:
    policy_config:
      rate_limit_policy:
        limits:
          deploy: 1/hour        # Very strict
      approval_workflow_policy:
        require_approval:
          - deploy
          - rollback
          - db_delete
```

### Pattern 2: Progressive Strictness (Dev → Staging → Prod)

```yaml
environments:
  development:
    policy_config:
      blast_radius_policy:
        max_files_per_commit: 100

  staging:
    policy_config:
      blast_radius_policy:
        max_files_per_commit: 50

  production:
    policy_config:
      blast_radius_policy:
        max_files_per_commit: 20
```

### Pattern 3: Per-Team Configuration

```yaml
policy_config:
  approval_workflow_policy:
    # Different approval rules per team
    team_overrides:
      backend_team:
        require_approval:
          - deploy
      frontend_team:
        require_approval:
          - deploy
          - rollback
      infrastructure_team:
        require_approval: []  # Trusted team
```

### Pattern 4: Time-Based Overrides

```yaml
policy_config:
  rate_limit_policy:
    # Different limits during business hours
    time_overrides:
      business_hours:  # 9am-5pm Mon-Fri
        deploy: 5/hour
      off_hours:       # All other times
        deploy: 2/hour
```

---

## Troubleshooting Configuration

### Issue: Policy Not Executing

**Problem:** Expected policy not running for an action.

**Check:**
1. Policy registered in `policy_mappings` for action type?
2. Policy name spelled correctly?
3. Action type correct?

```yaml
# Wrong action type
policy_mappings:
  file_writes:  # Should be file_write (singular)
    - file_access_policy

# Correct
policy_mappings:
  file_write:
    - file_access_policy
```

### Issue: Configuration Not Loading

**Problem:** Changes to YAML not taking effect.

**Check:**
1. YAML syntax valid? (use `yamllint`)
2. File path correct?
3. Application restarted?
4. Environment variable set correctly?

```bash
# Validate YAML
yamllint configs/safety/action_policies.yaml

# Check environment
echo $ENVIRONMENT  # Should be development, staging, or production
```

### Issue: Too Many Violations

**Problem:** Legitimate actions being blocked.

**Solutions:**
1. Review violation messages
2. Adjust policy configuration
3. Add to whitelist if safe
4. Use environment-specific overrides

```yaml
# Example: Whitelist safe command
policy_config:
  forbidden_ops_policy:
    whitelist_commands:
      - safe_script.sh
      - legitimate_operation
```

---

## Best Practices

### 1. Start Strict, Relax Carefully

Begin with strict policies, then relax based on real-world usage:

```yaml
# Start with
policy_config:
  rate_limit_policy:
    limits:
      deploy: 1/hour

# Relax if needed
policy_config:
  rate_limit_policy:
    limits:
      deploy: 3/hour
```

### 2. Use Environment-Specific Overrides

Don't compromise production safety for development speed:

```yaml
# ✓ Good: Separate configs
environments:
  development:
    policy_config:
      approval_workflow_policy:
        require_approval: []

  production:
    policy_config:
      approval_workflow_policy:
        require_approval:
          - deploy

# ✗ Bad: Single lax config for all environments
policy_config:
  approval_workflow_policy:
    require_approval: []
```

### 3. Document Custom Configuration

Add comments explaining custom settings:

```yaml
policy_config:
  rate_limit_policy:
    limits:
      # Increased from 10/hour to 20/hour on 2026-01-15
      # Reason: CI/CD pipeline needs more commits
      # Approved by: security-team
      git_commit: 20/hour
```

### 4. Version Control Configuration

Track configuration changes in git:

```bash
git add configs/safety/action_policies.yaml
git commit -m "Increase deployment rate limit for staging"
```

### 5. Test Configuration Changes

Always test configuration changes in development/staging first:

```bash
# 1. Update development config
# 2. Test in development
# 3. Update staging config
# 4. Test in staging
# 5. Update production config
```

---

## References

- [M4 Safety System Architecture](./M4_SAFETY_SYSTEM.md)
- [Custom Policy Development](./CUSTOM_POLICY_DEVELOPMENT.md)
- [Safety Examples](./SAFETY_EXAMPLES.md)
- Configuration file: `configs/safety/action_policies.yaml`
