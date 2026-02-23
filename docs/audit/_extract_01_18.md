# Audit Extract: Scopes 01-18

## Scope 01: Workflow Core
Grade: N/A (no numeric score; described as "well-engineered")
Findings: 3 critical, 5 high, 10 medium, 6 low

Critical findings:
- db_config_loader.py:27-44 -- No schema validation on DB-loaded configs; bypasses all Pydantic enforcement
- db_config_loader.py -- Zero test coverage; entire module untested (critical security surface)
- execution_service.py:397-422 -- Cancellation is cosmetic only; running thread continues to completion

High findings:
- runtime.py:541-649 -- run_pipeline() is 109 lines (limit: 50)
- runtime.py:541 -- run_pipeline() has 8 parameters (limit: 7)
- constants.py:38-41 vs security_limits.py:28-49 -- Duplicate security constants across two files
- _config_loader_helpers.py:91-96 -- Bare except Exception re-raises without preserving chain (from e)
- config_loader.py:228-233 -- Broad except Exception silently swallows ConfigDeployer lookup errors

Vision pillar gaps:
- Radical Modularity: DBConfigLoader does not implement full ConfigLoaderProtocol (missing load_tool, load_trigger, load_prompt_template)
- Observability: db_config_loader.py has no logging, metrics, or event emission for config loads
- Safety Through Composition: Safety policies do not compose at the DBConfigLoader level; DB configs bypass all validation

---

## Scope 02: Workflow Engines
Grade: N/A (no numeric score; "architecturally sound")
Findings: 0 critical, 3 high, 8 medium, 5 low

Critical findings:
(none)

High findings:
- dynamic_runner.py:121, workflow_executor.py:292, workflow_executor.py:398 -- Broad except Exception in parallel execution paths; misclassifies framework bugs as stage errors
- dynamic_engine.py:56,70,93,136 and langgraph_engine.py:51,100,127,222 -- Cancellation flag is plain boolean without synchronization; not truly thread-safe
- dynamic_engine.py:142-159, langgraph_engine.py:53-83, langgraph_compiler.py:433-450 -- _extract_stage_names duplicated 3 times with near-identical logic

Vision pillar gaps:
- Observability: DynamicCompiledWorkflow has no tracker injection point; no span/trace creation at engine level
- Progressive Autonomy: No approval gates between stages; engine does not enforce progressive autonomy policies
- Self-Improvement: No execution metrics fed back to improve future runs; no learning from checkpoint/resume patterns
- Safety Through Composition: No blast radius checking for dynamic edge routing; no safety policy evaluation at engine level

---

## Scope 03: Workflow Compilation, Checkpoint & DAG
Grade: N/A (no numeric score; "well-architected with strong security fundamentals")
Findings: 0 critical, 4 high, 8 medium, 7 low

Critical findings:
(none)

High findings:
- checkpoint_manager.py:304 -- Literal string bug: LOG_SEPARATOR_CHECKPOINT embedded as text instead of interpolated in f-string
- dag_builder.py:131-149 -- _kahn_bfs has O(V*E) instead of O(V+E) complexity; runs on every workflow execution
- stage_compiler.py:628-692 -- _insert_fan_in_barriers is 67 lines (limit: 50)
- node_builder.py:59-136 -- create_stage_node closure is 79 lines (limit: 50); five responsibilities in one function

Vision pillar gaps:
- Radical Modularity: Only FileCheckpointBackend exists; no shared storage backend for multi-worker deployments
- Configuration as Product: No YAML config for checkpoint backend type or barrier insertion strategy
- Observability: Stage compilation events not traced; no metrics for compilation time or DAG complexity
- Progressive Autonomy: No approval gates in compilation pipeline; no trust-level-based conditional execution
- Self-Improvement: Compilation metrics not fed to optimization; no compilation caching; planning pass results not stored
- Safety Through Composition: No safety policy enforcement during compilation itself

---

## Scope 04: Stage Executors
Grade: A- (no numeric score)
Findings: 0 critical, 2 high, 6 medium, 5 low (+ 3 dead code)

Critical findings:
(none)

High findings:
- _parallel_helpers.py:298-312 -- Duplicate exception types in parallel agent node; ValueError/TypeError caught by first clause, second clause never catches them, misclassifying runtime errors
- _agent_execution.py:13-14 -- Module-level persistent agent cache has no size bound; unbounded memory growth in long-running servers

