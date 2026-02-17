"""Core lifecycle adapter — orchestrates pre-compilation config transformation.

Adapts workflow configuration based on project characteristics, historical
outcomes, and lifecycle profiles before the config reaches LangGraph compilation.
"""

import copy
import logging
import uuid
from typing import Any, Dict, List, Optional

from src.lifecycle._schemas import (
    AdaptationAction,
    AdaptationRule,
    LifecycleProfile,
    ProjectCharacteristics,
)
from src.lifecycle.classifier import ProjectClassifier
from src.lifecycle.constants import TRUTHY_VALUES
from src.lifecycle.history import HistoryAnalyzer
from src.lifecycle.profiles import ProfileRegistry
from src.lifecycle.store import LifecycleStore

logger = logging.getLogger(__name__)

UUID_HEX_LEN = 12
MIN_STAGES_REQUIRED = 1


class LifecycleAdapter:
    """Orchestrates lifecycle adaptation of workflow configs.

    Transforms a workflow config dict before compilation by:
    1. Classifying project characteristics
    2. Selecting matching lifecycle profiles
    3. Checking autonomy level gates (M6.1)
    4. Evaluating and applying adaptation rules
    5. Recording adaptation for audit trail
    """

    def __init__(
        self,
        profile_registry: ProfileRegistry,
        classifier: ProjectClassifier,
        store: Optional[LifecycleStore] = None,
        history_analyzer: Optional[HistoryAnalyzer] = None,
        experimenter: Optional[Any] = None,
        autonomy_manager: Optional[Any] = None,
    ) -> None:
        self._registry = profile_registry
        self._classifier = classifier
        self._store = store
        self._history = history_analyzer
        self._experimenter = experimenter
        self._autonomy_manager = autonomy_manager

    def adapt(
        self,
        workflow_config: Dict[str, Any],
        input_data: Dict[str, Any],
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Adapt a workflow config based on project characteristics.

        Returns deep-copied adapted workflow config dict.
        Raises ValueError if all stages would be removed.
        """
        config = copy.deepcopy(workflow_config)
        wf = config.get("workflow", {})

        if not _check_emergency_stop():
            logger.info("Emergency stop active — skipping adaptation")
            return config

        lifecycle_cfg = wf.get("lifecycle", {})
        chars = self._classify(config, input_data, lifecycle_cfg)

        profile = self._resolve_profile(
            chars, lifecycle_cfg, wf, workflow_id
        )
        if profile is None:
            return config

        self._apply_and_record(
            wf, profile, chars, lifecycle_cfg, workflow_id
        )
        return config

    def _resolve_profile(
        self,
        chars: ProjectCharacteristics,
        lifecycle_cfg: Dict[str, Any],
        wf: Dict[str, Any],
        workflow_id: Optional[str],
    ) -> Optional[LifecycleProfile]:
        """Select and gate-check the lifecycle profile."""
        profile = self._select_profile(chars, lifecycle_cfg, wf)
        if profile is None:
            logger.info("No matching lifecycle profile found")
            return None

        if not self._check_autonomy(profile, chars):
            logger.info("Autonomy gate blocked profile: %s", profile.name)
            return None

        if self._experimenter and lifecycle_cfg.get("experiment_id"):
            exp_profile = self._experimenter.get_adapted_profile(
                lifecycle_cfg["experiment_id"],
                workflow_id or "",
                {profile.name: profile},
            )
            if exp_profile is None:
                logger.info("Experiment assigned control — no adaptation")
                return None
            return exp_profile  # type: ignore[no-any-return]

        return profile

    def _apply_and_record(
        self,
        wf: Dict[str, Any],
        profile: LifecycleProfile,
        chars: ProjectCharacteristics,
        lifecycle_cfg: Dict[str, Any],
        workflow_id: Optional[str],
    ) -> None:
        """Apply adaptation rules and record the result."""
        stages = wf.get("stages", [])
        original_names = [s.get("name", "") for s in stages]

        history_context = self._get_history_context(wf.get("name", ""))
        adapted_stages = _apply_rules(
            stages, profile.rules, chars, history_context
        )

        if len(adapted_stages) < MIN_STAGES_REQUIRED:
            raise ValueError(
                f"Lifecycle adaptation would remove all stages "
                f"(profile: {profile.name})"
            )

        wf["stages"] = adapted_stages
        adapted_names = [s.get("name", "") for s in adapted_stages]
        rules_applied = _get_applied_rule_names(
            profile.rules, original_names, adapted_names
        )

        self._record_adaptation(
            workflow_id=workflow_id or uuid.uuid4().hex[:UUID_HEX_LEN],
            profile_name=profile.name,
            chars=chars,
            rules_applied=rules_applied,
            original_names=original_names,
            adapted_names=adapted_names,
            lifecycle_cfg=lifecycle_cfg,
        )
        logger.info(
            "Adapted workflow: %s -> %s (profile: %s, rules: %d)",
            original_names, adapted_names, profile.name, len(rules_applied),
        )

    def _classify(
        self,
        config: Dict[str, Any],
        input_data: Dict[str, Any],
        lifecycle_cfg: Dict[str, Any],
    ) -> ProjectCharacteristics:
        """Classify project characteristics."""
        if lifecycle_cfg.get("auto_classify", True):
            return self._classifier.classify(config, input_data)
        return ProjectCharacteristics()

    def _select_profile(
        self,
        chars: ProjectCharacteristics,
        lifecycle_cfg: Dict[str, Any],
        wf: Dict[str, Any],
    ) -> Optional[LifecycleProfile]:
        """Select the lifecycle profile to apply."""
        # Explicit profile name
        profile_name = lifecycle_cfg.get("profile")
        if profile_name:
            profile = self._registry.get_profile(profile_name)
            if profile is None:
                logger.warning(
                    "Named profile not found: %s", profile_name
                )
            return profile

        # Auto-match
        matched = self._registry.match_profiles(
            chars, wf.get("name", "")
        )
        if matched:
            return matched[0]  # Use first match (highest priority)
        return None

    def _check_autonomy(
        self,
        profile: LifecycleProfile,
        chars: ProjectCharacteristics,
    ) -> bool:
        """Check if autonomy level allows this profile."""
        if self._autonomy_manager is None:
            # No autonomy system: only allow non-approval profiles
            return not profile.requires_approval

        try:
            level = self._autonomy_manager.get_level(
                "lifecycle_adapter", "lifecycle"
            )
            level_value = int(level)

            # Check minimum autonomy level
            if level_value < profile.min_autonomy_level:
                return False

            # Risk-based gating
            from src.lifecycle._schemas import RiskLevel

            if chars.risk_level == RiskLevel.CRITICAL:
                # STRATEGIC (4) required for CRITICAL risk
                return level_value >= 4  # scanner: skip-magic
            if profile.source != "manual":
                # RISK_GATED (2) required for learned/experiment profiles
                return level_value >= 2  # scanner: skip-magic

            return True
        except Exception:  # noqa: BLE001 -- autonomy is optional
            logger.warning(
                "Autonomy check failed, falling back to requires_approval",
                exc_info=True,
            )
            return not profile.requires_approval

    def _get_history_context(
        self, workflow_name: str
    ) -> Dict[str, Any]:
        """Build history context for Jinja2 condition evaluation."""
        if self._history is None:
            return {}

        stage_metrics = self._history.get_stage_metrics(workflow_name)
        return {
            "history": {
                name: metrics.model_dump()
                for name, metrics in stage_metrics.items()
            }
        }

    def _record_adaptation(
        self,
        workflow_id: str,
        profile_name: str,
        chars: ProjectCharacteristics,
        rules_applied: List[str],
        original_names: List[str],
        adapted_names: List[str],
        lifecycle_cfg: Dict[str, Any],
    ) -> None:
        """Record adaptation in the store for audit trail."""
        if self._store is None:
            return

        from src.lifecycle.models import LifecycleAdaptation

        adaptation = LifecycleAdaptation(
            id=uuid.uuid4().hex[:UUID_HEX_LEN],
            workflow_id=workflow_id,
            profile_name=profile_name,
            characteristics=chars.model_dump(),
            rules_applied=rules_applied,
            stages_original=original_names,
            stages_adapted=adapted_names,
            experiment_id=lifecycle_cfg.get("experiment_id"),
            experiment_variant=lifecycle_cfg.get("experiment_variant"),
        )
        try:
            self._store.save_adaptation(adaptation)
        except Exception:  # noqa: BLE001 -- recording is best-effort
            logger.warning(
                "Failed to record adaptation", exc_info=True
            )


def _apply_rules(
    stages: List[Dict[str, Any]],
    rules: List[AdaptationRule],
    chars: ProjectCharacteristics,
    history_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Apply adaptation rules to the stages list.

    Rules are sorted by priority (descending) and applied sequentially.
    """
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    env = ImmutableSandboxedEnvironment()

    # Build evaluation context
    context = chars.model_dump()
    context.update(history_context)

    # Sort by priority descending
    sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)
    result = list(stages)

    for rule in sorted_rules:
        if not _evaluate_condition(env, rule.condition, context):
            continue

        if rule.action == AdaptationAction.SKIP:
            result = _apply_skip(result, rule)
        elif rule.action == AdaptationAction.ADD:
            result = _apply_add(result, rule)
        elif rule.action == AdaptationAction.REORDER:
            result = _apply_reorder(result, rule)
        elif rule.action == AdaptationAction.MODIFY:
            result = _apply_modify(result, rule)

    return result


