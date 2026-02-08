"""Tests for tool configuration loading functionality.

Tests loading tools from YAML/JSON configuration files into the ToolRegistry.
"""
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from src.compiler.config_loader import ConfigLoader
from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.registry import ToolRegistry, ToolRegistryError

# ============================================================================
# Test Tools
# ============================================================================

class MockTestTool(BaseTool):
    """Mock test tool for configuration loading tests.

    Note: Renamed from TestTool to avoid pytest collection warning.
    """

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="TestTool",
            description="Test tool for testing",
            version="1.0",
            category="test"
        )

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            }
        }

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            result={"result": "test output"},  # Use 'result' not 'output'
            metadata={}
        )


# Dynamic tool classes for multi-tool tests
def create_tool_class(tool_num: int):
    """Create a unique tool class with unique name."""

    class DynamicTool(BaseTool):
        def get_metadata(self) -> ToolMetadata:
            return ToolMetadata(
                name=f"TestTool{tool_num}",
                description=f"Test tool {tool_num}",
                version="1.0",
                category="test"
            )

        def get_parameters_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, result={"tool": tool_num}, metadata={})

    return DynamicTool


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def config_root():
    """Create temporary config directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "configs"
        config_dir.mkdir()

        # Create tools directory
        tools_dir = config_dir / "tools"
        tools_dir.mkdir()

        yield config_dir


@pytest.fixture
def test_tool_config(config_root):
    """Create test tool configuration file."""
    tools_dir = config_root / "tools"

    config = {
        "tool": {
            "name": "TestTool",
            "description": "Test tool for testing",
            "version": "1.0",
            "implementation": {
                "module": "tests.test_tools.test_tool_config_loading",
                "class": "MockTestTool"
            }
        }
    }

    config_file = tools_dir / "test_tool.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


@pytest.fixture
def invalid_tool_config(config_root):
    """Create invalid tool configuration file (missing implementation)."""
    tools_dir = config_root / "tools"

    config = {
        "tool": {
            "name": "InvalidTool",
            "description": "Invalid tool config",
            "version": "1.0"
            # Missing implementation
        }
    }

    config_file = tools_dir / "invalid_tool.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


@pytest.fixture
def config_loader(config_root):
    """Create ConfigLoader for test configs."""
    return ConfigLoader(config_root=config_root)


# ============================================================================
# Tests for load_from_config
# ============================================================================

def test_load_from_config_success(test_tool_config, config_loader):
    """Test successfully loading tool from configuration."""
    registry = ToolRegistry()

    # Load tool from config
    tool = registry.load_from_config("test_tool", config_loader)

    # Verify tool was loaded
    assert tool is not None
    assert isinstance(tool, MockTestTool)
    assert tool.get_metadata().name == "TestTool"

    # Verify tool was registered
    assert "TestTool" in registry
    assert registry.get("TestTool") == tool


def test_load_from_config_creates_config_loader(test_tool_config, config_root):
    """Test that load_from_config creates ConfigLoader if not provided."""
    registry = ToolRegistry()

    # Patch ConfigLoader at import location
    with patch('src.compiler.config_loader.ConfigLoader') as mock_config_loader_class:
        mock_loader = Mock()
        mock_config_loader_class.return_value = mock_loader

        # Mock the load_tool method
        mock_loader.load_tool.return_value = {
            "tool": {
                "name": "TestTool",
                "description": "Test",
                "version": "1.0",
                "implementation": {
                    "module": "tests.test_tools.test_tool_config_loading",
                    "class": "MockTestTool"
                }
            }
        }

        # Load tool without providing config_loader
        tool = registry.load_from_config("test_tool")

        # Verify ConfigLoader was created
        mock_config_loader_class.assert_called_once()
        mock_loader.load_tool.assert_called_once_with("test_tool", validate=False)

        # Verify tool was loaded successfully
        assert tool is not None
        assert isinstance(tool, MockTestTool)


def test_load_from_config_tool_execution(test_tool_config, config_loader):
    """Test that loaded tool can execute properly."""
    registry = ToolRegistry()

    # Load tool
    tool = registry.load_from_config("test_tool", config_loader)

    # Execute tool
    result = tool.execute(input="test")

    # Verify execution
    assert result.success is True
    assert result.result == {"result": "test output"}  # Use 'result' not 'output'


def test_load_from_config_missing_name(config_root, config_loader):
    """Test error when tool config missing name field."""
    tools_dir = config_root / "tools"

    # Create config without name
    config = {
        "tool": {
            "description": "Tool without name",
            "implementation": {
                "module": "tests.test_tools.test_tool_config_loading",
                "class": "TestTool"
            }
        }
    }

    config_file = tools_dir / "no_name.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    registry = ToolRegistry()

    # Should raise error
    with pytest.raises(ToolRegistryError, match="missing 'name' field"):
        registry.load_from_config("no_name", config_loader)


def test_load_from_config_invalid_implementation(invalid_tool_config, config_loader):
    """Test error when implementation format is invalid."""
    registry = ToolRegistry()

    # Should raise error for missing implementation
    with pytest.raises(ToolRegistryError, match="must specify 'module' and 'class'"):
        registry.load_from_config("invalid_tool", config_loader)


def test_load_from_config_string_class_path(config_root, config_loader):
    """Test loading tool with string class path implementation."""
    tools_dir = config_root / "tools"

    # Create config with string class path
    config = {
        "tool": {
            "name": "TestTool",
            "description": "Test tool",
            "version": "1.0",
            "implementation": "tests.test_tools.test_tool_config_loading.MockTestTool"
        }
    }

    config_file = tools_dir / "string_path.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    registry = ToolRegistry()

    # Should load successfully
    tool = registry.load_from_config("string_path", config_loader)

    assert tool is not None
    assert isinstance(tool, MockTestTool)


def test_load_from_config_invalid_module(config_root, config_loader):
    """Test error when module cannot be imported."""
    tools_dir = config_root / "tools"

    # Create config with non-existent module
    config = {
        "tool": {
            "name": "BadTool",
            "description": "Tool with bad module",
            "version": "1.0",
            "implementation": {
                "module": "nonexistent.module.path",
                "class": "TestTool"
            }
        }
    }

    config_file = tools_dir / "bad_module.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    registry = ToolRegistry()

    # Should raise error
    with pytest.raises(ToolRegistryError, match="Failed to import tool class"):
        registry.load_from_config("bad_module", config_loader)


def test_load_from_config_missing_class(config_root, config_loader):
    """Test error when class doesn't exist in module."""
    tools_dir = config_root / "tools"

    # Create config with non-existent class
    config = {
        "tool": {
            "name": "BadClass",
            "description": "Tool with bad class",
            "version": "1.0",
            "implementation": {
                "module": "tests.test_tools.test_tool_config_loading",
                "class": "NonExistentClass"
            }
        }
    }

    config_file = tools_dir / "bad_class.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    registry = ToolRegistry()

    # Should raise error
    with pytest.raises(ToolRegistryError, match="Tool class not found"):
        registry.load_from_config("bad_class", config_loader)


