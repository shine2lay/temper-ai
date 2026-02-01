# Configuration Directory

This directory contains YAML configuration files for the Meta-Autonomous Framework.

## Directory Structure

```
configs/
├── agents/       # Agent definitions and configurations
├── workflows/    # Workflow definitions (DAGs)
├── stages/       # Stage configurations
├── tools/        # Tool configurations
├── prompts/      # Prompt templates
├── triggers/     # Event trigger definitions
├── oauth/        # OAuth provider configurations
└── README.md     # This file
```

---

## Configuration Files by Type

### 1. Agents (`agents/`)

Agent configurations define AI agents with their models, tools, and behavior.

**File naming:** `<agent-name>.yaml`

**Example:**
```yaml
# agents/research_agent.yaml
name: research_agent
description: Agent specialized in research and information gathering

inference:
  provider: ollama
  model: llama3.2:3b
  temperature: 0.7
  max_tokens: 2000

tools:
  - web_search
  - web_scraper
  - summarizer

prompts:
  system: prompts/research_system.j2
  user: prompts/research_user.j2
```

**Common Configurations:**
- `basic_agent.yaml` - Simple LLM-only agent
- `tool_agent.yaml` - Agent with tool access
- `specialized_agent.yaml` - Domain-specific agent

---

### 2. Workflows (`workflows/`)

Workflow definitions specify multi-stage agent execution graphs.

**File naming:** `<workflow-name>.yaml`

**Example:**
```yaml
# workflows/content_pipeline.yaml
name: content_pipeline
description: End-to-end content creation pipeline

stages:
  - name: research
    agent: research_agent
    next: outline

  - name: outline
    agent: outline_agent
    next: draft

  - name: draft
    agent: writer_agent
    next: review

  - name: review
    agent: editor_agent
    condition: quality_gate
    next: publish

  - name: publish
    agent: publisher_agent
    final: true
```

**Workflow Types:**
- **Linear:** Sequential stages (research → outline → draft)
- **Parallel:** Concurrent execution with LangGraph subgraphs
- **Conditional:** Branch based on conditions/gates
- **Looped:** Retry logic with convergence detection

---

### 3. Stages (`stages/`)

Stage configurations define individual workflow steps.

**File naming:** `<stage-name>.yaml`

**Example:**
```yaml
# stages/validation_stage.yaml
name: validation
type: conditional

agent: validator_agent

inputs:
  - draft_content
  - style_guide

outputs:
  - validation_result
  - suggested_edits

retry:
  max_attempts: 3
  backoff: exponential

quality_gate:
  metric: validation_score
  threshold: 0.8
```

---

### 4. Tools (`tools/`)

Tool configurations specify external tools and integrations.

**File naming:** `<tool-name>.yaml`

**Example:**
```yaml
# tools/web_scraper.yaml
name: web_scraper
description: Extract content from web pages

class: src.tools.web.WebScraperTool

parameters:
  timeout: 30
  max_retries: 3
  user_agent: "Meta-Autonomous-Bot/1.0"

rate_limit:
  requests_per_minute: 60
  burst: 10

safety:
  forbidden_domains:
    - malicious-site.com
  required_protocols:
    - https
```

**Common Tools:**
- `calculator.yaml` - Math operations
- `web_search.yaml` - Web search integration
- `file_operations.yaml` - File read/write
- `database.yaml` - Database queries

---

### 5. Prompts (`prompts/`)

Jinja2 prompt templates for agents.

**File naming:** `<prompt-name>.j2`

**Example:**
```jinja2
{# prompts/research_system.j2 #}
You are a research assistant specialized in {{ domain }}.

Your task is to:
1. Gather information from reliable sources
2. Synthesize findings into clear summaries
3. Cite sources appropriately

Guidelines:
- Prioritize recent information (last {{ timeframe }} years)
- Use {{ num_sources }} or more sources
- Fact-check claims before including

Current date: {{ current_date }}
```

**Usage in Agent Config:**
```yaml
prompts:
  system: prompts/research_system.j2
  user: prompts/research_user.j2

variables:
  domain: technology
  timeframe: 5
  num_sources: 3
```

---

### 6. Triggers (`triggers/`)

Event-driven trigger configurations.

**File naming:** `<trigger-name>.yaml`

**Example:**
```yaml
# triggers/new_ticket.yaml
name: new_support_ticket
description: Trigger workflow when support ticket created

event_type: ticket.created

filters:
  priority:
    - high
    - critical
  department:
    - engineering

workflow: support_response_pipeline

variables:
  escalate_threshold: 2
  response_sla: 1h
```

---

### 7. OAuth (`oauth/`)

OAuth provider configurations for authentication.

**File naming:** `<provider-name>.yaml`

**Example:**
```yaml
# oauth/github.yaml
provider: github
client_id: ${GITHUB_CLIENT_ID}
client_secret: ${GITHUB_CLIENT_SECRET}

scopes:
  - repo
  - user:email
  - workflow

endpoints:
  authorize: https://github.com/login/oauth/authorize
  token: https://github.com/login/oauth/access_token
  user_info: https://api.github.com/user
```

