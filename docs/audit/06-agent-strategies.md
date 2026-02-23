# Audit Report: Agent Strategies Module

**Module:** `temper_ai/agent/strategies/`
**Date:** 2026-02-22
**Files reviewed:** 13 source files, 12 test files
**Test results:** 327 passed, 1 skipped, 0 failed (3.66s)

---

## Executive Summary

The strategies module is a well-architected, thoroughly tested subsystem that implements multi-agent collaboration and conflict resolution. It follows the Strategy pattern cleanly, provides a pluggable registry with thread-safe singleton lifecycle, and has excellent backward compatibility shims. The test suite covers 327 scenarios including edge cases, thread safety, and memory leak prevention.

**Key strengths:** Clean ABC design, pluggable registry, thread safety, deprecation paths, comprehensive validation. **Key weaknesses:** Several functions exceed the 50-line limit, `min_rounds > max_rounds` not validated, merit scores not fed back from the learning subsystem, and no async support in any strategy.

**Overall grade: A- (91/100)**

---

## 1. Code Quality

### 1.1 Function Length Violations (>50 lines)

| File:Line | Function | Lines | Severity |
|---|---|---|---|
| `_dialogue_helpers.py:18-81` | `get_merit_weights` | 64 | Medium |
| `_dialogue_helpers.py:172-223` | `merit_weighted_synthesis` | 52 | Low |
| `base.py:370-437` | `detect_conflicts` | 68 | Medium |
| `concatenate.py:46-99` | `synthesize` | 54 | Low |
| `conflict_resolution.py:625-679` | `calculate_merit_weighted_votes` | 55 | Low |
| `consensus.py:166-250` | `synthesize` | 85 | High |
| `consensus.py:299-352` | `_build_reasoning` | 54 | Low |
| `leader.py:114-185` | `synthesize` | 72 | Medium |
| `leader.py:187-239` | `_consensus_fallback` | 53 | Low |
| `merit_weighted.py:115-182` | `resolve_with_context` | 68 | Medium |
| `merit_weighted.py:184-237` | `_build_reasoning` | 54 | Low |
| `multi_round.py:245-296` | `__init__` | 52 | Low |
| `multi_round.py:303-354` | `get_round_context` | 52 | Low |
| `registry.py:542-592` | `get_strategy_from_config` | 51 | Low |

**Finding CS-01 (Medium):** `consensus.py:166-250` `ConsensusStrategy.synthesize()` at 85 lines is the worst offender. The method handles config extraction, validation, vote counting, winner determination, weak consensus detection, confidence calculation, supporter/dissenter extraction, conflict detection, and reasoning building. The helper methods (`_validate_config`, `_determine_winner`, `_build_weak_consensus_result`) already extracted some logic but the main body still does too much.

**Finding CS-02 (Medium):** `_dialogue_helpers.py:18-81` `get_merit_weights()` at 64 lines mixes database query logic with fallback logic. The try/except block containing the DB query could be extracted into a dedicated `_query_merit_scores_from_db()` helper.

**Finding CS-03 (Medium):** `base.py:370-437` `detect_conflicts()` at 68 lines contains unhashable-key handling, group building, disagreement calculation, and conflict construction. The JSON serialization fallback (lines 400-410) could be extracted.

### 1.2 Parameter Count

All functions stay within the 7-parameter limit. The highest counts are:

- `_build_merit_metadata` (5 params) -- acceptable
- `build_merit_weighted_reasoning` (5 params) -- acceptable
- `DialogueOrchestrator.__init__` (10+ params) -- has `# noqa: params` annotation, delegates to `MultiRoundConfig` dataclass; this is a legacy compat shim and is acceptable

### 1.3 Nesting Depth

No function exceeds 4 levels of nesting. The deepest nesting (3 levels) is in `detect_conflicts()` at `base.py:395-410` with the try/except inside the for-loop inside the if-block.

### 1.4 Magic Numbers

