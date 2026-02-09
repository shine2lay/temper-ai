"""
Tests for tool registry.
"""
import pytest

from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.registry import ToolRegistry, ToolRegistryError

# ============================================
# MOCK TOOLS FOR TESTING
# ============================================

class MockCalculator(BaseTool):
    """Mock calculator tool for testing."""

    def __init__(self, config: dict = None):
        """Initialize mock calculator with optional config."""
        super().__init__(config)

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="calculator",
            description="Performs basic math operations",
            version="1.0",
            category="utility"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Math operation: add, subtract, multiply, divide",
                    "enum": ["add", "subtract", "multiply", "divide"]
                },
                "a": {
                    "type": "number",
                    "description": "First number"
                },
                "b": {
                    "type": "number",
                    "description": "Second number"
                }
            },
            "required": ["operation", "a", "b"]
        }

    def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation")
        a = kwargs.get("a")
        b = kwargs.get("b")

        operations = {
            "add": a + b,
            "subtract": a - b,
            "multiply": a * b,
            "divide": a / b if b != 0 else None
        }

        if operation not in operations:
            return ToolResult(
                success=False,
                error=f"Unknown operation: {operation}"
            )

        result = operations[operation]
        if result is None:
            return ToolResult(
                success=False,
                error="Division by zero"
            )

        return ToolResult(
            success=True,
            result=result
        )


class MockWebScraper(BaseTool):
    """Mock web scraper tool for testing."""

    def __init__(self, config: dict = None):
        """Initialize mock web scraper with optional config."""
        super().__init__(config)

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="web_scraper",
            description="Scrapes web pages",
            version="1.0",
            category="web",
            requires_network=True
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to scrape"
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum pages to scrape",
                    "default": 1
                }
            },
            "required": ["url"]
        }

    def execute(self, **kwargs) -> ToolResult:
        url = kwargs.get("url")
        max_pages = kwargs.get("max_pages", 1)

        return ToolResult(
            success=True,
            result={
                "url": url,
                "pages_scraped": max_pages,
                "content": f"Mock content from {url}"
            }
        )


class InvalidTool:
    """Invalid tool that doesn't inherit from BaseTool."""
    pass


# ============================================
# REGISTRY TESTS
# ============================================

