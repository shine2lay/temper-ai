# Glossary

Comprehensive terminology reference for the Temper AI.

---

## Core Concepts

### Agent

An autonomous AI entity that can execute tasks using LLMs and tools. Agents process inputs, make decisions, and produce outputs.

**Usage:** "The researcher agent analyzes scientific papers."

**Not:** "worker", "bot", "assistant" (use "agent" consistently)

**Related:** StandardAgent, BaseAgent, AgentFactory

---

### Stage

A discrete step in a workflow that executes one or more agents. Stages can run sequentially or in parallel.

**Usage:** "The research stage executes three agents in parallel."

**Not:** "step", "phase", "node" (use "stage" for workflow components)

**Types:**
- **Sequential Stage** - Runs single agent
- **Parallel Stage** - Runs multiple agents concurrently
- **Synthesis Stage** - Combines results from previous stages

**Related:** Workflow, ParallelStageExecutor

---

### Workflow

A complete execution graph consisting of multiple stages. Workflows define the entire lifecycle of a task from input to output.

**Usage:** "The research workflow contains three stages: search, analysis, and synthesis."

**Related:** CompiledWorkflow, WorkflowExecution

---

### Policy

A safety rule that validates actions before execution. Policies return violations when actions fail validation.

**Usage:** "The ForbiddenOperationsPolicy blocks dangerous bash commands."

**Not:** "rule" (use "policy" in safety context)

**Types:**
- **P0 (Critical)** - Security vulnerabilities, data integrity
- **P1 (High)** - Resource limits, safety constraints
- **P2 (Medium)** - Best practices, recommendations

**Related:** SafetyPolicy, PolicyComposer, ActionPolicyEngine

---

### Safety vs Security

**Safety** - Protection against unintended harm from autonomous agents (blast radius, rollback, approval workflows)

**Security** - Protection against malicious attacks (SSRF, injection, unauthorized access)

**Usage:**
- ✅ "Safety policies prevent agents from deleting production databases"
- ✅ "Security policies block SSRF attacks and command injection"

**The framework uses "safety" for most contexts** as it focuses on safe autonomous operation, not defending against attackers.

**Related:** SafetyViolation, SecurityPolicy, SafetyGate

---

## Execution Components

### Execution Engine

An abstraction layer that compiles and executes workflows. Engines can be swapped (LangGraph, custom implementations).

**Usage:** "The LangGraphExecutionEngine compiles YAML workflows into executable graphs."

**Related:** ExecutionEngine, EngineRegistry

---

### Tool

A function or capability that agents can invoke (e.g., web search, file read, calculator).

**Usage:** "The web_search tool fetches content from URLs."

**Related:** ToolRegistry, ToolExecution

---

### LLM (Large Language Model)

The AI model powering agent reasoning and decision-making.

**Supported Providers:** Ollama, OpenAI, Anthropic, vLLM

**Usage:** "The agent uses the Claude 3.5 Sonnet LLM for complex reasoning."

**Related:** LLMProvider, LLMCall

---

## Collaboration Concepts

### Collaboration Strategy

An algorithm for coordinating multiple agents working on the same task.

**Types:**
- **Consensus** - Democratic voting with majority rule
- **Debate** - Multi-round argumentation with convergence detection

**Usage:** "The consensus strategy combines agent outputs by majority vote."

**Related:** CollaborationStrategy, StrategyRegistry

---

### Conflict Resolution

The process of resolving disagreements between agents when they produce different outputs.

**Types:**
- **Merit-Weighted** - Weight votes by agent expertise and success rate
- **Majority Vote** - Simple majority wins
- **Unanimous** - All agents must agree

**Usage:** "Merit-weighted resolution gives more weight to expert agents."

**Related:** ConflictResolver, MeritWeightedResolver

---

### Synthesis

The process of combining outputs from multiple agents into a unified result.

**Usage:** "The synthesis node merges research findings from three agents."

**Related:** SynthesisNode, CollaborationEvent

---

### Convergence

When agents reach agreement or similarity threshold in their outputs, allowing early termination of debate.

**Usage:** "Debate terminated after round 3 when convergence reached 85%."

**Related:** ConvergenceDetector

---

## Safety & Governance

### Violation

A failed policy validation indicating an action violates safety constraints.

**Severity Levels:**
- **CRITICAL** - P0 violations, action must be blocked
- **HIGH** - P1 violations, action should be reviewed
- **MEDIUM** - P2 violations, warnings only

**Usage:** "The action triggered a CRITICAL violation for forbidden operations."

**Related:** SafetyViolation, ViolationSeverity

---

### Approval Workflow

