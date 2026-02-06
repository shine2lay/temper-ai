"""
Prompt template rendering engine using Jinja2.

Provides flexible prompt templating with variable substitution, conditional blocks,
and tool schema formatting for LLM function calling.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from jinja2 import FileSystemLoader, Template, TemplateNotFound
from jinja2.sandbox import ImmutableSandboxedEnvironment


class PromptRenderError(Exception):
    """Raised when prompt rendering fails."""
    pass


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

    # Allowed types for template variables (defense against SSTI via dangerous objects)
    ALLOWED_TYPES = (str, int, float, bool, list, dict, tuple, type(None))
    # Maximum size per variable in bytes (100KB)
    MAX_VAR_SIZE = 100 * 1024

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

        # Template compilation cache (LRU)
        self._template_cache: Dict[str, Template] = {}
        self._cache_size = cache_size
        self._cache_hits = 0
        self._cache_misses = 0

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
        self._validate_variables(variables)

        try:
            # Check cache for compiled template
            jinja_template = self._template_cache.get(template)

            if jinja_template is None:
                # Cache miss - compile template
                self._cache_misses += 1
                jinja_template = self._sandbox_env.from_string(template)

                # Add to cache (LRU eviction if full)
                if len(self._template_cache) >= self._cache_size:
                    # Remove oldest entry (simple FIFO since dicts are ordered in Python 3.7+)
                    oldest_key = next(iter(self._template_cache))
                    del self._template_cache[oldest_key]

                self._template_cache[template] = jinja_template
            else:
                # Cache hit
                self._cache_hits += 1

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
        self._validate_variables(variables)

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
            variables["tools_available"] = self._format_tool_schemas(
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
            variables["tools_available"] = self._format_tool_schemas(tool_schemas)
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
        if not schemas:
            return "No tools available"

        if format_style == "json":
            # Pretty JSON format
            return json.dumps(schemas, indent=2)

        elif format_style == "list":
            # Simple list format: "- name: description"
            lines = []
            for schema in schemas:
                name = schema.get("name", "Unknown")
                desc = schema.get("description", "No description")
                lines.append(f"- {name}: {desc}")
            return "\n".join(lines)

        elif format_style == "markdown":
            # Markdown table format
            lines = ["| Tool | Description |", "|------|-------------|"]
            for schema in schemas:
                name = schema.get("name", "Unknown")
                desc = schema.get("description", "No description")
                lines.append(f"| {name} | {desc} |")
            return "\n".join(lines)

        else:
            raise ValueError(f"Unknown format_style: {format_style}")

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
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0

        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_requests": total_requests,
            "cache_hit_rate": hit_rate,
            "cache_size": len(self._template_cache),
            "cache_capacity": self._cache_size
        }

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
        self._template_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def _validate_variables(self, variables: Dict[str, Any]) -> None:
        """
        Validate template variables for type safety and size limits.

        Prevents SSTI by ensuring only safe primitive types are passed to
        the template engine. Blocks functions, classes, modules, and other
        objects that could be used to access Python internals.

        Args:
            variables: Variables to validate

        Raises:
            PromptRenderError: If any variable has a disallowed type or exceeds size limit
        """
        for key, value in variables.items():
            self._validate_value(key, value)

    def _validate_value(self, key: str, value: Any, depth: int = 0) -> None:
        """Recursively validate a single value."""
        if depth > 20:
            raise PromptRenderError(
                f"Variable '{key}' has excessive nesting depth (>20)"
            )

        if not isinstance(value, self.ALLOWED_TYPES):
            raise PromptRenderError(
                f"Variable '{key}' has disallowed type: {type(value).__name__}. "
                f"Allowed: str, int, float, bool, list, dict, tuple, None"
            )

        # Check size for string values
        if isinstance(value, str):
            size = len(value.encode('utf-8', errors='replace'))
            if size > self.MAX_VAR_SIZE:
                raise PromptRenderError(
                    f"Variable '{key}' exceeds size limit: {size} > {self.MAX_VAR_SIZE}"
                )

        # Recursively validate nested structures
        if isinstance(value, dict):
            for k, v in value.items():
                self._validate_value(f"{key}.{k}", v, depth + 1)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                self._validate_value(f"{key}[{i}]", item, depth + 1)

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
                all_vars["tools_available"] = self._format_tool_schemas(tool_schemas)
                all_vars["tools"] = tool_schemas

            return self.render_file(template_path, all_vars)

        else:
            raise PromptRenderError(
                "Agent config must have 'prompt.inline' or 'prompt.template'"
            )
