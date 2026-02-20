"""Heuristic output quality scorer for agent executions.

This module provides a lightweight heuristic to assign an output quality
score when recording agent completions.  It is intentionally kept simple
so it can be called synchronously without blocking the tracking path.

Wiring:
    Call ``compute_quality_score(status, output_data)`` when recording
    agent completion (e.g. in ``SQLObservabilityBackend.track_agent_end``
    or ``set_agent_output``), then persist the returned value to
    ``AgentExecution.output_quality_score``.

Example::

    from temper_ai.observability._quality_scorer import compute_quality_score

    score = compute_quality_score(status="completed", output_data=output)
    agent.output_quality_score = score
"""

# Quality score constants
SCORE_FAILED = 0.0
SCORE_EMPTY = 0.3
SCORE_NON_EMPTY = 1.0


def compute_quality_score(
    status: str,
    output_data: object,
) -> float:
    """Compute heuristic quality score for an agent execution.

    Returns:
        0.0 for failed executions,
        0.3 for empty output,
        1.0 for non-empty successful output.
    """
    if status != "completed":
        return SCORE_FAILED

    if output_data is None:
        return SCORE_EMPTY

    if isinstance(output_data, str) and not output_data.strip():
        return SCORE_EMPTY

    if isinstance(output_data, dict) and not output_data:
        return SCORE_EMPTY

    return SCORE_NON_EMPTY
