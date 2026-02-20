"""Constants for the project scaffolding command."""

GITIGNORE_TEMPLATE = """\
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/
venv/
.venv/

# Environment
.env
.env.local

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Temper AI
.temper-ai/
*.db
"""

ENV_EXAMPLE_TEMPLATE = """\
# LLM Provider Configuration
TEMPER_LLM_PROVIDER=vllm
TEMPER_LLM_MODEL=qwen3-next
TEMPER_LLM_BASE_URL=http://localhost:8000
# TEMPER_LLM_API_KEY=

# Logging
TEMPER_LOG_LEVEL=INFO
"""

README_TEMPLATE = """\
# {project_name}

Temper AI project generated from the `{product_type}` template.

## Quick Start

```bash
# Install temper-ai
pip install temper-ai

# Run the workflow
temper-ai run workflow.yaml --input inputs.yaml --show-details
```

## Project Structure

```
{project_name}/
├── workflow.yaml      # Main workflow definition
├── agents/            # Agent configurations
├── stages/            # Stage configurations
├── .env.example       # Environment variables template
└── .gitignore
```

## Configuration

Copy `.env.example` to `.env` and fill in your settings:

```bash
cp .env.example .env
```
"""

# Error messages
ERR_DIR_EXISTS = "Directory already exists: {path}. Use --force to overwrite."
ERR_TEMPLATE_NOT_FOUND = "Template not found: {product_type}"

# Default values
DEFAULT_OUTPUT_DIR = "."
