# PROJECT TERRA — Agent Engineering Contract

These instructions apply to every AI coding agent working in this repository. They are mandatory unless the project owner explicitly overrides them for the current task. Prefer the actual implementation and accepted ADRs over assumptions based on the target architecture.

## 1. Mission and Non-Negotiable Principles

PROJECT TERRA (Ecosystem Response & Resilience Intelligence) investigates ecosystem response, environmental stress, and resilience using Earth-observation and hydrometeorological data.

- Scientific correctness, reproducibility, and data provenance come before presentation or convenience.
- Preserve explicit module, runtime, and dependency boundaries.
- Keep changes small, reviewable, testable, and limited to the requested scope.
- Never fabricate requirements, data, formulas, coefficients, capabilities, or verification results.
- Never silently change architecture, security behavior, persisted data, public contracts, or user-visible behavior.

## 2. Instruction Precedence and Stop-and-Ask

Apply instructions in this order:

1. Platform and system safety requirements.
2. Explicit project-owner instructions for the current task.
3. This repository-level `AGENTS.md`.
4. Nested `AGENTS.md` files (they may refine, but not silently weaken, higher-priority rules).
5. Referenced project documentation and applicable Skills.
6. General engineering defaults.

When requirements are ambiguous, incomplete, contradictory, or materially underspecified, stop before making a consequential choice. Explain the ambiguity, its impact, and the alternatives; ask the owner for clarification. Never invent missing requirements.

Routine, low-risk implementation choices may be made without asking when they do not alter architecture, public contracts, scientific assumptions, security boundaries, persisted data, or user-visible behavior.

## 3. Required Context and Documentation

Before every non-trivial task, read:

- `docs/PROJECT_OVERVIEW.md` — source of truth for current implementation state, placeholders, integration gaps, and verification baseline.
- `docs/architecture/SYSTEM_ARCHITECTURE.md` — target design, when changing architecture, multiple modules, data processing, or infrastructure.
- Relevant ADRs under `docs/adr/` and documentation for the affected component.
- `frontend/DESIGN.md` before substantial frontend visual/interaction work.
- `backend/services/geospatial_harmonization/README.md` before changing GHS.

Keep current reality distinct from the target design: `SYSTEM_ARCHITECTURE.md` does not prove a component is implemented. Update `docs/PROJECT_OVERVIEW.md` in the same increment when implementation status, runtime topology, public API contracts, dependencies, integrations, synthetic/mock status, or verification tooling materially changes. Update architecture documents and/or add an ADR for significant boundary or design changes. Never document planned work as implemented.

## 4. Current-State Guardrails

Read `docs/PROJECT_OVERVIEW.md` and inspect code rather than relying on this summary. The following distinctions are important in the current repository:

- `backend/core/` is the main FastAPI application. Its implemented business modules currently include `auth`, `layers`, and `regions`, alongside health and system routes. Do not assume planned analyses, assessments, comparisons, reports, or AI modules exist.
- `backend/services/geospatial_harmonization/` (GHS) is an implemented, independently runnable service accepted under ADR-0002. It has its own API, layered application/domain/infrastructure, readers, handlers, transformations, migrations, storage adapters, and service-local `WorkerRunner`. It is currently isolated from Core and the frontend unless the current overview/code proves otherwise.
- `backend/scientific/` and `backend/worker/` are placeholders, not an implemented shared Scientific Core or shared Worker runtime. Do not confuse the GHS worker with `backend/worker/`.
- The frontend is connected to Core for the implemented auth, layer-catalog, and region/AOI flows using generated OpenAPI contracts. Other analytical pages and scientific workflows still include synthetic/demo or unavailable states; preserve clear disclosure.
- Core currently uses SQLAlchemy async and a SQLite development fallback. Do not claim that Core currently uses PostGIS-backed spatial queries. GHS has its own SQLite/PostgreSQL persistence context.
- The layer catalog contains derived/resilience concepts whose algorithms are not thereby implemented. Catalog presence or `availableSteps: 0` is not evidence that quantitative analysis is available.
- NASA GIBS is a contextual visualization source only; never derive measurements, time series, or pixel statistics from rendered tiles or screenshot colors.
- Local Makefile verification exists. Do not assume CI workflows, Caddy, TiTiler, DuckDB analytics, PostGIS workflows, or shared Worker/Scientific Core are operational unless they are present and configured.

## 5. Skills Discovery

Before non-trivial work, identify relevant technologies and disciplines, discover Skills available in the agent environment/repository, and read the applicable instructions. Prefer existing Skills and project workflows over improvised ones. Never invent Skill names or assume an unavailable Skill exists.

When available in the current environment:

- Frontend: use `/antislop` and `/unslop` as applicable.
- Backend: use `/antislop-code` as applicable.
- Also look for relevant TDD/testing, code-review, architecture, security, database, and scientific-validation Skills.

