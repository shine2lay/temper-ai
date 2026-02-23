"""Schema declarations for stage-level context management.

Defines input/output declarations that stages use to specify what data
they read from prior stages/workflow and what structured fields they produce.

Input declarations with ``source`` refs enable selective context resolution,
replacing the default pass-everything behavior. Output declarations enable
structured field extraction from raw LLM output.

Example YAML::

    stage:
      inputs:
        suggestion_text:
          source: workflow.suggestion_text
          required: true
        triage_decision:
          source: vcs_triage.final_decision
          required: true
      outputs:
        final_decision:
          type: string
          description: "Approved, rejected, or needs revision"
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator

# Valid source pattern: workflow.<field> or <stage>.<field> or <stage>.structured.<field>
# or <stage>.raw.<field> — with nested dot paths allowed
_SOURCE_PATTERN = re.compile(
    r"^(workflow|[a-zA-Z_][a-zA-Z0-9_]*)"  # prefix: "workflow" or stage name
    r"(\.(structured|raw))?"  # optional compartment
    r"(\.[a-zA-Z_][a-zA-Z0-9_]*)+"  # at least one .field segment
    r"$"
)


class StageInputDeclaration(BaseModel):
    """Declaration of a single stage input with source reference.

    Attributes:
        source: Where to read the value from.
            Format: ``workflow.<field>`` or ``<stage>.<field>``
            or ``<stage>.structured.<field>`` or ``<stage>.raw.<field>``
        required: If True, missing value raises ContextResolutionError.
        default: Fallback value when required is False and source is missing.
        description: Human-readable description for documentation.
    """

    source: str
    required: bool = True
    default: Any = None
    description: str | None = None

    @field_validator("source")
    @classmethod
    def validate_source_format(cls, v: str) -> str:
        """Validate source matches expected format."""
        if not _SOURCE_PATTERN.match(v):
            raise ValueError(
                f"Invalid source format: '{v}'. "
                "Expected: 'workflow.<field>', '<stage>.<field>', "
                "'<stage>.structured.<field>', or '<stage>.raw.<field>'"
            )
        return v


class StageOutputDeclaration(BaseModel):
    """Declaration of a single structured output field to extract.

    Attributes:
        type: Expected data type for the extracted field.
        description: Human-readable description (used in extraction prompt).
    """

    type: Literal["string", "list", "dict", "number", "boolean", "any"] = "string"
    description: str | None = None


def parse_stage_inputs(
    raw: dict[str, Any] | None,
) -> dict[str, StageInputDeclaration] | None:
    """Parse raw YAML inputs into input declarations.

    Returns None if inputs are omitted/None (legacy passthrough mode).
    Entries without a ``source`` key are skipped (old documentation-only format).
    If at least one entry has a ``source`` key, all sourced entries are parsed.

    Args:
        raw: Raw inputs dict from stage YAML, or None.

    Returns:
        Dict of input name -> StageInputDeclaration, or None for passthrough.

    Raises:
        ValueError: If a sourced entry has an invalid source format.
    """
    if raw is None:
        return None

    # Check if any entry uses the new source-ref format
    has_source_refs = any(isinstance(v, dict) and "source" in v for v in raw.values())

    if not has_source_refs:
        # All entries are old documentation-only format — treat as passthrough
        return None

    result: dict[str, StageInputDeclaration] = {}
    for name, value in raw.items():
        if isinstance(value, dict) and "source" in value:
            result[name] = StageInputDeclaration(**value)
        # Entries without source are skipped (documentation-only)

    return result if result else None


def parse_stage_outputs(
    raw: dict[str, Any] | None,
) -> dict[str, StageOutputDeclaration]:
    """Parse raw YAML outputs into output declarations.

    Args:
        raw: Raw outputs dict from stage YAML, or None.

    Returns:
        Dict of output name -> StageOutputDeclaration. Empty dict if None.
    """
    if not raw:
        return {}

    result: dict[str, StageOutputDeclaration] = {}
    for name, value in raw.items():
        if isinstance(value, dict):
            result[name] = StageOutputDeclaration(**value)
        # Skip non-dict entries (old documentation-only format)

    return result
