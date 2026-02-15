"""Output extraction for structured stage results.

Provides two-compartment storage: structured fields extracted from raw LLM
output sit alongside the raw execution data. The ``SourceResolver`` checks
structured first, then falls through to raw and top-level compat keys.

Two implementations:

- ``LLMOutputExtractor``: Uses a cheap LLM call to extract structured fields
  from raw text according to output declarations.
- ``NoopExtractor``: Returns empty dict. Used when no outputs are declared
  or extraction is disabled.
"""
import json
import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from src.workflow.context_schemas import StageOutputDeclaration

logger = logging.getLogger(__name__)

# Timeout for extraction LLM calls (seconds)
DEFAULT_EXTRACTION_TIMEOUT = 30

# Max characters of raw output to send to the extraction LLM
MAX_EXTRACTION_TEXT_LENGTH = 4000


@runtime_checkable
class OutputExtractor(Protocol):
    """Protocol for extracting structured fields from raw stage output."""

    def extract(
        self,
        raw_output: str,
        output_declarations: Dict[str, StageOutputDeclaration],
        stage_name: str,
    ) -> Dict[str, Any]:
        """Extract structured fields from raw output text.

        Args:
            raw_output: Raw text output from stage execution.
            output_declarations: Declared output fields and their types.
            stage_name: Name of the stage (for logging).

        Returns:
            Dict mapping field name to extracted value.
        """
        ...


class NoopExtractor:
    """Returns empty dict. Used when no outputs are declared."""

    def extract(
        self,
        raw_output: str,
        output_declarations: Dict[str, StageOutputDeclaration],
        stage_name: str,
    ) -> Dict[str, Any]:
        """Return empty dict — no extraction needed."""
        return {}


class LLMOutputExtractor:
    """Extract structured fields from raw text via a cheap LLM call.

    Uses the framework's LLM infrastructure to parse raw stage output
    into declared structured fields.
    """

    def __init__(
        self,
        inference_config: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = DEFAULT_EXTRACTION_TIMEOUT,
    ) -> None:
        self.inference_config = inference_config or {}
        self.timeout_seconds = timeout_seconds

    def extract(
        self,
        raw_output: str,
        output_declarations: Dict[str, StageOutputDeclaration],
        stage_name: str,
    ) -> Dict[str, Any]:
        """Extract structured fields from raw output via LLM call."""
        if not output_declarations or not raw_output:
            return {}

        prompt = self._build_extraction_prompt(raw_output, output_declarations)

        try:
            response_text = self._call_llm(prompt)
            return self._parse_extraction_response(response_text)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(
                "Output extraction failed for stage '%s': %s. "
                "Structured compartment will be empty.",
                stage_name, e,
            )
            return {}

    def _build_extraction_prompt(
        self,
        raw_output: str,
        output_declarations: Dict[str, StageOutputDeclaration],
    ) -> str:
        """Build the extraction prompt for the LLM."""
        fields_desc = []
        for name, decl in output_declarations.items():
            desc = decl.description or name
            fields_desc.append(f'  "{name}": ({decl.type}) {desc}')
        fields_text = "\n".join(fields_desc)

        return (
            "Extract the following fields from the text below. "
            "Return ONLY a valid JSON object with these fields:\n"
            f"{fields_text}\n\n"
            "--- TEXT ---\n"
            f"{raw_output[:MAX_EXTRACTION_TEXT_LENGTH]}\n"
            "--- END TEXT ---\n\n"
            "Return ONLY the JSON object, no explanation."
        )

    def _call_llm(self, prompt: str) -> str:
        """Call LLM for extraction. Override in tests."""
        try:
            from src.llm.providers.factory import create_llm_client

            provider = self.inference_config.get("provider", "ollama")
            model = self.inference_config.get("model", "qwen3:8b")
            base_url = self.inference_config.get("base_url", "")
            if not base_url:
                # Sensible defaults for local providers
                default_urls = {
                    "ollama": "http://localhost:11434",
                    "vllm": "http://localhost:8000",
                }
                base_url = default_urls.get(provider, "")

            llm = create_llm_client(
                provider=provider,
                model=model,
                base_url=base_url,
                timeout=self.timeout_seconds,
            )
            response = llm.complete(prompt)
            return response.content if hasattr(response, "content") else str(response)
        except ImportError:
            logger.warning("LLM infrastructure not available for output extraction")
            return "{}"

    @staticmethod
    def _parse_extraction_response(response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = response.strip()
        # Strip markdown code block if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        result: Dict[str, Any] = json.loads(text)
        return result


def get_extractor(
    workflow_config: Optional[Dict[str, Any]] = None,
) -> OutputExtractor:
    """Get the appropriate extractor based on workflow configuration.

    Reads ``workflow.context_management.extraction`` from the workflow config.
    Returns NoopExtractor if not configured or disabled.

    Args:
        workflow_config: Workflow configuration dict.

    Returns:
        OutputExtractor instance.
    """
    if not workflow_config:
        return NoopExtractor()

    wf = workflow_config.get("workflow", {})
    ctx_mgmt = wf.get("context_management", {})
    extraction = ctx_mgmt.get("extraction", {})

    if not extraction.get("enabled", False):
        return NoopExtractor()

    inference = {
        "provider": extraction.get("provider", "ollama"),
        "model": extraction.get("model", "qwen3:8b"),
    }
    if extraction.get("base_url"):
        inference["base_url"] = extraction["base_url"]

    return LLMOutputExtractor(
        inference_config=inference,
        timeout_seconds=extraction.get("timeout_seconds", DEFAULT_EXTRACTION_TIMEOUT),
    )
