"""Helper functions extracted from ToolRegistry to reduce class size.

These are internal implementation details and should not be imported directly.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, cast

from src.tools.base import BaseTool
from src.utils.exceptions import ToolRegistryError

if TYPE_CHECKING:
    from src.tools.registry import ToolRegistry

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
        "  from src.tools.base import BaseTool\n"
        "  class MyTool(BaseTool):\n"
        "      ..."
    ),
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_tool_interface(tool_class: Type[Any]) -> Tuple[bool, List[str]]:
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

    required_methods = ['execute', 'get_metadata', 'get_parameters_schema']
    for method_name in required_methods:
        if not hasattr(tool_class, method_name):
            errors.append(f"Missing required method: {method_name}")
        else:
            attr = getattr(tool_class, method_name)
            if not callable(attr):
                errors.append(f"'{method_name}' is not callable")
            elif getattr(attr, '__isabstractmethod__', False):
                errors.append(f"'{method_name}' is still abstract (not implemented)")

    return len(errors) == 0, errors


def get_error_suggestion(error_msg: str) -> Optional[str]:
    """Get helpful suggestion for common errors."""
    error_lower = error_msg.lower()
    for pattern, suggestion in COMMON_ERROR_SUGGESTIONS.items():
        if pattern.lower() in error_lower:
            return suggestion
    return None


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

def auto_discover(
    registry: ToolRegistry,
    tools_package: str,
    use_cache: bool,
    global_lock,
    get_cache_fn,
    set_cache_fn,
) -> int:
    """Auto-discover and register tools from a package with detailed logging."""
    # TO-07: Read cache under lock
    if use_cache:
        with global_lock:
            cached = get_cache_fn()
        if cached is not None:
            logger.info(f"Using cached discovered tools ({len(cached)} tools)")
            for tool_name, tool_instance in cached.items():
                registry.register(tool_instance, allow_override=True)
            return len(cached)

    # Perform discovery
    logger.info(f"Starting tool discovery in package: {tools_package}")
    registered_count = 0
    discovered_count = 0
    skipped_tools: List[Tuple[str, str]] = []
    discovered_tools: Dict[str, BaseTool] = {}

    try:
        package = importlib.import_module(tools_package)
        if package.__file__ is None:
            raise ValueError(f"Package {tools_package} has no __file__ attribute")
        package_path = Path(package.__file__).parent

        for _, module_name, is_pkg in pkgutil.iter_modules([str(package_path)]):
            if is_pkg or module_name.startswith("_"):
                continue

            try:
                module = importlib.import_module(f"{tools_package}.{module_name}")

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        obj is not BaseTool
                        and obj.__module__ == module.__name__
                    ):
                        try:
                            if not issubclass(obj, BaseTool):
                                continue
                        except TypeError:
                            continue

                        discovered_count += 1

                        is_valid, validation_errors = validate_tool_interface(obj)

                        if not is_valid:
                            error_msg = f"Tool {obj.__name__} failed validation"
                            logger.warning(
                                f"{error_msg}:\n" +
                                "\n".join(f"  - {err}" for err in validation_errors)
                            )
                            skipped_tools.append((obj.__name__, "; ".join(validation_errors)))

                            suggestion = get_error_suggestion("\n".join(validation_errors))
                            if suggestion:
                                logger.info(f"Suggestion for {obj.__name__}:\n{suggestion}")
                            continue

                        try:
                            tool_instance = obj()
                            try:
                                registry.register(tool_instance, allow_override=False)
                                metadata = tool_instance.get_metadata()
                                version = metadata.version or "1.0.0"
                                discovered_tools[f"{tool_instance.name}:{version}"] = tool_instance
                                registered_count += 1
                                logger.info(f"[OK] Registered tool: {tool_instance.name} v{version} ({obj.__name__})")
                            except ToolRegistryError as e:
                                logger.warning(f"Skipping {obj.__name__}: {e}")
                                skipped_tools.append((obj.__name__, str(e)))

                        except TypeError as e:
                            error_msg = f"Tool {obj.__name__} requires init arguments"
                            logger.warning(
                                f"{error_msg}:\n"
                                f"  Error: {e}\n"
                                f"  Suggestion: Provide default values or register manually"
                            )
                            skipped_tools.append((obj.__name__, f"Constructor requires arguments: {e}"))

                            suggestion = get_error_suggestion("requires init arguments")
                            if suggestion:
                                logger.debug(f"How to fix:\n{suggestion}")

                        except (ValueError, AttributeError, RuntimeError) as e:
                            logger.error(
                                f"Failed to instantiate tool {obj.__name__}: {e}",
                                exc_info=True
                            )
                            skipped_tools.append((obj.__name__, f"Instantiation error: {e}"))

            except ImportError as e:
                logger.warning(
                    f"Failed to import module {tools_package}.{module_name}: {e}"
                )
                skipped_tools.append((module_name, f"Import error: {e}"))

    except ImportError as e:
        logger.error(f"Package {tools_package} not found for auto-discovery: {e}")
        return 0

    logger.info(
        f"Tool discovery complete: {registered_count}/{discovered_count} tools registered, "
        f"{len(skipped_tools)} skipped"
    )

    if skipped_tools and logger.isEnabledFor(logging.DEBUG):
        logger.debug("Skipped tools details:")
        for tool_name, reason in skipped_tools:
            logger.debug(f"  {tool_name}: {reason}")

    # TO-07: Cache discovered tools under lock
    if use_cache and discovered_tools:
        with global_lock:
            set_cache_fn(discovered_tools)

    return registered_count


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_from_config(
    registry: ToolRegistry,
    config_name: str,
    config_loader: Optional[Any] = None,
) -> BaseTool:
    """Load and register a tool from configuration file."""
    if config_loader is None:
        from src.compiler.config_loader import ConfigLoader
        config_loader = ConfigLoader()

    try:
        tool_config = config_loader.load_tool(config_name, validate=False)
    except Exception as e:
        raise ToolRegistryError(
            f"Failed to load tool configuration '{config_name}': {e}"
        )

    tool_data = tool_config.get("tool", {})
    tool_name = tool_data.get("name")
    implementation = tool_data.get("implementation", {})

    if not tool_name:
        raise ToolRegistryError(
            f"Tool configuration missing 'name' field: {config_name}"
        )

    if isinstance(implementation, str):
        class_path = implementation
    elif isinstance(implementation, dict):
        module_path = implementation.get("module")
        class_name = implementation.get("class")

        if not module_path or not class_name:
            raise ToolRegistryError(
                f"Tool implementation must specify 'module' and 'class': {config_name}"
            )

        class_path = f"{module_path}.{class_name}"
    else:
        raise ToolRegistryError(
            f"Invalid implementation format in tool config: {config_name}"
        )

    try:
        parts = class_path.rsplit(".", 1)
        if len(parts) != 2:
            raise ToolRegistryError(
                f"Invalid class path format: {class_path}"
            )

        module_name, class_name = parts

        module = importlib.import_module(module_name)

        tool_class = getattr(module, class_name)

        if not issubclass(tool_class, BaseTool):
            raise ToolRegistryError(
                f"Tool class must inherit from BaseTool: {class_path}"
            )

        tool_instance = cast(Type[BaseTool], tool_class)()

        registry.register(tool_instance)

        logger.info(f"Loaded tool from config: {tool_name} ({config_name})")

        return tool_instance

    except ImportError as e:
        raise ToolRegistryError(
            f"Failed to import tool class '{class_path}': {e}"
        )
    except AttributeError:
        raise ToolRegistryError(
            f"Tool class not found in module '{module_name}': {class_name}"
        )
    except (TypeError, ValueError, RuntimeError) as e:
        raise ToolRegistryError(
            f"Failed to instantiate tool '{tool_name}': {e}"
        )


def load_all_from_configs(
    registry: ToolRegistry,
    config_loader: Optional[Any] = None,
) -> int:
    """Load and register all tools from configuration files."""
    if config_loader is None:
        from src.compiler.config_loader import ConfigLoader
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

def list_available_tools(registry: ToolRegistry) -> Dict[str, Dict[str, Any]]:
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


def get_tool_metadata(registry: ToolRegistry, name: str) -> Dict[str, Any]:
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

def get_latest_version(versions: List[str]) -> str:
    """Get the latest version from a list of version strings."""
    if not versions:
        raise ValueError("No versions provided")
    if len(versions) == 1:
        return versions[0]

    def version_key(v: str) -> Tuple[int, ...]:
        """Parse version string into sortable tuple."""
        try:
            parts = v.split('.')
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (0, 0, 0)

    return max(versions, key=version_key)


# ---------------------------------------------------------------------------
# Mixin for reporting/query methods (extracted from ToolRegistry)
# ---------------------------------------------------------------------------

class ToolRegistryReportingMixin:
    """Mixin providing reporting and query methods for ToolRegistry."""

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """Get tool schema for LLM."""
        tool = self.get(name)  # type: ignore[attr-defined]
        if not tool:
            raise ToolRegistryError(f"Tool not found: {name}")
        return tool.to_llm_schema()

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for all registered tools."""
        return [tool.to_llm_schema() for tool in self.get_all_tools().values()]  # type: ignore[attr-defined]

    def get_tool_metadata(self, name: str) -> Dict[str, Any]:
        """Get tool metadata."""
        return get_tool_metadata(self, name)  # type: ignore[arg-type]

    def list_available_tools(self) -> Dict[str, Dict[str, Any]]:
        """List all registered tools with detailed information."""
        return list_available_tools(self)  # type: ignore[arg-type]

    def get_registration_report(self) -> str:
        """Get detailed registration report for debugging."""
        return get_registration_report(self)  # type: ignore[arg-type]


class ToolRegistryValidationMixin:
    """Mixin providing validation methods for ToolRegistry."""

    def _validate_tool_interface(self, tool_class: Type[Any]) -> Tuple[bool, List[str]]:
        """Validate that a tool class implements the required interface."""
        return validate_tool_interface(tool_class)

    def _get_error_suggestion(self, error_msg: str) -> Optional[str]:
        """Get helpful suggestion for common errors."""
        return get_error_suggestion(error_msg)
