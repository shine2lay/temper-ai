# Temper AI

A multi-agent workflow framework. Define agents and stages in YAML, and the framework orchestrates them with LLMs, tools, observability, and safety policies.

---

## Quickstart

### 1. Local dev (fastest)

```bash
git clone <repo> && cd temper-ai
make setup          # installs uv deps, pre-commit, copies .env
# Edit .env if needed — defaults to Ollama (install from ollama.com)
make test           # verify installation

uv run temper-ai serve --dev   # starts server at http://localhost:8420

# Run a workflow via API
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/vcs_suggestion.yaml", "inputs": {"description": "Fix login bug"}}'
```

### 2. Docker Compose (full stack with Postgres)

```bash
cp .env.example .env    # add LLM API keys
docker compose up -d    # starts postgres + server at localhost:8420
```

### 3. Kubernetes

```bash
helm install temper-ai ./helm/temper-ai \
  --set postgresql.auth.password=<secret>
```

---

## What it does

- **YAML-defined workflows** — agents, stages, and their connections are plain YAML files; no code required to compose a pipeline
- **LLM orchestration** — multi-provider support (Ollama, OpenAI, Anthropic, vLLM); provider is set per-agent in config
- **Built-in tools** — Bash, HTTP, JSON, FileWriter, CodeExecutor, Git, WebScraper; tools are declared in agent configs
- **Multi-agent strategies** — sequential, parallel, consensus, debate, and merit-weighted execution
- **Safety policies** — composable action policies, approval workflows, emergency stop, audit trail
- **Observability** — every LLM call and stage transition is traced; OTEL export optional
- **DSPy optimization** — compile better prompts from execution history via `POST /api/optimization/compile`
- **Plugin imports** — ingest agents from CrewAI, LangGraph, OpenAI Agents, and AutoGen via `POST /api/plugins/import`
- **Dashboard** — React UI served at port 8420 (`temper-ai serve --dev`)

---

## Project structure

```
temper_ai/              # Python package (source root)
  workflow/             # LangGraph compiler/engine, config loader, DAG/node builders
  stage/                # Stage executors: sequential, parallel, adaptive
  agent/                # Agent implementations, LLM providers, strategies
  llm/                  # LLM service, cache, prompts
  tools/                # Tool registry and built-in tools
  safety/               # Action policies, security checks
  observability/        # Execution tracker, metrics, OTEL export
  interfaces/           # CLI (main.py), FastAPI dashboard, HTTP API server
  optimization/         # DSPy prompt optimization
  plugins/              # External agent adapters (CrewAI, LangGraph, AutoGen)
  auth/                 # API key auth, tenant scoping, config sync
  storage/              # Database models and schemas (SQLModel + SQLAlchemy)
  registry/             # Persistent agent registry
  events/               # Event bus and subscriptions
  mcp/                  # Model Context Protocol client + server
  lifecycle/            # Lifecycle adaptation and rollback
  goals/                # Agent goal proposal and review
  portfolio/            # Workflow portfolio optimization
  memory/               # Agent memory and knowledge graph
  learning/             # Workflow learning and auto-tuning
  autonomy/             # Autonomous operation loop
  experimentation/      # A/B experimentation framework

configs/
  agents/               # Agent YAML definitions
  stages/               # Stage YAML definitions
  workflows/            # Workflow YAML definitions

tests/                  # pytest test suite
frontend/               # React + Vite + Tailwind dashboard source
helm/temper-ai/         # Helm chart for Kubernetes deployment
docs/                   # Guides and architecture docs
```

---

## Configuration

Workflows, stages, and agents are defined in `configs/`. Runtime secrets (LLM API keys, database URL) go in `.env`:

```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
TEMPER_DATABASE_URL=postgresql://...   # defaults to SQLite for local dev
```

A minimal agent config looks like:

```yaml
agent:
  name: researcher
  model: ollama/llama3.2
  system_prompt: "You are a research assistant."
  tools:
    - WebScraper
    - Bash
```

See `configs/agents/` for working examples and `docs/CONFIGURATION.md` for the full schema reference.

---

## Development

### Make targets

| Target | Description |
|--------|-------------|
| `make setup` | Bootstrap: uv sync, pre-commit, copy `.env` |
| `make test` | Core test suite (parallel, pytest-xdist) |
| `make test-all` | Full test suite |
| `make lint` | ruff + black check |
| `make format` | Auto-fix formatting (black + ruff --fix) |
| `make type` | mypy type checking |
| `make check` | Full quality gate: lint + type + test + quality |
| `make coverage` | Tests with coverage report |
| `make security` | Bandit security scan |
| `make help` | List all targets |

### Running tests

```bash
make test                   # core modules, parallel
make test-all               # everything
```

Tests run inside the uv-managed environment (pytest-xdist uses `-n auto`).

### Frontend

The dashboard frontend lives in `frontend/`. Built assets are committed to `temper_ai/interfaces/dashboard/react-dist/` so Python-only installs include the UI.

To rebuild after frontend changes:

```bash
cd frontend
npm install
npm run build
```

### CLI and API

The only CLI command is `temper-ai serve`. All workflow operations use the HTTP API:

```bash
temper-ai serve --dev                             # dashboard + API at localhost:8420
temper-ai serve --dev --mcp                       # also start MCP stdio server

# Key API endpoints
curl localhost:8420/api/health                    # liveness check
curl -X POST localhost:8420/api/runs -d '{"workflow":"workflows/research.yaml"}'
curl -X POST localhost:8420/api/validate -d '{"workflow":"workflows/research.yaml"}'
curl localhost:8420/api/workflows/available        # list workflow configs
curl localhost:8420/api/checkpoints                # list checkpoints
curl localhost:8420/api/events                     # list events
curl -X POST localhost:8420/api/optimization/compile  # DSPy prompt optimization
curl -X POST localhost:8420/api/visualize          # DAG visualization
curl localhost:8420/api/plugins                    # list plugins
curl localhost:8420/api/templates                   # list templates
```

---

## Deployment

Docker and Kubernetes targets are covered in the Helm chart (`helm/temper-ai/`) and `docker-compose.yml`.

The Dockerfile has a single `server` build target. Docker Compose starts Postgres (pgvector) alongside the server. The Helm chart (`helm/temper-ai/`) supports the same topology for Kubernetes.

---

## Optional dependency groups

Install only what you need:

```bash
pip install -e ".[dev]"            # development tools (pytest, black, ruff, mypy)
pip install -e ".[dashboard]"      # FastAPI + uvicorn for the dashboard
pip install -e ".[llm-providers]"  # OpenAI + Anthropic SDKs
pip install -e ".[dspy]"           # DSPy prompt optimization
pip install -e ".[mcp]"            # Model Context Protocol support
pip install -e ".[otel]"           # OpenTelemetry export
pip install -e ".[crewai]"         # CrewAI plugin adapter
pip install -e ".[autogen]"        # AutoGen plugin adapter
pip install -e ".[openai_agents]"  # OpenAI Agents plugin adapter
```

---

## License

Apache-2.0. See [LICENSE](./LICENSE) for details.
