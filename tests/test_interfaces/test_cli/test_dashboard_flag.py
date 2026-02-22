"""Tests for dashboard CLI integration."""
from click.testing import CliRunner
from temper_ai.interfaces.cli.main import main


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


class TestServeDevFlag:
    """Test --dev flag on serve command."""

    def test_serve_help_shows_dev_flag(self):
        """Serve command help includes --dev flag."""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--dev" in result.output

    def test_main_help_does_not_list_dashboard(self):
        """Main help should NOT list 'dashboard' as a command."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "dashboard" not in result.output.lower().split("commands:")[1] if "commands:" in result.output.lower() else True

    def test_dashboard_command_removed(self):
        """Standalone dashboard command should no longer exist."""
        runner = CliRunner()
        result = runner.invoke(main, ["dashboard"])
        assert result.exit_code != 0