def _evaluate_condition(
    env: Any, condition: str, context: Dict[str, Any]
) -> bool:
    """Evaluate a Jinja2 condition expression."""
    try:
        template = env.from_string(condition)
        rendered = template.render(**context).strip().lower()
        return rendered in TRUTHY_VALUES
    except Exception:  # noqa: BLE001 -- condition failure = skip rule
        logger.warning(
            "Condition evaluation failed: %s", condition, exc_info=True
        )
        return False


def _apply_skip(
    stages: List[Dict[str, Any]], rule: AdaptationRule
) -> List[Dict[str, Any]]:
    """Remove a stage by name."""
    original_count = len(stages)
    result = [s for s in stages if s.get("name") != rule.stage_name]
    if len(result) == original_count:
        logger.warning(
            "Skip rule %s: stage %s not found",
            rule.name,
            rule.stage_name,
        )
    return result


def _apply_add(
    stages: List[Dict[str, Any]], rule: AdaptationRule
) -> List[Dict[str, Any]]:
    """Add a new stage at the specified position."""
    # Check if stage already exists
    existing = {s.get("name") for s in stages}
    if rule.stage_name in existing:
        logger.info(
            "Add rule %s: stage %s already exists, skipping",
            rule.name,
            rule.stage_name,
        )
        return stages

    new_stage = {
        "name": rule.stage_name,
        "stage_ref": rule.stage_ref or "",
    }

    result = list(stages)
    insert_idx = len(result)  # Default: append

    if rule.insert_after:
        for i, s in enumerate(result):
            if s.get("name") == rule.insert_after:
                insert_idx = i + 1
                break

    if rule.insert_before:
        for i, s in enumerate(result):
            if s.get("name") == rule.insert_before:
                insert_idx = i
                break

    result.insert(insert_idx, new_stage)
    return result