Vision pillar gaps:
- Progressive Autonomy: approval_required_when declared in schema but not wired into executor pipeline
- Safety Through Composition: No per-agent execution timeout; tool_executor safety stack wired but no stage-level sandboxing
- Radical Modularity: _base_helpers.py mass re-export of 22 symbols slightly undermines modularity

---

## Scope 05: Agent Core
Grade: B+ (83/100)
Findings: 0 critical, 0 high, 5 medium, 9 low

Critical findings:
(none)

High findings:
(none)

Medium findings:
- script_agent.py:74, _pre_command_helpers.py:184 -- shell=True in subprocess calls; mitigated by env whitelist, shlex.quote, and timeout
- guardrails.py:64-65 -- importlib.import_module for guardrail function checks; no module path allowlist
- base_agent.py:439-440,451-452, agent_observer.py:106-107 -- Silent exception swallowing in stream callbacks
- _r0_pipeline_helpers.py -- No direct unit tests for retry loop, feedback injection, or async variants
- models/response.py:72-87 -- AgentResponse._calculate_confidence has minimal test coverage

Vision pillar gaps:
- Progressive Autonomy: No per-agent autonomy level (supervised/semi-autonomous/autonomous)
- Self-Improvement: DSPy doesn't close loop by feeding back runtime performance; no automatic performance feedback
- Merit-Based Collaboration: Confidence calculation is simplistic heuristic (output length, reasoning, tool success)
- Safety Through Composition: importlib in guardrails has no module path restriction

---

## Scope 06: Agent Strategies
Grade: A- (91/100)
Findings: 0 critical, 0 high, 10 medium, 13 low

Critical findings:
(none)

High findings:
(none)

Medium findings:
- consensus.py:166-250 -- ConsensusStrategy.synthesize() is 85 lines (limit: 50)
- _dialogue_helpers.py:18-81 -- get_merit_weights() is 64 lines; mixes DB query and fallback logic
- base.py:370-437 -- detect_conflicts() is 68 lines
- multi_round.py:512 -- No timeout on SentenceTransformer model download
- multi_round.py:286 -- min_rounds > max_rounds not validated
- conflict_resolution.py:453-484 -- 4 of 7 ResolutionMethod enum values have no implementation
- All strategies -- No async support in any strategy (all synchronous)
- Missing -- ConcatenateStrategy has no dedicated test file
- All strategies -- Strategy execution not integrated with observability tracker
- All strategies -- Strategy outcomes not fed to learning subsystem

Vision pillar gaps:
- Observability: Strategy execution not integrated with observability tracker; no events emitted to event bus
- Self-Improvement: Strategy outcomes not fed to learning subsystem; no feedback loop from strategies to learning miners
- Safety Through Composition: No safety policy integration at strategy level; no ActionPolicyEngine consultation

---

## Scope 07: LLM Core
Grade: B+ (83/100)
Findings: 3 critical, 3 high, 7 medium, 4 low

Critical findings:
- _tool_execution.py:106-112 -- Key inconsistency in check_safety_mode: hardcoded string literals vs ToolKeys constants in require_approval_for_tools branch
- tests/test_llm/ -- No unit tests for _retry.py; retry backoff logic entirely untested
- tests/test_llm/ -- No unit tests for _tool_execution.py; safety mode and parallel execution untested

High findings:
- _retry.py:56-58 -- Non-functional shutdown_event in sync retry; new Event per attempt never set
- _retry.py:46 -- Only LLMError caught in retry loop; transient httpx errors not retried
- tests/test_llm/ -- No unit tests for conversation.py; turn trimming logic untested

Vision pillar gaps:
- Configuration as Product: context window DEFAULT_MODEL_CONTEXT hardcoded at 128000; not per-model configurable
- Feature Completeness: _summarize strategy is a stub (truncates, does not summarize)

---

## Scope 08: LLM Providers
Grade: B+ (85/100)
Findings: 0 critical, 5 high, 9 medium, 7 low

Critical findings:
(none)

High findings:
- anthropic_provider.py:64-78 -- Anthropic provider has no streaming support; _consume_stream raises NotImplementedError
- openai_provider.py:38-49 -- OpenAI provider silently drops tools in _build_request; tool calling cannot work
- ollama.py:44,69,82,90 -- _use_chat_api mutable instance state set as side-effect of _build_request; thread-unsafe
- test_llm_providers.py -- Zero tests for async streaming (astream) on any provider
- test_llm_providers.py -- No tests for create_llm_from_config() or api_key_ref env-var resolution

