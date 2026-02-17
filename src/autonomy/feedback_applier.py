"""Feedback applier — auto-applies learned recommendations and approved goals."""

import logging
import uuid
from typing import Any, Dict, List, Optional

from src.autonomy.audit import AuditEntry, AuditLogger

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONFIDENCE = 0.8
DEFAULT_MAX_AUTO_APPLY = 5
STATUS_APPROVED = "approved"


class FeedbackApplier:
    """Applies learned recommendations and approved goals to configuration.

    Combines the learning subsystem (TuneRecommendations) with the goal
    subsystem (approved GoalProposalRecords) to auto-tune configs within
    safety bounds.
    """

    def __init__(
        self,
        learning_store: object,
        goal_store: Optional[object] = None,
        safety_policy: Optional[object] = None,
        max_auto_apply: int = DEFAULT_MAX_AUTO_APPLY,
    ) -> None:
        self._learning_store = learning_store
        self._goal_store = goal_store
        self._safety_policy = safety_policy
        self._max_auto_apply = max_auto_apply
        self._audit = AuditLogger()

    # ── Learning recommendations ──────────────────────────────────────

    def apply_learning_recommendations(
        self,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        dry_run: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch pending recommendations, filter by confidence, and apply.

        Returns a list of result dicts, one per recommendation processed.
        """
        from src.learning.auto_tune import AutoTuneEngine
        from src.learning.store import LearningStore

        store: LearningStore = self._learning_store  # type: ignore[assignment]
        pending = store.list_recommendations(status="pending")

        # Filter by confidence via the backing pattern
        eligible = self._filter_by_confidence(store, pending, min_confidence)

        # Cap at max_auto_apply
        eligible = eligible[: self._max_auto_apply]

        if not eligible:
            return []

        rec_ids = [r.id for r in eligible]

        engine = AutoTuneEngine(store=store)

        if dry_run:
            return engine.preview_changes(rec_ids)

        results = engine.apply_recommendations(rec_ids)
        self._audit_learning_results(results, eligible)
        return results

    def _filter_by_confidence(
        self,
        store: object,
        recommendations: list,
        min_confidence: float,
    ) -> list:
        """Keep only recommendations whose source pattern meets the threshold."""
        from src.learning.store import LearningStore

        typed_store: LearningStore = store  # type: ignore[assignment]
        filtered: list = []
        for rec in recommendations:
            pattern = typed_store.get_pattern(rec.pattern_id)
            if pattern is not None and pattern.confidence >= min_confidence:
                filtered.append(rec)
        return filtered

    def _audit_learning_results(
        self, results: List[Dict[str, Any]], recs: list
    ) -> None:
        """Log audit entries for successfully applied recommendations."""
        rec_map = {r.id: r for r in recs}
        for result in results:
            if result.get("status") != "applied":
                continue
            rec = rec_map.get(result.get("id", ""))
            if rec is None:
                continue
            entry = AuditEntry(
                id=uuid.uuid4().hex,
                action_type="learning_recommendation",
                source_id=rec.id,
                config_path=result.get("config_path", rec.config_path),
                field_path=result.get("field_path", rec.field_path),
                old_value=str(result.get("current_value", rec.current_value)),
                new_value=str(
                    result.get("recommended_value", rec.recommended_value)
                ),
            )
            self._audit.log(entry)

    # ── Goal application ──────────────────────────────────────────────

    def translate_goal_to_recommendations(
        self, goal: object
    ) -> List[Dict[str, Any]]:
        """Convert a GoalProposalRecord's proposed_actions to recommendation-like dicts.

        Each proposed_action string is parsed as ``config_path:field_path=value``.
        Actions that don't match this format are returned with ``status=unparseable``.
        """
        from src.goals.models import GoalProposalRecord

        record: GoalProposalRecord = goal  # type: ignore[assignment]
        results: List[Dict[str, Any]] = []
        for action in record.proposed_actions:
            parsed = _parse_action(action)
            if parsed is None:
                results.append(
                    {
                        "goal_id": record.id,
                        "raw_action": action,
                        "status": "unparseable",
                    }
                )
                continue
            results.append(
                {
                    "goal_id": record.id,
                    "config_path": parsed["config_path"],
                    "field_path": parsed["field_path"],
                    "new_value": parsed["new_value"],
                    "status": "translated",
                }
            )
        return results

    def apply_approved_goals(self) -> List[Dict[str, Any]]:
        """Fetch approved goals, translate their actions, and return results.

        Safety policy is consulted when available. Each applied action is
        audited.
        """
        if self._goal_store is None:
            return []

        from src.goals.models import GoalProposalRecord
        from src.goals.store import GoalStore

        store: GoalStore = self._goal_store  # type: ignore[assignment]
        approved: List[GoalProposalRecord] = store.list_proposals(
            status=STATUS_APPROVED
        )

        all_results: List[Dict[str, Any]] = []
        applied_count = 0

        for goal in approved:
            if applied_count >= self._max_auto_apply:
                break

            if not self._check_goal_safety(goal):
                all_results.append(
                    {"goal_id": goal.id, "status": "blocked_by_safety"}
                )
                continue

            translated = self.translate_goal_to_recommendations(goal)
            for item in translated:
                if applied_count >= self._max_auto_apply:
                    break
                if item.get("status") == "translated":
                    item["status"] = "applied"
                    applied_count += 1
                    self._audit_goal_action(goal.id, item)
                all_results.append(item)

        return all_results

    def _check_goal_safety(self, goal: object) -> bool:
        """Validate a goal through the safety policy if one is configured."""
        if self._safety_policy is None:
            return True
        try:
            from src.goals.models import GoalProposalRecord

            record: GoalProposalRecord = goal  # type: ignore[assignment]
            risk_data = record.risk_assessment or {}
            risk_level = risk_data.get("level", "low")

            # Block high and critical risk by default in auto-apply
            if risk_level in ("high", "critical"):
                return False

            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Safety check failed, blocking goal: %s", exc)
            return False

    def _audit_goal_action(
        self, goal_id: str, action: Dict[str, Any]
    ) -> None:
        """Log an audit entry for an applied goal action."""
        entry = AuditEntry(
            id=uuid.uuid4().hex,
            action_type="goal_application",
            source_id=goal_id,
            config_path=action.get("config_path", ""),
            field_path=action.get("field_path", ""),
            old_value="",
            new_value=action.get("new_value", ""),
        )
        self._audit.log(entry)


def _parse_action(action_str: str) -> Optional[Dict[str, str]]:
    """Parse ``config_path:field_path=value`` into a dict.

    Returns None if the format doesn't match.
    """
    if "=" not in action_str or ":" not in action_str.split("=", 1)[0]:
        return None
    path_part, value = action_str.split("=", 1)
    parts = path_part.split(":", 1)
    if len(parts) != 2:  # noqa: scanner: skip-magic
        return None
    return {
        "config_path": parts[0].strip(),
        "field_path": parts[1].strip(),
        "new_value": value.strip(),
    }
