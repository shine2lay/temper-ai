# ADR-0005: YAML-Based Workflow Configuration

**Date:** 2026-01-25
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** configuration, yaml, workflows, M1

---

## Context

The framework's vision of "Configuration as Code" requires a format for defining workflows, agents, stages, tools, and safety rules. The configuration system is central to the framework's usability and maintainability.

**Problem Statement:**
- How do users define complex multi-stage workflows?
- What format balances human-readability with machine-parseability?
- How do we support nested structures (workflows → stages → agents → tools)?
- How do we enable validation and type safety?

**Key Requirements:**
1. **Human-Readable** - Non-developers should be able to read and modify workflows
2. **Hierarchical** - Support nested structures (workflows contain stages contain agents)
3. **Comments** - Allow inline documentation
4. **Type-Safe** - Validate configurations before execution
5. **Version Control** - Diff-friendly for git workflows
6. **Templating** - Support variables and reusable components
7. **Standard** - Use industry-standard format

**Use Cases:**
- Product manager defines new workflow without touching code
- Developer creates agent config for code review
- Operations team modifies safety thresholds
- Version control shows clear diffs when workflows change

**Key Questions:**
1. YAML vs JSON vs TOML vs Python/code-based configuration?
2. How strict should validation be (fail fast vs permissive)?
3. Should we support includes/references between config files?
4. How do we handle secrets (API keys, credentials)?

---

## Decision Drivers

- **Readability** - Config should be readable by non-developers
- **Hierarchical** - Workflow configs are deeply nested (3-4 levels)
- **Comments** - Essential for documenting complex workflows
- **Validation** - Catch errors before execution (via Pydantic)
- **Diff-Friendly** - Git diffs should be clear and meaningful
- **Standard Format** - Don't invent custom DSL
- **Tool Support** - IDE syntax highlighting, linting, validation

---

## Considered Options

### Option 1: JSON Configuration

**Description:** Use JSON for all configuration files.

**Pros:**
- Universal standard (supported everywhere)
- Native Python parsing
- Strict structure

**Cons:**
- **No Comments** - Can't document complex configurations
- **Verbose** - Requires quotes on all keys
- **Not Human-Friendly** - Commas, brackets harder to read
- **Trailing Comma Errors** - Common syntax error
- **Poor Diff** - Multi-line changes often affect commas

**Effort:** 2 days (LOW)

---

### Option 2: TOML Configuration

**Description:** Use TOML for configuration files.

**Pros:**
- Comments supported
- Clean syntax (minimal punctuation)
- Good for flat configs

**Cons:**
- **Poor Hierarchical Support** - Deeply nested structures are verbose
- **Less Common** - Smaller ecosystem than YAML/JSON
- **Array of Tables Syntax** - Confusing for complex nesting
- **Not Ideal for Deep Trees** - Workflows have 3-4 levels of nesting

**Effort:** 2-3 days (MEDIUM)

---

### Option 3: Python-Based Configuration

**Description:** Define workflows in Python code (e.g., `workflow.py`).

**Pros:**
- Type-safe (IDE checks types)
- Can use Python logic (loops, conditionals)
- No parsing errors

**Cons:**
- **Not Accessible** - Non-developers can't modify workflows
- **Security Risk** - Executing user-provided Python code
- **Version Control** - Code diffs less clear than data diffs
- **Migration Harder** - Harder to migrate between framework versions
- **Not "Configuration as Code"** - It's just code, not config

**Effort:** 1 week (HIGH)

---

### Option 4: YAML Configuration (with Pydantic Validation)

**Description:** Use YAML for config files, validate with Pydantic schemas.

**Pros:**
- **Human-Readable** - Clean syntax, minimal punctuation
- **Comments Supported** - Inline documentation
- **Hierarchical** - Natural nesting with indentation
- **Industry Standard** - Kubernetes, Docker Compose, GitHub Actions all use YAML
- **Diff-Friendly** - Git diffs are clear
- **Validation** - Pydantic schemas catch errors before execution
- **Tool Support** - IDE syntax highlighting, YAML linting
- **Templating** - Can use Jinja2 for variable substitution
- **References** - YAML anchors for reusing config blocks

**Cons:**
- **Indentation Sensitive** - Whitespace errors (mitigated by IDE)
- **Complex Syntax** - Anchors, tags can be confusing (use sparingly)
- **Performance** - YAML parsing slower than JSON (negligible for config)

**Effort:** 2-3 days (MEDIUM)

---

## Decision Outcome

**Chosen Option:** Option 4: YAML Configuration (with Pydantic Validation)

**Justification:**

YAML provides the perfect balance of human-readability, hierarchical structure, and validation for the framework's needs:

1. **Human-Readable** - Clean, minimal syntax enables product managers and operations teams to modify workflows without developer assistance

2. **Hierarchical Structure** - Natural nesting perfectly matches workflow structure:
   ```yaml
   workflow:
     name: research_workflow
     stages:
       - name: research_stage
         agents:
           - name: researcher
             llm:
               provider: ollama
               model: llama3.2:3b
             tools: [WebScraper, Calculator]
   ```

3. **Comments** - Essential for documenting complex workflows:
   ```yaml
   # Stage 1: Research phase (3 agents in parallel)
   - name: research_stage
     execution: parallel  # 2-3x faster
   ```

4. **Industry Standard** - Same format as Kubernetes, Docker Compose, GitHub Actions—developers already familiar

5. **Validation** - Pydantic schemas provide strong type safety:
   ```python
   class WorkflowConfig(BaseModel):
       name: str
       stages: List[StageConfig]
   ```

