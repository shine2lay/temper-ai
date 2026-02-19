# Temper AI Server: Deployment Model

## Context

Temper AI is currently a CLI dev tool (`temper-ai run workflow.yaml`). For any real product built on Temper AI, you need a way to trigger workflows programmatically, run them in isolated workspaces, and stream results in real-time. This document specifies the Temper AI Server - the deployable runtime that makes Temper AI usable as infrastructure.

## Problem

Without a deployment model:
- Can't trigger workflows from an API (only CLI)
- Can't build products on top of Temper AI (no programmatic interface)
- Can't run workflows in CI/CD pipelines
- No workspace isolation (agents can access anything on the system)
- No way to run multiple workflows in parallel safely
- Every user has to figure out their own deployment

## What Temper AI Server Does

A deployable runtime that:
1. Accepts workflow run requests via API
2. Executes them in isolated workspaces
3. Streams events in real-time
4. Stores results and execution history

```bash
temper-ai serve --port 8080 --workspace-root /var/temper-ai/workspaces
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│               Temper AI Server                       │
│                                                     │
│  API Layer (FastAPI)                                │
│  ┌───────────────────────────────────────────────┐  │
│  │  POST /api/runs          (trigger workflow)   │  │
│  │  GET  /api/runs          (list runs)          │  │
│  │  GET  /api/runs/:id      (run status/result)  │  │
│  │  GET  /api/runs/:id/events (pipeline events)  │  │
│  │  WS   /ws/runs/:id      (live event stream)   │  │
│  │  POST /api/validate      (validate config)    │  │
│  │  GET  /api/workflows     (list workflows)     │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  Run Manager                                        │
│  ┌───────────────────────────────────────────────┐  │
│  │  - Accepts run requests                       │  │
│  │  - Creates isolated workspace per run         │  │
│  │  - Spawns workflow execution (container or    │  │
│  │    subprocess with path restrictions)         │  │
│  │  - Collects events from running workflows     │  │
│  │  - Stores results in DB                       │  │
│  │  - Manages concurrency (queue / pool)         │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  Event Store (SQLite / PostgreSQL)                  │
│  ┌───────────────────────────────────────────────┐  │
│  │  runs:   id, workflow, status, inputs, result │  │
│  │  events: id, run_id, agent, stage, content    │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
└─────────────────────┬───────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ Workspace│ │ Workspace│ │ Workspace│
   │  Run #1  │ │  Run #2  │ │  Run #3  │
   │          │ │          │ │          │
   │ /src     │ │ /src     │ │ /src     │
   │ /VISION  │ │ /VISION  │ │ /VISION  │
   │ /.git    │ │ /.git    │ │ /.git    │
   └──────────┘ └──────────┘ └──────────┘
   (isolated)   (isolated)   (isolated)
```

## Workspace Isolation

Each workflow run gets its own workspace. Agents can only access files within that workspace.

### Isolation Levels

| Level | Mechanism | Security | Startup | Complexity |
|-------|-----------|----------|---------|------------|
| **L1: Path restriction** | Check file paths are under workspace root | Basic | Instant | Low |
| **L2: Subprocess + chroot** | Run in subprocess with restricted paths | Medium | ~100ms | Medium |
| **L3: Container** | Docker container with mounted workspace volume | Strong | ~1-2s | High |

**Recommendation:** Start with L1 for development, L3 for production.

### Workspace Lifecycle

```
1. Run request comes in
2. Create workspace directory: /var/temper-ai/workspaces/{run_id}/
3. Clone/copy project files into workspace (or mount if persistent)
4. Execute workflow with workspace as root
5. Collect results
6. Cleanup workspace (or keep for debugging)
```

### Container Isolation (L3)

```bash
docker run --rm \
  -v /projects/my-product:/workspace:rw \
  -v /path/to/temper-ai/configs:/configs:ro \
  --network=host \
  --memory=2g \
  --cpus=1 \
  temper-ai-runner \
  --workflow suggestion_triage \
  --workspace /workspace \
  --input '{"suggestion_text": "Add dark mode"}' \
  --events-to stdout
```

The container:
- Mounts workspace as read-write (agents operate here)
- Mounts Temper AI configs as read-only (workflow definitions)
- Has network access for LLM API calls
- Has resource limits (memory, CPU)
- Streams events to stdout (collected by Temper AI Server)

## API Design

### POST /api/runs
Trigger a new workflow run.

