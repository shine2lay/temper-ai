# M8: Autonomous Self-Improving Loop

## M8.1: Post-Execution Autonomous Loop
- **Scope:** After every workflow execution, automatically trigger pattern mining, goal proposals, and portfolio updates
- **Module:** `src/autonomy/` (PostExecutionOrchestrator, AutonomousLoopConfig, WorkflowRunContext, PostExecutionReport)
- **Key design:** Opt-in via YAML (`autonomous_loop.enabled: true`) or CLI (`--autonomous`). Each subsystem wrapped in try/except for graceful degradation.
- **Schema:** `autonomous_loop` field added to `WorkflowConfigInner`

## M8.2: Feedback Application
- **Scope:** Auto-apply learned recommendations and approved goals to future configs
- **Module:** `src/autonomy/feedback_applier.py` (FeedbackApplier), `src/autonomy/audit.py` (AuditLogger)
- **Key design:** Confidence filtering, max_auto_apply limit, safety policy validation, full audit trail (JSONL)
- **Schema fields:** `auto_apply_learning`, `auto_apply_goals`, `auto_apply_min_confidence`, `max_auto_apply_per_run`

## M8.3: Memory Completion
- **Scope:** Bridge procedural and semantic memory to agent prompts
- **New:** `src/memory/adapters/knowledge_graph_adapter.py` (KnowledgeGraphMemoryAdapter)
- **New:** `src/autonomy/memory_bridge.py` (LearningToMemoryBridge)
- **Modified:** `src/memory/service.py` (+retrieve_procedural_context), `src/agent/standard_agent.py` (+procedural injection)
- **Key design:** KG concepts exposed as read-only semantic memories, learned patterns synced as procedural memories

## M8.4: Experimentation Integration
- **Scope:** CLI commands and dashboard routes for the experimentation system
- **New:** `src/experimentation/dashboard_service.py`, `src/experimentation/dashboard_routes.py`
- **New:** `src/interfaces/cli/experiment_commands.py`
- **CLI:** `maf experiment list|create|start|stop|results`
- **Dashboard:** 6 API endpoints under `/api/experiments`

## Test Coverage
| Module | Tests |
|--------|-------|
| M8.1 Orchestrator + Schemas | 28 |
| M8.2 Feedback + Audit | 60 |
| M8.3 Memory Adapter + Bridge | 31 |
| M8.4 Experimentation CLI + Dashboard | 37 |
| **Total** | **147+** |
