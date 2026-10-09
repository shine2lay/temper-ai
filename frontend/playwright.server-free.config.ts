import { defineConfig } from '@playwright/test';
import { readFileSync } from 'node:fs';
import base from './playwright.config';

/**
 * The browser tests GitHub runs (the e2e job, the nightly repeat), with no
 * temper behind them. AGENTS.md rule 15 allows no copy of Temper but the live
 * one, GitHub's included, and these tests never run against the live one.
 *
 * Only the spec files listed in e2e/server-free.txt run: ones that answer
 * every API call themselves. A test in a listed file that does need a server
 * is tagged @needs-server and left out. The pages are this commit's own build,
 * served by scripts/e2e_static_server.py, which answers every /api and /ws
 * call with a 503: a test that leans on a server fails loudly instead of
 * writing to one. Not `vite preview`: its proxy sends /api and /ws to
 * localhost:8420, and on the box that is the live temper.
 *
 *   npm run build && npx playwright test -c playwright.server-free.config.ts
 */
const PORT = Number(process.env.TEMPER_E2E_STATIC_PORT ?? 4317);
const STATIC = `http://127.0.0.1:${PORT}`;

// Some helpers take the address from the environment, not from this config, and fall
// back to localhost:8420 (e2e/safeRenderingScenes.ts): on the box that is the live
// temper, and on GitHub nothing. Whatever the shell says, they get the static build too.
process.env.TEMPER_E2E_BASE_URL = STATIC;

export const SERVER_FREE_SPECS = readFileSync(new URL('./e2e/server-free.txt', import.meta.url), 'utf8')
  .split('\n')
  .map((line) => line.replace(/#.*/, '').trim())
  .filter(Boolean);

export default defineConfig({
  ...base,
  // An empty list matches nothing: run with --pass-with-no-tests, or not at all.
  testMatch: SERVER_FREE_SPECS,
  grepInvert: /@needs-server/,
  use: { ...base.use, baseURL: STATIC },
  webServer: {
    command: `python3 ../scripts/e2e_static_server.py --port ${PORT} --dist dist`,
    url: `${STATIC}/app/`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
