import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
    // The live-backend integration suite has its own config
    // (vitest.integration.config.ts) and must not run in the hermetic
    // unit-test pass.
    //
    // The Playwright suite must not run here either: the default
    // `include` glob is `**/*.{test,spec}.?(c|m)[jt]s?(x)`, which
    // matches `e2e/*.spec.ts`.  Playwright's `test.describe()` cannot
    // be called from inside Vitest — it reports "Playwright Test did
    // not expect test.describe() to be called here" — so every spec
    // file would fail to load.  The browser suite has its own runner
    // (`scripts/e2e_run.sh`).
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      'src/test/integration/**',
      'e2e/**',
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.d.ts', 'src/test/**', 'src/main.tsx'],
    },
  },
})
