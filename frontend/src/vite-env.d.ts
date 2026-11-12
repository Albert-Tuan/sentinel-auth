/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * The API origin. Empty means "use the Vite dev proxy" (same-origin).
   * A full origin means "direct cross-origin requests"; the backend's
   * CORS allow-list must then include this origin.
   */
  readonly VITE_API_BASE_URL?: string
  /** The backend the Vite dev proxy forwards to (development only). */
  readonly VITE_DEV_API_TARGET?: string
  /** The port the Vite dev server listens on. */
  readonly VITE_DEV_PORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
