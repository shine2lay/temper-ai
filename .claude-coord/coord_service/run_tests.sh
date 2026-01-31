#!/bin/bash
# Comprehensive test runner for coordination service
#
# Usage:
#   ./run_tests.sh              # Run all tests with coverage
#   ./run_tests.sh fast         # Run only fast tests
#   ./run_tests.sh integration  # Run only integration tests
#   ./run_tests.sh stress       # Run only stress tests
#   ./run_tests.sh coverage     # Generate detailed coverage report

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================"
echo "Coordination Service Test Suite"
echo "================================"
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: python3 not found${NC}"
    exit 1
fi

echo "Python version: $(python3 --version)"

# Check pytest
if ! python3 -c "import pytest" 2>/dev/null; then
    echo -e "${YELLOW}Installing pytest...${NC}"
    pip3 install pytest pytest-cov pytest-timeout pytest-xdist 2>/dev/null || \
    pip install pytest pytest-cov pytest-timeout pytest-xdist
fi

# Determine test mode
MODE="${1:-all}"

case "$MODE" in
    fast)
        echo -e "${GREEN}Running fast tests only...${NC}"
        python3 -m pytest tests/ -m "not slow" -v
        ;;

    integration)
        echo -e "${GREEN}Running integration tests...${NC}"
        python3 -m pytest tests/test_integration.py -v
        ;;

    stress)
        echo -e "${GREEN}Running stress tests...${NC}"
        python3 -m pytest tests/test_stress.py -v
        ;;

    unit)
        echo -e "${GREEN}Running unit tests...${NC}"
        python3 -m pytest tests/test_database.py tests/test_validator.py tests/test_protocol.py -v
        ;;

    coverage)
        echo -e "${GREEN}Running all tests with coverage report...${NC}"
        python3 -m pytest tests/ \
            --cov=. \
            --cov-report=html \
            --cov-report=term \
            --cov-report=xml \
            -v

        echo
        echo -e "${GREEN}Coverage report generated:${NC}"
        echo "  HTML: file://$(pwd)/htmlcov/index.html"
        echo "  XML:  $(pwd)/coverage.xml"
        ;;

    parallel)
        echo -e "${GREEN}Running tests in parallel...${NC}"
        python3 -m pytest tests/ -n auto -v
        ;;

    all)
        echo -e "${GREEN}Running all tests with coverage...${NC}"
        python3 -m pytest tests/ \
            --cov=. \
            --cov-report=term \
            --cov-report=html \
            -v

        echo
        echo -e "${GREEN}Test Summary:${NC}"
        python3 -m pytest tests/ --collect-only -q | tail -5

        echo
        echo -e "${GREEN}Coverage report: file://$(pwd)/htmlcov/index.html${NC}"
        ;;

    *)
        echo -e "${RED}Unknown mode: $MODE${NC}"
        echo
        echo "Usage: $0 [fast|integration|stress|unit|coverage|parallel|all]"
        echo
        echo "Modes:"
        echo "  fast        - Run only fast tests (skip slow/stress tests)"
        echo "  integration - Run integration tests only"
        echo "  stress      - Run stress tests only"
        echo "  unit        - Run unit tests only"
        echo "  coverage    - Run all tests with detailed coverage report"
        echo "  parallel    - Run tests in parallel (faster)"
        echo "  all         - Run all tests with coverage (default)"
        exit 1
        ;;
esac

echo
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Tests completed successfully${NC}"
else
    echo -e "${RED}✗ Tests failed${NC}"
    exit 1
fi
