# Task: m1-04-config-schemas - Define Pydantic schemas for all config types

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Define Pydantic schemas for validating agent, stage, workflow, tool, and trigger configurations. Schemas should match the YAML structure from TECHNICAL_SPECIFICATION.md and provide clear validation errors.

---

## Files to Create

- `src/compiler/schemas.py` - All Pydantic config schemas
- `tests/test_compiler/test_schemas.py` - Schema validation tests

---

## Acceptance Criteria

### Config Schemas
- [x] - [ ] Agent Config schema (with all fields from spec)
- [x] - [ ] Stage Config schema
- [x] - [ ] Workflow Config schema
- [x] - [ ] Tool Config schema
- [x] - [ ] Trigger Config schema (EventTrigger, CronTrigger)
- [x] - [ ] Nested schemas (InferenceConfig, SafetyConfig, etc.)

### Validation
- [x] - [ ] Required fields enforced
- [x] - [ ] Enum validation (e.g., provider: ollama|vllm|openai)
- [x] - [ ] Type validation (str, int, float, bool, list, dict)
- [x] - [ ] Default values where appropriate
- [x] - [ ] Custom validators for complex rules

### Testing
- [x] - [ ] Test valid configs pass validation
- [x] - [ ] Test invalid configs fail with clear errors
- [x] - [ ] Test required fields
- [x] - [ ] Test default values
- [x] - [ ] Test enum validation
- [x] - [ ] Coverage > 90%

---

## Implementation Snippet

```python
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator


class InferenceConfig(BaseModel):
    """LLM inference configuration."""
    provider: Literal["ollama", "vllm", "openai", "anthropic"]
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.9
    timeout_seconds: int = 60
    max_retries: int = 3
    retry_delay_seconds: int = 2


class SafetyConfig(BaseModel):
    """Safety configuration."""
    mode: Literal["execute", "dry_run", "require_approval"] = "execute"
    require_approval_for_tools: List[str] = Field(default_factory=list)
    max_tool_calls_per_execution: int = 20
    max_execution_time_seconds: int = 300
    risk_level: Literal["low", "medium", "high"] = "medium"


class AgentConfig(BaseModel):
    """Agent configuration schema."""
    agent: 'AgentConfigInner'

class AgentConfigInner(BaseModel):
    name: str
    description: str
    version: str = "1.0"
    prompt: Dict[str, Any]  # template or inline
    inference: InferenceConfig
    tools: List[Any]  # str or dict with overrides
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    # ... other fields
```

---

## Success Metrics

- [x] - [ ] All 5 main config types have schemas
- [x] - [ ] Validation catches invalid configs
- [x] - [ ] Default values work correctly
- [x] - [ ] Tests pass > 90% coverage

---

## Dependencies

- **Blocked by:** m1-00-structure
- **Blocks:** m1-03-config-loader (needs schemas), m1-07-integration

---

## Design References

- TECHNICAL_SPECIFICATION.md Sections 3-7 (all config schemas)
