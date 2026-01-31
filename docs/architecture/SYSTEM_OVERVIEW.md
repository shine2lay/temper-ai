# System Architecture Overview

[🏠 Home](../../README.md) > [📚 Docs](../INDEX.md) > [Architecture](./) > System Overview

---

## High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         USER / CLI                                 │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│              EXECUTION ENGINE LAYER (M2.5)                         │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Config Loader → EngineRegistry → ExecutionEngine           │ │
│  │  (YAML → Pydantic → Engine Selection → Compile → Execute)   │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  Engines: LangGraph (default) | Custom via interface              │
│  Features: Checkpointing, Resume, Visualization                   │
└────┬────────────────────────────────────────────────┬──────────────┘
     │                                                │
     ▼                                                │
┌────────────────────────────────────────────────┐   │
│      MULTI-AGENT COLLABORATION (M3)            │   │
│                                                │   │
│  ┌──────────────────────────────────────────┐ │   │
│  │ Stage Executors                          │ │   │
│  │ • Sequential (one-by-one)                │ │   │
│  │ • Parallel (concurrent, 2-3x speedup)    │ │   │
│  │ • Adaptive (context-based)               │ │   │
│  └──────────────────────────────────────────┘ │   │
│                                                │   │
│  ┌──────────────────────────────────────────┐ │   │
│  │ Collaboration Strategies                 │ │   │
│  │ • Consensus (voting, <10ms)              │ │   │
│  │ • Debate (multi-round convergence)       │ │   │
│  │ • Merit-Weighted (expert opinions)       │ │   │
│  └──────────────────────────────────────────┘ │   │
└────┬───────────────────────────────────────────┘   │
     │                                                │
     ▼                                                │
┌────────────────────────────────────────────────┐   │
│      SAFETY & GOVERNANCE (M4)                  │   │
│                                                │   │
│  ┌──────────────────────────────────────────┐ │   │
│  │ PolicyComposer (multi-layer)             │ │   │
│  │ • P0: Secrets, forbidden ops, file access│ │   │
│  │ • P1: Blast radius, rate limits          │ │   │
│  │ • P2: Cost limits, resource quotas       │ │   │
│  └──────────────────────────────────────────┘ │   │
│                                                │   │
│  ┌──────────────────────────────────────────┐ │   │
│  │ Safety Gates + Circuit Breakers          │ │   │
│  │ • Pre/runtime/post validation            │ │   │
│  │ • Approval workflow (HITL)               │ │   │
│  │ • Rollback manager (snapshots)           │ │   │
│  └──────────────────────────────────────────┘ │   │
└────┬───────────────────────────────────────────┘   │
     │                                                │
     ▼                                                ▼
┌──────────────────┐                    ┌────────────────────────┐
│  AGENT LAYER     │                    │   OBSERVABILITY        │
│                  │                    │                        │
│  ┌────────────┐  │                    │  ┌──────────────────┐ │
│  │ BaseAgent  │◄─┼────────────────────┼──┤ ExecutionTracker │ │
│  │            │  │                    │  │                  │ │
│  │- execute() │  │                    │  │ - track_agent()  │ │
│  │- get_cap() │  │                    │  │ - track_llm()    │ │
│  └─────┬──────┘  │                    │  │ - track_tool()   │ │
│        │         │                    │  │ - track_collab() │ │
│        ▼         │                    │  │ - track_safety() │ │
│  ┌────────────┐  │                    │  └────────┬─────────┘ │
│  │StandardAgent  │                    │           │           │
│  │            │  │                    │           ▼           │
│  │ - LLM      │  │                    │  ┌──────────────────┐ │
│  │ - Tools    │  │                    │  │   Database       │ │
│  │ - Prompt   │  │                    │  │ (SQLModel)       │ │
│  └─┬──┬──┬───┘  │                    │  │                  │ │
└────┼──┼──┼──────┘                    │  │ - Workflows      │ │
     │  │  │                           │  │ - Agents         │ │
     │  │  │                           │  │ - LLM Calls      │ │
     │  │  │                           │  │ - Tool Calls     │ │
     ▼  ▼  ▼                           │  │ - Collab Events  │ │
┌─────────────────────────────────────┐  │ - Safety Violations│ │
│    FOUNDATION SERVICES              │  └──────────────────┘ │
│                                     │  └────────────────────┘
│  ┌───────────┐ ┌────────────┐      │
│  │LLM Provider│ │Tool Registry      │
│  │           │ │            │      │
│  │- Ollama   │ │- Calculator│      │
│  │- OpenAI   │ │- FileWriter│      │
│  │- Anthropic│ │- WebScraper│      │
│  └───────────┘ └────────────┘      │
│                                     │
│  ┌─────────────┐ ┌──────────────┐  │
│  │PromptEngine │ │StrategyRegistry │
│  │- Jinja2     │ │- Consensus    │  │
│  │- Variables  │ │- Debate       │  │
│  │- Templates  │ │- MeritWeighted│  │
│  └─────────────┘ └──────────────┘  │
└─────────────────────────────────────┘
```

## Data Flow

### 1. Configuration Loading
```
YAML File
    │
    ├─ configs/workflows/simple_research.yaml
    │
    ▼
ConfigLoader.load_workflow()
    │
    ├─ Parse YAML
    ├─ Substitute env vars (${VAR})
    ├─ Validate with Pydantic schemas
    │
    ▼
WorkflowConfig (validated)
    │
    └─> Contains: workflow.stages[].agents[]
