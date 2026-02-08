"""
Prompt template rendering engine using Jinja2.

Provides flexible prompt templating with variable substitution, conditional blocks,
and tool schema formatting for LLM function calling.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from jinja2 import FileSystemLoader, TemplateNotFound
from jinja2.sandbox import ImmutableSandboxedEnvironment

from src.agents.prompt_validation import (
    PromptRenderError,
    TemplateVariableValidator,
    _is_safe_template_value
)
from src.agents.prompt_cache import TemplateCacheManager
from src.agents.prompt_formatters import ToolSchemaFormatter


class PromptEngine:
    """
    Renders prompts from templates with variable substitution.

    Features:
    - Jinja2 template rendering with {{variable}} syntax
    - Load templates from files or inline strings
    - System variable injection (agent_name, tools, etc.)
    - Tool schema formatting for LLM function calling
    - Conditional blocks and loops
    - Safe rendering with error handling

    Examples:
        >>> engine = PromptEngine()
        >>> engine.render("Hello {{name}}!", {"name": "World"})
        'Hello World!'

        >>> engine.render_with_tools(
        ...     "You have {{tools|length}} tools",
        ...     {},
        ...     [{"name": "calc", "description": "Calculator"}]
        ... )
        'You have 1 tools'
    """

    # Backward-compatible class constants (delegate to validator)
    ALLOWED_TYPES = TemplateVariableValidator.ALLOWED_TYPES
    MAX_VAR_SIZE = TemplateVariableValidator.MAX_VAR_SIZE

    def __init__(self, templates_dir: Optional[Union[str, Path]] = None, cache_size: int = 128):
        """
        Initialize prompt engine.

        Args:
            templates_dir: Directory for template files (defaults to configs/prompts)
            cache_size: Maximum number of compiled templates to cache (default: 128)
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

        # Tool schema formatting
        self.formatter = ToolSchemaFormatter()

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

    def render_with_tools(
        self,
        template: str,
        variables: Optional[Dict[str, Any]] = None,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        format_style: str = "json"
    ) -> str:
        """
        Render template with tool schemas injected.

        Args:
            template: Template string
            variables: Variables to substitute
            tool_schemas: List of tool schema dictionaries
            format_style: How to format tools ("json", "list", "markdown")

        Returns:
            Rendered template with tools injected

        Raises:
            PromptRenderError: If rendering fails

        Examples:
            >>> engine = PromptEngine()
            >>> tools = [{"name": "calc", "description": "Calculator"}]
            >>> engine.render_with_tools(
            ...     "Tools: {{tools_available}}",
            ...     {},
            ...     tools,
            ...     format_style="list"
            ... )
            'Tools: - calc: Calculator'
        """
        if variables is None:
            variables = {}

        if tool_schemas:
            # Inject formatted tools into variables
            variables["tools_available"] = self.formatter.format_tool_schemas(
                tool_schemas,
                format_style
            )
            variables["tools"] = tool_schemas  # Also provide raw schemas
        else:
            variables["tools_available"] = "No tools available"
            variables["tools"] = []

        return self.render(template, variables)

    def render_with_system_vars(
        self,
        template: str,
        variables: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        **system_vars: Any
    ) -> str:
        """
        Render template with system variables injected.

        Automatically injects:
        - agent_name: Name of the agent
        - tools_available: Formatted tool list
        - tools: Raw tool schemas
        - Any additional system_vars passed as kwargs

        Args:
            template: Template string
            variables: User-provided variables
            agent_name: Name of the agent
            tool_schemas: Available tool schemas
            **system_vars: Additional system variables

        Returns:
            Rendered template string

        Examples:
            >>> engine = PromptEngine()
            >>> engine.render_with_system_vars(
            ...     "Agent {{agent_name}} has {{tools|length}} tools",
            ...     {},
            ...     agent_name="researcher",
            ...     tool_schemas=[{"name": "calc"}]
            ... )
            'Agent researcher has 1 tools'
        """
        if variables is None:
            variables = {}

        # Inject system variables
        if agent_name:
            variables["agent_name"] = agent_name

        if tool_schemas:
            variables["tools_available"] = self.formatter.format_tool_schemas(tool_schemas)
            variables["tools"] = tool_schemas
        else:
            variables["tools_available"] = "No tools available"
            variables["tools"] = []

        # Inject any additional system vars
        variables.update(system_vars)

        return self.render(template, variables)

    def _format_tool_schemas(
        self,
        schemas: List[Dict[str, Any]],
        format_style: str = "json"
    ) -> str:
        """
        Format tool schemas for inclusion in prompts.

        Backward-compatible wrapper around formatter.format_tool_schemas().

        Args:
            schemas: List of tool schema dictionaries
            format_style: How to format ("json", "list", "markdown")

        Returns:
            Formatted tool schemas string

        Examples:
            >>> engine = PromptEngine()
            >>> tools = [{"name": "calc", "description": "Calculator"}]
            >>> engine._format_tool_schemas(tools, "list")
            '- calc: Calculator'
        """
        return self.formatter.format_tool_schemas(schemas, format_style)

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

    def render_agent_prompt(
        self,
        agent_config: Dict[str, Any],
        variables: Optional[Dict[str, Any]] = None,
        tool_schemas: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Render agent prompt from config.

        Handles both inline prompts and template file references.

        Args:
            agent_config: Agent configuration dict (should have 'prompt' key)
            variables: Variables for template substitution
            tool_schemas: Available tool schemas

        Returns:
            Rendered prompt string

        Raises:
            PromptRenderError: If prompt config is invalid or rendering fails

        Examples:
            >>> engine = PromptEngine()
            >>> config = {
            ...     "agent": {
            ...         "name": "researcher",
            ...         "prompt": {"inline": "Hello {{name}}!"}
            ...     }
            ... }
            >>> engine.render_agent_prompt(config, {"name": "World"})
            'Hello World!'
        """
        if variables is None:
            variables = {}

        # Extract agent config
        agent_inner = agent_config.get("agent", agent_config)
        prompt_config = agent_inner.get("prompt", {})
        agent_name = agent_inner.get("name", "agent")

        # Check for inline prompt
        if "inline" in prompt_config:
            template = prompt_config["inline"]
            return self.render_with_system_vars(
                template,
                variables,
                agent_name=agent_name,
                tool_schemas=tool_schemas
            )

        # Check for template file
        elif "template" in prompt_config:
            template_path = prompt_config["template"]
            template_vars = prompt_config.get("variables", {})

            # Merge template vars with provided vars
            all_vars = {**template_vars, **variables}

            # Add system variables
            if agent_name:
                all_vars["agent_name"] = agent_name
            if tool_schemas:
                all_vars["tools_available"] = self.formatter.format_tool_schemas(tool_schemas)
                all_vars["tools"] = tool_schemas

            return self.render_file(template_path, all_vars)

        else:
            raise PromptRenderError(
                "Agent config must have 'prompt.inline' or 'prompt.template'"
            )
