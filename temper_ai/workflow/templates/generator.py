"""Template generator: stamps out project-specific configs from templates."""

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from temper_ai.workflow.templates._schemas import TemplateQualityGates
from temper_ai.workflow.templates.registry import TemplateRegistry

logger = logging.getLogger(__name__)

PROJECT_NAME_PLACEHOLDER = "{{project_name}}"


class TemplateGenerator:
    """Generates project-specific workflow configs from a product template."""

    def __init__(self, registry: TemplateRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        product_type: str,
        project_name: str,
        output_dir: Path,
        inference_overrides: Optional[Dict[str, str]] = None,
    ) -> Path:
        """Generate a full project config set from a template.

        Returns the path to the generated workflow YAML file.
        """
        manifest = self._registry.get_manifest(product_type)
        template_dir = self._registry.get_template_dir(product_type)

        workflow_dir = output_dir / "workflows"
        stages_dir = output_dir / "stages"
        agents_dir = output_dir / "agents"
        for d in (workflow_dir, stages_dir, agents_dir):
            d.mkdir(parents=True, exist_ok=True)

        workflow_path = self._copy_and_stamp_workflow(
            template_dir / "workflow.yaml",
            workflow_dir / f"{project_name}_workflow.yaml",
            project_name,
        )
        self._copy_and_stamp_stages(
            template_dir, stages_dir, project_name,
            manifest.quality_gates,
        )
        self._copy_and_stamp_agents(
            template_dir, agents_dir, project_name, inference_overrides,
        )
        logger.info(
            "Generated %s project '%s' at %s",
            product_type, project_name, output_dir,
        )
        return workflow_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _copy_and_stamp_workflow(
        self, src: Path, dst: Path, project_name: str,
    ) -> Path:
        """Read a template workflow, stamp project name, write output."""
        data = self._read_yaml(src)
        stamped = _replace_placeholder(data, project_name)
        self._write_yaml(dst, stamped)
        return dst

    def _copy_and_stamp_stages(
        self,
        template_dir: Path,
        output_dir: Path,
        project_name: str,
        quality_gates: TemplateQualityGates,
    ) -> List[str]:
        """Copy and stamp all stage configs from the template."""
        stages_dir = template_dir / "stages"
        written: List[str] = []
        if not stages_dir.is_dir():
            return written
        for src in sorted(stages_dir.glob("*.yaml")):
            data = self._read_yaml(src)
            stamped = _replace_placeholder(data, project_name)
            stamped = self._apply_quality_gates(stamped, quality_gates)
            self._write_yaml(output_dir / src.name, stamped)
            written.append(src.name)
        return written

    def _copy_and_stamp_agents(
        self,
        template_dir: Path,
        output_dir: Path,
        project_name: str,
        inference_overrides: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Copy and stamp all agent configs from the template."""
        agents_dir = template_dir / "agents"
        written: List[str] = []
        if not agents_dir.is_dir():
            return written
        for src in sorted(agents_dir.glob("*.yaml")):
            data = self._read_yaml(src)
            stamped = _replace_placeholder(data, project_name)
            if inference_overrides:
                stamped = _apply_inference_overrides(
                    stamped, inference_overrides,
                )
            self._write_yaml(output_dir / src.name, stamped)
            written.append(src.name)
        return written

    def _apply_quality_gates(
        self, stage_data: Any, quality_gates: TemplateQualityGates,
    ) -> Any:
        """Merge quality gate settings into a stage config dict."""
        if not isinstance(stage_data, dict):
            return stage_data
        inner = stage_data.get("stage", stage_data)
        inner["quality_gates"] = quality_gates.model_dump()
        return stage_data

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_yaml(path: Path) -> Any:
        """Read a YAML file and return its parsed content."""
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    @staticmethod
    def _write_yaml(path: Path, data: Any) -> None:
        """Write data to a YAML file."""
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False)


# ------------------------------------------------------------------
# Module-level helpers (kept short, no class state needed)
# ------------------------------------------------------------------


def _replace_placeholder(obj: Any, project_name: str) -> Any:
    """Recursively replace {{project_name}} in all string values."""
    if isinstance(obj, str):
        return obj.replace(PROJECT_NAME_PLACEHOLDER, project_name)
    if isinstance(obj, dict):
        return {
            k: _replace_placeholder(v, project_name) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_replace_placeholder(item, project_name) for item in obj]
    return obj


def _apply_inference_overrides(
    agent_data: Any, overrides: Dict[str, str],
) -> Any:
    """Apply inference setting overrides to an agent config dict."""
    if not isinstance(agent_data, dict):
        return agent_data
    data = copy.deepcopy(agent_data)
    agent_inner = data.get("agent", data)
    inference = agent_inner.get("inference", {})
    for key in ("provider", "model", "base_url"):
        if key in overrides:
            inference[key] = overrides[key]
    if inference:
        agent_inner["inference"] = inference
    return data
