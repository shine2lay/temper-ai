"""Tests for CLI memory commands."""

import os
import tempfile

import yaml
from click.testing import CliRunner

from temper_ai.interfaces.cli.memory_commands import memory_group
from temper_ai.memory.constants import MEMORY_TYPE_EPISODIC, MEMORY_TYPE_PROCEDURAL


def _runner():
    return CliRunner()


class TestListCommand:
    """Tests for 'memory list' command."""

    def test_list_no_memories(self):
        result = _runner().invoke(memory_group, ["list"])
        assert result.exit_code == 0
        assert "No memories found" in result.output

    def test_list_with_memories(self):
        runner = _runner()
        # Add a memory first
        runner.invoke(memory_group, [
            "add", "--type", "episodic", "--content", "test memory",
        ])
        # In-memory adapter creates new instance per invocation, so list is empty
        result = runner.invoke(memory_group, ["list"])
        assert result.exit_code == 0


class TestAddCommand:
    """Tests for 'memory add' command."""

    def test_add_with_content_flag(self):
        result = _runner().invoke(memory_group, [
            "add", "--type", "episodic", "--content", "hello world",
        ])
        assert result.exit_code == 0
        assert "Memory stored" in result.output

    def test_add_interactive(self):
        result = _runner().invoke(
            memory_group,
            ["add", "--type", "procedural"],
            input="interactive content\n",
        )
        assert result.exit_code == 0
        assert "Memory stored" in result.output


class TestSearchCommand:
    """Tests for 'memory search' command."""

    def test_search_with_query(self):
        result = _runner().invoke(memory_group, [
            "search", "--query", "test",
        ])
        assert result.exit_code == 0

    def test_search_no_results(self):
        result = _runner().invoke(memory_group, [
            "search", "--query", "nonexistent-query-xyz",
        ])
        assert result.exit_code == 0
        assert "No matching memories found" in result.output


class TestClearCommand:
    """Tests for 'memory clear' command."""

    def test_clear_requires_confirm(self):
        result = _runner().invoke(memory_group, ["clear"])
        assert result.exit_code != 0

    def test_clear_with_confirm(self):
        result = _runner().invoke(memory_group, ["clear", "--confirm"])
        assert result.exit_code == 0
        assert "Cleared" in result.output


class TestSeedCommand:
    """Tests for 'memory seed' command."""

    def test_seed_from_file(self):
        seed_data = {
            "memories": [
                {
                    "scope": {
                        "tenant_id": "default",
                        "workflow_name": "wf",
                        "agent_name": "ag",
                    },
                    "entries": [
                        {"content": "memory one", "type": MEMORY_TYPE_EPISODIC},
                        {"content": "memory two", "type": MEMORY_TYPE_PROCEDURAL},
                    ],
                }
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(seed_data, f)
            tmp_path = f.name

        try:
            result = _runner().invoke(memory_group, ["seed", tmp_path])
            assert result.exit_code == 0
            assert "Seeded 2 memories" in result.output
        finally:
            os.unlink(tmp_path)

    def test_seed_invalid_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump({"no_memories_key": []}, f)
            tmp_path = f.name

        try:
            result = _runner().invoke(memory_group, ["seed", tmp_path])
            assert result.exit_code != 0
        finally:
            os.unlink(tmp_path)
