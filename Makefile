.DEFAULT_GOAL := help
.PHONY: lint format type test test-all coverage quality security check test-random test-flaky mutate test-quality help

PYTEST_CORE_DIRS := tests/test_workflow/ tests/test_stage/ tests/test_agent/ tests/test_safety/
PYTEST_EXCLUDE := --ignore=tests/property --ignore=tests/self_improvement --ignore=tests/benchmarks --ignore=tests/test_benchmarks
SRC := temper_ai/
PYTHON ?= python3
MIN_SCORE ?= 90

## lint: Run ruff check + black --check
lint:
	ruff check $(SRC)
	black --check --diff $(SRC)

## format: Auto-fix formatting (black + ruff --fix)
format:
	black $(SRC)
	ruff check --fix $(SRC)

## type: Run mypy type checking
type:
	mypy $(SRC)

## test: Run core test suite (parallel)
test:
	pytest $(PYTEST_CORE_DIRS) -n auto $(PYTEST_EXCLUDE)

## test-all: Run full test suite (parallel)
test-all:
	pytest tests/ -n auto $(PYTEST_EXCLUDE)

## coverage: Run tests with coverage report
coverage:
	pytest $(PYTEST_CORE_DIRS) -n auto $(PYTEST_EXCLUDE) --cov=$(SRC) --cov-report=term-missing

## quality: Run architecture scanner with score gate
quality:
	$(PYTHON) scripts/check_quality_score.py --min-score $(MIN_SCORE)

## security: Run bandit security scan
security:
	bandit -r $(SRC) -c pyproject.toml 2>/dev/null || bandit -r $(SRC) -ll

## check: Full local quality gate (lint + type + test + quality)
check: lint type test quality

## test-random: Run tests in random order (catch ordering deps)
test-random:
	pytest $(PYTEST_CORE_DIRS) -n auto $(PYTEST_EXCLUDE) -p randomly

## test-flaky: Re-run failures to detect flaky tests
test-flaky:
	pytest $(PYTEST_CORE_DIRS) $(PYTEST_EXCLUDE) --reruns 3 --reruns-delay 1 -q

## mutate: Run mutation testing on core modules
mutate:
	$(PYTHON) -m mutmut run --paths-to-mutate=temper_ai/agent/,temper_ai/workflow/ \
		--tests-dir=tests/ \
		--runner="pytest tests/test_agent/ tests/test_workflow/ -x -q --timeout=10 --no-header" 2>&1 || true
	$(PYTHON) -m mutmut results

## test-quality: All test quality checks (random + flaky + scanner)
test-quality: test-random test-flaky quality

## help: Show available targets
help:
	@echo "Available targets:"
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/^## /  make /' | sed 's/: /\t/'