If a named Skill is unavailable, report that limitation and continue using project guidelines. A Skill cannot override owner instructions, this contract, or platform safety requirements.

## 6. Planning, Baseline, and Protection of Existing Work

Before editing a non-trivial task:

1. Read the required documentation and Skills.
2. Inspect the active branch and `git status`.
3. Identify pre-existing staged, unstaged, and untracked changes.
4. Inspect affected code, tests, callers, API contracts, and relevant configuration.
5. Identify the owning module, runtime, and architectural layer.
6. Check for reusable code before adding abstractions or dependencies.
7. Identify existing verification commands and known baseline failures.
8. Define expected behavior, acceptance criteria, affected files, risks, and reviewable increments.

For changes to architecture, public contracts, persistence, security, or scientific methodology, explain the proposed design and affected boundaries before implementation. Do not ask for redundant approval when the requested scope and design are already explicit.

**Protect user work:** preserve every change that existed before the task. Never revert, overwrite, stage, commit, delete, or reformat pre-existing user changes unless the owner explicitly includes them in scope. Never use destructive cleanup such as `git reset --hard` or `git clean`. Remove only temporary artifacts created by the current task. If ownership of a change is unclear, stop and ask.

Run relevant baseline checks before editing when practical. Record pre-existing failures and distinguish them from regressions after implementation. Never attribute a failure to the current task without evidence.

## 7. Incremental Development and Mandatory Review Gate

This workflow applies to frontend, backend, documentation, infrastructure, and data changes.

### Increment size

- Work in logically independent, coherent, reviewable increments.
- Target approximately **300–400 changed source-code lines per increment** (additions plus deletions). This is a reviewability target, not an absolute limit.
- Never split cohesive functionality or files artificially to meet the target. Explain materially larger increments that cannot reasonably be decomposed.
- Report generated files, lockfiles, binary assets, and other excluded changes separately.

### Required sequence for every increment

1. Implement only the current increment.
2. Stop adding functionality when it is ready for review.
3. Inspect the complete staged and unstaged diff, including new/untracked files.
4. Confirm pre-existing owner changes remain untouched and unstaged.
5. Remove only temporary artifacts and unrelated changes created by this task.
6. Run relevant tests, linting, type checks, contract generation, and build checks.
7. Review the diff for correctness, security, maintainability, and unintended scope.
8. Leave the increment **uncommitted** and request owner review.
9. Stop implementation and wait for explicit approval or requested corrections.
10. Only after approval, stage only approved files, create coherent Conventional Commits, and push the active working branch.
11. Start the next increment only after the approved increment is committed and pushed and the owner has authorized continuation.

Never interpret silence, an acknowledgement, or an ambiguous response as approval to commit, push, or continue. Approval must clearly authorize the pending action.

If checks fail, do not describe the increment as passing or commit it as successfully completed. Report the failure and request direction or correct it within the same review cycle. If the owner explicitly requests a failing checkpoint, disclose all failures prominently.

### Review notification

For each uncommitted increment, report:

- Implemented changes and rationale.
- Active branch.
- Modified, deleted, renamed, and untracked files.
- Added and deleted source-code lines separately (never only the net count).
- Generated, lockfile, binary, and asset changes separately.
- Verification commands and actual results.
- Pre-existing failures, new failures, skipped checks, and unfinished work.
- Architectural, API, database, security, or scientific decisions and documentation updates.

Explicitly ask the owner to review and approve before commit, push, and continuation.

## 8. Git, Branching, and Commit Safety

### Branch selection

- Respect the owner's active branch; do not switch branches for convenience.
- If a task is expected to exceed **1500 changed source-code lines in total** (additions plus deletions; exclude generated files, lockfiles, binary assets, and automatically generated code), create and use `feat/<descriptive-name>` before implementation begins.
- If the task is expected to remain at or below 1500 changed source-code lines, work on the current branch (including `main`) is permitted, subject to the approval gate.
- Report excluded generated/lock/binary changes separately.
- If a task unexpectedly approaches the threshold, stop before crossing it and move remaining work to a `feat/` branch without losing or rewriting existing work. Never rewrite commits already approved and pushed.

### Commits

Only after explicit owner approval:

- Stage only files belonging to the approved increment.
- Commit on the active working branch.
- Push only that active branch to `origin`.
- Keep increments independently reviewable.

Use Conventional Commits:

`<type>(<scope>): <description>`

Use concise English descriptions. Common types: `feat`, `fix`, `refactor`, `test`, `docs`, `style`, `perf`, `chore`, and `build`.

### Prohibited operations

AI agents MUST NOT:

