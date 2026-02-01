# Examples Directory

This directory contains demo scripts and examples for the Meta-Autonomous Framework.

## Prerequisites

1. **Install dependencies:**
   ```bash
   poetry install
   ```

2. **Start Ollama (required for LLM execution):**
   ```bash
   ollama serve
   ```

3. **Pull a model (recommended):**
   ```bash
   ollama pull llama3.2:3b
   ```

## Scripts

### 1. Run Workflow (`run_workflow.py`)

Execute a workflow configuration with real LLM and tool execution.

**Basic Usage:**
```bash
python examples/run_workflow.py configs/workflows/simple_research.yaml
```

**With Custom Prompt:**
```bash
python examples/run_workflow.py simple_research --prompt "Research TypeScript benefits"
```

**With Depth Control:**
```bash
python examples/run_workflow.py simple_research --depth deep
```

**Verbose Mode:**
```bash
python examples/run_workflow.py simple_research --verbose
```

**Export Results:**
```bash
python examples/run_workflow.py simple_research --output results.json
```

**Custom Database:**
```bash
python examples/run_workflow.py simple_research --db my_execution.db
```

**Arguments:**
- `workflow` - Workflow config file path or workflow name (required)
- `--prompt`, `--topic` - Research topic or prompt (default: "Benefits of Python typing")
- `--depth` - Analysis depth: surface|medium|deep (default: surface)
- `--verbose`, `-v` - Show verbose output
- `--output`, `-o` - Save results to JSON file
- `--db` - Database path (default: workflow_execution.db)

**Features:**
- Real-time streaming console visualization
- Comprehensive error checking (Ollama, dependencies, configs)
- Execution metrics display (tokens, cost, duration)
- Rich console output with panels and tables
- Interrupt handling (Ctrl+C)
- Query execution data from database

---

### 2. Query Trace (`query_trace.py`)

Query and display workflow execution traces from the observability database.

**Show Latest Execution:**
```bash
python examples/query_trace.py
```

**Show Specific Execution:**
```bash
python examples/query_trace.py abc123def456
```

**List Recent Executions:**
```bash
python examples/query_trace.py --list 10
```

**Export to JSON:**
```bash
python examples/query_trace.py --json trace.json
```

**Export Specific Execution:**
```bash
python examples/query_trace.py abc123def --json trace.json
```

**Summary Only (No Tree):**
```bash
python examples/query_trace.py --summary
```

**Custom Database:**
```bash
python examples/query_trace.py --db my_execution.db
```

**Arguments:**
- `workflow_id` - Workflow execution ID (optional, defaults to latest)
- `--list`, `-l` N - List last N executions
- `--json`, `-j` FILE - Export trace to JSON file
- `--db` - Database path (default: workflow_execution.db)
- `--summary`, `-s` - Show summary only (no tree)

**Output:**
- Summary table with metrics (tokens, cost, duration, status)
- Tree view of execution hierarchy (workflow → stages → agents → LLM calls + tools)
- JSON export of complete trace

---

### 3. Milestone 1 Demo (`milestone1_demo.py`)

Demonstrates Milestone 1 components (configuration and observability).

**Run Demo:**
```bash
python examples/milestone1_demo.py
```

**Features:**
- Configuration loading and validation
- Observability database operations
- Console visualization
- All M1 components integrated

---

## Guides

Comprehensive guides and tutorials for learning the framework are available in the [`guides/`](./guides/) directory.

**Quick Navigation:**
- **[E2E YAML Workflow Guide](./guides/E2E_YAML_WORKFLOW_GUIDE.md)** - Complete guide to creating workflows (619 lines)
- **[Multi-Agent Collaboration Examples](./guides/multi_agent_collaboration_examples.md)** - M3 collaboration features (235 lines)
- **[M3 YAML Configs Guide](./guides/M3_YAML_CONFIGS_GUIDE.md)** - Advanced M3 configuration (791 lines)
- **[LLM Debate Trace Analysis](./guides/LLM_DEBATE_TRACE_ANALYSIS.md)** - Analyzing debate traces (521 lines)
- **[M3 Demo Enhancements](./guides/M3_DEMO_ENHANCEMENTS.md)** - Demo improvements (294 lines)