All numeric constants are properly extracted to `constants.py` or module-level constants with descriptive names. Examples:
- `WEAK_CONSENSUS_CONFIDENCE_PENALTY = 0.7` in `consensus.py:51`
- `DEFAULT_AUTO_RESOLVE_THRESHOLD = 0.85` in `merit_weighted.py:31`
- `_STANCE_PER_AGENT_TRUNCATE = 500` with `# scanner: skip-magic` in `multi_round.py:78`

**No violations found.**

### 1.5 Fan-Out

Module import fan-out stays within limits:
- `multi_round.py` imports from 3 internal modules (base, _dialogue_helpers, constants)
- `registry.py` imports from 3 internal modules (base, conflict_resolution, constants)
- `_dialogue_helpers.py` imports from 2 internal modules (base, constants) + 1 shared

**No violations found.**

### 1.6 Naming

All names follow Python conventions. Strategy classes use descriptive names (`ConsensusStrategy`, `MeritWeightedResolver`, `LeaderCollaborationStrategy`). Constants use `UPPER_SNAKE_CASE`. No naming collisions detected.

---

## 2. Security

### 2.1 Input Validation

**Strong.** All public entry points validate inputs:
- `AgentOutput.__post_init__` validates confidence range [0, 1] and non-empty agent_name (`base.py:95-102`)
- `Conflict.__post_init__` validates disagreement_score range, non-empty agents/decisions (`base.py:131-141`)
- `SynthesisResult.__post_init__` validates confidence range (`base.py:179-184`)
- `CollaborationStrategy.validate_inputs()` checks empty list, wrong types, duplicate names (`base.py:340-368`)
- `ConflictResolutionStrategy.validate_inputs()` checks conflict type, empty outputs, agent existence (`conflict_resolution.py:215-246`)
- `_validate_config_ranges()` validates all numeric config params (`multi_round.py:51-64`)
- `StrategyRegistry.register_strategy()` validates name non-empty, checks `issubclass` (`registry.py:192-206`)

### 2.2 Injection Risks

