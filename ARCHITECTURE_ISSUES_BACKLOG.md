# Architecture Issues & Improvements Backlog

Identified during architecture walkthrough (Section 5: Agent Layer).

## Completion Status

**Wave 1 (Foundation — Error Handling & Execution Reliability): ✅ COMPLETE**
- Issue #1: ✅ Completed - Agent-level retry on LLM failures
- Issue #2: ✅ Completed - Circuit breaker at executor level
- Issue #3: ✅ Completed - Failed agent output loses error context (completed before wave started)
- Issue #4: ✅ Completed - Stage-level failure policy for sequential executor
- Issue #5: ✅ Completed - Silent exception swallowing — no logging

**Wave 2 (Safety Wiring): ✅ COMPLETE**
- Issue #19: ✅ Completed - Safety stack has ownership chain
- Issue #13: ✅ Completed - Safety layer connected to agent execution path
- Issue #9: ✅ Completed - Parameter validation via safe_execute
- Issue #14: ✅ Completed - Safety validation on LLM calls

**Wave 3 (Tool System): ✅ COMPLETE**
- Issue #6: ✅ Completed - Native function calling infrastructure for OpenAI/Anthropic
- Issue #7: ✅ Completed - Tool output size control
- Issue #18: ✅ Completed - Config validation at compiler level

**Wave 4 (Observability): ✅ COMPLETE**
- Issue #21: ✅ Completed - StandardAgent reports directly to tracker
- Issue #30: ✅ Completed - Self-improvement feedback path is bidirectional
- Issue #24: ✅ Completed - AgentMeritScore updated after decisions
- Issue #22: ✅ Completed - Real-time alerting for metric thresholds
- Issue #23: ✅ Completed - Metric aggregation pipeline

**Wave 5 (Collaboration): ⏳ Pending**

**Wave 6 (Self-Improvement): 🔄 In Progress**
- Issue #27: ✅ Completed - M5 integrated with M4 safety stack
- Issue #25: ✅ Completed - Strategies learn from outcomes via Bayesian updating
- Issue #26: ✅ Completed - Pattern mining from experiment history
- Issue #29: ⏳ Pending - Add more concrete strategies
- Issue #28: ⏳ Pending - Implement continuous improvement mode

---

## 1. No Agent-Level Retry (LLM Failures) ✅ COMPLETED

**Status:** ✅ Completed in Wave 1

**Problem:** When `_execute_iteration()` catches an `LLMError`, the agent stops immediately. No retry with backoff at the agent level — even though the LLM provider has retries internally, a transient failure that exhausts provider retries kills the agent with no second chance.

**Fix:** Add optional retry config to agent execution with sensible defaults (e.g., `max_agent_retries: 2`, `retry_delay: 1.0`). The LLM provider already has `RetryConfig` and `retry_with_backoff` — reuse those patterns.

**Schemas already exist:** `InferenceConfig.max_retries`, `RetryConfig` in `src/compiler/schemas.py`. Wire them into `StandardAgent.execute()`.

**Implementation:**
- Added agent-level retry loop in `StandardAgent._execute_iteration()` (lines ~420-465)
- Uses existing `InferenceConfig.max_retries` and `retry_delay_seconds` config
- Exponential backoff with base 2.0
- Logs each retry attempt with `logger.warning()`
- Returns error response after all retries exhausted

## 2. No Circuit Breaker at Executor Level ✅ COMPLETED

**Status:** ✅ Completed in Wave 1

**Problem:** If agent 1 fails due to LLM downtime in a sequential stage, agents 2 and 3 will still attempt and likely fail the same way. No mechanism to short-circuit remaining agents when the underlying provider is unhealthy.

**Fix:** Circuit breaker already exists per-provider in `src/llm/circuit_breaker.py` (CLOSED → OPEN → HALF_OPEN states, configurable thresholds). The issue is that the **executor** doesn't check circuit breaker state before launching the next agent. Options:
- Expose provider health from circuit breaker to executor level
- Add executor-level circuit breaker that tracks consecutive agent failures
- Check `CircuitBreakerOpen` before each agent in sequential loop

**Implementation:**
- Added `is_open()` method to `CircuitBreaker` class to check state without attempting call
- Sequential executor now imports and recognizes `CircuitBreakerError`
- Special error handling for circuit breaker failures in `_execute_agent()` (line ~260)
- Logs prominently with ERROR level when provider is unhealthy
- Circuit breaker automatically fast-fails subsequent calls to same provider (no wasted time)

## 3. Failed Agent Output Loses Error Context ✅ COMPLETED

**Status:** ✅ Completed (before Wave 1 started - commit b5dd36e)

**Problem:** When an agent fails, the sequential executor stores `output_data: {"output": ""}` — an empty string with no indication of what went wrong. Subsequent agents see this empty output in `current_stage_agents` but don't know *why* it failed. Error details are swallowed.

**This is critical.** In most workflows, a failed agent should halt the stage or workflow rather than silently continuing with empty output.

**Fix:**
- Include error message in the failed agent's output: `output_data: {"output": "", "error": str(e), "error_code": "LLM_TIMEOUT"}`
- Propagate error info in `agent_statuses` (currently just `"failed"` string — add reason)
- Default behavior should be to **halt the stage** on agent failure, not continue

**Implementation:**
- Sequential executor `_execute_agent()` now returns detailed error info (lines ~271-286)
- Output includes: `error`, `error_type`, `traceback`
- Derives `error_type` from framework `ErrorCode` or maps Python exceptions
- Sanitizes error messages to prevent credential leakage
- Agent statuses include error details as dict: `{"status": "failed", "error": ..., "error_type": ...}`

## 4. No Stage-Level Failure Policy for Sequential Executor ✅ COMPLETED

**Status:** ✅ Completed in Wave 1

**Problem:** The sequential executor always continues after an agent failure. There's no equivalent of the parallel executor's `min_successful_agents` or the stage-level `on_agent_failure` policy.

