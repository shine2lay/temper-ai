import { defineConfig } from '@playwright/test';

/**
 * End-to-end tests run against a real temper server serving the built
 * dashboard (the FastAPI app mounts `frontend/dist` at /app).
 *
 * Point them somewhere with TEMPER_E2E_BASE_URL; the default matches
 * `temper serve` / `docker compose up`:
 *
 *   npm run build && TEMPER_E2E_BASE_URL=http://localhost:8420 npm run e2e
 *
 * The specs create the data they need through the API using the zero-cost
 * `smoke_test` workflow, so they need no API key and no pre-seeded database.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'list' : 'line',
  use: {
    baseURL: process.env.TEMPER_E2E_BASE_URL ?? 'http://localhost:8420',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
