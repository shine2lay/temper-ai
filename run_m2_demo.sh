#!/bin/bash
# Run Milestone 2 Demo with virtual environment

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Set PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR"

# Run the demo
python "$SCRIPT_DIR/examples/milestone2_demo.py" "$@"
