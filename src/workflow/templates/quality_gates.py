"""Product-type quality gate defaults."""

from typing import Dict

from src.shared.constants.probabilities import PROB_HIGH, PROB_VERY_HIGH
from src.workflow.templates._schemas import TemplateQualityGates

# Confidence thresholds per product type
CONFIDENCE_API = 0.75  # scanner: skip-magic — API quality gate threshold

PRODUCT_QUALITY_GATES: Dict[str, TemplateQualityGates] = {
    "web_app": TemplateQualityGates(
        min_confidence=PROB_HIGH,
        require_citations=True,
        on_failure="retry_stage",
        custom_checks=["performance", "accessibility", "security"],
    ),
    "api": TemplateQualityGates(
        min_confidence=CONFIDENCE_API,
        require_citations=True,
        on_failure="retry_stage",
        custom_checks=["schema_validation", "backward_compatibility"],
    ),
    "data_pipeline": TemplateQualityGates(
        min_confidence=PROB_VERY_HIGH,
        require_citations=False,
        on_failure="escalate",
        custom_checks=["data_quality", "completeness"],
    ),
    "cli_tool": TemplateQualityGates(
        min_confidence=PROB_HIGH,
        require_citations=False,
        on_failure="retry_stage",
        custom_checks=["help_text", "exit_codes"],
    ),
}

DEFAULT_QUALITY_GATES = TemplateQualityGates()


def get_quality_gates(product_type: str) -> TemplateQualityGates:
    """Return quality gates for a product type, or defaults if unknown."""
    return PRODUCT_QUALITY_GATES.get(product_type, DEFAULT_QUALITY_GATES)
