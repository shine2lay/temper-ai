# M5: Implement OllamaModelSelectionStrategy

**Date:** 2026-02-01
**Task:** code-med-m5-ollama-model-strategy
**Component:** M5 Self-Improvement Strategies
**Milestone:** M5 Milestone 1 (Phase 1: Agent + Quality Metric)

---

## Summary

Implemented `OllamaModelSelectionStrategy` - the first concrete improvement strategy for M5's self-improvement system. This strategy generates configuration variants by selecting different Ollama models based on the detected performance problem (quality, cost, or speed).

## Changes Made

### New Files

**src/self_improvement/strategies/ollama_model_strategy.py**

Core implementation with intelligent model selection:

1. **Problem-Aware Selection**:
   - `low_quality` → Selects larger, higher-quality models (qwen2.5:32b, llama3.1:8b)
   - `high_cost` → Selects smaller, faster models (phi3:mini, llama3.1:8b)
   - `slow_response` → Selects faster models (phi3:mini, mistral:7b)
   - `balanced` → Diverse mix of models (when no patterns available)

2. **Variant Generation**:
   - Generates 2-4 configuration variants
   - Excludes current model from candidates
   - Preserves non-model configuration (temperature, prompt, caching)
   - Adds metadata (strategy name, model size, expected quality/speed)

3. **Impact Estimation**:
   - `low_quality`: 40% improvement expected
   - `high_cost`: 30% cost reduction
   - `slow_response`: 30% speed improvement
   - Default: 10% for unknown problems

**tests/self_improvement/strategies/test_ollama_model_strategy.py**

Comprehensive test suite with 30 test cases covering:
- Strategy properties (name, applicability)
- Variant generation (count, uniqueness, exclusion)
- Problem-specific selection (quality, cost, speed)
- Metadata preservation
- Impact estimation
- Integration with ModelRegistry

### Modified Files

**src/self_improvement/strategies/__init__.py**

Added `OllamaModelSelectionStrategy` to public exports.

## How It Works

### Initialization

```python
from src.self_improvement.strategies import OllamaModelSelectionStrategy
from src.self_improvement.model_registry import ModelRegistry

# Create registry with available models
registry = ModelRegistry()  # Loads phi3:mini, llama3.1:8b, mistral:7b, qwen2.5:32b

# Create strategy
strategy = OllamaModelSelectionStrategy(registry)
```

### Variant Generation

```python
from src.self_improvement.strategies import AgentConfig, LearnedPattern

# Current configuration
current = AgentConfig(
    inference={"model": "phi3:mini", "temperature": 0.7},
    prompt={"template": "Extract product info"},
)

# Learned patterns indicating low quality
patterns = [
    LearnedPattern(
        pattern_type="low_quality",
        description="Extraction accuracy is poor",
        support=15,
        confidence=0.9,
        evidence={"avg_quality": 0.45}
    )
]

# Generate variants
variants = strategy.generate_variants(current, patterns)

# Result: 3 variants using larger models
# Variant 1: qwen2.5:32b (highest quality)
# Variant 2: llama3.1:8b (high quality)
# Variant 3: mistral:7b (high quality)
```

### Applicability Check

```python
# Check if strategy applies to problem
strategy.is_applicable("low_quality")     # True
strategy.is_applicable("high_cost")       # True
strategy.is_applicable("slow_response")   # True
strategy.is_applicable("network_issues")  # False
```

### Impact Estimation

```python
# Estimate expected improvement
problem = {"type": "low_quality", "current_quality": 0.5}
impact = strategy.estimate_impact(problem)
# Returns: 0.4 (40% improvement expected)
```

## Features

### Problem-Specific Optimization

**Low Quality Problems:**
```python
# Current: phi3:mini (medium quality, very fast)
# Variants: qwen2.5:32b, llama3.1:8b, mistral:7b (higher quality)
# Trade-off: Better quality for slower speed
```

**High Cost Problems:**
```python
# Current: qwen2.5:32b (highest quality, slow, expensive)
# Variants: phi3:mini, llama3.1:8b, mistral:7b (faster, cheaper)
# Trade-off: Lower cost for reduced quality
```

**Slow Response Problems:**
```python
# Current: qwen2.5:32b (slow)
# Variants: phi3:mini, llama3.1:8b, mistral:7b (faster)
# Trade-off: Better latency for reduced quality
```

### Intelligent Variant Selection

1. **Excludes Current Model**:
   - Variants never include the baseline model
   - Ensures meaningful A/B testing

2. **Diverse Candidates**:
   - Selects 2-4 different models
   - Covers range of quality/speed trade-offs

3. **Metadata Enrichment**:
   ```python
   variant.metadata = {
       "strategy": "ollama_model_selection",
       "model_size": "8B",
       "expected_quality": "high",
       "expected_speed": "fast",
   }
   ```

### Configuration Preservation

Non-model settings are preserved across variants:
- Temperature, max_tokens, top_p (inference settings)
- Prompt template, examples, system message
- Caching configuration
- Other custom metadata

## Testing Performed

All 30 tests passing:

**Strategy Properties (6 tests):**
- ✅ Strategy name
- ✅ Applicability to different problem types
- ✅ Non-applicability to unrelated problems

**Variant Generation (9 tests):**
- ✅ Returns list of variants
- ✅ Generates 2-4 variants
- ✅ Variants have different models
- ✅ Excludes current model
- ✅ Includes strategy metadata
- ✅ Preserves other configuration
- ✅ Default model handling

