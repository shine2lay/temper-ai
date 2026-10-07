import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { privateFolder } from './e2e/privateFolder';

/**
 * The Team page journey against a live Temper with Team on (temper's
 * practice-run rig), run by hand:
 *
 *   TEAM_JOURNEY_BASE_URL=http://127.0.0.1:<port> TEAM_JOURNEY_SHOTS_DIR=<private folder> \
 *     npx playwright test -c playwright.live.config.ts
 *
 * README.md, "Team journey (live)", has every variable. The gate never runs
 * it: the default config's testDir is ./e2e. No trace, screenshot or video of
 * Playwright's own: a trace would keep the requests' headers, the owner's key
 * among them. The journey takes its own shots into TEAM_JOURNEY_SHOTS_DIR, and
 * Playwright's notes on a failure (they hold the live page's text) go there
 * too, in playwright-output/, never into a checkout.
 */
// Refused here, before Playwright starts or writes anything: a folder that is
// unset, relative, or really inside a git checkout (links followed). This is
// the real folder, the one everything is written to.
const shots = privateFolder(process.env.TEAM_JOURNEY_SHOTS_DIR);

export default defineConfig({
  testDir: './e2e-live',
  outputDir: path.join(shots, 'playwright-output'),
  workers: 1,
  retries: 0,
  // The spec sets its own, from TEAM_JOURNEY_TIMEOUT_S.
  timeout: 0,
  expect: { timeout: 15_000 },
  reporter: 'line',
  use: {
    baseURL: process.env.TEAM_JOURNEY_BASE_URL,
    viewport: { width: 1440, height: 900 },
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
