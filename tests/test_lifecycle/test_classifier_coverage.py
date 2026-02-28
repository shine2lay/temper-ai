"""Targeted tests for uncovered path in lifecycle/classifier.py.

Covers line 131: estimated_complexity explicit extraction.
"""

from temper_ai.lifecycle._schemas import ProjectCharacteristics
from temper_ai.lifecycle.classifier import _extract_explicit


class TestExtractExplicitEstimatedComplexity:
    """Covers line 131: 'estimated_complexity' key in input_data."""

    def test_estimated_complexity_extracted(self):
        """Line 131: float value extracted from input_data."""
        chars = _extract_explicit({"estimated_complexity": 0.75})
        assert chars.estimated_complexity == 0.75

    def test_estimated_complexity_zero(self):
        """Line 131: boundary value 0.0 extracted correctly."""
        chars = _extract_explicit({"estimated_complexity": 0.0})
        assert chars.estimated_complexity == 0.0

    def test_estimated_complexity_one(self):
        """Line 131: boundary value 1.0 extracted correctly."""
        chars = _extract_explicit({"estimated_complexity": 1.0})
        assert chars.estimated_complexity == 1.0

    def test_estimated_complexity_coerced_from_int(self):
        """Line 131: int value coerced to float via float()."""
        chars = _extract_explicit({"estimated_complexity": 1})
        assert chars.estimated_complexity == 1.0
        assert isinstance(chars.estimated_complexity, float)

    def test_estimated_complexity_combined_with_other_fields(self):
        """Line 131: coexists with other explicit fields."""
        chars = _extract_explicit(
            {
                "size": "large",
                "risk_level": "high",
                "estimated_complexity": 0.9,
                "is_prototype": False,
                "tags": ["ml"],
                "product_type": "ml_pipeline",
            }
        )
        assert chars.estimated_complexity == 0.9
        assert chars.product_type == "ml_pipeline"
        assert chars.tags == ["ml"]

    def test_estimated_complexity_not_present_uses_default(self):
        """Line 130-131 branch not taken: missing key → default used."""
        default = ProjectCharacteristics.model_fields["estimated_complexity"].default
        chars = _extract_explicit({})
        assert chars.estimated_complexity == default
