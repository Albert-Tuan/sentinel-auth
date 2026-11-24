import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

/**
 * Sentinel Auth frontend — Vite configuration.
 *
 * Development connection mode (pick ONE, do not configure both):
 *
 *   A. Vite proxy (default, recommended)
 *      `VITE_API_BASE_URL` is left EMPTY -> the axios baseURL is "/api" and
 *      the dev server proxies /api -> VITE_DEV_API_TARGET. The browser sees a
 *      same-origin request, so CORS is never exercised in development.
 *
 *   B. Direct CORS
 *      `VITE_API_BASE_URL=http://localhost:8000` -> the browser calls the
 *      API cross-origin. The backend's `CORS_ALLOWED_ORIGINS` MUST then list
 *      the Vite origin (http://localhost:5173 by default).
 *
 * The proxy is only registered when mode A is active, so the two
 * configurations can never conflict.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const apiBaseUrl = (env.VITE_API_BASE_URL ?? '').trim()
  const devApiTarget = (env.VITE_DEV_API_TARGET ?? 'http://localhost:8000').trim()

  // Mode A: no explicit base URL -> same-origin via the dev proxy.
  const useProxy = apiBaseUrl === ''

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: Number(env.VITE_DEV_PORT ?? 5173),
      strictPort: true,
      ...(useProxy
        ? {
            proxy: {
              '/api': {
                target: devApiTarget,
                changeOrigin: true,
                secure: false,
              },
              // Health probes are served at the root, not under /api.
              '/health': { target: devApiTarget, changeOrigin: true, secure: false },
              '/ready': { target: devApiTarget, changeOrigin: true, secure: false },
            },
          }
        : {}),
    },
    build: {
      outDir: 'dist',
      sourcemap: mode !== 'production',
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            query: ['@tanstack/react-query'],
          },
        },
      },
    },
  }
})
