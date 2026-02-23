"""Data lineage tracking for stage output attribution.

Provides stateless functions to compute which agent produced which output
during stage synthesis. Results are stored as output_lineage on StageExecution.

Uses SHA-256 first-16-hex-chars pattern (same as error_fingerprinting.py).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Hash length matches error_fingerprinting.py
LINEAGE_HASH_LENGTH = 16  # noqa — scanner: skip-magic

# Contribution type constants
CONTRIBUTION_PRIMARY = "primary"
CONTRIBUTION_SYNTHESIZED = "synthesized"
CONTRIBUTION_VOTE = "vote"
CONTRIBUTION_FAILED = "failed"


@dataclass
class OutputLineageEntry:
    """Lineage record for a single agent's contribution."""

    agent_name: str
    contribution_type: str  # primary / synthesized / vote / failed
    output_hash: str
    status: str = "success"


@dataclass
class StageOutputLineage:
    """Aggregated lineage for a stage execution."""

    stage_name: str
    entries: list[OutputLineageEntry]
    synthesis_method: str | None = None


def _hash_output(output: Any) -> str:
    """Compute SHA-256 first-16-hex-chars hash of an agent output."""
    text = str(output) if output is not None else ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:LINEAGE_HASH_LENGTH]


def _classify_contribution(
    agent_name: str,
    agent_status: str,
    successful_agents: list[str],
    synthesis_method: str | None,
) -> str:
    """Classify an agent's contribution type based on status and synthesis method."""
    if agent_status != "success":
        return CONTRIBUTION_FAILED

    if len(successful_agents) == 1:
        return CONTRIBUTION_PRIMARY

    if synthesis_method and synthesis_method in ("vote", "majority_vote", "voting"):
        return CONTRIBUTION_VOTE

    return CONTRIBUTION_SYNTHESIZED


def compute_output_lineage(
    stage_name: str,
    agent_outputs: dict[str, Any],
    agent_statuses: dict[str, Any],
    synthesis_method: str | None = None,
) -> StageOutputLineage:
    """Compute lineage from agent outputs and statuses.

    Args:
        stage_name: Name of the stage
        agent_outputs: Dict of {agent_name: output_data}
        agent_statuses: Dict of {agent_name: status_str}
        synthesis_method: Synthesis method used (e.g. "vote", "merge")

    Returns:
        StageOutputLineage with per-agent attribution
    """
    successful_agents = [
        name for name, status in agent_statuses.items() if status == "success"
    ]

    entries: list[OutputLineageEntry] = []
    for agent_name in sorted(agent_statuses.keys()):
        status = agent_statuses.get(agent_name, "unknown")
        output = agent_outputs.get(agent_name)
        output_hash = _hash_output(output)

        contribution = _classify_contribution(
            agent_name,
            status,
            successful_agents,
            synthesis_method,
        )
        entries.append(
            OutputLineageEntry(
                agent_name=agent_name,
                contribution_type=contribution,
                output_hash=output_hash,
                status=status,
            )
        )

    return StageOutputLineage(
        stage_name=stage_name,
        entries=entries,
        synthesis_method=synthesis_method,
    )


def lineage_to_dict(lineage: StageOutputLineage) -> dict[str, Any]:
    """Serialize StageOutputLineage to a JSON-compatible dict."""
    return asdict(lineage)