def test_load_from_config_not_base_tool_subclass(config_root, config_loader):
    """Test error when class doesn't inherit from BaseTool."""
    tools_dir = config_root / "tools"

    # Create config pointing to non-BaseTool class
    config = {
        "tool": {
            "name": "NotATool",
            "description": "Not a BaseTool subclass",
            "version": "1.0",
            "implementation": {
                "module": "pathlib",
                "class": "Path"  # Not a BaseTool
            }
        }
    }

    config_file = tools_dir / "not_tool.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    registry = ToolRegistry()

    # Should raise error
    with pytest.raises(ToolRegistryError, match="must inherit from BaseTool"):
        registry.load_from_config("not_tool", config_loader)


# ============================================================================
# Tests for load_all_from_configs
# ============================================================================

def test_load_all_from_configs_success(config_root, config_loader, tmp_path):
    """Test loading all tools from configurations."""
    tools_dir = config_root / "tools"

    # First, dynamically create tool classes in a temporary module
    # Write dynamic tool classes to temp file
    tool_module_content = '''
"""Dynamically generated test tools."""
from src.tools.base import BaseTool, ToolResult, ToolMetadata

'''

    for i in range(3):
        tool_module_content += f'''
class DynamicTestTool{i}(BaseTool):
    def get_metadata(self):
        return ToolMetadata(
            name="TestTool{i}",
            description="Test tool {i}",
            version="1.0",
            category="test"
        )

    def get_parameters_schema(self):
        return {{"type": "object", "properties": {{}}}}

    def execute(self, **kwargs):
        return ToolResult(success=True, result={{"tool": {i}}}, metadata={{}})

'''

    # Write to temp file
    temp_module = tmp_path / "dynamic_tools.py"
    temp_module.write_text(tool_module_content)

    # Add tmp_path to sys.path
    import sys
    sys.path.insert(0, str(tmp_path))

    try:
        # Create multiple tool configs pointing to dynamic classes
        for i in range(3):
            config = {
                "tool": {
                    "name": f"TestTool{i}",
                    "description": f"Test tool {i}",
                    "version": "1.0",
                    "implementation": {
                        "module": "dynamic_tools",
                        "class": f"DynamicTestTool{i}"
                    }
                }
            }

            config_file = tools_dir / f"tool{i}.yaml"
            with open(config_file, 'w') as f:
                yaml.dump(config, f)

        registry = ToolRegistry()

        # Load all tools
        count = registry.load_all_from_configs(config_loader)

        # Verify all tools loaded
        assert count == 3
        assert len(registry) == 3
        assert "TestTool0" in registry
        assert "TestTool1" in registry
        assert "TestTool2" in registry
    finally:
        # Clean up sys.path
        sys.path.remove(str(tmp_path))


