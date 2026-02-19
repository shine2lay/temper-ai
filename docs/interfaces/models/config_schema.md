# Configuration Schemas

## Overview

All configuration in the Temper AI is defined in YAML and validated using Pydantic schemas. This ensures type safety, provides clear error messages, and enables IDE autocomplete.

## Configuration Hierarchy

```
WorkflowConfig
    │
    ├─ workflow: WorkflowConfigInner
    │   ├─ name, description, version
    │   ├─ triggers: List[TriggerConfig]
    │   └─ stages: List[StageConfig]
    │
    └─ stages: List[StageConfig]
        ├─ stage: StageConfigInner
        │   ├─ name, description
        │   ├─ type: sequential | parallel | debate
        │   └─ agents: List[AgentRef]
        │
        └─ agents: AgentConfig
            ├─ agent: AgentConfigInner
            │   ├─ name, type, prompt
            │   ├─ inference: InferenceConfig
            │   ├─ tools: List[str | ToolConfig]
            │   └─ safety: SafetyConfig
            │
            └─ ... (full agent spec)
```

## Core Schemas

### WorkflowConfig

Top-level workflow configuration.

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class WorkflowConfigInner(BaseModel):
    """Inner workflow configuration."""
    name: str                                  # Workflow identifier
    description: str                           # Human-readable description
    version: str = "1.0"                       # Semantic version

    triggers: List['TriggerConfig'] = Field(default_factory=list)
    stages: List['StageConfigRef'] = []        # Stage references

    # Optional
    optimization_target: Optional[str] = None  # cost | speed | quality
    product_type: Optional[str] = None         # saas | api | mobile_app
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class WorkflowConfig(BaseModel):
    """Top-level workflow configuration."""
    workflow: WorkflowConfigInner
```

**YAML Example:**
```yaml
workflow:
  name: simple_research
  description: "Research agent workflow with web search"
  version: "1.0"
  optimization_target: cost

  triggers:
    - type: event
      event_type: api_request

  stages:
    - stage_name: research
```

### StageConfig

Stage configuration (single phase in workflow).

```python
class StageConfigInner(BaseModel):
    """Inner stage configuration."""
    name: str                                  # Stage identifier
    description: str                           # Human-readable description
    type: Literal["sequential", "parallel", "debate"] = "sequential"

    agents: List['AgentRef']                   # Agents to execute

    # Data flow
    input_from_previous: bool = True           # Receive previous stage output
    output_to_next: bool = True                # Pass output to next stage

    # Execution control
    continue_on_failure: bool = False          # Continue if agent fails
    timeout_seconds: Optional[int] = None      # Stage timeout

    # Collaboration (M3+)
    collaboration_strategy: Optional[str] = None  # voting | merit_weighted
    min_consensus_threshold: float = 0.6       # For debate stages
    max_debate_rounds: int = 3

    # Optional
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class StageConfig(BaseModel):
    """Top-level stage configuration."""
    stage: StageConfigInner
```

**YAML Example:**
```yaml
stage:
  name: research
  description: "Research stage with multiple agents"
  type: parallel

  agents:
    - agent_name: researcher_1
    - agent_name: researcher_2

  continue_on_failure: true
  timeout_seconds: 300
```

### AgentConfig

Complete agent configuration.

```python
class AgentConfigInner(BaseModel):
    """Inner agent configuration."""
    name: str                                  # Agent identifier
    description: str                           # Human-readable description
    version: str = "1.0"
    type: str = "standard"                     # standard | debate | human

    prompt: 'PromptConfig'                     # Prompt template
    inference: 'InferenceConfig'               # LLM configuration
    tools: List[Union[str, 'ToolConfig']] = Field(default_factory=list)
    safety: 'SafetyConfig' = Field(default_factory=SafetyConfig)

    # Collaboration (M3+)
    expertise_domains: List[str] = Field(default_factory=list)
    initial_merit_score: float = 50.0

    # Optional
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class AgentConfig(BaseModel):
    """Top-level agent configuration."""
    agent: AgentConfigInner
```

**YAML Example:**
```yaml
agent:
  name: researcher
  description: "Market research agent"
  version: "1.0"
  type: standard

  prompt:
    template: prompts/researcher.txt
    variables:
      expertise: "market analysis"

  inference:
    provider: ollama
    model: llama3.2:3b
    temperature: 0.7
    max_tokens: 2048

  tools:
    - Calculator
    - WebScraper
    - name: FileWriter
      max_file_size: 10000

  safety:
    mode: execute
    max_tool_calls_per_execution: 10
