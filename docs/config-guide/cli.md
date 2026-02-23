# CLI Commands

The `temper-ai` CLI exposes a single `serve` command that starts the HTTP API server and React dashboard.

**Source:** `temper_ai/interfaces/cli/main.py`

## Commands

### `temper-ai serve` — Start the Server

```bash
temper-ai serve [options]
```

Starts the Temper AI HTTP API server. All workflow operations (run, validate, list) are done via the REST API.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8420` | Listen port |
| `--config-root` | `configs` | Config directory root |
| `--db` | — | Database URL override |
| `--workers` | `4` | Max concurrent workflows |
| `--reload` | off | Auto-reload on code changes |
| `--dev` | off | Dev mode: disable auth, permissive CORS |
| `--mcp` | off | Also start MCP stdio server |

**Examples:**

```bash
# Dev mode (dashboard + API, no auth)
temper-ai serve --dev

# Dev mode with MCP
temper-ai serve --dev --mcp

# Custom port
temper-ai serve --dev --port 9000
```

---

## Key API Endpoints

Once the server is running, use the HTTP API:

```bash
curl localhost:8420/api/health                    # liveness check
curl -X POST localhost:8420/api/runs -d '{"workflow":"workflows/research.yaml"}'
curl -X POST localhost:8420/api/validate -d '{"workflow":"workflows/research.yaml"}'
curl localhost:8420/api/workflows/available        # list workflow configs
```

---

## Available Demo Workflows

| Workflow | Input File | Description |
|----------|-----------|-------------|
| `configs/workflows/quick_decision_demo.yaml` | `examples/demo_input.yaml` | Fast 3-agent decision making |
| `configs/workflows/simple_research.yaml` | `examples/research_input.yaml` | Single-agent research |
| `configs/workflows/llm_debate_demo.yaml` | `examples/debate_demo_input.yaml` | Multi-round debate |
| `configs/workflows/technical_problem_solving.yaml` | `examples/technical_problem_demo_input.yaml` | 4-phase problem solving |
| `configs/workflows/collaborative_dialogue_demo.yaml` | `examples/dialogue_demo_input.yaml` | Multi-round collaborative dialogue |
| `configs/workflows/multi_agent_research.yaml` | `examples/market_research_input.yaml` | Parallel multi-agent research |
| `configs/workflows/vcs_suggestion.yaml` | `examples/vcs_suggestion_input.yaml` | Vision-driven code generation pipeline |
