/// <reference types="vitest/config" />
import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8420',
      '/ws': { target: 'ws://localhost:8420', ws: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    css: false,
    // `e2e/` holds Playwright specs (run with `npx playwright test`, which
    // needs @playwright/test installed). Vitest picking them up made
    // `vitest run` fail before it ran a single unit test.
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
    // A few tests are deliberately heavy: bigRunLive.test.tsx renders a run
    // of 63 agents, replays its whole event stream and mounts a panel for
    // every one of them. Locally that is 2-3s, which fit under vitest's 5s
    // default with little to spare; GitHub's 2-core runners are about three
    // times slower, so the same tests took 5.4-8.5s and were killed
    // mid-assertion. The budget was the default, not a decision about how
    // fast the dashboard must be. 30s is that decision, and nothing that
    // takes half a minute is healthy either.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
})
