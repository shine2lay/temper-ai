# M6: Templates & Progressive Autonomy

## M6.1: Progressive Autonomy
- **Scope:** 5-level autonomy system (Supervised to Strategic), budget enforcement, emergency stop
- **Module:** `temper_ai/safety/autonomy/` (AutonomyManager, BudgetEnforcer, EmergencyStopController)
- **CLI:** `temper-aiautonomy status|escalate|deescalate|emergency-stop|resume|budget|history`

## M6.2: Memory System
- **Scope:** Episodic, procedural, and cross-session memory with pluggable adapters
- **Module:** `temper_ai/memory/` (MemoryService, MemoryProviderRegistry)
- **Adapters:** InMemory, Mem0, SQLite, KnowledgeGraph
- **CLI:** `temper-aimemory store|search|list|clear`
- **Key design:** Scope-based isolation (tenant > workflow > agent), time-decay scoring

## M6.3: Multi-Product Templates
- **Scope:** Copy-and-stamp template system for 4 product types
- **Module:** `temper_ai/workflow/templates/` (TemplateRegistry, TemplateGenerator, QualityGates)
- **Templates:** web_app (12 files), api (10), data_pipeline (10), cli_tool (10) = 42 YAML configs
- **CLI:** `temper-aitemplate list|info|create`
- **Tests:** 63 tests in `tests/test_workflow/test_templates/`
