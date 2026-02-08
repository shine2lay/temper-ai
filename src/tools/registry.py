"""
Tool registry for managing and discovering tools.
"""
import importlib
import inspect
import logging
import pkgutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, cast

from src.tools.base import BaseTool

# Import enhanced exceptions
from src.utils.exceptions import ToolRegistryError

logger = logging.getLogger(__name__)

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

# Global cache for discovered tools (populated on first auto-discovery)
_DISCOVERED_TOOLS_CACHE: Optional[Dict[str, BaseTool]] = None
_GLOBAL_REGISTRY: Optional['ToolRegistry'] = None
_GLOBAL_LOCK = threading.Lock()


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
        """
        Initialize tool registry.

        Args:
            auto_discover: If True, automatically discover and register tools
        """
        # Changed to support multiple versions: name -> version -> tool
        self._tools: Dict[str, Dict[str, BaseTool]] = {}
        self._lock = threading.Lock()

        if auto_discover:
            self.auto_discover()

    def register(self, tool: BaseTool, allow_override: bool = False) -> None:
        """
        Register a tool with version support.

        Args:
            tool: Tool instance to register
            allow_override: If True, allow registering same name+version (default: False)

        Raises:
            ToolRegistryError: If tool name+version already registered or invalid
        """
        if not isinstance(tool, BaseTool):
            raise ToolRegistryError(
                f"Tool must inherit from BaseTool, got {type(tool).__name__}"
            )

        metadata = tool.get_metadata()
        version = metadata.version or "1.0.0"  # Default version if not specified

        with self._lock:
            # Initialize tool name dict if not exists
            if tool.name not in self._tools:
                self._tools[tool.name] = {}

            # Check if this version already exists (atomic with registration)
            if version in self._tools[tool.name] and not allow_override:
                raise ToolRegistryError(
                    f"Tool '{tool.name}' version '{version}' is already registered. "
                    f"Use allow_override=True to replace it."
                )

            self._tools[tool.name][version] = tool

        logger.debug(f"Registered tool: {tool.name} v{version}")

    def register_multiple(self, tools: List[BaseTool]) -> None:
        """
        Register multiple tools at once.

        Args:
            tools: List of tool instances to register
        """
        for tool in tools:
            self.register(tool)

    def unregister(self, tool_name: str, version: Optional[str] = None) -> None:
        """
        Unregister a tool or specific tool version.

        Args:
            tool_name: Name of tool to unregister
            version: Specific version to unregister (None = unregister all versions)

        Raises:
            ToolRegistryError: If tool not found
        """
        with self._lock:
            if tool_name not in self._tools:
                raise ToolRegistryError(f"Tool '{tool_name}' not found")

            if version is None:
                # Unregister all versions
                del self._tools[tool_name]
            else:
                # Unregister specific version
                if version not in self._tools[tool_name]:
                    raise ToolRegistryError(
                        f"Tool '{tool_name}' version '{version}' not found"
                    )
                del self._tools[tool_name][version]

                # Remove tool entry if no versions left
                if not self._tools[tool_name]:
                    del self._tools[tool_name]

    def get(self, name: str, version: Optional[str] = None) -> Optional[BaseTool]:
        """
        Get tool by name and optionally version.

        Args:
            name: Tool name
            version: Tool version (default: None, returns latest version)

        Returns:
            Tool instance or None if not found
        """
        if name not in self._tools:
            return None

        tool_versions = self._tools[name]

        if version is not None:
            # Return specific version
            return tool_versions.get(version)

        # Return latest version (by semantic versioning)
        if not tool_versions:
            return None

        latest_version = self._get_latest_version(list(tool_versions.keys()))
        return tool_versions[latest_version]

    def _get_latest_version(self, versions: List[str]) -> str:
        """
        Get the latest version from a list of version strings.

        Uses simple string comparison if versions don't follow semantic versioning.

        Args:
            versions: List of version strings

        Returns:
            Latest version string
        """
        if not versions:
            raise ValueError("No versions provided")

        if len(versions) == 1:
            return versions[0]

        # Try semantic versioning comparison
        def version_key(v: str) -> Tuple[int, ...]:
            """Convert version string to comparable tuple."""
            try:
                # Handle semantic versioning (e.g., "1.2.3")
                parts = v.split('.')
                return tuple(int(p) for p in parts)
            except (ValueError, AttributeError):
                # Fall back to string comparison
                return (0, 0, 0)  # Versions that can't be parsed go first

        return max(versions, key=version_key)

    def has(self, name: str, version: Optional[str] = None) -> bool:
        """
        Check if tool is registered.

        Args:
            name: Tool name
            version: Tool version (optional)

        Returns:
            True if tool is registered
        """
        if name not in self._tools:
            return False

        if version is None:
            # Check if any version of this tool exists
            return len(self._tools[name]) > 0

        # Check if specific version exists
        return version in self._tools[name]

    def list_tools(self) -> List[str]:
        """
        List all registered tool names (without version info).

        Returns:
            List of unique tool names
        """
        return list(self._tools.keys())

    def list(self) -> List[str]:
        """
        List all registered tool names (Registry Protocol method).

        Returns:
            List of unique tool names
        """
        return self.list_tools()

    def list_all(self) -> List[str]:
        """
        DEPRECATED: Use list() instead.

        List all registered tool names (backward compatibility).

        Returns:
            List of unique tool names
        """
        return self.list_tools()

    def count(self) -> int:
        """
        Get total number of registered tool instances (Registry Protocol method).

        This is an alias for __len__() to satisfy the Registry Protocol.
        Counts all tool versions (not just unique names).

        Returns:
            Total count of tool instances (all versions)
        """
        return len(self)

    def list_tool_versions(self, name: str) -> List[str]:
        """
        List all versions of a specific tool.

        Args:
            name: Tool name

        Returns:
            List of version strings for this tool (empty if tool not found)
        """
        if name not in self._tools:
            return []

        return list(self._tools[name].keys())

    def get_all_tools(self) -> Dict[str, BaseTool]:
        """
        Get all registered tools (latest version of each).

        Returns:
            Dict mapping tool names to latest tool instances
        """
        result = {}
        for name in self._tools:
            latest_tool = self.get(name)  # Gets latest version
            if latest_tool:
                result[name] = latest_tool
        return result

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """
        Get tool schema for LLM (OpenAI function calling format).

        Args:
            name: Tool name

        Returns:
            Tool schema in OpenAI function calling format

        Raises:
            ToolRegistryError: If tool not found
        """
        tool = self.get(name)
        if not tool:
            raise ToolRegistryError(f"Tool not found: {name}")

        return tool.to_llm_schema()

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Get schemas for all registered tools (latest version of each).

        Returns:
            List of tool schemas in OpenAI function calling format
        """
        return [tool.to_llm_schema() for tool in self.get_all_tools().values()]

    def get_tool_metadata(self, name: str) -> Dict[str, Any]:
        """
        Get tool metadata.

        Args:
            name: Tool name

        Returns:
            Dict with tool metadata

        Raises:
            ToolRegistryError: If tool not found
        """
        tool = self.get(name)
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

    def _validate_tool_interface(self, tool_class: Type[Any]) -> Tuple[bool, List[str]]:
        """
        Validate that a tool class implements the required interface.

        Args:
            tool_class: Tool class to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check inheritance
        try:
            if not issubclass(tool_class, BaseTool):
                errors.append(f"Tool must inherit from BaseTool, got {tool_class.__name__}")
        except TypeError:
            errors.append(f"Invalid tool class: {tool_class}")
            return False, errors

        # Check for abstract methods
        if inspect.isabstract(tool_class):
            errors.append("Tool class has unimplemented abstract methods")

        # Check required methods exist and are callable
        required_methods = ['execute', 'get_metadata', 'get_parameters_schema']
        for method_name in required_methods:
            if not hasattr(tool_class, method_name):
                errors.append(f"Missing required method: {method_name}")
            else:
                attr = getattr(tool_class, method_name)
                if not callable(attr):
                    errors.append(f"'{method_name}' is not callable")
                # Verify it's not still an abstract method marker
                elif getattr(attr, '__isabstractmethod__', False):
                    errors.append(f"'{method_name}' is still abstract (not implemented)")

        return len(errors) == 0, errors

    def _get_error_suggestion(self, error_msg: str) -> Optional[str]:
        """
        Get helpful suggestion for common errors.

        Args:
            error_msg: Error message

        Returns:
            Suggestion string or None
        """
        error_lower = error_msg.lower()
        for pattern, suggestion in COMMON_ERROR_SUGGESTIONS.items():
            if pattern.lower() in error_lower:
                return suggestion
        return None

    def list_available_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        List all registered tools with detailed information (latest version of each).

        Returns:
            Dict mapping tool names to tool details (class, description, metadata)

        Example:
            >>> registry = ToolRegistry(auto_discover=True)
            >>> tools = registry.list_available_tools()
            >>> for name, info in tools.items():
            ...     print(f"{name}: {info['description']}")
        """
        result = {}
        for name in self._tools:
            tool = self.get(name)  # Get latest version
            if tool:
                metadata = tool.get_metadata()
                result[name] = {
                    "class": tool.__class__.__name__,
                    "description": metadata.description,
                    "version": metadata.version,
                    "category": metadata.category,
                    "requires_network": metadata.requires_network,
                    "requires_credentials": metadata.requires_credentials,
                    "all_versions": self.list_tool_versions(name),
                }
        return result

    def get_registration_report(self) -> str:
        """
        Get detailed registration report for debugging.

        Returns:
            Formatted report string with registration details

        Example:
            >>> registry = ToolRegistry(auto_discover=True)
            >>> print(registry.get_registration_report())
            Tool Registry Report
            ====================
            Total registered tools: 3 (5 versions)

            Registered tools:
              - Calculator (v1.0.0, v2.0.0)
              - FileWriter (v1.0.0)
              - WebScraper (v1.0.0, v1.1.0)
        """
        lines = []
        lines.append("Tool Registry Report")
        lines.append("=" * 40)

        total_tools = len(self._tools)
        total_versions = len(self)
        lines.append(f"Total registered tools: {total_tools} ({total_versions} versions)")
        lines.append("")

        if self._tools:
            lines.append("Registered tools:")
            for name in sorted(self._tools.keys()):
                versions = self.list_tool_versions(name)
                versions_str = ", ".join(f"v{v}" for v in sorted(versions))
                lines.append(f"  - {name} ({versions_str})")
        else:
            lines.append("No tools registered")

        return "\n".join(lines)

    def auto_discover(self, tools_package: str = "src.tools", use_cache: bool = True) -> int:
        """
        Auto-discover and register tools from a package with detailed logging.

        Searches for all classes that inherit from BaseTool in the specified package.
        Provides clear feedback about discovered, registered, and skipped tools.

        Args:
            tools_package: Python package path to search (default: src.tools)
            use_cache: If True, use cached discovered tools (default: True)

        Returns:
            Number of tools successfully registered

        Note:
            - Validates tool interface before instantiation
            - Provides clear error messages for failed tools
            - Logs at INFO for successful registration
            - Logs at WARNING for validation failures and errors
            - Uses global cache for performance (100-500ms savings per call)
        """
        global _DISCOVERED_TOOLS_CACHE

        # TO-07: Read cache under lock
        if use_cache:
            with _GLOBAL_LOCK:
                cached = _DISCOVERED_TOOLS_CACHE
            if cached is not None:
                logger.info(f"Using cached discovered tools ({len(cached)} tools)")
                for tool_name, tool_instance in cached.items():
                    # Re-register cached tools to ensure proper version management
                    self.register(tool_instance, allow_override=True)
                return len(cached)

        # Perform discovery
        logger.info(f"Starting tool discovery in package: {tools_package}")
        registered_count = 0
        discovered_count = 0
        skipped_tools: List[Tuple[str, str]] = []  # (tool_name, reason)
        discovered_tools: Dict[str, BaseTool] = {}

        try:
            # Import the tools package
            package = importlib.import_module(tools_package)
            if package.__file__ is None:
                raise ValueError(f"Package {tools_package} has no __file__ attribute")
            package_path = Path(package.__file__).parent

            # Iterate through all modules in the package
            for _, module_name, is_pkg in pkgutil.iter_modules([str(package_path)]):
                if is_pkg or module_name.startswith("_"):
                    continue  # Skip subpackages and private modules

                try:
                    # Import module
                    module = importlib.import_module(f"{tools_package}.{module_name}")

                    # Find all classes in module
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        # Check if it's a BaseTool subclass (but not BaseTool itself)
                        if (
                            obj is not BaseTool
                            and obj.__module__ == module.__name__  # Defined in this module
                        ):
                            # Check if it inherits from BaseTool
                            try:
                                if not issubclass(obj, BaseTool):
                                    continue  # Not a tool, skip silently
                            except TypeError:
                                continue  # Not a class we can check, skip

                            discovered_count += 1

                            # Validate tool interface
                            is_valid, validation_errors = self._validate_tool_interface(obj)

                            if not is_valid:
                                error_msg = f"Tool {obj.__name__} failed validation"
                                logger.warning(
                                    f"{error_msg}:\n" +
                                    "\n".join(f"  - {err}" for err in validation_errors)
                                )
                                skipped_tools.append((obj.__name__, "; ".join(validation_errors)))

                                # Provide helpful suggestion
                                suggestion = self._get_error_suggestion("\n".join(validation_errors))
                                if suggestion:
                                    logger.info(f"Suggestion for {obj.__name__}:\n{suggestion}")
                                continue

                            # Try to instantiate
                            try:
                                tool_instance = obj()
                                # Use allow_override=False to detect version conflicts in auto-discovery
                                try:
                                    self.register(tool_instance, allow_override=False)
                                    metadata = tool_instance.get_metadata()
                                    version = metadata.version or "1.0.0"
                                    discovered_tools[f"{tool_instance.name}:{version}"] = tool_instance
                                    registered_count += 1
                                    logger.info(f"[OK] Registered tool: {tool_instance.name} v{version} ({obj.__name__})")
                                except ToolRegistryError as e:
                                    # Version conflict - log warning but continue
                                    logger.warning(f"Skipping {obj.__name__}: {e}")
                                    skipped_tools.append((obj.__name__, str(e)))

                            except TypeError as e:
                                # Constructor requires arguments
                                error_msg = f"Tool {obj.__name__} requires init arguments"
                                logger.warning(
                                    f"{error_msg}:\n"
                                    f"  Error: {e}\n"
                                    f"  Suggestion: Provide default values or register manually"
                                )
                                skipped_tools.append((obj.__name__, f"Constructor requires arguments: {e}"))

                                # Provide helpful suggestion
                                suggestion = self._get_error_suggestion("requires init arguments")
                                if suggestion:
                                    logger.debug(f"How to fix:\n{suggestion}")

                            except (ValueError, AttributeError, RuntimeError) as e:
                                # Other instantiation error
                                logger.error(
                                    f"Failed to instantiate tool {obj.__name__}: {e}",
                                    exc_info=True
                                )
                                skipped_tools.append((obj.__name__, f"Instantiation error: {e}"))

                except ImportError as e:
                    # Module failed to import
                    logger.warning(
                        f"Failed to import module {tools_package}.{module_name}: {e}"
                    )
                    skipped_tools.append((module_name, f"Import error: {e}"))

        except ImportError as e:
            # Package not found
            logger.error(f"Package {tools_package} not found for auto-discovery: {e}")
            return 0

        # Log summary
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
            with _GLOBAL_LOCK:
                _DISCOVERED_TOOLS_CACHE = discovered_tools

        return registered_count

    def load_from_config(
        self,
        config_name: str,
        config_loader: Optional[Any] = None
    ) -> BaseTool:
        """
        Load and register a tool from configuration file.

        Args:
            config_name: Name of the tool configuration file (without extension)
            config_loader: ConfigLoader instance (creates one if not provided)

        Returns:
            Instantiated and registered tool

        Raises:
            ToolRegistryError: If tool cannot be loaded or instantiated

        Example:
            >>> registry = ToolRegistry()
            >>> calculator = registry.load_from_config("calculator")
            >>> result = calculator.execute(expression="2 + 2")
        """
        # Import ConfigLoader if not provided
        if config_loader is None:
            from src.compiler.config_loader import ConfigLoader
            config_loader = ConfigLoader()

        try:
            # Load tool configuration
            tool_config = config_loader.load_tool(config_name, validate=False)
        except Exception as e:
            raise ToolRegistryError(
                f"Failed to load tool configuration '{config_name}': {e}"
            )

        # Extract tool details
        tool_data = tool_config.get("tool", {})
        tool_name = tool_data.get("name")
        implementation = tool_data.get("implementation", {})

        if not tool_name:
            raise ToolRegistryError(
                f"Tool configuration missing 'name' field: {config_name}"
            )

        # Handle different implementation formats
        if isinstance(implementation, str):
            # Direct class path: "src.tools.calculator.Calculator"
            class_path = implementation
        elif isinstance(implementation, dict):
            # Module + class: {"module": "src.tools.calculator", "class": "Calculator"}
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

        # Dynamically import and instantiate tool
        try:
            # Split class path into module and class name
            parts = class_path.rsplit(".", 1)
            if len(parts) != 2:
                raise ToolRegistryError(
                    f"Invalid class path format: {class_path}"
                )

            module_name, class_name = parts

            # Import module
            module = importlib.import_module(module_name)

            # Get class
            tool_class = getattr(module, class_name)

            # Verify it's a BaseTool subclass
            if not issubclass(tool_class, BaseTool):
                raise ToolRegistryError(
                    f"Tool class must inherit from BaseTool: {class_path}"
                )

            # Instantiate tool (cast needed for mypy after issubclass check)
            tool_instance = cast(Type[BaseTool], tool_class)()

            # Register tool
            self.register(tool_instance)

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
        self,
        config_loader: Optional[Any] = None
    ) -> int:
        """
        Load and register all tools from configuration files.

        Args:
            config_loader: ConfigLoader instance (creates one if not provided)

        Returns:
            Number of tools loaded

        Example:
            >>> registry = ToolRegistry()
            >>> count = registry.load_all_from_configs()
            >>> print(f"Loaded {count} tools from configurations")
        """
        # Import ConfigLoader if not provided
        if config_loader is None:
            from src.compiler.config_loader import ConfigLoader
            config_loader = ConfigLoader()

        # List all tool configurations
        try:
            tool_configs = config_loader.list_configs("tool")
        except (OSError, ValueError, KeyError) as e:
            logger.warning(f"Failed to list tool configurations: {e}")
            return 0

        loaded_count = 0

        # Load each tool configuration
        for config_name in tool_configs:
            try:
                self.load_from_config(config_name, config_loader)
                loaded_count += 1
            except ToolRegistryError as e:
                # Log but continue with other tools
                logger.warning(f"Failed to load tool '{config_name}': {e}")

        logger.info(f"Loaded {loaded_count} tools from configurations")

        return loaded_count

    def clear(self) -> None:
        """Clear all registered tools."""
        with self._lock:
            self._tools.clear()

    def __len__(self) -> int:
        """Return number of registered tool instances (counting all versions)."""
        return sum(len(versions) for versions in self._tools.values())

    def __contains__(self, name: str) -> bool:
        """Check if tool is registered using 'in' operator."""
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={len(self._tools)})"


def get_global_registry() -> ToolRegistry:
    """
    Get or create global singleton tool registry with auto-discovered tools.

    This function returns a shared registry instance with all tools already
    discovered and registered. Subsequent calls return the same instance,
    avoiding repeated auto-discovery overhead.

    Returns:
        Global ToolRegistry instance with auto-discovered tools

    Performance:
        - First call: ~100-500ms (performs auto-discovery)
        - Subsequent calls: ~0.1ms (returns cached instance)

    Example:
        >>> registry = get_global_registry()
        >>> calc = registry.get('Calculator')
        >>> # Later in code...
        >>> registry2 = get_global_registry()  # Same instance, instant
        >>> assert registry is registry2
    """
    global _GLOBAL_REGISTRY

    with _GLOBAL_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = ToolRegistry(auto_discover=False)
            _GLOBAL_REGISTRY.auto_discover(use_cache=True)

    return _GLOBAL_REGISTRY


def clear_global_cache() -> None:
    """
    Clear global tool discovery cache and registry singleton.

    Useful for testing or when tools are dynamically added/removed.
    Next call to get_global_registry() will re-discover tools.
    """
    global _DISCOVERED_TOOLS_CACHE, _GLOBAL_REGISTRY
    with _GLOBAL_LOCK:
        _DISCOVERED_TOOLS_CACHE = None
        _GLOBAL_REGISTRY = None