**Problem-Specific Selection (3 tests):**
- ✅ Low quality → high-quality models
- ✅ High cost → fast/cheap models
- ✅ Slow response → fast models

**Impact Estimation (4 tests):**
- ✅ Low quality: 40% improvement
- ✅ High cost: 30% reduction
- ✅ Slow response: 30% improvement
- ✅ Unknown: 10% default

**Helper Functions (8 tests):**
- ✅ Quality score ordering
- ✅ Speed score ordering
- ✅ Problem type inference from patterns
- ✅ Candidate model selection
- ✅ Integration with ModelRegistry

## Integration with M5

This strategy completes the M5 Phase 1 strategy layer:

1. **ImprovementStrategy Interface** ✅ - Abstract base class
2. **ModelRegistry** ✅ - Available models catalog
3. **OllamaModelSelectionStrategy** ✅ - **THIS CHANGE** - First concrete strategy
4. **StrategyRegistry** ✅ - Manages strategy instances

**Next Steps:**
5. ⏳ Build ExperimentOrchestrator (runs A/B tests)
6. ⏳ Implement variant assignment logic
7. ⏳ Create ProductExtractorAgent (test subject)
8. ⏳ Run baseline evaluation

## Use Cases

### 1. Quality Improvement Experiment

```python
# Problem: Extraction quality is 50% (target: 80%)
current = AgentConfig(inference={"model": "phi3:mini"})
patterns = [LearnedPattern("low_quality", "Poor accuracy", 20, 0.95, {})]

# Generate 3 high-quality variants
variants = strategy.generate_variants(current, patterns)

# Run experiments to find best model for quality
```

### 2. Cost Optimization

```python
# Problem: Cost is $1.00 per 1000 requests (target: < $0.50)
current = AgentConfig(inference={"model": "qwen2.5:32b"})
patterns = [LearnedPattern("high_cost", "Too expensive", 50, 0.9, {})]

# Generate 3 cheaper variants
variants = strategy.generate_variants(current, patterns)

# Test if smaller models maintain quality at lower cost
```

### 3. Latency Reduction

```python
# Problem: Response time is 5 seconds (target: < 2 seconds)
current = AgentConfig(inference={"model": "qwen2.5:32b"})
patterns = [LearnedPattern("slow_response", "High latency", 30, 0.88, {})]

# Generate 3 faster variants
variants = strategy.generate_variants(current, patterns)

# Find fastest model that maintains acceptable quality
```

## Design Decisions

### Why Ollama-Specific?

**Decision:** Create Ollama-specific strategy instead of generic model selection.

**Rationale:**
- MVP focuses on Ollama models (locally hosted, free)
- Each provider has different characteristics (OpenAI: API, Anthropic: Claude)
- Provider-specific strategies enable better optimization

**Future:** Add `OpenAIModelSelectionStrategy`, `AnthropicModelSelectionStrategy`

### Why 2-4 Variants?

**Decision:** Generate 2-4 configuration variants per strategy.

**Rationale:**
- Too few (1): Not enough to find optimal configuration
- Too many (>5): Wastes compute, diminishing returns
- 2-4: Sweet spot for exploration vs exploitation

**Evidence:** Based on M5 architecture doc recommendations (line 1598)

### Why Problem-Specific Selection?

**Decision:** Different model selection logic for each problem type.

**Rationale:**
- Quality problems need larger models
- Cost problems need smaller models
- Speed problems need faster models
- One-size-fits-all approach is suboptimal

**Alternative Considered:** Random selection → Rejected (wasteful, slow convergence)

### Why Preserve Configuration?

**Decision:** Only modify inference.model, preserve everything else.

**Rationale:**
- Clean A/B testing (single variable changed)
- Avoids confounding variables
- Easier to attribute performance changes

## Performance Characteristics

**Time Complexity:**
- `generate_variants()`: O(n) where n = number of models in registry
- `is_applicable()`: O(1) constant time lookup
- `estimate_impact()`: O(1) dictionary lookup

**Space Complexity:**
- O(k) where k = number of variants (2-4)
- Each variant is a deep copy of current config

**Typical Runtime:**
- Generate 3 variants: < 1ms
- Negligible overhead for experimentation

## Limitations & Future Work

### No Learning from History

**Current:**
- Uses static rules (quality → large model)
- Doesn't learn which models work best over time

**Future:**
- Track historical performance by model
- Prioritize models with proven track record
- Bayesian optimization for model selection

### Fixed Model Set

**Current:**
- Uses 4 hardcoded Ollama models
- No dynamic model discovery

**Future:**
- Query Ollama API for available models
- Auto-discover newly installed models
- Support custom model registrations

### No Cost-Quality Trade-off Optimization

**Current:**
- Binary choice: optimize for quality OR cost
- Doesn't find Pareto-optimal solutions

**Future:**
- Multi-objective optimization
- Find models on quality-cost frontier
- Configurable quality/cost preferences

## References

- M5 Architecture: `/docs/M5_MODULAR_ARCHITECTURE.md` (Phase 1, line 1571-1598)
- ImprovementStrategy Interface: `src/self_improvement/strategies/strategy.py`
- ModelRegistry: `src/self_improvement/model_registry.py`
- Depends on: `code-high-m5-strategy-interface`, `code-med-m5-model-registry`
- Blocks: `test-med-m5-phase3-validation`
