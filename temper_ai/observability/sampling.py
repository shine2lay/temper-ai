"""Sampling context for observability data collection."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SamplingContext:
    """Context provided to sampling strategies for decision-making."""

    workflow_id: str = ""
    workflow_name: str = ""
    environment: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
