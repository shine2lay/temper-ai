# Examples Directory

This directory contains example YAML inputs and guides for the Temper AI.

## Prerequisites

1. **Install dependencies:**
   ```bash
   uv sync --dev
   ```

2. **Start the server:**
   ```bash
   uv run temper-ai serve --dev
   ```

3. **Start Ollama (required for LLM execution):**
   ```bash
   ollama serve
   ollama pull llama3.2:3b
   ```

## Running Workflows (HTTP API)

Execute workflows via the REST API (the canonical execution path).

```bash
# Run a workflow
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{"workflow_path": "configs/workflows/hello_world.yaml", "inputs": {"topic": "AI safety"}}'

# With input file
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d "$(python -c "import yaml,json; d=yaml.safe_load(open('examples/vcs_suggestion_input.yaml')); print(json.dumps({'workflow_path':'configs/workflows/vcs_suggestion.yaml','inputs':d}))")"

# List available workflows
curl http://localhost:8000/api/workflows/available

# Check run status
curl http://localhost:8000/api/runs/{run_id}

# Validate a config
curl -X POST http://localhost:8000/api/validate \
  -H "Content-Type: application/json" \
  -d '{"workflow_path": "configs/workflows/hello_world.yaml"}'
```

See `docs/config-guide/cli.md` for full API reference.

---

## Example Input Files

| File | Workflow | Description |
|------|----------|-------------|
| `hello_world_input.yaml` | `hello_world` | Minimal example input |
| `vcs_suggestion_input.yaml` | `vcs_suggestion` | Code suggestion workflow input |

---

---

## Example Workflows

### Hello World Workflow

Located at: `configs/workflows/hello_world.yaml`

**Purpose:** Minimal workflow demonstrating the agent -> stage -> workflow hierarchy.

```bash
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{"workflow_path": "configs/workflows/hello_world.yaml", "inputs": {"topic": "renewable energy"}}'
```

### VCS Suggestion Workflow

Located at: `configs/workflows/vcs_suggestion.yaml`

**Purpose:** Multi-stage code suggestion pipeline with quality gates and looping.

```bash
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d "$(python -c "import yaml,json; d=yaml.safe_load(open('examples/vcs_suggestion_input.yaml')); print(json.dumps({'workflow_path':'configs/workflows/vcs_suggestion.yaml','inputs':d}))")"
```

---

## Observability

Execution traces are stored in the observability database and viewable in the dashboard at `http://localhost:8000` (when running with `--dev`).

**Query traces with SQL:**
```bash
sqlite3 workflow_execution.db "SELECT * FROM workflow_executions ORDER BY start_time DESC LIMIT 5;"
```

**Query traces with Python:**
```python
from temper_ai.storage.database.manager import get_session
from temper_ai.storage.database.models import WorkflowExecution

with get_session() as session:
    executions = session.query(WorkflowExecution).all()
    for exec in executions:
        print(f"{exec.workflow_name}: {exec.total_tokens} tokens, ${exec.total_cost_usd:.6f}")
```

---

## References

- **Configuration Guide:** `docs/CONFIGURATION.md`
- **YAML Configs Guide:** `configs/README.md`
- **Architecture:** `docs/architecture/`
