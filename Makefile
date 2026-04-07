.PHONY: test lint typecheck serve dev build clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

test: ## Run tests
	pytest

lint: ## Run linter
	ruff check temper_ai/

format: ## Auto-format code
	ruff format temper_ai/

typecheck: ## Run type checker
	mypy temper_ai/ --ignore-missing-imports

serve: ## Start server (port 8420)
	temper serve --port 8420

dev: ## Start server with hot reload
	temper serve --port 8420 --dev

build: ## Build frontend
	cd frontend && npm ci && npx vite build

validate: ## Validate a workflow (usage: make validate WF=blog_writer)
	temper validate $(WF)

clean: ## Remove build artifacts
	rm -rf frontend/dist frontend/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker: ## Start with Docker Compose
	docker compose up --build

docker-down: ## Stop Docker Compose
	docker compose down
