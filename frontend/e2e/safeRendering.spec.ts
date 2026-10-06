/**
 * Agent output on the dashboard stays text, and showing it fetches nothing.
 *
 * Every surface that shows content gets the same inert, made-up probes
 * (src/__tests__/safeRenderingFixtures.ts) in a fresh, sealed browser
 * context (safeRenderingHarness.ts). After the content shows, the page may
 * hold no tripwire attribute, no custom element and no element that loads
 * anything, and the browser may have tried no request because of it.
 * Then the ordinary behaviour: links, placeholders, markdown, code, JSON,
 * copy and accessibility.
 *
 * Nothing here talks to a server: every /api read is answered in the test,
 * the websocket is faked, everything else is aborted. Run it against a
 * built dashboard served by `vite preview`:
 *
 *   npm run build && npx vite preview --port 5181 --strictPort &
 *   TEMPER_E2E_BASE_URL=http://127.0.0.1:5181 npx playwright test e2e/safeRendering.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {
  CODE_GENERIC_LINE,
  CODE_MARKUP_LINES,
  CODE_ORDINARY_LINES,
  CODE_PROBE,
  DISPLAY_PROBE_DOC,
  MARKER,
  SMART_PROBE_DOC,
} from '../src/__tests__/safeRenderingFixtures';
import { expectNothingLoaded, recordAttempts, sendEvent, settle } from './safeRenderingHarness';
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

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

/* ---------- the tripwire, surface by surface ---------- */

