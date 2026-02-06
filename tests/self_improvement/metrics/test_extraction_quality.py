"""Tests for ExtractionQualityCollector."""

from dataclasses import dataclass
from typing import Any, Dict

import pytest

from src.self_improvement.metrics.extraction_quality import ExtractionQualityCollector
from src.self_improvement.metrics.types import SIMetricType


@dataclass
class MockExecution:
    """Mock execution object for testing."""
    id: str
    status: str
    input_data: Dict[str, Any]
    output: Any


class TestExtractionQualityCollector:
    """Test suite for ExtractionQualityCollector."""

    def test_metric_name(self):
        """Test metric name is correct."""
        collector = ExtractionQualityCollector()
        assert collector.metric_name == "extraction_quality"

    def test_metric_type(self):
        """Test metric type is CUSTOM."""
        collector = ExtractionQualityCollector()
        assert collector.metric_type == SIMetricType.CUSTOM

    def test_not_applicable_missing_input_data(self):
        """Test not applicable when execution missing input_data."""
        collector = ExtractionQualityCollector()

        @dataclass
        class NoInputExecution:
            id: str = "test-001"
            status: str = "completed"
            output: dict = None

        execution = NoInputExecution()
        assert not collector.is_applicable(execution)

    def test_not_applicable_missing_output(self):
        """Test not applicable when execution missing output."""
        collector = ExtractionQualityCollector()

        @dataclass
        class NoOutputExecution:
            id: str = "test-001"
            status: str = "completed"
            input_data: dict = None

        execution = NoOutputExecution(
            input_data={"ground_truth": {"name": "Test"}}
        )
        assert not collector.is_applicable(execution)

    def test_not_applicable_missing_ground_truth(self):
        """Test not applicable when ground_truth missing."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={"description": "Some text"},
            output={"name": "Test"}
        )
        assert not collector.is_applicable(execution)

    def test_applicable_with_ground_truth_and_output(self):
        """Test applicable when has ground_truth and output."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={"ground_truth": {"name": "Test"}},
            output={"name": "Test"}
        )
        assert collector.is_applicable(execution)

    def test_perfect_extraction(self):
        """Test 100% accuracy for perfect extraction."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "iPhone 15 Pro",
                    "brand": "Apple",
                    "price": 999.99,
                    "currency": "USD"
                }
            },
            output={
                "name": "iPhone 15 Pro",
                "brand": "Apple",
                "price": 999.99,
                "currency": "USD"
            }
        )
        score = collector.collect(execution)
        assert score == 1.0

    def test_partial_extraction(self):
        """Test partial accuracy (2/4 fields correct)."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "iPhone 15 Pro",
                    "brand": "Apple",
                    "price": 999.99,
                    "currency": "USD"
                }
            },
            output={
                "name": "iPhone 15 Pro",  # Correct
                "brand": "Samsung",       # Wrong
                "price": 999.99,          # Correct
                "currency": "EUR"         # Wrong
            }
        )
        score = collector.collect(execution)
        assert score == 0.5  # 2 out of 4

    def test_zero_extraction(self):
        """Test 0% accuracy when no fields match."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "iPhone 15 Pro",
                    "brand": "Apple",
                    "price": 999.99
                }
            },
            output={
                "name": "Galaxy S24",
                "brand": "Samsung",
                "price": 799.99
            }
        )
        score = collector.collect(execution)
        assert score == 0.0

    def test_missing_fields(self):
        """Test when extracted output missing fields."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "iPhone 15 Pro",
                    "brand": "Apple",
                    "price": 999.99,
                    "currency": "USD"
                }
            },
            output={
                "name": "iPhone 15 Pro",  # Only 1 field extracted
            }
        )
        score = collector.collect(execution)
        assert score == 0.25  # 1 out of 4

    def test_extra_fields_ignored(self):
        """Test that extra fields in output don't affect score."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "iPhone 15 Pro",
                    "price": 999.99
                }
            },
            output={
                "name": "iPhone 15 Pro",
                "price": 999.99,
                "extra_field": "ignored",
                "another_extra": 123
            }
        )
        score = collector.collect(execution)
        assert score == 1.0  # 2 out of 2 (extras ignored)

    def test_json_string_output(self):
        """Test parsing JSON string output."""
        import json
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "iPhone 15 Pro",
                    "price": 999.99
                }
            },
            output=json.dumps({
                "name": "iPhone 15 Pro",
                "price": 999.99
            })
        )
        score = collector.collect(execution)
        assert score == 1.0

    def test_invalid_json_string_output(self):
        """Test handling of invalid JSON string."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {"name": "Test"}
            },
            output="not valid json {{"
        )
        score = collector.collect(execution)
        assert score is None  # Cannot parse = cannot score

    def test_numeric_comparison_int_vs_float(self):
        """Test numeric comparison handles int vs float."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "price": 999.99,
                    "quantity": 5
                }
            },
            output={
                "price": 999.99,  # float == float
                "quantity": 5.0   # int vs float should match
            }
        )
        score = collector.collect(execution)
        assert score == 1.0

    def test_list_comparison(self):
        """Test list comparison (order matters)."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "features": ["Wireless", "Noise Cancelling"],
                    "colors": ["Black", "White"]
                }
            },
            output={
                "features": ["Wireless", "Noise Cancelling"],  # Correct
                "colors": ["White", "Black"]  # Wrong order
            }
        )
        score = collector.collect(execution)
        assert score == 0.5  # 1 out of 2

    def test_nested_dict_non_strict_mode(self):
        """Test nested dict comparison in non-strict mode (default)."""
        collector = ExtractionQualityCollector(strict_mode=False)
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "MacBook Pro",
                    "specifications": {
                        "ram": "16GB",
                        "storage": "512GB"
                    }
                }
            },
            output={
                "name": "MacBook Pro",  # Correct
                "specifications": {      # Nested dict compared as single field
                    "ram": "16GB",
                    "storage": "512GB"
                }
            }
        )
        score = collector.collect(execution)
        assert score == 1.0  # 2 out of 2 (nested dict matches)

    def test_nested_dict_non_strict_mode_mismatch(self):
        """Test nested dict mismatch in non-strict mode."""
        collector = ExtractionQualityCollector(strict_mode=False)
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "MacBook Pro",
                    "specifications": {
                        "ram": "16GB",
                        "storage": "512GB"
                    }
                }
            },
            output={
                "name": "MacBook Pro",  # Correct
                "specifications": {
                    "ram": "32GB",       # Different value
                    "storage": "512GB"
                }
            }
        )
        score = collector.collect(execution)
        assert score == 0.5  # 1 out of 2 (nested dict doesn't match)

    def test_nested_dict_strict_mode(self):
        """Test nested dict comparison in strict mode."""
        collector = ExtractionQualityCollector(strict_mode=True)
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "MacBook Pro",
                    "specifications": {
                        "ram": "16GB",
                        "storage": "512GB"
                    }
                }
            },
            output={
                "name": "MacBook Pro",  # Correct (1/3)
                "specifications": {
                    "ram": "16GB",       # Correct (2/3)
                    "storage": "1TB"     # Wrong (2/3)
                }
            }
        )
        score = collector.collect(execution)
        # In strict mode: name (1) + ram (1) + storage (0) = 2/3
        assert score == pytest.approx(2/3)

    def test_nested_dict_strict_mode_missing(self):
        """Test nested dict with missing nested fields in strict mode."""
        collector = ExtractionQualityCollector(strict_mode=True)
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "ground_truth": {
                    "name": "MacBook Pro",
                    "specifications": {
                        "ram": "16GB",
                        "storage": "512GB"
                    }
                }
            },
            output={
                "name": "MacBook Pro",  # Correct (1/3)
                "specifications": {
                    "ram": "16GB"        # Correct (2/3), storage missing (2/3)
                }
            }
        )
        score = collector.collect(execution)
        # In strict mode: name (1) + ram (1) + storage (0) = 2/3
        assert score == pytest.approx(2/3)

    def test_realistic_product_extraction(self):
        """Test with realistic product extraction scenario."""
        from tests.fixtures.product_extraction_data import PRODUCT_TEST_CASES

        collector = ExtractionQualityCollector(strict_mode=False)

        # Get first test case (MacBook Pro)
        test_case = PRODUCT_TEST_CASES[0]

        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "description": test_case["description"],
                "ground_truth": test_case["ground_truth"]
            },
            output={
                "name": "Apple MacBook Pro 16-inch",  # Correct
                "brand": "Apple",                      # Correct
                "category": "Electronics",             # Correct
                "specifications": {                    # Nested dict (treated as 1 field)
                    "processor": "M3 Max chip",
                    "ram": "36GB",
                    "storage": "1TB SSD",
                    "display": "Liquid Retina XDR",
                    "battery_life": "22 hours"
                },
                "color": "Space Black",                # Correct
                "price": 3499.00,                      # Correct
                "currency": "USD"                      # Correct
            }
        )

        score = collector.collect(execution)
        # 7 fields match (name, brand, category, specs, color, price, currency)
        assert score == 1.0

    def test_realistic_partial_extraction(self):
        """Test realistic partial extraction (some errors)."""
        from tests.fixtures.product_extraction_data import PRODUCT_TEST_CASES

        collector = ExtractionQualityCollector(strict_mode=False)

        test_case = PRODUCT_TEST_CASES[0]  # MacBook Pro

        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={
                "description": test_case["description"],
                "ground_truth": test_case["ground_truth"]
            },
            output={
                "name": "Apple MacBook Pro 16-inch",  # Correct
                "brand": "Dell",                       # WRONG
                "category": "Electronics",             # Correct
                "specifications": {                    # Nested (correct)
                    "processor": "M3 Max chip",
                    "ram": "36GB",
                    "storage": "1TB SSD",
                    "display": "Liquid Retina XDR",
                    "battery_life": "22 hours"
                },
                "color": "Silver",                     # WRONG
                "price": 3499.00,                      # Correct
                "currency": "USD"                      # Correct
            }
        )

        score = collector.collect(execution)
        # Ground truth has 7 fields, 2 are wrong (brand, color)
        # Correct: name, category, specs, price, currency = 5/7
        assert score == pytest.approx(5/7)

    def test_collector_version(self):
        """Test collector version property."""
        collector = ExtractionQualityCollector()
        assert collector.collector_version == "1.0"

    def test_none_ground_truth(self):
        """Test handling of non-dict ground truth."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={"ground_truth": None},
            output={"name": "Test"}
        )
        score = collector.collect(execution)
        assert score is None

    def test_none_output(self):
        """Test handling of non-dict output."""
        collector = ExtractionQualityCollector()
        execution = MockExecution(
            id="test-001",
            status="completed",
            input_data={"ground_truth": {"name": "Test"}},
            output=None
        )
        score = collector.collect(execution)
        assert score is None
