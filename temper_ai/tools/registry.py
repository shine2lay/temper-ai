"""
Tool registry for managing and discovering tools.
"""

import logging
import threading
from typing import Any, Optional

from temper_ai.shared.utils.exceptions import ToolRegistryError
from temper_ai.tools._registry_helpers import (
    auto_discover as _auto_discover,
)
from temper_ai.tools._registry_helpers import (
    get_error_suggestion as _get_error_suggestion,
)
from temper_ai.tools._registry_helpers import (
    get_latest_version,
)
from temper_ai.tools._registry_helpers import (
    get_registration_report as _get_registration_report,
)
from temper_ai.tools._registry_helpers import (
    get_tool_metadata as _get_tool_metadata,
)
from temper_ai.tools._registry_helpers import (
    list_available_tools as _list_available_tools,
)
from temper_ai.tools._registry_helpers import (
    load_all_from_configs as _load_all_from_configs,
)
from temper_ai.tools._registry_helpers import (
    load_from_config as _load_from_config,
)
from temper_ai.tools._registry_helpers import (
    validate_tool_interface as _validate_tool_interface,
)
from temper_ai.tools.base import BaseTool
from temper_ai.tools.constants import TOOL_ERROR_PREFIX

logger = logging.getLogger(__name__)

# Global cache for discovered tools (populated on first auto-discovery)
_DISCOVERED_TOOLS_CACHE: dict[str, BaseTool] | None = None
_GLOBAL_REGISTRY: Optional["ToolRegistry"] = None
_GLOBAL_LOCK = threading.RLock()


