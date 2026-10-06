/**
 * The camera for the safe-rendering look check (not a pass/fail test).
 *
 * Shows ordinary, made-up content on every surface and saves, per surface,
 * theme and screen size: a screenshot of the surface and its text and
 * element outline. The same spec runs against the old and the new build;
 * a separate compare step diffs the two folders.
 *
 * Skipped unless both are set:
 *   SAFE_RENDERING_CORPUS=<corpus.json>  the ordinary content, one key per surface
 *   SAFE_RENDERING_LOOK=<folder>         where the pictures and outlines go
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { test, expect, type Locator, type Page } from '@playwright/test';
import { sendEvent } from './safeRenderingHarness';
import {
  GOAL,
  OUTCOME,
  finishedStream,
  fixture,
  gateWith,
  openAgent,
  openFold,
  openOut,
  openTeamRun,
  runSnapshot,
  sealedRun,
  withGoal,
  withMessage,
  withOutcome,
} from './safeRenderingScenes';

const CORPUS = process.env.SAFE_RENDERING_CORPUS;
const OUT = process.env.SAFE_RENDERING_LOOK;

test.skip(!CORPUS || !OUT, 'look check only: set SAFE_RENDERING_CORPUS and SAFE_RENDERING_LOOK');

const corpus: Record<string, string> = CORPUS ? JSON.parse(readFileSync(CORPUS, 'utf8')) : {};
const THEMES = ['dark', 'light'] as const;
const SIZES = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
];

const unfence = (s: string) => s.replace(/^```\w*\n/, '').replace(/\n```$/, '');

async function still(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  await page.waitForTimeout(300);
}

async function keep(page: Page, box: Locator, name: string) {
  await still(page);
  mkdirSync(OUT!, { recursive: true });
  await box.screenshot({ path: path.join(OUT!, `${name}.png`), animations: 'disabled', caret: 'hide' });
  const outline = await box.evaluate((el) => {
    const tags: string[] = [];
    const walk = (n: Element, depth: number) => {
      tags.push(`${'  '.repeat(depth)}${n.tagName.toLowerCase()}${n.getAttribute('class') ? `.${n.getAttribute('class')!.split(/\s+/).length}c` : ''}`);
      for (const c of n.children) walk(c, depth + 1);
    };
    walk(el, 0);
    return { text: (el as HTMLElement).innerText, tags };
  });
  writeFileSync(path.join(OUT!, `${name}.json`), JSON.stringify(outline, null, 1));
}

type Scene = (theme: (typeof THEMES)[number], size: { width: number; height: number }, name: string) => Promise<void>;

function eachLook(title: string, scene: (browser: import('@playwright/test').Browser) => Scene) {
  test(title, async ({ browser }) => {
    test.setTimeout(240_000);
    const run = scene(browser);
    for (const theme of THEMES) for (const size of SIZES) await run(theme, size, `${title}-${theme}-${size.width}`);
  });
}

eachLook('card', (browser) => async (theme, viewport, name) => {
  const s = await sealedRun(browser, runSnapshot([{ name: 'report_card', output: corpus.cardOutput }, { name: 'code_card', output: corpus.code }]), { theme, viewport });
  try {
    // At 1024x768 the second card sits below the canvas: send the click to the row itself.
    for (let i = 0; i < 2; i++) await s.page.getByText('▸ OUT').first().dispatchEvent('click');
    await expect(s.page.getByText('▾ OUT')).toHaveCount(2);
    await keep(s.page, s.page.locator('.react-flow__node').filter({ hasText: 'report_card' }).last(), name);
  } finally {
    await s.close();
  }
});

// cardOutput again here: the card shows only its first 200 px, the big view shows all of it.
for (const key of ['bigOutput', 'cardOutput', 'json', 'text', 'codeTs'] as const) {
  eachLook(`out-${key}`, (browser) => async (theme, viewport, name) => {
    const s = await sealedRun(browser, runSnapshot([{ name: 'writer', output: corpus[key] }]), { theme, viewport });
    try {
      await openAgent(s.page, 'writer');
      await keep(s.page, await openOut(s.page), name);
    } finally {
      await s.close();
    }
  });
}

eachLook('system', (browser) => async (theme, viewport, name) => {
  const s = await sealedRun(browser, runSnapshot([{ name: 'writer', systemPrompt: corpus.systemPrompt }]), { theme, viewport });
  try {
    await openAgent(s.page, 'writer');
    await keep(s.page, await openFold(s.page, 'system'), name);
  } finally {
    await s.close();
  }
});

eachLook('script', (browser) => async (theme, viewport, name) => {
  const s = await sealedRun(browser, runSnapshot([{ name: 'writer' }, { name: 'collector', script: unfence(corpus.code) }]), { theme, viewport });
  try {
    await openAgent(s.page, 'collector');
    await keep(s.page, await openFold(s.page, 'script'), name);
  } finally {
    await s.close();
  }
});

for (const key of ['reasoning', 'thinking'] as const) {
  eachLook(key, (browser) => async (theme, viewport, name) => {
    const s = await sealedRun(browser, runSnapshot([{ name: 'writer', [key]: corpus[key] }]), { theme, viewport });
    try {
      await openAgent(s.page, 'writer');
      await keep(s.page, await openFold(s.page, key), name);
    } finally {
      await s.close();
    }
  });
}

eachLook('story', (browser) => async (theme, viewport, name) => {
  const s = await sealedRun(browser, runSnapshot([{ name: 'writer', response: corpus.story }]), { theme, viewport });
  try {
    const text = s.page.getByTestId('story-text').first();
    await expect(text).toBeVisible();
    await keep(s.page, text, name);
  } finally {
    await s.close();
  }
});

eachLook('stream', (browser) => async (theme, viewport, name) => {
  const s = await sealedRun(browser, runSnapshot([{ name: 'writer' }]), { theme, viewport });
  try {
    await sendEvent(s.page, finishedStream(corpus.stream));
    await openAgent(s.page, 'writer');
    await keep(s.page, await openFold(s.page, 'stream'), name);
  } finally {
    await s.close();
  }
});

eachLook('gate', (browser) => async (theme, viewport, name) => {
  const s = await sealedRun(browser, runSnapshot([{ name: 'writer', status: 'running' }], 'running'), {
    gates: [gateWith(corpus.gate, corpus.preview)],
    theme,
    viewport,
  });
  try {
    const dialog = s.page.getByRole('dialog');
    await dialog.getByRole('button', { name: /First way/ }).click();
    await keep(s.page, dialog, name);
  } finally {
    await s.close();
  }
});

eachLook('goal', (browser) => async (theme, viewport, name) => {
  const s = await openTeamRun(browser, withGoal(fixture('run-running'), corpus.goal), { theme, viewport });
  try {
    await keep(s.page, s.page.locator(GOAL), name);
  } finally {
    await s.close();
  }
});

eachLook('outcome', (browser) => async (theme, viewport, name) => {
  const s = await openTeamRun(browser, withOutcome(fixture('run-done'), corpus.outcome), { theme, viewport });
  try {
    await keep(s.page, s.page.locator(OUTCOME), name);
  } finally {
    await s.close();
  }
});

eachLook('message', (browser) => async (theme, viewport, name) => {
  const s = await openTeamRun(browser, fixture('run-running'), { message: withMessage(fixture('message-read'), corpus.message), theme, viewport });
  try {
    await s.page.getByRole('button', { name: /^Open/ }).first().click();
    const body = s.page.locator('div[data-message-body]');
    await expect(body).toBeVisible();
    await keep(s.page, body, name);
  } finally {
    await s.close();
  }
});
