"""Auto-tune engine — applies approved recommendations to config files."""

import logging
from pathlib import Path
from typing import Any, Dict, List

import yaml

from temper_ai.learning.models import STATUS_APPLIED
from temper_ai.learning.store import LearningStore

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_ROOT = "configs"


class AutoTuneEngine:
    """Applies approved recommendations to workflow/agent YAML configs."""

    def __init__(
        self,
        store: LearningStore,
        config_root: str = DEFAULT_CONFIG_ROOT,
    ) -> None:
        self.store = store
        self.config_root = Path(config_root)

    def preview_changes(self, rec_ids: List[str]) -> List[Dict[str, Any]]:
        """Show what would change without modifying files."""
        return [
            self._build_change_info(rec_id, dry_run=True)
            for rec_id in rec_ids
        ]

    def apply_recommendations(self, rec_ids: List[str]) -> List[Dict[str, Any]]:
        """Apply approved recommendations to YAML config files."""
        return [
            self._build_change_info(rec_id, dry_run=False)
            for rec_id in rec_ids
        ]

    def _build_change_info(self, rec_id: str, dry_run: bool) -> Dict[str, Any]:
        """Build change info dict; optionally apply the change."""
        recs = self.store.list_recommendations(status="pending")
        rec = next((r for r in recs if r.id == rec_id), None)
        if rec is None:
            return {"id": rec_id, "status": "not_found"}

        config_path = self.config_root / rec.config_path
        if not config_path.exists():
            return {"id": rec_id, "status": "config_not_found", "path": str(config_path)}

        info: Dict[str, Any] = {
            "id": rec_id,
            "config_path": str(config_path),
            "field_path": rec.field_path,
            "current_value": rec.current_value,
            "recommended_value": rec.recommended_value,
            "rationale": rec.rationale,
        }

        if dry_run:
            info["status"] = "preview"
            return info

        if _apply_yaml_change(config_path, rec.field_path, rec.recommended_value):
            self.store.update_recommendation_status(rec_id, STATUS_APPLIED)
            info["status"] = "applied"
        else:
            info["status"] = "apply_failed"

        return info


def _apply_yaml_change(path: Path, field_path: str, new_value: str) -> bool:
    """Read YAML, set field at dotted path, write back."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        keys = field_path.split(".")
        target = data
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                return False
            target = target[key]

        target[keys[-1]] = new_value

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

        logger.info("Applied config change: %s -> %s in %s", field_path, new_value, path)
        return True
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Failed to apply change to %s: %s", path, exc)
        return False
