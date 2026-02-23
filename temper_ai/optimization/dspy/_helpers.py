"""Shared helpers for DSPy optimization."""

import logging
from typing import Any

from temper_ai.optimization.dspy._schemas import TrainingExample
from temper_ai.optimization.dspy.constants import INSTALL_HINT

logger = logging.getLogger(__name__)


def ensure_dspy_available() -> None:
    """Import dspy or raise ImportError with install hint."""
    try:
        import dspy  # noqa: F401
    except ImportError:
        raise ImportError(
            f"DSPy is required for prompt optimization. {INSTALL_HINT}"
        ) from None


LOCAL_PROVIDERS = frozenset({"ollama", "vllm"})
DUMMY_API_KEY = "not-needed"  # noqa: S105


def configure_dspy_lm(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Any:
    """Configure and return a dspy.LM instance."""
    ensure_dspy_available()
    import dspy

    model_id = _build_model_id(provider, model)
    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    elif provider in LOCAL_PROVIDERS:
        kwargs["api_key"] = DUMMY_API_KEY
    if base_url:
        api_base = base_url.rstrip("/")
        if provider == "vllm" and not api_base.endswith("/v1"):
            api_base = f"{api_base}/v1"
        kwargs["api_base"] = api_base

    lm = dspy.LM(model_id, **kwargs)
    dspy.configure(lm=lm)
    return lm


def _build_model_id(provider: str, model: str) -> str:
    """Map provider/model to dspy model identifier."""
    provider_map = {
        "ollama": f"ollama_chat/{model}",
        "vllm": f"openai/{model}",
        "openai": f"openai/{model}",
        "anthropic": f"anthropic/{model}",
    }
    return provider_map.get(provider, f"{provider}/{model}")


def _try_parse_json(text: str) -> dict | None:
    """Try to parse a JSON string, returning None on failure."""
    import json  # noqa: PLC0415

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _map_fields(
    text: str,
    field_names: list[str] | None,
    default_key: str,
) -> dict:
    """Map a raw text value to one or more named fields.

    When *field_names* contains more than one entry the text is
    JSON-parsed and each field is extracted individually.  Falls back
    to assigning the full text to the first field (or *default_key*)
    when parsing fails or only a single field is requested.
    """
    if field_names and len(field_names) > 1:
        parsed = _try_parse_json(text)
        if parsed:
            return {f: str(parsed.get(f, "")) for f in field_names}
        return {field_names[0]: text}
    if field_names:
        return {field_names[0]: text}
    return {default_key: text}


def _map_example_fields(
    ex: TrainingExample,
    input_fields: list[str] | None,
    output_fields: list[str] | None,
) -> dict:
    """Map a TrainingExample to named field kwargs for dspy.Example.

    When multi-field: tries JSON-parsing input_text/output_text.
    When single-field: uses current behavior (input/output keys).
    """
    fields: dict = {}
    fields.update(_map_fields(ex.input_text, input_fields, "input"))
    fields.update(_map_fields(ex.output_text, output_fields, "output"))
    return fields


def examples_to_dspy(
    examples: list[TrainingExample],
    input_fields: list[str] | None = None,
    output_fields: list[str] | None = None,
) -> list[Any]:
    """Convert TrainingExample list to dspy.Example objects."""
    ensure_dspy_available()
    import dspy  # noqa: PLC0415

    in_fields = input_fields or ["input"]

    result = []
    for ex in examples:
        fields = _map_example_fields(ex, input_fields, output_fields)
        dspy_ex = dspy.Example(**fields).with_inputs(*in_fields)
        result.append(dspy_ex)
    return result
