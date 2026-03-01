"""Helper functions extracted from ToolRegistry to reduce class size.

These are internal implementation details and should not be imported directly.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import TYPE_CHECKING, Any

from temper_ai.shared.utils.exceptions import ToolRegistryError
from temper_ai.tools.base import BaseTool

if TYPE_CHECKING:
    from temper_ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Constants
REPORT_SEPARATOR_LENGTH = 40  # Length of separator line in registration reports

# Common error suggestions for developers
COMMON_ERROR_SUGGESTIONS = {
    "requires init arguments": (
        "Solution: Provide default values in __init__ or register manually:\n"
        "  registry.register(MyTool(arg1='default'))"
    ),
    "Missing required method": (
        "Solution: Implement all required methods from BaseTool:\n"
        "  - execute(self, **kwargs) -> ToolResult\n"
        "  - get_metadata(self) -> ToolMetadata"
    ),
    "not inherit from BaseTool": (
        "Solution: Ensure your tool class inherits from BaseTool:\n"
        "  from temper_ai.tools.base import BaseTool\n"
        "  class MyTool(BaseTool):\n"
        "      ..."
    ),
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_tool_interface(tool_class: type[Any]) -> tuple[bool, list[str]]:
    """Validate that a tool class implements the required interface."""
    errors = []

    try:
        if not issubclass(tool_class, BaseTool):
            errors.append(f"Tool must inherit from BaseTool, got {tool_class.__name__}")
    except TypeError:
        errors.append(f"Invalid tool class: {tool_class}")
        return False, errors

    if inspect.isabstract(tool_class):
        errors.append("Tool class has unimplemented abstract methods")

    required_methods = ["execute", "get_metadata"]
    for method_name in required_methods:
        if not hasattr(tool_class, method_name):
            errors.append(f"Missing required method: {method_name}")
        else:
            attr = getattr(tool_class, method_name)
            if not callable(attr):
                errors.append(f"'{method_name}' is not callable")
            elif getattr(attr, "__isabstractmethod__", False):
                errors.append(f"'{method_name}' is still abstract (not implemented)")

    return len(errors) == 0, errors


def get_error_suggestion(error_msg: str) -> str | None:
    """Get helpful suggestion for common errors."""
    error_lower = error_msg.lower()
    for pattern, suggestion in COMMON_ERROR_SUGGESTIONS.items():
        if pattern.lower() in error_lower:
            return suggestion
    return None


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _parse_implementation_path(implementation: Any, config_name: str) -> str:
    """Parse implementation spec to class path. Raises ToolRegistryError on error."""
    if isinstance(implementation, str):
        return implementation

    if isinstance(implementation, dict):
        module_path = implementation.get("module")
        class_name = implementation.get("class")

        if not module_path or not class_name:
            raise ToolRegistryError(
                f"Tool implementation must specify 'module' and 'class': {config_name}"
            )

        return f"{module_path}.{class_name}"

    raise ToolRegistryError(
        f"Invalid implementation format in tool config: {config_name}"
    )


def _load_tool_class(class_path: str) -> type[BaseTool]:
    """Load and validate tool class. Raises ToolRegistryError on error."""
    parts = class_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ToolRegistryError(f"Invalid class path format: {class_path}")

    module_name, class_name = parts

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ToolRegistryError(
            f"Failed to import tool class '{class_path}': {e}"
        ) from e

    try:
        tool_class: type[BaseTool] = getattr(module, class_name)
    except AttributeError as e:
        raise ToolRegistryError(
            f"Tool class not found in module '{module_name}': {class_name}"
        ) from e

    if not issubclass(tool_class, BaseTool):
        raise ToolRegistryError(f"Tool class must inherit from BaseTool: {class_path}")

    return tool_class


def load_from_config(
    registry: ToolRegistry,
    config_name: str,
    config_loader: Any | None = None,
) -> BaseTool:
    """Load and register a tool from configuration file."""
    if config_loader is None:
        from temper_ai.workflow.config_loader import ConfigLoader

        config_loader = ConfigLoader()

    # Load configuration
    try:
        tool_config = config_loader.load_tool(config_name, validate=False)
    except Exception as e:
        raise ToolRegistryError(
            f"Failed to load tool configuration '{config_name}': {e}"
        ) from e

    # Parse tool data
    tool_data = tool_config.get("tool", {})
    tool_name = tool_data.get("name")
    implementation = tool_data.get("implementation", {})

    if not tool_name:
        raise ToolRegistryError(
            f"Tool configuration missing 'name' field: {config_name}"
        )

    # Parse implementation path
    class_path = _parse_implementation_path(implementation, config_name)

    # Load and instantiate tool
    try:
        tool_class = _load_tool_class(class_path)
        tool_instance = tool_class()
        registry.register(tool_instance)

        logger.info(f"Loaded tool from config: {tool_name} ({config_name})")
        return tool_instance

    except (TypeError, ValueError, RuntimeError) as e:
        raise ToolRegistryError(f"Failed to instantiate tool '{tool_name}': {e}") from e


def load_all_from_configs(
    registry: ToolRegistry,
    config_loader: Any | None = None,
) -> int:
    """Load and register all tools from configuration files."""
    if config_loader is None:
        from temper_ai.workflow.config_loader import ConfigLoader

        config_loader = ConfigLoader()

    try:
        tool_configs = config_loader.list_configs("tool")
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f"Failed to list tool configurations: {e}")
        return 0

    loaded_count = 0

    for config_name in tool_configs:
        try:
            load_from_config(registry, config_name, config_loader)
            loaded_count += 1
        except ToolRegistryError as e:
            logger.warning(f"Failed to load tool '{config_name}': {e}")

    logger.info(f"Loaded {loaded_count} tools from configurations")

    return loaded_count


# ---------------------------------------------------------------------------
# Reporting / info
# ---------------------------------------------------------------------------


def list_available_tools(registry: ToolRegistry) -> dict[str, dict[str, Any]]:
    """List all registered tools with detailed information."""
    result = {}
    for name in registry._tools:
        tool = registry.get(name)
        if tool:
            metadata = tool.get_metadata()
            result[name] = {
                "class": tool.__class__.__name__,
                "description": metadata.description,
                "version": metadata.version,
                "category": metadata.category,
                "requires_network": metadata.requires_network,
                "requires_credentials": metadata.requires_credentials,
                "all_versions": registry.list_tool_versions(name),
            }
    return result


def get_registration_report(registry: ToolRegistry) -> str:
    """Get detailed registration report for debugging."""
    lines = []
    lines.append("Tool Registry Report")
    lines.append("=" * REPORT_SEPARATOR_LENGTH)

    total_tools = len(registry._tools)
    total_versions = len(registry)
    lines.append(f"Total registered tools: {total_tools} ({total_versions} versions)")
    lines.append("")

    if registry._tools:
        lines.append("Registered tools:")
        for name in sorted(registry._tools.keys()):
            versions = registry.list_tool_versions(name)
            versions_str = ", ".join(f"v{v}" for v in sorted(versions))
            lines.append(f"  - {name} ({versions_str})")
    else:
        lines.append("No tools registered")

    return "\n".join(lines)


def get_tool_metadata(registry: ToolRegistry, name: str) -> dict[str, Any]:
    """Get tool metadata."""
    tool = registry.get(name)
    if not tool:
        raise ToolRegistryError(f"Tool not found: {name}")

    metadata = tool.get_metadata()
    return {
        "name": metadata.name,
        "description": metadata.description,
        "version": metadata.version,
        "category": metadata.category,
        "requires_network": metadata.requires_network,
        "requires_credentials": metadata.requires_credentials,
    }


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def get_latest_version(versions: list[str]) -> str:
    """Get the latest version from a list of version strings."""
    if not versions:
        raise ValueError("No versions provided")
    if len(versions) == 1:
        return versions[0]

    def version_key(v: str) -> tuple[int, ...]:
        """Parse version string into sortable tuple."""
        try:
            parts = v.split(".")
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (0, 0, 0)

    return max(versions, key=version_key)