```json
Request: {
  "workflow": "suggestion_triage",
  "inputs": {
    "suggestion_text": "Add dark mode toggle to the header"
  },
  "workspace": "/projects/vibe-coding-squad",
  "config": {
    "isolation": "container",
    "timeout_seconds": 600,
    "callback_url": "https://myapp.com/webhook/run-complete"
  }
}

Response: {
  "run_id": "run_abc123",
  "status": "queued",
  "created_at": "2026-02-12T10:00:00Z"
}
```

### GET /api/runs/:id
Get run status and result.

```json
Response: {
  "run_id": "run_abc123",
  "workflow": "suggestion_triage",
  "status": "running",
  "current_stage": "vision_alignment",
  "progress": {
    "stages_completed": 1,
    "stages_total": 5
  },
  "started_at": "2026-02-12T10:00:01Z",
  "result": null
}
```

Status values: `queued → running → completed | failed | cancelled`

### GET /api/runs/:id/events
Get all pipeline events for a run.

```json
Response: {
  "events": [
    {
      "id": "evt_001",
      "stage": "classify",
      "agent": "classifier",
      "type": "output",
      "content": "Classification: feature request. Category: UI change.",
      "timestamp": "2026-02-12T10:00:05Z"
    },
    {
      "id": "evt_002",
      "stage": "vision_alignment",
      "agent": "vision_checker",
      "type": "started",
      "content": null,
      "timestamp": "2026-02-12T10:00:06Z"
    }
  ]
}
```

### WebSocket /ws/runs/:id
Live stream of events as they happen.

```json
// Server pushes events as they occur:
{"type": "stage_started", "stage": "classify", "timestamp": "..."}
{"type": "agent_output", "stage": "classify", "agent": "classifier", "content": "...", "timestamp": "..."}
{"type": "stage_completed", "stage": "classify", "status": "success", "timestamp": "..."}
{"type": "stage_started", "stage": "vision_alignment", "timestamp": "..."}
// ...
{"type": "run_completed", "status": "completed", "result": {...}}
```

### POST /api/runs/:id/cancel
Cancel a running workflow.

### GET /api/workflows
List available workflows.

```json
Response: {
  "workflows": [
    {"name": "suggestion_triage", "description": "Triage and build user suggestions", "stages": 5},
    {"name": "code_review", "description": "Multi-agent code review", "stages": 3}
  ]
}
```

### POST /api/validate
Validate a workflow config without running it.

## Data Model

### Run
```
id: string (run_abc123)
workflow: string (workflow name or path)
status: enum (queued, running, completed, failed, cancelled)
inputs: JSON
result: JSON (null until completed)
workspace_path: string
current_stage: string (null if not running)
stages_completed: int
stages_total: int
created_at: timestamp
started_at: timestamp (null if queued)
completed_at: timestamp (null if not done)
error: string (null if no error)
```

### RunEvent
```
id: string
run_id: FK → Run
stage: string
agent: string
event_type: enum (stage_started, agent_output, stage_completed, stage_failed, run_completed)
content: text
timestamp: timestamp
```

## Concurrency Model

### Option A: Thread Pool (simple, v1)
- Fixed pool of worker threads (e.g., 4)
- Each thread runs one workflow at a time
- Queue for overflow
- Good for: single machine, moderate load

### Option B: Container Pool (production)
- Temper AI Server manages a pool of Docker containers
- Each run gets its own container
- Containers created on demand, destroyed after completion
- Good for: isolation, resource control, scaling

### Option C: External Queue (scale)
- Redis/RabbitMQ job queue
- Separate worker processes pull and execute
- Horizontal scaling by adding workers
- Good for: high volume, distributed deployment

**Recommendation:** Start with Option A, design the interface so B/C are drop-in replacements.

## Event Streaming

How events get from a running workflow to the API/WebSocket.

### Current State
- `ExecutionTracker` records events to SQLite
- `ObservabilityEventBus` exists for real-time events (used by dashboard)
- No mechanism for external consumers

### What's Needed
A callback mechanism that fires when agents produce output:

```python
class WorkflowRunner:
    async def run(
        self,
        workflow: str,
        inputs: dict,
        workspace: str,
        on_event: Callable[[RunEvent], None] = None,
    ) -> RunResult:
        # ... setup ...
        # Each time an agent produces output:
        #   on_event(RunEvent(stage="classify", agent="classifier", content="..."))
        # ... execute ...
```

The `on_event` callback is what connects the Temper AI runtime to the server's event store and WebSocket broadcaster.