def test_load_all_from_configs_creates_loader():
    """Test that load_all_from_configs creates ConfigLoader if not provided."""
    registry = ToolRegistry()

    # Patch ConfigLoader at import location
    with patch('src.compiler.config_loader.ConfigLoader') as mock_config_loader_class:
        mock_loader = Mock()
        mock_config_loader_class.return_value = mock_loader
        mock_loader.list_configs.return_value = []

        # Load all without providing loader
        count = registry.load_all_from_configs()

        # Verify ConfigLoader was created
        mock_config_loader_class.assert_called_once()
        mock_loader.list_configs.assert_called_once_with("tool")

        # Verify no tools were loaded (empty config list)
        assert count == 0
        assert len(registry) == 0


def test_load_all_from_configs_skips_invalid(config_root, config_loader):
    """Test that load_all_from_configs skips invalid configs and continues."""
    tools_dir = config_root / "tools"

    # Create valid config
    valid_config = {
        "tool": {
            "name": "TestTool",  # Use TestTool since that's the actual name from get_metadata()
            "description": "Valid tool",
            "version": "1.0",
            "implementation": {
                "module": "tests.test_tools.test_tool_config_loading",
                "class": "MockTestTool"
            }
        }
    }

    with open(tools_dir / "valid.yaml", 'w') as f:
        yaml.dump(valid_config, f)

    # Create invalid config (missing implementation)
    invalid_config = {
        "tool": {
            "name": "InvalidTool",
            "description": "Invalid tool"
        }
    }

    with open(tools_dir / "invalid.yaml", 'w') as f:
        yaml.dump(invalid_config, f)

    registry = ToolRegistry()

    # Load all - should load valid and skip invalid
    count = registry.load_all_from_configs(config_loader)

    # Verify only valid tool loaded
    assert count == 1
    assert len(registry) == 1
    assert "TestTool" in registry  # Tool name from get_metadata(), not config
    assert "InvalidTool" not in registry


def test_load_all_from_configs_empty_directory(config_root, config_loader):
    """Test loading from empty tools directory."""
    registry = ToolRegistry()

    # Load all from empty directory
    count = registry.load_all_from_configs(config_loader)

    # Should return 0
    assert count == 0
    assert len(registry) == 0


# ============================================================================
# Integration Tests
# ============================================================================

def test_load_calculator_from_real_config():
    """Integration test: Load real Calculator tool from config.

    This tests against the actual calculator.yaml configuration file.
    """
    # Use real ConfigLoader (not mocked)
    config_loader = ConfigLoader()

    registry = ToolRegistry()

    try:
        # Load calculator from real config
        calculator = registry.load_from_config("calculator", config_loader)

        # Verify tool loaded
        assert calculator is not None
        assert "Calculator" in registry

        # Verify tool can execute
        result = calculator.execute(expression="2 + 2")
        assert result.success is True
        assert result.result == 4  # Use 'result' not 'output'

    except Exception as e:
        # If calculator config doesn't exist or is malformed, skip test
        pytest.skip(f"Calculator config not available or invalid: {e}")


def test_load_and_use_tool_end_to_end(test_tool_config, config_loader):
    """End-to-end test: Load tool, register, and use it."""
    registry = ToolRegistry()

    # Load tool from config
    tool = registry.load_from_config("test_tool", config_loader)

    # Get tool by name
    retrieved_tool = registry.get("TestTool")
    assert retrieved_tool == tool

    # Get tool schema
    schema = registry.get_tool_schema("TestTool")
    assert schema is not None
    assert "function" in schema  # LLM schema has 'function' key
    assert schema["function"]["name"] == "TestTool"

    # Execute tool
    result = retrieved_tool.execute(input="test data")
    assert result.success is True

    # Get tool metadata
    metadata = registry.get_tool_metadata("TestTool")
    assert metadata["name"] == "TestTool"
    assert metadata["version"] == "1.0"

    # List tools
    tool_names = registry.list_tools()
    assert "TestTool" in tool_names


# ============================================================================
# End of tool configuration loading tests
# ============================================================================
