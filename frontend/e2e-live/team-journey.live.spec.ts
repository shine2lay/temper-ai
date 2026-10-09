/**
 * The Team page journey (e2e/team-journey.ts) against a live Temper with Team
 * on. Run by hand, never in the gate (the
 * default config's testDir is ./e2e):
 *
 *   cd frontend && TEAM_JOURNEY_BASE_URL=http://127.0.0.1:<port> \
 *     TEAM_JOURNEY_SHOTS_DIR=<private folder> npx playwright test -c playwright.live.config.ts
 *
 * README.md, "Team journey (live)", lists every variable. This file installs
 * no route and makes no API call: what the journey does is click, as the
 * owner would. It starts one project (unless TEAM_JOURNEY_STOP_AFTER stops it
 * sooner), so run it only against temper-dev, when a project start is
 * approved and none is running.
 */
import { test } from '@playwright/test';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { privateFolder } from '../e2e/privateFolder';
import { JOURNEY_STEPS, teamJourney, type JourneyForm, type JourneyStep } from '../e2e/team-journey';

const env = process.env;
const README = 'frontend/README.md, "Team journey (live)"';

function settings() {
  const baseURL = env.TEAM_JOURNEY_BASE_URL?.trim();
  if (!baseURL) throw new Error(`Set TEAM_JOURNEY_BASE_URL to the Temper to drive (${README}).`);

  // The config refused it already if it isn't private; asked again here, before any page opens.
  // This is the real folder (links followed): everything is written there.
  const shotsDir = privateFolder(env.TEAM_JOURNEY_SHOTS_DIR);

  let ownerKey: string | undefined;
  const keyFile = env.TEAM_JOURNEY_OWNER_KEY_FILE?.trim();
  if (keyFile) {
    if (!existsSync(keyFile) || !statSync(keyFile).isFile()) throw new Error('TEAM_JOURNEY_OWNER_KEY_FILE names no file.');
    ownerKey = readFileSync(keyFile, 'utf8').trim();
    if (!ownerKey) throw new Error('TEAM_JOURNEY_OWNER_KEY_FILE is empty.');
  }

  const timeoutS = Number(env.TEAM_JOURNEY_TIMEOUT_S?.trim() || 300);
  if (!Number.isFinite(timeoutS) || timeoutS <= 0) throw new Error('TEAM_JOURNEY_TIMEOUT_S must be a number of seconds above 0.');

  const stop = env.TEAM_JOURNEY_STOP_AFTER?.trim() || undefined;
  if (stop && !(JOURNEY_STEPS as readonly string[]).includes(stop)) {
    throw new Error(`TEAM_JOURNEY_STOP_AFTER must be one of ${JOURNEY_STEPS.join(', ')}.`);
  }

  const form: JourneyForm = {};
  const roles = (env.TEAM_JOURNEY_ROLES ?? '')
    .split(',')
    .map((r) => r.trim())
    .filter(Boolean);
  if (roles.length) form.roles = roles;
  if (env.TEAM_JOURNEY_PAUSE?.trim()) form.pause = env.TEAM_JOURNEY_PAUSE.trim();
  if (env.TEAM_JOURNEY_WHO_CAN_MESSAGE?.trim()) form.whoCanMessage = env.TEAM_JOURNEY_WHO_CAN_MESSAGE.trim();
  if (env.TEAM_JOURNEY_PROJECT?.trim()) form.project = env.TEAM_JOURNEY_PROJECT.trim();

  return {
    baseURL,
    shotsDir,
    ownerKey,
    timeoutS,
    stopAfter: stop as JourneyStep | undefined,
    answer: env.TEAM_JOURNEY_ANSWER?.trim() || undefined,
    form,
  };
}

test('Team page journey (live)', async ({ browser }) => {
  const s = settings();
  // Five waits on the team at most, plus the looks.
  test.setTimeout((s.timeoutS * 6 + 600) * 1000);
  await teamJourney(browser, {
    mode: 'live',
    baseURL: s.baseURL,
    tag: `journey-${new Date().toISOString()}`,
    timeoutMs: s.timeoutS * 1000,
    shotsDir: s.shotsDir,
    reportPath: path.join(s.shotsDir, 'report.json'),
    answer: s.answer,
    form: s.form,
    stopAfter: s.stopAfter,
    ownerKey: s.ownerKey,
  });
});
