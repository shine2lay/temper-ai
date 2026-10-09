import type { FullConfig } from '@playwright/test';

/**
 * Global setup of playwright.config.ts: no run without a server named.
 *
 * Many specs start runs on the server they reach (startSmokeRun), so there is
 * no default address: on the box, localhost:8420 is the live temper, where
 * they never run. playwright.server-free.config.ts names its own address, the
 * static build, so it passes here.
 */
export default function requireBaseURL(config: FullConfig): void {
  if (config.projects.every((project) => project.use.baseURL)) return;
  throw new Error(
    'TEMPER_E2E_BASE_URL is not set, and these specs start runs on the server they reach. ' +
      'For the specs that need no server: npx playwright test -c playwright.server-free.config.ts',
  );
}
