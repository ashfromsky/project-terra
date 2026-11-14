/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the TERRA core API, without a trailing slash. */
  readonly VITE_API_BASE_URL?: string
  /** URL of a MapLibre style JSON (see .env.example at the repository root). */
  readonly VITE_MAP_STYLE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
