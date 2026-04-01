"""Tests for tool loader."""

from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.loader import load_tools


class TestLoadTools:
    def test_bare_string(self):
        tools = load_tools(["Calculator"], TOOL_CLASSES)
        assert "Calculator" in tools
        assert tools["Calculator"].name == "Calculator"

    def test_dict_with_name(self):
        tools = load_tools([{"name": "Calculator"}], TOOL_CLASSES)
        assert "Calculator" in tools

    def test_dict_with_config(self):
        tools = load_tools(
            [{"name": "FileWriter", "config": {"allowed_root": "/tmp"}}],
            TOOL_CLASSES,
        )
        assert "FileWriter" in tools
        assert tools["FileWriter"].config["allowed_root"] == "/tmp"

    def test_multiple_tools(self):
        tools = load_tools(["Calculator", "Bash", {"name": "FileWriter"}], TOOL_CLASSES)
        assert len(tools) == 3
        assert "Calculator" in tools
        assert "Bash" in tools
        assert "FileWriter" in tools

    def test_unknown_tool_skipped(self):
        tools = load_tools(["Calculator", "NonExistent"], TOOL_CLASSES)
        assert "Calculator" in tools
        assert "NonExistent" not in tools
        assert len(tools) == 1

    def test_empty_list(self):
        tools = load_tools([], TOOL_CLASSES)
        assert tools == {}

    def test_only_requested_tools_loaded(self):
        """Requesting one tool doesn't load the whole registry."""
        tools = load_tools(["Calculator"], TOOL_CLASSES)
        assert len(tools) == 1
        assert "Bash" not in tools
        assert "FileWriter" not in tools


class TestResolveSpec:
    def test_mixed_formats(self):
        specs = [
            "Calculator",
            {"name": "Bash"},
            {"name": "FileWriter", "config": {"allowed_root": "/workspace"}},
        ]
        tools = load_tools(specs, TOOL_CLASSES)
        assert len(tools) == 3
        assert tools["FileWriter"].config["allowed_root"] == "/workspace"
        assert tools["Bash"].config == {}
        assert tools["Calculator"].config == {}
