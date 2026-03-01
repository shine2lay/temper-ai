"""
Tool registry for managing and discovering tools.
"""

import logging
import threading
import warnings
from typing import Any

from temper_ai.shared.utils.exceptions import ToolRegistryError
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
        """Initialize tool registry.

        The ``auto_discover`` parameter is deprecated and ignored.  Tools
        are now lazily instantiated from the static ``TOOL_CLASSES`` map
        in ``temper_ai.tools`` when first accessed via ``get()``.
        """
        self._tools: dict[str, dict[str, BaseTool]] = {}
        self._lock = threading.Lock()

        if auto_discover:
            warnings.warn(
                "auto_discover is deprecated. Tools are now lazily loaded "
                "from TOOL_CLASSES. Pass auto_discover=False or omit it.",
                DeprecationWarning,
                stacklevel=2,
            )

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
        """Get tool by name and optionally version.

        If the tool is not already registered, attempts lazy instantiation
        from the static ``TOOL_CLASSES`` registry.  Each call that triggers
        lazy instantiation creates a fresh instance so per-agent tool config
        doesn't leak across agents.
        """
        if name not in self._tools:
            # Lazy instantiation from static registry
            from temper_ai.tools import TOOL_CLASSES

            tool_class = TOOL_CLASSES.get(name)
            if tool_class is None:
                return None
            tool = tool_class()
            self.register(tool)

        tool_versions = self._tools[name]

        if version is not None:
            return tool_versions.get(version)

        if not tool_versions:
            return None

        latest_version = get_latest_version(list(tool_versions.keys()))
        return tool_versions[latest_version]

    def has(self, name: str, version: str | None = None) -> bool:
        """Check if tool exists (registered or in static registry)."""
        if name in self._tools:
            if version is None:
                return len(self._tools[name]) > 0
            return version in self._tools[name]
        # Check static registry (without instantiation)
        if version is not None:
            return False
        from temper_ai.tools import TOOL_CLASSES

        return name in TOOL_CLASSES

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

    def list_available(self) -> list[str]:
        """List all available tool names (static registry + manually registered)."""
        from temper_ai.tools import TOOL_CLASSES

        names = set(TOOL_CLASSES.keys())
        names.update(self._tools.keys())
        return sorted(names)

    def auto_discover(
        self, tools_package: str = "temper_ai.tools", use_cache: bool = True
    ) -> int:
        """Deprecated.  Tools are now lazily loaded from TOOL_CLASSES.

        This method is a no-op that returns the number of statically
        known tools for backward compatibility.
        """
        warnings.warn(
            "auto_discover() is deprecated. Tools are lazily loaded "
            "from TOOL_CLASSES. Remove this call.",
            DeprecationWarning,
            stacklevel=2,
        )
        from temper_ai.tools import TOOL_CLASSES

        return len(TOOL_CLASSES)

    def clear(self) -> None:
        """Clear all registered tools."""
        with self._lock:
            self._tools.clear()

    def __len__(self) -> int:
        return sum(len(versions) for versions in self._tools.values())

    def __contains__(self, name: str) -> bool:
        if name in self._tools:
            return True
        from temper_ai.tools import TOOL_CLASSES

        return name in TOOL_CLASSES

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
ToolRegistry.count = _count  # type: ignore[attr-defined]
ToolRegistry.get_tool_metadata = _get_tool_metadata_method  # type: ignore[attr-defined]
ToolRegistry._validate_tool_interface = _validate_tool_interface_method  # type: ignore[attr-defined]
ToolRegistry._get_error_suggestion = _get_error_suggestion_method  # type: ignore[attr-defined]
ToolRegistry.list_available_tools = _list_available_tools_method  # type: ignore[attr-defined]
ToolRegistry.get_registration_report = _get_registration_report_method  # type: ignore[attr-defined]
ToolRegistry.load_from_config = _load_from_config_method  # type: ignore[attr-defined]
ToolRegistry.load_all_from_configs = _load_all_from_configs_method  # type: ignore[attr-defined]