test.describe('tripwire (run page)', () => {
  test('agent card output', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([
      { name: 'markdown_card', output: SMART_PROBE_DOC },
      { name: 'code_card', output: CODE_PROBE },
    ]));
    try {
      const page = sealed.page;
      for (let i = 0; i < 2; i++) await page.getByText('▸ OUT').first().click();
      await expect(page.getByText(MARKER)).toHaveCount(2);
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
      await expect.soft(page.locator('.react-flow__node').getByText(CODE_MARKUP_LINES[0], { exact: true })).toBeVisible();
    } finally {
      await sealed.close();
    }
  });

  test('big view: output read as markdown', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', output: SMART_PROBE_DOC }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'writer');
      const body = await openOut(page);
      await expect(body.getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('big view: script read as code', async ({ browser }) => {
    const script = [MARKER, ...CODE_MARKUP_LINES, CODE_GENERIC_LINE].join('\n');
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer' }, { name: 'collector', script }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'collector');
      const fold = await openFold(page, 'script');
      await expect(fold.getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
      await expect.soft(fold.getByText(CODE_GENERIC_LINE, { exact: true })).toBeVisible();
    } finally {
      await sealed.close();
    }
  });

  test('big view: reasoning (markdown)', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', reasoning: DISPLAY_PROBE_DOC }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'writer');
      const fold = await openFold(page, 'reasoning');
      await expect(fold.getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('big view: thinking (markdown)', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', thinking: DISPLAY_PROBE_DOC }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'writer');
      const fold = await openFold(page, 'thinking');
      await expect(fold.getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('live panel: story view', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', response: DISPLAY_PROBE_DOC }]));
    try {
      const page = sealed.page;
      await expect(page.getByTestId('story-text').getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('big view: finished stream', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer' }]));
    try {
      const page = sealed.page;
      await sendEvent(page, finishedStream(DISPLAY_PROBE_DOC));
      await openAgent(page, 'writer');
      const fold = await openFold(page, 'stream');
      await expect(fold.getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('gate: upstream output and option preview', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', status: 'running' }], 'running'), {
      gates: [gateWith(DISPLAY_PROBE_DOC, DISPLAY_PROBE_DOC)],
    });
    try {
      const page = sealed.page;
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByText(MARKER)).toHaveCount(1);
      await dialog.getByRole('button', { name: /First way/ }).click();
      await expect(dialog.getByText(MARKER)).toHaveCount(2);
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });
});

test.describe('tripwire (Team run page)', () => {
  test('goal', async ({ browser }) => {
    const sealed = await openTeamRun(browser, withGoal(fixture('run-running'), DISPLAY_PROBE_DOC));
    try {
      const page = sealed.page;
      await expect(page.locator(GOAL).getByText(MARKER)).toBeAttached();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('outcome summary', async ({ browser }) => {
    const sealed = await openTeamRun(browser, withOutcome(fixture('run-done'), DISPLAY_PROBE_DOC));
    try {
      const page = sealed.page;
      await expect(page.locator(OUTCOME).getByText(MARKER)).toBeAttached();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });

  test('opened timeline message', async ({ browser }) => {
    const sealed = await openTeamRun(browser, fixture('run-running'), {
      message: withMessage(fixture('message-read'), DISPLAY_PROBE_DOC),
    });
    try {
      const page = sealed.page;
      await page.getByRole('button', { name: /^Open/ }).first().click();
      await expect(page.locator('div[data-message-body]').getByText(MARKER)).toBeVisible();
      await settle(page);
      recordAttempts(test.info(), sealed);
      await expectNothingLoaded(sealed);
    } finally {
      await sealed.close();
    }
  });
});

/* ---------- ordinary behaviour ---------- */

/** Tab forward until the focused element is a link with these words; false if never. */
async function tabTo(page: Page, words: string, max = 120): Promise<boolean> {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab');
    const hit = await page.evaluate(
      (w) => document.activeElement?.tagName === 'A' && document.activeElement.textContent?.trim() === w,
      words,
    );
    if (hit) return true;
  }
  return false;
}

test.describe('regression', () => {
  test('an https link: Tab reaches it, Enter follows it in the same tab with no referrer', async ({ browser }) => {
    const sealed = await openTeamRun(browser, withGoal(fixture('run-running'), `${MARKER}\n\n[external docs](https://docs.invalid/guide)`));
    try {
      const page = sealed.page;
      const link = page.locator(GOAL).getByRole('link', { name: 'external docs' });
      await expect(link).toHaveAttribute('href', 'https://docs.invalid/guide');
      await settle(page);
      expect.soft(await link.getAttribute('rel'), 'rel').toBe('noopener noreferrer');
      expect.soft(await link.getAttribute('referrerpolicy'), 'referrerpolicy').toBe('no-referrer');
      expect.soft(await link.getAttribute('target'), 'target').toBeNull();
      expect(await tabTo(page, 'external docs'), 'Tab reaches the link').toBe(true);
      sealed.deliberate();
      const pages = sealed.context.pages().length;
      const nav = page.waitForRequest((r) => r.isNavigationRequest() && r.url().startsWith('https://docs.invalid/'));
      await page.keyboard.press('Enter');
      const req = await nav;
      expect.soft(req.frame() === page.mainFrame(), 'same tab').toBe(true);
      expect.soft(sealed.context.pages().length, 'no new tab').toBe(pages);
      expect.soft((await req.allHeaders())['referer'], 'no referrer sent').toBeUndefined();
      recordAttempts(test.info(), sealed);
      expect.soft(sealed.contentAttempts(), 'request attempts caused by showing content').toBe(0);
    } finally {
      await sealed.close();
    }
  });

  test('an image placeholder: Tab reaches it, Enter opens a new tab with no referrer', async ({ browser }) => {
    const sealed = await openTeamRun(browser, withGoal(fixture('run-running'), `${MARKER}\n\n![inline probe](https://images.invalid/probe-inline.png)`));
    try {
      const page = sealed.page;
      await expect(page.locator(GOAL).getByText(MARKER)).toBeAttached();
      await settle(page);
      recordAttempts(test.info(), sealed);
      expect.soft(sealed.contentAttempts(), 'request attempts caused by showing content').toBe(0);
      const words = 'Image: inline probe (images.invalid)';
      expect(await tabTo(page, words), 'Tab reaches the placeholder link').toBe(true);
      sealed.deliberate();
      const popup = sealed.context.waitForEvent('page');
      await page.keyboard.press('Enter');
      const tab = await popup;
      const req = sealed.deliberateRequests().find((r) => r.url().startsWith('https://images.invalid/'))
        ?? (await tab.waitForEvent('request', (r) => r.url().startsWith('https://images.invalid/')));
      expect.soft(req.frame().page() === tab, 'opens in a new tab').toBe(true);
      expect.soft((await req.allHeaders())['referer'], 'no referrer sent').toBeUndefined();
      expect.soft(await tab.evaluate(() => window.opener), 'no opener').toBeNull();
      test.info().annotations.length = 0;
      recordAttempts(test.info(), sealed);
    } finally {
      await sealed.close();
    }
  });

  test('markdown keeps headings, lists, emphasis and code', async ({ browser }) => {
    const doc = ['# Findings heading', '', 'One **strong word** and an *emphasised word* and `inline code`.', '', '- first item', '- second item'].join('\n');
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', output: doc, reasoning: doc }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'writer');
      for (const box of [await openOut(page), await openFold(page, 'reasoning')]) {
        await expect.soft(box.getByRole('heading', { name: 'Findings heading' })).toBeVisible();
        await expect.soft(box.locator('strong', { hasText: 'strong word' })).toBeVisible();
        await expect.soft(box.locator('em', { hasText: 'emphasised word' })).toBeVisible();
        await expect.soft(box.locator('code', { hasText: 'inline code' })).toBeVisible();
        await expect.soft(box.getByRole('listitem')).toHaveText(['first item', 'second item']);
      }
      recordAttempts(test.info(), sealed);
      expect.soft(sealed.contentAttempts()).toBe(0);
    } finally {
      await sealed.close();
    }
  });

  test('code keeps line numbers and its three colours', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer' }, { name: 'collector', script: CODE_ORDINARY_LINES.join('\n') }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'collector');
      const fold = await openFold(page, 'script');
      const code = fold.getByTestId('bv-code');
      await expect.soft(code.locator('.text-violet-400.font-medium', { hasText: /^const$/ })).toBeVisible();
      await expect.soft(code.locator('.text-emerald-400', { hasText: '"hello"' })).toBeVisible();
      await expect.soft(code.locator('.text-temper-text-dim.italic', { hasText: '// say hi' })).toBeVisible();
      await expect.soft(code.locator('.text-temper-text-dim.italic', { hasText: '# entry point' })).toBeVisible();
      for (const n of ['1', '2', '3']) await expect.soft(code.getByText(n, { exact: true }).first()).toBeVisible();
      recordAttempts(test.info(), sealed);
      expect.soft(sealed.contentAttempts()).toBe(0);
    } finally {
      await sealed.close();
    }
  });

  test('JSON stays a tree of keys and values', async ({ browser }) => {
    const json = JSON.stringify({ verdict: 'split the key', steps: ['edit', 'test'] });
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', output: json }]));
    try {
      const page = sealed.page;
      await openAgent(page, 'writer');
      const body = await openOut(page);
      await expect.soft(body.getByText('verdict', { exact: false }).first()).toBeVisible();
      await expect.soft(body.getByText('split the key', { exact: false }).first()).toBeVisible();
      await expect.soft(body.getByText('edit', { exact: false }).first()).toBeVisible();
      recordAttempts(test.info(), sealed);
      expect.soft(sealed.contentAttempts()).toBe(0);
    } finally {
      await sealed.close();
    }
  });

  test('the copy button copies the raw text', async ({ browser }) => {
    const doc = `# Copy me\n\n${MARKER} With [a link](https://docs.invalid/guide) and <x-probe>text</x-probe>.`;
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer', output: doc }]));
    try {
      const page = sealed.page;
      await page.evaluate(() => {
        const w = window as unknown as { __copied?: string };
        Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: { writeText: async (t: string) => { w.__copied = t; } },
        });
      });
      await openAgent(page, 'writer');
      const body = await openOut(page);
      await body.getByRole('button', { name: 'Copy to clipboard' }).first().click({ force: true });
      await expect.poll(() => page.evaluate(() => (window as unknown as { __copied?: string }).__copied)).toBe(doc);
      recordAttempts(test.info(), sealed);
      expect.soft(sealed.contentAttempts()).toBe(0);
    } finally {
      await sealed.close();
    }
  });

  test('axe finds nothing on the content surfaces, light and dark', async ({ browser }) => {
    const doc = ['# Findings heading', '', `${MARKER} See [external docs](https://docs.invalid/guide) and [the run list](/app/runs).`, '', '- first item', '- second item', '', '```', 'const greeting = "hello"; // say hi', '```'].join('\n');
    let attempts = 0;
    for (const theme of ['dark', 'light'] as const) {
      const run = await sealedRun(browser, runSnapshot([{ name: 'writer', output: doc, reasoning: doc }]), { theme });
      try {
        const page = run.page;
        await openAgent(page, 'writer');
        await openOut(page);
        await openFold(page, 'reasoning');
        const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).include('[data-testid="bv-out-body"]').include('[data-testid="bv-fold-reasoning"]').analyze();
        expect.soft(result.violations.map((v) => `${theme} run: ${v.id}`)).toEqual([]);
        attempts += run.contentAttempts();
      } finally {
        await run.close();
      }
      const team = await openTeamRun(browser, withGoal(fixture('run-running'), doc), { theme });
      try {
        const page = team.page;
        await expect(page.locator(GOAL).getByText(MARKER)).toBeAttached();
        const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).include(GOAL).analyze();
        expect.soft(result.violations.map((v) => `${theme} team: ${v.id}`)).toEqual([]);
        attempts += team.contentAttempts();
      } finally {
        await team.close();
      }
    }
    test.info().annotations.push({ type: 'content-request-attempts', description: String(attempts) });
    expect.soft(attempts).toBe(0);
  });
});

/* ---------- the tripwire itself ---------- */

test.describe('tripwire control', () => {
  test('an image the test adds itself is counted and aborted', async ({ browser }) => {
    const sealed = await sealedRun(browser, runSnapshot([{ name: 'writer' }]));
    try {
      const page = sealed.page;
      await settle(page);
      const before = sealed.contentAttempts();
      await page.evaluate(() => {
        const img = document.createElement('img');
        img.src = 'https://images.invalid/control.png';
        img.alt = '';
        document.body.append(img);
      });
      await expect.poll(() => sealed.contentAttempts()).toBe(before + 1);
      expect(before, 'the page alone tries nothing').toBe(0);
      test.info().annotations.push({ type: 'control-request-attempts', description: String(sealed.contentAttempts()) });
    } finally {
      await sealed.close();
    }
  });
});