def _find_stage_index(
    stages: List[Dict[str, Any]], name: Optional[str],
) -> Optional[int]:
    """Find the index of a stage by name, or None."""
    if name is None:
        return None
    for i, s in enumerate(stages):
        if s.get("name") == name:
            return i
    return None


def _apply_reorder(
    stages: List[Dict[str, Any]], rule: AdaptationRule
) -> List[Dict[str, Any]]:
    """Move a stage to a new position."""
    stage_idx = _find_stage_index(stages, rule.stage_name)
    if stage_idx is None:
        logger.warning(
            "Reorder rule %s: stage %s not found",
            rule.name,
            rule.stage_name,
        )
        return stages

    stage = stages[stage_idx]
    result = [s for i, s in enumerate(stages) if i != stage_idx]

    insert_idx = _find_stage_index(result, rule.move_after)
    if insert_idx is not None:
        insert_idx += 1
    else:
        insert_idx = _find_stage_index(result, rule.move_before)
    if insert_idx is None:
        insert_idx = len(result)

    result.insert(insert_idx, stage)
    return result


def _apply_modify(
    stages: List[Dict[str, Any]], rule: AdaptationRule
) -> List[Dict[str, Any]]:
    """Merge modifications into a stage dict."""
    result = list(stages)
    for i, s in enumerate(result):
        if s.get("name") == rule.stage_name:
            result[i] = {**s, **rule.modifications}
            return result

    logger.warning(
        "Modify rule %s: stage %s not found",
        rule.name,
        rule.stage_name,
    )
    return result


def _get_applied_rule_names(
    rules: List[AdaptationRule],
    original_names: List[str],
    adapted_names: List[str],
) -> List[str]:
    """Determine which rules were actually applied."""
    if original_names == adapted_names:
        return []
    return [r.name for r in rules]


def _check_emergency_stop() -> bool:
    """Check if emergency stop is active. Returns True if safe to proceed."""
    try:
        from src.safety.autonomy.emergency_stop import (
            EmergencyStopController,
        )

        controller = EmergencyStopController()
        return not controller.is_active()
    except ImportError:
        return True  # No autonomy module = proceed
    except Exception:  # noqa: BLE001 -- safety check failure = proceed
        logger.warning(
            "Emergency stop check failed, proceeding", exc_info=True
        )
        return True
