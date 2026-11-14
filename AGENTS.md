# AGENTS.md

# PROJECT TERRA — Engineering Guidelines

These guidelines apply to the entire repository and all AI coding agents working on PROJECT TERRA.

All instructions are mandatory unless explicitly overridden by the project owner.

## Mandatory Incremental Development & Review Workflow

This workflow is mandatory for ALL AI coding agents and applies to both frontend and backend development.

### 1. Change Size Limit

- Work in small, logically independent implementation increments.
- Target approximately 300–350 changed source-code lines per increment.
- 400 changed source-code lines is the HARD LIMIT.
- Count added and deleted lines together, not net line differences.
- Exclude generated files, dependency lockfiles, binary assets, and automatically generated code from the limit. Report these separately.
- Never artificially split a file or commit an incomplete, broken implementation just to meet the line limit.
- If a task requires more changes, divide it into multiple independently reviewable and functional increments.

### 2. Mandatory Commit Procedure

When an implementation increment reaches approximately 300–350 changed source-code lines:

1. Stop implementing new functionality.
2. Review the complete staged and unstaged diff.
3. Remove unrelated changes and temporary files.
4. Run relevant tests, linting, type checking, and build verification.
5. Ensure the increment leaves the repository in a working state.
6. Stage ONLY files belonging to the current increment.
7. Create a Git commit using Conventional Commits on the current working branch.

Do not exceed 400 changed source-code lines in a single commit.

### 3. Conventional Commits

All commits MUST follow Conventional Commits:

`<type>(<scope>): <description>`

Allowed types include:

- `feat` — new functionality.
- `fix` — bug fixes.
- `refactor` — structural improvements without behavior changes.
- `test` — tests.
- `docs` — documentation.
- `style` — formatting and styling without logic changes.
- `perf` — performance improvements.
- `chore` — maintenance and configuration.
- `build` — build system changes.

Examples:

- `feat(map): implement Equal Earth renderer`
- `feat(frontend): add map explorer routing`
- `fix(api): handle invalid region geometry`
- `test(scientific-core): add NDVI validation tests`
- `docs(architecture): document spatial harmonization`

Commit messages must be concise, descriptive, and written in English.

### 4. Prohibited Git Operations (No Push, Merge, or History Rewrite)

- NEVER run `git merge` (including fast-forward merges, `--no-ff`, or `--squash`).
- NEVER run `git rebase` or `git cherry-pick`.
- NEVER merge feature or working branches into `main` (or any other branch), even after receiving review approval or completing the entire task.
- NEVER run `git push`, push branches or commits to remote repositories, or force-push.
- NEVER amend, squash, or rewrite existing commits unless explicitly instructed.
- Create local commits on the current working branch only.

Review approval from the project owner ONLY authorizes starting the next implementation increment on the same working branch—it NEVER authorizes merging branches or consolidating commits. All merges are performed exclusively by the project owner.

### 5. Mandatory Review Notification

Immediately after creating each commit:

- STOP all further implementation work.
- Notify the project owner that the increment is ready for review.
- Provide the commit hash and Conventional Commit message.
- Report the number of added and deleted source-code lines.
- List all modified files.
- Summarize the implemented changes.
- Report tests, linting, type checks, and build results.
- Explicitly disclose any failures or unfinished work.

The notification must request project owner review and approval.

### 6. Approval Gate

After sending the review notification:

- Do not start the next implementation increment.
- Wait for explicit approval from the project owner.
- Resume only after approval, continuing strictly as a new incremental commit on the current working branch.
- Do NOT merge branches, switch to `main`, or squash commits after approval or at the end of the task.
- Apply requested corrections before proceeding.
- Never interpret silence as approval.

### 7. Exceptional Cases

If the current change cannot be safely split into a working increment within the 400-line limit:

- Stop before exceeding the limit.
- Explain the dependency between the changes.
- Propose a safe implementation breakdown.
- Wait for approval before proceeding with an alternative approach.

If tests fail, do not commit the change as successfully completed. Report the failure and request review of the issue or corrective action.

**Core principle: Every implementation increment must be small, functional, committed as an individual local commit on the working branch, and explicitly approved before the next increment begins. Never merge commits or branches.**

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

## Architecture Reference

Before making any non-trivial architectural, cross-module, data-processing, or infrastructure changes, you MUST read:

- `docs/architecture/SYSTEM_ARCHITECTURE.md`

This document defines the intended system architecture, component responsibilities, boundaries, integrations, and data flows.

`AGENTS.md` defines engineering rules.
`SYSTEM_ARCHITECTURE.md` defines system design.

All implementations must respect both documents.

If an implementation requires deviating from the architecture:
1. Explain the reason.
2. Identify affected components.
3. Propose an Architecture Decision Record (ADR).
4. Do not silently change architectural boundaries.

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

## 11. Commits and Branching

- Use descriptive commit messages (Conventional Commits style).
- Create or use a feature branch for new development; never commit directly to `main`.
- NEVER merge changes into `main` or any other branch (`git merge` is strictly forbidden for AI agents).
- Leave all approved increments as separate, unmerged local commits on the working branch.
- Keep the `main` branch completely untouched; branch integration and pull requests are handled solely by the project owner.

## 12. Definition of Done

A task is complete only when:

- Requested functionality is implemented.
- Architectural boundaries are respected.
- Routing follows the established structure.
- Persistence uses repository contracts and implementations.
- Relevant tests and checks pass.
- No unrelated functionality is modified.
- Documentation is updated where necessary.
- All increments are committed separately on the working branch without merging into `main`.
- Remaining limitations are explicitly reported.

## Final Commit Organization & History Integrity

At the end of every multi-step implementation task, the agent MUST perform a final Git history audit on the current working branch without merging branches or rewriting history.

### 1. Logical Commit Organization

If implementation changes remain uncommitted, organize them into small, logically independent commits on the current working branch.

Group changes by:
- Architecture and project configuration.
- Dependencies and tooling.
- Core components and infrastructure.
- Individual features and modules.
- Tests.
- Documentation.
- Bug fixes and refinements.

Every commit must represent one coherent implementation step.

Do not group unrelated functionality into the same commit.

### 2. Commit Chronology

- Arrange commits in logical implementation order.
- Dependencies and foundational components must precede features that depend on them.
- Tests must follow or accompany the implementation they verify.
- Documentation should reflect the implementation that actually exists.
- Commit timestamps must reflect the actual time of committing.
- Never fabricate, backdate, or manipulate author or committer dates to create an artificial development timeline.

### 3. Existing Commits

- Preserve previously approved commits as individual commits.
- Never merge, squash, rewrite, amend, or reorder existing commits without explicit authorization.
- Do not duplicate functionality already committed.
- Do not force-push or push any changes.

### 4. Final History Audit

Before declaring the task complete:

1. Check `git status` and confirm the repository remains on the working branch (not merged into `main`).
2. Inspect all commits created during the task.
3. Verify that each commit follows Conventional Commits.
4. Verify that each commit respects the 400-line source-code change limit, excluding explicitly exempted generated files.
5. Verify chronological and logical consistency.
6. Confirm that no implementation changes remain unintentionally uncommitted.

### 5. Final Report

Provide:
- Current working branch name.
- Ordered list of commits.
- Commit hashes and messages.
- Actual commit timestamps.
- Files and functionality covered by each commit.
- Added and deleted source-code lines.
- Test and verification results.
- Any remaining uncommitted changes.

**Final principle: Git history must accurately represent the actual development process, with small, logical, chronological, unmerged, and independently reviewable commits.**

**Final principle: Build TERRA as a scientifically trustworthy, modular, reproducible, and maintainable engineering system.**