**By Experience Level:**
- **Beginner:** Start with [E2E YAML Workflow Guide](./guides/E2E_YAML_WORKFLOW_GUIDE.md)
- **Intermediate:** Read [M3 YAML Configs Guide](./guides/M3_YAML_CONFIGS_GUIDE.md)
- **Advanced:** See [M3 Demo Enhancements](./guides/M3_DEMO_ENHANCEMENTS.md)

See the [**guides README**](./guides/README.md) for full guide descriptions, quick reference by use case, and contribution guidelines.

---

## Example Workflows

### Simple Research Workflow

Located at: `configs/workflows/simple_research.yaml`

**Purpose:** Basic research workflow that takes a topic and produces insights.

**Usage:**
```bash
python examples/run_workflow.py simple_research --prompt "Research Rust programming language"
```

**What it does:**
1. Loads research stage configuration
2. Creates researcher agent with LLM (Ollama)
3. Executes research with optional tool usage
4. Tracks execution in observability database
5. Returns research findings and recommendations

---

## Database

The observability database stores complete execution traces:

**Location:** `workflow_execution.db` (default)

**Schema:**
```
WorkflowExecution (workflow-level metrics)
  ├── StageExecution (stage-level metrics)
  │   ├── AgentExecution (agent-level metrics)
  │   │   ├── LLMCall (prompt, response, tokens, cost)
  │   │   └── ToolExecution (tool name, params, result, duration)
```

**Query with SQL:**
```bash
sqlite3 workflow_execution.db "SELECT * FROM workflow_executions ORDER BY start_time DESC LIMIT 5;"
```

**Query with Python:**
```python
from src.observability.database import get_session
from src.observability.models import WorkflowExecution

with get_session() as session:
    executions = session.query(WorkflowExecution).all()
    for exec in executions:
        print(f"{exec.workflow_name}: {exec.total_tokens} tokens, ${exec.total_cost_usd:.6f}")
```

---

## Troubleshooting

### "Ollama not detected"

**Problem:** Ollama server is not running.

**Solution:**
```bash
ollama serve
```

### "M2 components not ready"

**Problem:** Required components (StandardAgent, AgentFactory, LangGraphCompiler) are not yet implemented.

**Status:** These are being implemented in tasks m2-04, m2-04b, m2-05, m2-06.

**Workaround:** Wait for these tasks to complete, or contribute to their implementation!

### "No executions found in database"

**Problem:** Database is empty (no workflows have been executed yet).

**Solution:** Run a workflow first:
```bash
python examples/run_workflow.py simple_research
```

### "Model not found"

**Problem:** Ollama model is not available.

**Solution:**
```bash
ollama pull llama3.2:3b
```

Available models:
- `llama3.2:3b` - Fast, good quality (recommended)
- `llama3.1:8b` - Larger, higher quality
- `mistral:7b` - Alternative fast model
- `codellama:7b` - For code-related tasks

### Database locked

**Problem:** SQLite database is locked by another process.

**Diagnosis:**
```bash
# Check which process has the database open
lsof .claude-coord/coordination.db

# Or on systems without lsof
fuser .claude-coord/coordination.db
```

**Solutions:**

1. **Kill the locking process:**
```bash
# Find process ID
PID=$(lsof -t .claude-coord/coordination.db)

# Kill gracefully
kill $PID

# Force kill if needed
kill -9 $PID
```

2. **Use different database path:**
```bash
# Specify custom database location
export COORD_DB_PATH=/tmp/my-coordination.db
coord register $CLAUDE_AGENT_ID $$
```

3. **Enable WAL mode (recommended):**
```bash
# SQLite WAL mode allows concurrent reads
sqlite3 .claude-coord/coordination.db "PRAGMA journal_mode=WAL;"
```

4. **For production, use PostgreSQL:**
```bash
# Set PostgreSQL connection
export OBSERVABILITY_BACKEND=postgres
export POSTGRES_URL=postgresql://user:pass@localhost/dbname
```

