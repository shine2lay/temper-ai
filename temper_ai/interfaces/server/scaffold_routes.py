"""Scaffold API routes — generate and download scaffolded project archives."""

import io
import logging
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_role

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATES_DIR = Path("configs/templates")


# ── Request / Response models ─────────────────────────────────────────


class ScaffoldRequest(BaseModel):
    """POST /api/projects/scaffold request body."""

    product_type: str
    project_name: str
    inference_overrides: dict[str, str] | None = None


# ── Router factory ────────────────────────────────────────────────────


def _generate_zip_archive(output_dir: Path, project_name: str) -> StreamingResponse:
    """Pack a directory into a ZIP archive and return as StreamingResponse."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(output_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(output_dir)
                zf.write(file_path, arcname)
    zip_buffer.seek(0)
    filename = f"{project_name}_scaffold.zip"
    return StreamingResponse(
        io.BytesIO(zip_buffer.read()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _handle_scaffold_project(
    body: ScaffoldRequest, templates_dir: Path
) -> StreamingResponse:
    """Generate a scaffolded project from a template and return as ZIP."""
    from temper_ai.workflow.templates.generator import TemplateGenerator
    from temper_ai.workflow.templates.registry import (
        TemplateNotFoundError,
        TemplateRegistry,
    )

    try:
        registry = TemplateRegistry(templates_dir)
        generator = TemplateGenerator(registry)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / body.project_name
            output_dir.mkdir(parents=True, exist_ok=True)
            generator.generate(
                product_type=body.product_type,
                project_name=body.project_name,
                output_dir=output_dir,
                inference_overrides=body.inference_overrides,
            )
            return _generate_zip_archive(output_dir, body.project_name)
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.exception(
            "Failed to scaffold project %s from template %s",
            body.project_name,
            body.product_type,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Project scaffolding failed",
        ) from e


def create_scaffold_router(
    templates_dir: Path = _DEFAULT_TEMPLATES_DIR,
    auth_enabled: bool = False,
) -> APIRouter:
    """Create the projects scaffold API router."""
    router = APIRouter(prefix="/api/projects", tags=["projects"])
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.post("/scaffold", dependencies=write_deps)
    def scaffold_project(body: ScaffoldRequest = Body(...)) -> StreamingResponse:
        """Generate a scaffolded project archive."""
        return _handle_scaffold_project(body, templates_dir)

    return router
