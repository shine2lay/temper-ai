"""Prompt template rendering engine using Jinja2.

Provides sandboxed template rendering with variable substitution,
conditional blocks, and template compilation caching.
"""

from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader, TemplateNotFound
from jinja2.sandbox import ImmutableSandboxedEnvironment

from temper_ai.llm.constants import DEFAULT_CACHE_SIZE
from temper_ai.llm.prompts.cache import TemplateCacheManager
from temper_ai.llm.prompts.validation import (
    PromptRenderError,
    TemplateVariableValidator,
)


class PromptEngine:
    """Renders prompts from Jinja2 templates with sandboxed variable substitution.

    Features:
    - Jinja2 template rendering with {{variable}} syntax
    - Load templates from files or inline strings
    - Conditional blocks and loops
    - Template compilation caching (LRU)
    - SSTI prevention via ImmutableSandboxedEnvironment
    - Variable type/size validation

    Examples:
        >>> engine = PromptEngine()
        >>> engine.render("Hello {{name}}!", {"name": "World"})
        'Hello World!'
    """

    def __init__(
        self,
        templates_dir: str | Path | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ):
        """
        Initialize prompt engine.

        Args:
            templates_dir: Directory for template files (defaults to configs/prompts)
            cache_size: Maximum number of compiled templates to cache (default from cache constants)
        """
        if templates_dir is None:
            # Default to configs/prompts in project root
            templates_dir = Path.cwd() / "configs" / "prompts"
            if not templates_dir.exists():
                # Try to find project root
                current = Path.cwd()
                while current != current.parent:
                    potential_dir = current / "configs" / "prompts"
                    if potential_dir.exists():
                        templates_dir = potential_dir
                        break
                    current = current.parent

        self.templates_dir = Path(templates_dir) if templates_dir else None

        # Validation
        self.validator = TemplateVariableValidator()

        # Template compilation cache (LRU)
        self.cache = TemplateCacheManager(cache_size)

        # Shared immutable sandboxed environment for inline templates
        # ImmutableSandboxedEnvironment prevents attribute modification on objects
        self._sandbox_env = ImmutableSandboxedEnvironment(
            autoescape=False, trim_blocks=True, lstrip_blocks=True
        )

        # Set up Jinja2 immutable sandboxed environment if templates_dir exists
        # ImmutableSandboxedEnvironment prevents template injection attacks
        self.jinja_env: ImmutableSandboxedEnvironment | None
        if self.templates_dir and self.templates_dir.exists():
            self.jinja_env = ImmutableSandboxedEnvironment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=False,  # Prompts are not HTML
                trim_blocks=True,  # Remove first newline after block
                lstrip_blocks=True,  # Strip leading spaces before blocks
            )
        else:
            self.jinja_env = None

    def render(self, template: str, variables: dict[str, Any] | None = None) -> str:
        """
        Render a template string with variables.

        Templates are compiled once and cached for performance. Subsequent renders
        of the same template reuse the compiled version (~10x faster).

        Args:
            template: Template string with {{variable}} placeholders
            variables: Variables to substitute in template

        Returns:
            Rendered template string

        Raises:
            PromptRenderError: If rendering fails

        Examples:
            >>> engine = PromptEngine()
            >>> engine.render("Hello {{name}}!", {"name": "World"})
            'Hello World!'

            >>> engine.render("{% if premium %}Premium{% else %}Free{% endif %}",
            ...               {"premium": True})
            'Premium'
        """
        if variables is None:
            variables = {}

        # Validate variable types and sizes before rendering
        self.validator.validate_variables(variables)

        try:
            # Get or compile template
            jinja_template = self.cache.get_or_compile(template, self._sandbox_env)
            return jinja_template.render(**variables)
        except PromptRenderError:
            raise
        except Exception as e:
            raise PromptRenderError(f"Failed to render template: {e}") from e

    def render_file(
        self, template_path: str, variables: dict[str, Any] | None = None
    ) -> str:
        """
        Render a template from a file.

        Args:
            template_path: Relative path to template file (e.g., "researcher_base.txt")
            variables: Variables to substitute in template

        Returns:
            Rendered template string

        Raises:
            PromptRenderError: If template not found or rendering fails

        Examples:
            >>> engine = PromptEngine()
            >>> engine.render_file("agent_base.txt", {"domain": "SaaS"})
            'You are an expert in SaaS...'
        """
        if variables is None:
            variables = {}

        # Validate variable types and sizes before rendering
        self.validator.validate_variables(variables)

        if not self.jinja_env:
            raise PromptRenderError(
                "Cannot load template file: templates directory not configured"
            )

        try:
            template = self.jinja_env.get_template(template_path)
            return template.render(**variables)
        except TemplateNotFound:
            raise PromptRenderError(
                f"Template file not found: {template_path} in {self.templates_dir}"
            ) from None
        except Exception as e:
            raise PromptRenderError(
                f"Failed to render template file {template_path}: {e}"
            ) from e

    def clear_cache(self) -> None:
        """
        Clear the template cache.

        Useful for testing or when template content needs to be invalidated.

        Examples:
            >>> engine = PromptEngine()
            >>> engine.render("Hello {{name}}!", {"name": "Alice"})
            >>> engine.clear_cache()
            >>> stats = engine.cache.get_cache_stats()
            >>> stats["cache_size"]
            0
        """
        self.cache.clear_cache()
