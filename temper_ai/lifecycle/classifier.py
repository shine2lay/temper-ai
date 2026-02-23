"""Project classifier for lifecycle adaptation.

Classifies project characteristics using LLM inference with
explicit-input fallback for deterministic operation without LLM.
"""

import json
import logging
from typing import Any

from temper_ai.lifecycle._schemas import (
    ProjectCharacteristics,
    ProjectSize,
    RiskLevel,
)

logger = logging.getLogger(__name__)

# Keys checked in input data for explicit classification
_EXPLICIT_KEYS = frozenset({"size", "risk_level", "is_prototype", "tags"})

_CLASSIFICATION_PROMPT = """Analyze the following project and classify it.

Project description: {description}
Workflow stages: {stages}

Respond with ONLY valid JSON (no markdown):
{{
    "size": "small" | "medium" | "large",
    "risk_level": "low" | "medium" | "high" | "critical",
    "estimated_complexity": 0.0 to 1.0,
    "is_prototype": true | false,
    "tags": ["tag1", "tag2"]
}}"""


class ProjectClassifier:
    """Classifies project characteristics for lifecycle adaptation.

    Fallback chain: explicit input -> LLM inference -> conservative defaults.
    """

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    def classify(
        self,
        workflow_config: dict[str, Any],
        input_data: dict[str, Any],
    ) -> ProjectCharacteristics:
        """Classify project characteristics.

        Args:
            workflow_config: Workflow configuration dict.
            input_data: User-provided input data.

        Returns:
            ProjectCharacteristics with inferred or explicit values.
        """
        # Start with defaults
        chars = _extract_explicit(input_data)

        # If minimum required fields (size + risk_level) are explicit, skip LLM
        if _has_all_explicit(input_data):
            logger.info("All characteristics explicitly provided")
            return chars

        # Try LLM inference for missing fields
        if self._llm is not None:
            llm_chars = self._classify_with_llm(workflow_config, input_data)
            if llm_chars is not None:
                chars = _merge_characteristics(chars, llm_chars)

        return chars

    def _classify_with_llm(
        self,
        workflow_config: dict[str, Any],
        input_data: dict[str, Any],
    ) -> ProjectCharacteristics | None:
        """Use LLM to infer project characteristics."""
        try:
            wf = workflow_config.get("workflow", {})
            stages = [s.get("name", "") for s in wf.get("stages", [])]
            description = input_data.get(
                "project_description", wf.get("description", "")
            )

            prompt = _CLASSIFICATION_PROMPT.format(
                description=description,
                stages=", ".join(stages),
            )

            response = self._llm.complete(prompt)  # type: ignore[union-attr]
            content = str(response.content).strip()
            return _parse_llm_response(content)
        except Exception:  # noqa: BLE001 -- fallback gracefully
            logger.warning(
                "LLM classification failed, using defaults",
                exc_info=True,
            )
            return None


def _extract_explicit(input_data: dict[str, Any]) -> ProjectCharacteristics:
    """Extract explicitly provided characteristics from input data."""
    kwargs: dict[str, Any] = {}

    if "size" in input_data:
        try:
            kwargs["size"] = ProjectSize(input_data["size"])
        except ValueError:
            logger.warning("Invalid size: %s", input_data["size"])

    if "risk_level" in input_data:
        try:
            kwargs["risk_level"] = RiskLevel(input_data["risk_level"])
        except ValueError:
            logger.warning("Invalid risk_level: %s", input_data["risk_level"])

    if "is_prototype" in input_data:
        kwargs["is_prototype"] = bool(input_data["is_prototype"])

    if "tags" in input_data:
        kwargs["tags"] = list(input_data["tags"])

    if "product_type" in input_data:
        kwargs["product_type"] = str(input_data["product_type"])

    if "estimated_complexity" in input_data:
        kwargs["estimated_complexity"] = float(input_data["estimated_complexity"])

    return ProjectCharacteristics(**kwargs)


def _has_all_explicit(input_data: dict[str, Any]) -> bool:
    """Check if minimum required classification fields (size, risk_level) are provided."""
    return "size" in input_data and "risk_level" in input_data


def _merge_characteristics(
    explicit: ProjectCharacteristics,
    llm: ProjectCharacteristics,
) -> ProjectCharacteristics:
    """Merge LLM-inferred characteristics with explicit overrides."""
    data = llm.model_dump()
    explicit_data = explicit.model_dump()

    # Explicit values take priority
    for key, value in explicit_data.items():
        default_val = ProjectCharacteristics.model_fields[key].default
        if value != default_val:
            data[key] = value

    return ProjectCharacteristics(**data)


def _parse_llm_response(content: str) -> ProjectCharacteristics | None:
    """Parse LLM JSON response into ProjectCharacteristics."""
    try:
        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        parsed = json.loads(content)
        return ProjectCharacteristics(**parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse LLM response: %s", exc)
        return None
