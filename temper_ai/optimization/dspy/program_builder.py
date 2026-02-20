"""DSPy program builder — converts agent config to dspy.Module."""

import logging
import re
from typing import Any, FrozenSet, List, Optional

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig
from temper_ai.optimization.dspy.constants import MAX_FIELD_NAME_LENGTH

logger = logging.getLogger(__name__)

# Template variables that are injected by the framework, not user input
INTERNAL_TEMPLATE_VARS: FrozenSet[str] = frozenset({
    "command_results",
    "dialogue_context",
    "memory_context",
    "tool_schemas",
    "optimization_context",
})

TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class DSPyProgramBuilder:
    """Builds a dspy.Module from agent configuration."""

    def build_from_config(
        self,
        config: PromptOptimizationConfig,
        template_source: Optional[str] = None,
    ) -> Any:
        """Create a dspy.Module based on the optimization config."""
        from temper_ai.optimization.dspy._helpers import ensure_dspy_available
        ensure_dspy_available()
        import dspy

        input_fields = config.input_fields or self._extract_fields(template_source)
        output_fields = config.output_fields

        if not input_fields:
            input_fields = ["input"]

        signature = self._build_signature(dspy, input_fields, output_fields)

        if config.module_type == "chain_of_thought":
            return dspy.ChainOfThought(signature)
        return dspy.Predict(signature)

    def _extract_fields(self, template_source: Optional[str]) -> List[str]:
        """Extract user-facing template variables from Jinja2 source."""
        if not template_source:
            return []
        matches = TEMPLATE_VAR_PATTERN.findall(template_source)
        fields = []
        seen: set = set()
        for match in matches:
            if match not in INTERNAL_TEMPLATE_VARS and match not in seen:
                if len(match) <= MAX_FIELD_NAME_LENGTH:
                    fields.append(match)
                    seen.add(match)
        return fields

    @staticmethod
    def _build_signature(_dspy_module: object, input_fields: List[str], output_fields: List[str]) -> str:
        """Build a dspy.Signature string from field lists."""
        return ", ".join(input_fields) + " -> " + ", ".join(output_fields)