```

## Nested Schemas

### PromptConfig

Prompt template configuration.

```python
class PromptConfig(BaseModel):
    """Prompt configuration."""
    # Either inline or template file
    inline: Optional[str] = None               # Inline prompt text
    template: Optional[str] = None             # Path to template file

    # Variables to inject
    variables: Dict[str, Any] = Field(default_factory=dict)

    # Template engine settings
    engine: str = "jinja2"                     # jinja2 | mustache
    strict_undefined: bool = True              # Raise on undefined vars

    @field_validator('inline', 'template')
    def check_one_defined(cls, v, values):
        """Ensure either inline or template is set, not both."""
        if 'inline' in values and 'template' in values:
            if values['inline'] and values['template']:
                raise ValueError("Cannot specify both inline and template")
            if not values['inline'] and not values['template']:
                raise ValueError("Must specify either inline or template")
        return v
```

**YAML Examples:**
```yaml
# Inline prompt
prompt:
  inline: |
    You are a {{role}}.
    Task: {{task}}
  variables:
    role: "researcher"

# Template file
prompt:
  template: prompts/researcher.txt
  variables:
    expertise: "market analysis"
```

### InferenceConfig

LLM provider configuration.

```python
class InferenceConfig(BaseModel):
    """LLM inference configuration."""
    # Provider selection
    provider: Literal["ollama", "vllm", "openai", "anthropic"]
    model: str                                 # Model name/identifier

    # Connection
    base_url: Optional[str] = None             # For ollama/vllm
    api_key: Optional[str] = None              # For openai/anthropic

    # Generation parameters
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=100000)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=1)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)

    # Execution control
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay_seconds: int = Field(default=2, ge=1, le=60)

    # Features
    streaming: bool = False                    # Enable streaming
    function_calling: bool = True              # Enable tool calling

    # Optional
    stop_sequences: List[str] = Field(default_factory=list)
    seed: Optional[int] = None                 # For reproducibility
```

**YAML Example:**
```yaml
inference:
  provider: ollama
  model: llama3.2:3b
  base_url: http://localhost:11434

  temperature: 0.7
  max_tokens: 2048
  top_p: 0.9

  timeout_seconds: 60
  max_retries: 3
  streaming: false
```

### SafetyConfig

Safety and execution controls.

```python
class SafetyConfig(BaseModel):
    """Safety configuration."""
    # Execution mode
    mode: Literal["execute", "dry_run", "require_approval"] = "execute"

    # Tool approval
    require_approval_for_tools: List[str] = Field(default_factory=list)
    auto_approve_safe_tools: bool = True

    # Limits
    max_tool_calls_per_execution: int = Field(default=20, ge=1, le=1000)
    max_execution_time_seconds: int = Field(default=300, ge=1, le=3600)
    max_cost_usd: Optional[float] = Field(default=None, ge=0.0)

    # Risk level
    risk_level: Literal["low", "medium", "high"] = "medium"

    # Path restrictions
    allowed_paths: List[str] = Field(default_factory=list)
    forbidden_paths: List[str] = Field(default_factory=lambda: ["/etc", "/sys", "/proc"])

    # Content filtering (M4)
    content_filters: List[str] = Field(default_factory=list)
```

**YAML Example:**
```yaml
safety:
  mode: execute
  require_approval_for_tools:
    - ShellExecutor
    - DatabaseQuery

  max_tool_calls_per_execution: 10
  max_execution_time_seconds: 300
  max_cost_usd: 0.50

  risk_level: medium

  forbidden_paths:
    - /etc
    - /sys
    - /home/user/.ssh
```

### ToolConfig

Tool-specific configuration overrides.

```python
class ToolConfig(BaseModel):
    """Tool configuration with overrides."""
    name: str                                  # Tool name (from registry)

    # Tool-specific overrides
    config: Dict[str, Any] = Field(default_factory=dict)

    # Safety overrides
    require_approval: bool = False
    timeout_seconds: Optional[int] = None
    max_retries: int = 3

    # Optional
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

**YAML Example:**
```yaml
tools:
  # Simple reference
  - Calculator
  - WebScraper

  # With overrides
  - name: FileWriter
    config:
      max_file_size: 10000
      allowed_extensions: [".txt", ".md", ".json"]
    require_approval: false

  - name: ShellExecutor
    require_approval: true
    timeout_seconds: 30
```

### TriggerConfig

Workflow trigger configuration.

```python
class EventTriggerConfig(BaseModel):
    """Event-based trigger."""
    type: Literal["event"] = "event"
    event_type: str                            # api_request | webhook | message
    filter_expression: Optional[str] = None    # JSONPath filter
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CronTriggerConfig(BaseModel):
    """Cron-based trigger."""
    type: Literal["cron"] = "cron"
    schedule: str                              # Cron expression
    timezone: str = "UTC"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ManualTriggerConfig(BaseModel):
    """Manual trigger (CLI/API)."""
    type: Literal["manual"] = "manual"
    metadata: Dict[str, Any] = Field(default_factory=dict)

TriggerConfig = Union[EventTriggerConfig, CronTriggerConfig, ManualTriggerConfig]
```

