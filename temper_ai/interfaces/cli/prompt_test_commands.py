"""CLI commands for prompt testing harness (R8)."""
from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.prompt_test_constants import (
    DEFAULT_TEST_CASES_DIR,
    LIST_HELP,
    LOADING_MSG,
    NO_SUITES_MSG,
    PROMPT_TEST_GROUP_HELP,
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    RUN_HELP,
    RUNNING_MSG,
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_PASS,
    SUITE_FAIL_MSG,
    SUITE_PASS_MSG,
    VERBOSE_ANSWER_HEADER,
    VERBOSE_RAW_HEADER,
)

console = Console()

_STATUS_MAP = {
    STATUS_PASS: RESULT_PASS,
    STATUS_FAIL: RESULT_FAIL,
    STATUS_ERROR: RESULT_ERROR,
}


@click.group("prompt-test", help=PROMPT_TEST_GROUP_HELP)
def prompt_test_group() -> None:
    """Test agent prompts against expected output formats."""


@prompt_test_group.command("run", help=RUN_HELP)
@click.argument("test_suite_path")
@click.option("--verbose", "-v", is_flag=True, help="Show full LLM output")
def run_tests(test_suite_path: str, verbose: bool) -> None:
    """Run prompt tests from a YAML file."""
    from temper_ai.evaluation._schemas import TestSuite

    console.print(LOADING_MSG.format(path=test_suite_path))

    try:
        with open(test_suite_path) as f:
            raw = yaml.safe_load(f)
        suite = TestSuite(**raw)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        console.print(f"[red]Error loading test suite: {exc}[/red]")
        sys.exit(1)

    console.print(
        RUNNING_MSG.format(count=len(suite.test_cases), agent=suite.agent_config)
    )

    from temper_ai.evaluation.runner import PromptTestRunner

    try:
        runner = PromptTestRunner(suite.agent_config)
        suite_result = runner.run_suite(suite)
    except (OSError, ValueError, RuntimeError) as exc:
        console.print(f"[red]Error running test suite: {exc}[/red]")
        sys.exit(1)

    _display_suite_result(suite_result, verbose=verbose)

    if suite_result.failed > 0 or suite_result.errors > 0:
        sys.exit(1)


def _display_suite_result(suite_result: object, *, verbose: bool) -> None:
    """Render a Rich table with all test results."""
    table = Table(title=f"Test Results: {suite_result.agent_name}")  # type: ignore[attr-defined]
    table.add_column("Test", style="bold")
    table.add_column("Status")
    table.add_column("Duration (s)", justify="right")
    table.add_column("Details")

    for result in suite_result.results:  # type: ignore[attr-defined]
        status_label = _STATUS_MAP.get(result.status, result.status)
        detail = result.error or ""
        if result.status in (STATUS_FAIL,) and result.validator_results:
            failures = [
                v["name"] for v in result.validator_results if not v.get("passed")
            ]
            detail = ", ".join(failures)

        table.add_row(
            result.test_name,
            status_label,
            f"{result.duration_seconds:.2f}",
            detail,
        )

        if verbose:
            if result.raw_output:
                console.print(f"  {VERBOSE_RAW_HEADER}")
                console.print(f"  {result.raw_output}")
            if result.answer_text:
                console.print(f"  {VERBOSE_ANSWER_HEADER}")
                console.print(f"  {result.answer_text}")

    console.print(table)

    total = suite_result.total  # type: ignore[attr-defined]
    failed = suite_result.failed  # type: ignore[attr-defined]

    if failed == 0 and suite_result.errors == 0:  # type: ignore[attr-defined]
        console.print(SUITE_PASS_MSG.format(count=total))
    else:
        console.print(SUITE_FAIL_MSG.format(failed=failed + suite_result.errors, total=total))  # type: ignore[attr-defined]


@prompt_test_group.command("list", help=LIST_HELP)
@click.option(
    "--dir",
    "test_dir",
    default=DEFAULT_TEST_CASES_DIR,
    help="Test cases directory",
)
def list_suites(test_dir: str) -> None:
    """List available test suite YAML files."""
    test_path = Path(test_dir)
    yaml_files = sorted(test_path.glob("*.yaml")) if test_path.is_dir() else []

    if not yaml_files:
        console.print(NO_SUITES_MSG.format(dir=test_dir))
        return

    table = Table(title=f"Test Suites in {test_dir}")
    table.add_column("File", style="bold")
    table.add_column("Agent Config")
    table.add_column("Test Cases", justify="right")

    for yaml_file in yaml_files:
        agent_cfg = ""
        test_count = "?"
        try:
            with open(yaml_file) as f:
                raw = yaml.safe_load(f)
            agent_cfg = raw.get("agent_config", "")
            cases = raw.get("test_cases", [])
            test_count = str(len(cases))
        except (OSError, yaml.YAMLError):
            pass

        table.add_row(yaml_file.name, agent_cfg, test_count)

    console.print(table)
