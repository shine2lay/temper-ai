import { defineConfig } from '@playwright/test';

/**
 * End-to-end tests run against a real temper server serving the built
 * dashboard (the FastAPI app mounts `frontend/dist` at /app).
 *
 * TEMPER_E2E_BASE_URL says which. It has no default, and without it the run
 * stops before any test (e2e/requireBaseURL.ts): these specs start runs on the
 * server they reach, and on the box localhost:8420 is the live temper, where
 * they never run.
 *
 * The specs create the data they need through the API using the zero-cost
 * `smoke_test` workflow, so they need no API key and no pre-seeded database.
 *
 * GitHub starts no temper for them (AGENTS.md rule 15: no copy of Temper but
 * the live one). It runs only the specs that need none, listed in
 * e2e/server-free.txt, with playwright.server-free.config.ts.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'list' : 'line',
  globalSetup: './e2e/requireBaseURL.ts',
  use: {
    baseURL: process.env.TEMPER_E2E_BASE_URL,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
