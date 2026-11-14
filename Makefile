# PROJECT TERRA — development commands
#
# Requirements: Node.js 20+ with npm (frontend), uv (backend).
# Frontend and backend run independently of each other.

.PHONY: help frontend-install frontend-dev frontend-build frontend-typecheck frontend-lint \
        backend-install backend-dev backend-test backend-lint test lint

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

frontend-install: ## Install frontend dependencies (npm)
	cd frontend && npm install

frontend-dev: ## Start the frontend dev server (http://localhost:5173)
	cd frontend && npm run dev

frontend-build: ## Production build of the frontend
	cd frontend && npm run build

frontend-typecheck: ## TypeScript type checking (strict)
	cd frontend && npm run typecheck

frontend-lint: ## Lint the frontend (ESLint)
	cd frontend && npm run lint

backend-install: ## Sync backend dependencies with uv (creates uv.lock)
	cd backend/core && uv sync

backend-dev: ## Start the API with Granian + auto reload (http://127.0.0.1:8000)
	cd backend/core && uv run granian --interface asgi --host 127.0.0.1 --port 8000 --reload terra.main:app

backend-test: ## Run backend tests (pytest)
	cd backend/core && uv run pytest

backend-lint: ## Lint backend code (ruff check + format check)
	cd backend/core && uv run ruff check . && uv run ruff format --check .

test: backend-test ## Run all tests

lint: frontend-lint backend-lint ## Run all linters
