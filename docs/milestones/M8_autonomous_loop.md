# M8: Autonomous Self-Improving Loop

## M8.1: Post-Execution Autonomous Loop
- **Scope:** After every workflow execution, automatically trigger pattern mining, goal proposals, and portfolio updates
- **Module:** `temper_ai/autonomy/` (PostExecutionOrchestrator, AutonomousLoopConfig, WorkflowRunContext, PostExecutionReport)
- **Key design:** Opt-in via YAML (`autonomous_loop.enabled: true`) or CLI (`--autonomous`). Each subsystem wrapped in try/except for graceful degradation.
- **Schema:** `autonomous_loop` field added to `WorkflowConfigInner`

## M8.2: Feedback Application
- **Scope:** Auto-apply learned recommendations and approved goals to future configs
- **Module:** `temper_ai/autonomy/feedback_applier.py` (FeedbackApplier), `temper_ai/autonomy/audit.py` (AuditLogger)
- **Key design:** Confidence filtering, max_auto_apply limit, safety policy validation, full audit trail (JSONL)
- **Schema fields:** `auto_apply_learning`, `auto_apply_goals`, `auto_apply_min_confidence`, `max_auto_apply_per_run`

## M8.3: Memory Completion
- **Scope:** Bridge procedural and semantic memory to agent prompts
- **New:** `temper_ai/memory/adapters/knowledge_graph_adapter.py` (KnowledgeGraphMemoryAdapter)
- **New:** `temper_ai/autonomy/memory_bridge.py` (LearningToMemoryBridge)
- **Modified:** `temper_ai/memory/service.py` (+retrieve_procedural_context), `temper_ai/agent/standard_agent.py` (+procedural injection)
- **Key design:** KG concepts exposed as read-only semantic memories, learned patterns synced as procedural memories

## M8.4: Experimentation Integration
- **Scope:** CLI commands and dashboard routes for the experimentation system
- **New:** `temper_ai/experimentation/dashboard_service.py`, `temper_ai/experimentation/dashboard_routes.py`
- **New:** `temper_ai/interfaces/cli/experiment_commands.py`
- **CLI:** `temper-aiexperiment list|create|start|stop|results`
- **Dashboard:** 6 API endpoints under `/api/experiments`

## Test Coverage
| Module | Tests |
|--------|-------|
| M8.1 Orchestrator + Schemas | 28 |
| M8.2 Feedback + Audit | 60 |
| M8.3 Memory Adapter + Bridge | 31 |
| M8.4 Experimentation CLI + Dashboard | 37 |
| **Total** | **147+** |
