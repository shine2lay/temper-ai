"""Tests for CLI argument parsing — command registration, flags, defaults.

These tests exercise the argparse layer in temper_ai/cli/main.py without
executing actual workflow/server logic (which would require a running server
and database). All side-effectful functions (_cmd_run, _cmd_serve,
_cmd_validate) are patched out.
"""

from unittest.mock import patch

import pytest

from temper_ai.cli.main import _parse_inputs, main

# ---------------------------------------------------------------------------
# _parse_inputs — unit tests (no subprocess, no mocking needed)
# ---------------------------------------------------------------------------


class TestParseInputs:
    def test_empty_list_returns_empty_dict(self):
        assert _parse_inputs([]) == {}

    def test_single_key_value(self):
        assert _parse_inputs(["topic=cats"]) == {"topic": "cats"}

    def test_multiple_key_values(self):
        result = _parse_inputs(["a=1", "b=2", "c=three"])
        assert result == {"a": "1", "b": "2", "c": "three"}

    def test_value_with_equals_sign(self):
        # Only the first '=' is the separator
        result = _parse_inputs(["url=http://host?a=1&b=2"])
        assert result == {"url": "http://host?a=1&b=2"}

    def test_missing_equals_calls_sys_exit(self):
        with pytest.raises(SystemExit) as exc_info:
            _parse_inputs(["no_equals_here"])
        assert exc_info.value.code == 1

    def test_empty_key_is_accepted(self):
        # partition on '=' with leading '=' gives empty key — accepted as-is
        result = _parse_inputs(["=value"])
        assert result == {"": "value"}

    def test_empty_value_is_accepted(self):
        result = _parse_inputs(["key="])
        assert result == {"key": ""}

    def test_last_write_wins_for_duplicate_keys(self):
        result = _parse_inputs(["x=first", "x=second"])
        assert result == {"x": "second"}


# ---------------------------------------------------------------------------
# Parser registration — test that subcommands and flags exist
# ---------------------------------------------------------------------------