Vision pillar gaps:
- Radical Modularity: Providers not fully interchangeable at runtime (tool calling, streaming, thinking tokens differ)
- Security: SSRF check does not resolve DNS; hostname bypass possible via evil.com pointing to internal IPs

---

## Scope 09: LLM Cache & Prompts
Grade: A- (93/100)
Findings: 0 critical, 2 high, 4 medium, 8 low

Critical findings:
(none)

High findings:
- prompts/cache.py:14-63 -- TemplateCacheManager not thread-safe; no locking around _template_cache, _cache_hits, _cache_misses
- prompts/cache.py -- No concurrency test for TemplateCacheManager

Vision pillar gaps:
- Configuration as Product: Cache configuration (backend, TTL, max_size) not exposed in agent YAML configs
- Self-Improvement: Cache hit rates not surfaced to learning/optimization system

---

## Scope 10: Tools Core
Grade: A- (91/100)
Findings: 0 critical, 0 high, 4 medium, 7 low

Critical findings:
(none)

High findings:
(none)

Medium findings:
- registry.py:238-247, executor.py:328-330 -- Monkey-patched methods hurt IDE discoverability and type checking
- _registry_helpers.py:356, _executor_helpers.py:490 -- Two broad except Exception catches
- N/A -- No async tool execution path; all sync + ThreadPoolExecutor
- loader.py -- No dedicated tests for template resolution logic

Vision pillar gaps:
- Extensibility: Monkey-patching pattern hurts subclassing; dead mixin classes never adopted
- Performance: No async path is the main gap for I/O-bound tools

---

## Scope 11: Tools Builtins
Grade: A (94/100)
Findings: 0 critical, 1 high, 2 medium, 10 low

Critical findings:
(none)

High findings:
- code_executor.py:24-41 -- CodeExecutor import blocklist bypassable via __import__(), string manipulation, or importlib indirection

Medium findings:
- http_client.py:31-51 -- HTTPClient lacks DNS-level SSRF protection; only checks hostname string, not resolved IP
- web_scraper.py:57-319 vs http_client.py:31-51 -- Missing shared SSRF protection module; inconsistent protection between tools

Vision pillar gaps:
- Safety Through Composition: CodeExecutor sandbox insufficient (regex-only import filter); HTTPClient weaker SSRF than WebScraper

---

## Scope 12: Safety Core Policies
Grade: A (95/100)
Findings: 0 critical, 0 high, 5 medium, 6 low

Critical findings:
(none)

High findings:
(none)

Medium findings:
- factory.py:15-31 -- 17 top-level imports exceed fan-out limit of 8
- config_change_policy.py:171-226 -- Unbounded recursion depth in _detect_changes
- composition.py:250 -- valid inconsistency: any violation (even INFO/LOW) marks result invalid, while ActionPolicyEngine only blocks on HIGH+
- Missing -- No dedicated tests for service_mixin.py
- Missing -- No dedicated tests for config_change_policy.py

Vision pillar gaps:
- (No major vision pillar gaps; this module IS the Safety Through Composition pillar implementation)

---

## Scope 13: Safety Detection & Limits
Grade: B+ (81/100)
Findings: 1 critical, 0 high, 4 medium, 5 low

Critical findings:
- _file_access_helpers.py:normalize_path() -- Null byte path injection bypass; embedded null bytes in path components can bypass forbidden directory checks

High findings:
(none)

Medium findings:
- _forbidden_ops_helpers.py:144-164 -- Incomplete command injection detection; pipe-to-shell, backtick, and subshell bypasses not detected
- llm_security.py:83 -- SecurityViolation.timestamp uses naive datetime.now() instead of datetime.now(timezone.utc)
- constants.py vs module files -- Priority constant duplication with conflicting values across files
- Missing -- No dedicated tests for PromptInjectionPolicy wrapper

Vision pillar gaps:
- Feature Completeness: No SSRF protection policy (documented, acceptable scope boundary)
- Feature Completeness: No SQL injection detection policy (documented, acceptable scope boundary)

---

## Scope 14: Safety Autonomy (Progressive Autonomy)
Grade: A- (90/100)
Findings: 0 critical, 1 high, 4 medium, 8 low

Critical findings:
(none)

High findings:
- budget_enforcer.py:110-131 -- BudgetEnforcer.record_spend() race condition; no lock on read-increment-write; concurrent calls can lose spend records

