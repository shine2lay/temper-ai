# Quick Start Guide

Get up and running with Temper AI in 5 minutes.

---

## What is This?

Temper AI is a self-improving autonomous agent system that can execute complete product lifecycles with minimal human intervention. It features:

- **Multi-agent collaboration** with parallel execution
- **Full observability** - every decision is traced and queryable
- **Configuration as code** - YAML-based workflow definitions
- **Pluggable LLM providers** - Ollama, OpenAI, Anthropic, vLLM
- **Swappable tools** - Calculator, WebScraper, FileWriter, and more

---

## Prerequisites

- **Python 3.11 or higher**
- **(Optional)** Ollama for local LLMs ([Install Ollama](https://ollama.ai))
- **(Optional)** PostgreSQL for production observability

---

## Installation (5 minutes)

### Step 1: Clone the Repository

```bash
git clone https://github.com/temper-ai/temper-ai.git
cd temper-ai
```

### Step 2: Install Dependencies

```bash
make setup   # installs uv deps, pre-commit, copies .env
```

Or manually with `uv`:

```bash
uv sync --extra dev --extra dashboard
```

This installs the framework in development mode with all dependencies.

### Step 3: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# For OpenAI (optional)
OPENAI_API_KEY=your_openai_api_key_here

# For Anthropic (optional)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# For Ollama (local - recommended for getting started)
OLLAMA_BASE_URL=http://localhost:11434
```

---

## Your First Workflow (2 minutes)

### Using Ollama (Local, Free)

1. **Start Ollama** (if not already running):
```bash
ollama serve
```

2. **Pull a model** (first time only):
```bash
ollama pull llama3.2:3b
```

3. **Start the server and run a workflow**:
```bash
uv run temper-ai serve --dev

# In another terminal:
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{"workflow_path": "configs/workflows/hello_world.yaml", "inputs": {"topic": "AI safety"}}'
```

You should see execution results in the API response and the dashboard at `http://localhost:8000`.

### Using OpenAI or Anthropic

1. **Set your API key** in `.env`:
```bash
OPENAI_API_KEY=sk-...
```

2. **Start the server and run a workflow via API**:
```bash
temper-ai serve --dev

# In another terminal:
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/simple_research.yaml", "inputs": {"query": "Research topic"}}'
```

---

## Run Example Workflows

The framework includes several pre-built example workflows. Start the server first:

```bash
temper-ai serve --dev
```

### Simple Research Workflow

Single-agent workflow for research tasks:

```bash
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/simple_research.yaml", "inputs": {"query": "Research Python typing benefits"}}'
```

### Multi-Agent Parallel Research

Run 3 agents in parallel with consensus synthesis:

```bash
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/parallel_research.yaml"}'
```

### Multi-Agent Debate

Run 3 agents in a multi-round debate:

```bash
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/debate_decision.yaml"}'
```

---

## Create Your Own Workflow

### Step 1: Define Agent Config

Create `configs/agents/my_agent.yaml`:

```yaml
agent:
  name: my_researcher
  description: Research agent for technical topics
  version: 1.0
  type: standard

  prompt:
    inline: |
      You are a technical research assistant.

      Query: {{ query }}

      Provide a comprehensive analysis.

  inference:
    provider: ollama
    model: llama3.2:3b
    base_url: http://localhost:11434
    temperature: 0.7
    max_tokens: 2048

  tools:
    - WebScraper
    - Calculator

  safety:
    max_tool_calls_per_execution: 5
```

### Step 2: Define Workflow Config

Create `configs/workflows/my_workflow.yaml`:

```yaml
workflow:
  name: my_research_workflow
  description: Custom research workflow
  version: 1.0

stages:
  - name: research
    type: agent
    agent_ref: my_researcher
    input_mapping:
      query: $input.topic

output_mapping:
  result: $stages.research.output
```

### Step 3: Run Your Workflow

```bash
temper-ai serve --dev

# In another terminal:
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/my_workflow.yaml", "inputs": {"topic": "AI safety"}}'
```

---

## Understanding the Output

When you run a workflow, you'll see:

```
🚀 Starting workflow: my_research_workflow
📊 Stage: research (agent: my_researcher)
🤖 Agent executing...
💬 LLM call: llama3.2:3b
🔧 Tool call: WebScraper(url="...")
✅ Tool result: [content]
📝 Agent output: [research findings]
✅ Workflow complete!
```

**Workflow Result:**
```json
{
  "result": "[Agent's research findings]",
  "stage_outputs": {
    "research": "[Detailed output]"
  },
  "metadata": {
    "total_tokens": 1234,
    "total_cost_usd": 0.002,
    "duration_seconds": 5.3
  }
}
```

---

## Next Steps

### Learn Core Concepts

- **[System Overview](./architecture/SYSTEM_OVERVIEW.md)** - Architecture diagrams
- **[Agent Interface](./interfaces/core/agent_interface.md)** - How agents work
- **[Tool Interface](./interfaces/core/tool_interface.md)** - How tools work
- **[Config Schemas](./interfaces/models/config_schema.md)** - Configuration reference

### Explore Multi-Agent Collaboration

- **[Multi-Agent Collaboration Guide](./features/collaboration/multi_agent_collaboration.md)** - Parallel execution, synthesis, conflict resolution
- **[Collaboration Strategies](./features/collaboration/collaboration_strategies.md)** - Consensus, debate, merit-weighted
- **[M3 Examples](../examples/guides/multi_agent_collaboration_examples.md)** - Complete multi-agent examples

### Advanced Topics

- **[Execution Engine Architecture](./features/execution/execution_engine_architecture.md)** - Engine abstraction layer
- **[Custom Engine Tutorial](./features/execution/custom_engine_guide.md)** - Build your own execution engine
- **[Observability](./interfaces/models/observability_models.md)** - Tracing and analytics

### Checkpoint and Resume Workflows

Save and resume long-running workflows:

```python
from temper_ai.compiler.checkpoint_manager import CheckpointManager, CheckpointStrategy
from temper_ai.compiler.checkpoint_backends import CheckpointNotFoundError
from temper_ai.compiler.domain_state import WorkflowDomainState

# Initialize checkpoint manager
manager = CheckpointManager(strategy=CheckpointStrategy.EVERY_STAGE)

workflow_id = "long-running-task-123"

# Try to resume from checkpoint
try:
    if manager.has_checkpoint(workflow_id):
        print("Resuming from checkpoint...")
        domain = manager.load_checkpoint(workflow_id)
        print(f"Resuming from stage: {domain.current_stage}")
    else:
        print("Starting new workflow...")
        domain = WorkflowDomainState(workflow_id=workflow_id, input="task data")
except CheckpointNotFoundError as e:
    print(f"Checkpoint load failed: {e}")
    print("Starting new workflow...")
    domain = WorkflowDomainState(workflow_id=workflow_id, input="task data")

# Execute workflow stages
for stage in ["research", "analysis", "synthesis"]:
    if stage in domain.stage_outputs:
        continue  # Skip completed stages

    # Execute stage...
    output = {"result": f"output from {stage}"}
    domain.set_stage_output(stage, output)

    # Save checkpoint (automatic with EVERY_STAGE strategy)
    checkpoint_id = manager.save_checkpoint(domain)
    print(f"Checkpoint saved: {checkpoint_id}")
```

**Configuration:**

```yaml
# Enable checkpointing in workflow config
name: my_workflow
checkpoint_strategy: every_stage  # or: periodic, manual, disabled
checkpoint_backend: file  # or: redis
checkpoint_dir: ./checkpoints
max_checkpoints: 10
```

See [API Reference - Checkpointing](./API_REFERENCE.md#checkpointing) for complete documentation.

### Run Tests

```bash
# Run all tests
pytest

# Run specific test suite
pytest tests/integration/ -v

# Run with coverage
pytest --cov=temper_ai tests/
```

---

## Common Issues & Solutions

### Issue: "Command not found: ollama"

**Solution:** Install Ollama from https://ollama.ai

### Issue: "Model not found: llama3.2:3b"

**Solution:** Pull the model:
```bash
ollama pull llama3.2:3b
```

### Issue: "OpenAI API key not found"

**Solution:** Set your API key in `.env`:
```bash
OPENAI_API_KEY=sk-your_key_here
```

### Issue: "ImportError: No module named 'src'"

**Solution:** Install in development mode:
```bash
uv sync --dev
```

### Issue: "Database connection error"

**Solution:** The framework uses SQLite by default. PostgreSQL is optional for production.

---

## Configuration Quick Reference

### LLM Providers

| Provider | Model Examples | Base URL |
|----------|---------------|----------|
| Ollama | llama3.2:3b, mistral | http://localhost:11434 |
| OpenAI | gpt-4, gpt-3.5-turbo | https://api.openai.com/v1 |
| Anthropic | claude-3-opus, claude-3-sonnet | https://api.anthropic.com/v1 |
| vLLM | (custom) | http://localhost:8000 |

### Available Tools

| Tool | Description | Use Cases |
|------|-------------|-----------|
| Calculator | Math expressions | Calculations, numerical analysis |
| WebScraper | Fetch web content | Research, data gathering |
| FileWriter | Write to files | Report generation, data export |

### Execution Modes

| Mode | Description | When to Use |
|------|-------------|-------------|
| Sequential | One agent at a time | Simple workflows, debugging |
| Parallel | Multiple agents concurrently | Research, consensus, speed |

### Collaboration Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| Consensus | Majority voting | Quick decisions, research |
| Debate | Multi-round argumentation | Complex decisions, analysis |
| Merit-Weighted | Expert-weighted voting | Technical decisions, trust |

---

## Example Use Cases

### 1. Research Assistant

**Use Case:** Gather information on a technical topic

**Workflow:** Single agent with WebScraper tool

```bash
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/simple_research.yaml", "inputs": {"query": "Research GraphQL vs REST APIs"}}'
```

### 2. Multi-Agent Decision

**Use Case:** Make a complex technical decision

**Workflow:** Multi-agent debate with convergence

```bash
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/quick_decision_demo.yaml", "inputs": {"question": "Should we use microservices?"}}'
```

**Result:** High-confidence decision with reasoning

---

## Getting Help

- **Documentation:** Browse `/docs` for detailed guides
- **Examples:** Check `/examples` for working code
- **Issues:** Report bugs on GitHub
- **Tests:** Run `pytest -v` to see working examples

---

## What's Next?

You've successfully installed and run Temper AI! Here's what to explore next:

1. **Create custom agents** with different LLM providers
2. **Experiment with multi-agent workflows** for parallel execution
3. **Build custom tools** for domain-specific tasks
4. **Integrate observability** to track and analyze agent behavior
5. **Deploy to production** with safety policies and monitoring

Happy building! 🚀
