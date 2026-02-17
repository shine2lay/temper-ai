"""Multi-product template system for workflow generation."""

from src.workflow.templates._schemas import TemplateManifest  # noqa: F401
from src.workflow.templates.generator import TemplateGenerator  # noqa: F401
from src.workflow.templates.registry import (  # noqa: F401
    TemplateNotFoundError,
    TemplateRegistry,
)
