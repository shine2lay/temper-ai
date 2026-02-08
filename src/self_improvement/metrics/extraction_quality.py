"""Extraction quality metric collector for structured data extraction tasks.

This module provides a metric collector that measures the accuracy of structured
data extraction by comparing extracted fields against ground truth data. It's
particularly useful for evaluating product extraction, form parsing, and other
structured data extraction tasks.

The metric is computed as:
    extraction_quality = (correctly_extracted_fields / total_fields)

where:
    - correctly_extracted_fields: Number of fields with exact match to ground truth
    - total_fields: Total number of fields in ground truth

The metric normalizes to [0.0, 1.0] range:
    - 0.0 = No fields correctly extracted
    - 1.0 = All fields correctly extracted
"""

import json
import logging
from typing import Any, Dict, Optional

from src.self_improvement.constants import MAX_EXTRACTION_SCORE, MIN_EXTRACTION_SCORE
from src.self_improvement.metrics.collector import ExecutionProtocol, MetricCollector
from src.self_improvement.metrics.types import SIMetricType

logger = logging.getLogger(__name__)


class ExtractionQualityCollector(MetricCollector):
    """Measures field-level accuracy for structured extraction tasks.

    This collector evaluates how well an agent extracts structured data by
    comparing the extracted output against ground truth data. It computes
    field-level accuracy, counting how many fields were extracted correctly.

    The collector is designed for tasks where:
    - Input includes ground truth data for validation
    - Output is structured JSON data
    - Accuracy is measured by field-level exact matches

    Example:
        >>> from src.self_improvement.metrics import MetricRegistry
        >>> collector = ExtractionQualityCollector()
        >>> registry = MetricRegistry()
        >>> registry.register(collector)
        >>>
        >>> # Execution with extraction task
        >>> metrics = registry.collect_all(execution)
        >>> # Returns: {"extraction_quality": 0.85}  # 85% of fields correct

    Attributes:
        strict_mode: If True, nested dictionaries are compared recursively.
                     If False, only top-level fields are compared (default).
    """

    def __init__(self, strict_mode: bool = False):
        """Initialize the extraction quality collector.

        Args:
            strict_mode: Enable strict comparison for nested fields (default: False)
        """
        self.strict_mode = strict_mode

    @property
    def metric_name(self) -> str:
        """Return the metric name.

        Returns:
            str: Always returns 'extraction_quality'
        """
        return "extraction_quality"

    @property
    def metric_type(self) -> SIMetricType:
        """Return the metric type classification.

        Returns:
            SIMetricType: Always returns SIMetricType.CUSTOM since quality
                        evaluation requires custom comparison logic
        """
        return SIMetricType.CUSTOM

    def is_applicable(self, execution: ExecutionProtocol) -> bool:
        """Check if this metric applies to the given execution.

        This collector is applicable when execution has both:
        - input_data with 'ground_truth' field
        - output data for comparison

        Args:
            execution: Execution object to check

        Returns:
            bool: True if execution has ground truth data and output,
                  False otherwise
        """
        try:
            # Check for required attributes
            if not hasattr(execution, 'input_data'):
                logger.debug(
                    f"Execution {execution.id} missing 'input_data' attribute"
                )
                return False

            if not hasattr(execution, 'output'):
                logger.debug(
                    f"Execution {execution.id} missing 'output' attribute"
                )
                return False

            # Check for ground truth in input_data
            input_data = execution.input_data
            if not isinstance(input_data, dict):
                logger.debug(
                    f"Execution {execution.id} input_data is not a dict"
                )
                return False

            if 'ground_truth' not in input_data:
                logger.debug(
                    f"Execution {execution.id} missing 'ground_truth' in input_data"
                )
                return False

            # Has all required data
            return True

        except Exception as e:
            logger.debug(
                f"Error checking applicability for execution "
                f"{getattr(execution, 'id', 'unknown')}: {e}"
            )
            return False

    def collect(self, execution: ExecutionProtocol) -> Optional[float]:
        """Compute extraction quality metric.

        Compares extracted output against ground truth and computes
        field-level accuracy score.

        Args:
            execution: Execution object with input_data['ground_truth']
                       and output fields

        Returns:
            float: Quality score in [0.0, 1.0] representing proportion of
                   correctly extracted fields, or None if metric cannot be
                   computed

        Note:
            For nested dictionaries (specifications, features, etc.):
            - In non-strict mode: Compares as single field (JSON equality)
            - In strict mode: Recursively compares all nested fields
        """
        try:
            # Extract ground truth and output
            ground_truth = execution.input_data['ground_truth']
            extracted = execution.output

            # Parse output if it's a JSON string
            if isinstance(extracted, str):
                try:
                    extracted = json.loads(extracted)
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse output as JSON for execution "
                        f"{execution.id}: {e}"
                    )
                    return None

            # Validate types
            if not isinstance(ground_truth, dict):
                logger.warning(
                    f"Ground truth is not a dict for execution {execution.id}"
                )
                return None

            if not isinstance(extracted, dict):
                logger.warning(
                    f"Extracted output is not a dict for execution {execution.id}"
                )
                return None

            # Compute field-level accuracy
            if self.strict_mode:
                # Recursive comparison for nested fields
                correct, total = self._compare_nested(ground_truth, extracted)
            else:
                # Top-level field comparison only
                correct, total = self._compare_top_level(ground_truth, extracted)

            # Compute accuracy
            if total == 0:
                logger.warning(
                    f"Ground truth has zero fields for execution {execution.id}"
                )
                return None

            accuracy = correct / total

            # Validate range
            if not (MIN_EXTRACTION_SCORE <= accuracy <= MAX_EXTRACTION_SCORE):
                logger.error(
                    f"Computed invalid accuracy {accuracy} for execution "
                    f"{execution.id}"
                )
                return None

            logger.debug(
                f"Extraction quality for {execution.id}: "
                f"{correct}/{total} = {accuracy:.3f}"
            )

            return accuracy

        except Exception as e:
            logger.error(
                f"Failed to collect extraction quality for execution "
                f"{getattr(execution, 'id', 'unknown')}: {e}",
                exc_info=True
            )
            return None

    def _compare_top_level(
        self,
        ground_truth: Dict[str, Any],
        extracted: Dict[str, Any]
    ) -> tuple[int, int]:
        """Compare top-level fields only.

        Nested dictionaries and lists are compared using equality check
        without recursion.

        Args:
            ground_truth: Expected values
            extracted: Actual extracted values

        Returns:
            Tuple[int, int]: (correct_fields, total_fields)
        """
        total = len(ground_truth)
        correct = 0

        for key, expected_value in ground_truth.items():
            if key not in extracted:
                continue  # Missing field = incorrect

            actual_value = extracted[key]

            # Compare values (supports primitives, dicts, lists)
            if self._values_equal(expected_value, actual_value):
                correct += 1

        return correct, total

    def _compare_nested(
        self,
        ground_truth: Dict[str, Any],
        extracted: Dict[str, Any]
    ) -> tuple[int, int]:
        """Compare all fields recursively, including nested structures.

        This provides a more detailed accuracy score by counting individual
        fields within nested dictionaries.

        Args:
            ground_truth: Expected values (possibly nested)
            extracted: Actual extracted values (possibly nested)

        Returns:
            Tuple[int, int]: (correct_fields, total_fields) including all
                             nested fields
        """
        correct = 0
        total = 0

        for key, expected_value in ground_truth.items():
            if isinstance(expected_value, dict):
                # Recursively compare nested dict
                if key in extracted and isinstance(extracted[key], dict):
                    nested_correct, nested_total = self._compare_nested(
                        expected_value,
                        extracted[key]
                    )
                    correct += nested_correct
                    total += nested_total
                else:
                    # Missing or wrong type - count all nested fields as incorrect
                    _, nested_total = self._compare_nested(expected_value, {})
                    total += nested_total
            else:
                # Leaf field - compare directly
                total += 1
                if key in extracted and self._values_equal(
                    expected_value,
                    extracted[key]
                ):
                    correct += 1

        return correct, total

    def _values_equal(self, expected: Any, actual: Any) -> bool:
        """Check if two values are equal.

        Handles special cases:
        - Numeric types (int vs float)
        - Case-insensitive strings (optional)
        - Lists (order matters)

        Args:
            expected: Expected value from ground truth
            actual: Actual extracted value

        Returns:
            bool: True if values are considered equal
        """
        # Handle None
        if expected is None and actual is None:
            return True
        if expected is None or actual is None:
            return False

        # Numeric comparison (handle int vs float)
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            # Allow small floating point differences
            float_comparison_epsilon = 1e-6
            return abs(expected - actual) < float_comparison_epsilon

        # String comparison (case-sensitive by default)
        if isinstance(expected, str) and isinstance(actual, str):
            return expected == actual

        # List comparison (order matters)
        if isinstance(expected, list) and isinstance(actual, list):
            if len(expected) != len(actual):
                return False
            return all(
                self._values_equal(e, a)
                for e, a in zip(expected, actual)
            )

        # Dict comparison (recursive)
        if isinstance(expected, dict) and isinstance(actual, dict):
            if set(expected.keys()) != set(actual.keys()):
                return False
            return all(
                self._values_equal(expected[k], actual[k])
                for k in expected.keys()
            )

        # Default: direct equality
        return expected == actual
