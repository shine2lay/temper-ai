"""DSPy program builder — converts agent config to dspy.Module."""

import logging
import re
from typing import Any

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig
from temper_ai.optimization.dspy.constants import MAX_FIELD_NAME_LENGTH

logger = logging.getLogger(__name__)

# Template variables that are injected by the framework, not user input
INTERNAL_TEMPLATE_VARS: frozenset[str] = frozenset(
    {
        "command_results",
        "dialogue_context",
        "memory_context",
        "tool_schemas",
        "optimization_context",
    }
)

TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# Module types that require class-based signatures
_CLASS_SIGNATURE_MODULES = frozenset({"react"})


class DSPyProgramBuilder:
    """Builds a dspy.Module from agent configuration."""

    def build_from_config(
        self,
        config: PromptOptimizationConfig,
        template_source: str | None = None,
    ) -> Any:
        """Create a dspy.Module based on the optimization config."""
        from temper_ai.optimization.dspy._helpers import (
            ensure_dspy_available,  # noqa: PLC0415
        )
        from temper_ai.optimization.dspy.modules import (
            get_module_builder,  # noqa: PLC0415
        )

        ensure_dspy_available()
        import dspy  # noqa: PLC0415

        input_fields = config.input_fields or self._extract_fields(template_source)
        output_fields = config.output_fields

        if not input_fields:
            input_fields = ["input"]

        signature = self._resolve_signature(
            dspy,
            input_fields,
            output_fields,
            config,
        )

        builder = get_module_builder(config.module_type)
        return builder(dspy, signature, config)

    def _extract_fields(self, template_source: str | None) -> list[str]:
        """Extract user-facing template variables from Jinja2 source."""
        if not template_source:
            return []
        matches = TEMPLATE_VAR_PATTERN.findall(template_source)
        fields: list[str] = []
        seen: set = set()
        for match in matches:
            if match not in INTERNAL_TEMPLATE_VARS and match not in seen:
                if len(match) <= MAX_FIELD_NAME_LENGTH:
                    fields.append(match)
                    seen.add(match)
        return fields

    @staticmethod
    def _resolve_signature(
        dspy_mod: Any,
        input_fields: list[str],
        output_fields: list[str],
        config: PromptOptimizationConfig,
    ) -> Any:
        """Build a string or class-based signature depending on config."""
        use_class = (
            config.signature_style == "class"
            or config.module_type in _CLASS_SIGNATURE_MODULES
        )
        if use_class:
            return DSPyProgramBuilder._build_class_signature(
                dspy_mod,
                input_fields,
                output_fields,
                config.field_descriptions,
            )
        return DSPyProgramBuilder._build_signature(
            dspy_mod,
            input_fields,
            output_fields,
        )

    @staticmethod
    def _build_signature(
        _dspy_module: object,
        input_fields: list[str],
        output_fields: list[str],
    ) -> str:
        """Build a dspy.Signature string from field lists."""
        return ", ".join(input_fields) + " -> " + ", ".join(output_fields)

    @staticmethod
    def _build_class_signature(
        dspy_mod: Any,
        input_fields: list[str],
        output_fields: list[str],
        descriptions: dict[str, str] | None = None,
    ) -> Any:
        """Build a class-based dspy.Signature with field descriptions."""
        descs = descriptions or {}
        attrs: dict[str, Any] = {}
        for field in input_fields:
            desc = descs.get(field, f"Input: {field}")
            attrs[field] = dspy_mod.InputField(desc=desc)
        for field in output_fields:
            desc = descs.get(field, f"Output: {field}")
            attrs[field] = dspy_mod.OutputField(desc=desc)
        return type("DynamicSignature", (dspy_mod.Signature,), attrs)
