# ==============================================================================
# PROJECT TERRA — Frontend Development Container Image
# Provides Vite development server with proxy routing for local Compose stack.
# ==============================================================================

FROM node:22-bookworm-slim

# Enable corepack and activate exact pnpm version specified in packageManager (12.19.0)
RUN corepack enable && corepack prepare pnpm@12.19.0 --activate

WORKDIR /app/frontend

# Copy package manifests for deterministic dependency caching
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# Install frontend dependencies using frozen lockfile
RUN pnpm install --frozen-lockfile

# Copy frontend source files
COPY frontend/ ./

EXPOSE 5173

# Listen on all container interfaces so Docker port mapping reaches host
CMD ["pnpm", "exec", "vite", "--host", "0.0.0.0", "--port", "5173"]
