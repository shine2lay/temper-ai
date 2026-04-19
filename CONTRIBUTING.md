# Contributing to Temper AI

Thanks for your interest in contributing. This guide covers how to set up, develop, test, and submit changes.

## Setup

```bash
git clone https://github.com/shine2lay/temper-ai.git
cd temper-ai

# Option A: uv (recommended — matches lock file)
uv sync --all-extras

# Option B: pip
pip install -e ".[dev]"
```

### Pre-commit hook

The repo includes a tracked pre-commit hook (`scripts/git-hooks/pre-commit`) that mirrors CI — running `ruff`, `mypy`, and the full test suite against your commit so lint/type/test failures surface locally before CI catches them.

Install it once after cloning:

```bash
./scripts/install-git-hooks.sh
```

This points `core.hooksPath` at `scripts/git-hooks/`. The hook runs the same checks CI runs:

- **ruff check .** — whole project
- **mypy temper_ai/ --ignore-missing-imports** — whole package
- **pytest tests/ -x --timeout=60** — full suite (`--ignore=tests/test_database` by default)
- **docs regeneration** — auto-runs `scripts/generate_docs.py` when source files that feed the reference docs are staged

Escape hatches:

```bash
git commit --no-verify              # skip the hook entirely
PRECOMMIT_RUN_DB=1 git commit       # include tests/test_database/
```

To regenerate docs manually without committing:

```bash
python scripts/generate_docs.py
```

## Running Tests

```bash
# Full suite (900+ tests, ~25s)
pytest

# Or via Makefile
make test

# Specific module
pytest tests/test_stage/

# Single test
pytest tests/test_stage/test_executor.py::TestExecuteGraph -v
```

## Code Quality

```bash
# Lint
ruff check temper_ai/
# or: make lint

# Type check
mypy temper_ai/ --ignore-missing-imports
# or: make typecheck

# Quality report (anti-patterns, complexity, dead code, etc.)
python -m scripts.code_quality_check.runner temper_ai
```

## Frontend Development

The dashboard is a React + TypeScript + Vite app in `frontend/`.

```bash
cd frontend
npm install
npm run dev      # Dev server at http://localhost:5173 (proxied to backend)
```

To build for production:

```bash
npm run build    # Outputs to frontend/dist/
# or from repo root: make build
```

The backend serves `frontend/dist/` as static files at `/app/*`.

**Stack:** React 19, TypeScript 5.9, Tailwind CSS 4.1, Shadcn/ui, React Flow, Zustand, TanStack React Query.

See `frontend/README.md` for directory structure.

## Documentation

Reference docs auto-generate from code introspection. The pre-commit hook regenerates them when source files change.

To regenerate manually:

```bash
python scripts/generate_docs.py
```

Docs live in `docs/reference/` — don't edit them manually.

## Project Structure

```
temper_ai/        Core package (14 modules)
tests/            Mirrors package structure (725+ tests)
configs/          Workflow, agent, stage, tool YAML configs
scripts/          Doc generator + code quality checker
docs/             Auto-generated reference docs + roadmap
frontend/         React + Vite + TypeScript dashboard
```

## Making Changes

1. **Read before editing.** Understand the existing code before modifying it.
2. **Keep changes focused.** One PR = one concern. Don't bundle unrelated changes.
3. **Add tests.** New features need tests. Bug fixes need a test that reproduces the bug.
4. **Run the full suite** before submitting: `pytest`
5. **Don't add unnecessary abstractions.** Three similar lines is better than a premature abstraction.

## Adding New Components

Temper uses a registry pattern for extensible components. To add a new one:

### New tool
1. Create `temper_ai/tools/my_tool.py` implementing `BaseTool`
2. Add to `TOOL_CLASSES` in `temper_ai/tools/__init__.py`
3. Add tests in `tests/test_tools/test_my_tool.py`

### New LLM provider
1. Create `temper_ai/llm/providers/my_provider.py` implementing `BaseLLM`
2. Register in `temper_ai/llm/providers/factory.py`
3. Add tests in `tests/test_llm/test_providers.py`

### New topology strategy
1. Create the generator function in `temper_ai/stage/topology.py` (or a new file)
2. Call `register_topology()` in the module
3. Add tests in `tests/test_stage/test_topology.py`

### New safety policy
1. Create `temper_ai/safety/my_policy.py` implementing `BasePolicy`
2. Call `register_policy()` in `temper_ai/safety/__init__.py`
3. Add tests in `tests/test_safety/test_policies.py`

Docs regenerate automatically on commit.

## Code Conventions

- **No hidden behavior.** If a function does something non-obvious, name it clearly.
- **Module owns its interface.** Base classes live in their module, not a central file.
- **YAML is the user's interface.** Config changes should be expressible in YAML without code.
- **Observability by default.** New execution paths should emit events via the recorder.
- **Safety first.** New tools must work within the policy engine.

## Reporting Issues

[Open an issue](https://github.com/shine2lay/temper-ai/issues) with:
- What you expected
- What happened
- Steps to reproduce
- Workflow YAML if applicable
- Error output

## License

By contributing, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