### Test paths

**Problem:** Tests can't find modules or fixtures.

**Specific examples:**
```bash
# Run tests from project root (not from tests/ directory)
cd /home/shinelay/meta-autonomous-framework
pytest tests/test_agents/

# Run specific test file
pytest tests/test_compiler/test_workflow_executor.py

# Run specific test
pytest tests/test_agents/test_standard_agent.py::test_agent_creation

# Run with verbose output to see import errors
pytest -vv tests/
```

### Database path clarification

**Project database locations:**
```bash
# Coordination database (multi-agent)
.claude-coord/coordination.db

# Observability database (metrics, traces)
observability.db  # Or configured via OBSERVABILITY_BACKEND

# Test databases (temporary)
tests/test_data/*.db
```

---

## Output Examples

### Workflow Execution Output

```
╭───────────────────────────────────╮
│ Meta-Autonomous Framework         │
│ Workflow Execution Demo           │
╰───────────────────────────────────╯

Initializing...
✓ Registered 3 tools
Loading workflow: simple_research
✓ Workflow loaded
Topic: Benefits of Python typing
Depth: surface

Starting workflow execution...

[Real-time streaming console shows stages, agents, LLM calls, tools...]

✓ Workflow completed successfully!

╭─ Execution Summary ────────────────────╮
│ Workflow      simple_research          │
│ Status        COMPLETED                │
│ Duration      12.45s                   │
│ LLM Calls     3                        │
│ Tool Calls    1                        │
│ Total Tokens  2,847                    │
│ Cost          $0.000142                │
╰────────────────────────────────────────╯
```

### Query Trace Output

```
╭─ Workflow Execution Trace ─────────────────────╮

╭─ Summary Metrics ──────────────────────────────╮
│ Workflow ID   abc123def456                     │
│ Workflow Name simple_research                  │
│ Status        COMPLETED                        │
│ Duration      12.45s                           │
│ Total Tokens  2,847                            │
│ Total Cost    $0.000142                        │
╰────────────────────────────────────────────────╯

Workflow: simple_research COMPLETED (12.45s)
└── Stage: research COMPLETED (12.23s)
    └── Agent: researcher COMPLETED (12.15s) 2847 tokens, $0.000142
        ├── LLM Calls
        │   ├── ollama/llama3.2:3b 1423 tokens (2547ms) $0.000071
        │   ├── ollama/llama3.2:3b 892 tokens (1823ms) $0.000045
        │   └── ollama/llama3.2:3b 532 tokens (1012ms) $0.000026
        └── Tool Executions
            └── Calculator (0.002s)
```

---

## Development

### Adding New Examples

1. Create new script in `examples/` directory
2. Follow naming convention: `snake_case.py`
3. Include help text and examples
4. Add error handling
5. Update this README

### Running in Development Mode

```bash
# With virtual environment
source venv/bin/activate
python examples/run_workflow.py simple_research --verbose

# With poetry
poetry run python examples/run_workflow.py simple_research --verbose
```

---

## Next Steps

Once M2 is complete, try:

1. **Run your first workflow:**
   ```bash
   python examples/run_workflow.py simple_research --prompt "Your topic here"
   ```

2. **Query the execution trace:**
   ```bash
   python examples/query_trace.py
   ```

3. **Export trace data:**
   ```bash
   python examples/query_trace.py --json my_trace.json
   ```

4. **Create your own workflow:**
   - Copy `configs/workflows/simple_research.yaml`
   - Modify stages and agents
   - Run with `run_workflow.py`

5. **Build custom tools:**
   - See `src/tools/` for examples
   - Implement `BaseTool` interface
   - Register in tool registry

---

## References

- **Codebase Reference:** `docs/CODEBASE_REFERENCE.md`
- **M2 Completion Report:** `docs/milestones/milestone2_completion.md`
- **Configuration Guide:** `configs/README.md` (if exists)
- **Tool Development:** `src/tools/README.md` (if exists)

---

**Questions or Issues?**

Open an issue in the project repository or consult the documentation in `docs/`.
