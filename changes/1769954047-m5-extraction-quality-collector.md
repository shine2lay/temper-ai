# M5: Implement ExtractionQualityCollector

**Date:** 2026-02-01
**Task:** code-med-m5-extraction-quality-collector
**Component:** M5 Metric Collection System
**Milestone:** M5 Milestone 1 (Phase 1: Agent + Quality Metric)

---

## Summary

Implemented `ExtractionQualityCollector` - a custom metric collector that measures field-level accuracy for structured data extraction tasks. This collector enables M5 to quantitatively evaluate how well an agent extracts structured information from unstructured text.

## Changes Made

### New Files

**src/self_improvement/metrics/extraction_quality.py**

Core implementation with two comparison modes:

1. **Non-strict mode (default)**: Top-level field comparison
   - Treats nested dictionaries as single fields
   - Faster comparison
   - Suitable for most extraction tasks

2. **Strict mode**: Recursive field comparison
   - Counts every nested field individually
   - More granular accuracy measurement
   - Better for complex nested structures

**tests/self_improvement/metrics/test_extraction_quality.py**

Comprehensive test suite with 22 test cases covering:
- Perfect extraction (1.0 score)
- Partial extraction (varying scores)
- Zero extraction (0.0 score)
- Missing/extra fields
- Nested dictionaries (both modes)
- Numeric comparison (int vs float)
- List comparison (order-sensitive)
- JSON string parsing
- Realistic product extraction scenarios

### Modified Files

**src/self_improvement/metrics/__init__.py**

Added `ExtractionQualityCollector` to public exports.

## How It Works

### Metric Computation

```python
extraction_quality = correct_fields / total_fields
```

where:
- `correct_fields`: Number of fields with exact match to ground truth
- `total_fields`: Total number of fields in ground truth

### Non-Strict Mode Example

```python
collector = ExtractionQualityCollector(strict_mode=False)

ground_truth = {
    "name": "iPhone 15 Pro",
    "brand": "Apple",
    "price": 999.99,
    "currency": "USD"
}

extracted = {
    "name": "iPhone 15 Pro",  # ✓ Correct
    "brand": "Samsung",       # ✗ Wrong
    "price": 999.99,          # ✓ Correct
    "currency": "EUR"         # ✗ Wrong
}

# Score: 2/4 = 0.5
```

### Strict Mode Example (Nested Fields)

```python
collector = ExtractionQualityCollector(strict_mode=True)

ground_truth = {
    "name": "MacBook Pro",
    "specifications": {
        "ram": "16GB",
        "storage": "512GB"
    }
}

extracted = {
    "name": "MacBook Pro",  # ✓ Correct (1/3)
    "specifications": {
        "ram": "16GB",       # ✓ Correct (2/3)
        "storage": "1TB"     # ✗ Wrong (2/3)
    }
}

# Score: 2/3 = 0.667 (counts nested fields individually)
```

## Integration with M5

This collector is used in M5 Milestone 1 to:

1. **Measure agent performance** - Quantify extraction accuracy for product extraction agent
2. **Enable experimentation** - Compare different Ollama models on extraction quality
3. **Track improvements** - Monitor quality changes after configuration deployments

### Usage with MetricRegistry

```python
from src.self_improvement.metrics import MetricRegistry, ExtractionQualityCollector

# Setup
registry = MetricRegistry()
registry.register(ExtractionQualityCollector())

# After execution completes
metrics = registry.collect_all(execution)
# Returns: {"extraction_quality": 0.85}
```

### Execution Requirements

The collector is applicable when execution has:
- `input_data` dict with `ground_truth` field
- `output` with extracted data (dict or JSON string)

Example execution structure:

```python
execution = AgentExecution(
    id="exec-001",
    status="completed",
    input_data={
        "description": "Apple MacBook Pro 16-inch...",
        "ground_truth": {
            "name": "Apple MacBook Pro 16-inch",
            "brand": "Apple",
            "price": 3499.00,
            "currency": "USD"
        }
    },
    output={
        "name": "Apple MacBook Pro 16-inch",
        "brand": "Apple",
        "price": 3499.00,
        "currency": "USD"
    }
)
```

## Features

### Value Comparison

- **Numeric types**: Handles int vs float comparison with epsilon tolerance
- **Strings**: Case-sensitive exact match
- **Lists**: Order-sensitive comparison
- **Nested dicts**: Configurable strict/non-strict mode
- **None values**: Proper null handling

### Error Handling

- **Invalid JSON**: Gracefully handles unparseable output
- **Type mismatches**: Validates dict types for ground truth and output
- **Missing fields**: Counts as incorrect, doesn't crash
- **Extra fields**: Ignored (doesn't affect score)

### Logging

- Debug: Applicability checks, metric collection results
- Warning: Invalid JSON, type mismatches
- Error: Computation failures, invalid scores

## Testing Performed

All tests passing (22 test cases):

- ✅ Metric properties (name, type, version)
- ✅ Applicability checks (with/without ground truth)
- ✅ Perfect extraction (1.0)
- ✅ Partial extraction (0.5)
- ✅ Zero extraction (0.0)
- ✅ Missing fields handling
- ✅ Extra fields ignored
- ✅ JSON string parsing
- ✅ Invalid JSON handling
- ✅ Numeric comparison (int vs float)
- ✅ List comparison (order matters)
- ✅ Nested dict non-strict mode
- ✅ Nested dict strict mode
- ✅ Realistic product extraction (100%)
- ✅ Realistic partial extraction (71.4%)

## Performance Characteristics

| Mode | Speed | Accuracy Granularity | Use Case |
|------|-------|----------------------|----------|
| **Non-strict** | Fast | Top-level fields | Default, simple extractions |
| **Strict** | Slower | All nested fields | Complex nested structures |

**Complexity:**
- Non-strict: O(n) where n = top-level fields
- Strict: O(n*m) where n = fields, m = avg nesting depth

## Use Cases

### 1. Product Information Extraction

```python
# Input: "Apple MacBook Pro 16-inch with M3 Max chip, 36GB RAM..."
# Output: JSON with name, brand, category, specs, price, currency
# Metric: 100% if all fields correct, proportional if partial
```

### 2. Form Parsing

```python
# Input: Unstructured form text
# Output: Structured fields (name, address, phone, email, etc.)
# Metric: Percentage of correctly extracted fields
```

### 3. Resume Parsing

```python
# Input: Resume PDF/text
# Output: Candidate info (name, skills, experience, education)
# Metric: Field-level extraction accuracy
```

## Next Steps

1. ✅ ExtractionQualityCollector implemented and tested
2. ⏳ Integrate with ExecutionTracker (task: code-med-m5-execution-tracker-integration)
3. ⏳ Build ProductExtractorAgent (uses Ollama for inference)
4. ⏳ Create test dataset (50 product extraction cases) - **DONE** (already exists)
5. ⏳ Run baseline evaluations to establish ground truth metrics

## References

- M5 Architecture: `/docs/M5_MODULAR_ARCHITECTURE.md` (Phase 1)
- MetricCollector Interface: `src/self_improvement/metrics/collector.py`
- Test Dataset: `tests/fixtures/product_extraction_data.py` (50 test cases)
- Depends on: `code-high-m5-metric-collector-interface` (completed)
- Blocks: `code-med-m5-execution-tracker-integration`