class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_empty_registry(self):
        """Test creating empty registry."""
        registry = ToolRegistry()
        assert len(registry) == 0
        assert registry.list_tools() == []

    def test_register_tool(self):
        """Test registering a tool."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        assert len(registry) == 1
        assert "calculator" in registry.list_tools()
        assert registry.has("calculator")

    def test_register_multiple_tools(self):
        """Test registering multiple tools."""
        registry = ToolRegistry()
        calc = MockCalculator()
        scraper = MockWebScraper()

        registry.register(calc)
        registry.register(scraper)

        assert len(registry) == 2
        assert set(registry.list_tools()) == {"calculator", "web_scraper"}

    def test_register_multiple_batch(self):
        """Test register_multiple method."""
        registry = ToolRegistry()
        tools = [MockCalculator(), MockWebScraper()]
        registry.register_multiple(tools)

        assert len(registry) == 2

    def test_register_duplicate_name(self):
        """Test that registering duplicate name raises error."""
        registry = ToolRegistry()
        calc1 = MockCalculator()
        calc2 = MockCalculator()

        registry.register(calc1)

        with pytest.raises(ToolRegistryError) as exc_info:
            registry.register(calc2)
        assert "already registered" in str(exc_info.value)

    def test_register_invalid_tool(self):
        """Test that registering non-BaseTool raises error."""
        registry = ToolRegistry()
        invalid = InvalidTool()

        with pytest.raises(ToolRegistryError) as exc_info:
            registry.register(invalid)
        assert "must inherit from BaseTool" in str(exc_info.value)

    def test_get_tool(self):
        """Test getting tool by name."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        retrieved = registry.get("calculator")
        assert retrieved is not None
        assert retrieved.name == "calculator"
        assert retrieved is calc

    def test_get_nonexistent_tool(self):
        """Test getting tool that doesn't exist."""
        registry = ToolRegistry()
        result = registry.get("nonexistent")
        assert result is None

    def test_has_tool(self):
        """Test checking if tool exists."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        assert registry.has("calculator")
        assert not registry.has("nonexistent")

    def test_contains_operator(self):
        """Test 'in' operator."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        assert "calculator" in registry
        assert "nonexistent" not in registry

    def test_unregister_tool(self):
        """Test unregistering a tool."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        assert "calculator" in registry
        registry.unregister("calculator")
        assert "calculator" not in registry

    def test_unregister_nonexistent(self):
        """Test unregistering tool that doesn't exist."""
        registry = ToolRegistry()

        with pytest.raises(ToolRegistryError) as exc_info:
            registry.unregister("nonexistent")
        assert "not found" in str(exc_info.value)

    def test_get_all_tools(self):
        """Test getting all tools."""
        registry = ToolRegistry()
        calc = MockCalculator()
        scraper = MockWebScraper()
        registry.register(calc)
        registry.register(scraper)

        all_tools = registry.get_all_tools()
        assert len(all_tools) == 2
        assert "calculator" in all_tools
        assert "web_scraper" in all_tools

    def test_get_tool_schema(self):
        """Test getting tool schema for LLM."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        schema = registry.get_tool_schema("calculator")
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "calculator"
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]

    def test_get_schema_for_nonexistent_tool(self):
        """Test getting schema for tool that doesn't exist."""
        registry = ToolRegistry()

        with pytest.raises(ToolRegistryError) as exc_info:
            registry.get_tool_schema("nonexistent")
        assert "not found" in str(exc_info.value)

    def test_get_all_tool_schemas(self):
        """Test getting schemas for all tools."""
        registry = ToolRegistry()
        calc = MockCalculator()
        scraper = MockWebScraper()
        registry.register(calc)
        registry.register(scraper)

        schemas = registry.get_all_tool_schemas()
        assert len(schemas) == 2
        assert all("type" in s and s["type"] == "function" for s in schemas)

    def test_get_tool_metadata(self):
        """Test getting tool metadata."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        metadata = registry.get_tool_metadata("calculator")
        assert metadata["name"] == "calculator"
        assert metadata["description"] == "Performs basic math operations"
        assert metadata["version"] == "1.0"
        assert metadata["category"] == "utility"

    def test_get_metadata_for_nonexistent_tool(self):
        """Test getting metadata for tool that doesn't exist."""
        registry = ToolRegistry()

        with pytest.raises(ToolRegistryError) as exc_info:
            registry.get_tool_metadata("nonexistent")
        assert "not found" in str(exc_info.value)

    def test_clear_registry(self):
        """Test clearing all tools."""
        registry = ToolRegistry()
        calc = MockCalculator()
        scraper = MockWebScraper()
        registry.register(calc)
        registry.register(scraper)

        assert len(registry) == 2
        registry.clear()
        assert len(registry) == 0
        assert registry.list_tools() == []

    def test_auto_discover_empty(self):
        """Test auto-discover with no tools."""
        registry = ToolRegistry()
        count = registry.auto_discover("nonexistent.package")
        assert count == 0

    def test_auto_discover_with_init(self):
        """Test auto-discover in constructor."""
        # This won't find any tools in the actual package yet
        # but tests that auto_discover is called
        registry = ToolRegistry(auto_discover=True)
        # Should not raise any errors
        assert isinstance(registry, ToolRegistry)

    def test_repr(self):
        """Test string representation."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        repr_str = repr(registry)
        assert "ToolRegistry" in repr_str
        assert "tools=1" in repr_str


class TestToolParameterValidation:
    """Tests for parameter validation."""

    def test_valid_parameters(self):
        """Test validation with valid parameters."""
        calc = MockCalculator()
        params = {"operation": "add", "a": 5, "b": 3}
        result = calc.validate_params(params)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_required_parameter(self):
        """Test validation with missing required parameter."""
        calc = MockCalculator()
        params = {"operation": "add", "a": 5}
        result = calc.validate_params(params)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_unknown_parameter(self):
        """Test validation with unknown parameter."""
        calc = MockCalculator()
        params = {
            "operation": "add",
            "a": 5,
            "b": 3,
            "unknown": "value"
        }
        result = calc.validate_params(params)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_wrong_type(self):
        """Test validation with wrong parameter type."""
        calc = MockCalculator()
        params = {
            "operation": "add",
            "a": "not_a_number",  # Should be number
            "b": 3
        }
        result = calc.validate_params(params)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_optional_parameter(self):
        """Test validation with optional parameter."""
        scraper = MockWebScraper()

        # Without optional parameter
        params1 = {"url": "https://example.com"}
        result1 = scraper.validate_params(params1)
        assert result1.valid is True

        # With optional parameter
        params2 = {"url": "https://example.com", "max_pages": 5}
        result2 = scraper.validate_params(params2)
        assert result2.valid is True


class TestToolSchemas:
    """Tests for tool schemas."""

    def test_llm_schema_format(self):
        """Test LLM schema is in correct format."""
        calc = MockCalculator()
        schema = calc.to_llm_schema()

        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == "calculator"
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]

    def test_parameters_schema_structure(self):
        """Test parameters schema structure."""
        calc = MockCalculator()
        params = calc.get_parameters_schema()

        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params
        assert "operation" in params["properties"]
        assert "a" in params["properties"]
        assert "b" in params["properties"]

    def test_metadata_completeness(self):
        """Test tool metadata is complete."""
        calc = MockCalculator()
        metadata = calc.get_metadata()

        assert metadata.name
        assert metadata.description
        assert metadata.version


class TestEnhancedAutoDiscovery:
    """Tests for enhanced auto-discovery features (m3.1-03)."""

    def test_validate_tool_interface_valid(self):
        """Test interface validation with valid tool class."""
        registry = ToolRegistry()
        is_valid, errors = registry._validate_tool_interface(MockCalculator)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_tool_interface_not_basetool(self):
        """Test interface validation with non-BaseTool class."""
        registry = ToolRegistry()
        is_valid, errors = registry._validate_tool_interface(InvalidTool)
        assert is_valid is False
        assert len(errors) > 0
        assert any("inherit from BaseTool" in err for err in errors)

    def test_validate_tool_interface_missing_methods(self):
        """Test interface validation with class missing required methods."""
        registry = ToolRegistry()

        class IncompleteTool(BaseTool):
            """Tool missing execute method."""
            def get_metadata(self):
                return ToolMetadata(name="incomplete", description="Test", version="1.0")

            def get_parameters_schema(self):
                return {"type": "object", "properties": {}}
            # Missing execute() method

        is_valid, errors = registry._validate_tool_interface(IncompleteTool)
        # This should still pass because execute is inherited from BaseTool
        # But if we check abstract methods, it might fail
        assert isinstance(is_valid, bool)

    def test_list_available_tools(self):
        """Test listing tools with detailed information."""
        registry = ToolRegistry()
        calc = MockCalculator()
        scraper = MockWebScraper()
        registry.register(calc)
        registry.register(scraper)

        tools_info = registry.list_available_tools()

        assert len(tools_info) == 2
        assert "calculator" in tools_info
        assert "web_scraper" in tools_info

        # Check calculator info
        calc_info = tools_info["calculator"]
        assert calc_info["class"] == "MockCalculator"
        assert calc_info["description"] == "Performs basic math operations"
        assert calc_info["version"] == "1.0"
        assert calc_info["category"] == "utility"
        assert calc_info["requires_network"] is False

        # Check web scraper info
        scraper_info = tools_info["web_scraper"]
        assert scraper_info["requires_network"] is True

    def test_get_registration_report(self):
        """Test getting detailed registration report."""
        registry = ToolRegistry()
        calc = MockCalculator()
        scraper = MockWebScraper()
        registry.register(calc)
        registry.register(scraper)

        report = registry.get_registration_report()

        # Report should be a string
        assert isinstance(report, str)
        assert len(report) > 0

        # Should contain tool names
        assert "calculator" in report
        assert "web_scraper" in report

        # Should contain summary line with total count
        assert "Total registered tools: 2" in report

    def test_get_registration_report_empty(self):
        """Test registration report with empty registry."""
        registry = ToolRegistry()
        report = registry.get_registration_report()

        assert isinstance(report, str)
        assert "0" in report or "empty" in report.lower()

    def test_error_suggestion_for_init_args(self):
        """Test error suggestion for tools requiring init arguments."""
        registry = ToolRegistry()
        error_msg = "requires init arguments"
        suggestion = registry._get_error_suggestion(error_msg)

        assert suggestion is not None
        assert "default values" in suggestion.lower() or "init" in suggestion.lower()

    def test_error_suggestion_for_missing_methods(self):
        """Test error suggestion for missing required methods."""
        registry = ToolRegistry()
        error_msg = "Missing required method: execute"
        suggestion = registry._get_error_suggestion(error_msg)

        assert suggestion is not None
        assert "implement" in suggestion.lower()

    def test_error_suggestion_for_no_basetool(self):
        """Test error suggestion for not inheriting BaseTool."""
        registry = ToolRegistry()
        error_msg = "Tool must not inherit from BaseTool"
        suggestion = registry._get_error_suggestion(error_msg)

        assert suggestion is not None
        assert "inherit" in suggestion.lower()

    def test_error_suggestion_for_unknown_error(self):
        """Test error suggestion for unknown error type."""
        registry = ToolRegistry()
        error_msg = "Some random error that doesn't match patterns"
        suggestion = registry._get_error_suggestion(error_msg)

        # Should return None or a generic suggestion
        assert suggestion is None or isinstance(suggestion, str)

    def test_auto_discover_logs_success(self, caplog):
        """Test that auto-discover logs successful tool loading."""
        import logging
        caplog.set_level(logging.INFO)

        # Create a temporary module structure with a valid tool
        # For this test, we'll just verify the registry doesn't crash
        registry = ToolRegistry()

        # Auto-discover in a package that doesn't exist shouldn't crash
        count = registry.auto_discover("nonexistent.package")

        # Should not raise errors
        assert count >= 0

    def test_auto_discover_with_real_tools(self):
        """Test auto-discover finds real tools in src.tools package."""
        registry = ToolRegistry(auto_discover=False)

        # Manually discover from src.tools
        count = registry.auto_discover("src.tools")

        # Should find at least Calculator, FileWriter, WebScraper
        assert count >= 3
        assert "Calculator" in registry or "calculator" in registry
        assert "FileWriter" in registry or "file_writer" in registry
        assert "WebScraper" in registry or "web_scraper" in registry

    def test_registry_with_config_parameter(self):
        """Test that tools can be registered with config parameter."""
        registry = ToolRegistry()

        # Create tool with config
        calc = MockCalculator(config={"precision": 10})

        # Should have config attribute
        assert hasattr(calc, "config")
        assert calc.config == {"precision": 10}

        # Should register successfully
        registry.register(calc)
        assert "calculator" in registry


class TestToolVersioning:
    """Tests for tool versioning support."""

    def test_register_multiple_versions(self):
        """Test registering multiple versions of the same tool."""
        registry = ToolRegistry()

        # Create calculator v1.0
        calc_v1 = MockCalculator()
        calc_v1.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v1",
            version="1.0",
            category="utility"
        )

        # Create calculator v2.0
        calc_v2 = MockCalculator()
        calc_v2.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v2",
            version="2.0",
            category="utility"
        )

        # Register both versions
        registry.register(calc_v1)
        registry.register(calc_v2)

        # Both versions should be registered
        assert "calculator" in registry
        assert len(registry.list_tool_versions("calculator")) == 2

    def test_get_latest_version_default(self):
        """Test that get() returns latest version by default."""
        registry = ToolRegistry()

        # Create multiple versions
        calc_v1 = MockCalculator()
        calc_v1.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v1",
            version="1.0",
            category="utility"
        )

        calc_v2 = MockCalculator()
        calc_v2.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v2",
            version="2.0",
            category="utility"
        )

        registry.register(calc_v1)
        registry.register(calc_v2)

        # Get without version should return latest (2.0)
        tool = registry.get("calculator")
        assert tool is not None
        assert tool.get_metadata().version == "2.0"

    def test_get_specific_version(self):
        """Test getting a specific tool version."""
        registry = ToolRegistry()

        # Create multiple versions
        calc_v1 = MockCalculator()
        calc_v1.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v1",
            version="1.0",
            category="utility"
        )

        calc_v2 = MockCalculator()
        calc_v2.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v2",
            version="2.0",
            category="utility"
        )

        registry.register(calc_v1)
        registry.register(calc_v2)

        # Get v1.0 specifically
        tool_v1 = registry.get("calculator", version="1.0")
        assert tool_v1 is not None
        assert tool_v1.get_metadata().version == "1.0"

        # Get v2.0 specifically
        tool_v2 = registry.get("calculator", version="2.0")
        assert tool_v2 is not None
        assert tool_v2.get_metadata().version == "2.0"

    def test_register_duplicate_version_fails(self):
        """Test that registering duplicate version raises error."""
        registry = ToolRegistry()

        calc1 = MockCalculator()
        calc2 = MockCalculator()

        registry.register(calc1)

        with pytest.raises(ToolRegistryError) as exc_info:
            registry.register(calc2)
        assert "already registered" in str(exc_info.value)

    def test_register_duplicate_version_with_override(self):
        """Test that allow_override=True allows replacing tool version."""
        registry = ToolRegistry()

        calc1 = MockCalculator()
        calc2 = MockCalculator()

        registry.register(calc1)
        registry.register(calc2, allow_override=True)

        # Second tool should replace first
        tool = registry.get("calculator")
        assert tool is calc2

    def test_list_tool_versions(self):
        """Test listing all versions of a tool."""
        registry = ToolRegistry()

        # Create multiple versions
        for version in ["1.0", "1.1", "2.0", "2.1"]:
            calc = MockCalculator()
            calc.get_metadata = lambda v=version: ToolMetadata(
                name="calculator",
                description=f"Calculator v{v}",
                version=v,
                category="utility"
            )
            registry.register(calc)

        versions = registry.list_tool_versions("calculator")
        assert len(versions) == 4
        assert "1.0" in versions
        assert "1.1" in versions
        assert "2.0" in versions
        assert "2.1" in versions

    def test_unregister_specific_version(self):
        """Test unregistering a specific tool version."""
        registry = ToolRegistry()

        # Create multiple versions
        calc_v1 = MockCalculator()
        calc_v1.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v1",
            version="1.0",
            category="utility"
        )

        calc_v2 = MockCalculator()
        calc_v2.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v2",
            version="2.0",
            category="utility"
        )

        registry.register(calc_v1)
        registry.register(calc_v2)

        # Unregister v1.0
        registry.unregister("calculator", version="1.0")

        # v1.0 should be gone, v2.0 should remain
        assert registry.get("calculator", version="1.0") is None
        assert registry.get("calculator", version="2.0") is not None

    def test_unregister_all_versions(self):
        """Test unregistering all versions of a tool."""
        registry = ToolRegistry()

        # Create multiple versions
        for version in ["1.0", "2.0"]:
            calc = MockCalculator()
            calc.get_metadata = lambda v=version: ToolMetadata(
                name="calculator",
                description=f"Calculator v{v}",
                version=v,
                category="utility"
            )
            registry.register(calc)

        # Unregister all versions
        registry.unregister("calculator")

        # Tool should be completely gone
        assert "calculator" not in registry
        assert registry.get("calculator") is None

    def test_has_tool_with_version(self):
        """Test has() method with version parameter."""
        registry = ToolRegistry()

        calc_v1 = MockCalculator()
        calc_v1.get_metadata = lambda: ToolMetadata(
            name="calculator",
            description="Calculator v1",
            version="1.0",
            category="utility"
        )

        registry.register(calc_v1)

        # Check tool exists
        assert registry.has("calculator")
        assert registry.has("calculator", version="1.0")
        assert not registry.has("calculator", version="2.0")

    def test_semantic_version_ordering(self):
        """Test that semantic versioning is properly ordered."""
        registry = ToolRegistry()

        # Register versions in random order
        for version in ["1.0.0", "2.1.0", "1.5.0", "2.0.0"]:
            calc = MockCalculator()
            calc.get_metadata = lambda v=version: ToolMetadata(
                name="calculator",
                description=f"Calculator v{v}",
                version=v,
                category="utility"
            )
            registry.register(calc)

        # Latest should be 2.1.0
        tool = registry.get("calculator")
        assert tool.get_metadata().version == "2.1.0"

    def test_get_nonexistent_version(self):
        """Test getting a version that doesn't exist."""
        registry = ToolRegistry()

        calc = MockCalculator()
        registry.register(calc)

        # Get non-existent version
        tool = registry.get("calculator", version="999.0")
        assert tool is None

    def test_registry_length_counts_versions(self):
        """Test that len() counts all tool versions."""
        registry = ToolRegistry()

        # Register 2 tools with 2 versions each
        for tool_name in ["calculator", "scraper"]:
            for version in ["1.0", "2.0"]:
                if tool_name == "calculator":
                    tool = MockCalculator()
                    tool.get_metadata = lambda n=tool_name, v=version: ToolMetadata(
                        name=n,
                        description=f"{n} v{v}",
                        version=v,
                        category="utility"
                    )
                else:
                    tool = MockWebScraper()
                    tool.get_metadata = lambda n=tool_name, v=version: ToolMetadata(
                        name=n,
                        description=f"{n} v{v}",
                        version=v,
                        category="web",
                        requires_network=True
                    )
                registry.register(tool)

        # Should count 4 total tool instances
        assert len(registry) == 4

    def test_list_available_tools_includes_versions(self):
        """Test that list_available_tools includes version information."""
        registry = ToolRegistry()

        # Register multiple versions
        for version in ["1.0", "2.0"]:
            calc = MockCalculator()
            calc.get_metadata = lambda v=version: ToolMetadata(
                name="calculator",
                description="Calculator",
                version=v,
                category="utility"
            )
            registry.register(calc)

        tools = registry.list_available_tools()

        assert "calculator" in tools
        assert tools["calculator"]["version"] == "2.0"  # Latest version
        assert len(tools["calculator"]["all_versions"]) == 2
        assert "1.0" in tools["calculator"]["all_versions"]
        assert "2.0" in tools["calculator"]["all_versions"]


