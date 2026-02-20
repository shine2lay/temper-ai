"""DSPy prompt adapter — injects compiled program sections into prompts."""

import logging
from typing import Any

from temper_ai.optimization.constants import (
    DEFAULT_MAX_DEMOS,
    EXAMPLES_HEADER,
    OPTIMIZATION_HEADER,
    OPTIMIZATION_SECTION_SEPARATOR,
)

logger = logging.getLogger(__name__)


class DSPyPromptAdapter:
    """Augments rendered prompts with DSPy-optimized instruction and demos."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def augment_prompt(
        self,
        agent_name: str,
        rendered_prompt: str,
        max_demos: int = DEFAULT_MAX_DEMOS,
    ) -> str:
        """Append optimized guidance and examples to the rendered prompt."""
        program_data = self._store.load_latest(agent_name)
        if program_data is None:
            return rendered_prompt

        inner = program_data.get("program_data", {})
        instruction = inner.get("instruction", "")
        demos = inner.get("demos", [])

        if not instruction and not demos:
            return rendered_prompt

        sections = [rendered_prompt, OPTIMIZATION_SECTION_SEPARATOR.lstrip("\n")]

        if instruction:
            sections.append(f"{OPTIMIZATION_HEADER}\n{instruction}")

        if demos:
            sections.append(self._format_demos(demos, max_demos))

        return "\n".join(sections)

    @staticmethod
    def _format_demos(demos: list, max_demos: int) -> str:
        """Format few-shot demos as numbered examples."""
        limited = demos[:max_demos]
        parts = [EXAMPLES_HEADER]
        for idx, demo in enumerate(limited, 1):
            input_text = demo.get("input", "")
            output_text = demo.get("output", "")
            parts.append(
                f"## Example {idx}\nInput: {input_text}\nOutput: {output_text}"
            )
        return "\n".join(parts)