def _build_parser():
    """Re-run main() argument setup by calling the real parser construction.

    We patch sys.argv so parse_args() returns after parsing, then capture the
    parser via the argparse.ArgumentParser constructor. This avoids executing
    the command handlers while still exercising the registration code.
    """
    # We call main() with --help which exits cleanly; capture the HelpAction
    # output by catching SystemExit(0).
    with patch("sys.argv", ["temper", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 0


class TestMainHelp:
    def test_top_level_help_exits_0(self):
        with patch("sys.argv", ["temper", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_run_subcommand_help_exits_0(self):
        with patch("sys.argv", ["temper", "run", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_serve_subcommand_help_exits_0(self):
        with patch("sys.argv", ["temper", "serve", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_validate_subcommand_help_exits_0(self):
        with patch("sys.argv", ["temper", "validate", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


class TestNoCommand:
    def test_no_subcommand_exits_1(self):
        """Invoking temper with no subcommand should print help and exit 1."""
        with patch("sys.argv", ["temper"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Argument parsing — verify defaults and flags are registered correctly
# ---------------------------------------------------------------------------


def _parse_args_for(argv):
    """Parse argv using the real argparse setup, without executing commands.

    Works by patching _cmd_run/_cmd_serve/_cmd_validate and capturing the
    args namespace that would be passed to them via a side_effect.
    """
    captured = {}

    def capture_run(args):
        captured["args"] = args

    def capture_serve(args):
        captured["args"] = args

    def capture_validate(args):
        captured["args"] = args

    with (
        patch("sys.argv", argv),
        patch("temper_ai.cli.main._cmd_run", side_effect=capture_run),
        patch("temper_ai.cli.main._cmd_serve", side_effect=capture_serve),
        patch("temper_ai.cli.main._cmd_validate", side_effect=capture_validate),
    ):
        main()

    return captured.get("args")


class TestRunSubcommandArgs:
    def test_positional_workflow_name(self):
        args = _parse_args_for(["temper", "run", "my_workflow"])
        assert args.workflow == "my_workflow"

    def test_default_config_dir(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.config_dir == "configs"

    def test_custom_config_dir(self):
        args = _parse_args_for(["temper", "run", "wf", "--config-dir", "/tmp/cfgs"])
        assert args.config_dir == "/tmp/cfgs"

    def test_verbose_default_is_zero(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.verbose == 0

    def test_verbose_flag_increments(self):
        args = _parse_args_for(["temper", "run", "wf", "-v"])
        assert args.verbose == 1

    def test_verbose_double_flag(self):
        args = _parse_args_for(["temper", "run", "wf", "-vv"])
        assert args.verbose == 2

    def test_provider_flag(self):
        args = _parse_args_for(["temper", "run", "wf", "--provider", "openai"])
        assert args.provider == "openai"

    def test_model_flag(self):
        args = _parse_args_for(["temper", "run", "wf", "--model", "gpt-4o"])
        assert args.model == "gpt-4o"

    def test_workspace_flag(self):
        args = _parse_args_for(["temper", "run", "wf", "--workspace", "/tmp/ws"])
        assert args.workspace == "/tmp/ws"

    def test_no_db_flag(self):
        args = _parse_args_for(["temper", "run", "wf", "--no-db"])
        assert args.no_db is True

    def test_no_db_default_false(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.no_db is False

    def test_input_flag_single(self):
        args = _parse_args_for(["temper", "run", "wf", "--input", "topic=cats"])
        assert args.input == ["topic=cats"]

    def test_input_flag_short_form(self):
        args = _parse_args_for(["temper", "run", "wf", "-i", "a=1"])
        assert args.input == ["a=1"]

    def test_input_flag_repeatable(self):
        args = _parse_args_for(["temper", "run", "wf", "-i", "a=1", "-i", "b=2"])
        assert args.input == ["a=1", "b=2"]

    def test_input_default_is_empty_list(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.input == []

    def test_debug_flag(self):
        args = _parse_args_for(["temper", "run", "wf", "--debug"])
        assert args.debug is True

    def test_debug_default_false(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.debug is False

    def test_provider_default_is_none(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.provider is None

    def test_model_default_is_none(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.model is None

    def test_workspace_default_is_none(self):
        args = _parse_args_for(["temper", "run", "wf"])
        assert args.workspace is None


class TestServeSubcommandArgs:
    def test_default_port(self):
        args = _parse_args_for(["temper", "serve"])
        assert args.port == 8420

    def test_custom_port(self):
        args = _parse_args_for(["temper", "serve", "--port", "9000"])
        assert args.port == 9000

    def test_port_is_int(self):
        args = _parse_args_for(["temper", "serve", "--port", "8000"])
        assert isinstance(args.port, int)

    def test_default_host(self):
        args = _parse_args_for(["temper", "serve"])
        assert args.host == "0.0.0.0"

    def test_custom_host(self):
        args = _parse_args_for(["temper", "serve", "--host", "127.0.0.1"])
        assert args.host == "127.0.0.1"

    def test_dev_flag_false_by_default(self):
        args = _parse_args_for(["temper", "serve"])
        assert args.dev is False

    def test_dev_flag(self):
        args = _parse_args_for(["temper", "serve", "--dev"])
        assert args.dev is True

    def test_default_config_dir(self):
        args = _parse_args_for(["temper", "serve"])
        assert args.config_dir == "configs"

    def test_custom_config_dir(self):
        args = _parse_args_for(["temper", "serve", "--config-dir", "my/configs"])
        assert args.config_dir == "my/configs"

    def test_debug_flag(self):
        args = _parse_args_for(["temper", "serve", "--debug"])
        assert args.debug is True

    def test_debug_default_false(self):
        args = _parse_args_for(["temper", "serve"])
        assert args.debug is False

    def test_port_non_integer_exits(self):
        """Passing a non-integer to --port should cause argparse to exit with error."""
        with patch("sys.argv", ["temper", "serve", "--port", "notanumber"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0


class TestValidateSubcommandArgs:
    def test_positional_workflow_name(self):
        args = _parse_args_for(["temper", "validate", "my_workflow"])
        assert args.workflow == "my_workflow"

    def test_default_config_dir(self):
        args = _parse_args_for(["temper", "validate", "wf"])
        assert args.config_dir == "configs"

    def test_custom_config_dir(self):
        args = _parse_args_for(["temper", "validate", "wf", "--config-dir", "custom/"])
        assert args.config_dir == "custom/"

    def test_debug_flag(self):
        args = _parse_args_for(["temper", "validate", "wf", "--debug"])
        assert args.debug is True

    def test_debug_default_false(self):
        args = _parse_args_for(["temper", "validate", "wf"])
        assert args.debug is False


class TestGlobalDebugFlag:
    def test_global_debug_before_subcommand_is_registered(self):
        """--debug before the subcommand should be registered by the top-level parser."""
        # Verify the top-level parser accepts --debug by checking help doesn't error
        with patch("sys.argv", ["temper", "--debug", "run", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        # --help always exits 0
        assert exc_info.value.code == 0
