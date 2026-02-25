"""Visualize API routes — generate DAG representations of a workflow config."""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from temper_ai.auth.api_key_auth import require_auth

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class VisualizeRequest(BaseModel):
    """POST /api/visualize request body."""

    workflow: str
    format: Literal["mermaid", "dot", "ascii", "json"] = "mermaid"


# ── Helpers ───────────────────────────────────────────────────────────


def _load_workflow_config(config_root: str, workflow_path: str) -> dict[str, Any]:
    """Load and validate a workflow YAML file with path traversal protection."""
    from pathlib import Path

    import yaml

    config_root_resolved = Path(config_root).resolve()
    workflow_file = (config_root_resolved / workflow_path).resolve()
    try:
        workflow_file.relative_to(config_root_resolved)
    except ValueError:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="Invalid workflow path"
        ) from None

    if not workflow_file.exists():
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Workflow not found: {workflow_path}",
        )

    try:
        with open(workflow_file, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except Exception as e:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse workflow config: {e}",
        ) from e


def _extract_stage_info(stages_raw: list) -> tuple[list[str], list[Any]]:
    """Extract stage names and refs from raw stage config entries."""
    stage_names: list[str] = []
    stage_refs: list[Any] = []
    for stage_entry in stages_raw:
        if isinstance(stage_entry, str):
            stage_names.append(stage_entry)
            stage_refs.append(stage_entry)
        elif isinstance(stage_entry, dict):
            name = stage_entry.get("name", "")
            if name:
                stage_names.append(name)
                stage_refs.append(stage_entry)
    return stage_names, stage_refs


def _render_dag_output(dag: Any, fmt: str) -> Any:
    """Render DAG to the requested output format."""
    from temper_ai.workflow.dag_visualizer import (
        export_dot,
        export_mermaid,
        render_console_dag,
    )

    if fmt == "mermaid":
        return export_mermaid(dag)
    if fmt == "dot":
        return export_dot(dag)
    if fmt == "ascii":
        return render_console_dag(dag)
    if fmt == "json":
        return {
            "topo_order": dag.topo_order,
            "roots": dag.roots,
            "terminals": dag.terminals,
            "predecessors": dag.predecessors,
            "successors": dag.successors,
        }
    raise HTTPException(
        status_code=HTTP_400_BAD_REQUEST, detail=f"Unsupported format: {fmt}"
    )


def _handle_visualize_workflow(
    body: VisualizeRequest, config_root: str
) -> dict[str, Any]:
    """Return a DAG representation of a workflow config."""
    from temper_ai.workflow.dag_builder import build_stage_dag, has_dag_dependencies

    config = _load_workflow_config(config_root, body.workflow)
    wf_block = config.get("workflow", {}) if config else {}
    stages_raw = wf_block.get("stages", [])
    if not stages_raw:
        return {
            "workflow": body.workflow,
            "format": body.format,
            "output": "",
            "stages": [],
            "message": "Workflow has no stages",
        }

    stage_names, stage_refs = _extract_stage_info(stages_raw)
    try:
        dag = build_stage_dag(stage_names, stage_refs)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("DAG construction failed for workflow %s", body.workflow)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build workflow DAG",
        ) from e

    output = _render_dag_output(dag, body.format)
    return {
        "workflow": body.workflow,
        "format": body.format,
        "output": output,
        "stages": stage_names,
        "has_dag_dependencies": has_dag_dependencies(stage_refs),
    }


# ── Router factory ────────────────────────────────────────────────────


def create_visualize_router(
    config_root: str = "configs",
    auth_enabled: bool = False,
) -> APIRouter:
    """Create the visualize API router."""
    router = APIRouter(prefix="/api/visualize", tags=["visualize"])
    read_deps = [Depends(require_auth)] if auth_enabled else []

    @router.post("", dependencies=read_deps)
    def visualize_workflow(body: VisualizeRequest = Body(...)) -> dict[str, Any]:
        """Generate a workflow visualization."""
        return _handle_visualize_workflow(body, config_root)

    return router