- Run `git merge` (including fast-forward, no-ff, or squash merges), `git rebase`, or `git cherry-pick`.
- Merge any branch or pull request into `main` or another branch. The project owner exclusively handles integration.
- Force-push, amend, squash, reorder, or rewrite existing commits/history.
- Commit or push unapproved changes.
- Indiscriminately stage the full working tree (for example, `git add .`) when pre-existing or unrelated changes may exist.
- Use `git pull` without first checking its behavior; fetch and inspect remote changes without implicitly merging or rebasing.

A feature branch remains separate until the owner integrates it. Do not switch to `main` to integrate a feature branch.

Do not create commits merely to organize changes that are still awaiting review. After approval, make each commit a coherent unit; preserve previously approved commits and real timestamps. At task end, inspect `git status`, the active branch, commits created during the task, commit messages, and push status. Intentional uncommitted changes awaiting review are not accidental leftovers and must not be cleaned up.

## 9. Architecture and Backend Boundaries

The intended Core design is a modular monolith with explicit layers:

- **API:** HTTP routing, transport validation, authentication dependencies, response serialization.
- **Application:** use cases, workflow orchestration, transaction coordination.
- **Domain:** business rules, entities, value objects, and ports/contracts.
- **Infrastructure:** database, external providers, storage, and concrete adapters.
- **Scientific Core (target):** independently testable scientific algorithms, independent of HTTP/database/UI.

Dependency direction: API → Application → Domain; Infrastructure implements Domain/Application ports. Domain and Scientific Core must not depend on FastAPI, SQLAlchemy, HTTP clients, storage implementations, or frontend code.

ADR-0002 makes GHS a deliberate independently deployable exception for the heavy geospatial ingestion/decoding stack. Preserve this boundary unless the owner approves an ADR-backed change. Do not merge GHS into Core or create additional services merely by preference.

General backend rules:

- Follow existing `auth`, `layers`, and `regions` patterns; do not create speculative or empty modules merely to match a template.
- Keep route handlers thin. Put workflows in application use cases/services, not route handlers or repositories.
- For persisted business data, use focused repository/port contracts and infrastructure implementations. Keep SQLAlchemy models and session lifecycle inside Infrastructure; inject dependencies through the established wiring layer.
- Use a Unit of Work only when multiple repositories need one atomic transaction. Static catalogs and analytical read paths may use focused query services/adapters instead of forced CRUD repositories.
- Preserve versioned Core routes under the configured prefix (`/api/v1` by default) and separate health endpoints.
- Do not assume PostGIS is installed or used by Core. Verify database support before introducing spatial SQL/extensions.
- Treat schema changes, migrations, and destructive data operations as high-risk. Never drop, truncate, or migrate production data without explicit owner approval and a documented backup/rollback plan.
- Keep Core lightweight. Heavy native geospatial dependencies belong in GHS unless an ADR approves otherwise.

## 10. Frontend Rules and API Contracts

Use the repository's FSD-lite dependency direction:

`app → pages → widgets → features → entities → shared`

Upper layers may depend on lower layers; lower layers must not import upper layers. Follow existing public entry points and slice boundaries.

- Preserve strict TypeScript; avoid `any`, unjustified casts, and suppression comments without a reason.
- Keep UI components focused on presentation/interaction. Do not put scientific calculations or ad-hoc network calls in presentation components.
- Use the shared API client and established adapters/hooks. Use TanStack Query for remote state, Zustand for genuinely shared client UI state, React state for local state, and URL parameters for shareable configuration where appropriate.
- Handle loading, error, empty, unavailable, and insufficient-data states explicitly.
- Preserve responsive behavior, keyboard accessibility, semantic controls, and visible focus states.
- Follow `frontend/DESIGN.md`; do not introduce a competing visual language without owner approval.

**OpenAPI is the Core API contract source of truth.** Use `make contracts` (or `pnpm contracts:generate` from `frontend/`) after changing Core routes/schemas. Never hand-edit `frontend/src/shared/api/generated/openapi.json` or `schema.d.ts`; change the backend contract, regenerate, and review the generated diff. Keep frontend calls typed through the shared `openapi-fetch` client. Verify both sides when changing public API behavior.

Exact frontend/backend dependency versions are defined by package manifests and lockfiles. Inspect them; do not duplicate patch versions here.

## 11. GHS-Specific Rules

GHS is under `backend/services/geospatial_harmonization/` and has its own environment, manifest/lockfile, API, application/domain/infrastructure, readers, handlers, transformations, migrations, storage adapters, and service-local worker.

- Read its README and ADRs before changing it.
- Preserve `api → application → domain ← infrastructure` and the declared ports/contracts.
- Preserve local and S3-compatible storage behavior.
- Preserve PostgreSQL job-claiming/concurrency semantics, including `FOR UPDATE SKIP LOCKED`. SQLite tests do not prove PostgreSQL concurrency correctness; run the PostgreSQL integration test when changing locking behavior and when a test database is available.
- Do not weaken SSRF protections or casually broaden `GENERIC_HANDLER_ALLOWED_HOSTS`; the generic handler remains disabled with an empty allowlist.
- Do not claim AppEEARS/Harmony integrations or end-to-end temporal processing are complete unless code proves they are wired and verified.
- Do not invent a Core↔GHS RPC/HTTP contract. Define and review it first, then update architecture and overview documents.

