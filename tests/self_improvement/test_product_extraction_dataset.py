"""Tests for product extraction test dataset."""

import pytest

from tests.fixtures.product_extraction_data import (
    PRODUCT_TEST_CASES,
    TEST_DATASET_INFO,
    get_all_test_cases,
    get_test_case,
    get_test_cases_by_category,
    get_test_cases_by_price_range,
)


def test_dataset_size():
    """Verify dataset has exactly 50 test cases."""
    assert len(PRODUCT_TEST_CASES) == 50
    assert TEST_DATASET_INFO["total_cases"] == 50


def test_dataset_structure():
    """Verify all test cases have required structure."""
    required_fields = ["description", "ground_truth"]
    ground_truth_required = ["name", "brand", "category", "price", "currency"]

    for i, case in enumerate(PRODUCT_TEST_CASES):
        # Check top-level fields
        for field in required_fields:
            assert field in case, f"Case {i} missing '{field}'"

        # Check ground_truth fields
        for field in ground_truth_required:
            assert field in case["ground_truth"], f"Case {i} missing ground_truth '{field}'"

        # Validate types
        assert isinstance(case["description"], str), f"Case {i} description not string"
        assert isinstance(case["ground_truth"]["name"], str), f"Case {i} name not string"
        assert isinstance(case["ground_truth"]["brand"], str), f"Case {i} brand not string"
        assert isinstance(case["ground_truth"]["category"], str), f"Case {i} category not string"
        assert isinstance(case["ground_truth"]["price"], (int, float)), f"Case {i} price not numeric"
        assert case["ground_truth"]["price"] > 0, f"Case {i} price not positive"
        assert isinstance(case["ground_truth"]["currency"], str), f"Case {i} currency not string"


def test_dataset_diversity():
    """Verify dataset covers diverse categories and price ranges."""
    categories = set(case["ground_truth"]["category"] for case in PRODUCT_TEST_CASES)

    # Should have at least 5 different categories
    assert len(categories) >= 5, f"Only {len(categories)} categories, expected at least 5"

    # Should have Electronics, Clothing, Home & Kitchen
    assert "Electronics" in categories
    assert "Clothing" in categories
    assert "Home & Kitchen" in categories

    # Price range should be substantial
    prices = [case["ground_truth"]["price"] for case in PRODUCT_TEST_CASES]
    assert min(prices) < 100, "Should have some low-priced items"
    assert max(prices) > 500, "Should have some high-priced items"


def test_get_test_case():
    """Test retrieving individual test cases."""
    case = get_test_case(0)
    assert "description" in case
    assert "ground_truth" in case

    # Should raise IndexError for invalid index
    with pytest.raises(IndexError):
        get_test_case(100)


def test_get_all_test_cases():
    """Test retrieving all test cases."""
    cases = get_all_test_cases()
    assert len(cases) == 50
    assert cases[0] == PRODUCT_TEST_CASES[0]


def test_get_test_cases_by_category():
    """Test filtering by category."""
    electronics = get_test_cases_by_category("Electronics")
    assert len(electronics) > 0
    assert all(case["ground_truth"]["category"] == "Electronics" for case in electronics)

    clothing = get_test_cases_by_category("Clothing")
    assert len(clothing) > 0
    assert all(case["ground_truth"]["category"] == "Clothing" for case in clothing)


def test_get_test_cases_by_price_range():
    """Test filtering by price range."""
    budget_items = get_test_cases_by_price_range(0, 100)
    assert len(budget_items) > 0
    assert all(case["ground_truth"]["price"] <= 100 for case in budget_items)

    premium_items = get_test_cases_by_price_range(500, 10000)
    assert len(premium_items) > 0
    assert all(case["ground_truth"]["price"] >= 500 for case in premium_items)


def test_realistic_descriptions():
    """Verify descriptions are realistic and varied."""
    descriptions = [case["description"] for case in PRODUCT_TEST_CASES]

    # All descriptions should be non-empty
    assert all(len(desc) > 0 for desc in descriptions)

    # Descriptions should vary in length (some short, some detailed)
    lengths = [len(desc) for desc in descriptions]
    assert min(lengths) < 100, "Should have some concise descriptions"
    assert max(lengths) > 150, "Should have some detailed descriptions"

    # Should have variety in product names
    names = set(case["ground_truth"]["name"] for case in PRODUCT_TEST_CASES)
    assert len(names) == 50, "All products should have unique names"


def test_ground_truth_completeness():
    """Verify ground truth data is comprehensive."""
    # All cases should have specifications (except minimal test cases)
    cases_with_specs = [
        case for case in PRODUCT_TEST_CASES
        if "specifications" in case["ground_truth"]
    ]
    assert len(cases_with_specs) >= 45, "Most cases should have specifications"

    # Electronics should have detailed specs
    electronics = get_test_cases_by_category("Electronics")
    electronics_with_specs = [
        case for case in electronics
        if "specifications" in case["ground_truth"]
    ]
    assert len(electronics_with_specs) == len(electronics), "All electronics should have specs"


def test_price_and_currency_consistency():
    """Verify price and currency data is consistent."""
    for case in PRODUCT_TEST_CASES:
        gt = case["ground_truth"]

        # All should have USD currency
        assert gt["currency"] == "USD"

        # Price should be reasonable
        assert 0 < gt["price"] < 10000, f"Unusual price: ${gt['price']}"


def test_dataset_metadata():
    """Verify dataset metadata is accurate."""
    assert TEST_DATASET_INFO["total_cases"] == len(PRODUCT_TEST_CASES)

    # Check categories match
    actual_categories = set(case["ground_truth"]["category"] for case in PRODUCT_TEST_CASES)
    metadata_categories = set(TEST_DATASET_INFO["categories"])
    assert actual_categories == metadata_categories

    # Check price range
    prices = [case["ground_truth"]["price"] for case in PRODUCT_TEST_CASES]
    assert TEST_DATASET_INFO["price_range"]["min"] == min(prices)
    assert TEST_DATASET_INFO["price_range"]["max"] == max(prices)


def test_dataset_suitable_for_m5_validation():
    """Verify dataset is suitable for M5 milestone validation."""
    # M5 needs at least 300 total executions in the test scenario:
    # - 100 baseline
    # - 200 experiment (4 variants x 50 each)
    # - 100 validation
    # With 50 test cases, we can do 6 passes to get 300 executions
    assert len(PRODUCT_TEST_CASES) >= 50, "Need at least 50 cases for M5 validation"

    # Should have diverse difficulty levels based on description length
    description_lengths = [len(case["description"]) for case in PRODUCT_TEST_CASES]

    # Check we have variety in description complexity
    assert min(description_lengths) < 100, "Should have some very concise descriptions"
    assert max(description_lengths) > 150, "Should have some detailed descriptions"

    # Verify we have good distribution across complexity levels
    very_short_cases = [d for d in description_lengths if d < 60]  # Minimal info
    short_cases = [d for d in description_lengths if 60 <= d < 120]  # Moderate info
    detailed_cases = [d for d in description_lengths if d >= 120]  # Detailed info

    assert len(very_short_cases) >= 2, "Should have minimal cases for easy extraction"
    assert len(short_cases) >= 10, "Should have moderate cases"
    assert len(detailed_cases) >= 20, "Should have detailed cases to challenge models"
