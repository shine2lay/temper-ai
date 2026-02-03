# Remove Duplicate AgentConfig and Unify Strategy-Experiment Pipeline

**Task:** code-crit-agentconfig-09
**Priority:** P0 - CRITICAL

## What Changed

Removed the duplicate `AgentConfig` dataclass from `strategies/strategy.py` and
unified all strategy code to use the canonical `AgentConfig` from `data_models.py`.

### Key Differences Between Old and Canonical AgentConfig

| Field | Old (strategy.py) | Canonical (data_models.py) |
|-------|-------------------|---------------------------|
| `agent_name` | Missing | Required (str) |
| `agent_version` | Missing | "1.0.0" default |
| `metadata` | Present (Dict) | N/A |
| `extra_metadata` | Missing | Present (Dict) |
| `tools` | Missing | Present (Dict) |
| `retry` | Missing | Present (Dict) |

### Files Modified
- `src/self_improvement/strategies/strategy.py` -- removed duplicate class, imports from data_models
- `src/self_improvement/strategies/ollama_model_strategy.py` -- `.metadata` -> `.extra_metadata`
- `src/self_improvement/strategies/erc721_strategy.py` -- `.metadata` -> `.extra_metadata`
- `tests/self_improvement/strategies/test_strategy.py` -- `agent_name` + `extra_metadata`
- `tests/self_improvement/strategies/test_ollama_model_strategy.py` -- `agent_name` + `extra_metadata`
- `tests/test_self_improvement/test_strategy_registry.py` -- `agent_name` + `extra_metadata`
- `tests/self_improvement/test_m5_phase3_validation.py` -- `agent_name` + `extra_metadata`

## Why

Two incompatible `AgentConfig` classes caused strategy-generated configs to fail when
passed to `ExperimentOrchestrator` (which expects `agent_name`). The field name
mismatch (`.metadata` vs `.extra_metadata`) also caused silent data loss in the
strategy-experiment pipeline.

## Testing

- 431 passing tests in self_improvement modules (+0 regressions)
- 1 skipped (pre-existing)
- 0 new failures introduced

## Risks

- Low: mechanical rename verified via grep
- All old `AgentConfig` references in strategy files now point to canonical class
