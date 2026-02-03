# Fix Runtime API Mismatch in Phase 4 Executor

**Task:** code-crit-executor-api-1
**Priority:** P0 - CRITICAL
**File:** src/self_improvement/loop/executor.py

## What Changed

Fixed `_execute_phase_4_experiment()` method which called the wrong
ExperimentOrchestrator API and used incorrect return type access patterns.

### Before (Broken)
- Called `analyze_experiment(experiment_id, force=True)` — `analyze_experiment()`
  does not accept a `force` parameter
- Treated return value (`ExperimentAnalysis`) as a dictionary with `.get()` calls
- Would crash at runtime when the full 5-phase loop executed

### After (Fixed)
- Calls `get_winner(experiment_id, force=True)` — correct method with `force` param
- Uses proper attribute access on `WinnerResult` object (`winner.variant_id`,
  `winner.winning_config`, etc.)
- Handles `None` return (no winner / inconclusive) gracefully
- Maps `WinnerResult` fields to loop's `ExperimentResult` correctly

## Why

This bug blocked ALL end-to-end testing of the M5.1 improvement loop and would
cause an immediate runtime crash when executing the full 5-phase cycle. It was
the highest-priority blocker for M5.1 validation.

## Testing

- All 277 passing tests in `tests/self_improvement/` continue to pass
- 16 pre-existing failures (unrelated ollama strategy + M5 phase5 DB issues)
- Import verification passes
- No dedicated loop executor tests exist yet (pre-existing gap)

## Risks

- Low risk: single method fix with well-defined API contract
- Control-as-winner case returns `winner_config=None`, correctly skipping deployment
