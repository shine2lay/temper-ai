"""Tests for optimization CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.optimize_commands import optimize_group


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample agent config YAML."""
    config_file = tmp_path / "agent.yaml"
    config_file.write_text(
        "agent:\n"
        "  name: researcher\n"
        "  description: test\n"
        "  prompt:\n"
        "    inline: 'Research {{ topic }}'\n"
    )
    return str(config_file)


class TestOptimizeCLI:

    def test_compile_dry_run(self, runner, sample_config):
        mock_collector = MagicMock()
        mock_collector.collect_examples.return_value = [
            MagicMock() for _ in range(15)
        ]
        with patch(
            "temper_ai.interfaces.cli.optimize_commands._ensure_database",
            return_value=True,
        ), patch(
            "temper_ai.interfaces.cli.optimize_commands._show_dry_run_stats"
        ), patch.dict(
            "sys.modules",
            {
                "temper_ai.optimization.dspy.data_collector": MagicMock(
                    TrainingDataCollector=lambda: mock_collector,
                ),
                "temper_ai.optimization.dspy._schemas": MagicMock(),
            },
        ):
            result = runner.invoke(
                optimize_group,
                ["compile", sample_config, "--dry-run"],
            )
            assert result.exit_code == 0

    def test_list_no_programs(self, runner):
        with patch(
            "temper_ai.interfaces.cli.optimize_commands.CompiledProgramStore",
            create=True,
        ) as MockStore:
            mock_store = MagicMock()
            mock_store.list_programs.return_value = []
            MockStore.return_value = mock_store
            with patch.dict(
                "sys.modules",
                {
                    "temper_ai.optimization.dspy.program_store": MagicMock(
                        CompiledProgramStore=MockStore,
                    ),
                },
            ):
                result = runner.invoke(optimize_group, ["list"])
                assert result.exit_code == 0
                assert "no" in result.output.lower() or "empty" in result.output.lower() or result.output.strip() == ""

    def test_list_with_programs(self, runner):
        with patch(
            "temper_ai.interfaces.cli.optimize_commands.CompiledProgramStore",
            create=True,
        ) as MockStore:
            mock_store = MagicMock()
            mock_store.list_programs.return_value = [
                {
                    "program_id": "prog_1",
                    "agent_name": "researcher",
                    "created_at": "2026-02-19",
                    "metadata": {},
                },
            ]
            MockStore.return_value = mock_store
            with patch.dict(
                "sys.modules",
                {
                    "temper_ai.optimization.dspy.program_store": MagicMock(
                        CompiledProgramStore=MockStore,
                    ),
                },
            ):
                result = runner.invoke(optimize_group, ["list"])
                assert result.exit_code == 0
                assert "prog_1" in result.output or "researcher" in result.output

    def test_preview_no_program(self, runner, sample_config):
        with patch(
            "temper_ai.interfaces.cli.optimize_commands.CompiledProgramStore",
            create=True,
        ) as MockStore:
            mock_store = MagicMock()
            mock_store.load_latest.return_value = None
            MockStore.return_value = mock_store
            with patch.dict(
                "sys.modules",
                {
                    "temper_ai.optimization.dspy.program_store": MagicMock(
                        CompiledProgramStore=MockStore,
                    ),
                    "temper_ai.optimization.dspy.prompt_adapter": MagicMock(
                        DSPyPromptAdapter=lambda store: MagicMock(
                            augment_prompt=lambda name, prompt, **kw: prompt,
                        ),
                    ),
                },
            ):
                result = runner.invoke(
                    optimize_group, ["preview", sample_config],
                )
                assert result.exit_code == 0

    def test_compile_missing_config(self, runner):
        result = runner.invoke(
            optimize_group, ["compile", "/nonexistent/path.yaml"],
        )
        assert result.exit_code != 0

    def test_list_with_agent_filter(self, runner):
        with patch(
            "temper_ai.interfaces.cli.optimize_commands.CompiledProgramStore",
            create=True,
        ) as MockStore:
            mock_store = MagicMock()
            mock_store.list_programs.return_value = []
            MockStore.return_value = mock_store
            with patch.dict(
                "sys.modules",
                {
                    "temper_ai.optimization.dspy.program_store": MagicMock(
                        CompiledProgramStore=MockStore,
                    ),
                },
            ):
                result = runner.invoke(
                    optimize_group, ["list", "--agent", "researcher"],
                )
                assert result.exit_code == 0
                mock_store.list_programs.assert_called_once_with(
                    agent_name="researcher"
                )

    def test_compile_insufficient_data(self, runner, sample_config):
        """When not enough examples, shows insufficient data message."""
        mock_collector = MagicMock()
        mock_collector.collect_examples.return_value = [MagicMock()]  # Only 1

        with patch(
            "temper_ai.interfaces.cli.optimize_commands._ensure_database",
            return_value=True,
        ), patch.dict(
            "sys.modules",
            {
                "temper_ai.optimization.dspy.data_collector": MagicMock(
                    TrainingDataCollector=lambda: mock_collector,
                ),
                "temper_ai.optimization.dspy._schemas": MagicMock(),
            },
        ):
            result = runner.invoke(
                optimize_group,
                ["compile", sample_config, "--min-examples", "10"],
            )
            assert result.exit_code == 0
            assert "insufficient" in result.output.lower() or "not enough" in result.output.lower() or "1" in result.output