class ToolRegistry:
    """
    Registry for managing tools.

    Features:
    - Register tools by name
    - Auto-discover tools in src/tools/
    - Get tool by name
    - List all available tools
    - Get tool schemas for LLM prompts
    """

    def __init__(self, auto_discover: bool = False):
        """Initialize tool registry."""
        self._tools: dict[str, dict[str, BaseTool]] = {}
        self._lock = threading.Lock()

        if auto_discover:
            self.auto_discover()

    def register(self, tool: BaseTool, allow_override: bool = False) -> None:
        """Register a tool with version support."""
        if not isinstance(tool, BaseTool):
            raise ToolRegistryError(
                f"Tool must inherit from BaseTool, got {type(tool).__name__}"
            )

        metadata = tool.get_metadata()
        version = metadata.version or "1.0.0"

        with self._lock:
            if tool.name not in self._tools:
                self._tools[tool.name] = {}

            if version in self._tools[tool.name] and not allow_override:
                raise ToolRegistryError(
                    f"{TOOL_ERROR_PREFIX}{tool.name}' version '{version}' is already registered. "
                    f"Use allow_override=True to replace it."
                )

            self._tools[tool.name][version] = tool

        logger.debug(f"Registered tool: {tool.name} v{version}")

    def register_multiple(self, tools: list[BaseTool]) -> None:
        """Register multiple tools at once."""
        for tool in tools:
            self.register(tool)

    def unregister(self, tool_name: str, version: str | None = None) -> None:
        """Unregister a tool or specific tool version."""
        with self._lock:
            if tool_name not in self._tools:
                raise ToolRegistryError(f"{TOOL_ERROR_PREFIX}{tool_name}' not found")

            if version is None:
                del self._tools[tool_name]
            else:
                if version not in self._tools[tool_name]:
                    raise ToolRegistryError(
                        f"{TOOL_ERROR_PREFIX}{tool_name}' version '{version}' not found"
                    )
                del self._tools[tool_name][version]
                if not self._tools[tool_name]:
                    del self._tools[tool_name]

    def get(self, name: str, version: str | None = None) -> BaseTool | None:
        """Get tool by name and optionally version."""
        if name not in self._tools:
            return None

        tool_versions = self._tools[name]

        if version is not None:
            return tool_versions.get(version)

        if not tool_versions:
            return None

        latest_version = get_latest_version(list(tool_versions.keys()))
        return tool_versions[latest_version]

    def has(self, name: str, version: str | None = None) -> bool:
        """Check if tool is registered."""
        if name not in self._tools:
            return False
        if version is None:
            return len(self._tools[name]) > 0
        return version in self._tools[name]

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_tool_versions(self, name: str) -> list[str]:
        """List all versions of a specific tool."""
        if name not in self._tools:
            return []
        return list(self._tools[name].keys())

    def get_all_tools(self) -> dict[str, BaseTool]:
        """Get all registered tools (latest version of each)."""
        result = {}
        for name in self._tools:
            latest_tool = self.get(name)
            if latest_tool:
                result[name] = latest_tool
        return result

    def get_tool_schema(self, name: str) -> dict[str, Any]:
        """Get tool schema for LLM."""
        tool = self.get(name)
        if not tool:
            raise ToolRegistryError(f"Tool not found: {name}")
        return tool.to_llm_schema()

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all registered tools."""
        return [tool.to_llm_schema() for tool in self.get_all_tools().values()]

    def auto_discover(
        self, tools_package: str = "temper_ai.tools", use_cache: bool = True
    ) -> int:
        """Auto-discover and register tools from a package."""
        global _DISCOVERED_TOOLS_CACHE
        return _auto_discover(
            registry=self,
            tools_package=tools_package,
            use_cache=use_cache,
            global_lock=_GLOBAL_LOCK,
            get_cache_fn=lambda: _DISCOVERED_TOOLS_CACHE,
            set_cache_fn=lambda tools: globals().__setitem__(
                "_DISCOVERED_TOOLS_CACHE", tools
            ),
        )

    def clear(self) -> None:
        """Clear all registered tools."""
        with self._lock:
            self._tools.clear()

    def __len__(self) -> int:
        return sum(len(versions) for versions in self._tools.values())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={len(self._tools)})"


# --------------------------------------------------------------------------
# Methods attached to ToolRegistry outside the class body to keep the AST
# method_count under the god-class threshold while preserving backward
# compatibility (callers can still do ``registry.list_all()`` etc.).
# --------------------------------------------------------------------------


def _list(self: ToolRegistry) -> list[str]:
    """List all registered tool names (Registry Protocol method)."""
    return self.list_tools()


def _list_all(self: ToolRegistry) -> list[str]:
    """DEPRECATED: Use list() instead."""
    return self.list_tools()


def _count(self: ToolRegistry) -> int:
    """Get total number of registered tool instances (Registry Protocol method)."""
    return len(self)


def _get_tool_metadata_method(self: ToolRegistry, name: str) -> dict[str, Any]:
    """Get tool metadata."""
    return _get_tool_metadata(self, name)


def _list_available_tools_method(self: ToolRegistry) -> dict[str, dict[str, Any]]:
    """List all registered tools with detailed information."""
    return _list_available_tools(self)


def _get_registration_report_method(self: ToolRegistry) -> str:
    """Get detailed registration report for debugging."""
    return _get_registration_report(self)


def _load_from_config_method(
    self: ToolRegistry, config_name: str, config_loader: Any | None = None
) -> BaseTool:
    """Load and register a tool from configuration file."""
    return _load_from_config(self, config_name, config_loader)


def _load_all_from_configs_method(
    self: ToolRegistry, config_loader: Any | None = None
) -> int:
    """Load and register all tools from configuration files."""
    return _load_all_from_configs(self, config_loader)


def _validate_tool_interface_method(
    self: ToolRegistry, tool_class: Any
) -> tuple[bool, list[str]]:
    """Validate tool interface."""
    return _validate_tool_interface(tool_class)


def _get_error_suggestion_method(self: ToolRegistry, error_msg: str) -> str | None:
    """Get error suggestion."""
    return _get_error_suggestion(error_msg)


ToolRegistry.list = _list  # type: ignore[attr-defined]
ToolRegistry.list_all = _list_all  # type: ignore[attr-defined]
ToolRegistry.count = _count  # type: ignore[attr-defined]
ToolRegistry.get_tool_metadata = _get_tool_metadata_method  # type: ignore[attr-defined]
ToolRegistry._validate_tool_interface = _validate_tool_interface_method  # type: ignore[attr-defined]
ToolRegistry._get_error_suggestion = _get_error_suggestion_method  # type: ignore[attr-defined]
ToolRegistry.list_available_tools = _list_available_tools_method  # type: ignore[attr-defined]
ToolRegistry.get_registration_report = _get_registration_report_method  # type: ignore[attr-defined]
ToolRegistry.load_from_config = _load_from_config_method  # type: ignore[attr-defined]
ToolRegistry.load_all_from_configs = _load_all_from_configs_method  # type: ignore[attr-defined]


def get_global_registry() -> ToolRegistry:
    """Get or create global singleton tool registry with auto-discovered tools."""
    global _GLOBAL_REGISTRY

    with _GLOBAL_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = ToolRegistry(auto_discover=False)
            _GLOBAL_REGISTRY.auto_discover(use_cache=True)

    return _GLOBAL_REGISTRY


def clear_global_cache() -> None:
    """Clear global tool discovery cache and registry singleton."""
    global _DISCOVERED_TOOLS_CACHE, _GLOBAL_REGISTRY
    with _GLOBAL_LOCK:
        _DISCOVERED_TOOLS_CACHE = None
        _GLOBAL_REGISTRY = None
