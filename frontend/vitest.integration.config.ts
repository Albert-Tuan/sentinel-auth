import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

/**
 * Integration test configuration.
 *
 * These tests hit the LIVE FastAPI backend over real HTTP. They therefore
 * run in the `node` environment (no jsdom) and are excluded from the default
 * unit-test run, which must stay hermetic.
 *
 * The API origin comes from `VITE_API_BASE_URL` so the SAME axios client the
 * browser uses is exercised — only the origin differs.
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: 'node',
    include: ['src/test/integration/**/*.test.ts'],
    testTimeout: 30_000,
    hookTimeout: 30_000,
    fileParallelism: false,
    // Point the real axios client at the live backend. The frontend adds
    // the `/api/v1` prefix itself, so only the origin is given here.
    env: {
      VITE_API_BASE_URL: process.env.M12_API_ORIGIN ?? 'http://127.0.0.1:8000',
    },
  },
})
