"""Prompt template rendering engine using Jinja2.

Provides sandboxed template rendering with variable substitution,
conditional blocks, and template compilation caching.
"""
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from jinja2 import FileSystemLoader, TemplateNotFound
from jinja2.sandbox import ImmutableSandboxedEnvironment

from src.llm.prompts.cache import TemplateCacheManager
from src.llm.prompts.validation import (
    PromptRenderError,
    TemplateVariableValidator,
)
from src.llm.cache.constants import DEFAULT_CACHE_SIZE

# Hash length for prompt template versioning — matches error_fingerprinting.py
_TEMPLATE_HASH_LENGTH = 16  # noqa — scanner: skip-magic


def _compute_template_hash(template_text: str) -> str:
    """Compute SHA-256 first-16-hex-chars hash of raw template text (pre-rendering).

    The hash is computed on the raw template before variable substitution,
    so the same template always produces the same hash regardless of variables.
    """
    return hashlib.sha256(template_text.encode("utf-8")).hexdigest()[:_TEMPLATE_HASH_LENGTH]


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

    def __init__(self, templates_dir: Optional[Union[str, Path]] = None, cache_size: int = DEFAULT_CACHE_SIZE):
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
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Set up Jinja2 immutable sandboxed environment if templates_dir exists
        # ImmutableSandboxedEnvironment prevents template injection attacks
        self.jinja_env: Optional[ImmutableSandboxedEnvironment]
        if self.templates_dir and self.templates_dir.exists():
            self.jinja_env = ImmutableSandboxedEnvironment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=False,  # Prompts are not HTML
                trim_blocks=True,  # Remove first newline after block
                lstrip_blocks=True,  # Strip leading spaces before blocks
            )
        else:
            self.jinja_env = None

    def render(self, template: str, variables: Optional[Dict[str, Any]] = None) -> str:
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
        self,
        template_path: str,
        variables: Optional[Dict[str, Any]] = None
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
            )
        except Exception as e:
            raise PromptRenderError(
                f"Failed to render template file {template_path}: {e}"
            ) from e

    def render_with_metadata(
        self,
        template: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str, str]:
        """Render a template string and return metadata for prompt versioning.

        Args:
            template: Template string with {{variable}} placeholders
            variables: Variables to substitute in template

        Returns:
            Tuple of (rendered_text, template_hash, source) where source is "inline"

        Raises:
            PromptRenderError: If rendering fails
        """
        rendered = self.render(template, variables)
        template_hash = _compute_template_hash(template)
        return rendered, template_hash, "inline"

    def render_file_with_metadata(
        self,
        template_path: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str, str]:
        """Render a template from a file and return metadata for prompt versioning.

        Args:
            template_path: Relative path to template file
            variables: Variables to substitute in template

        Returns:
            Tuple of (rendered_text, template_hash, template_path)

        Raises:
            PromptRenderError: If template not found or rendering fails
        """
        # Read raw template source for hashing (before variable substitution)
        if not self.jinja_env:
            raise PromptRenderError(
                "Cannot load template file: templates directory not configured"
            )
        try:
            raw_source, _, _ = self.jinja_env.loader.get_source(  # type: ignore[union-attr]
                self.jinja_env, template_path,
            )
        except TemplateNotFound:
            raise PromptRenderError(
                f"Template file not found: {template_path} in {self.templates_dir}"
            )

        rendered = self.render_file(template_path, variables)
        template_hash = _compute_template_hash(raw_source)
        return rendered, template_hash, template_path

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get template cache statistics.

        Returns:
            Dictionary with cache statistics including hits, misses, size, and hit rate.

        Examples:
            >>> engine = PromptEngine()
            >>> engine.render("Hello {{name}}!", {"name": "Alice"})
            >>> engine.render("Hello {{name}}!", {"name": "Bob"})
            >>> stats = engine.get_cache_stats()
            >>> stats["cache_hits"]
            1
            >>> stats["cache_hit_rate"]
            0.5
        """
        return self.cache.get_cache_stats()

    def clear_cache(self) -> None:
        """
        Clear the template cache.

        Useful for testing or when template content needs to be invalidated.

        Examples:
            >>> engine = PromptEngine()
            >>> engine.render("Hello {{name}}!", {"name": "Alice"})
            >>> engine.clear_cache()
            >>> stats = engine.get_cache_stats()
            >>> stats["cache_size"]
            0
        """
        self.cache.clear_cache()
