#!/bin/bash
# Run M5.1 Demo: Real LLM Execution with Ollama
#
# This demo makes ACTUAL LLM calls to Ollama models.
# Requirements:
# - Ollama installed and running
# - Models downloaded (llama3.1:8b, gemma2:2b, phi3:mini, mistral:7b)

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  M5.1 Demo: Real LLM Execution${NC}"
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

# Check if Ollama is running
echo "Checking Ollama installation..."
if ! command -v ollama &> /dev/null; then
    echo -e "${RED}❌ Ollama not installed${NC}"
    echo ""
    echo "To install Ollama:"
    echo "  1. Visit: https://ollama.ai/download"
    echo "  2. Download and install"
    echo "  3. Run: ollama serve"
    exit 1
fi

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${RED}❌ Ollama is not running${NC}"
    echo ""
    echo "To start Ollama:"
    echo "  ollama serve"
    echo ""
    echo "In a separate terminal, then re-run this script."
    exit 1
fi

echo -e "${GREEN}✓ Ollama is running${NC}"
echo ""

# Check for required models
echo "Checking required models..."
REQUIRED_MODELS=("llama3.1:8b" "gemma2:2b" "phi3:mini" "mistral:7b")
MISSING_MODELS=()

for model in "${REQUIRED_MODELS[@]}"; do
    if ! ollama list | grep -q "$model"; then
        MISSING_MODELS+=("$model")
    fi
done

if [ ${#MISSING_MODELS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Missing models:${NC}"
    for model in "${MISSING_MODELS[@]}"; do
        echo "   - $model"
    done
    echo ""
    echo "To download missing models:"
    for model in "${MISSING_MODELS[@]}"; do
        echo "  ollama pull $model"
    done
    echo ""
    read -p "Continue without all models? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓ All required models available${NC}"
fi

echo ""

# Check if required packages are installed
echo "Checking dependencies..."
python -c "import temper_ai.self_improvement; import httpx" 2>/dev/null || {
    echo -e "${YELLOW}⚠️  Missing dependencies. Installing...${NC}"
    pip install -e . httpx -q
}
echo -e "${GREEN}✓ Dependencies ready${NC}"
echo ""

# Run the demo
echo -e "${BLUE}Starting M5.1 Real LLM demo...${NC}"
echo -e "${YELLOW}⚠️  This will make ~40 real Ollama API calls${NC}"
echo -e "${YELLOW}   Estimated time: 2-5 minutes${NC}"
echo ""

python examples/m5_demo_real_llm.py

echo ""
echo -e "${GREEN}Demo completed!${NC}"