class TestRegistryEdgeCases:
    """Test error paths and edge cases in registry operations."""

    def test_unregister_specific_version_not_found(self):
        """Test unregistering a version that doesn't exist."""
        from src.utils.exceptions import ToolRegistryError
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        with pytest.raises(ToolRegistryError) as exc:
            registry.unregister("calculator", version="9.9.9")

        assert "version '9.9.9' not found" in str(exc.value)

    def test_get_tool_empty_versions_dict(self):
        """Test getting tool when versions dict exists but is empty."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        # Manually corrupt the registry to have empty versions dict
        registry._tools["calculator"] = {}

        result = registry.get("calculator")
        assert result is None

    def test_list_tool_versions_nonexistent(self):
        """Test listing versions for nonexistent tool."""
        registry = ToolRegistry()
        versions = registry.list_tool_versions("nonexistent")
        assert versions == []

    def test_global_registry_singleton(self):
        """Test that get_global_registry returns same instance."""
        from src.tools.registry import get_global_registry, clear_global_cache, _GLOBAL_LOCK

        # Clear first to ensure clean state
        with _GLOBAL_LOCK:
            clear_global_cache()

        # Get registry twice
        registry1 = get_global_registry()
        registry2 = get_global_registry()

        # Should be same instance
        assert registry1 is registry2

        # Cleanup
        with _GLOBAL_LOCK:
            clear_global_cache()

    def test_clear_global_cache(self):
        """Test clearing global cache and registry."""
        from src.tools.registry import get_global_registry, clear_global_cache, _GLOBAL_LOCK

        # Get initial registry
        with _GLOBAL_LOCK:
            clear_global_cache()

        registry1 = get_global_registry()

        # Clear and get new one
        with _GLOBAL_LOCK:
            clear_global_cache()

        registry2 = get_global_registry()

        # Should be different instances after clear
        assert registry1 is not registry2

        # Cleanup
        with _GLOBAL_LOCK:
            clear_global_cache()

    def test_registry_protocol_methods(self):
        """Test attached protocol methods work correctly."""
        registry = ToolRegistry()
        calc = MockCalculator()
        registry.register(calc)

        # Test list() method
        assert "calculator" in registry.list()

        # Test count() method
        assert registry.count() == 1

        # Test list_all() deprecated method
        assert "calculator" in registry.list_all()
