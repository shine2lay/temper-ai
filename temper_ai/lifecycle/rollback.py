"""Rollback monitor for lifecycle adaptation.

Detects quality degradation from lifecycle adaptations and
disables problematic profiles to prevent sustained regressions.
"""

import logging

from temper_ai.lifecycle._schemas import DegradationReport
from temper_ai.lifecycle.constants import (
    DEFAULT_DEGRADATION_THRESHOLD,
    DEFAULT_DEGRADATION_WINDOW,
)
from temper_ai.lifecycle.history import HistoryAnalyzer
from temper_ai.lifecycle.store import LifecycleStore

logger = logging.getLogger(__name__)


class RollbackMonitor:
    """Monitors for quality degradation from lifecycle adaptations."""

    def __init__(
        self,
        store: LifecycleStore,
        history: HistoryAnalyzer,
        threshold: float = DEFAULT_DEGRADATION_THRESHOLD,
    ) -> None:
        self._store = store
        self._history = history
        self._threshold = threshold

    def check_degradation(
        self,
        profile_name: str,
        window: int = DEFAULT_DEGRADATION_WINDOW,
    ) -> DegradationReport | None:
        """Check if a profile has caused quality degradation.

        Compares recent adapted runs vs baseline success rate.
        Returns a report if degradation exceeds threshold.

        Args:
            profile_name: Name of the profile to check.
            window: Number of recent adaptations to examine.

        Returns:
            DegradationReport if degradation detected, else None.
        """
        adaptations = self._store.list_adaptations(
            profile_name=profile_name, limit=window
        )

        if len(adaptations) < 2:
            return None  # Not enough data

        # Get workflow metrics for adapted runs
        adapted_results = _compute_adapted_success_rate(adaptations, self._history)
        if adapted_results is None:
            return None

        adapted_rate, sample_size = adapted_results

        # Get baseline metrics (overall workflow success rate)
        workflow_names = set()
        for a in adaptations:
            # Extract workflow name from characteristics
            chars = a.characteristics or {}
            wf_name = chars.get("workflow_name", "")
            if wf_name:
                workflow_names.add(wf_name)

        baseline_rate = _get_baseline_rate(workflow_names, self._history)

        degradation_pct = baseline_rate - adapted_rate
        if degradation_pct > self._threshold:
            report = DegradationReport(
                profile_name=profile_name,
                baseline_success_rate=baseline_rate,
                adapted_success_rate=adapted_rate,
                degradation_pct=degradation_pct,
                sample_size=sample_size,
            )
            logger.warning(
                "Degradation detected for profile %s: "
                "baseline=%.2f, adapted=%.2f, drop=%.2f%%",
                profile_name,
                baseline_rate,
                adapted_rate,
                degradation_pct * 100,
            )
            return report

        return None

    def revert_profile(self, profile_name: str) -> None:
        """Disable a degraded profile in the store.

        Args:
            profile_name: Name of the profile to disable.
        """
        success = self._store.update_profile_status(profile_name, enabled=False)
        if success:
            logger.info("Disabled profile: %s", profile_name)
        else:
            logger.warning(
                "Profile %s not found in DB (may be YAML-only)",
                profile_name,
            )


def _compute_adapted_success_rate(
    adaptations: list,
    history: HistoryAnalyzer,
) -> tuple[float, int] | None:
    """Compute real success rate for adapted workflow runs.

    For each adaptation, extracts the workflow_name from characteristics
    and queries actual metrics from HistoryAnalyzer.

    Returns (success_rate, sample_size) or None if no measurable data.
    """
    if not adaptations:
        return None

    total = len(adaptations)
    successes: float = 0.0
    measured = 0

    for adaptation in adaptations:
        chars = adaptation.characteristics or {}
        wf_name = chars.get("workflow_name", "")
        if not wf_name:
            continue
        metrics = history.get_workflow_metrics(wf_name)
        if metrics.run_count > 0:
            measured += 1
            successes += metrics.success_rate

    if measured == 0:
        return None  # No measurable data yet

    return successes / measured, total


def _get_baseline_rate(
    workflow_names: set,
    history: HistoryAnalyzer,
) -> float:
    """Get baseline success rate across workflows."""
    if not workflow_names:
        return 1.0

    rates = []
    for name in workflow_names:
        metrics = history.get_workflow_metrics(name)
        if metrics.run_count > 0:
            rates.append(metrics.success_rate)

    if not rates:
        return 1.0

    return sum(rates) / len(rates)
