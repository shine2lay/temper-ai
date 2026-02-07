# Configuration Guide

**Scope:** General Framework Configuration (Agents, Workflows, LLM Providers, Tools, Multi-Agent, Observability)

**For M4 Safety System Configuration:** See [M4_CONFIGURATION_GUIDE.md](M4_CONFIGURATION_GUIDE.md) for detailed safety policy, approval workflows, rollback, circuit breakers, and safety gate configuration.

Complete guide to configuring the Meta-Autonomous Agent Framework.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Configuration Basics](#configuration-basics)
3. [Agent Configuration](#agent-configuration)
4. [Workflow Configuration](#workflow-configuration)
5. [LLM Provider Configuration](#llm-provider-configuration)
6. [Tool Configuration](#tool-configuration)
7. [Safety Configuration](#safety-configuration)
8. [Multi-Agent Configuration](#multi-agent-configuration)
9. [Observability Configuration](#observability-configuration)
10. [Environment Variables](#environment-variables)
11. [Best Practices](#best-practices)
12. [Examples](#examples)

---

## Quick Start

### Minimal Agent Config

**File:** `configs/agents/simple_agent.yaml`

```yaml
agent:
  name: simple_researcher
  description: Basic research agent
  version: 1.0
  type: standard

  prompt:
    inline: |
      You are a research assistant.
      Query: {{ query }}
      Provide a detailed response.

  inference:
    provider: ollama
    model: llama3.2:3b
    temperature: 0.7

  tools: []
```

### Minimal Workflow Config

**File:** `configs/workflows/simple_workflow.yaml`

```yaml
workflow:
  name: simple_research
  description: Single-agent research workflow
  version: 1.0

  stages:
    - name: research
      stage_ref: configs/stages/research.yaml
```

### Run Your Config

```bash
maf run configs/workflows/simple_workflow.yaml \
  --input inputs.yaml --show-details
```

---

## Configuration Basics

### File Structure

```
configs/
├── agents/          # Agent definitions
│   ├── researcher.yaml
│   ├── writer.yaml
│   └── reviewer.yaml
│
├── workflows/       # Workflow definitions
│   ├── simple_research.yaml
│   └── multi_agent_debate.yaml
│
├── tools/           # Tool configurations (optional)
│   └── custom_tool.yaml
│
└── prompts/         # Reusable prompt templates
    └── research_prompt.j2
```

### YAML Basics

```yaml
# Comments start with #
key: value
number: 42
float: 3.14
boolean: true
list:
  - item1
  - item2
nested:
  child_key: child_value
```

### Environment Variables

Reference environment variables in configs:

```yaml
inference:
  provider: openai
  api_key: ${env:OPENAI_API_KEY}  # From environment
  model: gpt-4
```

---

## Agent Configuration

### Full Agent Config

```yaml
agent:
  name: research_agent
  description: "Advanced research agent with tools"
  version: "1.0"
  type: standard

  # Prompt Configuration
  prompt:
    template: prompts/research.j2      # External template file
    # OR
    inline: |                          # Inline template
      You are a research assistant.
      Topic: {{ topic }}
    variables:                         # Default variables
      max_depth: 3
      format: markdown

  # LLM Configuration
  inference:
    provider: ollama                   # ollama | openai | anthropic | vllm
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.7
    max_tokens: 2048
    top_p: 0.9
    timeout_seconds: 60
    max_retries: 3
    retry_delay_seconds: 1.0

  # Tools
  tools:
    - WebScraper
    - Calculator
    - FileWriter

  # Safety Limits
  safety:
    max_tool_calls_per_execution: 10
    allowed_domains:
      - wikipedia.org
      - arxiv.org
    forbidden_operations:
      - delete_file
      - modify_system

  # Error Handling
  error_handling:
    retry_strategy: ExponentialBackoff
    fallback: GracefulDegradation
    max_retries: 3

  # Memory (optional)
  memory:
    type: conversation
    max_messages: 10
```

### Prompt Configuration Options

**Option 1: Inline Prompt**
```yaml
prompt:
  inline: |
    You are {{ role }}.
    Task: {{ task }}
```

**Option 2: External Template**
```yaml
prompt:
  template: prompts/my_prompt.j2
  variables:
    role: researcher
    task: analyze data
```

**Template File (`prompts/my_prompt.j2`):**
```jinja2
You are a {{ role }}.

Your task: {{ task }}

{% if context %}
Context: {{ context }}
{% endif %}

Provide a detailed response.
```

### Inference Provider Options

**Ollama (Local):**
```yaml
inference:
  provider: ollama
  model: llama3.2:3b
  base_url: http://localhost:11434
  temperature: 0.7
```

**OpenAI:**
```yaml
inference:
  provider: openai
  model: gpt-4
  api_key: ${env:OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  temperature: 0.7
  max_tokens: 2048
```

**Anthropic:**
```yaml
inference:
  provider: anthropic
  model: claude-3-opus-20240229
  api_key: ${env:ANTHROPIC_API_KEY}
  base_url: https://api.anthropic.com/v1
  temperature: 0.7
```

**vLLM (Custom):**
```yaml
inference:
  provider: vllm
  model: custom-model
  base_url: http://localhost:8000
  temperature: 0.7
```

---

## Workflow Configuration

### Workflow Structure

```yaml
workflow:
  name: my_workflow
  description: "Multi-stage workflow"
  version: "1.0"

  # Execution Engine
  engine: langgraph                   # Default: langgraph
  engine_config:
    max_retries: 3
    timeout: 300

  # Stages
  stages:
    - name: stage1
      stage_ref: configs/stages/research.yaml

    - name: stage2
      stage_ref: configs/stages/writing.yaml
      depends_on:
        - stage1
```

### Stage Types

**1. Agent Stage (Sequential)**
```yaml
stages:
  - name: research
    stage_ref: configs/stages/research.yaml
```

**2. Parallel Stage**
```yaml
stages:
  - name: parallel_research
    type: parallel
    agents:
      - researcher1
      - researcher2
      - researcher3
    execution:
      agent_mode: parallel
      max_concurrent: 3
    collaboration:
      strategy: consensus
```

**3. Debate Stage**
```yaml
stages:
  - name: debate_decision
    type: debate
    agents:
      - analyst1
      - analyst2
      - analyst3
    collaboration:
      strategy: debate
      config:
        max_rounds: 5
        convergence_threshold: 0.8
```

### Data Flow

**Input Mapping:**
```yaml
input_mapping:
  query: $input.topic              # From workflow input
  context: $stages.prev.output     # From previous stage
  config: $workflow.metadata       # From workflow metadata
```

**Output Mapping:**
```yaml
output_mapping:
  final_result: $stages.writer.output
  research_data: $stages.research.output
  metadata:
    total_time: $execution.duration
    cost: $execution.total_cost
```

---

## LLM Provider Configuration

### Ollama Configuration

```yaml
inference:
  provider: ollama
  model: llama3.2:3b              # Or: mistral, codellama, etc.
  base_url: http://localhost:11434
  temperature: 0.7
  max_tokens: 2048
  top_p: 0.9
```

**Available Models:**
- `llama3.2:3b` - Fast, good for simple tasks
- `llama3.2:8b` - Balanced, better reasoning
- `mistral` - Alternative, good quality
- `codellama` - Optimized for code

**Pull Models:**
```bash
ollama pull llama3.2:3b
```

### OpenAI Configuration

```yaml
inference:
  provider: openai
  model: gpt-4                    # Or: gpt-3.5-turbo, gpt-4-turbo
  api_key: ${env:OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  temperature: 0.7
  max_tokens: 2048
  timeout_seconds: 60
  max_retries: 3
```

**Model Options:**
- `gpt-4` - Best quality, expensive
- `gpt-4-turbo` - Fast, cheaper than gpt-4
- `gpt-3.5-turbo` - Fast, cheap, good for simple tasks

### Anthropic Configuration

```yaml
inference:
  provider: anthropic
  model: claude-3-opus-20240229   # Or: sonnet, haiku
  api_key: ${env:ANTHROPIC_API_KEY}
  base_url: https://api.anthropic.com/v1
  temperature: 0.7
  max_tokens: 4096
```

**Model Options:**
- `claude-3-opus-20240229` - Best quality
- `claude-3-sonnet-20240229` - Balanced
- `claude-3-haiku-20240307` - Fast, cheap

### Cost Optimization

```yaml
# Use cheaper models for simple tasks
inference:
  provider: openai
  model: gpt-3.5-turbo
  temperature: 0.7
  max_tokens: 500                # Limit tokens

# Or use local models (free)
inference:
  provider: ollama
  model: llama3.2:3b
```

---

## Tool Configuration

### Basic Tool List

```yaml
tools:
  - Calculator
  - WebScraper
  - FileWriter
```

### Tool with Configuration

```yaml
tools:
  - name: WebScraper
    config:
      timeout: 30
      max_retries: 3
      rate_limit: 10  # requests per minute

  - name: FileWriter
    config:
      base_directory: /tmp/outputs
      allowed_extensions:
        - .txt
        - .md
        - .json
```

### Custom Tool

**Define tool class:**
```python
# src/tools/my_tool.py
from src.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "MyTool"

    @property
    def description(self) -> str:
        return "My custom tool"

    def execute(self, **kwargs) -> ToolResult:
        # Implementation
        return ToolResult(success=True, result="done")
```

**Register in config:**
```yaml
tools:
  - MyTool
```

---

## Safety Configuration

**Note:** This section covers basic safety constraints (timeouts, rate limits, allowed operations). For advanced safety features (policies, approval workflows, rollback, circuit breakers), see [M4_CONFIGURATION_GUIDE.md](M4_CONFIGURATION_GUIDE.md).

### Agent-Level Safety

```yaml
safety:
  max_tool_calls_per_execution: 10
  max_execution_time_seconds: 300

  allowed_domains:
    - wikipedia.org
    - github.com
    - arxiv.org

  forbidden_operations:
    - delete_file
    - modify_system
    - execute_code

  rate_limits:
    max_requests_per_minute: 10
    max_tokens_per_hour: 100000
```

### Stage-Level Safety

```yaml
stages:
  - name: research
    type: agent
    agent_ref: researcher

    safety:
      max_duration_seconds: 60
      max_cost_usd: 0.10
      require_approval: false
```

### Workflow-Level Safety

```yaml
workflow:
  name: my_workflow

  safety:
    max_total_cost_usd: 1.00
    max_total_duration_seconds: 600
    require_human_approval_for:
      - high_cost_operations
      - destructive_operations
```

---

## Multi-Agent Configuration

### Parallel Execution

```yaml
stages:
  - name: parallel_research
    type: parallel

    execution:
      agent_mode: parallel        # Run concurrently
      max_concurrent: 3           # Max 3 at once
      min_success: 2              # At least 2 must succeed

    agents:
      - researcher1
      - researcher2
      - researcher3

    input_mapping:
      topic: $input.topic
```

### Consensus Strategy

```yaml
collaboration:
  strategy: consensus
  conflict_resolver: merit_weighted

  config:
    threshold: 0.5                # 50% agreement needed
    conflict_threshold: 0.3       # 30% disagreement = conflict
    weights:                      # Optional agent weights
      researcher1: 1.0
      researcher2: 1.2            # Higher expertise
      researcher3: 1.0
```

### Debate Strategy

```yaml
collaboration:
  strategy: debate
  conflict_resolver: merit_weighted

  config:
    max_rounds: 5
    convergence_threshold: 0.8    # 80% agents unchanged
    min_confidence: 0.7           # Min confidence for acceptance
    allow_early_termination: true
```

### Merit-Weighted Resolution

```yaml
conflict_resolution:
  strategy: merit_weighted

  merit_tracking:
    enabled: true
    decay_factor: 0.9             # Recent success weighs more
    min_executions: 3             # Min runs before weighting

  domain_expertise:
    researcher1:
      - python
      - machine_learning
    researcher2:
      - javascript
      - web_development
```

---

## Observability Configuration

### Database Configuration

**SQLite (Development):**
```yaml
observability:
  enabled: true
  database_url: sqlite:///./observability.db
```

**PostgreSQL (Production):**
```yaml
observability:
  enabled: true
  database_url: postgresql://user:pass@localhost:5432/dbname
```

**Environment Variable:**
```yaml
observability:
  enabled: true
  database_url: ${env:DATABASE_URL}
```

### Tracking Configuration

```yaml
observability:
  enabled: true
  database_url: sqlite:///./obs.db

  track_llm_calls: true
  track_tool_calls: true
  track_errors: true

  retention_days: 30              # Auto-cleanup old data

  console_streaming: true         # Real-time console output
  log_level: INFO                 # DEBUG | INFO | WARNING | ERROR
```

---

## Environment Variables

### Required Variables

```bash
# For OpenAI
export OPENAI_API_KEY=sk-...

# For Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# For Ollama (optional - uses default)
export OLLAMA_BASE_URL=http://localhost:11434
```

### Optional Variables

```bash
# Database
export DATABASE_URL=postgresql://user:pass@localhost/db

# Observability
export OBSERVABILITY_ENABLED=true
export LOG_LEVEL=INFO

# Safety
export MAX_COST_USD=10.00
export MAX_EXECUTION_TIME=3600
```

### .env File

**Create `.env` file:**
```bash
# LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_BASE_URL=http://localhost:11434

# Database
DATABASE_URL=sqlite:///./observability.db

# Observability
OBSERVABILITY_ENABLED=true
LOG_LEVEL=INFO

# Safety
MAX_COST_USD=10.00
```

**Load automatically:**
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## Best Practices

### 1. Separate Configs by Environment

```
configs/
├── agents/
│   ├── base/
│   │   └── researcher.yaml
│   ├── dev/
│   │   └── researcher_dev.yaml
│   └── prod/
│       └── researcher_prod.yaml
```

### 2. Use Environment Variables for Secrets

**Bad:**
```yaml
api_key: sk-1234567890abcdef  # Hard-coded secret
```

**Good:**
```yaml
api_key: ${env:OPENAI_API_KEY}  # From environment
```

### 3. Start Simple, Add Complexity

**Start with:**
```yaml
inference:
  provider: ollama
  model: llama3.2:3b
  temperature: 0.7
```

**Then optimize:**
```yaml
inference:
  provider: openai
  model: gpt-4
  temperature: 0.7
  max_tokens: 2048
  timeout_seconds: 60
  max_retries: 3
```

### 4. Use Descriptive Names

**Bad:**
```yaml
agent:
  name: a1
  description: agent
```

**Good:**
```yaml
agent:
  name: research_agent
  description: "Research agent specialized in technical documentation"
```

### 5. Document Your Configs

```yaml
agent:
  name: researcher

  # Using Ollama for cost savings during development
  # Switch to OpenAI in production for better quality
  inference:
    provider: ollama
    model: llama3.2:3b
    temperature: 0.7  # Higher = more creative
```

---

## Examples

### Example 1: Simple Research Agent

```yaml
agent:
  name: simple_researcher
  description: Basic research agent
  version: 1.0

  prompt:
    inline: |
      Research the following topic: {{ topic }}
      Provide a comprehensive summary.

  inference:
    provider: ollama
    model: llama3.2:3b
    temperature: 0.7

  tools:
    - WebScraper
```

### Example 2: Multi-Agent Parallel Research

```yaml
workflow:
  name: parallel_research
  description: "3 agents research in parallel"

stages:
  - name: research
    type: parallel

    execution:
      agent_mode: parallel
      max_concurrent: 3

    agents:
      - researcher1
      - researcher2
      - researcher3

    collaboration:
      strategy: consensus
      config:
        threshold: 0.5

    input_mapping:
      topic: $input.topic
```

### Example 3: Production-Ready Agent

```yaml
agent:
  name: production_agent
  description: "Production-ready agent with full config"
  version: 1.0

  prompt:
    template: prompts/production.j2

  inference:
    provider: openai
    model: gpt-4
    api_key: ${env:OPENAI_API_KEY}
    temperature: 0.7
    max_tokens: 2048
    timeout_seconds: 60
    max_retries: 3

  tools:
    - WebScraper
    - Calculator

  safety:
    max_tool_calls_per_execution: 10
    max_execution_time_seconds: 300
    allowed_domains:
      - wikipedia.org

  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3

  observability:
    enabled: true
    track_llm_calls: true
    track_tool_calls: true
```

---

## Troubleshooting

### Issue: Config Not Loading

**Error:** `FileNotFoundError: configs/agents/my_agent.yaml`

**Solution:**
- Check file path is correct
- Ensure file exists
- Verify working directory

### Issue: Validation Error

**Error:** `ValidationError: field required (type=value_error.missing)`

**Solution:**
- Check all required fields are present
- Verify field names match schema
- Check indentation in YAML

### Issue: API Key Not Found

**Error:** `ValueError: API key not found`

**Solution:**
```bash
# Set environment variable
export OPENAI_API_KEY=sk-...

# Or create .env file
echo "OPENAI_API_KEY=sk-..." >> .env
```

---

## Summary

- **Configuration is YAML-based** with Pydantic validation
- **Three main config types:** Agents, Workflows, Tools
- **Environment variables** for secrets and environment-specific values
- **Multiple LLM providers** supported (Ollama, OpenAI, Anthropic, vLLM)
- **Safety policies** at agent, stage, and workflow levels
- **Multi-agent collaboration** with parallel execution and synthesis
- **Best practices:** Separate configs by environment, use env vars for secrets, start simple

For detailed schema reference, see [Config Schemas](./interfaces/models/config_schema.md).

Happy configuring! ⚙️