**Environment Variables:**
- Use `${VAR_NAME}` syntax for secrets
- Load from `.env` file via python-dotenv

---

## File Naming Conventions

### Standard Format

```
<entity-type>_<descriptor>_<variant>.yaml
```

**Examples:**
- `research_agent_basic.yaml`
- `validation_stage_strict.yaml`
- `content_workflow_blog.yaml`

### Naming Rules

1. **Lowercase:** All filenames lowercase
2. **Underscores:** Use `_` to separate words (not hyphens)
3. **Descriptive:** Name should indicate purpose
4. **No spaces:** Never use spaces in filenames
5. **Extensions:** Always `.yaml` (not `.yml`)

---

## Creating Custom Configurations

### Step 1: Choose Template

Copy an existing configuration as a starting point:

```bash
# Create new agent based on existing
cp configs/agents/basic_agent.yaml configs/agents/my_custom_agent.yaml
```

### Step 2: Edit Configuration

Modify the copied file:

```yaml
name: my_custom_agent  # Change name
description: My specialized agent for X

inference:
  model: llama3.2:7b  # Larger model if needed

tools:
  - custom_tool  # Add your tools

# Add custom fields as needed
```

### Step 3: Validate Configuration

```bash
# Run agent with custom config
python -m src.cli.main --agent configs/agents/my_custom_agent.yaml
```

---

## Configuration Examples by Use Case

### Use Case: Blog Writing Pipeline

**Workflow:** `workflows/blog_pipeline.yaml`
```yaml
stages:
  - research → outline → draft → edit → publish
```

**Agents:**
- `agents/researcher.yaml` - Gather information
- `agents/outliner.yaml` - Create structure
- `agents/writer.yaml` - Draft content
- `agents/editor.yaml` - Review and polish

**Tools:**
- `tools/web_search.yaml` - Research sources
- `tools/grammar_check.yaml` - Editing
- `tools/cms_publish.yaml` - Publishing

### Use Case: Code Review Automation

**Workflow:** `workflows/code_review.yaml`
```yaml
stages:
  - analyze → test → security → approve
```

**Agents:**
- `agents/code_analyzer.yaml` - Static analysis
- `agents/test_reviewer.yaml` - Test coverage
- `agents/security_auditor.yaml` - Security scan

---

## Environment-Specific Configurations

### Development vs Production

Use environment-specific overrides:

```bash
configs/
├── agents/
│   ├── researcher.yaml         # Base config
│   ├── researcher.dev.yaml     # Dev overrides
│   └── researcher.prod.yaml    # Prod overrides
```

**Loading Priority:**
1. Base config: `researcher.yaml`
2. Environment override: `researcher.{ENV}.yaml`
3. Environment variables: `${VAR_NAME}`

---

## Configuration Validation

### YAML Schema Validation

Configurations are validated against JSON schemas:

```python
from src.compiler.config_loader import load_workflow_config

# Automatically validates against schema
config = load_workflow_config("workflows/my_workflow.yaml")
```

### Manual Validation

```bash
# Check YAML syntax
yamllint configs/workflows/my_workflow.yaml

# Validate against framework schema
python -m src.tools.validate_config configs/workflows/my_workflow.yaml
```

---

## Common Configuration Patterns

### Pattern 1: Agent Chaining

```yaml
# Sequential processing
stages:
  - agent: preprocessor → transformer → postprocessor
```

### Pattern 2: Parallel Processing

```yaml
# Concurrent execution (LangGraph)
parallel:
  - agent: reviewer_1
  - agent: reviewer_2
  - agent: reviewer_3
strategy: consensus  # or debate, merit-weighted
```

### Pattern 3: Conditional Branching

```yaml
stages:
  - name: validation
    next:
      - stage: approve
        condition: score > 0.8
      - stage: revise
        condition: score <= 0.8
```

---

## Troubleshooting

### Configuration Not Loading

**Problem:** YAML syntax error

**Solution:**
```bash
# Check syntax
yamllint configs/agents/my_agent.yaml

# Common issues:
# - Incorrect indentation (use 2 spaces, not tabs)
# - Missing colons
# - Unquoted strings with special characters
```

### Agent Not Found

**Problem:** Agent reference doesn't match filename

**Solution:**
```yaml
# Filename: agents/researcher.yaml
name: researcher  # Must match filename (without .yaml)
```

### Environment Variables Not Resolving

**Problem:** `${VAR_NAME}` not replaced

**Solution:**
```bash
# Ensure .env file exists
cp .env.example .env

# Add variable
echo "GITHUB_CLIENT_ID=your_value" >> .env
```

---

## Best Practices

1. **Version Control:** Commit all configs to git
2. **Secrets:** Use environment variables, never hardcode
3. **Documentation:** Add comments to complex configs
4. **Validation:** Run validation before committing
5. **Naming:** Follow naming conventions consistently
6. **Reusability:** Create reusable components (prompts, stages)
7. **Testing:** Test configurations in dev before production

---

## See Also

- [API Reference](../docs/API_REFERENCE.md) - Configuration API
- [Workflow Examples](../examples/) - Sample workflows
- [Architecture Guide](../docs/ARCHITECTURE.md) - System design

---

**Last Updated:** 2026-02-01
