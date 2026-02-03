# Fix Problem Type Naming Mismatch Between Detector and Strategy

**Task:** code-crit-naming-mismatch-2
**Priority:** P0 - CRITICAL

## What Changed

Standardized ProblemType enum and all problem type string references to follow
a consistent `{metric}_{state}` naming convention across the M5 self-improvement
detection and strategy modules.

### Naming Convention: `{metric}_{state}`
- `quality_low` (quality metric is low)
- `cost_high` (cost metric is high)
- `speed_low` (speed metric is low)
- `error_rate_high` (error rate is high) — NEW

### Renames
| Old Name | New Name |
|----------|----------|
| `COST_TOO_HIGH` / `cost_too_high` | `COST_HIGH` / `cost_high` |
| `TOO_SLOW` / `too_slow` | `SPEED_LOW` / `speed_low` |

### Files Modified
- `src/self_improvement/detection/problem_models.py` — ProblemType enum
- `src/self_improvement/detection/problem_detector.py` — enum references
- `src/self_improvement/strategies/ollama_model_strategy.py` — applicability, impact, inference
- `src/self_improvement/strategies/erc721_strategy.py` — applicability, impact
- `src/self_improvement/strategies/strategy.py` — docstrings
- `tests/self_improvement/strategies/test_ollama_model_strategy.py` — assertions
- `tests/self_improvement/strategies/test_strategy.py` — mock strategy types
- `tests/self_improvement/detection/test_problem_detector.py` — assertions
- `tests/self_improvement/detection/test_improvement_detector.py` — mock types
- `tests/self_improvement/test_m5_phase3_validation.py` — assertions

## Why

The mismatch between detector output (`low_quality`, `high_cost`, `slow_response`)
and strategy expectations (`quality_low`, `cost_too_high`, `too_slow`) caused 10
test failures and prevented strategies from being selected for detected problems.

## Testing

- 287 passing tests (+10 from baseline, all previously-failing strategy tests now pass)
- 6 pre-existing failures in test_m5_phase5_validation.py (unrelated DB issues)
- 0 new failures introduced

## Risks

- Low: naming rename is mechanical and comprehensive (verified via grep)
- All old references eliminated from src/ and tests/ directories