## 12. Scientific Computing and Data Integrity

- Never invent formulas, coefficients, thresholds, baselines, quality rules, or scientific interpretations.
- Use authoritative product documentation and validated methodology; record method/product versions and sources.
- Preserve product identifiers/versions, units, native grid/projection, temporal semantics, QA flags, nodata masks, retrieval timestamps, processing parameters, and lineage.
- Surface missing data, coverage, quality limitations, and uncertainty.
- Resampling does not create source resolution or new information.
- Distinguish observations, reanalysis, model estimates, synthetic data, and derived products.
- Distinguish correlation from causation; account for seasonality, autocorrelation, multiple testing, sample size, and assumptions where relevant.
- A catalog entry is not an implemented algorithm. Experimental metrics (including TRI) must be labeled, versioned, validated, and withheld from authoritative rankings until justified.
- Never use NASA GIBS rendered tiles as quantitative source data.
- Scientific algorithms must be independently testable and isolated from HTTP, database, storage, and UI infrastructure.

## 13. Testing, Dependencies, and Security

Prefer deterministic tests, explicit fixtures, meaningful assertions, and isolated external services. For new business logic, scientific algorithms, security-sensitive behavior, and critical bug fixes, use TDD where practical: define behavior, add a test that fails for the intended reason, implement the smallest correct change, rerun regression checks, then refactor. If strict TDD is impractical, explain why and provide equivalent verification.

Use checks appropriate to the affected component. Common commands:

- Root: `make test`, `make lint`, `make frontend-typecheck`, `make frontend-build`.
- Core: `make backend-test`, `make backend-lint`.
- Frontend: `make frontend-test`, `make frontend-lint`, `make frontend-typecheck`, `make frontend-build`.
- Contracts: `make contracts`.
- GHS: follow commands in `backend/services/geospatial_harmonization/README.md` (`uv run pytest`, Ruff, and mypy as applicable).

Verification boundaries:

- Root `make test` currently covers Core and frontend tests; it does not automatically run GHS tests.
- GHS PostgreSQL locking integration tests require `GHS_TEST_POSTGRES_URL`; report them skipped/not run when no test database is available.
- Do not claim CI passed when no applicable workflow was found or run.
- Never claim a test/build/linter/type check/migration/live integration passed unless it was actually executed and inspected.
- Never weaken checks or security controls merely to obtain a green result; fix the cause or request approval for an exception.

Dependency and security rules:

- Inspect manifests/lockfiles and verify compatibility before adding or upgrading dependencies. Use `uv` for Python and `pnpm` for frontend; never hand-edit lockfiles.
- Add the smallest necessary dependency set and explain why existing capabilities are insufficient.
- Never commit secrets, tokens, credentials, private keys, or real user data. Follow the repository's `.env*` ignore policy and ADR-0001; do not commit environment files.
- Validate external input. Preserve OAuth state validation, redirect sanitization, authentication/authorization, CORS/cookie policy, SSRF controls, and storage access restrictions.
- Follow third-party licenses and report material unresolved security advisories.
- Do not add infrastructure (for example PostGIS, DuckDB, TiTiler, Caddy, Redis, Kafka, RabbitMQ, Kubernetes, or additional services) just because it appears in target architecture. Require a concrete need and owner approval. Preserve existing GHS Docker support.

## 14. Definition of Done and Reporting

An increment is **ready for review** only when its scope is implemented or gaps are disclosed, architecture/contracts are respected, pre-existing owner changes are preserved, relevant checks are run and honestly reported, generated files/docs are updated where needed, and the complete diff is reviewed. It must remain uncommitted while awaiting owner approval.

A task is **delivered** only after all required increments have been approved, committed, and pushed to the active branch, unless the owner explicitly chooses another stopping point.

Final report:

- Implemented functionality and deliberately deferred work.
- Active branch and whether it is `main` or `feat/*`.
- Ordered commits created during the task (hash, Conventional Commit message, actual timestamp), if any.
- Changed files and added/deleted source-code line counts; generated/lock/binary changes separately.
- Verification commands and actual results, including skipped/unavailable checks.
- Architecture, ADR, overview, API contract, and migration impact.
- Push status and any remaining uncommitted changes, clearly marked as awaiting review where applicable.

**Final principle: build TERRA as a scientifically trustworthy, reproducible, secure, and maintainable system. Preserve the difference between what exists today and what the architecture intends to build next.**
