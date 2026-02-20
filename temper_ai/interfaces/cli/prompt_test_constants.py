"""Display constants for prompt-test CLI commands."""

# Test status values (canonical source: temper_ai.evaluation.constants)
# Duplicated here to avoid interfaces→evaluation fan-out dependency.
DEFAULT_TEST_CASES_DIR = "configs/test_cases"
STATUS_PASS = "PASS"  # noqa: S105
STATUS_FAIL = "FAIL"
STATUS_ERROR = "ERROR"

PROMPT_TEST_GROUP_HELP = "Test agent prompts against expected output formats"
RUN_HELP = "Run prompt tests from a test suite YAML file"
LIST_HELP = "List available test suite files"
LOADING_MSG = "Loading test suite: {path}"
RUNNING_MSG = "Running {count} test case(s) for {agent}..."
RESULT_PASS = "[green]PASS[/green]"  # noqa: S105
RESULT_FAIL = "[red]FAIL[/red]"
RESULT_ERROR = "[yellow]ERROR[/yellow]"
SUITE_PASS_MSG = "[green]All {count} test(s) passed[/green]"  # noqa: S105
SUITE_FAIL_MSG = "[red]{failed} of {total} test(s) failed[/red]"
NO_SUITES_MSG = "No test suite files found in {dir}"
VERBOSE_RAW_HEADER = "--- Raw Output ---"
VERBOSE_ANSWER_HEADER = "--- Extracted Answer ---"
