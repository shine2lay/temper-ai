.DEFAULT_GOAL := help
.PHONY: lint format type test test-all coverage quality security check help

PYTEST_CORE_DIRS := tests/test_workflow/ tests/test_stage/ tests/test_agent/ tests/test_safety/
PYTEST_EXCLUDE := --ignore=tests/property --ignore=tests/self_improvement --ignore=tests/benchmarks --ignore=tests/test_benchmarks
SRC := temper_ai/
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
	python scripts/check_quality_score.py --min-score $(MIN_SCORE)

## security: Run bandit security scan
security:
	bandit -r $(SRC) -c pyproject.toml 2>/dev/null || bandit -r $(SRC) -ll

## check: Full local quality gate (lint + type + test + quality)
check: lint type test quality

## help: Show available targets
help:
	@echo "Available targets:"
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/^## /  make /' | sed 's/: /\t/'
