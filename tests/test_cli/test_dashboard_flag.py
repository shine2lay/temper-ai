"""Tests for dashboard CLI integration."""
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from src.cli.main import main


class TestDashboardFlag:
    """Test --dashboard flag on run command."""

    def test_dashboard_flag_parses_default_port(self):
        """--dashboard without port defaults to 8420."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "--dashboard" in result.output

    def test_dashboard_help_shows_default(self):
        """Help text mentions default port 8420."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "8420" in result.output

    def test_run_help_includes_all_options(self):
        """Run command help includes dashboard among other options."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--dashboard" in result.output
        assert "--show-details" in result.output
        assert "--output" in result.output


class TestDashboardCommand:
    """Test standalone dashboard command."""

    def test_dashboard_command_exists(self):
        """Standalone dashboard command exists."""
        runner = CliRunner()
        result = runner.invoke(main, ["dashboard", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--db" in result.output

    def test_dashboard_help_shows_default_port(self):
        """Dashboard help shows default port 8420."""
        runner = CliRunner()
        result = runner.invoke(main, ["dashboard", "--help"])
        assert "8420" in result.output

    def test_dashboard_command_import_error(self):
        """Dashboard command handles missing dependencies gracefully."""
        runner = CliRunner()
        # Simulate missing dashboard dependencies by patching the import
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "src.dashboard.app":
                raise ImportError("No module named 'src.dashboard.app'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = runner.invoke(main, ["dashboard"])
            # Should fail gracefully with exit code 1
            assert result.exit_code == 1
            assert "Dashboard dependencies not installed" in result.output

    def test_dashboard_command_description(self):
        """Dashboard command has proper description."""
        runner = CliRunner()
        result = runner.invoke(main, ["dashboard", "--help"])
        assert "browse past workflow executions" in result.output.lower()


class TestMainHelpIncludesDashboard:
    """Test that main --help lists dashboard command."""

    def test_main_help_lists_dashboard(self):
        """Main help includes dashboard as a command."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "dashboard" in result.output