```

### 2. Agent Creation
```
AgentConfig (from YAML)
    │
    ├─ type: "standard"
    ├─ inference: {...}
    ├─ tools: [...]
    ├─ prompt: {...}
    │
    ▼
AgentFactory.create(config)
    │
    ├─ Check type field
    ├─ Instantiate StandardAgent
    │
    ▼
StandardAgent
    │
    ├─ Create LLM provider from config.inference
    ├─ Load tools from config.tools
    ├─ Load prompt template
    │
    └─> Ready to execute
```

### 3. Execution Flow
```
agent.execute(input_data, context)
    │
    ├─ 1. Render prompt template
    │      └─> "You are a researcher..."
    │
    ├─ 2. Call LLM
    │      ├─> llm.generate(prompt)
    │      └─> Track to database
    │
    ├─ 3. Parse tool calls from LLM response
    │      └─> [{"name": "Calculator", "params": {...}}]
    │
    ├─ 4. Execute tools
    │      ├─> tool.execute(**params)
    │      └─> Track to database
    │
    ├─ 5. Inject tool results into prompt
    │      └─> "Tool result: 42"
    │
    ├─ 6. Call LLM again (if needed)
    │      └─> Repeat steps 2-5
    │
    └─> Return AgentResponse
         ├─ output: final answer
         ├─ reasoning: thought process
         ├─ tool_calls: all tools used
         └─ metadata: tokens, cost, duration
```

### 4. Observability Tracking
```
ExecutionTracker
    │
    ├─ Workflow Start
    │   └─> Create WorkflowExecution (status=running)
    │
    ├─ Stage Start
    │   └─> Create StageExecution
    │
    ├─ Agent Start
    │   └─> Create AgentExecution
    │
    ├─ LLM Call
    │   └─> Create LLMCall (tokens, cost, latency)
    │
    ├─ Tool Call
    │   └─> Create ToolExecution (params, result, duration)
    │
    ├─ Agent End
    │   └─> Update AgentExecution (metrics, status)
    │
    ├─ Stage End
    │   └─> Update StageExecution
    │
    └─ Workflow End
        └─> Update WorkflowExecution (aggregated metrics)
```

## Component Interactions

### Agent → LLM Provider
```python
# Agent owns LLM provider
class StandardAgent:
    def __init__(self, config):
        self.llm = self._create_llm_provider(config.inference)

    def execute(self, input_data, context):
        # Agent calls LLM
        response = self.llm.generate(prompt)
        # Track to observability
        context.tracker.track_llm_call(response)
```

### Agent → Tool Registry
```python
# Agent loads tools on init
class StandardAgent:
    def __init__(self, config):
        registry = ToolRegistry()
        self.tools = [registry.get(name) for name in config.tools]

    def execute(self, input_data, context):
        # Agent executes tool
        tool = next(t for t in self.tools if t.name == tool_name)
        result = tool.execute(**params)
```

### Agent → Observability
```python
# Agent receives tracker in context
def execute(self, input_data, context):
    # Context contains tracker
    tracker = context.tracker

    # Track LLM call
    tracker.track_llm_call(agent_id, llm_response)

    # Track tool execution
    tracker.track_tool_call(agent_id, tool_name, params, result)
```

## Layer Responsibilities

### **Execution Engine Layer (M2.5)**
- Abstract interface for pluggable execution engines
- Engine selection via EngineRegistry
- Workflow compilation (config → executable)
- Workflow execution with state management
- Feature detection for engine capabilities
- Checkpoint/resume support for long-running workflows
- Workflow visualization generation

### **Multi-Agent Collaboration Layer (M3)**
- Stage execution strategies (Sequential, Parallel, Adaptive)
- Parallel execution with 2-3x speedup
- Collaboration synthesis (Consensus, Debate, Merit-Weighted)
- Conflict detection and resolution
- Convergence detection for early termination
- Multi-agent state management
- Quality gates for collaboration output

### **Safety & Governance Layer (M4)**
- Multi-layer policy enforcement (P0-P2)
- Safety gates at tool/agent/stage/workflow levels
- Circuit breakers for failure detection
- Approval workflow (human-in-the-loop)
- Rollback manager with state snapshots
- Rate limiting and blast radius controls
- Secret detection and forbidden operation blocking

### **Agent Layer**
- Execute agent logic (LLM + tools)
- Render prompts with variables
- Parse LLM responses
- Orchestrate tool calls with safety checks
- Return structured responses with confidence scores

### **Foundation Layer**
- LLM provider abstraction (Ollama, OpenAI, Anthropic, vLLM)
- Tool registry and execution
- Prompt template rendering (Jinja2)
- Strategy registry (Consensus, Debate, Merit-Weighted)
- All reusable components

### **Observability Layer**
- Track all executions to database
- Calculate metrics (tokens, cost, duration)
- Track collaboration events (M3)
- Track safety violations (M4)
- Enable querying and visualization
- Console streaming updates

## Key Design Principles

1. **Interface-Based** - All major components have abstract base classes
2. **Config-Driven** - Behavior determined by YAML configuration
3. **Modular** - Each component can be swapped/extended
4. **Observable** - Every action tracked to database
5. **Type-Safe** - Pydantic validation throughout

## Next: Detailed Interface Documentation

See:
- [Agent Interface](../interfaces/core/agent_interface.md)
- [LLM Provider Interface](../interfaces/core/llm_provider_interface.md)
- [Tool Interface](../interfaces/core/tool_interface.md)
- [Observability Models](../interfaces/models/observability_models.md)
