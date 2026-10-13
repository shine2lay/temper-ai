/// <reference types="vitest/config" />
import fs from 'fs'
import path from 'path'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The fonts are under the SIL Open Font License 1.1, which asks that the
// licence travel with them. Each licence text kept next to the fonts
// (src/assets/fonts/*.txt) is emitted unchanged, read as bytes, to
// dist/licenses/<same name>, which the server hands out at
// /app/licenses/<name>. One source, so no copy can drift from it;
// `npm run check:fonts` checks the copies byte for byte, and the fonts
// against their manifests.
function fontLicences(): Plugin {
  const fonts = path.resolve(__dirname, './src/assets/fonts')
  return {
    name: 'temper-font-licences',
    apply: 'build',
    generateBundle() {
      for (const name of fs.readdirSync(fonts).filter((f) => f.endsWith('.txt')).sort()) {
        this.emitFile({ type: 'asset', fileName: `licenses/${name}`, source: fs.readFileSync(path.join(fonts, name)) })
      }
    },
  }
}

export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss(), fontLicences()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // A crash in the browser has to name the function it happened in.
    // Minified, the run page's errors read "h is not iterable", which says
    // nothing and cost a day of guessing. Source maps are separate files the
    // browser only fetches when devtools are open, so the dashboard the user
    // downloads is not a byte bigger, and a stack trace in devtools reads in
    // our own names. (esbuild's `keepNames` would do it without devtools, but
    // it costs ~10% of the gzipped bundle, so maps it is.)
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8420',
      '/ws': { target: 'ws://localhost:8420', ws: true },
    },
  },
  // `vite preview` serves the built dashboard, which is what the browser
  // tests should judge: the dev server re-renders everything twice and skips
  // no work, so a run of eighty-eight nodes feels slow there for reasons no
  // user will ever meet. It needs the same proxy as the dev server.
  preview: {
    port: 5174,
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
    // `vitest run` fail before it ran a single unit test. `e2e-live/` holds
    // the live Team journey (playwright.live.config.ts), for the same reason.
    exclude: ['node_modules/**', 'dist/**', 'e2e/**', 'e2e-live/**'],
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
