# Contributing Guide

Thank you for your interest in contributing to Temper AI. This guide covers everything you need to go from zero to a merged PR.

---

## Code of Conduct

We are committed to a harassment-free experience for everyone. Expected behaviors:

- Use welcoming and inclusive language
- Be respectful of differing viewpoints
- Accept constructive criticism gracefully
- Focus on what is best for the community

Unacceptable behavior includes harassment, personal attacks, publishing others' private information, or any conduct that would be inappropriate in a professional setting. Violations can be reported to the project maintainers via GitHub.

---

## Quick Start

```bash
git clone https://github.com/temper-ai/temper-ai.git
cd temper-ai
make setup       # uv sync, pre-commit, copies .env
make test        # verify everything works
```

`make setup` requires [uv](https://docs.astral.sh/uv/). It installs all dependencies from `pyproject.toml` (including dev extras) and configures pre-commit hooks. You do not need to manually install anything else.

---

## Development Workflow

### Branching

```bash
git checkout -b feature/your-feature-name   # new feature
git checkout -b fix/issue-123               # bug fix
```

### Daily cycle

```bash
# Format and lint before committing
make format      # black + ruff --fix
make lint        # ruff check + black --check

# Type check
make type        # mypy

# Run core tests (parallel)
make test

# Full quality gate — run this before opening a PR
make check       # lint + type + test + quality scanner
```

Pre-commit hooks run `lint` and `format` automatically on every `git commit`. If a hook fails, fix the issue and recommit — do not bypass hooks with `--no-verify`.

### Other useful targets

| Command | What it does |
|---|---|
| `make test-all` | Full test suite (all directories) |
| `make coverage` | Core tests with coverage report |
| `make security` | Bandit security scan |
| `make dev` | Start dev server on port 8420 |

Run `make help` to see all available targets.

---

## Code Standards

### Formatting and linting

- **Formatter:** `black` — run via `make format`, not manually
- **Linter:** `ruff` — run via `make lint`, not manually
- **Line length:** 88 characters (black default)
- **Type checker:** `mypy` — run via `make type`
- **String quotes:** double quotes preferred

### Functions and classes

- Functions: 50 lines max, 7 parameters max, 4 nesting depth max
- Classes: 500 lines or 20 methods max
- All public functions must have type hints
- Use Google-style docstrings

```python
def process_items(items: list[str], limit: int = 100) -> list[str]:
    """Filter items to the given limit.

    Args:
        items: Input strings to filter.
        limit: Maximum number of items to return.

    Returns:
        Filtered list of strings.

    Raises:
        ValueError: If limit is negative.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return items[:limit]
```

### Security rules (never do these)

- No f-string SQL queries — use parameterized queries
- No `eval()` or `exec()`
- No `pickle` for untrusted data
- No `os.system()` or `shell=True`
- No `yaml.load()` — use `yaml.safe_load()`

### Constants and imports

- Magic numbers must use named `UPPER_CASE` constants (whitelist: 0, 1, 2, 10, 24, 60, 100, 256, 512, 1000, 1024)
- No unused imports
- Module fan-out must be less than 8 — use lazy imports for cross-domain dependencies
- Extract repeated strings (3+ uses) to module-level constants

### Suppression comments

```python
from module import Thing  # noqa: F401  (re-exported, not unused)
TIMEOUT = 30  # noqa: scanner: skip-magic  (documented exception)
```

---

## Testing Requirements

### Running tests

```bash
make test                                            # core suite, parallel
make test-all                                        # full suite
pytest tests/test_workflow/ tests/test_agent/ -v     # specific directories
pytest tests/test_tools/test_my_tool.py -v           # single file
```

Tests run in parallel via `pytest-xdist`.

Excluded from the default suite (slow/property-based):
`tests/property/`, `tests/self_improvement/`, `tests/benchmarks/`, `tests/test_benchmarks/`

### Writing tests

Every test must have at least one `assert`. Follow the Arrange-Act-Assert pattern:

```python
def test_feature_returns_expected_value():
    """Test that feature produces the correct output."""
    # Arrange
    input_data = {"key": "value"}

    # Act
    result = my_function(input_data)

    # Assert
    assert result.success is True
    assert result.output == "expected"
```

Use `Mock(spec=ClassName)` for mocks that will be checked with `isinstance`. Mock at the point of use, not at the original definition.

### Coverage

- All new code must have tests
- Module coverage minimum: 50%
- Critical paths (auth, safety, data layer): aim for 80%+

---

## Adding a New Tool

Create `temper_ai/tools/your_tool.py`:

```python
from temper_ai.tools.base import BaseTool, ToolResult


class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful."

    def execute(self, **kwargs) -> ToolResult:
        # Implementation
        return ToolResult(success=True, result="done")
```

Then add tests in `tests/test_tools/test_my_tool.py` and update the tool loader if the tool needs to be auto-discoverable.

---

## Adding Dependencies

All dependencies live in `pyproject.toml` — do not add `requirements.txt` files.

- Add runtime deps under `[project] dependencies`
- Add dev-only deps under `[project.optional-dependencies] dev`
- Prefer well-maintained packages with compatible licenses (MIT, Apache-2, BSD)
- Document in your PR why the dependency is necessary

---

## Pull Request Process

### Before opening a PR

```bash
make check   # must pass cleanly
```

Checklist:
- [ ] `make check` passes (lint + type + test + quality)
- [ ] New tests added for new functionality
- [ ] No new suppression comments without justification
- [ ] Documentation updated if behavior changed
- [ ] Commit messages are descriptive (`type: short description`)

### PR description

Include:
- What the change does and why
- Type of change (bug fix, feature, refactor, docs)
- How it was tested
- Any breaking changes and migration notes

### Review process

1. Automated checks run (CI: lint, type, tests)
2. A maintainer reviews the code
3. Address feedback by pushing to the same branch — the PR updates automatically
4. Maintainer approves and merges

---

## Reporting Issues

Good bug reports include:
- Clear description of the bug
- Steps to reproduce
- Expected vs. actual behavior
- Environment: OS, Python version, framework version
- Relevant logs or stack traces

Feature requests should include: what the feature does, why it is needed, and any alternatives you considered.

---

## Getting Help

- **Docs:** `/docs` directory
- **Examples:** `/examples` directory
- **Tests:** `/tests` directory — working usage examples
- **GitHub Issues:** bug reports and feature requests
- **GitHub Discussions:** questions and ideas

Response times: issues within 1-2 business days, PRs within 2-3 business days, security issues within 24 hours.