**YAML Examples:**
```yaml
# Event trigger
triggers:
  - type: event
    event_type: api_request
    filter_expression: "$.data.priority == 'high'"

# Cron trigger
triggers:
  - type: cron
    schedule: "0 9 * * MON-FRI"  # 9am weekdays
    timezone: America/Los_Angeles

# Manual trigger
triggers:
  - type: manual
```

## Validation

### Field Validation

```python
from pydantic import field_validator

class InferenceConfig(BaseModel):
    temperature: float
    max_tokens: int

    @field_validator('temperature')
    def validate_temperature(cls, v):
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v

    @field_validator('max_tokens')
    def validate_max_tokens(cls, v):
        if v < 1 or v > 100000:
            raise ValueError("max_tokens must be between 1 and 100000")
        return v
```

### Model Validation

```python
from pydantic import model_validator

class PromptConfig(BaseModel):
    inline: Optional[str] = None
    template: Optional[str] = None

    @model_validator(mode='after')
    def check_prompt_source(self):
        """Ensure exactly one of inline or template is set."""
        if not self.inline and not self.template:
            raise ValueError("Must specify either inline or template")
        if self.inline and self.template:
            raise ValueError("Cannot specify both inline and template")
        return self
```

## Environment Variable Substitution

All string fields support environment variable substitution:

```yaml
inference:
  provider: openai
  api_key: ${OPENAI_API_KEY}              # From environment
  base_url: ${OPENAI_BASE_URL:https://api.openai.com}  # With default

database:
  url: ${DATABASE_URL}                     # Required env var
```

Implementation:
```python
import os
import re

def substitute_env_vars(config_str: str) -> str:
    """Replace ${VAR} and ${VAR:default} patterns."""
    def replacer(match):
        var_name = match.group(1)
        default = match.group(2)

        value = os.getenv(var_name)
        if value is None:
            if default is None:
                raise ValueError(f"Environment variable {var_name} not set")
            return default
        return value

    pattern = r'\$\{([A-Z_][A-Z0-9_]*?)(?::([^}]+))?\}'
    return re.sub(pattern, replacer, config_str)
```

## Configuration Loading

### ConfigLoader Usage

```python
from temper_ai.compiler.config_loader import ConfigLoader

# Initialize loader
loader = ConfigLoader(config_root="configs")

# Load workflow (validates automatically)
workflow_config = loader.load_workflow("simple_research")
# Returns: WorkflowConfig instance

# Load agent
agent_config = loader.load_agent("researcher")
# Returns: AgentConfig instance

# Load stage
stage_config = loader.load_stage("research_stage")
# Returns: StageConfig instance
```

### Validation Errors

```python
from pydantic import ValidationError

try:
    config = loader.load_workflow("invalid_workflow")
except ValidationError as e:
    # Clear error messages
    print(e.json(indent=2))

    # Example output:
    # [
    #   {
    #     "loc": ["workflow", "inference", "temperature"],
    #     "msg": "temperature must be between 0.0 and 2.0",
    #     "type": "value_error"
    #   }
    # ]
```

## Complete Examples

### Simple Research Workflow

```yaml
# configs/workflows/simple_research.yaml
workflow:
  name: simple_research
  description: "Simple research workflow"
  version: "1.0"

  stages:
    - stage_name: research
```

### Research Stage

```yaml
# configs/stages/research.yaml
stage:
  name: research
  description: "Research stage"
  type: sequential

  agents:
    - agent_name: researcher
```

### Researcher Agent

```yaml
# configs/agents/researcher.yaml
agent:
  name: researcher
  description: "Market research agent"
  version: "1.0"
  type: standard

  prompt:
    inline: |
      You are a market research expert.

      Your task: {{task}}
      Required depth: {{depth}}

      Available tools:
      {{tools}}

      Provide thorough analysis with citations.
    variables:
      depth: "surface"

  inference:
    provider: ollama
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.7
    max_tokens: 2048
    timeout_seconds: 60

  tools:
    - Calculator
    - WebScraper
    - name: FileWriter
      config:
        max_file_size: 50000

  safety:
    mode: execute
    max_tool_calls_per_execution: 10
    max_execution_time_seconds: 300
```

## Schema Export

Generate JSON Schema for external tools:

```python
from temper_ai.compiler.schemas import WorkflowConfig, AgentConfig

# Export JSON Schema
workflow_schema = WorkflowConfig.model_json_schema()
agent_schema = AgentConfig.model_json_schema()

# Save to file
import json
with open("workflow_schema.json", "w") as f:
    json.dump(workflow_schema, f, indent=2)
```

This enables:
- IDE autocomplete in YAML editors
- Schema validation in CI/CD
- API documentation generation

## Related Documentation

- [Agent Interface](./agent_interface.md)
- [LLM Provider Interface](./llm_provider_interface.md)
- [Tool Interface](./tool_interface.md)
- [System Overview](../architecture/SYSTEM_OVERVIEW.md)