6. **Diff-Friendly** - Git diffs clearly show workflow changes:
   ```diff
   - max_concurrent: 3
   + max_concurrent: 5  # Increase parallelism
   ```

7. **Templating** - Jinja2 integration enables variables:
   ```yaml
   model: {{ env.DEFAULT_MODEL | default("llama3.2:3b") }}
   ```

8. **References** - YAML anchors for reusing config blocks:
   ```yaml
   default_llm: &default_llm
     provider: ollama
     model: llama3.2:3b

   agents:
     - name: agent1
       llm: *default_llm  # Reuse default
   ```

**Decision Factors:**
- **Readability:** YAML > TOML > JSON > Python (for non-developers)
- **Hierarchical Support:** YAML > JSON > TOML > Python
- **Comments:** YAML = TOML = Python > JSON
- **Type Safety:** Python > YAML+Pydantic > JSON+Pydantic > TOML+Pydantic
- **Diff-Friendly:** YAML = TOML > JSON > Python
- **Standard:** JSON > YAML > TOML > Python (but YAML is standard for K8s, etc.)

---

## Consequences

### Positive

- **Accessible** - Product managers and operations can modify workflows
- **Clean Syntax** - Minimal punctuation, reads like pseudo-code
- **Comments** - Inline documentation for complex workflows
- **Hierarchical** - Natural nesting matches workflow structure
- **Validation** - Pydantic catches errors before execution
- **Diff-Friendly** - Clear git diffs for version control
- **Tool Support** - IDE syntax highlighting, YAML linting
- **Templating** - Jinja2 variables for environment-specific configs
- **References** - YAML anchors for DRY (Don't Repeat Yourself)
- **Industry Standard** - Familiar format for DevOps engineers

### Negative

- **Indentation Errors** - Whitespace-sensitive (mitigated by IDE linting)
- **Complex Features** - YAML anchors, tags can be confusing (avoid or document well)
- **Parsing Overhead** - Slower than JSON (negligible for config files)
- **Type Safety** - Not as strong as Python (mitigated by Pydantic validation)

### Neutral

- **Learning Curve** - YAML is widely known, minimal learning needed
- **Security** - YAML safe_load prevents code execution (unlike Python configs)

---

## Implementation Notes

**Configuration Hierarchy:**

```
configs/
├── workflows/       # Workflow definitions
│   ├── simple_research.yaml
│   └── parallel_research.yaml
├── stages/          # Reusable stage configs
│   ├── research_stage.yaml
│   └── debate_stage.yaml
├── agents/          # Agent definitions
│   ├── researcher.yaml
│   └── reviewer.yaml
├── tools/           # Tool configurations
│   ├── web_scraper.yaml
│   └── calculator.yaml
├── prompts/         # Prompt templates (Jinja2)
│   └── research_prompt.jinja2
└── safety/          # Safety policies
    └── default_policy.yaml
```

**Example Workflow Config:**

```yaml
# Simple research workflow
workflow:
  name: simple_research
  version: "1.0"
  description: Single-agent research workflow

  # Stages execute sequentially
  stages:
    - name: research_stage
      type: standard
      execution:
        mode: sequential
        timeout_seconds: 300

      agents:
        - name: researcher
          type: standard

          llm:
            provider: ollama
            model: llama3.2:3b
            temperature: 0.7
            max_tokens: 2000

          tools:
            - WebScraper
            - Calculator

          prompt:
            template: prompts/research_prompt.jinja2
            variables:
              depth: "{{ workflow.inputs.depth | default('surface') }}"
              topic: "{{ workflow.inputs.topic }}"

      on_success: end
      on_failure: halt
```

**Pydantic Validation:**

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class WorkflowConfig(BaseModel):
    """Workflow configuration schema."""
    name: str = Field(..., description="Unique workflow name")
    version: str = Field(default="1.0")
    stages: List[StageConfig] = Field(..., min_items=1)

    class Config:
        extra = "forbid"  # Reject unknown fields
```

**Loading and Validation:**

```python
from src.compiler.config_loader import ConfigLoader

loader = ConfigLoader("configs")
workflow_config = loader.load_workflow("simple_research")
# Automatically validated via Pydantic
```

**Action Items:**
- [x] Define Pydantic schemas for all config types
- [x] Create YAML loader with validation
- [x] Add schema documentation
- [x] Create example configs for common workflows
- [x] Add YAML linting to pre-commit hooks
- [x] Document YAML best practices

---

## Related Decisions

- [ADR-0001: Execution Engine Abstraction](./0001-execution-engine-abstraction.md) - Engine selection via YAML config
- [ADR-0002: LangGraph as Initial Engine](./0002-langgraph-as-initial-engine.md) - YAML compiles to LangGraph
- [ADR-0003: Multi-Agent Collaboration Strategies](./0003-multi-agent-collaboration-strategies.md) - Strategy config in YAML
- [ADR-0004: Observability Database Schema](./0004-observability-database-schema.md) - Config snapshots stored in JSON

---

## References

- [Config Schemas Documentation](../interfaces/models/config_schema.md)
- [Milestone 1 Completion Report](../milestones/milestone1_completion.md)
- [YAML Specification](https://yaml.org/spec/1.2.2/) - YAML 1.2 spec
- [Pydantic Documentation](https://docs.pydantic.dev/) - Validation library
- [TECHNICAL_SPECIFICATION.md](../../TECHNICAL_SPECIFICATION.md) - Configuration system

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-25 | Framework Core Team | Initial decision |
| 2026-01-28 | agent-d6e90e | Backfilled from M1 completion |