Medium findings:
- budget_enforcer.py:70-108 -- check_budget() has TOCTOU gap with record_spend(); no atomic check-and-decrement
- dashboard_routes.py:39-44 -- Dashboard routes lack authentication; POST routes for emergency-stop/resume/escalate are unauthenticated
- shadow_mode.py -- Shadow mode not automatically wired into escalation flow; must be explicitly invoked
- Missing -- No concurrent/thread-safety tests for AutonomyManager or BudgetEnforcer

Vision pillar gaps:
- Observability: Autonomy transitions not emitted as observability events to main trace timeline
- Progressive Autonomy: Shadow mode exists but is not enforced by default during escalation

---

## Scope 15: Observability Core
Grade: B+ (85/100)
Findings: 0 critical, 3 high, 5 medium, 8 low

Critical findings:
(none)

High findings:
- _tracker_helpers.py:883,977,1032 -- Unsanitized str(error) written to backend and event bus; exception messages can contain credentials
- sanitization.py:263-287 -- redact_medium_confidence_secrets config flag is dead code; no confidence classification exists
- _tracker_helpers.py:125 vs backend.py:97 -- Duplicate CollaborationEventData class name with different fields

Medium findings:
- hooks.py:410,449,550,570 -- end_stage/end_agent pass None instead of error.__traceback__; lose stack traces
- types.py:1-17 -- Vestigial file with 9 dict[str, Any] aliases providing no type safety
- _tracker_helpers.py:125-141 -- CollaborationEventData has redundant fields (agents/agents_involved, confidence/confidence_score)
- _tracker_helpers.py -- No direct unit tests for extracted helper functions (sanitize_dict, _validate_llm_metrics, etc.)
- event_bus.py:128-134 -- Async event bus drops events on queue full with no drop counter

Vision pillar gaps:
- Observability: No structured logging integration (JSON format for ELK/Datadog)
- Observability: No OpenTelemetry span propagation in core tracker

---

## Scope 16: Observability Backends & Aggregation
Grade: B+ (82/100)
Findings: 0 critical, 3 high, 4 medium, 5 low

Critical findings:
(none)

High findings:
- query_builder.py:54,134-135 -- percentile_cont is PostgreSQL-only; fails on SQLite with OperationalError
- otel_backend.py -- 903-line backend with zero test coverage
- otel_backend.py:181,899-902 -- Module-level otel_trace may be None; _start_span uses it unconditionally

Medium findings:
- _sql_backend_helpers.py:271-308 -- cleanup_old_records only counts/deletes workflows; child counts always 0
- sql_backend.py:287 -- compute_quality_score import can fail; no error handling
- aggregation/aggregator.py:94,152,209 -- Broad except Exception in aggregation methods; should catch SQLAlchemyError
- _sql_backend_helpers.py:586-631 -- read_get_stage still uses N+1 queries; missing selectinload

Vision pillar gaps:
- Feature Completeness: S3 and Prometheus backends are stubs (M6 implementation pending)
- Feature Completeness: Aggregation pipeline tightly coupled to PostgreSQL due to percentile_cont

---

## Scope 17: Observability Features
Grade: A- (91/100)
Findings: 0 critical, 0 high, 3 medium, 6 low

Critical findings:
(none)

High findings:
(none)

Medium findings:
- rollback_logger.py:50-52 -- Rollback snapshots may persist sensitive file contents unsanitized in DB
- 4 files (cost_rollup, dialogue_metrics, failover_events, resilience_events) -- _emit_via_tracker copy-pasted across 4 files
- performance.py:114-374 -- PerformanceTracker.record() and cleanup_expired_metrics() not thread-safe; mutate shared state without locking

Vision pillar gaps:
- (Strong alignment overall; no major vision pillar gaps identified)

---

## Scope 18: CLI Core
Grade: 82/100 (B+)
Findings: 0 critical, 4 high, 7 medium, 5 low

Critical findings:
(none)

High findings:
- main.py:848-1033 -- _run_local_workflow is 185 lines (limit: 50); 3.7x over threshold
- server_client.py:37 vs main.py:1667 -- Auth header inconsistency: X-API-Key vs Authorization: Bearer between server_client and config commands
- N/A -- server_client.py has zero test coverage; all 6 methods untested
- main.py:848-864 -- _run_local_workflow takes 15 parameters (limit: 7)

Vision pillar gaps:
- Observability: CLI operations (config validation, server delegation, rollback) do not emit observability events

---

## Totals

| Severity | Count |
|----------|-------|
| Critical | 7 |
| High | 38 |
| Medium | 101 |
| Low | 111 |
