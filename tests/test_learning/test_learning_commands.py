"""Tests for learning CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.learning_commands import learning_group

runner = CliRunner()


class TestLearningCommands:
    def test_mine_help(self) -> None:
        result = runner.invoke(learning_group, ["mine", "--help"])
        assert result.exit_code == 0
        assert "lookback" in result.output

    def test_patterns_help(self) -> None:
        result = runner.invoke(learning_group, ["patterns", "--help"])
        assert result.exit_code == 0
        assert "type" in result.output

    def test_recommend_help(self) -> None:
        result = runner.invoke(learning_group, ["recommend", "--help"])
        assert result.exit_code == 0
        assert "min-confidence" in result.output

    def test_tune_help(self) -> None:
        result = runner.invoke(learning_group, ["tune", "--help"])
        assert result.exit_code == 0
        assert "preview" in result.output

    def test_stats_help(self) -> None:
        result = runner.invoke(learning_group, ["stats", "--help"])
        assert result.exit_code == 0

    @patch("temper_ai.interfaces.cli.learning_commands._get_store")
    @patch("temper_ai.learning.orchestrator.MiningOrchestrator")
    def test_mine_command(self, mock_orch_cls, mock_store) -> None:
        mock_run = MagicMock()
        mock_run.patterns_found = 3
        mock_run.patterns_new = 2
        mock_run.novelty_score = 0.67
        mock_run.miner_stats = {"agent_performance": 2}
        mock_orch_cls.return_value.run_mining.return_value = mock_run

        result = runner.invoke(learning_group, ["mine"])
        assert result.exit_code == 0
        assert "Mining complete" in result.output

    @patch("temper_ai.interfaces.cli.learning_commands._get_store")
    def test_patterns_empty(self, mock_store) -> None:
        mock_store.return_value.list_patterns.return_value = []
        result = runner.invoke(learning_group, ["patterns"])
        assert result.exit_code == 0
        assert "No patterns" in result.output

    @patch("temper_ai.interfaces.cli.learning_commands._get_store")
    def test_stats_command(self, mock_store) -> None:
        mock_store.return_value.list_mining_runs.return_value = []
        result = runner.invoke(learning_group, ["stats"])
        assert result.exit_code == 0
        assert "not converged" in result.output