**None detected.** No SQL queries (the DB access in `_dialogue_helpers.py:47-55` uses SQLModel's `select()` with parameterized queries). No `eval/exec/pickle/os.system/shell=True`. No f-string SQL. No `yaml.load` (only `safe_load` via upstream).

### 2.3 LLM Prompt Injection Surface

**Finding SEC-01 (Low):** `multi_round.py:121-124` `_extract_stance_via_llm()` constructs a prompt using agent output text:
```python
prompt = _STANCE_COMPARE_PROMPT.format(
    others=others_summary,
    output=output_text[:_STANCE_OUTPUT_TRUNCATE],
)
```
Agent output text is truncated (1000 chars) and used as-is in the prompt. Since this is an internal classification call (not user-facing), and the result is validated against `VALID_STANCES` frozenset (`multi_round.py:68`), the risk is minimal. The regex validation at line 130-131 ensures only AGREE/DISAGREE/PARTIAL are accepted.

### 2.4 Random Number Generation

`RandomTiebreakerResolver` uses `random.Random(seed)` with a `# noqa: S311` annotation (`conflict_resolution.py:334`). This is intentional for deterministic reproducibility, not cryptographic use. **Acceptable.**

---

## 3. Error Handling

### 3.1 Exception Specificity

**Good.** All exceptions are specific:
- `ValueError` for invalid inputs (confidence, agent names, config ranges)
- `TypeError` for wrong strategy class types
- `RuntimeError` for synthesis failures and human escalation

**Finding EH-01 (Low):** `_dialogue_helpers.py:73` catches a broad tuple of exceptions:
```python
except (ImportError, AttributeError, TypeError, ValueError) as e:
```
This is acceptable for a fallback path (merit score loading), but the `AttributeError` and `TypeError` catches could mask unexpected bugs in the DB query logic.

### 3.2 Graceful Degradation

**Excellent.** Multiple fallback paths:
- Semantic convergence falls back to exact match when `sentence-transformers` is unavailable (`multi_round.py:440-445`)
- Merit weight loading falls back to equal weights on any DB error (`_dialogue_helpers.py:73-75`)
- Leader strategy falls back to consensus when leader output is missing (`leader.py:172-185`)
- Registry handles import failures gracefully during default registration (`registry.py:126-129`)

### 3.3 Timeout/Retry Gaps

**Finding EH-02 (Medium):** No timeout on the `sentence-transformers` model loading at `multi_round.py:512`:
```python
cls._embedding_model = SentenceTransformer("paraphrase-MiniLM-L6-v2")
```
This downloads a model from the internet on first use. If the network is slow or unreachable, this blocks indefinitely. Consider adding a timeout or using a pre-downloaded model path.

**Finding EH-03 (Low):** `_extract_stance_via_llm()` at `multi_round.py:127` calls `llm_provider.complete()` without an explicit timeout. The provider's default timeout applies, but the strategy code doesn't enforce its own limit.

### 3.4 Missing Validation

**Finding EH-04 (Medium):** `multi_round.py` does not validate `min_rounds <= max_rounds`. The test `test_min_rounds_greater_than_max_rounds` at `test_dialogue.py:820-826` explicitly documents this gap:
```python
def test_min_rounds_greater_than_max_rounds(self):
    """Test that min_rounds > max_rounds is allowed (executor enforces)."""
    strategy = DialogueOrchestrator(min_rounds=5, max_rounds=3)
    assert strategy.min_rounds == 5
    assert strategy.max_rounds == 3
```
While the comment says "executor enforces," this is a foot-gun. A `min_rounds=5, max_rounds=3` config will silently produce unexpected behavior if the executor doesn't check.

---

## 4. Modularity

### 4.1 Interface Design

**Excellent.** The module follows the Strategy pattern with clean separation:

1. **`CollaborationStrategy` ABC** (`base.py:187-322`) defines the contract with:
   - `synthesize()` -- core method
   - `get_capabilities()` -- feature detection
   - `get_metadata()` -- introspection (default impl)
   - `requires_requery` property -- signals multi-round behavior
   - `requires_leader_synthesis` property -- signals leader path
   - `validate_inputs()` -- common validation
   - `detect_conflicts()` -- conflict detection

2. **`ConflictResolutionStrategy` ABC** (`conflict_resolution.py:125-213`) defines a parallel contract for resolvers.

3. **`StrategyRegistry`** (`registry.py:66-537`) provides thread-safe registration, retrieval, and lifecycle management.

### 4.2 Backward Compatibility

**Well handled.** Two deprecation shims:
- `debate.py:26-69` -- `DebateAndSynthesize` wraps `MultiRoundStrategy(mode='debate')` with deprecation warning
- `dialogue.py:31-94` -- `DialogueOrchestrator` wraps `MultiRoundStrategy(mode='dialogue')` with deprecation warning

Both emit `DeprecationWarning` with `stacklevel=2`, preserve old type aliases (`DebateRound`, `DebateHistory`, `DialogueRound`, `DialogueHistory`), and maintain backward-compatible constructor signatures.

### 4.3 Coupling

**Low coupling.** The strategies module has minimal dependencies:
- `temper_ai.shared.constants.probabilities` -- shared constants
- `temper_ai.observability` -- only in `_dialogue_helpers.py:get_merit_weights()`, lazily imported inside try/except
- `sentence_transformers` -- optional, lazily imported with fallback

### 4.4 Dead Code

**Finding MOD-01 (Low):** `conflict_resolution.py:487-488` contains an alias:
```python
ConflictResolver = ConflictResolutionStrategy
```
This is used by `merit_weighted.py` imports. Not dead code, but the alias adds unnecessary indirection. The original class name `ConflictResolutionStrategy` is more descriptive.

**Finding MOD-02 (Low):** `constants.py:19` defines `MERIT_DECAY_FACTOR = 0.95` and `constants.py:20` defines `DEFAULT_MERIT_LOOKBACK_DAYS = 30`, but neither is imported anywhere in the strategies module. They may be used externally or be aspirational constants for future time-decay implementation.

### 4.5 Unused Imports

No unused imports detected. All `# noqa: F401` annotations are justified (re-exports and conditional imports).

---

## 5. Feature Completeness

### 5.1 Implemented Strategies

| Strategy | Status | Multi-round | Merit-aware |
|---|---|---|---|
| `ConsensusStrategy` | Complete | No | No |
| `ConcatenateStrategy` | Complete | No | No |
| `MultiRoundStrategy` (dialogue) | Complete | Yes | Optional |
| `MultiRoundStrategy` (debate) | Complete | Yes | Optional |
| `MultiRoundStrategy` (consensus) | Complete | No | Optional |
| `LeaderCollaborationStrategy` | Complete | No | No |
| `DebateAndSynthesize` (deprecated shim) | Complete | Yes (inherited) | Inherited |
| `DialogueOrchestrator` (deprecated shim) | Complete | Yes (inherited) | Inherited |

### 5.2 Implemented Resolvers

| Resolver | Status | Merit-aware |
|---|---|---|
| `HighestConfidenceResolver` | Complete | No |
| `RandomTiebreakerResolver` | Complete | No |
| `MeritWeightedResolver` (conflict_resolution.py) | Complete | Via metadata |
| `MeritWeightedResolver` (merit_weighted.py) | Complete | Via DB query |
| `HumanEscalationResolver` | Complete | No |

### 5.3 Partial Implementations and Gaps

**Finding FC-01 (Medium):** The `create_resolver` factory function at `conflict_resolution.py:453-484` only supports 3 of 7 `ResolutionMethod` enum values:
- Supported: `HIGHEST_CONFIDENCE`, `RANDOM_TIEBREAKER`, `MERIT_WEIGHTED`
- Unsupported: `ESCALATION`, `NEGOTIATION`, `FALLBACK`, `MAJORITY_PLUS_CONFIDENCE`

These raise `ValueError("Unsupported resolution method")`. The enum defines methods without implementations, which is misleading.

**Finding FC-02 (Low):** `SynthesisMethod` enum at `base.py:48-62` defines `BEST_OF` and `DEBATE_EXTRACT` but no strategy uses these methods. They are aspirational values. Consider adding a comment or removing unused values.

**Finding FC-03 (Low):** `constants.py` defines `REBUTTAL_WEIGHT = 0.8` (line 58) and `MIN_ARGUMENT_LENGTH = 50` / `MAX_ARGUMENT_LENGTH = 5000` (lines 56-57) for the debate strategy, but these are never used. The debate implementation was replaced by `MultiRoundStrategy` which doesn't use argument length validation.

### 5.4 No Async Support

**Finding FC-04 (Medium):** All strategies report `"supports_async": False`. Every `synthesize()` and `resolve()` method is synchronous. Given that the framework uses async execution (the executors call `await` in many places), the strategy layer is a synchronous bottleneck. The `_dialogue_helpers.py:get_merit_weights()` function performs a synchronous DB query inside what could be an async path.

---

## 6. Test Quality

### 6.1 Coverage Summary

| Test File | Tests | Focus |
|---|---|---|
| `test_base.py` | 25 | ABC, dataclasses, utility functions, validation |
| `test_consensus.py` | 21 | Majority voting, ties, thresholds, metadata |
| `test_debate.py` | 13 | Deprecation shim, backward compat |
| `test_dialogue.py` | 35 | Shim, convergence, context curation, merit weighting |
| `test_multi_round.py` | 20 | Mode defaults, convergence, context, synthesis, validation |
| `test_conflict_resolution.py` | 14 | All resolvers, factory, validation |
| `test_merit_weighted.py` | 17 | Merit scoring, thresholds, escalation, backward compat |
| `test_leader.py` | 14 | Leader synthesis, fallback, registry integration |
| `test_registry.py` | 20 | Registration, retrieval, config-based, aliases |
| `test_registry_reset.py` | 16 | Reset, clear, thread safety, memory leaks |
| `test_strategy_edge_cases.py` | 13 | Boundary conditions, unusual inputs |
| **Total** | **327** | |

### 6.2 Assertion Depth

**Good.** Most tests make multiple meaningful assertions. Examples:
- `test_consensus.py:41-62` `test_unanimous_consensus` makes 9 assertions covering decision, confidence, method, votes, conflicts, reasoning text, and metadata
- `test_merit_weighted.py:49-73` `test_high_merit_disparity` asserts decision correctness and confidence range
- `test_registry_reset.py:228-253` `test_concurrent_registrations` verifies thread safety with 10 concurrent threads

### 6.3 Mock Usage

**Appropriate.** Mocks are used sparingly:
- `_dialogue_helpers.get_merit_weights` is mocked for DB-dependent tests (5 occurrences)
- `_check_embeddings_available` is patched for fallback tests (2 occurrences)
- No over-mocking -- most tests exercise real strategy logic

### 6.4 Test Gaps

**Finding TQ-01 (Medium):** `ConcatenateStrategy` has no dedicated test file. It is only exercised through the registry integration tests. Missing coverage:
- Empty decision text fallback to reasoning
- Empty agents in output (the `logger.warning` path at `concatenate.py:75-79`)
- `_extract_useful_text` with None decision
- `get_capabilities()` and `get_metadata()` methods

**Finding TQ-02 (Low):** `_dialogue_helpers.py` functions (`curate_recent`, `curate_relevant`, `calculate_semantic_similarity`, `calculate_exact_match_convergence`, `merit_weighted_synthesis`) are tested indirectly through `DialogueOrchestrator` tests but have no direct unit tests. If the shim layer is removed (it's deprecated), these tests would break.

**Finding TQ-03 (Low):** No negative test for `_extract_stance_via_llm()` with a mocked LLM provider that returns invalid stance values.

**Finding TQ-04 (Low):** The `HumanEscalationResolver.resolve()` backward compat method at `merit_weighted.py:363-384` has dead code after the `resolve_with_context` call (lines 377-384) since `resolve_with_context` always raises `RuntimeError`. This is covered by the test at `test_merit_weighted.py:502-510` but the dead code after the call is never executed.

### 6.5 Test Infrastructure

**Excellent.** The `conftest.py` fixture `reset_strategy_registry` (autouse) ensures test isolation by calling `StrategyRegistry.reset_for_testing()` before and after each test. This prevents singleton state leakage between parallel tests.

---

## 7. Architectural Alignment with Vision Pillars

### 7.1 Radical Modularity

**Grade: A.** Strategies are fully pluggable via the `StrategyRegistry`. New strategies can be added by:
1. Subclassing `CollaborationStrategy`
2. Calling `registry.register_strategy("name", MyStrategy)`
3. Referencing `"strategy": "name"` in YAML config

Custom strategies can be unregistered. Defaults are protected. The pattern supports plugin-based extension. The `get_capabilities()` method enables runtime feature detection for graceful degradation.

### 7.2 Configuration as Product

**Grade: A.** Strategy selection is YAML-driven:
```yaml
collaboration:
  strategy: leader
  config:
    leader_agent: vcs_triage_decider
    fallback_to_consensus: true
```
The `get_strategy_from_config()` and `get_resolver_from_config()` functions handle both flat and nested config formats. Each strategy documents its config schema via `get_metadata()`.

### 7.3 Observability as Foundation

**Grade: B-.** Strategy decisions produce detailed `SynthesisResult` objects with:
- `votes` dict showing vote distribution
- `conflicts` list with disagreement scores
- `reasoning` string explaining the decision
- `metadata` dict with supporters, dissenters, decision support %

**Finding ARCH-01 (Medium):** However, strategy execution is NOT integrated with the observability tracker. The `temper_ai/observability/collaboration_tracker.py` exists but is not called from any strategy code. Strategy decisions are not emitted as events to the event bus. There is no span or trace context for strategy execution. The executor layer may handle this, but the strategies themselves are observability-blind.

### 7.4 Progressive Autonomy

**Grade: N/A.** Not directly relevant to strategies, though the `HumanEscalationResolver` provides a safety valve for low-confidence decisions, which aligns with the progressive autonomy principle of human-in-the-loop for uncertain situations.

### 7.5 Self-Improvement Loop

**Grade: C.** **Finding ARCH-02 (Medium):** Strategy outcomes are NOT fed back to the learning subsystem. There is no import path from strategies to `temper_ai/learning/`. The `_dialogue_helpers.py:get_merit_weights()` function reads merit scores from the observability DB, but there is no mechanism to write back strategy performance metrics. The learning system's miners (`agent_performance`, `collaboration_patterns`) could theoretically analyze strategy outcomes from trace data, but there is no explicit integration.

### 7.6 Merit-Based Collaboration

**Grade: B+.** Merit integration is present but has gaps:

**Implemented:**
- `MeritWeightedResolver` uses `AgentMerit` with domain, overall, and recent performance scores (`merit_weighted.py`)
- `_dialogue_helpers.py:get_merit_weights()` queries `AgentMeritScore` from the observability DB
- `MultiRoundStrategy` supports `use_merit_weighting=True` for merit-weighted synthesis
- Merit weights are configurable with custom component ratios (domain 40%, overall 30%, recent 30%)

**Gaps:**
- **Finding ARCH-03 (Low):** `MERIT_DECAY_FACTOR = 0.95` is defined in `constants.py:19` but never used. Time-based merit decay is not implemented in strategy code. The `recency_decay_days` config in `MeritWeightedResolver.__init__` (`merit_weighted.py:89`) is stored but never applied.
- **Finding ARCH-04 (Low):** Domain-specific merit is supported in the data model (`AgentMerit.domain_merit`) but the strategies don't dynamically look up the current task's domain. The `merit_domain` parameter must be explicitly configured.

### 7.7 Safety Through Composition

**Grade: B.** Safety is partially addressed:
- Input validation prevents malformed data from reaching synthesis logic
- `HumanEscalationResolver` provides a safety escalation path
- `MeritWeightedResolver` flags low-confidence decisions for review (`needs_review: True`)
- `ConsensusStrategy` detects weak consensus and marks results with `needs_conflict_resolution: True`

**Finding ARCH-05 (Low):** No strategy enforces safety policies from `temper_ai/safety/`. There is no integration with `ActionPolicyEngine` or blast radius checks. If a strategy produces a dangerous decision, the safety layer is not consulted at the strategy level.

---

## 8. Findings Summary

### Critical (P0)

None.

### High (P1)

None.

### Medium (P2)

| ID | Finding | Location | Recommendation |
|---|---|---|---|
| CS-01 | `ConsensusStrategy.synthesize()` is 85 lines | `consensus.py:166-250` | Extract config extraction and result building into helpers |
| CS-02 | `get_merit_weights()` is 64 lines, mixes DB and fallback | `_dialogue_helpers.py:18-81` | Extract DB query into `_query_merit_from_db()` |
| CS-03 | `detect_conflicts()` is 68 lines | `base.py:370-437` | Extract unhashable-key handling and group building |
| EH-02 | No timeout on SentenceTransformer model download | `multi_round.py:512` | Add timeout or use pre-downloaded model path |
| EH-04 | `min_rounds > max_rounds` not validated | `multi_round.py:286` | Add validation: `if min_rounds > max_rounds: raise ValueError` |
| FC-01 | 4 of 7 `ResolutionMethod` enum values have no implementation | `conflict_resolution.py:55-73` | Remove unused enum values or add implementations |
| FC-04 | No async support in any strategy | All strategies | Add `async def synthesize_async()` or make `synthesize()` async |
| TQ-01 | `ConcatenateStrategy` has no dedicated test file | Missing | Add `test_concatenate.py` |
| ARCH-01 | Strategy execution not integrated with observability tracker | All strategies | Emit events from strategy execution, add trace spans |
| ARCH-02 | Strategy outcomes not fed to learning subsystem | All strategies | Emit strategy performance metrics to learning miners |

### Low (P3)

| ID | Finding | Location |
|---|---|---|
| SEC-01 | Agent text used in LLM prompt for stance extraction | `multi_round.py:121-124` |
| EH-01 | Broad exception catch in merit loading | `_dialogue_helpers.py:73` |
| EH-03 | No explicit timeout on stance LLM call | `multi_round.py:127` |
| MOD-01 | `ConflictResolver` alias adds indirection | `conflict_resolution.py:487-488` |
| MOD-02 | `MERIT_DECAY_FACTOR` and `DEFAULT_MERIT_LOOKBACK_DAYS` unused | `constants.py:19-20` |
| FC-02 | `BEST_OF` and `DEBATE_EXTRACT` SynthesisMethod values unused | `base.py:60-61` |
| FC-03 | Debate-specific constants unused after MultiRound refactor | `constants.py:56-58` |
| TQ-02 | `_dialogue_helpers` functions tested only indirectly via shims | `_dialogue_helpers.py` |
| TQ-03 | No negative test for invalid LLM stance extraction | `multi_round.py:95-136` |
| TQ-04 | Dead code after always-raising call in `HumanEscalationResolver.resolve()` | `merit_weighted.py:377-384` |
| ARCH-03 | `MERIT_DECAY_FACTOR` defined but time-decay not implemented | `constants.py:19` |
| ARCH-04 | Domain-specific merit requires explicit config, no auto-detection | `_dialogue_helpers.py:49` |
| ARCH-05 | No safety policy integration at strategy level | All strategies |

---

## 9. Recommendations

### Immediate (sprint-level)

1. **Extract long functions** (CS-01, CS-02, CS-03): Split `ConsensusStrategy.synthesize()`, `get_merit_weights()`, and `detect_conflicts()` to stay under 50 lines.
2. **Add `min_rounds <= max_rounds` validation** (EH-04): One-line check in `_validate_config_ranges()`.
3. **Add `test_concatenate.py`** (TQ-01): 8-10 tests covering empty decisions, fallback text, get_capabilities/metadata.

### Near-term (1-2 sprints)

4. **Clean up unused enum values and constants** (FC-01, FC-02, FC-03, MOD-02): Remove `BEST_OF`, `DEBATE_EXTRACT`, `REBUTTAL_WEIGHT`, `MIN_ARGUMENT_LENGTH`, `MAX_ARGUMENT_LENGTH`, and either implement or remove the 4 unsupported `ResolutionMethod` values.
5. **Add timeout to SentenceTransformer loading** (EH-02): Use `signal.alarm()` or `concurrent.futures.ThreadPoolExecutor` with timeout.
6. **Remove dead code** (TQ-04): The `HumanEscalationResolver.resolve()` backward compat method can never reach lines 377-384.

### Strategic (quarter-level)

7. **Integrate with observability tracker** (ARCH-01): Emit strategy execution events (strategy name, round count, convergence score, conflict count, final confidence) as observability events. Add trace spans around synthesis calls.
8. **Close the learning loop** (ARCH-02): Feed strategy performance metrics (conflict rate, convergence speed, decision confidence) into the learning subsystem's collaboration_patterns miner.
9. **Implement merit decay** (ARCH-03): Use the already-defined `MERIT_DECAY_FACTOR = 0.95` and `recency_decay_days` config to apply time-based decay to merit scores.
10. **Add async strategy support** (FC-04): Define `async def synthesize_async()` on the ABC with a default sync wrapper, allowing strategies to perform async DB queries and LLM calls.
