#!/usr/bin/env bash
# ==============================================================================
# PROJECT TERRA — Cloudflare Pages Build Script
#
# Builds the React 19 / Vite frontend SPA for deployment on Cloudflare Pages.
# Handles monorepo prerequisites: Node.js, pnpm 12.19.0, Python 3.13, uv,
# backend OpenAPI contract generation, and Vite static compilation.
#
# Cloudflare Pages Build Configuration:
# - Root Directory: (Repository root `/`)
# - Build Command: bash deploy/containerization/cloudflare-pages-build.sh
# - Build Output Directory: frontend/dist
# ==============================================================================

set -euo pipefail

echo "=========================================================="
echo " PROJECT TERRA — CLOUDFLARE PAGES BUILD PIPELINE"
echo "=========================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

echo "[INFO] Repository root resolved to: ${REPO_ROOT}"

# ------------------------------------------------------------------------------
# 1. Verify Node.js
# ------------------------------------------------------------------------------
if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] Node.js is required but not found in PATH." >&2
  exit 1
fi
echo "[INFO] Node.js version: $(node --version)"

# ------------------------------------------------------------------------------
# 2. Activate or Install required pnpm (12.19.0)
# ------------------------------------------------------------------------------
REQUIRED_PNPM_VERSION="12.19.0"
if ! command -v pnpm >/dev/null 2>&1; then
  echo "[INFO] pnpm command not found. Activating via Corepack..."
  if command -v corepack >/dev/null 2>&1; then
    corepack enable
    corepack prepare "pnpm@${REQUIRED_PNPM_VERSION}" --activate
  else
    echo "[INFO] Corepack not found; installing pnpm globally via npm..."
    npm install -g "pnpm@${REQUIRED_PNPM_VERSION}"
  fi
else
  CURRENT_PNPM="$(pnpm --version)"
  echo "[INFO] Found pnpm version: ${CURRENT_PNPM}"
  if [[ "${CURRENT_PNPM}" != "${REQUIRED_PNPM_VERSION}" ]]; then
    echo "[INFO] Switching to required pnpm version: ${REQUIRED_PNPM_VERSION}"
    if command -v corepack >/dev/null 2>&1; then
      corepack enable
      corepack prepare "pnpm@${REQUIRED_PNPM_VERSION}" --activate
    fi
  fi
fi
echo "[INFO] Active pnpm version: $(pnpm --version)"

# ------------------------------------------------------------------------------
# 3. Ensure uv is available
# ------------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "[INFO] uv command not found in PATH. Checking ~/.local/bin/uv..."
  if [[ -x "${HOME}/.local/bin/uv" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
  else
    echo "[INFO] Downloading and installing uv standalone binary..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
fi
echo "[INFO] Active uv version: $(uv --version)"

# ------------------------------------------------------------------------------
# 4. Ensure Python 3.13 is available
# ------------------------------------------------------------------------------
echo "[INFO] Ensuring Python 3.13 runtime is available via uv..."
uv python install 3.13

# ------------------------------------------------------------------------------
# 5. Synchronize backend/core dependencies for openapi_export
# ------------------------------------------------------------------------------
echo "[INFO] Syncing backend/core dependencies for contract generation..."
(
  cd "${REPO_ROOT}/backend/core"
  uv sync --locked --no-dev
)

# ------------------------------------------------------------------------------
# 6. Install frontend dependencies with frozen lockfile
# ------------------------------------------------------------------------------
echo "[INFO] Installing frontend dependencies with frozen lockfile..."
(
  cd "${REPO_ROOT}/frontend"
  pnpm install --frozen-lockfile
)

# ------------------------------------------------------------------------------
# 7. Execute Contract Generation and Frontend Production Build
# ------------------------------------------------------------------------------
echo "[INFO] Running contract generation and Vite production build..."
(
  cd "${REPO_ROOT}/frontend"
  # `pnpm build` triggers `prebuild` (generate-contracts.mjs) then `tsc -b && vite build`
  pnpm build
)

# ------------------------------------------------------------------------------
# 8. Configure Cloudflare Pages SPA Routing Fallback
# ------------------------------------------------------------------------------
echo "[INFO] Generating Cloudflare Pages SPA fallback rule (_redirects)..."
cat << 'EOF' > "${REPO_ROOT}/frontend/dist/_redirects"
/*    /index.html   200
EOF

# ------------------------------------------------------------------------------
# 9. Validate Output Artifacts
# ------------------------------------------------------------------------------
if [[ -f "${REPO_ROOT}/frontend/dist/index.html" && -f "${REPO_ROOT}/frontend/dist/_redirects" ]]; then
  echo "=========================================================="
  echo " [SUCCESS] Cloudflare Pages build completed successfully!"
  echo " Output ready in frontend/dist/"
  echo "=========================================================="
else
  echo "[ERROR] Build failed: Expected artifacts in frontend/dist/ were not produced." >&2
  exit 1
fi
