# ADR 0001 — Bootstrap stack, pinned versions, and known trade-offs

- **Status:** Accepted
- **Date:** 2026-11-14
- **Scope:** Initial technical foundation of the repository (`frontend/`, `backend/core/`).

## Context

The repository was bootstrapped with React 19 + Vite + MapLibre GL JS + deck.gl +
Zustand + TanStack Query + Apache ECharts on the frontend, and Python + uv +
FastAPI + Granian + Pydantic Settings on the backend. Version choices had to
balance the mandated stack against current ecosystem compatibility.

## Decisions

1. **Frontend stack pins.** React 19.3, Vite 8 (Rolldown-based), MapLibre GL JS
   **5.24** (v5 is a project requirement), deck.gl **9.4** via
   `@deck.gl/maplibre`'s `MapLibreOverlay` (officially supports MapLibre
   v4.5.1/v5/v6), Zustand 5, TanStack Query 5, Apache ECharts 6, ESLint 10 flat
   config. Frontend code follows FSD-lite layering
   (`app → pages → widgets → features → entities → shared`).

2. **TypeScript 6.0.x (not 7).** The newest `typescript-eslint` release (8.72.x)
   declares support for `typescript < 6.1.0`; TypeScript 7 is outside that
   range. Strict mode is enabled in all tsconfig projects.

3. **MapLibre v5 worker mechanism.** MapLibre GL JS v5 embeds its map worker in
   the main bundle and loads it through a Blob URL, so no
   `setWorkerUrl`/`?worker&url` wiring is needed. That mechanism belongs to
   MapLibre v6, where the worker is a separate ESM file.

4. **Known security trade-off (MapLibre v5).**
   [GHSA-jrc7-96c5-q579](https://github.com/advisories/GHSA-jrc7-96c5-q579)
   (critical, XSS sanitizer bypass in `DOM.sanitize()`) affects every MapLibre
   GL JS ≤ 6.4.0, including the pinned 5.24.1; the patched line is 6.4.1+.
   Because the project mandates MapLibre GL JS 5, the advisory is accepted for
   the bootstrap phase. `@deck.gl/maplibre` officially supports MapLibre v6, so
   lifting the pin is a one-line version change in `frontend/package.json` plus
   re-verifying the worker setup described above.

5. **Backend package layout.** `backend/core` contains a single `terra` package
   (`terra.main`, `terra.config`, `terra.api`, `terra.modules`,
   `terra.infrastructure`) following the mandatory module structure. Health
   endpoints are kept separate from business routes, and the versioned surface
   mounts under the configurable `API_V1_PREFIX` (`/api/v1` by default).

6. **pydantic-settings list parsing.** List-typed settings (`CORS_ORIGINS`,
   `CORS_ALLOW_METHODS`, `CORS_ALLOW_HEADERS`) use `Annotated[..., NoDecode]`
   with a validator that accepts JSON arrays or comma-separated strings.
   Without `NoDecode`, pydantic-settings JSON-decodes the raw env string before
   validators run and crashes on plain CSV values (verified during bootstrap).

7. **No persistence or integrations yet.** SQLAlchemy/PostgreSQL/PostGIS wiring
   is deferred until the first business module requires persistence, at which
   point repository contracts (Protocol) go in the Domain Layer and SQLAlchemy
   implementations in the Infrastructure Layer. No Docker/Kubernetes/Kafka, no
   scientific algorithms, no external API integrations, and no synthetic data
   ship with the bootstrap.

8. **No environment files in version control.** Every `.env*` file — including
   examples — is gitignored and stays out of history. Variable documentation
   lives in code instead of a committed example file: `terra/config.py` lists
   the backend variables with defaults, `frontend/src/vite-env.d.ts` types the
   `VITE_*` variables.

## Consequences

- Frontend and backend install, run, test, and build independently; both are
  configured from environment variables (root `.env` for Vite,
  `backend/core/.env` or the process environment for the backend), and no
  environment file is ever committed.
- The MapLibre v5 security advisory must be revisited before production use
  (see Decision 4).
- TypeScript should be revisited when `typescript-eslint` supports TS 7.
- Dependency lockfiles (`frontend/package-lock.json`,
  `backend/core/uv.lock`) are committed and define reproducible installs.
