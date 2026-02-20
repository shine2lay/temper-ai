"""Helper functions for the MCP server."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import yaml

logger = logging.getLogger(__name__)

YAML_EXTENSIONS = (".yaml", ".yml")


def scan_workflow_configs(config_root: str) -> List[Dict]:
    """Scan config_root/workflows/ for workflow YAML files.

    Returns list of dicts with keys: name, description, path, stages (count).
    """
    results: List[Dict[str, Any]] = []
    workflows_dir = Path(config_root) / "workflows"
    if not workflows_dir.exists():
        return results
    for path in sorted(workflows_dir.iterdir()):
        if path.suffix not in YAML_EXTENSIONS:
            continue
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
            if not config:
                continue
            wf = config.get("workflow", {})
            results.append({
                "name": wf.get("name", path.stem),
                "description": wf.get("description", ""),
                "path": str(path),
                "stages": len(wf.get("stages", [])),
            })
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Failed to scan %s: %s", path, exc)
    return results


def scan_agent_configs(config_root: str) -> List[Dict]:
    """Scan config_root/agents/ for agent YAML files.

    Returns list of dicts with keys: name, description, type, path.
    """
    results: List[Dict[str, Any]] = []
    agents_dir = Path(config_root) / "agents"
    if not agents_dir.exists():
        return results
    for path in sorted(agents_dir.iterdir()):
        if path.suffix not in YAML_EXTENSIONS:
            continue
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
            if not config:
                continue
            agent = config.get("agent", {})
            results.append({
                "name": agent.get("name", path.stem),
                "description": agent.get("description", ""),
                "type": agent.get("type", "standard"),
                "path": str(path),
            })
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Failed to scan %s: %s", path, exc)
    return results


def format_run_result(result: object) -> str:
    """Format a workflow run result as a human-readable string."""
    if isinstance(result, dict):
        return json.dumps(result, indent=2, default=str)
    return str(result)