### Implementation Path
1. Add `on_event` callback support to `WorkflowRunner`
2. In the sequential/parallel executors, fire callbacks after each agent completes
3. Temper AI Server's run manager wires `on_event` to its event store + WebSocket

## Configuration

### Server Config (temper-ai-server.yaml)

```yaml
server:
  host: 0.0.0.0
  port: 8080

workspaces:
  root: /var/temper-ai/workspaces
  cleanup_after_hours: 24
  max_concurrent_runs: 4

isolation:
  level: container  # path | subprocess | container
  container:
    image: temper-ai-runner:latest
    memory_limit: 2g
    cpu_limit: 1
    network: host  # for LLM API access
    timeout: 600

database:
  url: sqlite:///temper-ai-server.db  # or postgresql://...

llm:
  # LLM config inherited by all runs (or overridden per workflow)
  default_provider: vllm
  default_base_url: http://localhost:8000
```

### Per-Workspace Config

Each workspace can have a `.temper-ai/config.yaml`:

```yaml
# Project-specific Temper AI config
workspace:
  name: vibe-coding-squad
  vision_doc: VISION.md

  # What agents can access
  allowed_paths:
    - temper_ai/
    - public/
    - VISION.md

  # What agents cannot touch
  denied_paths:
    - .env
    - secrets/
    - node_modules/
```

## CLI Extension

```bash
# Start the server
temper-ai serve --port 8080

# Trigger a run from CLI (calls the server API)
temper-ai trigger suggestion_triage \
  --workspace /projects/vibe-coding-squad \
  --input suggestion_text="Add dark mode"

# Check run status
temper-ai status run_abc123

# Stream events
temper-ai logs run_abc123 --follow

# List runs
temper-ai runs --status running
```

## Integration with The Vibe Coding Squad

With Temper AI Server, The Vibe Coding Squad becomes a thin client:

```
┌──────────────────────┐         ┌─────────────────────┐
│  VCS Web App          │  HTTP   │  Temper AI Server     │
│                       │────────▶│                      │
│  POST /suggestions    │         │  POST /api/runs      │
│    → calls Server     │         │    → spawns workflow  │
│                       │◀────────│    → streams events   │
│  WS /ws/suggestions   │  WS     │  WS /ws/runs/:id     │
│    ← forwards events  │         │    ← pipeline events  │
└──────────────────────┘         └─────────────────────┘
         │                                  │
         ▼                                  ▼
   ┌────────────┐                  ┌──────────────────┐
   │ VCS DB      │                  │ Workspace         │
   │ suggestions │                  │ /projects/vcs     │
   │ pipeline    │                  │   temper_ai/            │
   │ events      │                  │   VISION.md       │
   └────────────┘                  └──────────────────┘
```

## Build Order

### Phase 1: WorkflowRunner (library API)
- Extract CLI workflow execution into a `WorkflowRunner` class

- Support `run(workflow, inputs, workspace)` as a Python call
- Add `on_event` callback
- Path-based workspace restriction (L1 isolation)
- This alone unblocks The Vibe Coding Squad with embedded approach

### Phase 2: Temper AI Server (HTTP API)
- FastAPI app wrapping `WorkflowRunner`
- REST endpoints for runs, events, workflows
- WebSocket event streaming
- SQLite event store
- Thread pool concurrency

### Phase 3: Container Isolation
- Docker-based workspace isolation
- Container lifecycle management
- Resource limits
- Secure by default

### Phase 4: Production Hardening
- PostgreSQL support
- Queue-based concurrency (Redis)
- Auth (API keys)
- Rate limiting
- Health checks
- Metrics/monitoring

## Prior Art

| Tool | Model | What we can learn |
|------|-------|-------------------|
| **Temporal** | Server + workers | Durable execution, workflow replay |
| **Airflow** | Scheduler + workers + UI | DAG visualization, run history |
| **GitHub Actions** | Runners pull jobs | Workspace isolation, container runners |
| **LangServe** | Wraps LangChain in FastAPI | Simple API-first approach |
| **Modal** | Serverless containers | Per-run isolation, instant spinup |

## Open Questions

1. **Auth model** - API keys? OAuth? None for v1?
2. **Workspace persistence** - Clone fresh per run? Or use a persistent workspace with locking?
3. **LLM routing** - Should each run specify its LLM endpoint, or use a shared config?
4. **Multi-tenancy** - One server per project, or one server for many projects?
5. **Workflow hot-reload** - Can you update workflow configs without restarting the server?
6. **Run cancellation** - How to gracefully stop a running workflow mid-execution?
7. **Cost tracking** - Should the server track LLM costs per run?
