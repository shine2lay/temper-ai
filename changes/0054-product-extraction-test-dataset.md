# Change: Product Extraction Test Dataset

**Task ID:** code-med-m5-test-dataset
**Date:** 2026-02-01
**Type:** Feature - Test Data

## Summary

Created comprehensive product extraction test dataset with 50 diverse product descriptions and ground truth JSON for M5 self-improvement validation.

## What Changed

### Files Created

1. **tests/fixtures/product_extraction_data.py**
   - 50 test cases with realistic product descriptions
   - Structured ground truth JSON for each product
   - Helper functions for filtering by category and price range
   - Dataset metadata with statistics

2. **tests/self_improvement/test_product_extraction_dataset.py**
   - 12 comprehensive tests validating dataset structure
   - Tests for data quality, diversity, and completeness
   - Validation that dataset is suitable for M5 milestone testing

## Dataset Characteristics

### Coverage
- **Total Test Cases:** 50
- **Categories:** 10 (Electronics, Home & Kitchen, Clothing, Furniture, Sports & Outdoors, Books, Food & Beverage, Footwear, Health & Wellness, Travel)
- **Price Range:** $24.99 - $7,145.00
- **Description Complexity:** Varied (36-187 characters)

### Distribution
- Electronics: 16 cases (most common for testing)
- Home & Kitchen: 12 cases
- Sports & Outdoors: 6 cases
- Furniture: 5 cases
- Clothing: 4 cases
- Books, Food & Beverage: 2 cases each
- Footwear, Health & Wellness, Travel: 1 case each

### Quality Features
- Diverse brands and products
- Varied specification complexity
- Mix of minimal and detailed descriptions
- Realistic pricing and product information
- Edge cases (bundles, subscriptions, multi-piece sets)

## Use Cases

### M5 Validation Scenario
The dataset supports the complete M5 end-to-end test:
- **Baseline Period:** 100 executions (2 passes of dataset)
- **Experiment Phase:** 200 executions (4 variants × 50 each)
- **Validation Phase:** 100 executions (2 passes)
- **Total:** 300+ executions with diverse test data

### Quality Metrics Testing
Each test case includes:
- Product name, brand, category
- Detailed specifications
- Price and currency
- Features and attributes
- Accurate ground truth for measuring extraction quality

## Testing Performed

All 12 tests pass:
- ✓ Dataset has exactly 50 cases
- ✓ All cases have required structure
- ✓ Diverse categories and price ranges
- ✓ Helper functions work correctly
- ✓ Realistic descriptions with variety
- ✓ Comprehensive ground truth data
- ✓ Consistent pricing and currency
- ✓ Accurate metadata
- ✓ Suitable for M5 validation needs

## Risks & Mitigations

**Risk:** Dataset might not cover all product extraction edge cases
**Mitigation:** Included diverse cases: bundles, subscriptions, minimal info, detailed specs, multi-piece sets, various price points

**Risk:** Ground truth might have inconsistencies
**Mitigation:** Comprehensive test suite validates structure, types, and completeness for all 50 cases

## Next Steps

This dataset unblocks:
- `test-med-m5-phase1-validation` - End-to-end M5 validation test
- Quality metric collector testing
- Ollama model comparison experiments

## Technical Notes

### Dataset Access
```python
from tests.fixtures.product_extraction_data import (
    PRODUCT_TEST_CASES,
    get_test_case,
    get_test_cases_by_category,
    get_test_cases_by_price_range
)

# Get all cases
all_cases = PRODUCT_TEST_CASES

# Get specific case
case = get_test_case(0)

# Filter by category
electronics = get_test_cases_by_category("Electronics")

# Filter by price
budget_items = get_test_cases_by_price_range(0, 100)
```

### Ground Truth Format
Each case includes:
- `description`: Natural language product description
- `ground_truth`: Expected JSON with name, brand, category, specifications, price, features, etc.

Example:
```python
{
    "description": "Apple MacBook Pro 16-inch with M3 Max chip, 36GB RAM, 1TB SSD...",
    "ground_truth": {
        "name": "Apple MacBook Pro 16-inch",
        "brand": "Apple",
        "category": "Electronics",
        "specifications": {...},
        "price": 3499.00,
        "currency": "USD"
    }
}
```
