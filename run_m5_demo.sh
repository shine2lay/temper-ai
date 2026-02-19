#!/bin/bash
# Run M5.1 Demo: Find Best Ollama Model
#
# This demo showcases M5.1's self-improvement infrastructure:
# - Performance Metric Tracking
# - A/B Testing Framework
# - Experiment Management

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  M5.1 Demo: Find Best Ollama Model${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not activated${NC}"
    echo "Activating .venv..."
    source .venv/bin/activate || {
        echo -e "${YELLOW}Failed to activate .venv. Trying venv...${NC}"
        source venv/bin/activate || {
            echo "❌ No virtual environment found. Please create one:"
            echo "   python -m venv .venv"
            echo "   source .venv/bin/activate"
            echo "   pip install -e ."
            exit 1
        }
    }
fi

echo -e "${GREEN}✓ Virtual environment active${NC}"
echo ""

# Check if required packages are installed
echo "Checking dependencies..."
python -c "import temper_ai.self_improvement" 2>/dev/null || {
    echo -e "${YELLOW}⚠️  Package not installed. Installing...${NC}"
    pip install -e . -q
}
echo -e "${GREEN}✓ Dependencies ready${NC}"
echo ""

# Run the demo
echo -e "${BLUE}Starting M5.1 demo...${NC}"
echo ""

python examples/m5_demo.py

echo ""
echo -e "${GREEN}Demo completed!${NC}"