Human-in-the-loop process requiring manual approval before executing high-risk actions.

**Usage:** "Production deployments require approval workflow with 2-person confirmation."

**Related:** ApprovalPolicy, HumanApproval

---

### Rollback

The process of reverting system state to a previous snapshot after failed or unsafe actions.

**Usage:** "The rollback manager restored the database to pre-migration state."

**Related:** RollbackManager, Snapshot

---

### Circuit Breaker

Automatic failure detection and recovery mechanism that stops repeated failing operations.

**States:**
- **Closed** - Normal operation
- **Open** - Failures detected, operations blocked
- **Half-Open** - Testing recovery

**Usage:** "The circuit breaker opened after 5 consecutive LLM timeouts."

**Related:** CircuitBreakerPolicy

---

### Safety Gate

Multi-layer validation checkpoint that actions must pass before execution.

**Usage:** "The safety gate validates actions against all P0 and P1 policies."

**Related:** SafetyGate, PolicyComposer

---

## Observability

### Observability

The ability to understand system state and behavior through traces, logs, and metrics.

**Components:**
- **Traces** - Execution flow and timing
- **Logs** - Event records and errors
- **Metrics** - Counters, gauges, histograms

**Usage:** "Observability tracking captured 45 LLM calls and 12 tool executions."

**Related:** ObservabilityBackend, ExecutionTracker

---

### Trace

A complete record of workflow execution including all stages, agents, LLM calls, and tool executions.

**Usage:** "The trace shows the workflow took 2.5 minutes and cost $0.15."

**Related:** WorkflowExecution, StageExecution, AgentExecution

---

### Metric

A quantitative measurement of system behavior (tokens used, cost, latency, success rate).

**Usage:** "The cost metric shows LLM expenses of $12.50 this month."

**Related:** MetricsCollector

---

## Configuration

### YAML Configuration

Declarative configuration format for defining agents, workflows, tools, and policies.

**Configuration Types:**
- `configs/agents/` - Agent definitions
- `configs/workflows/` - Workflow definitions
- `configs/tools/` - Tool configurations
- `configs/prompts/` - Prompt templates

**Usage:** "The researcher.yaml config defines the agent's LLM and tools."

**Related:** ConfigLoader

---

### Template

A reusable prompt or configuration pattern with variable substitution (Jinja2 format).

**Usage:** "The prompt template substitutes {{query}} with user input."

**Related:** PromptEngine, Jinja2

---

## Common Confusions

### Agent vs Worker

✅ **Use:** Agent
❌ **Avoid:** Worker

The framework uses "agent" exclusively for AI entities that reason and act.

---

### Stage vs Step

✅ **Use:** Stage (for workflow components)
❌ **Avoid:** Step, phase, node

The framework uses "stage" for workflow execution units.

---

### Safety vs Security

✅ **Use:** Safety (for most autonomous operation contexts)
✅ **Use:** Security (only when specifically discussing attack defense)

Safety is the primary focus - protecting against unintended harm from autonomous agents.

---

### Policy vs Rule

✅ **Use:** Policy (for safety validation)
❌ **Avoid:** Rule

The framework uses "policy" in the context of safety and governance.

---

## Acronyms

| Acronym | Full Term | Description |
|---------|-----------|-------------|
| **LLM** | Large Language Model | AI model powering agent reasoning |
| **YAML** | YAML Ain't Markup Language | Configuration file format |
| **API** | Application Programming Interface | Programmatic interface |
| **CLI** | Command-Line Interface | Terminal-based user interface |
| **P0/P1/P2** | Priority 0/1/2 | Safety policy priority levels |
| **SSRF** | Server-Side Request Forgery | Security vulnerability type |
| **TTL** | Time To Live | Cache expiration duration |
| **E2E** | End-to-End | Complete integration testing |
| **ADR** | Architecture Decision Record | Design decision documentation |

---

## Quick Reference

| If you mean... | Use this term |
|---------------|---------------|
| AI entity that executes tasks | Agent |
| Workflow execution unit | Stage |
| Complete execution graph | Workflow |
| Safety validation rule | Policy |
| Preventing unintended harm | Safety |
| Defending against attacks | Security |
| Failed validation | Violation |
| Combining agent outputs | Synthesis |
| Agents reaching agreement | Convergence |
| Function/capability | Tool |
| AI model | LLM |

---

## See Also

- [API Reference](./API_REFERENCE.md) - Complete API documentation
- [Configuration Guide](./CONFIGURATION.md) - Configuration details
- [Architecture](./architecture/) - System architecture
- [Contributing Guide](./CONTRIBUTING.md) - Contribution guidelines
