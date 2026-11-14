# AGENTS.md

# PROJECT TERRA — Engineering Guidelines

These guidelines apply to the entire repository and all AI coding agents working on PROJECT TERRA.

All instructions are mandatory unless explicitly overridden by the project owner.

## 1. Project Context

PROJECT TERRA is an open-source environmental analysis platform focused on ecosystem response, environmental stress, and resilience assessment.

Core principles:
- Scientific correctness.
- Explicit architectural boundaries.
- Reproducibility.
- Data provenance.
- Maintainability.
- Incremental development.

## 2. General Engineering Rules

- Inspect existing architecture before modifying code.
- Prefer simple, explicit, maintainable implementations.
- Keep modules focused and responsibilities separated.
- Avoid unnecessary abstractions and dependencies.
- Do not duplicate existing functionality.
- Do not modify unrelated files.
- Never silently introduce breaking changes.
- Never claim verification without executing the relevant checks.

## 3. Architecture

TERRA follows a **Modular Monolith** architecture.

The API and Worker are separate runtime processes that share application, domain, and scientific packages.

Backend architectural layers:

- API Layer — HTTP routing, request validation, response serialization.
- Application Layer — use cases, orchestration, application services.
- Domain Layer — business rules, domain entities, repository contracts.
- Infrastructure Layer — database implementations, external integrations, storage adapters.
- Scientific Core — independent scientific calculations and algorithms.

Dependency direction:

`API → Application → Domain`

`Infrastructure → Domain / Application Contracts`

The Domain Layer must not depend on FastAPI, SQLAlchemy, HTTP, or infrastructure implementations.

Modules must have explicit boundaries. Avoid cyclic dependencies and direct access to another module's internal implementation.

Do not introduce microservices or distributed infrastructure without a demonstrated requirement.

## 4. Frontend Engineering

Technology:
- React 19
- TypeScript
- Vite
- MapLibre GL JS 5
- deck.gl
- Zustand
- TanStack Query
- Apache ECharts

Use **Feature-Sliced Design (FSD-lite)**.

Layers:
- `app` — initialization, routing, providers.
- `pages` — route-level pages.
- `widgets` — compositional UI blocks.
- `features` — user actions and functionality.
- `entities` — domain entities and representations.
- `shared` — reusable utilities, infrastructure, and UI.

Dependency direction:

`app → pages → widgets → features → entities → shared`

Rules:
- Use strict TypeScript.
- Avoid `any` and unjustified type assertions.
- Keep components focused on presentation and interaction.
- Do not implement scientific calculations inside React components.
- Do not perform direct API calls inside UI components.
- Use TanStack Query for server state.
- Use Zustand for shared client-side UI state.
- Use React state for local component state.
- Use URL parameters for shareable analysis configuration where appropriate.
- Centralize API communication.
- Handle loading, error, empty, and insufficient-data states.

## 5. Backend Engineering

Technology:
- Python
- FastAPI
- Granian
- Pydantic
- uv
- SQLAlchemy
- PostgreSQL
- PostGIS

### 5.1 Mandatory Backend Module Structure

Use a modular structure in which each business module owns its API, application logic, domain definitions, and infrastructure implementations.

Example:

```text
backend/core/
└── terra/
    ├── main.py
    ├── api/
    │   ├── dependencies.py
    │   └── v1/
    │       └── router.py
    │
    ├── modules/
    │   ├── regions/
    │   │   ├── api/
    │   │   │   ├── router.py
    │   │   │   └── schemas.py
    │   │   ├── application/
    │   │   │   ├── services.py
    │   │   │   └── use_cases/
    │   │   ├── domain/
    │   │   │   ├── entities.py
    │   │   │   └── repositories.py
    │   │   └── infrastructure/
    │   │       ├── models.py
    │   │       └── repositories/
    │   │           └── sqlalchemy.py
    │   │
    │   ├── analyses/
    │   ├── assessments/
    │   ├── data_sources/
    │   └── reports/
    │
    └── infrastructure/
        └── database/
            ├── session.py
            └── base.py
```

This is a reference structure. Adapt it when necessary, but preserve the architectural boundaries.

### 5.2 Routing Architecture

Routing must be explicit, modular, and versioned.

Mandatory requirements:

- Use FastAPI `APIRouter`.
- Each business module owns its own router.
- The version-level router aggregates module routers.
- The main application registers the root API router.
- All business endpoints must be grouped under `/api/v1`.
- Health endpoints must be separate from business routes.
- Use consistent URL naming and HTTP methods.
- Define request and response schemas explicitly.
- Use appropriate HTTP status codes.
- Keep route handlers thin.

Example routing hierarchy:

```text
main.py
  └── api/v1/router.py
        ├── regions/router.py
        ├── analyses/router.py
        ├── assessments/router.py
        ├── data_sources/router.py
        └── reports/router.py
```

Example endpoints:

```text
GET    /api/v1/regions
POST   /api/v1/regions
GET    /api/v1/regions/{region_id}

POST   /api/v1/analyses
GET    /api/v1/analyses/{analysis_id}

GET    /api/v1/assessments/{assessment_id}
GET    /api/v1/reports/{report_id}

GET    /health
```

Route handlers must not contain business logic, complex database queries, or scientific calculations.

Their responsibility is limited to:
1. Receiving and validating requests.
2. Invoking the appropriate application use case.
3. Returning the appropriate response.

