# PROJECT TERRA — development commands
#
# Requirements: Node.js 20+ with pnpm (frontend), uv (backend).
# Frontend and backend run independently of each other, or together via `make dev`.

.PHONY: help contracts dev \
        frontend-install frontend-dev frontend-build frontend-typecheck frontend-lint frontend-test \
        backend-install backend-dev backend-test backend-lint test lint

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

contracts: ## Generate OpenAPI + TypeScript contracts from backend/core into frontend
	cd frontend && pnpm contracts:generate

dev: contracts ## Generate contracts and start backend + frontend together
	@trap 'kill 0' EXIT INT TERM; \
	(cd backend/core && uv run granian --interface asgi --host 127.0.0.1 --port 8000 --reload terra.main:app) & \
	(cd frontend && pnpm exec vite) & \
	wait

frontend-install: ## Install frontend dependencies (pnpm)
	cd frontend && pnpm install --frozen-lockfile

frontend-dev: ## Generate contracts and start the frontend dev server (http://localhost:5173)
	cd frontend && pnpm dev

frontend-build: ## Generate contracts and run production build of the frontend
	cd frontend && pnpm build

frontend-typecheck: ## Generate contracts and run strict TypeScript type checking
	cd frontend && pnpm typecheck

frontend-lint: ## Lint the frontend (ESLint)
	cd frontend && pnpm lint

frontend-test: ## Run frontend tests (Vitest)
	cd frontend && pnpm test

backend-install: ## Sync backend dependencies with uv (creates uv.lock)
	cd backend/core && uv sync

backend-dev: ## Start the API with Granian + auto reload (http://127.0.0.1:8000)
	cd backend/core && uv run granian --interface asgi --host 127.0.0.1 --port 8000 --reload terra.main:app

backend-test: ## Run backend tests (pytest)
	cd backend/core && uv run pytest

backend-lint: ## Lint backend code (ruff check + format check)
	cd backend/core && uv run ruff check . && uv run ruff format --check .

test: backend-test frontend-test ## Run all tests

lint: frontend-lint backend-lint ## Run all linters