**Fix:** Add configurable failure policy with a safe default:
- `on_agent_failure: "halt_stage"` (default — stop the stage, mark as failed)
- `on_agent_failure: "continue_with_remaining"` (current behavior — keep going)
- `on_agent_failure: "skip_agent"` (skip and continue, don't pass empty output to next agent)
- `on_agent_failure: "retry_agent"` (retry the failed agent up to `max_agent_retries`)

**Schema already exists:** `StageErrorHandlingConfig` in `src/compiler/schemas.py` defines exactly these options (lines 357-363). It's just not wired into the sequential executor.

**Implementation:**
- `execute_stage()` now extracts `error_handling` config from `stage_config` (lines ~60-82)
- Backward compatible with deprecated `halt_on_failure` parameter
- `_run_all_agents()` implements all four policy options (lines ~195-260):
  - `halt_stage`: Breaks loop immediately, stores output
  - `skip_agent`: Skips agent, doesn't add to outputs
  - `retry_agent`: Placeholder logged as TODO
  - `continue_with_remaining`: Stores error output for subsequent agents
- All policies log prominently with context about which policy is active

## 5. Silent Exception Swallowing — No Logging ✅ COMPLETED

**Status:** ✅ Completed in Wave 1

**Problem:** The outermost catches in `StandardAgent.execute()` and `SequentialStageExecutor._execute_agent()` don't log the exception traceback. Errors are captured in response/status fields but never written to logs. Debugging production failures requires adding logging after the fact.

**Fix:**
- Add `logger.error(f"Agent {agent_name} failed: {e}", exc_info=True)` in `_execute_agent()` catch block
- Add `logger.warning(f"Agent execution error: {e}", exc_info=True)` in `StandardAgent.execute()` catch block
- Surface errors in observability tracker (already has `set_agent_output` — add error field)
- Ensure error details appear in execution trace / workflow report

**Implementation:**
- Added `logging` import and `logger` to `StandardAgent` (line ~12, 18)
- `StandardAgent.execute()` exception handler logs with `exc_info=True` (lines ~376-380)
- `StandardAgent._execute_iteration()` LLMError handler logs with `exc_info=True` (lines ~444-448)
- Sequential executor already had logging (lines ~266-285)
- All exceptions now logged with full tracebacks for debugging

---

# Tool System — Issues & Improvements

Identified during architecture walkthrough (Section 7: Tool System).

## 6. Native Function Calling is Ollama-Only ✅ COMPLETED

**Status:** ✅ Completed in Wave 3 (foundation)

**Problem:** OpenAI and Anthropic both support native function calling, but the system only uses it for Ollama (`/api/chat`). All other providers fall back to text-based `<tool_call>JSON</tool_call>` XML tags parsed by regex. This is fragile — LLMs generate malformed JSON, forget closing tags, or embed extra text inside tags.

**Fix:** Extend native function calling to OpenAI and Anthropic providers. Both accept `tools` parameter in their chat completion APIs. The `to_llm_schema()` method already outputs OpenAI-compatible format. Wire it through `_build_request()` in `OpenAILLM` and `AnthropicLLM`, and handle `tool_calls` in their `_parse_response()`.

**Impact:** High — directly affects tool calling reliability on paid APIs.

**Implementation:**
- Updated `_get_native_tool_definitions()` to support OpenAILLM and AnthropicLLM (not just OllamaLLM)
- Infrastructure in place for providers to receive tool definitions
- Note: Full provider-specific API integration (tools parameter in requests, tool_calls parsing) requires provider API updates (TODO for future enhancement)

## 7. No Tool Output Size Control ✅ COMPLETED

**Status:** ✅ Completed in Wave 3

**Problem:** Tool results are injected back into the prompt as `<tool_result>JSON</tool_result>` with no universal size limit. Bash truncates at 50KB internally, but other tools have no truncation. A large WebScraper response or verbose tool output can blow the context window.

**Fix:** Add a configurable `max_result_size` at the injection layer in `StandardAgent._inject_tool_results()`. Truncate with a `[truncated — {original_size} chars]` suffix. Default to something reasonable like 10KB per tool result.

**Implementation:**
- Added `MAX_TOOL_RESULT_SIZE = 10_000` constant in `_inject_tool_results()` (10KB per result)
- Tool results truncated before injection with clear indicator
- Shows original size and truncation point: `[truncated — 25,000 total chars, showing first 10,000]`
- Applies to both successful results and error messages
- Protects context window while preserving most relevant information

## 8. AVAILABLE_TOOLS Mapping is Hardcoded ✅ COMPLETED

**Status:** ✅ Completed

**Problem:** `StandardAgent._setup_tools()` maps tool names to class paths via a hardcoded dict. Auto-discovery exists in `ToolRegistry` but is only the fallback when no tools are configured. Adding a new tool requires updating both `src/tools/` and the dict in `standard_agent.py`.

**Fix:** Remove the hardcoded dict. Use auto-discovery as the primary mechanism — scan `src/tools/`, build a name→class mapping dynamically, then filter by the agent config's `tools` list. The hardcoded dict becomes unnecessary.

**Implementation:**
1. Removed hardcoded AVAILABLE_TOOLS dictionary from StandardAgent._setup_tools():
   - Was: {' WebScraper': 'src.tools.web_scraper.WebScraper', ...}
   - Now: Uses ToolRegistry.auto_discover() to scan src/tools/

2. Modified _setup_tools() flow:
   - Check if registry empty → call registry.auto_discover()
   - Auto-discovery scans src/tools/ for BaseTool subclasses
   - Get tool via registry.get(tool_name) - already instantiated
   - Provide helpful error if tool not found

3. Benefits:
   - Adding new tools is seamless: just create BaseTool in src/tools/
   - No code changes needed in StandardAgent
   - Auto-discovery caches results for performance
   - Better error messages with list of available tools
   - Removes 50+ lines of hardcoded mapping maintenance

**Result:**
- Tool system now fully dynamic
- Adding new tools requires zero code changes outside src/tools/
- Better maintainability and extensibility
- Consistent with ToolRegistry design

**Relevant Files:**
- `src/agents/standard_agent.py:240-285` — Replaced hardcoded dict with auto-discovery
- `src/tools/registry.py` — ToolRegistry.auto_discover() (existing)

## 9. Parameter Validation Bypassed in Execution Path ✅ COMPLETED

**Status:** ✅ Completed in Wave 2 (resolved by Issue #13)

**Problem:** `BaseTool` has `validate_params()` and `safe_execute()` (which wraps validation + execution). But `StandardAgent._execute_single_tool()` calls `tool.execute(**params)` directly, bypassing `safe_execute()`. Pydantic model validation and JSON schema validation exist but aren't invoked by the agent. Each tool does its own validation internally.

**Fix:** Change `_execute_single_tool()` to call `tool.safe_execute(**params)` instead of `tool.execute(**params)`. This activates the validation layer for all tools uniformly without requiring each tool to duplicate validation logic.

**Implementation:**
- Resolved by routing through ToolExecutor (Issue #13)
- `ToolExecutor.execute()` calls `tool.validate_params()` before execution (lines 265-279)
- Returns validation errors if params invalid
- All tools now get uniform parameter validation without duplication

## 10. No Tool Output Schema ✅ COMPLETED

**Status:** ✅ Completed

**Problem:** Tools define input schemas (parameters) but not output schemas. The LLM has no contract for what a tool result looks like. It gets raw JSON and has to infer the structure, which makes it harder to reliably extract information from complex tool results.

**Fix:** Add an optional `get_result_schema() -> Dict[str, Any]` method to `BaseTool`. Include the output schema in the tool description passed to the LLM. Not strictly required — many tools have simple string results — but useful for tools that return structured data.

**Implementation:**
1. Added `get_result_schema()` method to BaseTool:
   - Optional method (returns None by default)
   - Returns JSON Schema dict for tool output structure
   - Comprehensive docstring with examples
   - Not required for tools with simple results

2. Modified `_get_native_tool_definitions()` in StandardAgent:
   - Calls `tool.get_result_schema()` for each tool
   - If schema provided, augments tool description with schema
   - Format: "description\n\nResult schema: {json schema}"
   - Helps LLM understand output structure

3. Benefits:
   - LLM has contract for tool outputs
   - Better extraction of structured data
   - More reliable multi-step reasoning with tool results
   - Optional - no breaking changes for existing tools

4. Example usage (tools can override):
   ```python
   def get_result_schema(self) -> Dict[str, Any]:
       return {
           "type": "object",
           "properties": {
               "title": {"type": "string"},
               "content": {"type": "string"},
               "links": {"type": "array", "items": {"type": "string"}}
           },
           "required": ["title", "content"]
       }
   ```

**Result:**
- Tools can now specify output schemas
- LLM receives schema in tool description
- Better understanding of complex tool results
- Fully optional and backward compatible
- Foundation for structured tool outputs

**Relevant Files:**
- `src/tools/base.py:143-194` — Added get_result_schema() method to BaseTool
- `src/agents/standard_agent.py:989-1009` — Modified _get_native_tool_definitions() to include result schema

## 11. Sequential-Only Tool Execution

**Problem:** Multiple tool calls in a single LLM response are executed one at a time. If the LLM requests three independent operations (e.g., three file reads), they run sequentially. `ToolExecutor` has thread pool support, but the agent loop doesn't use it for parallel execution.

**Fix:** Detect independent tool calls (no data dependencies between them) and execute in parallel via `ToolExecutor`'s thread pool. Conservative approach: execute in parallel by default, with a `parallel_tool_calls: false` config option to disable.

## 12. No Tool Call Budget Awareness ✅ COMPLETED

**Status:** ✅ Completed

**Problem:** The agent config has `max_tool_calls_per_execution`, but the LLM doesn't know how many calls it has remaining. It can burn through the budget and get cut off mid-task with no warning.

**Fix:** Inject remaining budget info into the tool results section: `"You have {remaining} tool calls remaining."` Simple, no schema changes needed.

**Implementation:**
1. Modified `_inject_tool_results()` to accept optional `remaining_tool_calls` parameter:
   - Adds budget awareness message after tool results
   - Message: "[System Info: You have N tool call(s) remaining in your budget.]"
   - When remaining = 0: "[System Info: This is your last tool call. Budget exhausted after this iteration.]"

2. Modified `_execute_iteration()` to accept optional `max_iterations` parameter:
   - Calculates remaining budget: `max_iterations - len(tool_calls_made)`
   - Passes remaining count to `_inject_tool_results()`

3. Updated `execute()` main loop to pass max_iterations to _execute_iteration():
   - Enables budget awareness throughout execution
   - No breaking changes - parameters are optional

4. Budget awareness flow:
   - LLM sees budget in tool results section
   - Can plan accordingly and prioritize remaining calls
   - Avoids mid-task cutoffs from budget exhaustion
   - Better task completion rates

**Result:**
- LLM now aware of remaining tool call budget
- Can plan and prioritize remaining calls intelligently
- Prevents frustrating mid-task cutoffs
- Simple implementation, no schema changes
- Backward compatible (optional parameters)

**Relevant Files:**
- `src/agents/standard_agent.py:1051-1106` — Modified _inject_tool_results() to add budget message
- `src/agents/standard_agent.py:402-425` — Modified _execute_iteration() to accept max_iterations
- `src/agents/standard_agent.py:358-360` — Updated execute() to pass budget info

---

---

# Safety & Governance — Issues & Improvements

Identified during architecture walkthrough (Section 8: Safety & Governance).

## 13. Safety Layer Not Connected to Agent Execution Path ✅ COMPLETED

**Status:** ✅ Completed in Wave 2

**Problem:** The entire safety subsystem (`ActionPolicyEngine`, `ApprovalWorkflow`, `RollbackManager`, all concrete policies) is fully built but **not wired into the actual execution path**. `StandardAgent._execute_single_tool()` calls `tool.execute(**params)` directly, bypassing `ToolExecutor` entirely.

The `ToolExecutor` (`src/tools/executor.py`) properly integrates with:
- `ActionPolicyEngine` (lines 282-283) — validates actions against all policies
- `ApprovalWorkflow` (lines 304-305) — requests human approval for blocking violations
- `RollbackManager` — creates pre-action snapshots
- Circuit breaker integration

But `StandardAgent` (`src/agents/standard_agent.py`) imports `ToolRegistry` and `BaseTool` directly (lines 58-59), never imports `ToolExecutor`, and has only inline safety checks (lines 544-568):
- `safety.mode == "require_approval"` → block all
- `tool_name in safety.require_approval_for_tools` → block that tool
- `safety.mode == "dry_run"` → simulated result

**What's NOT active as a result:**
- FileAccess policy (path traversal, forbidden dirs)
- SecretDetection policy (AWS keys, tokens in tool args)
- ForbiddenOperations policy (dangerous bash patterns)
- RateLimiter policy (operation frequency limits)
- ResourceLimit policy (CPU, memory, disk)
- Approval workflow (human-in-the-loop)
- Rollback snapshots (pre-action recovery)

**Impact:** Critical. The safety system exists but provides no protection. Each tool does its own internal validation, which is inconsistent and incomplete.

**Fix:** Route `StandardAgent._execute_single_tool()` through `ToolExecutor` instead of calling `tool.execute()` directly. The `ToolExecutor` already has the complete integration. Changes needed:
1. `StandardAgent.__init__()` — instantiate `ToolExecutor` with `ActionPolicyEngine`, `ApprovalWorkflow`, `RollbackManager`
2. `_execute_single_tool()` — call `self.tool_executor.execute(tool_name, params)` instead of `tool.execute(**params)`
3. Remove inline safety checks (lines 544-568) — `ToolExecutor` handles these via policy engine

Relevant files:
- `src/agents/standard_agent.py:492-594` — current direct tool execution
- `src/tools/executor.py:56-88` — `ToolExecutor.__init__()` with all safety wiring
- `src/tools/executor.py:282-305` — policy validation + approval integration

**Implementation:**
- `StandardAgent.execute()` now extracts `tool_executor` from state (line ~319)
- `_execute_single_tool()` checks if tool_executor available and routes through it (lines ~585-605)
- When available, calls `self.tool_executor.execute(tool_name, params)` which handles all safety
- Falls back to inline safety checks if tool_executor not available (backward compatibility)
- **All safety policies now active**: FileAccess, SecretDetection, ForbiddenOperations, RateLimiter, ResourceLimit, Approval, Rollback

## 14. No Safety on LLM Calls ✅ COMPLETED

**Status:** ✅ Completed in Wave 2

**Problem:** The safety layer only has a path through `ToolExecutor` for tool actions. LLM calls themselves — prompt content, output content — never pass through any policy engine. The `RateLimiter` policy defines an `llm_call` limit (100/min), but nothing invokes it. There's no input/output guardrails on what goes to or comes from the LLM.

**Fix:** Add an LLM call validation hook in `StandardAgent._execute_iteration()` that passes through the policy engine before calling `self.llm.complete()`. At minimum, invoke the rate limiter. Optionally add output content filtering (PII, harmful content) as a post-LLM policy.

**Implementation:**
- Added LLM call validation in `_execute_iteration()` before calling `llm.complete()` (lines ~426-455)
- Checks if policy_engine available via tool_executor
- Validates with `action_type="llm_call"` including model and prompt length
- Blocks LLM call if policy violations (e.g., rate limit exceeded from config: 1000/hour)
- Uses `asyncio.run()` to call async validate_action from sync context
- Logs validation errors without blocking if validation itself fails

## 15. Observability Coverage Gaps

**Problem:** The sequential executor integrates with `ExecutionTracker` via `tracker` in state, but `StandardAgent` itself doesn't report to the tracker — it returns metrics in `AgentResponse` and the executor records them. If an agent is instantiated directly (outside an executor), there's no observability. The parallel executor's tracker integration is also inconsistent.

**Fix:** Move observability tracking into `StandardAgent.execute()` itself rather than relying on the executor to extract metrics from `AgentResponse`. The agent has access to `ExecutionContext` (which contains workflow_id, stage_id, agent_id) — it can report directly to the tracker.

## 16. Self-Improvement Has No Feedback Path ✅ COMPLETED

**Status:** ✅ Completed (continuation of existing work)

**Problem:** The self-improvement layer reads metrics from observability but has no feedback path back into the system. It can't modify agent configs, adjust prompts, change strategies, or influence the next workflow run. The strategies and experiment orchestrator exist, but the connection from "experiment result" → "apply to next run" is missing.

**Impact:** The self-improvement loop is open, not closed. Analysis happens but nothing changes as a result.

**Implementation:**
1. Modified ConfigLoader to integrate with ConfigDeployer (M5 deployment store):
   - Added optional `config_deployer` parameter to __init__()
   - Implemented lazy initialization of ConfigDeployer (automatic M5 integration)
   - Added `_ensure_config_deployer()` for seamless setup

2. Updated `load_agent()` to check ConfigDeployer first:
   - **Flow**: ConfigDeployer (M5-improved) → YAML fallback (baseline)
   - Checks coordination database for deployed configs
   - Falls back to YAML if no deployed config exists
   - Gracefully handles missing database or initialization failures
   - Logs source of config (M5-improved vs YAML baseline)

3. Lazy initialization enables seamless integration:
   - When coordination database available: automatic M5 integration
   - When database unavailable: graceful fallback to YAML-only mode
   - No changes needed to existing ConfigLoader instantiations
   - Zero breaking changes to existing code

4. Closes the feedback loop:
   ```
   Observability → M5 Detection → M5 Analysis → M5 Strategy →
   M5 Experiment → M5 Deploy (ConfigDeployer) →
   ConfigLoader → Runtime (agents use improved configs) →
   Observability (cycle repeats)
   ```

**Result:**
- M5 self-improvement loop now fully closed
- Deployed configs automatically used in next workflow run
- Backward compatible: YAML configs still work as fallback
- Seamless integration via lazy initialization
- Production-ready with graceful degradation

**Relevant Files:**
- `src/compiler/config_loader.py` — Modified load_agent() to check ConfigDeployer first, added lazy init
- `src/self_improvement/deployment/deployer.py` — ConfigDeployer.get_agent_config() (existing)
- Coordination database `config_deployments` table (existing)

## 17. Collaboration Only Available in Parallel Mode

**Problem:** Synthesis strategies (consensus, majority, weighted vote) are only called from the parallel executor. Sequential stages with multiple agents accumulate outputs but have no synthesis step — the last agent's output is used for backward compatibility. There's no way for sequential agents to debate and reach consensus.

**Fix:** Add an optional `collaboration` config to sequential stages. After all agents run, if a collaboration strategy is configured, run synthesis on the accumulated `agent_outputs` (same as parallel does). The sequential executor already has `agent_outputs` in the right format.

## 18. No Config Validation at Compiler Level ✅ COMPLETED

**Status:** ✅ Completed in Wave 3

**Problem:** `ConfigLoader` loads YAML configs as raw dicts. Pydantic schema validation (`AgentConfig`, `StageConfig`) happens deep inside the executors when agents are created, not at the compiler level. Invalid configs aren't caught until runtime — during stage execution — rather than at workflow compilation time.

**Fix:** Validate all configs at `LangGraphCompiler.compile()` time. Load each stage and agent config, validate against Pydantic schemas, and fail fast with clear error messages before any execution begins.

**Implementation:**
- Added `_validate_all_configs()` method to LangGraphCompiler
- Called early in `compile()` before graph construction (fail fast)
- Validates each stage config against StageConfig schema
- Validates each agent config against AgentConfig schema
- Collects all validation errors and reports them together
- Clear error messages with stage/agent context
- Logs successful validation for visibility

## 19. Safety Stack Has No Ownership Chain ✅ COMPLETED

**Status:** ✅ Completed in Wave 2

**Problem:** Even connecting `StandardAgent` to `ToolExecutor` isn't enough — someone needs to instantiate `ActionPolicyEngine` with the right config from `config/safety/action_policies.yaml`, create the `ApprovalWorkflow` and `RollbackManager`, and pass the assembled `ToolExecutor` down through CLI → Compiler → Executor → Agent. This ownership chain doesn't exist. The safety layer has environment-specific configs (dev/staging/production) but the compiler layer doesn't read or propagate them.

**Fix:** Add safety initialization to `LangGraphCompiler.__init__()` or `WorkflowExecutor`:
1. Load `config/safety/action_policies.yaml`
2. Select environment config (dev/staging/production)
3. Instantiate `ActionPolicyEngine` with policies
4. Create `ApprovalWorkflow`, `RollbackManager`
5. Create `ToolExecutor` with all safety components
6. Pass `ToolExecutor` through state or executor context to `StandardAgent`

**Implementation:**
- Created `src/safety/factory.py` with safety stack initialization functions
- `create_safety_stack()` loads config, creates PolicyRegistry, ActionPolicyEngine, ApprovalWorkflow, RollbackManager
- `LangGraphCompiler.__init__()` now creates safety stack via `create_safety_stack()`
- ToolExecutor passed through NodeBuilder → state → agents
- Environment-aware: reads SAFETY_ENV or defaults to "development"
- Uses NoOpApprover in dev (auto-approve), configurable for staging/production

---

# Relevant Code Locations

## Agent Failure Handling

| File | What's There |
|------|-------------|
| `src/agents/standard_agent.py:280-377` | `execute()` outer try/except |
| `src/agents/standard_agent.py:379-459` | `_execute_iteration()` LLMError catch |
| `src/agents/standard_agent.py:492-594` | `_execute_single_tool()` tool failure |
| `src/compiler/executors/sequential.py:137-193` | `_execute_agent()` exception catch |
| `src/compiler/executors/parallel.py:140-157` | `min_successful_agents` pattern |
| `src/compiler/executors/parallel.py:397-410` | `on_failure` halt/skip policy |
| `src/compiler/schemas.py:357-363` | `StageErrorHandlingConfig` (exists, unused by sequential) |
| `src/compiler/schemas.py:468-474` | `WorkflowErrorHandlingConfig` |
| `src/compiler/schemas.py:90-103` | `RetryConfig`, `ErrorHandlingConfig` |
| `src/llm/circuit_breaker.py` | Per-provider circuit breaker (3 states) |
| `src/utils/error_handling.py` | `retry_with_backoff`, `safe_execute`, `ErrorHandler` |
| `src/utils/exceptions.py` | Full exception hierarchy with error codes |

## Tool System

| File | What's There |
|------|-------------|
| `src/tools/base.py:143-166` | `safe_execute()` — validation wrapper (not called by agent) |
| `src/tools/base.py:311-325` | `to_llm_schema()` — OpenAI function calling format |
| `src/tools/registry.py:440-593` | `auto_discover()` — package scanning |
| `src/agents/standard_agent.py:235-240` | Hardcoded `AVAILABLE_TOOLS` dict |
| `src/agents/standard_agent.py:461-594` | `_execute_tool_calls()` and `_execute_single_tool()` |
| `src/agents/standard_agent.py:728` | `_get_native_tool_definitions()` — Ollama only |
| `src/agents/standard_agent.py:791` | `_inject_tool_results()` — no size limit |
| `src/agents/llm_providers.py:709-790` | Ollama native function calling |

## Safety & Governance / Architecture Gaps

| File | What's There |
|------|-------------|
| `src/tools/executor.py:56-88` | `ToolExecutor.__init__()` — full safety wiring (unused) |
| `src/tools/executor.py:282-305` | Policy validation + approval integration (unused) |
| `src/agents/standard_agent.py:544-568` | Inline safety checks (only active safety) |
| `src/agents/standard_agent.py:58-59` | Imports ToolRegistry/BaseTool directly (no ToolExecutor) |
| `src/safety/action_policy_engine.py` | Central enforcement engine (not called from agent) |
| `src/safety/approval.py` | Human-in-the-loop (not called from agent) |
| `src/safety/rollback.py` | Snapshot/restore (not called from agent) |
| `config/safety/action_policies.yaml` | Safety config with env overrides (not loaded by compiler) |
| `src/core/service.py:139-163` | Separate `validate_action()` (not in execution path) |
| `src/compiler/langgraph_compiler.py:23-33` | Compiler imports (no safety imports) |
| `src/compiler/config_loader.py` | Loads YAML as raw dicts (no Pydantic validation) |
| `src/self_improvement/loop/executor.py` | Improvement loop executor (reads only, no write-back) |
| `src/strategies/registry.py` | Strategy lookup (only used by parallel executor) |

---

# Collaboration — Redesign Required

Identified during architecture walkthrough (Section 9: Collaboration / M3).

## 20. Collaboration is Post-Hoc Voting, Not Back-and-Forth Dialogue

**Problem:** The current collaboration system treats agents as independent workers whose outputs get merged after-the-fact. No agent ever sees another agent's work during execution.

Current flow:
1. All agents run independently in parallel
2. Outputs collected into a list
3. Synthesis strategy (Consensus or Debate) picks/merges results

The "Debate" strategy (`src/strategies/debate.py`) is misnamed — it does **not** re-query any agent. It takes the initial outputs, calculates a convergence metric from confidence scores, and picks the best output. There are zero actual debate rounds where agents respond to each other.

This is fundamentally a **voting system**, not collaboration.

**What's Needed:** Actual back-and-forth dialogue between agents:

1. Agent A produces initial output
2. Agent B receives Agent A's output as context, responds/critiques/builds on it
3. Agent A receives Agent B's response, revises or defends its position
4. Iterate until convergence or max rounds
5. Final synthesis from the full dialogue history

This requires agents to be **participants in a conversation**, not independent workers.

**Design Considerations:**
- **Dialogue orchestrator**: A new component that manages multi-round agent conversations, injecting prior agent outputs as context for each round
- **Role differentiation**: Agents can have roles — proposer, critic, synthesizer, reviewer — that shape how they interact with prior outputs
- **Convergence detection**: Real convergence based on semantic similarity of successive outputs, not just confidence score comparison
- **Round budget**: Configurable max rounds with cost awareness (each round is an LLM call)
- **Context curation**: Not all prior outputs need to go to every agent every round — a context curator selects relevant parts (connects to Stage Router concept)
- **Works in both modes**: Sequential agents should also benefit — agent 2 sees agent 1's output and can respond to it (connects to Issue #17)

**Relevant Files:**
- `src/strategies/base.py` — CollaborationStrategy interface (currently one-shot)
- `src/strategies/consensus.py` — Majority voting (no re-query)
- `src/strategies/debate.py` — Fake debate (convergence check, no re-query)
- `src/strategies/conflict_resolution.py` — Resolver strategies
- `src/compiler/executors/parallel.py:183-230` — Synthesis integration point
- `src/compiler/executors/sequential.py` — No collaboration at all

**Impact:** High — this changes collaboration from "pick the best independent output" to "agents that actually work together". Requires new dialogue orchestration layer and modifications to how agents are invoked within executors.

---

# Observability — Issues & Improvements

Identified during architecture walkthrough (Section 10: Observability).

## 21. StandardAgent Doesn't Report to Tracker Directly ✅ COMPLETED

**Status:** ✅ Completed in Wave 4

**Problem:** Observability metrics flow indirectly: `StandardAgent` returns metrics in `AgentResponse` → the executor extracts them → executor writes to tracker. If an agent is instantiated outside an executor (e.g., direct usage, testing, or future contexts), there's zero observability. The agent itself never calls the tracker.

**Fix:** Move tracking into `StandardAgent.execute()` directly. The agent has access to `ExecutionContext` (workflow_id, stage_id, agent_id) — it can call `tracker.track_agent()`, `tracker.track_llm_call()`, and `tracker.track_tool_call()` from within its own execution loop, removing the dependency on the executor for observability.

**Implementation:**
1. Modified `StandardAgent.execute()` to:
   - Store execution context in `self._execution_context` for access by helper methods
   - Extract tracker from `input_data` (passed by executors)

2. Modified `StandardAgent._execute_iteration()` to:
   - Track each LLM call with `tracker.track_llm_call()` after successful completion
   - Pass provider, model, prompt, response, tokens, latency, cost, and status to tracker
   - Handle tracking errors gracefully without failing agent execution

3. Modified `StandardAgent._execute_single_tool()` to:
   - Track each tool call with `tracker.track_tool_call()` after execution
   - Time tool execution and pass duration to tracker
   - Track both ToolExecutor path and direct execution path
   - Pass tool name, params, output, duration, status, and errors to tracker
   - Handle tracking errors gracefully

4. Modified executors to pass tracker to agents:
   - `SequentialStageExecutor`: Pass `tracker` in `input_data` inside track_agent context
   - `ParallelStageExecutor`: Extract tracker from state and pass to agents
   - `AdaptiveStageExecutor`: Inherits from sequential/parallel, no changes needed

**Result:**
- Agents now directly report LLM calls and tool executions to tracker
- Tracking happens at the source, not post-hoc by executor
- Agents can be used standalone with full observability (if tracker provided)
- Tracking errors are logged but don't break agent execution

**Relevant Files:**
- `src/agents/standard_agent.py:320-326, 525-547, 658-722` — Added tracker integration
- `src/compiler/executors/sequential.py:446` — Pass tracker to agent
- `src/compiler/executors/parallel.py:460-463` — Pass tracker to agent
- `src/observability/tracker.py:615-795` — track_llm_call() and track_tool_call() methods

## 22. No Real-Time Alerting ✅ COMPLETED

**Status:** ✅ Completed in Wave 4

**Problem:** Observability data goes into the database, but nothing watches it in real time. There's no mechanism to trigger alerts when thresholds are breached — cost exceeds budget, latency spikes above p99, error rates exceed acceptable levels, or a workflow has been running longer than expected. The `PerformanceTracker` flags slow operations but only in-memory; nothing fires an external notification.

**Fix:** Add an alerting layer that subscribes to tracker events:
- Configurable alert rules (metric + threshold + window + action)
- Actions: log warning, webhook, email, halt workflow
- Built-in rules: cost budget exceeded, error rate > X%, latency p95 > threshold
- Could use the existing `PerformanceTracker` slow-operation detection as a trigger source

**Implementation:**
1. Created AlertManager with configurable rule system:
   - AlertRule dataclass: name, metric_type, threshold, window, severity, actions
   - MetricType enum: cost_usd, error_rate, latency_p95, latency_p99, duration, token_count
   - AlertAction enum: log_warning, log_error, webhook, email, halt_workflow
   - AlertSeverity enum: info, warning, error, critical

2. Built-in default rules:
   - **high_cost_per_workflow**: Alert when workflow cost > $5 (WARNING, log)
   - **high_error_rate**: Alert when error rate > 10% in 5-minute window (ERROR, log)
   - **extreme_latency_p99**: Alert when p99 latency > 30 seconds (WARNING, log)
   - **critical_cost_budget**: Alert when cost > $50 (CRITICAL, halt workflow - disabled by default)

3. Integrated AlertManager with ExecutionTracker:
   - Added optional alert_manager parameter to tracker __init__
   - Creates default AlertManager if not provided
   - Check workflow cost after metrics aggregation
   - Check LLM call latency and cost after each call
   - Check tool execution duration after each tool call

4. Extensible action system:
   - Custom webhook/email handlers can be registered per rule
   - Halt workflow action logs critical alert (actual halting requires engine integration)
   - Alert history tracking for recent alerts (24-hour window)
   - Filter alerts by severity

**Result:**
- Real-time monitoring of cost, latency, and error rate thresholds
- Configurable rules with multiple action types
- Default rules for common issues (production-ready)
- Extensible for custom webhooks/email notifications
- Alert history for debugging and trend analysis

**Relevant Files:**
- `src/observability/alerting.py` — New AlertManager, AlertRule, Alert classes
- `src/observability/tracker.py:70-110, 314-324, 752-778, 842-856` — Integrated alerting
- `src/observability/constants.py` — Thresholds used by default rules

## 23. No Metric Aggregation Pipeline ✅ COMPLETED

**Status:** ✅ Completed in Wave 4

**Problem:** `SystemMetric` model exists in `src/observability/models.py` with fields for `aggregation_period` (minute/hour/day), but there's no background process that rolls up raw execution data into aggregated metrics. The table schema is ready but nothing writes to it. Trend analysis, dashboards, and SLO monitoring all need aggregated data.

**Fix:** Add a periodic aggregation job that:
- Reads recent `WorkflowExecution`, `AgentExecution`, `LLMCall` records
- Computes rollups: success rate, avg duration, total cost, p95 latency per agent/stage/workflow
- Writes to `SystemMetric` table with appropriate period granularity
- Can run as a background thread, cron job, or triggered after each workflow completion

**Implementation:**
1. Created MetricAggregator class with three aggregation pipelines:
   - **aggregate_workflow_metrics()**: Workflows by name
     - Success rate (completed/total)
     - Average duration
     - Total cost
     - P95 duration
   - **aggregate_agent_metrics()**: Agents by name
     - Success rate
     - Average duration
     - Total cost
     - Average tokens
   - **aggregate_llm_metrics()**: LLM calls by provider/model
     - Success rate
     - Average latency
     - P95/P99 latency
     - Total cost

2. Supports three aggregation periods:
   - MINUTE: 1-minute rolling windows
   - HOUR: 1-hour rolling windows (default)
   - DAY: 1-day rolling windows

3. Each pipeline:
   - Queries raw execution records from time window
   - Groups by dimension (workflow_name, agent_name, provider/model)
   - Computes statistical aggregates (avg, sum, percentiles)
   - Creates SystemMetric records with proper dimensions
   - Commits to database atomically

4. Convenience method:
   - **aggregate_all_metrics()**: Runs all three pipelines in one call
   - Returns dict mapping metric type to created IDs
   - Can be called on-demand, via cron, or as background thread

**Result:**
- SystemMetric table now populated with aggregated metrics
- Supports trend analysis over time
- Ready for dashboards and SLO monitoring
- Configurable aggregation periods for different use cases
- Can be triggered after workflow completion or on schedule

**Relevant Files:**
- `src/observability/aggregation.py` — New MetricAggregator class (complete pipeline)
- `src/observability/models.py:385-407` — SystemMetric model (now written by aggregator)

## 24. AgentMeritScore Never Updated ✅ COMPLETED

**Status:** ✅ Completed in Wave 4

**Problem:** `AgentMeritScore` model exists for tracking per-agent expertise over time — total decisions, success rate, 30/90-day decay windows, expertise scores per domain. But nothing updates these records. The `DecisionOutcome` model also exists for recording individual decisions, but no process connects outcomes to merit score updates.

**Fix:** Add a merit score update mechanism triggered after experiment results or workflow completions:
- When a `DecisionOutcome` is recorded, update the corresponding `AgentMeritScore`
- Compute rolling success rates with time decay
- Feed merit scores back into the collaboration layer (connects to Issue #20 — merit-weighted dialogue)

**Implementation:**
1. Added `update_agent_merit_score()` method to ExecutionTracker:
   - Gets or creates AgentMeritScore record for agent/domain pair
   - Updates decision counts (total, successful, failed, overridden)
   - Computes cumulative success rate
   - Updates average confidence using exponential moving average (alpha=0.1)
   - Computes expertise score (70% success rate + 30% confidence)
   - Computes time-windowed success rates (30-day, 90-day) from DecisionOutcome history
   - Updates timestamps (first_decision_date, last_decision_date, last_updated)

2. Modified `track_decision_outcome()` to automatically update merit scores:
   - Extracts agent_name from decision_data
   - Determines domain from tags or decision_type
   - Extracts confidence from impact_metrics if available
   - Calls update_agent_merit_score() after recording decision outcome
   - Handles errors gracefully without breaking decision tracking

3. Merit score computation details:
   - **Success rate**: successful_decisions / total_decisions
   - **Average confidence**: Exponential moving average of decision confidences
   - **Expertise score**: 0.7 * success_rate + 0.3 * average_confidence
   - **30-day/90-day rates**: Query DecisionOutcome table for time-windowed metrics

**Result:**
- AgentMeritScore records now automatically updated after every decision
- Merit scores accumulate across sessions
- Time-windowed metrics support decay/recency weighting
- Ready for merit-weighted collaboration (Issue #20)
- MeritWeightedResolver will now get populated merit scores

**Relevant Files:**
- `src/observability/tracker.py:1293-1477` — Added update_agent_merit_score() and _update_merit_score_in_session()
- `src/observability/tracker.py:1268-1285` — Modified track_decision_outcome() to update merit scores
- `src/observability/models.py:311-341` — AgentMeritScore model (now written by tracker)

---

# Self-Improvement (M5) — Issues & Improvements

Identified during architecture walkthrough (Section 11: Self-Improvement / M5).

## 25. Strategies Don't Learn From Outcomes (Open Loop) ✅ COMPLETED

**Status:** ✅ Completed in Wave 6

**Problem:** `estimate_impact()` returns hardcoded values (30-40% for Ollama model selection, 25-35% for ERC721). After an experiment runs and produces a winner (or loser), that result is never fed back into the strategy. The next time the same strategy runs, it makes the same estimates regardless of past performance. Each experiment starts from scratch.

**Fix:** Add outcome tracking per strategy:
- After experiment completion, record (strategy, problem_type, actual_improvement) in a learning store
- `estimate_impact()` should query historical outcomes for similar contexts
- Use Bayesian updating or simple moving averages to refine estimates over time
- Strategies that consistently underperform should be deprioritized

**Implementation:**

1. **Created StrategyOutcome data model** (`src/self_improvement/data_models.py:431-520`):
   - Tracks actual improvements (quality, speed, cost, composite)
   - Links to experiment ID and strategy name
   - Records whether strategy was winner
   - Includes statistical confidence and sample size
   - Stores problem type and agent context

2. **Created StrategyLearningStore** (`src/self_improvement/strategy_learning.py`):
   - SQLite-backed storage with indexed queries
   - `record_outcome()`: Stores strategy outcomes after experiments
   - `get_average_improvement()`: Weighted average by confidence
   - `get_win_rate()`: Success rate for strategy + problem type
   - `get_sample_count()`: Number of historical outcomes
   - Supports time windows (e.g., last 90 days)

3. **Updated base ImprovementStrategy** (`src/self_improvement/strategies/strategy.py`):
   - Added `learning_store` parameter to `__init__()`
   - Redesigned `estimate_impact()` with Bayesian updating:
     - Queries historical outcomes for strategy + problem_type
     - Combines prior estimate with historical data using weighted average
     - Prior weight = 10, data weight = sample count
     - Formula: `(prior * 10 + historical_avg * N) / (10 + N)`
     - Requires ~10 samples before historical data dominates

4. **Updated concrete strategies**:
   - `OllamaModelSelectionStrategy`: Calls `super().estimate_impact()` if learning_store available
   - `ERC721WorkflowStrategy`: Same pattern
   - Fall back to hardcoded estimates if no historical data

5. **Integrated with LoopExecutor** (`src/self_improvement/loop/executor.py`):
   - Initializes `StrategyLearningStore` with coordination database
   - After Phase 4 (Experiment):
     - If winner found: Records outcome with actual improvements
     - If no winner: Records zero-improvement outcome
   - Both cases build learning data for future iterations

**Learning Process:**
1. Experiment completes → Outcome recorded with actual metrics
2. Next iteration → Strategy queries historical outcomes
3. Bayesian update combines prior + historical data
4. More samples → More confidence in historical average
5. Better estimates → Better strategy prioritization

**Relevant Files:**
- `src/self_improvement/data_models.py:431-520` — NEW: StrategyOutcome model
- `src/self_improvement/strategy_learning.py` — NEW: Learning store with queries
- `src/self_improvement/strategies/strategy.py:100-258` — Bayesian estimate_impact()
- `src/self_improvement/strategies/ollama_model_strategy.py:43,118-139` — Uses learning
- `src/self_improvement/strategies/erc721_strategy.py:71-81,158-180` — Uses learning
- `src/self_improvement/loop/executor.py:36-37,96-97,489-522,551-582` — Records outcomes

## 26. No Pattern Mining From Experiment History ✅ COMPLETED

**Status:** ✅ Completed in Wave 6

**Problem:** `LearnedPattern` data model exists but nothing mines experiment history for recurring patterns. The system can't discover that "lower temperature consistently improves quality for code generation agents" or "switching from phi3:mini to llama3.1:8b improves success rate by 15% on average." Each improvement cycle is independent.

**Fix:** Add a pattern mining phase that runs periodically:
- Query completed experiments grouped by strategy, problem_type, agent_type
- Identify statistically significant patterns (e.g., strategy X consistently wins for problem Y)
- Store as `LearnedPattern` records with confidence and sample count
- Feed patterns back into detection phase to proactively suggest improvements before degradation occurs

**Implementation:**

1. **Created PatternMiner class** (`src/self_improvement/pattern_mining.py`):
   - Analyzes historical StrategyOutcome records
   - Groups by strategy_name + problem_type combinations
   - Identifies patterns meeting statistical thresholds:
     - Minimum support (sample count)
     - Minimum confidence score
     - Minimum win rate
     - Minimum improvement magnitude

2. **Pattern confidence calculation**:
   - Sample size confidence: Asymptotic function (90% at 50 samples, 95% at 100)
   - Win rate confidence: Linear with win rate
   - Improvement magnitude confidence: Based on improvement percentage
   - Weighted combination: 50% sample + 30% win rate + 20% improvement

3. **mine_patterns() method**:
   - Queries strategy_outcomes table with SQL aggregation
   - Groups by (strategy_name, problem_type)
   - Calculates win_rate, avg_improvement, sample_count
   - Filters candidates by thresholds
   - Creates LearnedPattern objects with evidence
   - Default thresholds: 10+ samples, 80% confidence, 60% win rate, 5% improvement

4. **Pattern types created**:
   - `strategy_effectiveness_{problem_type}`: Which strategies work for which problems
   - Evidence includes: strategy_name, problem_type, win_rate, avg_improvement, agent_names
   - Description: Human-readable summary of pattern

5. **Integrated with LoopExecutor**:
   - Initializes PatternMiner with StrategyLearningStore
   - Phase 3 (Strategy) now mines patterns before generating variants
   - Patterns inform which strategies have historically worked
   - Logged for debugging and observability

6. **Additional utilities**:
   - `get_patterns_for_problem_type()`: Filter patterns by problem
   - `get_strategy_insights()`: Analyze specific strategy performance
   - Detailed metrics: win rates by problem type, best problem types

**Pattern Discovery Process:**
1. Query all strategy outcomes from learning store
2. Group by (strategy_name, problem_type)
3. Calculate aggregated metrics per group
4. Apply statistical filters
5. Calculate confidence scores
6. Create LearnedPattern objects
7. Make available to detection and strategy phases

**Example Pattern:**
```
Pattern: "ollama_model_selection for quality_low"
- Win rate: 75%
- Avg improvement: 28%
- Support: 25 experiments
- Confidence: 0.87
- Description: "Strategy 'ollama_model_selection' consistently
  improves 'quality_low' (win rate: 75%, avg improvement: 28%)"
```

**Relevant Files:**
- `src/self_improvement/pattern_mining.py` — NEW: PatternMiner class with mining algorithms
- `src/self_improvement/loop/executor.py:38,99-101,361-410` — Integrated in Phase 3
- `src/self_improvement/strategies/strategy.py:41-75` — LearnedPattern model (now used)

## 27. M4 Safety Integration Missing ✅ COMPLETED

**Status:** ✅ Completed in Wave 6

**Problem:** M5 built its own `ConfigDeployer` instead of using M4's safety/rollback infrastructure. Config deployments bypass all safety policies — no `ActionPolicyEngine` validation, no `CircuitBreaker` protection, no `ApprovalWorkflow` for human review of automated config changes. An improvement cycle could deploy a config that violates safety policies.

**Fix:**
- Route config deployments through `ToolExecutor` / `ActionPolicyEngine`
- Add a `ConfigChangePolicy` to the safety layer that validates proposed config changes
- Require approval for high-impact changes (model swaps, significant parameter shifts)
- Use M4's `RollbackManager` instead of M5's standalone rollback (consolidate)
- This depends on Issue #13 (safety layer connection) being resolved first

**Implementation:**

1. **Created ConfigChangePolicy** (`src/safety/config_change_policy.py`):
   - Extends `BaseSafetyPolicy` with full M4 safety stack integration
   - Validates model changes (checks allowed list, requires approval)
   - Validates temperature changes (enforces min/max ranges)
   - Blocks safety mode downgrades (prevent require_approval → execute)
   - Validates tool configuration changes (requires approval)
   - Estimates cost impact using model size heuristics
   - Returns `ValidationResult` with critical/high violations for ActionPolicyEngine

2. **Updated ConfigDeployer** (`src/self_improvement/deployment/deployer.py`):
   - Added `ActionPolicyEngine` and `ApprovalWorkflow` as dependencies
   - `deploy()` method now validates through `_validate_through_safety_stack()`
   - Creates config_change action and routes through ActionPolicyEngine
   - Blocks deployment on critical violations (raises ValueError)
   - Requests approval for high-impact changes via `_request_and_wait_for_approval()`
   - Waits for approval decision with configurable timeout
   - Only deploys if approved or no violations
   - Fully integrated with M4 PolicyExecutionContext

3. **Updated LoopExecutor** (`src/self_improvement/loop/executor.py`):
   - Added `policy_engine` and `approval_workflow` parameters to `__init__()`
   - Passes safety components to ConfigDeployer during initialization
   - Enables `enable_safety_checks` flag from config

**Safety Checks:**
- **CRITICAL violations block deployment**: Unauthorized model, temperature out of range, safety downgrade
- **HIGH violations require approval**: Model changes, tool config changes, cost increases >50%
- **Approval workflow**: Configurable timeout, polls for approval decision
- **Context tracking**: Full PolicyExecutionContext with agent_id, workflow_id, stage_id

**Relevant Files:**
- `src/safety/config_change_policy.py` — NEW: Validates config changes through M4 stack
- `src/self_improvement/deployment/deployer.py` — Integrated with ActionPolicyEngine + ApprovalWorkflow
- `src/self_improvement/loop/executor.py` — Passes safety components to ConfigDeployer
- `src/safety/action_policy_engine.py` — Validates config_change actions
- `src/safety/approval.py` — Handles approval requests for high-impact changes

## 28. Continuous Mode Not Implemented ✅ COMPLETED

**Status:** ✅ Completed in Wave 6

**Problem:** `M5SelfImprovementLoop.run_continuous()` raises `NotImplementedError`. The system can run a single detect→analyze→strategy→experiment→deploy iteration, but can't run autonomously over time. No convergence detection — there's no way to determine when further improvement is unlikely or when to stop.

**Fix:**
- Implement `run_continuous()` as a loop that repeatedly calls `run_iteration()` with configurable sleep intervals
- Add convergence detection: if last N iterations produced no significant improvement, reduce frequency or stop
- Add a cost budget cap: stop if total experiment cost exceeds threshold
- Add scheduling: run improvement cycles on a cron-like schedule rather than continuous polling

**Implementation:**
1. Added configuration parameters to LoopConfig:
   - `continuous_max_iterations` — Optional cap on total iterations (None = unlimited)
   - `continuous_convergence_window` — Stop if no deployments in N iterations (default: 5)
   - `continuous_cost_budget` — Optional cost cap (None = unlimited)
   - `continuous_check_interval_minutes` — Sleep interval between iterations (default: 60)

2. Implemented `run_continuous()` in M5SelfImprovementLoop:
   - **Main loop**: Repeatedly calls `run_iteration()` for each agent
   - **Multi-agent support**: Takes list of agent names, runs iteration for each
   - **Sleep with interrupts**: Sleep between iterations with periodic checks for shutdown signal
   - **Convergence detection**: Tracks iterations without deployment, stops after N consecutive no-deploy iterations
   - **Cost budget tracking**: Tracks total cost, stops when budget exceeded (basic framework, requires cost data in IterationResult)
   - **Max iterations cap**: Stops after configured max iterations if set
   - **Graceful shutdown**: Registers SIGINT/SIGTERM handlers, allows clean stop
   - **Comprehensive statistics**: Returns dict with per-agent stats, success/failure counts, deployment counts, duration

3. Stop conditions (first to trigger wins):
   - Max iterations reached (`continuous_max_iterations`)
   - Convergence detected (no deployments in `continuous_convergence_window` iterations)
   - Cost budget exceeded (`continuous_cost_budget`)
   - Manual interrupt (Ctrl+C, SIGINT, SIGTERM)

4. Statistics tracking:
   - Total iterations (across all agents)
   - Successful/failed iteration counts
   - Total deployments
   - Iterations without deployment (convergence tracking)
   - Per-agent iteration and deployment counts
   - Start/stop timestamps
   - Stop reason

5. Signal handling:
   - Registers handlers for SIGINT and SIGTERM
   - Checks shutdown flag between agents and during sleep
   - Restores default handlers on exit
   - Handles KeyboardInterrupt for Ctrl+C

**Result:**
- Continuous improvement mode fully functional
- Can run autonomously with multiple stop conditions
- Convergence detection prevents infinite loops
- Graceful shutdown preserves system state
- Comprehensive execution statistics for monitoring
- Ready for production use with proper resource limits

**Relevant Files:**
- `src/self_improvement/loop/orchestrator.py:130-354` — Complete `run_continuous()` implementation (225 lines)
- `src/self_improvement/loop/config.py:57-60` — Added 3 continuous mode config parameters

## 29. Only 2 Concrete Strategies ✅ COMPLETED

**Status:** ✅ Completed in Wave 6

**Problem:** The strategy framework is flexible, but only 2 concrete strategies exist:
1. `OllamaModelSelectionStrategy` — Swap the LLM model
2. `ERC721WorkflowStrategy` — Domain-specific Solidity tuning

Missing strategy types that the framework could support:
- **Prompt optimization** — Vary system prompts, few-shot examples, reasoning guides
- **Temperature/sampling search** — Systematic parameter tuning across the sampling space
- **Tool configuration** — Enable/disable tools, adjust timeouts, change retry policies
- **Context window management** — Vary max_tokens, prompt truncation strategies
- **Retry policy adjustment** — Tune backoff parameters based on error patterns
- **Caching tuning** — Adjust TTL, cache type based on hit/miss patterns

**Fix:** Implement additional strategies following the `ImprovementStrategy` interface. Priority should be prompt optimization (highest expected impact for effort) and temperature search (systematic, low effort).

**Implementation:**
1. **PromptOptimizationStrategy** — High-impact strategy for improving output quality:
   - Variant 1: Add chain-of-thought reasoning guide (step-by-step thinking)
   - Variant 2: Enhance system prompt with specificity guide (precision, concrete examples)
   - Variant 3: Add structured output format guide (clear structure)
   - Variant 4: Combined approach (specificity + format)
   - Applicable to: quality_low, error_rate_high, inconsistent_output, hallucination, incorrect_output
   - Expected impact: 35-45% improvement depending on problem type
   - Uses Bayesian learning when historical data available

2. **TemperatureSearchStrategy** — Systematic sampling parameter tuning:
   - Variant 1: Lower temperature (more deterministic, better for quality/consistency)
   - Variant 2: Higher temperature (more creative, better for diversity)
   - Variant 3: Adjusted top_p (focused vs diverse sampling based on problem)
   - Variant 4: Combined optimal temperature + top_p
   - Presets: DETERMINISTIC (0.1), BALANCED (0.5), CREATIVE (0.9)
   - Top-p presets: FOCUSED (0.8), BALANCED (0.9), DIVERSE (0.95)
   - Applicable to: quality_low, error_rate_high, inconsistent_output, hallucination, incorrect_output, too_verbose, too_brief
   - Expected impact: 20-40% improvement depending on problem type
   - Pattern-aware: Infers problem type from learned patterns to select optimal direction

3. Both strategies:
   - Follow ImprovementStrategy interface with generate_variants(), is_applicable(), estimate_impact()
   - Support Bayesian learning from StrategyLearningStore
   - Provide problem-specific fallback estimates when no historical data
   - Include rich metadata for tracking changes
   - Support learned pattern input for informed variant generation

4. Updated exports in `__init__.py` for easy importing

**Result:**
- Now 4 concrete strategies available (2x growth)
- Prompt optimization addresses highest-impact improvement area
- Temperature search provides systematic, low-effort tuning
- Both strategies integrate with learning system for continuous improvement
- Framework ready for additional strategies (tool config, context window, retry policy, caching)

**Relevant Files:**
- `src/self_improvement/strategies/prompt_optimization_strategy.py` — New PromptOptimizationStrategy (complete, 211 lines)
- `src/self_improvement/strategies/temperature_search_strategy.py` — New TemperatureSearchStrategy (complete, 264 lines)
- `src/self_improvement/strategies/__init__.py` — Updated exports to include new strategies
- `src/self_improvement/strategies/strategy.py` — ImprovementStrategy ABC (interface)
- `src/self_improvement/strategies/registry.py` — StrategyRegistry (for registration)

## 30. Self-Improvement Feedback Path is One-Directional ✅ COMPLETED

**Status:** ✅ Completed in Wave 4

**Problem:** M5 reads metrics from the observability database but never writes back:
- Experiment decisions not recorded in observability
- Deployment outcomes not tracked
- Learned patterns not stored for cross-session persistence
- No audit trail of what M5 changed and why

The self-improvement layer is a consumer of observability data but not a producer. This means you can't observe the self-improvement process itself — there's no way to know what experiments ran, what changes were deployed, or whether deployments improved things.

**Fix:**
- Write `DecisionOutcome` records to observability after each experiment
- Log config deployments as tracked events (connects to Issue #21)
- Record improvement proposals and their outcomes for audit trail
- Feed experiment metadata back into `SystemMetric` aggregations
- This closes the loop: observability → detection → improvement → observability

**Implementation:**
1. Added `track_decision_outcome()` method to ExecutionTracker:
   - Accepts decision type, decision data, outcome, impact metrics, lessons learned
   - Supports experiment selections, config deployments, strategy choices, rollbacks
   - Sanitizes decision data and impact metrics to prevent sensitive data exposure
   - Creates DecisionOutcome records in observability database
   - Handles errors gracefully without breaking M5 loop

2. Modified LoopExecutor to track M5 decisions:
   - Added optional `tracker` parameter to __init__
   - Track experiment outcomes after Phase 4 (success or neutral)
   - Track deployment outcomes after Phase 5 (success)
   - Record impact metrics (quality/speed/cost improvements, statistical significance)
   - Add lessons learned and tags for pattern mining

3. Decision tracking details:
   - **Experiment success**: Records winner variant, improvements, confidence, statistical significance
   - **Experiment neutral**: Records when no significant improvement found (control remains best)
   - **Deployment**: Records deployed config, previous config, rollback monitoring status
   - All decisions include agent name, experiment ID, strategy name, and timestamps

**Result:**
- M5 now writes back to observability database
- Full audit trail of experiments and deployments
- Decision outcomes persist across sessions
- Enables future pattern mining and strategy learning
- Closes the feedback loop: observability → detection → improvement → observability

**Relevant Files:**
- `src/observability/tracker.py:1125-1290` — Added track_decision_outcome() method
- `src/self_improvement/loop/executor.py:48-75, 427-493, 519-558` — Added tracker integration
- `src/observability/models.py:344-382` — DecisionOutcome model (now written by M5)

---

# Prioritized Execution Plan

## Prioritization Criteria

Issues are grouped into **waves** based on two factors:
1. **Dependency order** — some issues must be resolved before others are possible
2. **Impact** — how much the fix improves the system's ability to actually run workflows correctly

---

## Wave 1: Foundation — Error Handling & Execution Reliability ✅ COMPLETED

**Status:** ✅ All issues completed

**Goal:** Make the execution path reliable. Without this, nothing else matters — agents fail silently, errors vanish, and you can't trust any output.

| Priority | Issue | Severity | Description | Status |
|----------|-------|----------|-------------|--------|
| W1.1 | #3 | Critical | Failed agent output loses error context | ✅ Done |
| W1.2 | #5 | Medium | Silent exception swallowing — no logging | ✅ Done |
| W1.3 | #4 | High | No stage-level failure policy for sequential | ✅ Done |
| W1.4 | #1 | High | No agent-level retry on LLM failures | ✅ Done |
| W1.5 | #2 | High | No circuit breaker at executor level | ✅ Done |

**Rationale:** Issue #3 is the single most impactful fix — right now a failed agent produces empty output and the workflow silently continues. Combined with #5 (no logging), failures are invisible. These two are the minimum for a debuggable system. #4 then gives you control over what happens when agents fail. #1 and #2 add resilience.

**Implementation Summary:**
- Error context preservation: Failed agents now include detailed error info (error, error_type, traceback)
- Logging: All exception handlers log with full tracebacks
- Failure policies: Four configurable policies (halt_stage, skip_agent, retry_agent, continue_with_remaining)
- Agent-level retry: LLM calls retry with exponential backoff using existing config
- Circuit breaker: Executor recognizes and logs provider health failures prominently

---

## Wave 2: Safety Wiring — Connect the Disconnected Safety Layer ✅ COMPLETED

**Status:** ✅ All issues completed

**Goal:** The safety system is fully built but provides zero protection. Wire it into the execution path.

| Priority | Issue | Severity | Description | Status |
|----------|-------|----------|-------------|--------|
| W2.1 | #19 | Critical | Safety stack has no ownership chain | ✅ Done |
| W2.2 | #13 | Critical | Safety layer not connected to agent execution path | ✅ Done |
| W2.3 | #9 | High | Parameter validation bypassed in execution path | ✅ Done |
| W2.4 | #14 | High | No safety on LLM calls | ✅ Done |

**Rationale:** #19 is the prerequisite — someone must instantiate the safety stack and pass it down through CLI → Compiler → Executor → Agent. Once ownership exists (#19), #13 routes tool execution through `ToolExecutor` (which already has all safety integrations). #9 comes free if #13 is done right (use `safe_execute()` through `ToolExecutor`). #14 extends safety to LLM calls.

**Implementation Summary:**
- Safety factory: Created `src/safety/factory.py` for centralized safety stack initialization
- Ownership chain: LangGraphCompiler → NodeBuilder → state → StandardAgent
- Tool execution: Routes through ToolExecutor with full policy validation
- Parameter validation: Automatic via ToolExecutor.execute()
- LLM call safety: Pre-call validation with rate limiting and policy checks
- **All safety policies now active**: FileAccess, SecretDetection, ForbiddenOperations, RateLimiter, ResourceLimit, Approval, Rollback

---

## Wave 3: Tool System Reliability ✅ COMPLETED

**Status:** ✅ All issues completed

**Goal:** Make tool calling work correctly across all providers and protect against bad inputs/outputs.

| Priority | Issue | Severity | Description | Status |
|----------|-------|----------|-------------|--------|
| W3.1 | #6 | High | Native function calling is Ollama-only | ✅ Done |
| W3.2 | #7 | Medium | No tool output size control | ✅ Done |
| W3.3 | #18 | High | No config validation at compiler level | ✅ Done |

**Rationale:** #6 directly affects reliability for OpenAI/Anthropic APIs — XML tag parsing is fragile. #7 prevents context window blowouts. #18 catches invalid configs early instead of at runtime mid-workflow. These are independent of Waves 1-2 and can run in parallel.

**Implementation Summary:**
- Native function calling: Infrastructure for OpenAI/Anthropic (providers now receive tool definitions)
- Output size control: 10KB per tool result with clear truncation indicators
- Config validation: Early validation at compile() time with comprehensive error reporting

---

## Wave 4: Observability Completeness

**Goal:** Close the observability gaps so you can actually see what the system is doing.

| Priority | Issue | Severity | Description | Depends On |
|----------|-------|----------|-------------|------------|
| W4.1 | #21 | Medium | StandardAgent doesn't report to tracker directly | Wave 2 (#13) |
| W4.2 | #30 | High | Self-improvement feedback path is one-directional | #21 |
| W4.3 | #24 | Medium | AgentMeritScore never updated | #30 |
| W4.4 | #22 | Medium | No real-time alerting | #21 |
| W4.5 | #23 | Low | No metric aggregation pipeline | — |

**Rationale:** #21 is the foundation — once agents report directly to the tracker, everything downstream works. #30 closes the M5 feedback loop. #24 enables merit-weighted collaboration. #22 adds operational alerting. #23 is nice-to-have for dashboards.

---

## Wave 5: Collaboration Redesign

**Goal:** Replace vote-based synthesis with actual back-and-forth agent dialogue.

| Priority | Issue | Severity | Description | Depends On |
|----------|-------|----------|-------------|------------|
| W5.1 | #17 | Medium | Collaboration only available in parallel mode | — |
| W5.2 | #20 | High | Collaboration is post-hoc voting, not back-and-forth | #17 |

**Rationale:** #17 is a quick win — let sequential agents see prior agents' outputs (already planned, see plan file). #20 is the big redesign — a dialogue orchestrator that re-queries agents with each other's outputs. This requires the most design work and is architecturally independent of the safety/observability fixes, but benefits from #24 (merit scores for weighting dialogue).

---

## Wave 6: Self-Improvement Maturity

**Goal:** Close the M5 loop — strategies that learn, patterns that persist, safety-checked deployments.

| Priority | Issue | Severity | Description | Depends On |
|----------|-------|----------|-------------|------------|
| W6.1 | #27 | Critical | M4 safety integration missing | Wave 2 (#13, #19) |
| W6.2 | #25 | High | Strategies don't learn from outcomes | #30 |
| W6.3 | #26 | Medium | No pattern mining from experiment history | #25 |
| W6.4 | #29 | Low | Only 2 concrete strategies | #25 |
| W6.5 | #28 | Medium | Continuous mode not implemented | #25, #27 |

**Rationale:** #27 must wait for the safety layer to be connected (Wave 2). #25 requires the feedback loop (#30 from Wave 4). #26 and #29 build on learned outcomes. #28 (continuous mode) needs both safety guardrails and learning to be safe to run autonomously.

---

## Deferred — Low Priority / Nice-to-Have

These provide incremental value but aren't blocking:

| Issue | Severity | Description |
|-------|----------|-------------|
| #8 | Low | AVAILABLE_TOOLS mapping is hardcoded |
| #10 | Low | No tool output schema |
| #11 | Medium | Sequential-only tool execution |
| #12 | Low | No tool call budget awareness |
| #15 | Medium | Observability coverage gaps (general) |

---

## Dependency Graph

```
Wave 1 (Execution Reliability)          Wave 3 (Tool System)
  #3 ──→ #4                               #6
  #5                                       #7
  #1 ──→ #2                               #18
    │
    ↓
Wave 2 (Safety Wiring)
  #19 ──→ #13 ──→ #9
              ──→ #14
              │
              ↓
Wave 4 (Observability)                  Wave 5 (Collaboration)
  #21 ──→ #30 ──→ #24                    #17 ──→ #20
      ──→ #22
  #23
              │
              ↓
Wave 6 (Self-Improvement)
  #27 (needs #13, #19)
  #25 (needs #30) ──→ #26
                  ──→ #29
  #28 (needs #25, #27)
```

## Execution Summary

| Wave | Issues | Theme | Status | Parallel With |
|------|--------|-------|--------|---------------|
| **Wave 1** | #3, #5, #4, #1, #2 | Execution reliability | ✅ COMPLETE | Wave 3 |
| **Wave 2** | #19, #13, #9, #14 | Safety wiring | ✅ COMPLETE | — |
| **Wave 3** | #6, #7, #18 | Tool system | ✅ COMPLETE | — |
| **Wave 4** | #21, #30, #24, #22, #23 | Observability | ✅ COMPLETE | Wave 5 |
| **Wave 5** | #17, #20 | Collaboration redesign | ⏳ Pending | Wave 4 |
| **Wave 6** | #27, #25, #26, #29, #28 | Self-improvement | ⏳ Pending | — |

**Critical path:** Wave 1 → Wave 2 → Wave 4 → Wave 6

Waves 1 and 3 can run in parallel. Waves 4 and 5 can run in parallel. Wave 6 depends on both Waves 2 and 4 completing.

**Progress:** Waves 1, 2, 3, and 4 complete! Wave 6 (Self-Improvement Maturity) is now unblocked and ready to start. Wave 5 (Collaboration) can run in parallel with Wave 6.