Do not register all endpoints in one large router file.

### 5.3 Repository Pattern — Mandatory

Use the Repository Pattern for persistence access.

Repositories must separate business logic from database implementations.

Requirements:

- Define repository interfaces using Python `Protocol` or abstract interfaces.
- Keep repository contracts in the Domain Layer or an appropriate application port.
- Implement concrete repositories in the Infrastructure Layer.
- Application services and use cases must depend on repository contracts, not SQLAlchemy implementations.
- Keep database models separate from domain entities.
- Avoid exposing SQLAlchemy models outside the Infrastructure Layer.
- Use explicit methods representing domain operations.
- Keep transaction management outside individual route handlers.

Example:

```text
regions/
├── domain/
│   └── repositories.py
├── application/
│   └── use_cases/
│       └── get_region.py
└── infrastructure/
    └── repositories/
        └── sqlalchemy.py
```

Example contract:

```python
from typing import Protocol
from uuid import UUID

class RegionRepository(Protocol):
    async def get_by_id(self, region_id: UUID): ...
    async def save(self, region) -> None: ...
    async def delete(self, region_id: UUID) -> None: ...
```

The SQLAlchemy implementation must satisfy this contract.

Rules:
- Do not instantiate SQLAlchemy repositories inside route handlers.
- Inject dependencies through an explicit dependency wiring layer.
- Do not create one universal repository for every business module.
- Avoid generic CRUD abstractions that hide domain-specific behavior.
- Keep repositories focused on persistence and retrieval.
- Use Unit of Work where multiple repositories must participate in one transaction.
- Keep database session lifecycle explicit and correctly scoped.

Do not force the Repository Pattern onto every analytical operation. Complex analytical queries and DuckDB operations may use dedicated query services or infrastructure adapters.

### 5.4 Application Layer

Application services and use cases coordinate business operations.

They must:
- Implement application workflows.
- Coordinate repositories and other domain services.
- Enforce application-level rules.
- Manage transaction boundaries through appropriate abstractions.
- Remain independent of HTTP and FastAPI.

Do not put application workflows into repositories.

### 5.5 API and Worker Responsibilities

The API process handles incoming requests and application orchestration.

Long-running scientific computations must execute in the Worker runtime.

Both processes may reuse the same application, domain, and scientific packages.

Do not duplicate business logic between API and Worker.

Do not make internal HTTP calls between processes when direct shared application functionality or the task queue is appropriate.

## 6. Scientific Computing & Data Integrity

Scientific correctness is mandatory.

- Never invent scientific formulas or coefficients.
- Document assumptions, limitations, units, and calculation methods.
- Preserve data provenance and product versions.
- Account for missing observations and quality flags.
- Consider seasonality and autocorrelation.
- Maintain spatial reference system consistency.
- Do not imply that resampling creates additional source-data resolution.
- Distinguish correlation from causation.
- Account for multiple testing where statistically relevant.
- Distinguish observations, reanalysis, and model-derived estimates.
- Clearly label synthetic data.

Scientific algorithms must be independent of HTTP, database, and UI infrastructure.

## 7. Code Quality & Testing

Requirements:
- Write tests alongside new functionality.
- Prefer deterministic tests.
- Use explicit types and interfaces.
- Avoid hidden side effects.
- Avoid broad exception handling.
- Do not disable linting or type checks to bypass errors.

Backend testing must include:
- Unit tests for domain logic.
- Application use-case tests using fake or mock repository implementations.
- Repository integration tests.
- API routing and HTTP response tests.
- Dependency override tests where appropriate.

Frontend testing must cover important components and application behavior.

Run relevant tests, linting, type checking, and builds before completing a task.

## 8. Dependencies & Security

- Verify compatibility before introducing or upgrading dependencies.
- Use uv for Python dependency management.
- Preserve lockfiles.
- Never commit secrets or credentials.
- Validate external input.
- Follow third-party licenses.
- Avoid unnecessary infrastructure.

Do not introduce Docker, Kubernetes, Envoy, Kafka, or additional services without a concrete architectural requirement.

## 9. AI Agent Workflow

Before implementing a non-trivial task:

1. Inspect existing files and architecture.
2. Identify the responsible module and architectural layer.
3. Check existing contracts and reusable functionality.
4. Identify affected dependencies.
5. Present the intended file changes when architecture is affected.

During implementation:

- Respect module boundaries.
- Follow routing and repository conventions.
- Do not bypass application services.
- Do not introduce direct database access into routes.
- Do not make unrelated architectural changes.
- Keep changes focused and reviewable.

After implementation:

1. Run relevant tests and checks.
2. Review the final diff.
3. Report modified files.
4. Explain architectural decisions.
5. Report verification results and limitations.

## 10. Documentation

- Keep documentation consistent with the implementation.
- Document public interfaces.
- Document scientific formulas and assumptions.
- Record significant architectural decisions in ADRs.
- Update documentation when changing existing behavior.

## 11. Definition of Done

A task is complete only when:

- Requested functionality is implemented.
- Architectural boundaries are respected.
- Routing follows the established structure.
- Persistence uses repository contracts and implementations.
- Relevant tests and checks pass.
- No unrelated functionality is modified.
- Documentation is updated where necessary.
- Remaining limitations are explicitly reported.

**Final principle: Build TERRA as a scientifically trustworthy, modular, reproducible, and maintainable engineering system.**