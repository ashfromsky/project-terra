# PROJECT TERRA — development commands
#
# Requirements: Node.js 20+ with pnpm (frontend & orchestration), uv (backend & GHS).
# Each component runs independently, or together via `make dev`, `make dev-ghs`, or `make dev-full`.

.PHONY: help contracts dev dev-ghs dev-full dev-check \
        frontend-install frontend-dev frontend-build frontend-typecheck frontend-lint frontend-test \
        backend-install backend-dev backend-test backend-lint \
        ghs-install ghs-api-dev ghs-worker-dev ghs-migrate ghs-test ghs-lint \
        test lint

help: ## List available commands
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

contracts: ## Generate OpenAPI + TypeScript contracts from backend/core into frontend
	cd frontend && pnpm contracts:generate

dev: ## Generate contracts and start Core + Frontend together
	node scripts/dev.mjs dev

dev-ghs: ## Start GHS API + GHS Worker together
	node scripts/dev.mjs dev-ghs

dev-full: ## Generate contracts and start Core + Frontend + GHS API + GHS Worker
	node scripts/dev.mjs dev-full

dev-check: ## Run development orchestration unit tests
	node --test scripts/dev-orchestrator.test.mjs

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

backend-install: ## Sync Core backend dependencies with uv
	cd backend/core && uv sync

backend-dev: ## Start Core API with Granian (http://127.0.0.1:8000)
	cd backend/core && uv run granian --interface asgi --host $${CORE_HOST:-127.0.0.1} --port $${CORE_PORT:-8000} terra.main:app

backend-test: ## Run Core backend tests (pytest)
	cd backend/core && uv run pytest

backend-lint: ## Lint Core backend code (ruff check + format check)
	cd backend/core && uv run ruff check . && uv run ruff format --check .

ghs-install: ## Sync GHS dependencies with uv
	cd backend/services/geospatial_harmonization && uv sync

ghs-api-dev: ## Start GHS API with Granian (http://127.0.0.1:8080)
	cd backend/services/geospatial_harmonization && uv run granian --interface asgi --host $${GHS_HOST:-127.0.0.1} --port $${GHS_PORT:-8080} geospatial_harmonization.main:app

ghs-worker-dev: ## Start GHS WorkerRunner polling loop
	cd backend/services/geospatial_harmonization && uv run python -m geospatial_harmonization.worker

ghs-migrate: ## Apply GHS Alembic migrations (alembic upgrade head)
	cd backend/services/geospatial_harmonization && uv run alembic upgrade head

ghs-test: ## Run GHS tests (pytest; PostgreSQL test skips unless GHS_TEST_POSTGRES_URL is set)
	cd backend/services/geospatial_harmonization && uv run pytest

ghs-lint: ## Lint and type-check GHS (ruff + mypy)
	cd backend/services/geospatial_harmonization && uv run ruff check . && uv run ruff format --check . && uv run mypy src

test: backend-test frontend-test ## Run default tests (Core + Frontend; run `make ghs-test` for GHS)

lint: frontend-lint backend-lint ## Run default linters (Frontend + Core; run `make ghs-lint` for GHS)
