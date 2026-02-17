"""Template registry: discovers and validates product templates."""

import logging
from pathlib import Path
from typing import Dict, List

import yaml

from src.workflow.templates._schemas import TemplateManifest

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.yaml"
REQUIRED_SUBDIRS = ("stages", "agents")


class TemplateNotFoundError(Exception):
    """Raised when a requested product template does not exist."""


class TemplateRegistry:
    """Scans a templates directory and provides access to product templates."""

    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir
        self._cache: Dict[str, TemplateManifest] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_templates(self) -> List[TemplateManifest]:
        """Return manifests for every valid template found on disk."""
        results: List[TemplateManifest] = []
        if not self._templates_dir.is_dir():
            return results
        for child in sorted(self._templates_dir.iterdir()):
            manifest_path = child / MANIFEST_FILENAME
            if child.is_dir() and manifest_path.is_file():
                manifest = self._load_manifest(manifest_path)
                results.append(manifest)
        return results

    def get_manifest(self, product_type: str) -> TemplateManifest:
        """Return the manifest for *product_type*, raising on miss."""
        if product_type in self._cache:
            return self._cache[product_type]
        template_dir = self._resolve_dir(product_type)
        manifest_path = template_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise TemplateNotFoundError(
                f"No {MANIFEST_FILENAME} in template '{product_type}'"
            )
        manifest = self._load_manifest(manifest_path)
        self._cache[product_type] = manifest
        return manifest

    def get_template_dir(self, product_type: str) -> Path:
        """Return the filesystem path for a product template."""
        return self._resolve_dir(product_type)

    def validate_template(self, product_type: str) -> List[str]:
        """Check a template for structural problems. Returns error strings."""
        errors: List[str] = []
        template_dir = self._templates_dir / product_type
        if not template_dir.is_dir():
            errors.append(f"Template directory missing: {product_type}")
            return errors
        manifest_path = template_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            errors.append(f"Missing {MANIFEST_FILENAME}")
        if not (template_dir / "workflow.yaml").is_file():
            errors.append("Missing workflow.yaml")
        for subdir in REQUIRED_SUBDIRS:
            if not (template_dir / subdir).is_dir():
                errors.append(f"Missing required subdirectory: {subdir}")
        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_dir(self, product_type: str) -> Path:
        """Resolve and verify a template directory exists."""
        template_dir = self._templates_dir / product_type
        if not template_dir.is_dir():
            raise TemplateNotFoundError(
                f"Template not found: '{product_type}'"
            )
        return template_dir

    def _load_manifest(self, path: Path) -> TemplateManifest:
        """Parse a manifest YAML file into a TemplateManifest."""
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        return TemplateManifest(**raw)
