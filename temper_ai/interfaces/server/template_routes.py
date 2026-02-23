"""Template API routes — list and retrieve workflow product templates."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATES_DIR = Path("configs/templates")


# ── Request / Response models ─────────────────────────────────────────


class GenerateWorkflowRequest(BaseModel):
    """POST /api/templates/generate request body."""

    product_type: str
    project_name: str
    output_dir: str
    inference_overrides: dict[str, str] | None = None


# ── Router factory ────────────────────────────────────────────────────


def _handle_list_templates(templates_dir: Path) -> dict[str, Any]:
    """List all available product templates."""
    from temper_ai.workflow.templates.registry import TemplateRegistry

    try:
        registry = TemplateRegistry(templates_dir)
        manifests = registry.list_templates()
        result = [m.model_dump() for m in manifests]
        return {"templates": result, "total": len(result)}
    except Exception as e:
        logger.exception("Failed to list templates")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list templates",
        ) from e


def _handle_get_template(name: str, templates_dir: Path) -> dict[str, Any]:
    """Get details for a specific template by product type name."""
    from temper_ai.workflow.templates.registry import (
        TemplateNotFoundError,
        TemplateRegistry,
    )

    try:
        registry = TemplateRegistry(templates_dir)
        manifest = registry.get_manifest(name)
        errors = registry.validate_template(name)
        return {
            "manifest": manifest.model_dump(),
            "validation_errors": errors,
            "valid": len(errors) == 0,
        }
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to retrieve template %s", name)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template",
        ) from e


def _handle_generate_workflow(
    body: GenerateWorkflowRequest, templates_dir: Path
) -> dict[str, Any]:
    """Generate a project config set from a product template."""
    from temper_ai.workflow.templates.generator import TemplateGenerator
    from temper_ai.workflow.templates.registry import (
        TemplateNotFoundError,
        TemplateRegistry,
    )

    try:
        registry = TemplateRegistry(templates_dir)
        generator = TemplateGenerator(registry)
        output_path = generator.generate(
            product_type=body.product_type,
            project_name=body.project_name,
            output_dir=Path(body.output_dir),
            inference_overrides=body.inference_overrides,
        )
        return {
            "product_type": body.product_type,
            "project_name": body.project_name,
            "output_dir": body.output_dir,
            "workflow_file": str(output_path),
        }
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.exception(
            "Failed to generate workflow from template %s", body.product_type
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template generation failed",
        ) from e


def create_template_router(
    templates_dir: Path = _DEFAULT_TEMPLATES_DIR,
    auth_enabled: bool = False,
) -> APIRouter:
    """Create the templates API router."""
    router = APIRouter(prefix="/api/templates", tags=["templates"])
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.get("", dependencies=read_deps)
    def list_templates() -> dict[str, Any]:
        """List all available product templates."""
        return _handle_list_templates(templates_dir)

    @router.get("/{name}", dependencies=read_deps)
    def get_template(name: str) -> dict[str, Any]:
        """Get details for a specific template."""
        return _handle_get_template(name, templates_dir)

    @router.post("/generate", dependencies=write_deps)
    def generate_workflow(body: GenerateWorkflowRequest = Body(...)) -> dict[str, Any]:
        """Generate a workflow from a template."""
        return _handle_generate_workflow(body, templates_dir)

    return router
