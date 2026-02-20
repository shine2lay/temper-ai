"""Shared helpers for DSPy optimization."""

import logging
from typing import Any, List, Optional

from temper_ai.optimization._schemas import TrainingExample
from temper_ai.optimization.constants import INSTALL_HINT

logger = logging.getLogger(__name__)


def ensure_dspy_available() -> None:
    """Import dspy or raise ImportError with install hint."""
    try:
        import dspy  # noqa: F401
    except ImportError:
        raise ImportError(
            f"DSPy is required for prompt optimization. {INSTALL_HINT}"
        ) from None


def configure_dspy_lm(
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Any:
    """Configure and return a dspy.LM instance."""
    ensure_dspy_available()
    import dspy

    model_id = _build_model_id(provider, model)
    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url

    lm = dspy.LM(model_id, **kwargs)
    dspy.configure(lm=lm)
    return lm


def _build_model_id(provider: str, model: str) -> str:
    """Map provider/model to dspy model identifier."""
    provider_map = {
        "ollama": f"ollama_chat/{model}",
        "openai": f"openai/{model}",
        "anthropic": f"anthropic/{model}",
    }
    return provider_map.get(provider, f"{provider}/{model}")


def examples_to_dspy(examples: List[TrainingExample]) -> List[Any]:
    """Convert TrainingExample list to dspy.Example objects."""
    ensure_dspy_available()
    import dspy

    result = []
    for ex in examples:
        dspy_ex = dspy.Example(
            input=ex.input_text, output=ex.output_text,
        ).with_inputs("input")
        result.append(dspy_ex)
    return result
